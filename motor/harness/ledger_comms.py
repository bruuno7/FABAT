"""Comms del harness que delegan en SimComms y escriben episodios en el ledger (best-effort).

No altera el RNG ni el resultado de poll/send: solo observa. Si el ledger falla, el caso sigue.
"""
from __future__ import annotations

import os
import re
from typing import Any

from motor.contracts import Action, Resource


def harness_ledger_enabled(ledger: Any = None) -> bool:
    """¿Hay que auditar esta ejecución?

    - `ledger` True / instancia → sí
    - `ledger` False → no
    - `ledger` None → sí si `MANDO_HARNESS_LEDGER=1` o hay `MANDO_LEDGER_PATH`
    """
    if ledger is False:
        return False
    if ledger is not None and ledger is not True:
        return True
    if ledger is True:
        return True
    flag = (os.environ.get("MANDO_HARNESS_LEDGER") or "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    if flag in ("1", "true", "yes", "on"):
        return True
    return bool((os.environ.get("MANDO_LEDGER_PATH") or "").strip())


def open_harness_ledger(ledger: Any = None) -> tuple[Any | None, bool]:
    """Devuelve (ledger_or_None, owns_close). Import perezoso de motor.server."""
    if ledger is False or not harness_ledger_enabled(ledger):
        return None, False
    if ledger is not None and ledger is not True:
        return ledger, False
    try:
        from motor.server.ledger import open_ledger
        return open_ledger(), True
    except Exception:
        return None, False


class LedgerSimComms:
    """Proxy transparente de SimComms: al hacer poll, upsert de episodios (real=0)."""

    def __init__(self, inner: Any, ledger: Any, *, session_id: str, seed: int) -> None:
        self._inner = inner
        self._ledger = ledger
        self._session_id = session_id
        self._seed = int(seed)
        self._meta: dict[str, dict[str, Any]] = {}
        # El agente (Mando) lee `comms.world`
        self.world = inner.world

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def send(self, action: Action, resource: Resource | None = None) -> None:
        rid = ""
        rkind = ""
        if resource is not None:
            rid = str(getattr(resource, "id", "") or "")
            rkind = str(getattr(resource, "kind", "") or "")
        elif action.resource:
            rid = str(action.resource)
        self._meta[str(action.id)] = {
            "kind": str(action.kind),
            "zone": action.zone or (action.params or {}).get("zone"),
            "resource": rid,
            "resource_kind": rkind,
            "t_send": getattr(self.world, "t", None),
        }
        try:
            self._ledger.append_event(
                self._session_id, "send_sim", str(action.id),
                {"kind": str(action.kind), "zone": action.zone, "resource": rid, "source": "harness"},
            )
        except Exception:
            pass
        return self._inner.send(action, resource)

    def poll(self, t: int) -> list[dict[str, Any]]:
        out = self._inner.poll(t)
        for item in out:
            self._record(item)
        return out

    def _record(self, item: dict[str, Any]) -> None:
        aid = str(item.get("action_id") or "")
        if not aid:
            return
        meta = self._meta.get(aid) or {}
        text = str(item.get("text") or "")
        eta = item.get("eta_min")
        if eta is None:
            m = re.search(r"(\d+)\s*min", text)
            if m:
                try:
                    eta = int(m.group(1))
                except ValueError:
                    eta = None
        # PK global: evita que dos casos pisen el mismo action_id (A-12, …)
        ep_id = f"{self._session_id}:{aid}"
        t_sim = item.get("t")
        if t_sim is None:
            t_sim = meta.get("t_send")
        try:
            self._ledger.upsert_episode(
                self._session_id, ep_id,
                kind=str(meta.get("kind") or ""),
                zone=str(meta.get("zone") or "") if meta.get("zone") is not None else "",
                resource=str(meta.get("resource") or ""),
                resource_kind=str(meta.get("resource_kind") or ""),
                real=False,
                result=str(item.get("result") or "") or None,
                eta_min=float(eta) if eta is not None else None,
                text=text,
                t=int(t_sim) if t_sim is not None else None,
                seed=self._seed,
            )
        except Exception:
            pass
