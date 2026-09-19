"""`python3 -m motor.harness day2` — ¿«aprende de interacciones pasadas» es verdad y se puede medir?

La forma es la de IDEA-bruno.md: memoria operativa de RESULTADOS OBSERVADOS → propuesta de cambio de PARÁMETROS →
aprobación de una persona → medición repitiendo la MISMA secuencia con la configuración inicial y la revisada.

  1. «Día 1»: N casos de train (semilla fija) con los parámetros de ficha (`Params.initial()`); Mando lleva enganchada
     una `OperationalMemory` que solo apunta lo que él observa. Las memorias de los N casos se suman en una.
  2. `tuning.propose(memoria)` → cambios de parámetros con valor anterior, nuevo, N y texto.
  3. Los decide un operador simulado con criterio FIJO (`tuning.simulated_operator`: aprueba si N ≥ 5) o `--approve`.
  4. «Día 2»: OTROS N casos de train, y N de heldout (nunca usados para la memoria), corridos DOS veces con exactamente
     los mismos casos y semillas: parámetros de ficha y parámetros revisados. Se compara, pareado y con IC bootstrap,
     SOLO con métricas del mundo (nada de `expected.must`).

La «capa de operación» (`ops_layer`). Los casos de `motor/cases` nacen con los depósitos llenos, una reposición de 5 min
fija, todo el mundo cogiendo el teléfono igual y sin coste por buscar a alguien en 13.000 m²: ahí no hay nada que una
jornada pueda enseñar. `ops_layer` añade a cada caso, SIN tocar su guion, lo que un recinto real tiene y el agente no
sabe de antemano (`initial.ops`, ver README de `motor/world`):
  · nivel inicial de los depósitos (sembrado por caso) → el agua se acaba o no según el calor y la gente;
  · minutos reales de reposición por punto (el norte obliga a rodear: 20–30 min; el sur 7–12);
  · quién coge el teléfono (perfil FIJO del festival: las mismas personas el día 1, el día 2 y en heldout);
  · minutos que cuesta dar con una persona en una zona amplia si no hay un punto concreto;
  · en parte de los casos, un preaviso de viento que sube o se desactiva (misma distribución los dos días).
Los dos brazos del día 2 corren la MISMA capa: lo único que cambia entre ellos son los valores de los parámetros.
ESTO ES SIMULACIÓN: el tamaño del efecto depende de esos parámetros ocultos, que hemos puesto nosotros. Lo que se
demuestra es que el circuito observar → proponer → aprobar → medir funciona y se mide limpio, no un dato de campo.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random
from typing import Any

from motor.world import load_festival

from . import metrics as M
from .runner import AgentFactory, assert_same_cases, code_fingerprint, loaded_fingerprint, run_many

FESTIVAL_SEED = 2026
WATER_START_L = (250, 1600)       # litros con que empieza cada depósito en la capa de operación
WIND_ALERT_P = 0.35               # fracción de casos (sin meteorología de viento propia) con preaviso de viento
WIND_ARRIVES_P = 0.30             # de esos, en cuántos el viento acaba subiendo a riesgo en estructuras
LOCATE_MIN_AREA = 2000.0          # m² a partir de los cuales una zona es «demasiado amplia»

# (métrica, texto, ¿menos es mejor?)
METRICS = (
    ("stockouts", "roturas de stock de agua que llegan a ocurrir (por caso)", True),
    ("dry_minutes", "minutos-punto con el depósito a cero (por caso)", True),
    ("heat_incidents", "incidentes de calor espontáneos (por caso)", True),
    ("skipped_events", "incidentes derivados que se evitan, `skipped_events` (por caso)", False),
    ("accept_min", "minutos del aviso al despacho que acaba llegando", True),
    ("dup_moved", "equipos movidos por un duplicado (por caso)", True),
    ("locate_min", "minutos buscando a la persona en zona amplia", True),
    ("time_to_first_attention", "minutos hasta la primera atención", True),
    ("critical_failed", "críticos fallidos (por caso)", True),
    ("world_score", "`world_score` (solo-mundo, 0–100)", False),
)


def festival_profile(seed: int = FESTIVAL_SEED) -> dict[str, Any]:
    """Lo que el recinto «es» y Mando no sabe: determinista por semilla, igual para todos los casos y días."""
    fest = load_festival()
    rng = random.Random(f"festival:{seed}")
    by_kind: dict[str, list[str]] = {}
    for r in fest["resources"]:
        by_kind.setdefault(r["kind"], []).append(r["id"])
    contact: dict[str, dict[str, float]] = {}
    for kind in sorted(by_kind):
        ids = sorted(by_kind[kind])
        if len(ids) < 2:
            continue            # un solo recurso de ese tipo: no hay orden que aprender
        bad = set(rng.sample(ids, 2 if len(ids) >= 4 else 1))
        for rid in ids:
            contact[rid] = {"p_no_answer": round(rng.uniform(0.35, 0.60), 2) if rid in bad else round(rng.uniform(0.01, 0.06), 2),
                            "p_reject": 0.04}
    zones = {z["id"]: [max(1, round(math.sqrt(z["area_m2"]) / 28)), round(math.sqrt(z["area_m2"]) / 13)]
             for z in fest["zones"] if z["area_m2"] >= LOCATE_MIN_AREA}
    return {"seed": seed, "resupply_min": {"water_n": [20, 30], "water_s": [7, 12]}, "contact": contact,
            "locate": {"zones": zones, "p_point": 0.8}}


def ops_layer(case: dict[str, Any], profile: dict[str, Any], day: int) -> dict[str, Any]:
    """El mismo caso con la capa de operación. No toca incidentes, avisos ni `expected`; determinista por (semilla, día)."""
    c = copy.deepcopy(case)
    rng = random.Random(f"{c.get('seed', 0)}:ops:{day}")
    c["id"] = f"{c['id']}@d{day}"
    init = c.setdefault("initial", {})
    init["ops"] = {k: profile[k] for k in ("resupply_min", "contact", "locate")}
    flags = init.setdefault("flags", {})
    for point in ("water_n", "water_s"):
        flags.setdefault(point, {}).setdefault("water_l", rng.randint(*WATER_START_L))
    windy = any((e.get("effect") or {}).get("wind_kmh") for e in c.get("events", [])) \
        or float((init.get("weather") or {}).get("wind_kmh") or 0) >= 35
    roll, t0, arrives = rng.random(), rng.randint(4, 18), rng.random() < WIND_ARRIVES_P
    t1, low, high = t0 + rng.randint(5, 14), rng.randint(41, 48), rng.randint(52, 63)
    if not windy and roll < WIND_ALERT_P and t1 < int(c.get("duration_min", 60)) - 5:
        c["events"] = sorted(c.get("events", []) + [
            {"t": t0, "kind": "world", "tag": "ops_wind", "effect": {"kind": "weather", "wind_kmh": low, "alert": "amarilla por viento"}},
            {"t": t1, "kind": "world", "tag": "ops_wind", "effect": {"kind": "weather", "wind_kmh": high, "alert": "naranja por viento"}
             if arrives else {"kind": "weather", "wind_kmh": 12, "alert": None}}], key=lambda e: e.get("t", 0))
    return c


def _hash(x: Any) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:12]


def _value(r: dict[str, Any], key: str) -> float | None:
    if r["metrics"].get("run_error"):      # un error cuenta como fallo: no aporta valor a las métricas de operación,
        return {"critical_failed": float(r["metrics"]["critical_failed"]), "world_score": 0.0}.get(key)   # pero sí a estas dos
    v = r["metrics"].get(key) if key in ("critical_failed", "world_score", "time_to_first_attention") else (r["detail"].get("ops") or {}).get(key)
    return None if v is None else float(v)


def compare_arms(initial: list[dict[str, Any]], revised: list[dict[str, Any]]) -> dict[str, Any]:
    """Revisado − inicial, pareado caso a caso. Veredicto por métrica con IC 99 % (son 10 métricas × 2 conjuntos)."""
    out: dict[str, Any] = {}
    for key, text, lower_better in METRICS:
        pairs = [(_value(a, key), _value(b, key)) for a, b in zip(revised, initial)]
        pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
        after, before = [x for x, _ in pairs], [y for _, y in pairs]
        d95, d99 = M.paired_diff(after, before, 0.95), M.paired_diff(after, before, 0.99)
        ini, rev = M.describe(before, 1000), M.describe(after, 1000)
        good = None
        if d99["n"] and d99["ci"]:
            lo, hi = d99["ci"]
            good = (hi < 0) if lower_better else (lo > 0)
            bad = (lo > 0) if lower_better else (hi < 0)
        else:
            bad = False
        overlap = None
        if ini["ci95"] and rev["ci95"]:
            overlap = not (rev["ci95"][1] < ini["ci95"][0] or rev["ci95"][0] > ini["ci95"][1])
        verdict = "MEJORA" if good else "EMPEORA" if bad else "sin evidencia de mejora"
        out[key] = {"text": text, "lower_is_better": lower_better, "n_pairs": len(pairs), "initial": ini, "revised": rev,
                    "paired_diff_95": d95, "paired_diff_99": d99, "unpaired_ci95_overlap": overlap, "verdict": verdict,
                    "totals": {"initial": round(sum(before), 2), "revised": round(sum(after), 2)}}
    return out


def _sentence(split: str, n: int, cmp: dict[str, Any]) -> str:
    better = [k for k, v in cmp.items() if v["verdict"] == "MEJORA"]
    worse = [k for k, v in cmp.items() if v["verdict"] == "EMPEORA"]

    def one(k: str) -> str:
        v = cmp[k]
        d = v["paired_diff_99"]
        return (f"{v['text']}: {v['initial']['mean']} → {v['revised']['mean']} (diferencia pareada {d['mean']:+}, IC 99 % "
                f"[{d['ci'][0]}, {d['ci'][1]}], N={v['n_pairs']}"
                + ("; ojo: los intervalos NO pareados de los dos brazos se solapan, solo vale como diferencia pareada" if v["unpaired_ci95_overlap"] else "") + ")")
    parts = []
    if better:
        parts.append("con los parámetros revisados MEJORA: " + "; ".join(one(k) for k in better))
    if worse:
        parts.append("EMPEORA: " + "; ".join(one(k) for k in worse))
    rest = [cmp[k]["text"] for k in cmp if k not in better and k not in worse]
    if rest:
        parts.append("sin evidencia de mejora en: " + "; ".join(rest))
    if not better:
        parts.insert(0, "sin evidencia de mejora")
    return f"{split} (N={n} por brazo, mismos casos y semillas): " + ". ".join(parts) + "."


def composition(cases: list[dict[str, Any]]) -> dict[str, int]:
    def has(c: dict[str, Any], what: str) -> bool:
        return what in json.dumps(c.get("events", []))
    return {"n": len(cases),
            "hot_over_32c": sum(1 for c in cases if float((c.get("initial", {}).get("weather") or {}).get("temp_c") or 0) > 32),
            "scripted_water_out": sum(1 for c in cases if has(c, '"water_out"')),
            "resource_no_answer_or_rejects": sum(1 for c in cases if has(c, "resource_no_answer") or has(c, "resource_rejects")),
            "duplicates": sum(1 for c in cases if has(c, '"duplicate"')),
            "ops_wind_alert": sum(1 for c in cases if has(c, "ops_wind")),
            "conditional_chains": sum(1 for c in cases if has(c, "unless_resolved"))}


def day2(train: list[dict[str, Any]], heldout: list[dict[str, Any]], n: int, *, workers: int | None = None,
         approve: str = "criterion", decisions: dict[str, bool] | None = None, festival_seed: int = FESTIVAL_SEED,
         reference: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    """Devuelve (resultado, artefactos). Determinista: mismos casos, mismo código → mismo resultado, byte a byte."""
    from motor.mando.memory import OperationalMemory
    from motor.mando.tuning import Params, propose, simulated_operator
    if len(train) < 2 * n or len(heldout) < n:
        raise SystemExit(f"ABORTADO: hacen falta {2 * n} casos de train (día 1 y día 2 no comparten casos) y {n} de heldout; "
                         f"hay {len(train)} y {len(heldout)}.")
    fp0 = loaded_fingerprint()
    profile = festival_profile(festival_seed)
    names = {z["id"]: z["name"] for z in load_festival()["zones"]} | {r["id"]: r["name"] for r in load_festival()["resources"]}
    d1 = [ops_layer(c, profile, 1) for c in train[:n]]
    d2 = [ops_layer(c, profile, 2) for c in train[n:2 * n]]
    he = [ops_layer(c, profile, 2) for c in heldout[:n]]
    initial = Params.initial()

    # 1 · día 1: parámetros de ficha, memoria enganchada
    runs1 = run_many(d1, AgentFactory("mando", [], params=initial.to_dict(), memory=True), workers, detail=False)
    assert_same_cases({"day1": runs1}, d1)
    parts = [r["detail"]["memory"] for r in runs1 if r.get("detail", {}).get("memory")]
    memory = OperationalMemory.merge(parts)
    _same_code(fp0, runs1, "día 1")

    # 2 y 3 · propuestas y decisión
    proposals = simulated_operator(propose(memory, initial, names), approve, decisions)
    revised = proposals.approved_params()

    # 4 · día 2 y heldout: mismos casos y semillas, dos configuraciones (y, de referencia, Mando sin parámetros)
    arms = [("initial", AgentFactory("mando", [], params=initial.to_dict())),
            ("revised", AgentFactory("mando", [], params=revised.to_dict()))]
    if reference:
        arms.append(("legacy", AgentFactory("mando", [])))
    out: dict[str, Any] = {
        "code": fp0, "n_per_arm": n, "festival_seed": festival_seed, "approve_mode": approve,
        "what": "revisado − inicial, pareado; SOLO métricas del mundo; veredicto por métrica con IC 99 % bootstrap (2.000 remuestreos)",
        "simulation_note": "Simulación. Los parámetros ocultos del recinto (festival_profile) los hemos puesto nosotros: el tamaño del "
                           "efecto depende de ellos. Se demuestra el circuito observar → proponer → aprobar → medir, no un dato de campo.",
        "festival_profile": profile,
        "day1": {"n": len(d1), "errors": sum(1 for r in runs1 if r["metrics"].get("run_error")), "case_signature": _hash(d1),
                 "composition": composition(d1), "memory_runs": memory.data["runs"], "n_by_parameter": memory.n_by_parameter(),
                 "world_score": M.describe([r["metrics"]["world_score"] for r in runs1], 1000)},
        "proposals": proposals.to_dict(),
        "params": {"initial": initial.to_dict(), "revised": revised.to_dict(),
                   "hash": {"initial": _hash(initial.to_dict()), "revised": _hash(revised.to_dict())}},
        "splits": {}}
    for split, cases in (("day2_train", d2), ("heldout", he)):
        runs = {name: run_many(cases, f, workers, detail=False) for name, f in arms}
        sig = assert_same_cases(runs, cases)        # mismos casos y semillas en todos los brazos, o se aborta
        for name, rs in runs.items():
            _same_code(fp0, rs, f"{split}/{name}")
        cmp = compare_arms(runs["initial"], runs["revised"])
        applied: dict[str, int] = {}
        for r in runs["revised"]:
            for k, v in (r["detail"].get("params_applied") or {}).items():
                applied[k] = applied.get(k, 0) + v
        out["splits"][split] = {
            "n": len(cases), "case_signature": sig, "composition": composition(cases),
            "errors": {name: sum(1 for r in rs if r["metrics"].get("run_error")) for name, rs in runs.items()},
            "unsafe_actions": {name: sum(r["metrics"]["unsafe_actions"] for r in rs) for name, rs in runs.items()},
            "critical_failed": {name: [sum(r["metrics"]["critical_failed"] for r in rs), sum(r["metrics"]["n_critical"] for r in rs)]
                                for name, rs in runs.items()},
            "params_applied_in_revised": dict(sorted(applied.items())),
            "compare": cmp, "sentence": _sentence(split, len(cases), cmp)}
        if reference:
            out["splits"][split]["initial_minus_legacy"] = {
                k: M.paired_diff([x for x, y in p], [y for x, y in p], 0.99) for k, _, _ in METRICS
                for p in [[(x, y) for x, y in ((_value(a, k), _value(b, k)) for a, b in zip(runs["initial"], runs["legacy"]))
                           if x is not None and y is not None]]}
    now = code_fingerprint()
    if now != fp0:
        raise SystemExit(f"ABORTADO en day2: la huella del código ha cambiado entre pasadas ({fp0} → {now}). No se escribe nada.")
    return out, {"memory": memory, "proposals": proposals, "revised": revised}


def _same_code(fp0: str, runs: list[dict[str, Any]], where: str) -> None:
    codes = {r.get("code") for r in runs}
    if codes != {fp0}:
        raise SystemExit(f"ABORTADO en day2 ({where}): ejecuciones con huellas de código distintas: {sorted(map(str, codes))}.")


def report_section(d: dict[str, Any]) -> list[str]:
    """Sección de `report.md`. Las frases salen del resultado: si no hay evidencia, lo dice tal cual."""
    md = [f"## Día 1 → día 2: memoria operativa y parámetros aprobados (`python3 -m motor.harness day2`, huella {d['code']})", "",
          d["simulation_note"], "",
          f"Día 1: N={d['day1']['n']} casos de train con parámetros de ficha (errores: {d['day1']['errors']}). Observaciones por parámetro: "
          f"`{json.dumps(d['day1']['n_by_parameter'], ensure_ascii=False)}`. Día 2: otros N={d['n_per_arm']} casos de train y N={d['n_per_arm']} de heldout "
          "(heldout nunca se usó para la memoria), corridos dos veces con exactamente los mismos casos y semillas.", "",
          "| Cambio | Parámetro | Antes | Después | N | Decisión | Texto |", "|---|---|---|---|---|---|---|"]
    for c in d["proposals"]["changes"]:
        new = c["new"] if not isinstance(c["new"], dict) else "orden: " + " → ".join(c["new"].get("order", []))
        md.append(f"| {c['id']} | {c['param']}{'[' + c['key'] + ']' if c['key'] else ''} | {c['old']} | {new} | {c['n']} | "
                  f"{c['status']} ({c['note']}) | {c['text']} |")
    md += ["", "Mirado y NO cambiado: " + " · ".join(u["text"] for u in d["proposals"]["unchanged"]) + ".", ""]
    for split, s in d["splits"].items():
        md += [f"### {split} (N={s['n']} por brazo; errores {s['errors']}; acciones inseguras {s['unsafe_actions']})", "",
               "| Métrica (solo mundo) | N pares | Inicial | IC 95 % | Revisado | IC 95 % | Diferencia pareada | IC 99 % | ¿IC no pareados se solapan? | Veredicto |",
               "|---|---|---|---|---|---|---|---|---|---|"]
        for k, v in s["compare"].items():
            dd = v["paired_diff_99"]
            md.append(f"| {v['text']} | {v['n_pairs']} | {v['initial']['mean']} | {v['initial']['ci95']} | {v['revised']['mean']} | {v['revised']['ci95']} | "
                      f"{dd['mean']} | {dd['ci']} | {'sí' if v['unpaired_ci95_overlap'] else 'no'} | **{v['verdict']}** |")
        md += ["", f"Veces que un parámetro aprendido cambió una decisión (brazo revisado): `{json.dumps(s['params_applied_in_revised'], ensure_ascii=False)}`.",
               "", f"**{s['sentence']}**", ""]
    return md


__all__ = ["day2", "ops_layer", "festival_profile", "compare_arms", "report_section", "METRICS"]
