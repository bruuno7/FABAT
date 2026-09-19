"""Verificación de afirmaciones del pitch con Exa (fuera del motor).

Por defecto NO llama a la red: imprime el expediente local y el estado.
Para gastar crédito Exa hace falta EXA_API_KEY + EXA_RUN=1 + OK de persona (AGENTS.md).

    uv run --project motor/server python -m motor.server.exa_pitch
    EXA_RUN=1 uv run --project motor/server python -m motor.server.exa_pitch
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Afirmaciones del pitch (TRASPASO.md). Etiqueta local: verificado | en_verificacion | no_usar_demo
CLAIMS: list[dict[str, Any]] = [
    {
        "id": "astroworld-2021",
        "claim": "Astroworld 5-nov-2021: ~65 min con información y sin decisión de parar el show",
        "local_status": "verificado",
        "local_source": "cronología policía Houston vía ABC13 (TRASPASO)",
        "exa_query": "Astroworld 2021 Houston police timeline first 911 call show stopped",
        "notes": "No decir «37 minutos» sin fuente policial.",
    },
    {
        "id": "itaewon-2022",
        "claim": "Itaewon 29-oct-2022: avisos de aplastamiento horas antes; respuesta insuficiente",
        "local_status": "verificado",
        "local_source": "Korea Herald (TRASPASO); cifra 159 muertos solo Wikipedia → no enfatizar sin VB",
        "exa_query": "Itaewon Halloween crush 2022 police calls warning hours before",
        "notes": "Cuidado con cifras de víctimas: etiquetar fuente.",
    },
    {
        "id": "rd-393-2007",
        "claim": "RD 393/2007: Plan de Autoprotección en espectáculos al aire libre en España",
        "local_status": "verificado",
        "local_source": "BOE RD 393/2007 (TRASPASO VB)",
        "exa_query": "Real Decreto 393/2007 plan autoprotección espectáculos BOE",
        "notes": "Preferir cita BOE literal en diapositiva.",
    },
    {
        "id": "madrid-arena",
        "claim": "Madrid Arena 2012: aforo y vomitorios (contexto, no escenario demo)",
        "local_status": "verificado_no_demo",
        "local_source": "CGPJ / Supremo (TRASPASO VB)",
        "exa_query": "Madrid Arena 2012 sentencia Supremo aforo vomitorios",
        "notes": "No usar como escenario de la demo (muertos reales, Madrid).",
    },
]


def _exa_search(query: str, api_key: str, num: int = 3) -> list[dict[str, str]]:
    body = json.dumps({"query": query, "num_results": num, "type": "auto"}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.exa.ai/search",
        data=body,
        headers={"x-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    out = []
    for r in data.get("results") or []:
        out.append({"title": str(r.get("title") or ""), "url": str(r.get("url") or "")})
    return out


def run(*, live: bool = False) -> dict[str, Any]:
    key = (os.environ.get("EXA_API_KEY") or "").strip()
    want = live or os.environ.get("EXA_RUN", "").strip().lower() in ("1", "true", "yes")
    report: dict[str, Any] = {"live": False, "claims": [], "warning": None}
    if want and not key:
        report["warning"] = "EXA_RUN=1 pero falta EXA_API_KEY: solo expediente local"
        want = False
    if want:
        report["live"] = True
    for c in CLAIMS:
        row = dict(c)
        row["exa_results"] = []
        if want:
            try:
                row["exa_results"] = _exa_search(c["exa_query"], key)
                row["exa_status"] = "ok" if row["exa_results"] else "sin_resultados"
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as ex:
                row["exa_status"] = f"error:{type(ex).__name__}"
        else:
            row["exa_status"] = "omitido"
        report["claims"].append(row)
    return report


def write_markdown(report: dict[str, Any], path: Path) -> Path:
    lines = [
        "# Fuentes del pitch (Exa + expediente)",
        "",
        f"Modo: **{'Exa en vivo' if report.get('live') else 'solo local (sin gastar crédito)'}**.",
        "",
    ]
    if report.get("warning"):
        lines += [f"> Aviso: {report['warning']}", ""]
    for c in report["claims"]:
        lines += [
            f"## {c['id']}",
            "",
            f"- Afirmación: {c['claim']}",
            f"- Estado local: **{c['local_status']}** — {c['local_source']}",
            f"- Notas: {c.get('notes') or '—'}",
            f"- Exa: `{c.get('exa_status')}`",
        ]
        for r in c.get("exa_results") or []:
            lines.append(f"  - [{r['title'] or r['url']}]({r['url']})")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    report = run()
    # Preferir escritura en FABAT-thinking/entrega si existe; si no, junto al server.
    thinking = Path(__file__).resolve().parents[2].parent / "FABAT-thinking" / "entrega" / "fuentes-pitch.md"
    local = Path(__file__).resolve().parent.parent.parent / "entrega" / "fuentes-pitch.md"
    out = thinking if thinking.parent.is_dir() else local
    write_markdown(report, out)
    print(json.dumps({"ok": True, "path": str(out), "live": report["live"],
                      "n": len(report["claims"]), "warning": report.get("warning")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
