"""Panel de memoria DÍA 1 → DÍA 2. Lee lo que dejan `motor/mando/memory.py`, `motor/mando/tuning.py` y
`python3 -m motor.harness day2` SI existen; si no, lo dice y no inventa nada.

Formatos reales (19-sep, los escribe `motor.mando.tuning`): `params.proposed.json` = {changes: [{id, param, key, old, new, n,
text, evidence}], unchanged, safety_locked…}; `params.approved.json` = {approved_changes: [ids], values, evidence}. ESE FICHERO
ES DE MANDO: este panel no lo reescribe. La API de tuning aplica las decisiones a
`motor/server/params.approved.local.json`, que carga la siguiente sesión; la auditoría queda en
`motor/server/memoria.decisions.local.json`. Sin API disponible se registra la decisión como no aplicada.
Las cifras se enseñan tal cual: si el informe dice que
no hay evidencia de mejora, el panel dice «sin evidencia de mejora».
"""
from __future__ import annotations

import json
import time
import threading
from pathlib import Path
from typing import Any

MOTOR = Path(__file__).resolve().parent.parent
MEMORY_PATH = MOTOR / "mando" / "memory.day1.json"
PROPOSALS_PATH = MOTOR / "mando" / "params.proposed.json"
APPROVED_PATH = MOTOR / "mando" / "params.approved.json"                          # de Mando: solo lectura
DECISIONS_PATH = Path(__file__).resolve().parent / "memoria.decisions.local.json"   # nuestro: quién aprobó qué y cuándo
LOCAL_APPROVED_PATH = Path(__file__).resolve().parent / "params.approved.local.json"
_LOCK = threading.RLock()
DAY2_FALLBACK_PATH = MOTOR / "harness" / "out" / "day2.json"
DAY2_PATH = MOTOR / "harness" / "out" / "latest" / "day2.json"


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _day2() -> Any:
    return _read(DAY2_PATH) or _read(DAY2_FALLBACK_PATH)


def _observations(memory: Any) -> list[dict]:
    if not isinstance(memory, dict):
        return []
    rows = _items(memory, "observations", "observaciones")
    def add(kind, key, text, n, evidence):
        rows.append({"id": f"{kind}:{key}", "kind": kind, "key": key, "text": text,
                     "n": n, "evidence": evidence, "source": str(MEMORY_PATH), "verified": True, "simulation": True})
    for zone, data in memory.get("resupply", {}).items():
        values = data.get("minutes", [])
        n = data.get("n", len(values))
        mean = round(sum(values) / len(values), 1) if values else None
        add("resupply", zone, f"Reposición en {zone}: {mean} min de media (N={n}).", n,
            {"mean_min": mean, "dry_before_refill": data.get("dry_before_refill")})
    for resource, data in memory.get("contacts", {}).items():
        channels = data.get("channels", {}).values()
        n = sum(c.get("sent", 0) for c in channels)
        accepts = sum(c.get("accept", 0) for c in channels)
        add("contacts", resource, f"{resource}: acepta {accepts} de {n} llamadas (N={n}).", n, {"accepted": accepts})
    dup = memory.get("duplicates", {})
    if dup:
        n = dup.get("reports", 0)
        merged = len(dup.get("merge_gap_min", []))
        add("duplicates", "all", f"{merged} avisos fusionados de {n} recibidos (N={n}).", n,
            {"merged": merged, "teams_moved_by_duplicate": dup.get("teams_moved_by_duplicate")})
    for zone, data in memory.get("locate", {}).get("search", {}).items():
        values = data.get("minutes", [])
        n = data.get("n", len(values))
        mean = round(sum(values) / len(values), 1) if values else None
        add("locate", zone, f"Búsqueda en {zone}: {mean} min de media (N={n}).", n, {"mean_min": mean})
    episodes = memory.get("weather", {}).get("episodes", [])
    if episodes:
        quiet = sum(e.get("outcome") == "no_llego" for e in episodes)
        add("weather", "all", f"{quiet} alertas no llegaron a más (N={len(episodes)}).", len(episodes), {"did_not_arrive": quiet})
    return rows


