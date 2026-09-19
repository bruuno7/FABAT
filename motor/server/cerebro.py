"""Modo del cerebro: quién decide (reglas / agente HR / híbrido) y las barandillas de tiempo.

Por defecto `MANDO_CEREBRO` no está definido → `reglas`: el planificador sigue igual.
En `agente`, las reglas no ejecutan lo que debe entregar `/hr/tools/decidir`; sí vigilan
riesgo vital (despacho inmediato). Si HappyRobot no contesta, decide el equipo local con LLM;
las reglas solo entran si TAMBIÉN falla el LLM local, rotuladas («modo degradado: reglas»).
En `hibrido` las reglas proponen y ejecutan; el agente puede corregir vía `decidir`.
"""
from __future__ import annotations

import os
import time
from typing import Any

from motor.contracts import Action, ActionKind, ActionStatus, ALWAYS_APPROVE

ORIGEN_AGENTE = "agente HR"
ORIGEN_PLAN_B = "plan B reglas"
ORIGEN_LLM_LOCAL = "equipo local LLM"
ORIGEN_BARANDILLA = "barandilla"
ETIQUETA_DEGRADADO = "modo degradado: reglas"
_GRAVE = {ActionKind.EVACUATE, ActionKind.STOP_SHOW, ActionKind.REQUEST_EXTERNAL}


def mode() -> str:
    v = (os.environ.get("MANDO_CEREBRO") or "").strip().lower()
    return v if v in ("agente", "hibrido") else "reglas"


def timeout_s() -> float:
    try:
        return max(0.0, float(os.environ.get("MANDO_CEREBRO_TIMEOUT_S") or "8"))
    except (TypeError, ValueError):
        return 8.0


def attach(session: Any) -> None:
    """Envuelve el planificador. En `reglas` el envoltorio es transparente."""
    session._cerebro_seen = getattr(session, "_cerebro_seen", {})
    session._cerebro_decided = getattr(session, "_cerebro_decided", set())
    session._cerebro_from_agent = getattr(session, "_cerebro_from_agent", set())
    session._cerebro_llm_tried = getattr(session, "_cerebro_llm_tried", set())
    session._cerebro_degradado = getattr(session, "_cerebro_degradado", False)
    session._cerebro_cadena = getattr(session, "_cerebro_cadena", "plataforma" if mode() == "agente" else mode())
    agent = getattr(session, "agent", None)
    if agent is None or not hasattr(agent, "_plan_dirty"):
        return
    if getattr(agent, "_cerebro_wrapped", False):
        return
    agent._cerebro_wrapped = True
    original_plan = agent._plan_dirty
    original_send = agent._send

    def plan_dirty() -> None:
        _plan_dirty_gated(session, original_plan)

    def send(a: Action) -> None:
        if _should_send(session, a):
            original_send(a)

    agent._plan_dirty = plan_dirty
    agent._send = send


def after_tick(session: Any, actions: list[Action]) -> list[Action]:
    """Etiqueta el origen. En `agente` no deja salir AUTO no vital si el agente aún tiene tiempo."""
    m = mode()
    if m == "reglas" or not actions:
        return actions
    now = time.monotonic()
    to = timeout_s()
    seen = getattr(session, "_cerebro_seen", {})
    from_agent = getattr(session, "_cerebro_from_agent", set())
    agent = session.agent
    out: list[Action] = []
    for a in actions:
        origen = (a.params or {}).get("origen")
        inc = a.incident
        meta = agent.meta.get(inc) if inc and hasattr(agent, "meta") else None
        vital = bool(meta and meta.life_threat)
        grave = a.kind in _GRAVE or a.status == ActionStatus.AWAITING_APPROVAL
        if a.kind in (ActionKind.MERGE, ActionKind.DISMISS):
            out.append(a)
            continue
        if a.id in from_agent or origen in (ORIGEN_AGENTE, ORIGEN_LLM_LOCAL):
            a.params["origen"] = origen or ORIGEN_AGENTE
            out.append(a)
            continue
        if vital and a.kind == ActionKind.DISPATCH:
            a.params.setdefault("origen", ORIGEN_BARANDILLA)
            out.append(a)
            continue
        if grave:
            a.params.setdefault("origen", origen or ORIGEN_BARANDILLA)
            out.append(a)
            continue
        if m == "hibrido":
            a.params.setdefault("origen", "reglas")
            out.append(a)
            continue
        # agente: primero equipo local con LLM; reglas solo si también falla, rotuladas
        waited = now - float(seen.get(inc, now)) if inc else 0.0
        if inc and waited >= to:
            a.params.setdefault("origen", ORIGEN_PLAN_B)
            out.append(a)
        # si no, se omite: el planificador no decide por su cuenta
    return out


