"""Regresión: el caso que falló y se arregló queda BLOQUEADO. Si vuelve a romperse, `regress` falla.

Un bloqueo es un fichero `regression/<caso>.json` con el caso entero, la semilla, qué pasaba antes,
qué pasa ahora y los límites que debe seguir cumpliendo:
    critical_failed ≤ el valor arreglado · unsafe_actions == 0 · score ≥ score arreglado − margen.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .runner import AgentFactory, run_case

import os

REG_DIR = Path(os.environ.get("MOTOR_HARNESS_REG") or (Path(__file__).resolve().parent / "regression"))
SCORE_MARGIN = 5.0


def world_fingerprint() -> str:
    """Huella del SIMULADOR. Si cambia, los límites de un bloqueo antiguo ya no significan nada (otro mundo, otras
    puntuaciones): el bloqueo se marca OBSOLETO, no se borra y no cuenta como roto."""
    import hashlib
    h = hashlib.sha256()
    for f in sorted((Path(__file__).resolve().parent.parent / "world").glob("*")):
        if f.suffix in (".py", ".json") and not f.name.startswith(("test_", "demo")):
            h.update(f.name.encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:12]


def is_failure(metrics: dict[str, Any]) -> bool:
    return bool(metrics) and (metrics["critical_failed"] > 0 or metrics["unsafe_actions"] > 0 or metrics["score"] < 60)


def is_fixed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """Fallaba (crítico fallido, acción insegura o score < 60) y ya no, con mejor puntuación."""
    return is_failure(before) and bool(after) and not is_failure(after) and after["score"] > before["score"]


def lock(case: dict[str, Any], before: dict[str, Any], after: dict[str, Any], agent: str = "mando",
         note: str = "", reg_dir: Path | None = None) -> Path:
    d = reg_dir or REG_DIR
    d.mkdir(parents=True, exist_ok=True)
    rec = {"case_id": case["id"], "seed": case.get("seed", 0), "agent": agent, "note": note, "world": world_fingerprint(),
           "before": {k: before.get(k) for k in ("score", "critical_failed", "unsafe_actions", "failed")},
           "fixed": {k: after.get(k) for k in ("score", "critical_failed", "unsafe_actions", "failed")},
           "limits": {"max_critical_failed": after["critical_failed"], "max_unsafe_actions": 0,
                      "min_score": round(after["score"] - SCORE_MARGIN, 2)},
           "case": case}
    path = d / f"{case['id']}.json"
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def lock_fixed(cases: list[dict[str, Any]], before: list[dict[str, Any]], after: list[dict[str, Any]],
               agent: str = "mando", note: str = "", reg_dir: Path | None = None) -> list[str]:
    """Bloquea todo caso que fallaba en `before` y está arreglado en `after` (mismo orden que `cases`)."""
    locked = []
    for c, b, a in zip(cases, before, after):
        if is_fixed(b.get("metrics") or {}, a.get("metrics") or {}):
            lock(c, b["metrics"], a["metrics"], agent, note, reg_dir)
            locked.append(c["id"])
    return locked


def check(rec: dict[str, Any], factory: Callable[[Any], Any]) -> dict[str, Any]:
    lim = rec["limits"]
    try:
        m = run_case(rec["case"], factory, rec.get("seed"), detail=False).metrics
    except Exception as ex:     # una ejecución que revienta es un caso roto, no un caso que desaparece
        return {"case_id": rec["case_id"], "ok": False, "broken": [f"la ejecución revienta: {ex!r}"], "score": 0.0,
                "critical_failed": None, "unsafe_actions": None}
    broken = []
    if m["critical_failed"] > lim["max_critical_failed"]:
        broken.append(f"critical_failed {m['critical_failed']} > {lim['max_critical_failed']}")
    if m["unsafe_actions"] > lim["max_unsafe_actions"]:
        broken.append(f"unsafe_actions {m['unsafe_actions']} > {lim['max_unsafe_actions']}")
    if m["score"] < lim["min_score"]:
        broken.append(f"score {m['score']} < {lim['min_score']}")
    return {"case_id": rec["case_id"], "ok": not broken, "broken": broken, "score": m["score"],
            "critical_failed": m["critical_failed"], "unsafe_actions": m["unsafe_actions"]}


def regress(factory: Callable[[Any], Any] | None = None, reg_dir: Path | None = None,
            lessons: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Re-ejecuta todos los bloqueos vigentes. `ok` es False si alguno vuelve a romperse. Los bloqueos hechos con
    otra versión del simulador se listan como obsoletos (no se borran ni cuentan)."""
    d = reg_dir or REG_DIR
    rows, obsolete, wfp = [], [], world_fingerprint()
    for path in sorted(d.glob("*.json")) if d.exists() else []:
        rec = json.loads(path.read_text(encoding="utf-8"))
        if rec.get("world") != wfp:
            obsolete.append(rec["case_id"])
            continue
        rows.append(check(rec, factory or AgentFactory(rec.get("agent", "mando"), lessons)))
    return {"n": len(rows), "ok": all(r["ok"] for r in rows), "broken": [r for r in rows if not r["ok"]], "rows": rows,
            "obsolete": obsolete, "world": wfp}
