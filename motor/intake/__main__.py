"""Consola del agente de recogida.

    python3 -m motor.intake chat [--channel web|telegram|voice] [--lang es|en] [--zone front_pit] [--json]
    python3 -m motor.intake replay <fichero> [--json]
    python3 -m motor.intake bench [...]           (atajo de `python3 -m motor.intake.bench`)

En `chat` y en los guiones, las líneas que empiezan por `@` no son de la persona, son de Mando o del reloj:
    @mando ¿Junto a qué estáis?        pregunta de Mando (ASK) que entra en la conversación
    @notify dispatched medical 3       estado de Mando → frase llana (estado, tipo de equipo, minutos estimados)
    @silence 60                        segundos sin respuesta
Un guion es un .txt (una línea por mensaje, `#` comenta) o un .json: {"channel", "lang", "zone_hint", "messages": [...]}.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .engine import IntakeSession, Turn


def _show(turn: Turn, as_json: bool) -> None:
    if as_json:
        print(json.dumps(turn.to_dict(), ensure_ascii=False, default=str))
        return
    print(f"  agente › {turn.say}")
    if turn.instruction:
        print(f"    ┌ INSTRUCCIÓN «{turn.instruction['id']}»  ({turn.instruction.get('source', '')})")
        for i, step in enumerate(turn.instruction["steps"], 1):
            print(f"    │ {i}. {step}")
        print("    └")
    if turn.why_next:
        print(f"    por qué pregunta eso: {turn.why_next}")
    for r, m in zip(turn.reports, turn.report_meta):
        marks = ", ".join(k for k in ("partial", "reserved", "life_risk", "update") if m.get(k)) or "completo"
        print(f"    → MANDO [{r.id}] ({marks}; zona={r.zone_hint}; necesita={m.get('needs') or '-'}): {r.text}")
    for a in turn.answers:
        print(f"    → RESPUESTA a Mando [{a['ask_id']}]: «{a['text']}» (zona={a['zone']})")
    known = {k: v["value"] for k, v in turn.state["slots"].items() if v["status"] == "known"}
    gave_up = [k for k, v in turn.state["slots"].items() if v["status"] not in ("known", "open")]
    print(f"    fichas: {json.dumps(known, ensure_ascii=False)}" + (f" · sin dato: {gave_up}" if gave_up else "")
          + (f" · flags: {turn.flags}" if turn.flags else "") + ("  · FIN" if turn.done else ""))


def _feed(session: IntakeSession, line: str) -> Turn | None:
    if line.startswith("@mando"):
        return session.mando_asks(line[len("@mando"):].strip() or "¿Puedes darme más detalles?")
    if line.startswith("@notify"):
        parts = line.split()[1:]
        info: dict[str, Any] = {"status": parts[0] if parts else "received"}
        if len(parts) > 1:
            info["kind"] = parts[1]
        if len(parts) > 2 and parts[2].isdigit():
            info["eta"] = int(parts[2])
        return session.notify(info)
    if line.startswith("@silence"):
        parts = line.split()
        return session.silence(float(parts[1]) if len(parts) > 1 else 999)
    return session.receive(line)


def _session(cfg: dict[str, Any]) -> IntakeSession:
    return IntakeSession(channel=cfg.get("channel") or "web", lang=cfg.get("lang"), zone_hint=cfg.get("zone_hint"),
                         profile=cfg.get("profile"), session_id=str(cfg.get("session_id") or "S1"))


def chat(args: argparse.Namespace) -> int:
    s = _session({"channel": args.channel, "lang": args.lang, "zone_hint": args.zone})
    print(f"Agente de recogida · protocolos: {s.state()['protocols_file']} · Ctrl-D o «/salir» para terminar\n")
    _show(s.opening(), args.json)
    while True:
        try:
            line = input("  tú › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if line in ("/salir", "/exit", "/quit"):
            break
        turn = _feed(s, line)
        if turn is None:
            print("    (todavía no ha pasado el tiempo de silencio)")
            continue
        _show(turn, args.json)
    return 0


def replay(args: argparse.Namespace) -> int:
    path = Path(args.file)
    raw = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        cfg = json.loads(raw)
        messages = cfg.get("messages") or cfg.get("turns") or []
    else:
        cfg, messages = {}, [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    s = _session(cfg)
    for m in messages:
        line = m if isinstance(m, str) else str(m.get("text") or m.get("say") or "")
        if not args.json:
            print(f"  {'mando/reloj' if line.startswith('@') else 'persona'} › {line}")
        turn = _feed(s, line)
        if turn is not None:
            _show(turn, args.json)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m motor.intake", description="Agente de recogida de avisos (sin LLM, sin red).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chat", help="conversación por consola")
    c.add_argument("--channel", default="web")
    c.add_argument("--lang", default=None)
    c.add_argument("--zone", default=None, help="zona que da el canal (QR de zona)")
    c.add_argument("--json", action="store_true")
    r = sub.add_parser("replay", help="reproduce un guion (.txt o .json)")
    r.add_argument("file")
    r.add_argument("--json", action="store_true")
    b = sub.add_parser("bench", help="banco de conversaciones de prueba")
    b.add_argument("rest", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    if args.cmd == "chat":
        return chat(args)
    if args.cmd == "replay":
        return replay(args)
    from .bench import main as bench_main
    return bench_main(args.rest)


if __name__ == "__main__":
    sys.exit(main())
