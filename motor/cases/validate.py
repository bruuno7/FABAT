"""Valida casos contra el formato de `motor/INTERFACES.md` y los enums de `motor/contracts.py`.

`validate_case(case)` devuelve la lista de errores (vacía = válido). No depende del simulador.
"""
from __future__ import annotations

import json
import re
from typing import Any

from motor.contracts import Channel, Family

from .taxonomy import (
    DEMO_EXCLUDED_TYPES, DEMO_FORBIDDEN_WORDS, INFO_QUALITIES, PERTURBATIONS, PHASES, RESOURCE_KINDS, RESOURCE_STATES,
    RESOURCES, RULE_VERBS, SHOW_PHASES, TAXONOMY, WEATHERS, WORLD_EFFECTS, ZONES, phase_at,
)

FAMILIES = {f.value for f in Family}
CHANNELS = {c.value for c in Channel}
LANGS = {"es", "en", "fr", "de", "pt"}
REPORT_KEYS = {"channel", "source", "lang", "text", "zone_hint", "truth_incident"}  # campos de contracts.Report
INCIDENT_KEYS = {"id", "family", "type", "zone", "severity", "deadline", "needs"}
ZONE_STATES = {"open", "restricted", "closed"}
ZONE_FLAGS = {"power", "water_l", "structure_ok", "shade"}
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# Campos obligatorios de cada efecto `world` (además de `kind`). La duración se llama `n`, como en el simulador
# (que también entiende `ticks` y `duration`); sin ella, `zone_inflow` y `transport_cut` no acabarían nunca.
EFFECT_FIELDS: dict[str, tuple[str, ...]] = {
    "resource_offline": ("resource",), "resource_online": ("resource",), "resource_no_answer": ("resource", "n"),
    "resource_rejects": ("resource",), "zone_state": ("zone", "state"), "zone_inflow": ("zone", "per_min", "n"),
    "zone_flag": ("zone", "flag", "value"), "weather": (), "comms_down": ("channel", "n"),
    "incident": ("incident",), "transport_cut": ("n",),
}
DURATION_ALIASES = ("n", "ticks", "duration")


def _check_reports(reports: Any, where: str, errors: list[str], incident_ids: set[str]) -> None:
    if not isinstance(reports, list) or not reports:
        errors.append(f"{where}: sin avisos")
        return
    for k, r in enumerate(reports):
        extra = set(r) - REPORT_KEYS
        if extra:
            errors.append(f"{where}.reports[{k}]: claves fuera del contrato Report: {sorted(extra)}")
        if r.get("channel") not in CHANNELS:
            errors.append(f"{where}.reports[{k}]: canal desconocido {r.get('channel')!r}")
        if r.get("lang") not in LANGS:
            errors.append(f"{where}.reports[{k}]: idioma desconocido {r.get('lang')!r}")
        if not isinstance(r.get("text"), str) or not r["text"].strip():
            errors.append(f"{where}.reports[{k}]: texto vacío")
        if "{" in r.get("text", "") or "}" in r.get("text", ""):
            errors.append(f"{where}.reports[{k}]: hueco de plantilla sin rellenar")
        if r.get("zone_hint") is not None and r["zone_hint"] not in ZONES:
            errors.append(f"{where}.reports[{k}]: zone_hint desconocida {r['zone_hint']!r}")
        if r.get("truth_incident") is not None and r["truth_incident"] not in incident_ids:
            errors.append(f"{where}.reports[{k}]: truth_incident {r['truth_incident']!r} no existe")


