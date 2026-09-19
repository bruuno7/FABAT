"""Servidor MCP propio de Mando en `/mcp` (SDK oficial `mcp`, FastMCP, Streamable HTTP dentro de la misma app).

Para que un agente de voz de HappyRobot (o cualquier cliente MCP) pueda leer su orden, confirmarla, preguntar si el plan
ha cambiado durante la llamada (alternativa a Signals), registrar un aviso y consultar el estado de una zona o de una
aprobación. Protegido por `MANDO_MCP_TOKEN` (`Authorization: Bearer …` o `X-Mando-Token`); sin token configurado, 503.

Ninguna tool ejecuta acciones graves (parar, evacuar, cerrar, pedir externos), ni devuelve teléfonos, ni datos de
incidentes `reserved`.
"""
from __future__ import annotations

import hmac
import json
import os
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

INSTRUCTIONS = ("Centro de control MANDO (simulación de un festival). Usa obtener_orden al empezar la llamada, confirmar_orden "
                "UNA vez cuando la persona diga afirmativo o negativo, y hay_cambio_de_plan antes de despedirte.")
_CHANNELS = ("voice", "sms", "whatsapp", "radio", "operator")
_RESERVED_ORDER = "Orden reservada. Acude al punto que te indique el centro de control por canal privado."


def mcp_token() -> str:
    return os.environ.get("MANDO_MCP_TOKEN", "")


