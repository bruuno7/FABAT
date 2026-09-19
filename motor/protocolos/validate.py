"""Valida `protocolos.json` contra el esquema que usa el agente de recogida.

AVISO: los protocolos son instrucciones de apoyo para una SIMULACIÓN de hackathon. No sustituyen al
112 ni a la formación; en un despliegue real las valida la dirección sanitaria del evento.

Uso (desde la raíz del repo):
    python3 -m motor.protocolos.validate            # valida motor/protocolos/protocolos.json
    python3 -m motor.protocolos.validate otro.json
Solo biblioteca estándar. `validate(doc) -> list[str]` devuelve la lista de errores (vacía = válido).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PATH = Path(__file__).with_name("protocolos.json")

MAX_SLOTS = 5
MAX_QUESTION_WORDS = 16
MAX_STEP_WORDS = 30
MIN_PROTOCOLS = 22
LANGS = ("es", "en")
SLOT_TYPES = {"bool", "number", "enum", "text", "zone_point"}
FAMILIES = {"crowd", "medical", "weather", "aggression", "supply", "infra", "resource", "info", "external"}
NEED_KINDS = {"medical", "ambulance", "security", "volunteer", "logistics", "tech"}
NOTIFY_ROLES = {"medical_lead", "security_lead", "violet_point", "coordinator", "gates", "production",
                "stage_manager", "health_authority", "all_leads"}
EXTERNAL_KINDS = {"112", "ambulance", "fire", "police", "transport"}
THEN_REQUIRED = {"life_risk": bool, "severity_min": int, "needs": dict, "instruction": str, "dispatch_now": bool}
THEN_OPTIONAL = {"switch_to", "mando_type_hint"}
UNKNOWN = "unknown"


def words(text: str) -> int:
    return len(text.split())


def _bilingual(obj: Any, where: str, errs: list[str], max_words: int | None = None) -> None:
    if not isinstance(obj, dict):
        errs.append(f"{where}: debe ser un objeto con 'es' y 'en'")
        return
    for lang in LANGS:
        val = obj.get(lang)
        if not isinstance(val, str) or not val.strip():
            errs.append(f"{where}: falta el texto '{lang}'")
        elif max_words is not None and words(val) > max_words:
            errs.append(f"{where}.{lang}: {words(val)} palabras (máximo {max_words}): «{val}»")


def _taxonomy_ids() -> set[str] | None:
    """Tipos de Mando, si el paquete está a mano; si no, no se comprueba `mando_type_hint`."""
    try:
        from motor.cases.taxonomy import TAXONOMY  # type: ignore
        return set(TAXONOMY)
    except Exception:
        return None


def _check_condition(cond: Any, slots: dict[str, dict], where: str, errs: list[str], before: set[str] | None = None) -> None:
    """Condición = {slot: valor | [valores] | {"gte"/"lte": n}}; todas las claves deben cumplirse."""
    if not isinstance(cond, dict):
        errs.append(f"{where}: la condición debe ser un objeto")
        return
    for sid, expected in cond.items():
        slot = slots.get(sid)
        if slot is None:
            errs.append(f"{where}: referencia al slot inexistente '{sid}'")
            continue
        if before is not None and sid not in before:
            errs.append(f"{where}: '{sid}' se pregunta después; un ask_if solo puede mirar slots anteriores")
        stype = slot.get("type")
        if isinstance(expected, dict):
            if stype != "number" or not expected or set(expected) - {"gte", "lte"} or \
                    not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in expected.values()):
                errs.append(f"{where}: {{'gte'/'lte': n}} solo vale para slots 'number' ('{sid}' es {stype})")
            continue
        for val in expected if isinstance(expected, list) else [expected]:
            if stype == "bool":
                ok = isinstance(val, bool) or val == UNKNOWN
            elif stype == "enum":
                ok = val in slot.get("options", [])
            elif stype == "number":
                ok = isinstance(val, (int, float)) and not isinstance(val, bool)
            else:
                ok = False
            if not ok:
                errs.append(f"{where}: valor {val!r} no válido para '{sid}' (tipo {stype})")


def _check_slots(p: dict, where: str, errs: list[str]) -> dict[str, dict]:
    slots = p.get("slots")
    if not isinstance(slots, list) or not slots:
        errs.append(f"{where}: 'slots' vacío")
        return {}
    if len(slots) > MAX_SLOTS:
        errs.append(f"{where}: {len(slots)} slots (máximo {MAX_SLOTS})")
    by_id: dict[str, dict] = {}
    seen_non_critical = False
    for i, s in enumerate(slots):
        w = f"{where}.slots[{i}]"
        if not isinstance(s, dict):
            errs.append(f"{w}: debe ser un objeto")
            continue
        sid = s.get("id")
        if not isinstance(sid, str) or not sid:
            errs.append(f"{w}: falta 'id'")
            continue
        w = f"{where}.slots[{sid}]"
        if sid in by_id:
            errs.append(f"{w}: id de slot repetido")
        if not isinstance(s.get("critical"), bool):
            errs.append(f"{w}: 'critical' debe ser booleano")
        elif s["critical"] and seen_non_critical:
            errs.append(f"{w}: slot crítico detrás de uno no crítico (van ordenados por criticidad)")
        elif not s["critical"]:
            seen_non_critical = True
        if s.get("type") not in SLOT_TYPES:
            errs.append(f"{w}: tipo {s.get('type')!r} no válido ({', '.join(sorted(SLOT_TYPES))})")
        opts = s.get("options")
        if s.get("type") == "enum":
            if not isinstance(opts, list) or len(opts) < 2 or len(set(opts)) != len(opts) or not all(isinstance(o, str) and o for o in opts):
                errs.append(f"{w}: un 'enum' necesita 'options' con al menos 2 valores distintos")
        elif opts is not None:
            errs.append(f"{w}: 'options' solo vale para 'enum'")
        _bilingual(s.get("question"), f"{w}.question", errs, MAX_QUESTION_WORDS)
        if "why" in s and (not isinstance(s["why"], str) or not s["why"].strip()):
            errs.append(f"{w}: 'why' vacío")
        by_id[sid] = s
    asked: set[str] = set()
    for s in slots:  # segunda pasada: los ask_if pueden nombrar cualquier slot, pero solo mirar los anteriores
        if isinstance(s, dict) and isinstance(s.get("id"), str):
            if "ask_if" in s:
                _check_condition(s["ask_if"], by_id, f"{where}.slots[{s['id']}].ask_if", errs, before=asked)
            asked.add(s["id"])
    return by_id


def _check_instructions(p: dict, where: str, errs: list[str], library: dict[str, tuple[str, str]]) -> set[str]:
    ids: set[str] = set()
    items = p.get("instructions")
    if not isinstance(items, list) or not items:
        errs.append(f"{where}: 'instructions' vacío")
        return ids
    for i, ins in enumerate(items):
        iid = ins.get("id") if isinstance(ins, dict) else None
        if not isinstance(iid, str) or not iid:
            errs.append(f"{where}.instructions[{i}]: falta 'id'")
            continue
        w = f"{where}.instructions[{iid}]"
        if iid in ids:
            errs.append(f"{w}: id de instrucción repetido")
        ids.add(iid)
        steps = ins.get("steps")
        if not isinstance(steps, dict):
            errs.append(f"{w}: falta 'steps'")
            continue
        lens = []
        for lang in LANGS:
            lst = steps.get(lang)
            if not isinstance(lst, list) or not lst or not all(isinstance(t, str) and t.strip() for t in lst):
                errs.append(f"{w}: faltan los pasos en '{lang}'")
                continue
            lens.append(len(lst))
            for t in lst:
                if words(t) > MAX_STEP_WORDS:
                    errs.append(f"{w}.{lang}: paso de {words(t)} palabras (máximo {MAX_STEP_WORDS}): «{t}»")
        if len(lens) == 2 and lens[0] != lens[1]:
            errs.append(f"{w}: distinto número de pasos en es ({lens[0]}) y en ({lens[1]})")
        if not isinstance(ins.get("source"), str) or not ins["source"].strip():
            errs.append(f"{w}: 'source' vacío")
        # una misma instrucción repetida en varios protocolos debe decir exactamente lo mismo
        canon = json.dumps(steps, sort_keys=True, ensure_ascii=False)
        prev = library.setdefault(iid, (canon, where))
        if prev[0] != canon:
            errs.append(f"{w}: mismo id que en {prev[1]} pero con otro texto")
    return ids


def _check_protocol(p: dict, where: str, errs: list[str], all_ids: set[str], taxonomy: set[str] | None,
                    library: dict[str, tuple[str, str]]) -> None:
    if p.get("family") not in FAMILIES:
        errs.append(f"{where}: familia {p.get('family')!r} no válida")
    _bilingual(p.get("label"), f"{where}.label", errs)
    if not isinstance(p.get("sensitive"), bool):
        errs.append(f"{where}: 'sensitive' debe ser booleano")

    trig = p.get("triggers")
    if not isinstance(trig, dict):
        errs.append(f"{where}: falta 'triggers'")
    else:
        for lang in LANGS:
            lst = trig.get(lang)
            if not isinstance(lst, list) or not all(isinstance(t, str) and t.strip() for t in lst):
                errs.append(f"{where}.triggers.{lang}: debe ser una lista de textos")
                continue
            if not lst and p.get("id") != "unknown":
                errs.append(f"{where}.triggers.{lang}: vacío (solo 'unknown' puede no tener disparadores)")
            for t in lst:
                if t != t.lower():
                    errs.append(f"{where}.triggers.{lang}: «{t}» debe ir en minúsculas")

    slots = _check_slots(p, where, errs)
    instr = _check_instructions(p, where, errs, library)

    flags = p.get("red_flags")
    if not isinstance(flags, list) or not flags:
        errs.append(f"{where}: 'red_flags' vacío")
        flags = []
    for i, flag in enumerate(flags):
        w = f"{where}.red_flags[{i}]"
        if not isinstance(flag, dict) or "if" not in flag or not isinstance(flag.get("then"), dict):
            errs.append(f"{w}: necesita 'if' y 'then'")
            continue
        _check_condition(flag["if"], slots, f"{w}.if", errs)
        then = flag["then"]
        for key, typ in THEN_REQUIRED.items():
            if not isinstance(then.get(key), typ) or (typ is int and isinstance(then.get(key), bool)):
                errs.append(f"{w}.then.{key}: falta o no es {typ.__name__}")
        for key in set(then) - set(THEN_REQUIRED) - THEN_OPTIONAL:
            errs.append(f"{w}.then: clave desconocida '{key}'")
        sev = then.get("severity_min")
        if isinstance(sev, int) and not 1 <= sev <= 10:
            errs.append(f"{w}.then.severity_min: {sev} fuera de 1..10")
        needs = then.get("needs")
        if isinstance(needs, dict):
            if not needs:
                errs.append(f"{w}.then.needs: vacío")
            for kind, n in needs.items():
                if kind not in NEED_KINDS or not isinstance(n, int) or isinstance(n, bool) or n < 1:
                    errs.append(f"{w}.then.needs: '{kind}: {n}' no válido")
        if isinstance(then.get("instruction"), str) and then["instruction"] not in instr:
            errs.append(f"{w}.then.instruction: '{then['instruction']}' no está en las instrucciones del protocolo")
        if then.get("life_risk") is True and then.get("dispatch_now") is not True:
            errs.append(f"{w}.then: riesgo vital sin 'dispatch_now' (nunca se retrasa el envío)")
        if "switch_to" in then and then["switch_to"] not in all_ids:
            errs.append(f"{w}.then.switch_to: protocolo inexistente '{then['switch_to']}'")
        if "mando_type_hint" in then and taxonomy is not None and then["mando_type_hint"] not in taxonomy:
            errs.append(f"{w}.then.mando_type_hint: '{then['mando_type_hint']}' no es un tipo de Mando")
        if p.get("sensitive") and then.get("instruction") == "aggression" and p.get("id") == "sexual_violence":
            errs.append(f"{w}: la instrucción 'aggression' está prohibida en violencia sexual")

    dispatch = p.get("dispatch_as_soon_as")
    if not isinstance(dispatch, list) or not dispatch:
        errs.append(f"{where}: 'dispatch_as_soon_as' vacío")
    else:
        for sid in dispatch:
            s = slots.get(sid)
            if s is None:
                errs.append(f"{where}.dispatch_as_soon_as: slot inexistente '{sid}'")
            elif not s.get("critical"):
                errs.append(f"{where}.dispatch_as_soon_as: '{sid}' no es crítico")
            elif "ask_if" in s:
                errs.append(f"{where}.dispatch_as_soon_as: '{sid}' es condicional y podría no preguntarse nunca")

    handoff = p.get("handoff")
    if not isinstance(handoff, dict):
        errs.append(f"{where}: falta 'handoff'")
    else:
        notify = handoff.get("notify")
        if not isinstance(notify, list) or not notify or set(notify) - NOTIFY_ROLES:
            errs.append(f"{where}.handoff.notify: lista no vacía de roles conocidos ({', '.join(sorted(NOTIFY_ROLES))})")
        if "external" not in handoff:
            errs.append(f"{where}.handoff: falta 'external' (puede ser null)")
        elif handoff["external"] is not None:
            ext = handoff["external"]
            if not isinstance(ext, dict) or ext.get("kind") not in EXTERNAL_KINDS:
                errs.append(f"{where}.handoff.external.kind: debe ser uno de {', '.join(sorted(EXTERNAL_KINDS))}")
            elif ext.get("requires_approval") is not True:
                errs.append(f"{where}.handoff.external: todo servicio externo exige 'requires_approval: true'")
        if p.get("sensitive") and isinstance(notify, list) and not set(notify) & {"violet_point", "security_lead"}:
            errs.append(f"{where}.handoff.notify: un protocolo sensible avisa al punto violeta o al jefe de seguridad")

    hint = p.get("mando_type_hint")
    if not isinstance(hint, str) or not hint:
        errs.append(f"{where}: falta 'mando_type_hint'")
    elif taxonomy is not None and hint not in taxonomy:
        errs.append(f"{where}.mando_type_hint: '{hint}' no es un tipo de Mando")

    sources = p.get("sources")
    if not isinstance(sources, list) or not sources or not all(isinstance(s, str) and s.strip() for s in sources):
        errs.append(f"{where}: 'sources' vacío")
    elif not any(s.startswith("http") for s in sources):
        errs.append(f"{where}.sources: hace falta al menos una URL abierta")


def _check_global(g: Any, errs: list[str]) -> None:
    if not isinstance(g, dict):
        errs.append("global: falta")
        return
    _bilingual(g.get("opening"), "global.opening", errs)
    _bilingual(g.get("reserved_handling"), "global.reserved_handling", errs)
    lq = g.get("location_questions")
    if not isinstance(lq, list) or not lq:
        errs.append("global.location_questions: vacío")
    else:
        for i, item in enumerate(lq):
            _bilingual(item, f"global.location_questions[{i}]", errs, MAX_QUESTION_WORDS)
    ns = g.get("never_say")
    if not isinstance(ns, list) or not ns:
        errs.append("global.never_say: vacío")
    else:
        for i, item in enumerate(ns):
            if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k].strip() for k in ("es", "why")):
                errs.append(f"global.never_say[{i}]: necesita 'es' y 'why'")
    sr = g.get("stop_rules")
    if not isinstance(sr, list) or not sr or not all(isinstance(r, str) and r.strip() for r in sr):
        errs.append("global.stop_rules: lista no vacía de textos")


def validate(doc: Any, taxonomy: set[str] | None = None) -> list[str]:
    errs: list[str] = []
    if not isinstance(doc, dict):
        return ["el documento debe ser un objeto JSON"]
    if doc.get("version") != 1:
        errs.append("version: debe ser 1")
    _check_global(doc.get("global"), errs)
    protocols = doc.get("protocols")
    if not isinstance(protocols, list):
        return errs + ["protocols: falta la lista"]
    if len(protocols) < MIN_PROTOCOLS:
        errs.append(f"protocols: {len(protocols)} protocolos (mínimo {MIN_PROTOCOLS})")
    ids = [p.get("id") for p in protocols if isinstance(p, dict)]
    for pid in {i for i in ids if ids.count(i) > 1}:
        errs.append(f"protocols: id repetido '{pid}'")
    if "unknown" not in ids:
        errs.append("protocols: falta el protocolo genérico 'unknown'")
    elif ids[-1] != "unknown":
        errs.append("protocols: 'unknown' debe ser el último (el orden es la prioridad de desempate)")
    if taxonomy is None:
        taxonomy = _taxonomy_ids()
    library: dict[str, tuple[str, str]] = {}
    for i, p in enumerate(protocols):
        if not isinstance(p, dict) or not isinstance(p.get("id"), str) or not p["id"]:
            errs.append(f"protocols[{i}]: falta 'id'")
            continue
        _check_protocol(p, f"protocols[{p['id']}]", errs, set(ids), taxonomy, library)
    return errs


def load(path: Path | str = PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else PATH
    doc = load(path)
    errs = validate(doc)
    if errs:
        print(f"{path}: {len(errs)} errores")
        for e in errs:
            print("  -", e)
        return 1
    protos = doc["protocols"]
    instr = {i["id"] for p in protos for i in p["instructions"]}
    print(f"{path}: válido · {len(protos)} protocolos · {sum(len(p['slots']) for p in protos)} preguntas · "
          f"{len(instr)} instrucciones · {sum(1 for p in protos if p['sensitive'])} sensibles")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
