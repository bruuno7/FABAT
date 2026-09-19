"""Banco del agente de recogida: 40 conversaciones escritas a mano contra un usuario simulado que contesta a lo que
se le pregunta. Mide y REPORTA TAL CUAL (con su N): protocolo acertado, slots críticos correctos, nº medio de
preguntas y en cuántos casos el primer `Report` sale en el primer turno. Es una prueba de conversación, no de campo.

    python3 -m motor.intake.bench [--cases fichero] [--real] [--json] [--verbose] [--case c07]

`--real` usa `motor/protocolos/protocolos.json` si existe. Lo esperado está escrito contra la MUESTRA: con otro fichero
los ids de protocolo y de slot pueden no coincidir, y entonces el protocolo se compara por familia.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ..contracts import Report
from ..mando.parser import HeuristicParser, normalize
from .engine import SAMPLE_PROTOCOLS, IntakeSession, Turn, load_protocols, load_zones, never_patterns

CASES = Path(__file__).resolve().parent / "bench_cases.json"
HELDOUT = Path(__file__).resolve().parent / "bench_heldout.json"
MAX_USER_TURNS = 14
# Con `--real`: los casos están escritos con los ids de la muestra; esto los traduce a los del fichero real donde hay un
# equivalente claro. Lo que no tiene equivalente (p. ej. `caller_has_child`, que allí es un enum `role`) se compara tal cual
# y fallará: la cifra con `--real` es orientativa.
REAL_SLOTS = {"location": "location_point", "breathing": "breathing_normal", "heavy_bleeding": "bleeding_heavy", "safe": "safe_now",
              "hot_skin": "skin_hot", "count": "people_count", "seizure": "still_seizing"}
REAL_INSTRUCTIONS = {"cool_now": "heat_cool_now", "recovery_position": "unconscious_breathing", "lost_child_found": "lost_child"}
FAMILY = {"person_down": "medical", "heat": "medical", "bleeding": "medical", "crowd": "crowd", "fight": "aggression",
          "violet": "aggression", "lost_child": "info", "generic": "info"}


def translate(case: dict[str, Any]) -> dict[str, Any]:
    c = json.loads(json.dumps(case))
    c["answers"] = {REAL_SLOTS.get(k, k): v for k, v in (c.get("answers") or {}).items()}
    exp = c["expect"]
    exp["slots"] = {REAL_SLOTS.get(k, k): v for k, v in (exp.get("slots") or {}).items()}
    if exp.get("instruction"):
        exp["instruction"] = REAL_INSTRUCTIONS.get(exp["instruction"], exp["instruction"])
    return c


def run_case(case: dict[str, Any], protocols: dict[str, Any], zones: dict[str, Any]) -> dict[str, Any]:
    s = IntakeSession(channel=case.get("channel", "web"), lang=case.get("lang"), zone_hint=case.get("zone_hint"),
                      profile=case.get("profile"), protocols=protocols, session_id=case["id"], zones=zones)
    queue = list(case.get("open") or [])
    answers = {k: list(v) if isinstance(v, list) else [v] for k, v in (case.get("answers") or {}).items()}
    inject = {str(k): v for k, v in (case.get("inject") or {}).items()}
    turns: list[Turn] = []
    log: list[tuple[str, str]] = []
    violations: list[str] = []
    last: Turn | None = None
    never = never_patterns((protocols.get("global") or {}).get("never_say") or [])
    for n in range(1, MAX_USER_TURNS + 1):
        if str(n) in inject:
            text = inject[str(n)]
        elif queue:
            text = queue.pop(0)
        elif last is None or last.done or not last.ask:
            break
        else:
            pool = answers.get(last.ask["slot"] or "")
            text = pool.pop(0) if pool else ("I don't know" if s.lang == "en" else "no lo sé")
        if text.startswith("@silence"):
            turn = s.silence(float(text.split()[1]) if len(text.split()) > 1 else 999)
            if turn is None:
                break
        else:
            turn = s.receive(text)
        log.append((text, turn.say))
        # invariantes de TODOS los turnos
        if turn.say.count("?") > 1:
            violations.append(f"turno {n}: dos preguntas: «{turn.say}»")
        said = normalize(turn.say)        # lo que dice el AGENTE; los pasos de una instrucción son texto literal del protocolo
        violations += [f"turno {n}: frase prohibida «{x.pattern}»" for x in never if x.search(said)]
        if turn.ask and turn.ask.get("slot") and last is not None:
            th = next((t for t in last.state["threads"] if t["id"] == turn.ask["thread"]), None)
            prev = (th or {}).get("slots", {}).get(turn.ask["slot"], {})
            if prev.get("status") == "known" and prev.get("type") != "zone_point":
                violations.append(f"turno {n}: repite una pregunta ya contestada ({turn.ask['slot']})")
        if turn.instruction:
            ids = {i["id"] for p in protocols["protocols"] for i in p.get("instructions") or []}
            if turn.instruction["id"] not in ids:
                violations.append(f"turno {n}: instrucción fuera de la lista ({turn.instruction['id']})")
        turns.append(turn)
        last = turn
    return {"session": s, "turns": turns, "log": log, "violations": violations}


def _slot(state: dict[str, Any], key: str) -> list[Any]:
    out = []
    for th in state["threads"]:
        for sid, v in th["slots"].items():
            if v["status"] != "known":
                continue
            if key.endswith(".zone") and v["type"] == "zone_point" and isinstance(v["value"], dict):
                out.append(v["value"].get("zone"))
            elif sid == key:
                out.append(v["value"])
    return out


def score(case: dict[str, Any], run: dict[str, Any], protocols: dict[str, Any], zones: dict[str, Any]) -> dict[str, Any]:
    exp, s, turns = case["expect"], run["session"], run["turns"]
    state = s.state()
    got_protocols = [t["protocol"] for t in state["threads"]]
    known_ids = {p["id"] for p in protocols["protocols"]}
    want = list(exp.get("protocol") or [])
    if want and not set(want) <= known_ids:          # otro fichero de protocolos: se compara por familia
        got_fam = [t["family"] for t in state["threads"]]
        want_fam = {FAMILY.get(w, w) for w in want}
        protocol_ok = (bool(got_fam) and got_fam[0] in want_fam) if exp.get("any_protocol") else \
            sorted(set(got_fam)) == sorted(want_fam) or (want == ["generic"] and len(got_fam) == 1)
    elif exp.get("any_protocol"):
        protocol_ok = len(got_protocols) >= 1 and got_protocols[0] in want
    else:
        protocol_ok = sorted(got_protocols) == sorted(want)
    slots_total = len(exp.get("slots") or {})
    slots_ok = sum(1 for k, v in (exp.get("slots") or {}).items() if v in _slot(state, k))
    wrong = {k: (v, _slot(state, k)) for k, v in (exp.get("slots") or {}).items() if v not in _slot(state, k)}
    first = bool(turns and turns[0].reports)
    all_reports = [r for t in turns for r in t.reports]
    metas = [m for t in turns for m in t.report_meta]
    given = [i for th in state["threads"] for i in th["instructions_given"]]
    if exp.get("instruction"):
        instruction_ok = exp["instruction"] in given
    else:
        instruction_ok = bool(exp.get("any_instruction")) or not given
    flags = {f for t in turns for f in t.flags}
    says = normalize(" ".join(t.speech() for t in turns))
    checks = {
        "protocol": protocol_ok,
        "slots": slots_ok == slots_total,
        "first_turn_report": first == bool(exp.get("first_turn_report")),
        "instruction": instruction_ok,
        "flags": set(exp.get("flags") or []) <= flags,
        "reserved": all(bool(m["reserved"]) == bool(exp.get("reserved")) for m in metas),
        "lang": exp.get("lang") in (None, s.lang),
        "no_report": (not all_reports) if exp.get("no_report") else True,
        "threads": exp.get("threads") in (None, len(state["threads"])),
        "never_in_say": not any(normalize(x) in says for x in exp.get("never_in_say") or []),
        "max_questions": s.questions_asked <= int(exp.get("max_questions", s.limits["max_questions"])),
        "invariants": not run["violations"],
    }
    mando_ok = None
    if all_reports and state["threads"] and state["threads"][0]["protocol"] not in ("generic",):
        r = all_reports[0]
        p = HeuristicParser().parse(Report(id=r.id, t=0, channel=r.channel, text=r.text, source=r.source,
                                           zone_hint=r.zone_hint), zones)
        fam = next((t["family"] for t in state["threads"] if t["id"] == r.id), state["threads"][0]["family"])
        mando_ok = str(p["family"]) == str(fam) or (fam == "info" and p["type"] == "lost_child")
    return {"id": case["id"], "level": case.get("level", ""), "checks": checks, "pass": all(checks.values()),
            "slots_ok": slots_ok, "slots_total": slots_total, "wrong_slots": wrong, "questions": s.questions_asked,
            "first_turn": first, "first_turn_expected": bool(exp.get("first_turn_report")), "got_protocols": got_protocols,
            "given": given, "violations": run["violations"], "reports": len(all_reports), "mando_family_ok": mando_ok,
            "turns": len(turns)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m motor.intake.bench")
    ap.add_argument("--cases", default=str(CASES))
    ap.add_argument("--real", action="store_true", help="usar motor/protocolos/protocolos.json si existe")
    ap.add_argument("--heldout", action="store_true", help="la reserva (bench_heldout.json) en vez del banco de desarrollo")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true", help="imprime las conversaciones que fallan")
    ap.add_argument("--case", default=None)
    args = ap.parse_args(argv)
    data = json.loads(Path(HELDOUT if args.heldout else args.cases).read_text(encoding="utf-8"))
    protocols = load_protocols() if args.real else load_protocols(SAMPLE_PROTOCOLS)
    zones = load_zones()
    cases = [translate(c) if args.real else c for c in data["cases"] if args.case in (None, c["id"])]
    results, runs = [], {}
    for c in cases:
        run = run_case(c, protocols, zones)
        runs[c["id"]] = run
        results.append(score(c, run, protocols, zones))
    n = len(results)
    if not n:
        print("sin casos")
        return 1
    slots_ok, slots_total = sum(r["slots_ok"] for r in results), sum(r["slots_total"] for r in results)
    mando = [r["mando_family_ok"] for r in results if r["mando_family_ok"] is not None]
    should = [r for r in results if r["first_turn_expected"]]
    summary = {
        "N": n, "protocols_file": Path(protocols["_path"]).name,
        "protocol_ok": sum(r["checks"]["protocol"] for r in results),
        "critical_slots_ok": slots_ok, "critical_slots_total": slots_total,
        "cases_all_slots_ok": sum(r["checks"]["slots"] for r in results),
        "mean_questions": round(sum(r["questions"] for r in results) / n, 2),
        "max_questions": max(r["questions"] for r in results),
        "first_report_in_first_turn": sum(r["first_turn"] for r in results),
        "first_turn_expected": len(should), "first_turn_expected_and_done": sum(r["first_turn"] for r in should),
        "instruction_ok": sum(r["checks"]["instruction"] for r in results),
        "invariant_violations": sum(len(r["violations"]) for r in results),
        "mando_reads_same_family": sum(mando), "mando_reads_N": len(mando),
        "cases_all_checks_ok": sum(r["pass"] for r in results),
        "by_level": {lv: {"N": sum(1 for r in results if r["level"] == lv),
                          "ok": sum(1 for r in results if r["level"] == lv and r["pass"])}
                     for lv in dict.fromkeys(r["level"] for r in results)},
        "failed": [{"id": r["id"], "checks": [k for k, v in r["checks"].items() if not v], "got_protocols": r["got_protocols"],
                    "wrong_slots": {k: list(v) for k, v in r["wrong_slots"].items()}, "given": r["given"],
                    "violations": r["violations"]} for r in results if not r["pass"]],
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"Banco de recogida ({'RESERVA' if args.heldout else 'desarrollo'}) · N = {n} conversaciones escritas a mano · "
          f"protocolos: {summary['protocols_file']}" + (" (orientativo: lo esperado está escrito contra la muestra)" if args.real else ""))
    print(f"  protocolo acertado ............................ {summary['protocol_ok']}/{n}")
    print(f"  slots críticos correctos ...................... {slots_ok}/{slots_total}  (casos con todos bien: {summary['cases_all_slots_ok']}/{n})")
    print(f"  preguntas por conversación .................... media {summary['mean_questions']}, máximo {summary['max_questions']} (tope 5)")
    print(f"  primer Report en el PRIMER turno .............. {summary['first_report_in_first_turn']}/{n}"
          f"  (de los {len(should)} casos en que debía: {summary['first_turn_expected_and_done']}/{len(should)})")
    print(f"  instrucción esperada .......................... {summary['instruction_ok']}/{n}")
    print(f"  el parser de Mando lee la misma familia ....... {summary['mando_reads_same_family']}/{len(mando)} (primer aviso, protocolos no genéricos)")
    print(f"  invariantes rotos (2 preguntas, frase prohibida, pregunta repetida, instrucción inventada): {summary['invariant_violations']}")
    print(f"  casos con TODAS las comprobaciones bien ....... {summary['cases_all_checks_ok']}/{n}")
    print("  por dificultad: " + " · ".join(f"{lv} {v['ok']}/{v['N']}" for lv, v in summary["by_level"].items()))
    for f in summary["failed"]:
        print(f"  ✗ {f['id']}: {', '.join(f['checks'])}"
              + (f" · protocolos={f['got_protocols']}" if "protocol" in f["checks"] else "")
              + (f" · slots={f['wrong_slots']}" if f["wrong_slots"] else "")
              + (f" · instrucciones={f['given']}" if "instruction" in f["checks"] else "")
              + (f" · {f['violations']}" if f["violations"] else ""))
        if args.verbose:
            for u, a in runs[f["id"]]["log"]:
                print(f"      › {u}\n      ‹ {a}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