def _check_incident(inc: Any, t: int, duration: int, where: str, errors: list[str]) -> None:
    if not isinstance(inc, dict):
        errors.append(f"{where}: incidente ausente")
        return
    missing = INCIDENT_KEYS - set(inc)
    if missing:
        errors.append(f"{where}: faltan claves {sorted(missing)}")
        return
    if inc["family"] not in FAMILIES:
        errors.append(f"{where}: familia desconocida {inc['family']!r}")
    ty = TAXONOMY.get(inc["type"])
    if ty is None or ty.mode != "incident":
        errors.append(f"{where}: tipo fuera de la taxonomía {inc['type']!r}")
    elif ty.family.value != inc["family"]:
        errors.append(f"{where}: {inc['type']} es de la familia {ty.family.value}, no {inc['family']}")
    if inc["zone"] is not None and inc["zone"] not in ZONES:
        errors.append(f"{where}: zona desconocida {inc['zone']!r}")
    if not (isinstance(inc["severity"], int) and 1 <= inc["severity"] <= 10):
        errors.append(f"{where}: severidad fuera de 1..10")
    if inc["deadline"] is not None and not (t < inc["deadline"] <= duration):
        errors.append(f"{where}: deadline {inc['deadline']} fuera de ({t}, {duration}]")
    if not inc["needs"]:
        errors.append(f"{where}: needs vacío")
    for kind, n in inc["needs"].items():
        if kind not in RESOURCE_KINDS or not (isinstance(n, int) and n > 0):
            errors.append(f"{where}: necesidad inválida {kind}={n!r}")


def _check_effect(eff: Any, t: int, duration: int, where: str, errors: list[str], incident_ids: set[str]) -> None:
    if not isinstance(eff, dict) or eff.get("kind") not in WORLD_EFFECTS:
        errors.append(f"{where}: efecto world no admitido {eff.get('kind') if isinstance(eff, dict) else eff!r}")
        return
    kind = eff["kind"]
    for f in EFFECT_FIELDS[kind]:
        if f == "n" and any(a in eff for a in DURATION_ALIASES):
            continue
        if f not in eff:
            errors.append(f"{where}: a {kind} le falta {f!r}")
    if "resource" in eff and eff["resource"] not in RESOURCES:
        errors.append(f"{where}: recurso desconocido {eff['resource']!r}")
    if "zone" in eff and eff["zone"] not in ZONES:
        errors.append(f"{where}: zona desconocida {eff['zone']!r}")
    if kind == "zone_state" and eff.get("state") not in ZONE_STATES:
        errors.append(f"{where}: estado de zona desconocido {eff.get('state')!r}")
    if kind == "zone_flag" and eff.get("flag") not in ZONE_FLAGS:
        errors.append(f"{where}: flag de zona desconocido {eff.get('flag')!r}")
    if kind == "comms_down" and eff.get("channel") not in CHANNELS:
        errors.append(f"{where}: canal desconocido {eff.get('channel')!r}")
    if "minutes" in eff:
        errors.append(f"{where}: `minutes` no lo entiende el simulador; la duración es `n`")
    for f in ("n", "ticks", "duration", "per_min"):
        if f in eff and not (isinstance(eff[f], int) and eff[f] > 0):
            errors.append(f"{where}: {f} debe ser un entero positivo")
    if kind == "incident":
        _check_incident(eff.get("incident"), t, duration, f"{where}.incident", errors)
        _check_reports(eff.get("reports"), where, errors, incident_ids)


def _incident_ids(case: dict[str, Any]) -> list[str]:
    ids = []
    for ev in case.get("events", []):
        if not isinstance(ev, dict):
            continue
        body = ev.get("incident") if ev.get("kind") == "incident" else (ev.get("effect") or {}).get("incident")
        if isinstance(body, dict) and "id" in body:
            ids.append(body["id"])
    return ids


