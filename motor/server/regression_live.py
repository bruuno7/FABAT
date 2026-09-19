"""«El test con tu nombre»: un fallo provocado en directo queda BLOQUEADO como test de regresión.

Se guarda el caso, la semilla, el manual y TODAS las entradas de fuera con su minuto (avisos, golpes, aprobaciones).
Como el mundo y Mando son deterministas, re-ejecutarlo a ×16 reproduce la misma partida: pasa o no pasa, a la vista.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

DIR = Path(__file__).resolve().parent / "regression_live"
HARNESS_REG = Path(__file__).resolve().parent.parent / "harness" / "regression"


def _files() -> list[Path]:
    return sorted(DIR.glob("test-*.json")) if DIR.exists() else []


def next_number() -> int:
    """Numeración corrida con los casos que ya tiene bloqueados el banco de pruebas."""
    base = len(list(HARNESS_REG.glob("*.json"))) if HARNESS_REG.exists() else 0
    mine = [int(m.group(1)) for f in _files() if (m := re.search(r"test-(\d+)", f.name))]
    return max([base] + mine) + 1


def lock(*, case: dict[str, Any], seed: int, playbook: str, inputs: list[dict[str, Any]], metrics: dict[str, Any],
         author: str, t: int, note: str = "") -> dict[str, Any]:
    DIR.mkdir(parents=True, exist_ok=True)
    n = next_number()
    author = re.sub(r"[^\w .,'’-]", "", author, flags=re.UNICODE).strip()[:40] or "anónimo"
    rec = {"n": n, "author": author, "note": note[:200], "locked_at": time.strftime("%Y-%m-%d %H:%M:%S"), "locked_t": t,
           "case_id": case.get("id"), "seed": seed, "playbook": playbook, "inputs": inputs,
           "before": {k: metrics.get(k) for k in ("critical_failed", "critical_total", "unsafe_actions", "replans",
                                                  "peak_density", "minutes_over_5")},
           "limits": {"max_critical_failed": 0, "max_unsafe_actions": 0}, "case": case}
    (DIR / f"test-{n:03d}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: v for k, v in rec.items() if k != "case"}


def list_tests() -> list[dict[str, Any]]:
    out = []
    for f in _files():
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        out.append({k: rec.get(k) for k in ("n", "author", "case_id", "seed", "locked_at", "before", "last_run")}
                   | {"inputs": len(rec.get("inputs", []))})
    return out


def load(n: int) -> dict[str, Any]:
    f = DIR / f"test-{int(n):03d}.json"
    if not f.exists():
        raise KeyError(n)
    return json.loads(f.read_text(encoding="utf-8"))


def save_result(n: int, metrics: dict[str, Any]) -> dict[str, Any]:
    rec = load(n)
    lim = rec["limits"]
    passed = metrics.get("critical_failed", 1) <= lim["max_critical_failed"] and metrics.get("unsafe_actions", 1) <= lim["max_unsafe_actions"]
    rec["last_run"] = {"passed": passed, "critical_failed": metrics.get("critical_failed"),
                       "unsafe_actions": metrics.get("unsafe_actions"), "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    (DIR / f"test-{int(n):03d}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec["last_run"]
