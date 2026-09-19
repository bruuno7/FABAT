"""Informe markdown + JSON. Empieza por la tabla y por «Lo que falla hoy», sin maquillar."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import EvalResult, ensure_out


def failures_today(evals: list[EvalResult]) -> list[dict[str, Any]]:
    out = []
    for e in evals:
        if e.failed <= 0:
            continue
        ex = e.failures[0] if e.failures else {}
        out.append({
            "id": e.id, "suite": e.suite, "n": e.n, "aprobados": e.passed, "fallos": e.failed,
            "ejemplo": ex, "descripcion": e.description,
        })
    return out


def to_payload(evals: list[EvalResult], *, rapido: bool, wall_s: float) -> dict[str, Any]:
    return {
        "simulacion": True,
        "rotulo": "simulación, no dato de campo. Toda cifra lleva su N.",
        "rapido": rapido,
        "wall_s": round(wall_s, 2),
        "cuando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "vocabulario_happyrobot": {
            "northstars": "criterios pass/fail de conversación en la plataforma; aquí también propiedades de DECISIÓN",
            "adversarial_agents": "los suyos atacan la conversación; Caos ataca el mundo (escenario, recursos, supuestos)",
            "audits_and_tests": "esta batería: fallo de producción → test de regresión reproducible (semilla + caso)",
        },
        "evals": [e.to_dict() for e in evals],
        "lo_que_falla_hoy": failures_today(evals),
        "n_evals": len(evals),
        "n_evals_con_fallo": sum(1 for e in evals if e.failed),
        "suma_n": sum(e.n for e in evals),
        "suma_aprobados": sum(e.passed for e in evals),
        "suma_fallos": sum(e.failed for e in evals),
    }


def render_md(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    a = lines.append
    a("# Audits & Tests — MANDO (simulación)")
    a("")
    a("**Rotulado:** todas las cifras son de **simulación**, no dato de campo. Cada eval declara su N. "
      "Heldout regenerable con semilla 1. La reserva de frases (`frases_sinteticas_reserva.jsonl`) **solo se mide**.")
    a("")
    a(f"Pasada `{'rápida' if payload.get('rapido') else 'completa'}` · {payload.get('wall_s')} s · {payload.get('cuando')}.")
    a("")
    a("HappyRobot vende **northstars**, **Adversarial Agents** y **Audits & Tests**. "
      "Su adversario ataca la *conversación*; el nuestro (Caos) ataca el *mundo*. Esta batería es el audit local.")
    a("")
    a("## Resumen")
    a("")
    a("| id | suite | N | aprobados | fallos |")
    a("|---|---|---:|---:|---:|")
    for e in payload["evals"]:
        a(f"| `{e['id']}` | {e['suite']} | {e['n']} | {e['aprobados']} | {e['fallos']} |")
    a("| **total** |  | "
      f"{payload['suma_n']} | {payload['suma_aprobados']} | {payload['suma_fallos']} |")
    a("")
    a("## Lo que falla hoy")
    a("")
    fails = payload["lo_que_falla_hoy"]
    if not fails:
        a("En esta pasada ningún eval de la batería local quedó con fallos. Eso no prueba producción ni la plataforma.")
    else:
        a("Sin maquillar. Cada fallo lleva semilla y caso para reproducirlo.")
        a("")
        for f in fails:
            ex = f.get("ejemplo") or {}
            a(f"- **{f['id']}** ({f['suite']}): {f['fallos']}/{f['n']} fallos. "
              f"Ejemplo: caso `{ex.get('caso')}` semilla `{ex.get('seed')}` — {ex.get('detalle')}")
    a("")
    by: dict[str, list] = {}
    for e in payload["evals"]:
        by.setdefault(e["suite"], []).append(e)
    titles = {
        "seguridad": "1. Seguridad de decisión (northstars de decisión)",
        "comprension": "2. Comprensión (parser; reserva no se usa para ajustar)",
        "conversacion": "3. Conversación (intake; northstars de diálogo)",
        "adversario": "4. Adversario del mundo (Caos vs lista fija)",
        "notificaciones": "5. Notificaciones raras (HTTP / TestClient)",
        "plataforma": "6. Plataforma HappyRobot (solo lectura de ficheros)",
    }
    for suite, title in titles.items():
        if suite not in by:
            continue
        a(f"## {title}")
        a("")
        for e in by[suite]:
            a(f"### `{e['id']}`")
            a("")
            a(e["descripcion"])
            a("")
            a(f"N = **{e['n']}** · aprobados **{e['aprobados']}** · fallos **{e['fallos']}** · simulación = sí.")
            if e.get("notas"):
                a("")
                a(e["notas"])
            if e.get("extra"):
                a("")
                a("```json")
                a(json.dumps(e["extra"], ensure_ascii=False, indent=2)[:4000])
                a("```")
            if e["ejemplos"]:
                a("")
                a("Fallos reproducibles:")
                for ex in e["ejemplos"][:5]:
                    a(f"- semilla `{ex.get('seed')}` caso `{ex.get('caso')}`: {ex.get('detalle')}")
            a("")
    a("## Cómo reproducir")
    a("")
    a("```")
    a("python3 -m motor.evals           # pasada completa → motor/evals/out/informe.md y resultados.json")
    a("python3 -m motor.evals --rapido  # < 60 s")
    a("```")
    a("")
    return "\n".join(lines) + "\n"


def write(evals: list[EvalResult], *, rapido: bool, wall_s: float, out_dir: Path | None = None) -> dict[str, Path]:
    out = ensure_out(out_dir)
    payload = to_payload(evals, rapido=rapido, wall_s=wall_s)
    md_path = out / "informe.md"
    js_path = out / "resultados.json"
    md_path.write_text(render_md(payload), encoding="utf-8")
    js_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"informe": md_path, "resultados": js_path, "payload": payload}  # type: ignore[dict-item]