def validate_case(case: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("id", "seed", "split", "day", "start_hhmm", "duration_min", "families", "difficulty", "initial", "events", "expected"):
        if key not in case:
            errors.append(f"falta la clave {key!r}")
    if errors:
        return errors
    if case["split"] not in ("train", "heldout", "demo"):
        errors.append(f"split desconocido {case['split']!r}")
    if case["day"] not in (1, 2, 3):
        errors.append(f"día fuera de 1..3: {case['day']!r}")
    if not _HHMM.match(str(case["start_hhmm"])):
        errors.append(f"start_hhmm inválido {case['start_hhmm']!r}")
    duration = case["duration_min"]
    if not (isinstance(duration, int) and 10 <= duration <= 240):
        errors.append(f"duration_min inválida {duration!r}")
        return errors
    if case["difficulty"] not in (1, 2, 3, 4, 5):
        errors.append(f"dificultad fuera de 1..5: {case['difficulty']!r}")
    if not case["families"] or any(f not in FAMILIES for f in case["families"]):
        errors.append(f"familias inválidas {case['families']!r}")

    initial = case["initial"]
    for z, occ in initial.get("occupancy", {}).items():
        if z not in ZONES or not (isinstance(occ, int) and occ >= 0):
            errors.append(f"initial.occupancy: entrada inválida {z}={occ!r}")
    for r in initial.get("resources_offline", []):
        if r not in RESOURCES:
            errors.append(f"initial.resources_offline: recurso desconocido {r!r}")
    for r, t in initial.get("shift_ends", {}).items():
        if r not in RESOURCES or not (isinstance(t, int) and 0 <= t < duration):
            errors.append(f"initial.shift_ends: entrada inválida {r}={t!r}")

    ids = _incident_ids(case)
    if len(ids) != len(set(ids)):
        errors.append("ids de incidente repetidos")
    id_set = set(ids)
    last_t = -1
    for k, ev in enumerate(case["events"]):
        where = f"events[{k}]"
        t = ev.get("t")
        if not (isinstance(t, int) and 0 <= t < duration):
            errors.append(f"{where}: t={t!r} fuera de [0, {duration})")
            continue
        if t < last_t:
            errors.append(f"{where}: eventos desordenados en el tiempo")
        last_t = t
        kind = ev.get("kind")
        if kind == "incident":
            _check_incident(ev.get("incident"), t, duration, where, errors)
            _check_reports(ev.get("reports"), where, errors, id_set)
        elif kind == "report_only":
            _check_reports(ev.get("reports"), where, errors, id_set)
        elif kind == "world":
            _check_effect(ev.get("effect"), t, duration, where, errors, id_set)
        else:
            errors.append(f"{where}: kind desconocido {kind!r}")
        if "cond" in ev and ev["cond"].get("unless_resolved") not in id_set:
            errors.append(f"{where}: cond apunta a un incidente inexistente")
    if not ids:
        errors.append("el caso no tiene ningún incidente verdadero")

    expected = case["expected"]
    for side in ("must", "must_not"):
        if not isinstance(expected.get(side), list):
            errors.append(f"expected.{side} debe ser una lista")
            continue
        for rule in expected[side]:
            if not isinstance(rule, str) or rule.split()[0] not in RULE_VERBS:
                errors.append(f"expected.{side}: regla con verbo desconocido {rule!r}")
            elif "{" in rule:
                errors.append(f"expected.{side}: hueco sin rellenar en {rule!r}")
            else:
                m = re.search(r"\bi\d+\b", rule)
                if m and m.group(0) not in id_set:
                    errors.append(f"expected.{side}: {rule!r} cita un incidente inexistente")

    meta = case.get("meta")
    if meta is not None:
        checks = (("phase", PHASES), ("weather", WEATHERS), ("info_quality", INFO_QUALITIES), ("resource_state", RESOURCE_STATES))
        for key, allowed in checks:
            if meta.get(key) not in allowed:
                errors.append(f"meta.{key} inválido {meta.get(key)!r}")
        for p in meta.get("perturbations", []):
            if p not in PERTURBATIONS:
                errors.append(f"meta.perturbations: desconocida {p!r}")
        for t in meta.get("types", []):
            if t not in TAXONOMY:
                errors.append(f"meta.types: tipo fuera de la taxonomía {t!r}")
        fams = {TAXONOMY[t].family.value for t in meta.get("types", []) if t in TAXONOMY}
        if fams != set(case["families"]):
            errors.append(f"families {case['families']} no coincide con las de meta.types {sorted(fams)}")
    errors += _check_program(case, id_set)
    errors += _check_priority_and_load(case)
    if case["split"] == "demo":
        errors += _check_demo_content(case)
    return errors


def _bodies(case: dict[str, Any]) -> list[tuple[int, dict[str, Any], bool]]:
    out = []
    for ev in case["events"]:
        body = ev.get("incident") if ev.get("kind") == "incident" else (ev.get("effect") or {}).get("incident")
        if isinstance(body, dict) and isinstance(ev.get("t"), int):
            out.append((ev["t"], body, "cond" in ev))
    return out


def _check_program(case: dict[str, Any], id_set: set[str]) -> list[str]:
    """Coherencia con el programa de `festival.json`: la fase declarada es la del reloj del simulador, ningún
    incidente nace con el recinto cerrado y solo se exige `stop_show` si en ese minuto hay concierto."""
    errors = []
    day, start = case["day"], case["start_hhmm"]
    real = phase_at(day, start)
    declared = (case.get("meta") or {}).get("phase")
    if declared is not None and declared != real:
        errors.append(f"meta.phase dice {declared!r} pero el programa da {real!r} el día {day} a las {start}")
    if real == "closed":
        errors.append(f"el caso empieza con el recinto cerrado (día {day}, {start})")
    when = {}
    for t, body, _ in _bodies(case):
        when[body.get("id")] = phase_at(day, start, t)
        if when[body.get("id")] == "closed":
            errors.append(f"el incidente {body.get('id')} nace en t={t} con el recinto ya cerrado")
    for rule in case["expected"].get("must", []):
        m = re.search(r"\bi\d+\b", rule) if isinstance(rule, str) else None
        if m and rule.startswith("stop_show") and when.get(m.group(0)) not in SHOW_PHASES:
            errors.append(f"expected.must exige {rule!r} en fase {when.get(m.group(0))!r}: no hay concierto que parar")
    return errors


def _check_priority_and_load(case: dict[str, Any]) -> list[str]:
    errors = []
    sure = {body["id"] for _, body, cond in _bodies(case) if not cond and "id" in body}
    exp = case["expected"]
    if "priority" in exp:
        if set(exp["priority"]) != sure or len(exp["priority"]) != len(sure):
            errors.append("expected.priority debe listar una vez cada incidente seguro")
        if [i for tier in exp.get("priority_tiers", []) for i in tier] != exp["priority"]:
            errors.append("expected.priority_tiers no coincide con expected.priority")
        if not set(exp.get("may_wait", [])) <= sure:
            errors.append("expected.may_wait cita incidentes inexistentes")
    meta = case.get("meta") or {}
    if meta.get("load") is not None:
        if "priority" not in exp:
            errors.append("un caso de carga necesita expected.priority")
        if meta.get("max_concurrent", 0) < meta["load"]:
            errors.append(f"carga {meta['load']} pero solo {meta.get('max_concurrent')} incidentes activos a la vez")
        if not meta.get("scarce_kinds"):
            errors.append("caso de carga sin ningún tipo de recurso escaso")
        for k, item in enumerate(meta.get("surprise_menu", [])):  # golpes que inyecta una persona: mismo formato
            _check_effect(item.get("effect"), 0, case["duration_min"], f"meta.surprise_menu[{k}]", errors, set())
        st = meta.get("surprise_t")
        if st is not None and not (isinstance(st, int) and 0 <= st < case["duration_min"]):
            errors.append(f"meta.surprise_t fuera del caso: {st!r}")
    return errors


def _check_demo_content(case: dict[str, Any]) -> list[str]:
    """Decisión D4 del consejo: en demo no hay violencia sexual, amenaza de bomba, armas, menores en peligro
    ni atrapados; ni como tipo de incidente ni en el texto de ningún aviso."""
    errors = []
    for _, body, _ in _bodies(case):
        if body.get("type") in DEMO_EXCLUDED_TYPES:
            errors.append(f"demo no puede contener el tipo {body['type']}")
    for ev in case["events"]:
        for r in ev.get("reports") or (ev.get("effect") or {}).get("reports") or []:
            m = DEMO_FORBIDDEN_WORDS.search(r.get("text", ""))
            if m:
                errors.append(f"demo: aviso con contenido vetado ({m.group(0)!r})")
    return errors


def validate_file(path: str) -> tuple[int, list[tuple[str, list[str]]]]:
    """Devuelve (casos leídos, [(id, errores)] solo de los inválidos). Comprueba ids únicos."""
    bad: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    n = 0
    with open(path, encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            if not line.strip():
                continue
            n += 1
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                bad.append((f"línea {line_no}", [f"JSON inválido: {exc}"]))
                continue
            errs = validate_case(case)
            if case.get("id") in seen:
                errs.append("id de caso repetido en el fichero")
            seen.add(case.get("id"))
            if errs:
                bad.append((str(case.get("id", f"línea {line_no}")), errs))
    return n, bad
