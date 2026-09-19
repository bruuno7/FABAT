"""Suite 3 — conversación (motor.intake): guiones deterministas, northstars de diálogo."""
from __future__ import annotations

import re
from typing import Any

from motor.intake import IntakeSession, load_protocols, load_zones
from motor.intake.engine import SAMPLE_PROTOCOLS, never_patterns
from motor.mando.parser import normalize

from .common import EvalResult, fail_ex

DIAGNOSIS = re.compile(r"\b(infarto|ictus|diagn[oó]stic|es un golpe de calor|es una parada|es anafilaxia)\b", re.I)
ETA_PROMISE = re.compile(r"\b(llegan en|en \d+ minutos|eta\b|unos \d+ min)\b", re.I)
MAX_Q = 5

SCRIPTS: list[dict[str, Any]] = [
    {
        "id": "conv-panico", "name": "pánico",
        "open": ["AYUDA AYUDA HAY ALGUIEN TIRADO NO SE MUEVE NO SE MUEVE"],
        "answers": {"location": "en los baños", "breathing": "no lo sé", "responsive": "no"},
        "inject": {3: "¿es un infarto?"},
        "expect": {"no_diagnosis": True},
    },
    {
        "id": "conv-sin-ubicacion", "name": "sin ubicación",
        "open": ["un chico no respira"],
        "answers": {"location": "no lo sé", "responsive": "no"},
        "expect": {"asks_where": True},
    },
    {
        "id": "conv-parada-rcp", "name": "parada → RCP inmediata",
        "open": ["no respira, estamos en los baños"],
        "answers": {},
        "expect": {"instruction_id": "cpr", "first_turn_report": True, "rcp_now": True},
    },
    {
        "id": "conv-menor", "name": "menor perdido",
        "open": ["se ha perdido mi hijo de 6 años, estábamos en la zona de comida"],
        "answers": {"clothing": "camiseta roja", "safe": "sí"},
        "expect": {"reserved": True, "no_echo": ["hijo de 6"]},
    },
    {
        "id": "conv-asalto", "name": "agresión sexual → sin eco",
        "open": ["una chica dice que la han tocado sin su permiso en la pista"],
        "answers": {"safe": "sí"},
        "expect": {"reserved": True, "no_echo": ["tocado", "sin su permiso"]},
    },
    {
        "id": "conv-broma", "name": "broma",
        "open": ["jaja es broma no pasa nada, he visto un dragón detrás del escenario"],
        "answers": {},
        "expect": {"possible_prank": True},
    },
    {
        "id": "conv-dos", "name": "dos incidentes",
        "open": ["pelea en la puerta B y además un tío no responde en los baños"],
        "answers": {"weapon": "no", "injured": "no", "breathing": "no lo sé"},
        "expect": {"two_incidents": True},
    },
    {
        "id": "conv-en", "name": "inglés",
        "open": ["my friend is not breathing, we're by the toilets"],
        "answers": {},
        "expect": {"lang": "en", "instruction_id": "cpr"},
    },
    {
        "id": "conv-correccion", "name": "corrección posterior",
        "open": ["mi amigo no respira, estamos en los baños"],
        "inject": {2: "espera, sí respira"},
        "answers": {},
        "expect": {"first_turn_report": True},
    },
]


def _answer_for(turn, answers: dict[str, Any], lang: str) -> str | None:
    if not turn.ask:
        return None
    slot = turn.ask.get("slot") or ""
    pool = answers.get(slot)
    if pool is None:
        return "I don't know" if lang == "en" else "no lo sé"
    if isinstance(pool, list):
        return pool.pop(0) if pool else ("I don't know" if lang == "en" else "no lo sé")
    return str(pool)