class TokenGuard:
    """ASGI: 503 sin `MANDO_MCP_TOKEN`, 401 con token incorrecto; si no, pasa la petición al servidor MCP."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        expected = mcp_token()
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        got = headers.get("authorization", "")
        got = got[7:].strip() if got.lower().startswith("bearer ") else headers.get("x-mando-token", "")
        if not expected:
            return await self._deny(send, 503, "Servidor MCP sin configurar (MANDO_MCP_TOKEN)")
        if not hmac.compare_digest(got.encode(), expected.encode()):
            return await self._deny(send, 401, "Token incorrecto")
        await self.app(scope, receive, send)

    @staticmethod
    async def _deny(send: Any, status: int, msg: str) -> None:
        body = json.dumps({"ok": False, "error": msg}, ensure_ascii=False).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


def build_mcp(get_session: Callable[[], Any], submit_report: Callable[..., dict[str, Any]]) -> FastMCP:
    # Sin estado y con respuesta JSON: cada llamada es un POST suelto, lo más fácil para un cliente ajeno.
    # La protección de «DNS rebinding» del SDK solo admite Host = localhost; aquí la entrada legítima es el túnel
    # (`MANDO_PUBLIC_URL`) y TODA petición exige el token, así que se desactiva.
    mcp = FastMCP("mando", instructions=INSTRUCTIONS, stateless_http=True, json_response=True, streamable_http_path="/mcp",
                  transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False), log_level="WARNING")

    def reserved(s: Any, incident_id: str | None) -> bool:
        return any(i.get("id") == incident_id and (i.get("reserved") or i.get("zone_masked")) for i in s.state().get("incidents", []))

    def zone_id(s: Any, zona: str) -> str | None:
        from .telegram_bot import match_zone
        return match_zone(zona or "", {z["id"]: z["name"] for z in s.festival["zones"]})

    @mcp.tool()
    def obtener_orden(action_id: str) -> dict[str, Any]:
        """Devuelve la orden que hay que decirle a quien contesta: texto, zona, prioridad y cargo. Sin teléfonos."""
        s = get_session()
        call = s.comms.calls.get(action_id)
        p = s.comms.payloads.get(action_id) or {}
        if call is None:
            return {"ok": False, "error": "No existe ninguna orden con ese action_id en esta partida."}
        if reserved(s, call.get("incident")):
            return {"ok": True, "action_id": action_id, "reservado": True, "order_text": _RESERVED_ORDER,
                    "estado": call.get("result") or "en curso"}
        return {"ok": True, "action_id": action_id, "reservado": False,
                "order_text": p.get("order_text") or f"Acude a {p.get('zone_spoken') or 'tu destino'}.",
                "zone_spoken": p.get("zone_spoken") or "", "priority": p.get("priority_label") or "",
                "role": p.get("contact_title") or call.get("to") or "", "estado": call.get("result") or "en curso"}

    @mcp.tool()
    def confirmar_orden(action_id: str, resultado: str, eta_min: int | None = None, motivo: str | None = None) -> dict[str, Any]:
        """Registra la respuesta de quien contesta. resultado: accept | reject | unclear. eta_min: minutos hasta llegar, si los
        ha dicho. motivo: por qué no puede, si rechaza. Llamarla UNA vez; repetirla no cambia nada."""
        s = get_session()
        if action_id not in s.comms.calls:
            return {"ok": False, "error": "No existe ninguna orden con ese action_id en esta partida."}
        if str(resultado).strip().lower() not in ("accept", "reject", "unclear"):
            return {"ok": False, "error": "resultado debe ser accept, reject o unclear."}
        # mismo camino e idempotencia que el webhook `dispatch_progress`/`dispatch_result` de la plataforma
        out = s.comms.on_event({"type": "dispatch_progress" if resultado != "unclear" else "dispatch_result", "action_id": s.comms.wire_payload(action_id)["action_id"],
                                "result": resultado, "eta_min": "" if eta_min is None else str(eta_min), "reason": motivo or "",
                                "channel_used": "mcp", "event_id": f"{action_id}-mcp-{resultado}"})
        with s.lock:
            s._rebuild()
        s._wake.set()
        again = bool(out.get("duplicate") or out.get("already_confirmed") or out.get("ignored"))
        return {"ok": True, "registrada": not again, "ya_estaba_registrada": again, "eta_min": out.get("eta_min")}

    @mcp.tool()
    def hay_cambio_de_plan(action_id: str) -> dict[str, Any]:
        """¿Se ha roto un supuesto del plan DURANTE esta llamada? Si sí, devuelve la orden NUEVA que hay que decir."""
        s = get_session()
        call = s.comms.calls.get(action_id)
        if call is None:
            return {"ok": False, "error": "No existe ninguna orden con ese action_id en esta partida."}
        change = s.comms.plan_changes.get(action_id)
        if change is None:
            return {"ok": True, "hay_cambio": False, "orden_nueva": None}
        if reserved(s, call.get("incident")):
            return {"ok": True, "hay_cambio": True, "orden_nueva": "Cambio de orden. " + _RESERVED_ORDER}
        return {"ok": True, "hay_cambio": True, "orden_nueva": change["text"], "minuto": change["t"]}

    @mcp.tool()
    def registrar_aviso(texto: str, canal: str = "voice", zona: str | None = None) -> dict[str, Any]:
        """Registra un aviso nuevo (lo que cuenta quien llama) en el centro de control. canal: voice | sms | whatsapp | radio.
        Solo crea el aviso: no cierra accesos ni ordena nada."""
        s = get_session()
        texto = (texto or "").strip()
        if not texto:
            return {"ok": False, "error": "Falta el texto del aviso."}
        out = submit_report(canal if canal in _CHANNELS else "voice", texto[:400], zone_id(s, zona) if zona else None,
                            source="agente de voz (MCP)")
        return {"ok": True, "report_id": out["report_id"], "say_text": "Aviso recibido. El centro de control ya lo tiene."}

    @mcp.tool()
    def estado_zona(zona: str) -> dict[str, Any]:
        """Estado observable de una zona del recinto: densidad (personas/m²), ocupación, si está abierta y cuántos
        incidentes abiertos NO reservados hay en ella."""
        s = get_session()
        zid = zone_id(s, zona)
        z = next((x for x in s.state().get("zones", []) if x["id"] == zid), None)
        if z is None:
            return {"ok": False, "error": "No conozco esa zona."}
        live = [i for i in s.state().get("incidents", []) if i.get("zone") == zid and not i.get("reserved")
                and i.get("status") not in ("resolved", "false_alarm", "failed")]
        return {"ok": True, "zona": z["name"], "estado": {"open": "abierta", "restricted": "restringida", "closed": "cerrada"}.get(z["state"], z["state"]),
                "densidad_m2": z["density"], "ocupacion": z["occupancy"], "porcentaje_de_capacidad": round(z["ratio"] * 100),
                "incidentes_abiertos": [{"tipo": i.get("label") or str(i.get("type", "")).replace("_", " "), "prioridad": i.get("priority")}
                                        for i in live[:5]]}

    @mcp.tool()
    def consultar_aprobacion(action_id: str) -> dict[str, Any]:
        """¿Una persona del centro de control ha aprobado esta acción grave? Solo consulta: no aprueba ni ejecuta nada."""
        s = get_session()
        rec = s.approvals.get(action_id)
        pending = any(a.get("id") == action_id for a in s.state().get("approvals", []))
        if rec is None:
            return {"ok": True, "estado": "pendiente" if pending else "desconocida", "aprobada": False}
        return {"ok": True, "estado": "aprobada" if rec.get("ok") else "vetada", "aprobada": bool(rec.get("ok")),
                "por": rec.get("by"), "minuto": rec.get("t")}

    return mcp