def mark_decided(session: Any, incident_id: str | None, action_ids: list[str] | None = None) -> None:
    if incident_id:
        session._cerebro_decided.add(incident_id)
        session._cerebro_seen.setdefault(incident_id, time.monotonic())
    for aid in action_ids or ():
        session._cerebro_from_agent.add(aid)


def _plan_dirty_gated(session: Any, original: Any) -> None:
    m = mode()
    if m in ("reglas", "hibrido"):
        original()
        return
    agent = session.agent
    now = time.monotonic()
    to = timeout_s()
    live = list(getattr(agent, "live", []) or [])
    for inc in live:
        session._cerebro_seen.setdefault(inc.id, now)
    saved: dict[str, str] = {}
    logged_b = getattr(session, "_cerebro_plan_b_logged", set())
    session._cerebro_plan_b_logged = logged_b
    for inc in live:
        meta = agent.meta.get(inc.id)
        if meta is None:
            continue
        allow = False
        if meta.life_threat:
            allow = True
        elif inc.id in session._cerebro_decided:
            allow = bool(meta.broken and meta.dirty)
        elif now - session._cerebro_seen[inc.id] >= to:
            if _intentar_llm_local(session, inc):
                allow = False
            else:
                allow = True
                if inc.id not in logged_b and meta.dirty:
                    logged_b.add(inc.id)
                    session._cerebro_degradado = True
                    session._cerebro_cadena = "reglas"
                    session.log("cerebro",
                                f"{ETIQUETA_DEGRADADO}: HappyRobot y el LLM local no contestaron en {to} s",
                                inc.id)
        if not allow and meta.dirty:
            saved[inc.id] = meta.dirty
            meta.dirty = None
    try:
        original()
    finally:
        for iid, dirty in saved.items():
            meta = agent.meta.get(iid)
            if meta is not None and not meta.dirty:
                meta.dirty = dirty


def _should_send(session: Any, a: Action) -> bool:
    m = mode()
    if m != "agente":
        return True
    origen = (a.params or {}).get("origen")
    if origen in (ORIGEN_AGENTE, ORIGEN_BARANDILLA, ORIGEN_LLM_LOCAL):
        return True
    if a.kind in (ActionKind.MERGE, ActionKind.DISMISS):
        return True
    if a.status == ActionStatus.AWAITING_APPROVAL or a.kind in ALWAYS_APPROVE:
        return True
    if a.id in getattr(session, "_cerebro_from_agent", set()):
        return True
    inc = a.incident
    meta = session.agent.meta.get(inc) if inc and hasattr(session.agent, "meta") else None
    if meta and meta.life_threat and a.kind == ActionKind.DISPATCH:
        return True
    if inc and time.monotonic() - float(session._cerebro_seen.get(inc, time.monotonic())) >= timeout_s():
        return True
    return False


def _intentar_llm_local(session: Any, inc: Any) -> bool:
    """Plan B: mismo equipo, mismos prompts, misma pizarra. Sin LLM configurado → False (reglas)."""
    tried = getattr(session, "_cerebro_llm_tried", set())
    session._cerebro_llm_tried = tried
    if inc.id in tried:
        return inc.id in getattr(session, "_cerebro_decided", set())
    tried.add(inc.id)
    try:
        from . import llm_parser_factory
        from .cerebro_llm import cycle
        client = llm_parser_factory.make_client()
        if client is None:
            return False
        aviso = {"tipo": getattr(inc, "type", None) or "", "zona": getattr(inc, "zone", None) or "",
                 "texto": f"reevaluar {inc.id}", "incident_id": inc.id}
        out = cycle(session, aviso, client=client, fake=False)
        if out.get("ok"):
            session._cerebro_cadena = "llm_local"
            session._cerebro_degradado = False
            mark_decided(session, inc.id, [x.get("action_id") for x in (out.get("resultado") or {}).get("aceptadas") or [] if x.get("action_id")])
            session.log("cerebro", f"equipo local LLM decidió {inc.id} (HappyRobot no contestó)", inc.id)
            return True
    except Exception as exc:
        session.log("cerebro", f"LLM local falló: {type(exc).__name__}", inc.id)
    return False
