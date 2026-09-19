"""Entrada de avisos: pulseras de demostración, avisos estructurados de los workflows de HappyRobot (`type: public_report`)
y ENTENDIMIENTO DELEGADO (el texto libre se manda al workflow de texto `HR_HOOK_INTAKE` y el aviso entra al mundo cuando
vuelve estructurado; si la plataforma no contesta en `HR_INTAKE_TIMEOUT_S`, entra con el parser propio).

Nada de aquí toca `motor/contracts.py`: `email` y `telegram` no existen en `Channel`, así que viajan como `sms` y
`whatsapp`, y el canal REAL se guarda aparte, por `report_id`, para pintarlo con su icono.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from .comms_happyrobot import EVENTS_PATH, _blank, shared_secret
from .telegram_bot import _plain, match_zone
from . import hr_config

HERE = Path(__file__).resolve().parent
WRISTBANDS_PATH = HERE / "static" / "pulseras.json"

# canal real -> canal del contrato
CONTRACT_CHANNEL = {"voice": "voice", "web_call": "voice", "phone": "voice", "sms": "sms", "email": "sms", "telegram": "whatsapp",
                    "whatsapp": "whatsapp", "web": "whatsapp", "sensor": "sensor", "radio": "radio", "operator": "operator"}
# categoría del AI Classify -> incidente típico, SOLO si las palabras del texto no bastan. «sanitario» no decide gravedad:
# la valoración clínica no sale de un clasificador genérico (IDEA-bruno.md).
CATEGORY_PRESET = {"aglomeracion": "surge", "agresion": "fight", "infraestructura": "barrier"}
# etiquetas de asistencia que suben la prioridad UN escalón. El tipo de acceso (VIP) no la cambia nunca.
PRIORITY_TAGS = ("menor", "movilidad reducida", "alergia grave", "diabetes", "embarazo", "epilepsia", "cardiopatía",
                 "discapacidad visual", "discapacidad auditiva", "persona mayor")

_wristbands: dict[str, dict[str, Any]] | None = None


def wristbands() -> dict[str, dict[str, Any]]:
    global _wristbands
    if _wristbands is None:
        try:
            data = json.loads(WRISTBANDS_PATH.read_text(encoding="utf-8"))
            _wristbands = {str(p["code"]).upper(): p for p in data.get("profiles", [])}
        except (OSError, ValueError, KeyError):
            _wristbands = {}
    return _wristbands


def wristband(code: str | None) -> dict[str, Any] | None:
    """Perfil FICTICIO de una pulsera. Devuelve acceso y etiquetas; nunca una ubicación: la pulsera no localiza a nadie."""
    p = wristbands().get(str(code or "").strip().upper().replace(" ", ""))
    if p is None:
        return None
    tags = [str(t) for t in p.get("tags", [])]
    return {"code": p["code"], "access": p.get("access", "General"), "tags": tags, "role": p.get("role"),
            "raises_priority": any(t in PRIORITY_TAGS for t in tags), "verified_staff": p.get("access") == "Personal"}


def structured_report(ev: dict[str, Any], zones: dict[str, str]) -> dict[str, Any]:
    """`type: public_report` de un workflow de ingesta → argumentos de `Session.report`. Todo llega como cadena."""
    # forma real de la plataforma: `report` {channel, text, zone_hint, source, lang} + `extracted` {location, description,
    # people, responsive, reporter, missing, sensitive, danger_now, breathing_normally}; o los mismos campos en plano
    flat = dict(ev)
    for block in (ev.get("extracted"), ev.get("report")):
        if isinstance(block, dict):
            flat.update({k: v for k, v in block.items() if not _blank(v)})
    for alias, name in (("reporter", "informant"), ("missing", "pending")):
        if _blank(flat.get(name)) and not _blank(flat.get(alias)):
            flat[name] = flat[alias]
    if not _blank(ev.get("channel")):
        flat["channel"] = ev["channel"]   # el canal REAL manda sobre el del bloque `report`
    ev = flat

    def val(k: str) -> str:
        return "" if _blank(ev.get(k)) else str(ev[k]).strip()
    real = {"chat": "web", "chatbot": "web"}.get((val("channel") or "voice").lower(), (val("channel") or "voice").lower())
    text = val("text") or val("description") or val("transcript")[:400]
    location, description = val("location"), val("description")
    if description and _plain(description) not in _plain(text):
        text = f"{text}. {description}" if text else description
    if location and _plain(location) not in _plain(text):
        text = f"{text}. Lugar: {location}."
    if val("responsive").lower() in ("no", "false", "0") and "no responde" not in _plain(text):
        text += " No responde."
    if val("breathing_normally").lower() in ("no", "false", "0") and "no respira" not in _plain(text):
        text += " No respira con normalidad."
    hint = val("zone_hint") if val("zone_hint") in zones else None
    extracted = {k: val(k) for k in ("location", "description", "people", "responsive", "breathing_normally", "danger_now", "informant",
                                     "pending", "category", "sensitive", "instruction_given") if val(k)}
    return {"channel": CONTRACT_CHANNEL.get(real, "whatsapp"), "real_channel": real if real in CONTRACT_CHANNEL else "web",
            "text": text[:400], "zone": hint, "where": hint or match_zone(location, zones),
            "source": (val("informant") or "asistente")[:40], "lang": val("lang") or "es", "extracted": extracted,
            "preset_hint": CATEGORY_PRESET.get(_plain(val("category"))), "reply_to": val("reply_to"), "hr_run_id": val("hr_run_id"),
            "report_ref": val("report_ref"), "partial": str(ev.get("partial")).lower() == "true" or ev.get("final") is False}


_UPDATE_TEXT = {"ubicacion": "Actualización: estoy en {v}.", "location": "Actualización: estoy en {v}.", "que_pasa": "Actualización: {v}.",
                "description": "Actualización: {v}.", "responde": "Actualización: ¿responde? {v}.", "responsive": "Actualización: ¿responde? {v}.",
                "respira_normal": "Actualización: ¿respira con normalidad? {v}.", "breathing_normally": "Actualización: ¿respira con normalidad? {v}.",
                "peligro_ahora": "Actualización: ¿peligro ahora? {v}.", "danger_now": "Actualización: ¿peligro ahora? {v}."}


def update_text(field: str, value: str) -> str:
    """`public_report_update {field, value}` → una frase que Mando sabe leer («¿responde? no» → «no responde»)."""
    f, v = _plain(field).strip(), str(value).strip()[:200]
    if f in ("responde", "responsive") and _plain(v) in ("no", "false"):
        return "Actualización: no responde."
    if f in ("respira_normal", "breathing_normally") and _plain(v) in ("no", "false"):
        return "Actualización: no respira con normalidad."
    return _UPDATE_TEXT.get(f, "Actualización ({f}): {v}.").format(f=field, v=v)


# Lo que el agente de la plataforma REPITE tal cual cuando alguien pregunta «¿ya viene alguien?». Corto, neutro y sin tiempos:
# «ya va un equipo» lo afirma Mando con su estado, no el modelo. Sirve igual para un incidente reservado.
SAY_STATUS = {"unknown": "Tu aviso está en el centro de control.", "open": "Tu aviso está en el centro de control. Se está buscando un equipo.",
              "assigned": "Ya va un equipo hacia ti.", "in_progress": "El equipo ya está en el sitio.",
              "resolved": "El aviso consta como resuelto. Si no es así, dímelo.", "false_alarm": "El aviso consta como cerrado. Si sigue pasando, dímelo.",
              "failed": "Tu aviso está en el centro de control."}


class DelegatedIntake:
    """Manda el texto libre al workflow de texto y espera (poco) a que vuelva estructurado por `/hr/events`."""

    def __init__(self, callback_base: Callable[[], str], on_log: Callable[..., None]) -> None:
        self.callback_base, self.on_log = callback_base, on_log
        self._lock = threading.Lock()
        self._pending: dict[str, dict[str, Any]] = {}
        self._n = 0
        self.stats = {"happyrobot": 0, "local": 0, "late": 0}
        self.workflow_status = hr_config.WorkflowStatus()

    @property
    def hook(self) -> str:
        scoped = 'HR_HOOK_INTAKE_' + hr_config.environment().upper()
        if os.environ.get(scoped):
            return os.environ[scoped].strip()
        if 'HR_HOOK_INTAKE' in os.environ:
            return os.environ['HR_HOOK_INTAKE'].strip()
        return hr_config.workflow_urls()['intake'] if os.environ.get('HR_API_KEY') else ''

    @property
    def timeout_s(self) -> float:
        try:
            return max(0.2, min(10.0, float(os.environ.get("HR_INTAKE_TIMEOUT_S", "6"))))
        except ValueError:
            return 6.0

    def reset(self) -> None:
        with self._lock:
            for slot in self._pending.values():
                slot['timed_out'] = True
                slot['event'].set()
            self.stats = {'happyrobot': 0, 'local': 0, 'late': 0}
            self.workflow_status = hr_config.WorkflowStatus()

    def understand(self, *, text: str, channel: str, source: str, zone_hint: str | None, lang: str) -> tuple[dict[str, Any] | None, str]:
        """Devuelve (evento estructurado | None, por qué). Bloquea como mucho `timeout_s`: llamar SIEMPRE fuera del bucle asyncio."""
        if not self.hook:
            return None, "sin HR_HOOK_INTAKE"
        with self._lock:
            self._n += 1
            key = f"in-{self._n:04d}-{int(time.time()) % 100000}"
            slot = self._pending[key] = {"event": threading.Event(), "ev": None, "timed_out": False, "report_id": None}
        body = {"text": text, "channel": channel, "source": source, "zone_hint": zone_hint or "", "lang": lang, "reply_to": key,
                "callback_url": self.callback_base().rstrip("/") + EVENTS_PATH, "callback_token": shared_secret()}
        headers = {"Content-Type": "application/json"}
        if os.environ.get("HR_API_KEY") and os.environ.get("HR_HOOK_ENHANCED", "1") != "0":
            headers["x-api-key"] = os.environ["HR_API_KEY"]
        t0 = time.monotonic()
        self.workflow_status.record('intake', 'request')
        try:
            resp = httpx.post(self.hook, json=body, headers=headers, timeout=self.timeout_s)
            if resp.status_code >= 300:
                raise httpx.HTTPError(f"HTTP {resp.status_code}")
        except httpx.HTTPError as e:
            self.workflow_status.record('intake', 'error', error=type(e).__name__)
            with self._lock:
                slot["timed_out"] = True
            return None, f"el workflow de texto no responde ({type(e).__name__})"
        slot["event"].wait(max(0.05, self.timeout_s - (time.monotonic() - t0)))
        with self._lock:
            if slot["ev"] is None:
                self.workflow_status.record('intake', 'error', error='Tiempo de espera agotado; comprensión local')
                slot["timed_out"] = True
                return None, f"sin respuesta de HappyRobot en {self.timeout_s:g} s"
            return slot["ev"], "ok"

    def deliver(self, ev: dict[str, Any]) -> str | None:
        """Llega un `public_report` con `reply_to` nuestro. Devuelve "taken" (alguien lo espera), "late" o None (no es nuestro)."""
        key = "" if _blank(ev.get("reply_to")) else str(ev["reply_to"])
        with self._lock:
            slot = self._pending.get(key)
            if slot is None:
                return None
            if slot["timed_out"] or slot["ev"] is not None:
                self.stats["late"] += 1
                return "late"
            slot["ev"] = ev
            self.workflow_status.record('intake', 'event', error='', run_url=ev.get('run_url'))
        slot["event"].set()
        return "taken"

    def remember(self, ev: dict[str, Any] | None, report_id: str) -> None:
        if ev is not None:
            with self._lock:
                slot = self._pending.get(str(ev.get("reply_to") or ""))
                if slot is not None:
                    slot["report_id"] = report_id

    def report_of(self, ev: dict[str, Any]) -> str | None:
        with self._lock:
            return (self._pending.get(str(ev.get("reply_to") or "")) or {}).get("report_id")
