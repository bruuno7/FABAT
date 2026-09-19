"""Mide el parser con avisos SINTÉTICOS difíciles, escritos por modelos ajenos al léxico (vía Cursor).

- `data/frases_sinteticas_dev.jsonl` (Grok 4.6): se puede mirar para ampliar vocabulario.
- `data/frases_sinteticas_reserva.jsonl` (Claude Opus 5): SOLO se mide; no se mira para ajustar nada.
Las etiquetas las puso el modelo que escribió cada aviso y algunas son discutibles: es una cota, no un examen.

    python3 -m motor.mando.frases_bench
"""
from __future__ import annotations

import json
from pathlib import Path

from motor.mando.free_text_bench import score

DATA = Path(__file__).parent / "data"


def load(name: str) -> list[tuple]:
    rows = []
    for line in (DATA / name).read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            rows.append((r["text"], r["family"], None, r.get("zone")))
        except (ValueError, KeyError):
            continue
    return rows


if __name__ == "__main__":
    for label, name in (("DESARROLLO", "frases_sinteticas_dev.jsonl"), ("RESERVA", "frases_sinteticas_reserva.jsonl")):
        r = score(load(name))
        n = r["n"]
        print(f"{label}: N={n} · familia {r['family']}/{n} ({100 * r['family'] / n:.0f} %) · "
              f"zona {r['zone']}/{n} ({100 * r['zone'] / n:.0f} %)")
