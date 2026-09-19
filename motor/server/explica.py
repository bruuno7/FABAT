"""Capa de explicación para `/api/explica` y `/porque`: de dónde sale cada decisión."""
from __future__ import annotations

from typing import Any

from .cerebro import ORIGEN_AGENTE


def explica(state: dict[str, Any], incident_id: str | None = None) -> dict[str, Any]:
    """Resumen de las seis preguntas del reto + origen de la decisión (reglas / agente HR / persona)."""
    incidents = list(state.get("incidents") or [])
    if incident_id:
        incidents = [i for i in incidents if i.get("id") == incident_id]
        if not incidents:
            return {"ok": False, "error": "incidente desconocido", "id": incident_id}
    actions = list(state.get("actions") or [])
    if incident_id:
        actions = [a for a in actions if a.get("incident") == incident_id]
    origin = _origin(incidents, actions, state)
    cola = sorted(
        (i for i in (state.get("incidents") or []) if i.get("status") not in ("resolved", "false_alarm", "failed")),
        key=lambda i: -(i.get("priority") or 0),
    )[:8]
    return {
        "ok": True,
        "origen": origin,
        "informacion": {
            "avisos": (state.get("funnel") or {}).get("reports"),
            "incidentes": (state.get("funnel") or {}).get("incidents"),
            "fusionados": (state.get("metrics") or {}).get("merges"),
        },
        "prioridad": {
            "primero": (cola[0] if cola else None),
            "cola": [{"id": i.get("id"), "prioridad": i.get("priority"), "porque": i.get("explain"),
                      "origen": i.get("origin")} for i in cola],
        },
        "aviso": _avisos(state, incident_id),
        "recursos": {
            "asignados": [a for a in actions if a.get("kind") == "dispatch"],
            "esperando": [f for f in (state.get("fronts") or []) if f.get("why_waiting")],
        },
        "accion": {
            "pendientes_persona": state.get("approvals") or [],
            "ultimas": actions[-8:],
        },
        "plan": {
            "vivos": [p for p in (state.get("plans") or []) if p.get("live")],
            "rotos": [p for p in (state.get("plans") or []) if p.get("invalidated_by")],
        },
        "cerebro": (state.get("session") or {}).get("cerebro"),
        "enjambre": {
            "regla_peso": _regla_peso(),
            "modo": ((state.get("enjambre") or {}).get("modo")),
            "confianza": ((state.get("enjambre") or {}).get("agentes")),
            "degradado": ((state.get("session") or {}).get("modo_degradado")),
            "cadena": ((state.get("session") or {}).get("cerebro_cadena")),
        },
    }


def _regla_peso() -> str:
    from .confianza import REGLA_PESO
    return REGLA_PESO


def _origin(incidents: list, actions: list, state: dict) -> str:
    for a in reversed(actions):
        o = a.get("origen") or (a.get("params") or {}).get("origen")
        if o:
            return str(o)
    for i in incidents:
        if i.get("origin"):
            return str(i["origin"])
    if state.get("approvals"):
        return "persona"
    return "reglas"


def _avisos(state: dict, incident_id: str | None) -> dict[str, Any]:
    calls = ((state.get("calls") or {}).get("calls") or [])[-8:]
    if incident_id:
        calls = [c for c in calls if c.get("incident") == incident_id]
    return {"llamadas": [{"id": c.get("action_id"), "estado": c.get("result") or c.get("stage"),
                          "recurso": c.get("resource"), "origen": c.get("origen")} for c in calls],
            "agente_hr": any((a.get("origen") or (a.get("params") or {}).get("origen")) == ORIGEN_AGENTE
                             for a in (state.get("actions") or []))}