def _tuning() -> Any:
    try:
        from motor.mando import tuning  # type: ignore[attr-defined]
        return tuning
    except Exception:
        return None


def _items(x: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(x, dict):
        x = next((x[k] for k in keys if isinstance(x.get(k), list)), [])
    return [i for i in (x or []) if isinstance(i, dict)]


def _proposals(memory: Any, day2: Any) -> tuple[list[dict[str, Any]], str]:
    for src, label in ((_read(PROPOSALS_PATH), PROPOSALS_PATH.name), ((day2 or {}).get("proposals") if isinstance(day2, dict) else None, DAY2_PATH.name),
                       (memory, MEMORY_PATH.name)):
        items = _items(src, "changes", "proposals", "propuestas")
        if items:
            out = []
            for p in items:   # nombres del formato real → los que pinta la página
                p = dict(p)
                p.setdefault("from", p.get("old"))
                p.setdefault("value", p.get("new"))
                p.setdefault("title", p.get("text"))
                if p.get("key") and p.get("param"):
                    p["param"] = f"{p['param']}[{p['key']}]"
                if isinstance(p.get("evidence"), dict):
                    p["evidence"] = ", ".join(f"{k}: {v}" for k, v in list(p["evidence"].items())[:4])
                out.append(p)
            return out, label
    return [], "ninguna"


def _comparison(day2: Any) -> dict[str, Any] | None:
    """Antes/después de `day2.json`, sin maquillar. Se aceptan varios nombres de campo; lo que no esté, no sale."""
    if not isinstance(day2, dict):
        return None
    if isinstance(day2.get("splits"), dict):
        rows = []
        for split, data in day2["splits"].items():
            for metric, values in data.get("compare", {}).items():
                diff = values.get("paired_diff_99") or values.get("paired_diff_95") or {}
                rows.append({"name": values.get("text", metric), "metric": metric, "split": split,
                             "before": values.get("initial", {}).get("mean"), "after": values.get("revised", {}).get("mean"),
                             "delta": diff.get("mean"), "ci": diff.get("ci"), "confidence_level": diff.get("level"),
                             "n": values.get("n_pairs", diff.get("n")), "significant": diff.get("evidence"),
                             "verdict": values.get("verdict"), "lower_is_better": values.get("lower_is_better"),
                             "case_signature": data.get("case_signature")})
        return {"n": day2.get("n_per_arm"), "rows": rows, "params": day2.get("params", {}),
                "fingerprint": day2.get("code"), "verdict": "Consultar evidencia por métrica y conjunto; no implica mejora global",
                "simulation_note": day2.get("simulation_note"), "source": str(DAY2_PATH if DAY2_PATH.exists() else DAY2_FALLBACK_PATH)}
    cmp_ = day2.get("comparison") or day2.get("comparacion") or day2
    rows = []
    for m in _items(cmp_, "metrics", "metricas", "rows"):
        rows.append({"name": m.get("name") or m.get("metric") or m.get("metrica"), "before": m.get("before", m.get("antes")),
                     "after": m.get("after", m.get("despues")), "delta": m.get("delta", m.get("diff")),
                     "ci": m.get("ci") or m.get("ci95") or m.get("intervalo"), "n": m.get("n", cmp_.get("n") if isinstance(cmp_, dict) else None),
                     "significant": m.get("significant", m.get("significativo"))})
    verdict = cmp_.get("verdict") or cmp_.get("veredicto") or day2.get("verdict") if isinstance(cmp_, dict) else None
    if verdict is None and rows:
        verdict = ("mejora con evidencia" if any(r["significant"] for r in rows) else "sin evidencia de mejora")
    return {"n": cmp_.get("n") if isinstance(cmp_, dict) else None, "fingerprint": day2.get("fingerprint") or day2.get("huella"),
            "rows": rows, "verdict": verdict, "raw_keys": sorted(day2.keys())[:20]}


def overview(extra_lessons: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    memory, day2, approved = _read(MEMORY_PATH), _day2(), _read(APPROVED_PATH) or {}
    proposals, source = _proposals(memory, day2)
    decided = {str(i): {"status": "approved", "by": "params.approved.json", "at": None} for i in (approved.get("approved_changes") or [])
               if isinstance(approved, dict)}
    decided.update({str(d.get("id")): d for d in _items(_read(DECISIONS_PATH), "decisions")})
    for n, p in enumerate(proposals):
        p.setdefault("id", f"p-{n + 1}")
        d = decided.get(str(p["id"]))
        p["decision"] = {"status": d.get("status"), "by": d.get("by"), "at": d.get("at")} if d else None
    return {"available": memory is not None or bool(proposals) or day2 is not None,
            "files": {"memory": MEMORY_PATH.exists(), "proposals": PROPOSALS_PATH.exists(), "day2": DAY2_PATH.exists() or DAY2_FALLBACK_PATH.exists(),
                      "approved": APPROVED_PATH.exists(), "tuning_module": _tuning() is not None},
            "observations": _observations(memory), "proposals": proposals, "proposals_source": source,
            "comparison": _comparison(day2), "operator_lessons": extra_lessons or [],
            "how": "python3 -m motor.harness day2   (lo crea otro módulo; este panel solo lo lee)"}


def decide(proposal_id: str, approve: bool, by: str) -> dict[str, Any]:
    if type(approve) is not bool:
        raise ValueError("approve debe ser booleano")
    with _LOCK:
        return _decide(proposal_id, approve, by)


def _decide(proposal_id: str, approve: bool, by: str) -> dict[str, Any]:
    """Una PERSONA aprueba o rechaza un cambio de parámetros. Queda escrito con quién y cuándo."""
    memory, day2 = _read(MEMORY_PATH), _day2()
    proposals, _ = _proposals(memory, day2)
    for n, p in enumerate(proposals):
        p.setdefault("id", f"p-{n + 1}")
    prop = next((p for p in proposals if str(p["id"]) == str(proposal_id)), None)
    if prop is None:
        raise KeyError(proposal_id)
    data = _read(DECISIONS_PATH) or {}
    decisions = [d for d in _items(data, "decisions") if str(d.get("id")) != str(proposal_id)]
    status = "approved" if approve else "rejected"
    decisions.append({"id": proposal_id, "status": status, "by": by[:40], "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                      "param": prop.get("param"), "value": prop.get("value")})
    data["decisions"] = decisions
    tuning = _tuning()
    applied = False
    raw = _read(PROPOSALS_PATH) or {}
    if tuning is not None and all(hasattr(tuning, key) for key in ("Change", "Proposals", "Params")) and raw.get("changes"):
        changes = [tuning.Change(**{k: v for k, v in change.items() if k in tuning.Change.__dataclass_fields__})
                   for change in raw["changes"]]
        proposals_api = tuning.Proposals(changes, base=tuning.Params.from_dict((day2 or {}).get("params", {}).get("initial")))
        canonical = _read(APPROVED_PATH) or {}
        approved_ids = set(canonical.get("approved_changes", []))
        for change in changes:
            change.status = "approved" if change.id in approved_ids else "proposed"
        for decision in decisions:
            if any(c.id == decision["id"] for c in changes):
                fn = proposals_api.approve if decision["status"] == "approved" else proposals_api.reject
                fn(decision["id"], by=decision["by"])
        # La API de Mando serializa su formato; este encargo solo permite escribir dentro del servidor.
        proposals_api.write_approved(LOCAL_APPROVED_PATH)
        applied = True
    data["applied_to_mando"] = applied
    DECISIONS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "via": DECISIONS_PATH.name, "id": proposal_id, "status": status, "applied_to_mando": applied,
            "effective": "next_session" if applied else None, "params_path": str(LOCAL_APPROVED_PATH) if applied else None}