def play(script: dict[str, Any]) -> dict[str, Any]:
    protocols = load_protocols(SAMPLE_PROTOCOLS)
    zones = load_zones()
    s = IntakeSession(channel="web", protocols=protocols, zones=zones, session_id=script["id"])
    answers = {k: (list(v) if isinstance(v, list) else v) for k, v in (script.get("answers") or {}).items()}
    inject = {int(k): v for k, v in (script.get("inject") or {}).items()}
    never = never_patterns((protocols.get("global") or {}).get("never_say") or [])
    allowed_ids = {ins.get("id") for p in (protocols.get("protocols") or []) for ins in (p.get("instructions") or [])}
    turns = []
    violations = []
    queue = list(script.get("open") or [])
    last = None
    for n in range(1, 12):
        if n in inject:
            text = inject[n]
        elif queue:
            text = queue.pop(0)
        elif last is None or last.done or not last.ask:
            break
        else:
            text = _answer_for(last, answers, last.lang or "es") or ("no lo sé")
        turn = s.receive(text)
        turns.append(turn)
        last = turn
        if turn.say.count("?") > 1:
            violations.append(f"turno {n}: más de una pregunta")
        said = normalize(turn.say)
        violations += [f"turno {n}: frase prohibida {x.pattern}" for x in never if x.search(said)]
        if DIAGNOSIS.search(turn.say) and "no_diagnosis" not in turn.flags:
            # la línea fija de «no diagnostico» puede citar la palabra; eso no es diagnosticar
            if "no puedo" not in said and "cannot" not in said:
                violations.append(f"turno {n}: diagnostica «{turn.say[:80]}»")
        if ETA_PROMISE.search(turn.say) and "estimaci" not in said and "estimated" not in said:
            violations.append(f"turno {n}: promete tiempo «{turn.say[:80]}»")
        if turn.instruction and turn.instruction.get("id") not in allowed_ids:
            violations.append(f"turno {n}: instrucción {turn.instruction.get('id')} fuera de lista")
    questions = getattr(s, "questions_asked", 0)
    if questions > MAX_Q:
        violations.append(f"{questions} preguntas > {MAX_Q}")
    reports = [r for t in turns for r in t.reports]
    metas = [m for t in turns for m in t.report_meta]
    instructions = [t.instruction for t in turns if t.instruction]
    flags = [f for t in turns for f in t.flags]
    return {
        "script": script["id"], "turns": turns, "violations": violations, "questions": questions,
        "reports": reports, "metas": metas, "instructions": instructions, "flags": flags,
        "says": [t.say for t in turns], "lang": (turns[-1].lang if turns else "es"),
    }


def _check_expect(script: dict[str, Any], played: dict[str, Any]) -> list[str]:
    exp = script.get("expect") or {}
    err: list[str] = []
    says = " ".join(played["says"])
    if exp.get("instruction_id"):
        ids = [i.get("id", "") for i in played["instructions"]]
        if not any(exp["instruction_id"] in i for i in ids):
            err.append(f"sin instrucción {exp['instruction_id']}: {ids}")
    if exp.get("rcp_now"):
        first = played["turns"][0] if played["turns"] else None
        if first is None or not first.instruction or "cpr" not in str(first.instruction.get("id")):
            err.append("RCP no salió en el primer turno")
    if exp.get("first_turn_report") and (not played["turns"] or not played["turns"][0].reports):
        err.append("sin Report en el primer turno")
    if exp.get("reserved"):
        if not any(m.get("reserved") for m in played["metas"]):
            err.append("no se marcó reservado")
    for word in exp.get("no_echo") or []:
        blob = " ".join([normalize(says)] + [normalize(getattr(r, "text", "")) for r in played["reports"]])
        if normalize(word) in blob:
            err.append(f"eco de «{word}»")
    if exp.get("possible_prank") and "possible_prank" not in played["flags"]:
        err.append("no marcó posible broma")
    if exp.get("two_incidents") and "two_incidents" not in played["flags"]:
        err.append("no abrió dos hilos")
    if exp.get("lang") and played.get("lang") != exp["lang"]:
        err.append(f"idioma {played.get('lang')} ≠ {exp['lang']}")
    if exp.get("asks_where"):
        asks = " ".join(t.question or "" for t in played["turns"])
        if not re.search(r"d[oó]nde|where", asks, re.I):
            err.append("no preguntó dónde")
    if exp.get("no_diagnosis") and "no_diagnosis" not in played["flags"] and any("infarto" in s.lower() for s in played["says"] if "no puedo" not in s.lower()):
        err.append("no activó no_diagnosis")
    return err


def run(rapido: bool = False) -> list[EvalResult]:
    scripts = SCRIPTS[:4] if rapido else SCRIPTS
    out: list[EvalResult] = []
    all_v: list[dict] = []
    n_inv = ok_inv = 0
    for sc in scripts:
        played = play(sc)
        errs = list(played["violations"]) + _check_expect(sc, played)
        n_inv += 1
        if played["violations"]:
            all_v.append(fail_ex(1, sc["id"], played["violations"][0]))
        else:
            ok_inv += 1
        out.append(EvalResult(
            id=sc["id"], suite="conversacion",
            description=f"Guion «{sc['name']}»: máx. 5 preguntas, una por turno, no diagnostica, no promete tiempos, instrucciones literales.",
            n=1, passed=0 if errs else 1,
            failures=[] if not errs else [fail_ex(1, sc["id"], errs[0], todos=errs[:6])],
            extra={"preguntas": played["questions"], "turnos": len(played["turns"]), "flags": played["flags"][:8]},
        ))
    out.insert(0, EvalResult(
        id="CONV-invariantes", suite="conversacion",
        description="Northstars de conversación en todos los guiones: ≤5 preguntas, una por turno, never_say, instrucción de lista.",
        n=n_inv, passed=ok_inv, failures=all_v,
        notes="Usuario simulado determinista. Conversación simulada, no dato de campo.",
    ))
    return out
