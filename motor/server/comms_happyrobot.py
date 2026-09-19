"""Adaptador de comunicaciones con HappyRobot. Implementa `CommsAPI` en modo HÍBRIDO.

- Solo las acciones cuyo destinatario está en la lista blanca (`contacts.local.json`) salen por
  HappyRobot: POST al «Incoming hook» del workflow que toca (contrato `mando.hr.v1`, cuerpo plano).
- Todo lo demás lo contesta `SimComms`.
- Si el hook falla, o el resultado final no llega en `HR_FALLBACK_S` segundos REALES, la acción cae
  a la simulación y queda escrito en el log: la demo no se puede quedar colgada.
- `poll(t)` devuelve lo simulado más lo que ha llegado por webhook (`on_event`).

- Dos formas de lanzar un workflow, por configuración (`HR_LAUNCH_MODE`): `hook` (POST a `/hooks/{slug}`, cuya
  respuesta no está documentada y por eso no se usa) o `runs` (`POST {HR_API_BASE}/workflows/{id}/runs`, que sí
  devuelve `run_id`). Los webhooks de vuelta traen `hr_run_id` (= `current.run_id`) y se casan con la acción.
- WEB CALL como canal principal de voz (`MANDO_VOICE_MODE=web_call`): la orden no marca ningún teléfono; queda una
  «llamada para <cargo>» con enlace y QR, y el token de LiveKit solo se pide (`POST /voice/tokens/`) cuando esa
  persona descuelga, y solo se entrega a su página. La API key no sale nunca del servidor.
- `signal()` cambia la orden EN PLENA LLAMADA (`POST /signals`, clave `session.<id>`); `takeover_token()` deja a una
  persona escuchar o TOMAR la llamada (`should_takeover`); la transcripción llega en vivo por el SSE de la sesión.

- FASE 3: el despacho (teléfono o llamada web) viaja con EXACTAMENTE los parámetros del trigger de los workflows reales
  (`DISPATCH_PARAMS`); `callback_url` = `MANDO_PUBLIC_URL + /hr/events` y `callback_token` = `HR_SECRET`. Lo que devuelven
  esos workflows (`type: dispatch_result | dispatch_progress`, todo cadenas) se normaliza en `normalize_platform_event`.
- Lista blanca OBLIGATORIA para marcar un teléfono: `MANDO_ALLOWED_NUMBERS`. Sin ella no se marca a nadie.
- En `MANDO_VOICE_MODE=phone`, solo las clases de `MANDO_HR_PHONE_KINDS` (por defecto `dispatch,recall,resupply`)
  salen a la plataforma; ASK/NOTIFY van a SimComms. Además `MANDO_HR_MAX_INFLIGHT` (por defecto 1) evita
  ráfagas de Runs cuando el reloj va a ×16.
- `external_ask`: una pregunta dirigida a un informante que llegó por otro canal propio (bot de Telegram) no pasa por
  HappyRobot ni por la simulación: la contesta esa persona y vuelve por `answer_external`.

URLs y secretos SOLO por variables de entorno (ver README). Nada de eso se escribe en ficheros.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from .validation import webhook
from . import privacy
from . import hr_config

from motor.contracts import ALWAYS_APPROVE, Action, ActionKind, Resource

SCHEMA = "mando.hr.v1"
HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE.parent / "happyrobot" / "webhook_contract.json"
CONTACTS_PATH = HERE / "contacts.local.json"

# Números a los que no se marca jamás, pase lo que pase en la lista blanca.
NEVER_DIAL = {"112", "061", "062", "080", "085", "088", "091", "092", "+34112", "911", "999"}

# Parámetros del trigger de `mando-despacho-telefono` y `mando-despacho-webcall` (leídos de la plataforma el 19-sep).
# En llamada web van como `data` de `POST /voice/tokens/`: si sobra o falta una clave, la plataforma puede devolver 400.
DISPATCH_PARAMS = ("action_id", "to_number", "role", "order_text", "zone_spoken", "priority", "callback_url", "callback_token")
EVENTS_PATH = "/hr/events"

_RESULT_MESSAGES = {"dispatch_result", "clarify_result", "notify_result", "external_result", "followup_result"}
_STAGE_ES = {"call_started": "llamando", "call_answered": "ha descolgado", "fallback_sent": "orden enviada por SMS",
             "approval_verified": "aprobación verificada", "transferred_to_human": "transferida a una persona"}
_KIND_ES = {"security": "seguridad", "medical": "equipo médico", "ambulance": "ambulancia", "tech": "técnicos",
            "logistics": "logística", "volunteer": "voluntarios"}


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return default


def hook_urls() -> dict[str, str]:
    """Una URL por workflow. Se aceptan los nombres del encargo y los del contrato. Cada entorno de la plataforma tiene su
    propia URL de hook: `HR_HOOK_DISPATCH_DEVELOPMENT` (según `HR_ENV`) gana a `HR_HOOK_DISPATCH`."""
    env = hr_config.environment().upper()
    dispatch = hr_config.workflow_urls()["dispatch"]
    return {
        "dispatch": dispatch,
        "ask": _env("HR_HOOK_ASK", "HR_HOOK_CLARIFY", default=dispatch),
        "notify": _env("HR_HOOK_NOTIFY", default=dispatch),
        "external": _env("HR_HOOK_EXTERNAL", default=dispatch),
        "followup": _env("HR_HOOK_FOLLOWUP", default=dispatch),
    }


def api_base() -> str:
    """Clúster por configuración. EU: https://platform.eu.happyrobot.ai/api/v2"""
    return hr_config.api_base()


def workflow_ids() -> dict[str, str]:
    ids = hr_config.workflow_ids()
    return {**ids, **{k: _env('HR_WORKFLOW_' + k.upper(), default=ids['dispatch'])
                     for k in ('ask', 'notify', 'external', 'followup')}}


def shared_secret() -> str:
    return _env("HR_SECRET", "MANDO_HR_TOKEN")


def public_base(default: str = "") -> str:
    """Base pública de este servidor: la de `callback_url` y la del QR. La pone una persona (su túnel), no este código."""
    return _env("MANDO_PUBLIC_URL", "MANDO_CALLBACK_URL", default=default).rstrip("/")


def allowed_numbers() -> set[str]:
    return {normalize_number(x) for x in _env("MANDO_ALLOWED_NUMBERS").split(",") if x.strip()}


def _blank(v: Any) -> bool:
    return v is None or str(v).strip().lower() in ("", "null", "none", "undefined", "n/a", "-")


def _minutes(v: Any) -> int | None:
    """`eta_min` llega como cadena desde la plataforma («3», «3 minutos», «», «null»)."""
    if isinstance(v, bool) or _blank(v):
        return None
    if isinstance(v, (int, float)):
        return int(v) if 0 <= v <= 240 else None
    m = re.search(r"\d{1,3}", str(v))
    return int(m.group(0)) if m and int(m.group(0)) <= 240 else None


_PLATFORM_RESULT = {"accept": "accept", "accepted": "accept", "afirmativo": "accept", "si": "accept", "sí": "accept", "yes": "accept",
                    "reject": "reject", "rejected": "reject", "negativo": "reject", "no": "reject",
                    "unclear": "no_answer", "no_answer": "no_answer", "unknown": "no_answer"}


def normalize_platform_event(ev: dict[str, Any]) -> dict[str, Any]:
    """Lo que mandan de verdad los workflows (`type`, valores en cadena, `result`/`resultado`, `reason`/`motivo`,
    `session_id` = sesión de HAPPYROBOT) → mensaje del contrato `mando.hr.v1`. Un mensaje del contrato pasa sin tocar."""
    kind = str(ev.get("type") or "")
    if kind not in ("dispatch_result", "dispatch_progress"):
        return ev
    out = dict(ev)
    raw = str(ev.get("result") or ev.get("resultado") or "").strip().lower()
    result = _PLATFORM_RESULT.get(raw)
    out["platform_result"] = raw or None
    out["eta_min"] = _minutes(ev.get("eta_min"))
    reason = ev.get("reason") if not _blank(ev.get("reason")) else ev.get("motivo")
    out["reason_text"] = None if _blank(reason) else str(reason)[:200]
    # `session_id` en estos mensajes es la sesión de la plataforma, no la partida de Mando: no sirve para descartar
    hr_session = ev.get("hr_session_id") if not _blank(ev.get("hr_session_id")) else ev.get("session_id")
    out["hr_session_id"] = None if _blank(hr_session) else str(hr_session)
    out.pop("session_id", None)
    if _blank(out.get("hr_run_id")):
        out["hr_run_id"] = None
    if _blank(out.get("action_id")):
        out["action_id"] = None
    if out.get("channel_used") == "phone":
        out["channel_used"] = "voice"
    ref = out.get("hr_run_id") or out.get("action_id") or ""
    if kind == "dispatch_progress":
        out["message"] = "progress"
        out["stage"] = str(ev.get("stage") or "order_confirmed")
        out["final"] = False
        out["early_result"] = result if result in ("accept", "reject") else None
        out.setdefault("event_id", f"{ref}-progress-{raw or 'x'}")
        return out
    out["message"] = "dispatch_result"
    out["final"] = True
    status = str(ev.get("call_status") or "").strip().lower()
    if result is None:  # sin resultado extraído: manda el estado de la llamada; ante la duda, «no contesta» y Mando reintenta
        result = "no_answer"
    out["result"] = result
    out["detail"] = "unclear" if raw == "unclear" else (status or None)
    out.setdefault("event_id", f"{ref}-final")
    return out


def normalize_number(n: str | None) -> str:
    return re.sub(r"[^\d+]", "", n or "")


def load_contacts(path: Path | None = None) -> dict[str, Any]:
    """Lista blanca. Sin fichero = ningún contacto real = todo simulado."""
    p = path or Path(_env("MANDO_CONTACTS", default=str(CONTACTS_PATH)))
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("resources", {})
    data.setdefault("roles", {})
    return data


def _catalogs() -> dict[str, Any]:
    try:
        return json.loads(CONTRACT_PATH.read_text(encoding="utf-8")).get("catalogs", {})
    except (OSError, ValueError):
        return {}


class HappyRobotComms:
    def __init__(self, world: Any, sim: Any, *, session_id: str, mode: str = "sim",
                 contacts: dict[str, Any] | None = None,
                 incident_lookup: Callable[[str | None], dict[str, Any] | None] | None = None,
                 is_approved: Callable[[str], dict[str, Any] | None] | None = None,
                 on_log: Callable[..., None] | None = None,
                 fallback_s: float | None = None, http_timeout_s: float | None = None,
                 ledger: Any = None) -> None:
        self.world, self.sim = world, sim
        self.session_id = session_id
        self.ledger = ledger
        self.mode = mode if mode in ("sim", "happyrobot") else "sim"
        self.contacts = contacts if contacts is not None else load_contacts()
        self.incident_lookup = incident_lookup or (lambda _id: None)
        self.is_approved = is_approved or (lambda _id: None)
        self.on_log = on_log or (lambda *a, **k: None)
        self.fallback_s = max(0.1, min(75.0, float(fallback_s if fallback_s is not None else _env("HR_FALLBACK_S", default="12"))))
        self.http_timeout_s = max(0.1, min(10.0, float(http_timeout_s if http_timeout_s is not None else _env("HR_TIMEOUT_S", default="5"))))
        self.retries = max(0, min(3, int(_env("HR_RETRIES", default="1"))))
        self.callback_url = public_base("http://127.0.0.1:8000")
        self.external_ask: Callable[[Action], Any] | None = None   # ¿esta pregunta es para alguien de un canal nuestro? → "telegram" | "web" | ""
        self.ask_wait_s = self.fallback_s
        self.hooks = hook_urls()
        self.api_base = api_base()
        self.workflows = workflow_ids()
        self.launch_mode = "runs" if _env("HR_LAUNCH_MODE", default="hook") == "runs" else "hook"
        self.voice_mode = "phone" if _env("MANDO_VOICE_MODE", default="web_call") == "phone" else "web_call"
        self.hr_env = hr_config.environment()
        self.disclaimer_s = float(_env("HR_DISCLAIMER_S", default="4"))  # aviso legal UE: suena antes y no es latencia del agente
        # Teléfono PSTN: por defecto solo despacho/recall/resupply. ASK/NOTIFY al mismo hook llenaban Runs sin conversación útil (×16).
        kinds_raw = _env("MANDO_HR_PHONE_KINDS", default="dispatch,recall,resupply")
        self._phone_kinds = {k.strip().lower() for k in kinds_raw.split(",") if k.strip()} or {"dispatch"}
        try:
            self.max_inflight = max(1, min(5, int(_env("MANDO_HR_MAX_INFLIGHT", default="1"))))
        except ValueError:
            self.max_inflight = 1
        cat = _catalogs()
        self._zone_spoken = {k: v.get("spoken", k) for k, v in cat.get("zones", {}).items() if isinstance(v, dict)}
        self._res_spoken = dict(cat.get("resources_spoken", {}))
        self._allowed = allowed_numbers()  # OBLIGATORIA: vacía = no se marca a nadie, esté quien esté en contacts.local.json
        self._warned_no_list = False
        self._warned_inflight = False

        self.revision = 0
        self.workflow_status = hr_config.WorkflowStatus()
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._inbox: list[dict[str, Any]] = []            # resultados reales listos para poll()
        self._inflight: dict[str, dict[str, Any]] = {}    # action_id -> envío real pendiente
        self._seen_events: set[str] = set()
        self._closed: set[str] = set()                    # acciones con resultado final (o caídas a simulación)
        self.calls: dict[str, dict[str, Any]] = {}        # lo que pinta la pantalla, reales y simuladas
        self.payloads: dict[str, dict[str, Any]] = {}     # último cuerpo enviado por acción
        self.webcalls: dict[str, dict[str, Any]] = {}     # call_id (secreto del enlace) -> llamada web pendiente
        self._nonce = secrets.token_hex(8)
        self._wire_to_action: dict[str, str] = {}
        self._run_to_action: dict[str, str] = {}          # hr_run_id -> action_id
        self.wire: dict[str, dict[str, Any]] = {}         # lo que de verdad sale hacia la plataforma, por acción
        self._early: set[str] = set()                     # acciones confirmadas en caliente: el webhook final solo completa
        self.plan_changes: dict[str, dict[str, Any]] = {} # action_id -> orden NUEVA si el plan se rompió durante la llamada
        self.signals: list[dict[str, Any]] = []
        self.stats = {"real_sent": 0, "real_ok": 0, "fallbacks": 0, "hook_rtt_ms": [], "turn_latency_ms": [],
                      "answer_ms": [], "first_word_ms": [], "signal_rtt_ms": [], "test_events": 0, "stale_events": 0,
                      "duplicates": 0}

    def __deepcopy__(self, memo: dict[int, Any]) -> Any:
        """Caos clona a Mando para mirar hacia delante. El clon NUNCA debe poder llamar a nadie de verdad:
        recibe unas comunicaciones simuladas, enganchadas al mundo clonado si ya está en `memo`."""
        import copy
        sim = copy.copy(self.sim)
        sim.world = memo.get(id(self.world), self.world)
        sim.rng = copy.deepcopy(self.sim.rng)
        sim._pending = copy.deepcopy(self.sim._pending)
        memo[id(self)] = sim
        return sim

    # ================================================================ CommsAPI
    def close(self) -> None:
        self._stop.set()
        with self._lock:
            self._closed.update(self._inflight)
            self._inflight.clear()
            self._inbox.clear()
            self.webcalls.clear()
            self._wire_to_action.clear()
            self._run_to_action.clear()

    def _ledger_event(self, event_type: str, action_id: str | None = None,
                      payload: dict[str, Any] | None = None) -> None:
        led = self.ledger
        if led is None:
            return
        try:
            led.append_event(self.session_id, event_type, action_id, payload)
        except Exception:
            pass

    def _ledger_episode(self, action_id: str, *, result: str | None = None, fell_back: bool = False,
                        text: str = "", real: bool | None = None) -> None:
        led = self.ledger
        if led is None or not action_id:
            return
        call = self.calls.get(action_id) or {}
        flight = self._inflight.get(action_id) or {}
        answer_ms = call.get("answer_ms")
        if answer_ms is None and flight.get("answered_at") and flight.get("started"):
            answer_ms = round((flight["answered_at"] - flight["started"]) * 1000)
        hook_rtt = self.stats["hook_rtt_ms"][-1] if self.stats.get("hook_rtt_ms") else None
        is_real = bool(call.get("real")) if real is None else real
        if fell_back:
            is_real = False
        resource_id = str(call.get("resource") or "")
        resource_kind = ""
        if resource_id:
            try:
                res_obj = getattr(self.world, "resources", {}).get(resource_id)
                if res_obj is not None:
                    resource_kind = str(getattr(res_obj, "kind", "") or "")
            except Exception:
                resource_kind = ""
        try:
            t_sim = call.get("t")
            if t_sim is None:
                t_sim = getattr(self.world, "t", None)
            seed_val = getattr(self.world, "seed", None)
            led.upsert_episode(
                self.session_id, action_id,
                kind=str(call.get("kind") or ""),
                zone=str(call.get("zone") or ""),
                resource=resource_id,
                resource_kind=resource_kind,
                real=is_real,
                result=result if result is not None else call.get("result"),
                eta_min=call.get("eta_min"),
                fell_back=fell_back or bool(call.get("fell_back")),
                answer_ms=answer_ms,
                hook_rtt_ms=hook_rtt,
                text=text or str(call.get("text") or ""),
                t=int(t_sim) if t_sim is not None else None,
                seed=int(seed_val) if seed_val is not None else None,
            )
        except Exception:
            pass

    def send(self, action: Action, resource: Resource | None = None) -> None:
        if self._stop.is_set():
            return
        name = resource.name if resource is not None else str(action.params.get("to") or "destinatario")
        call = {"action_id": action.id, "kind": str(action.kind), "to": name, "resource": action.resource,
                "incident": action.incident, "zone": action.zone, "channel": str(action.channel or "voice"),
                "real": False, "stage": "llamando", "result": None, "eta_min": None, "text": "",
                "t": self.world.t, "t_end": None, "fell_back": False, "started": time.monotonic()}
        with self._lock:
            self.calls[action.id] = call
        if action.kind == ActionKind.ASK and self.external_ask is not None and self._ask_outside(action, call):
            return
        route = self._real_route(action, resource)
        if route is None:
            self._ledger_event("send_sim", action.id, {"kind": str(action.kind), "zone": action.zone,
                                                       "resource": action.resource, "reason": "no_real_route"})
            with self._lock:
                self.sim.send(action, resource)
            return
        hook, payload = route
        call["real"] = True
        call["title"] = payload.get("contact_title") or name
        with self._lock:
            self._inflight[action.id] = {"action": action, "resource": resource, "started": time.monotonic(),
                                         "deadline": time.monotonic() + self.fallback_s}
            self.payloads[action.id] = payload
            self.stats["real_sent"] += 1
        self._ledger_event("send_real", action.id, {"kind": str(action.kind), "zone": action.zone,
                                                    "resource": action.resource,
                                                    "channel": "webcall" if hook == "webcall" else "hook"})
        if hook == "webcall":
            call_id = secrets.token_urlsafe(9)
            call.update(web_call=True, stage="esperando a que descuelgue", channel="voice")
            with self._lock:
                self.webcalls[call_id] = {"call_id": call_id, "action_id": action.id, "title": call["title"],
                                          "order_text": payload.get("order_text", ""), "answered": False, "t": self.world.t}
            call["call_id"] = call_id
            self.on_log("action", f"LLAMADA WEB para {call['title']} ({action.id}): esperando a que descuelgue", action.id, real=True)
            return
        self.on_log("action", f"HappyRobot: {payload['message']} a {name} ({action.id})", action.id, real=True)
        threading.Thread(target=self._post, args=(action.id, hook, self.wire_payload(action.id)), daemon=True).start()

    def _ask_outside(self, action: Action, call: dict[str, Any]) -> bool:
        """La pregunta va a quien avisó por un canal propio (Telegram). Si no contesta en `fallback_s`, cae a simulación."""
        try:
            channel = self.external_ask(action)
        except Exception:
            channel = ""
        if not channel:
            return False
        channel = channel if isinstance(channel, str) else "telegram"
        where = {"telegram": "Telegram", "web": "su página"}.get(channel, channel)
        call.update(real=True, channel=channel, stage="pregunta enviada", title=f"quien avisó por {where}")
        with self._lock:
            self._inflight[action.id] = {"action": action, "resource": None, "started": time.monotonic(),
                                         "deadline": time.monotonic() + getattr(self, "ask_wait_s", self.fallback_s), "external": True}
        self.on_log("action", f"Pregunta a quien avisó, por {where} ({action.id})", action.id, real=True)
        return True

    def _fall_back_reason(self, action_id: str) -> str:
        return "quien avisó no contesta" if (self._inflight.get(action_id) or {}).get("external") else ""

    def answer_external(self, action_id: str, text: str, channel: str = "telegram") -> bool:
        """La persona ha contestado a la pregunta: entra a Mando como cualquier respuesta de comunicaciones."""
        with self._lock:
            if action_id in self._closed or action_id not in self._inflight:
                return False
        out = self.on_event({"message": "clarify_result", "action_id": action_id, "result": "answer", "final": True,
                             "text": str(text)[:400], "channel_used": channel, "event_id": f"{action_id}-{channel}-answer"})
        return bool(out.get("ok")) and not out.get("ignored")

    def wire_payload(self, action_id: str) -> dict[str, Any]:
        """Lo que sale hacia la plataforma. Despacho: SOLO los parámetros del trigger real. Resto: contrato `mando.hr.v1`."""
        p = self.payloads.get(action_id) or {}
        wire_id = f"{self._nonce}:{action_id}"
        with self._lock:
            self._wire_to_action[wire_id] = action_id
        wire = {"action_id": wire_id, "to_number": p.get("to_number") or "",
                "role": p.get("contact_title") or p.get("resource_spoken") or p.get("recipient_role") or p.get("contact_role") or "responsable",
                "order_text": p.get("order_text") or p.get("question_text") or p.get("message_text") or p.get("parte_text") or "",
                "zone_spoken": p.get("zone_spoken") or self._zone_name((self.calls.get(action_id) or {}).get("zone")),
                "priority": p.get("priority_label") or "amarilla",
                "callback_url": self.callback_url.rstrip("/") + EVENTS_PATH, "callback_token": shared_secret()}
        assert tuple(wire) == DISPATCH_PARAMS
        if (self.calls.get(action_id) or {}).get("web_call"):
            del wire["to_number"]   # el trigger Web call declara las otras siete: si sobra o falta una clave, /voice/tokens/ da 400
        with self._lock:
            self.wire[action_id] = {k: "(oculto)" if k in ("to_number", "callback_token") and v else v for k, v in wire.items()}
        return wire

    def poll(self, t: int) -> list[dict[str, Any]]:
        self.sweep()
        with self._lock:
            out = list(self.sim.poll(t))
            real, self._inbox = self._inbox, []
        for item in real:
            item["t"] = self.world.t  # el reloj de la simulación es nuestro: lo pone el adaptador
        out.extend(real)
        for item in out:
            self._track_result(item)
        return out

    # ================================================================ ruta real
    def _real_route(self, action: Action, resource: Resource | None) -> tuple[str, dict[str, Any]] | None:
        if self.mode != "happyrobot":
            return None
        kind = action.kind
        entry: dict[str, Any] | None = None
        if resource is not None:
            entry = self.contacts["resources"].get(resource.id)
        else:
            to = str(action.params.get("to") or action.params.get("kind") or "")
            entry = self.contacts["roles"].get(to)
        if isinstance(entry, str):
            entry = {"to_number": entry}
        if not entry:
            return None
        voice = kind in (ActionKind.DISPATCH, ActionKind.RECALL, ActionKind.RESUPPLY, ActionKind.ASK, ActionKind.NOTIFY)
        if voice and self.voice_mode == "web_call":
            if not (self.api_base and _env("HR_API_KEY") and self.workflows["webcall"]):
                return None
            build = self._clarify_payload if kind == ActionKind.ASK else self._notify_payload if kind == ActionKind.NOTIFY else self._dispatch_payload
            payload = build(action, resource, entry, "")
            payload["to_number"] = None
            return "webcall", payload
        if self.voice_mode == "phone" and str(kind).lower() not in self._phone_kinds:
            return None  # ASK/NOTIFY/… → SimComms; evita Runs basura en el Outbound Voice Agent
        if not entry.get("to_number"):
            return None
        number = normalize_number(entry["to_number"])
        if number in NEVER_DIAL or number.lstrip("+") in NEVER_DIAL or not re.fullmatch(r"\+[1-9]\d{7,14}", number):
            self.on_log("action", f"Número bloqueado para {action.id}: no se marca. Sigue en simulación", action.id)
            return None
        if not self._allowed:
            if not self._warned_no_list:
                self._warned_no_list = True
                self.on_log("action", "MANDO_ALLOWED_NUMBERS sin configurar: no se marca a NADIE. Todo sigue en simulación")
            return None
        if number not in self._allowed:
            self.on_log("action", f"Número fuera de la lista blanca para {action.id}. Sigue en simulación", action.id)
            return None
        with self._lock:
            pstn_inflight = sum(1 for meta in self._inflight.values() if not meta.get("external"))
        if pstn_inflight >= self.max_inflight:
            if not self._warned_inflight:
                self._warned_inflight = True
                self.on_log("action",
                            f"Ya hay {pstn_inflight} llamada(s) real(es) en curso (máx. {self.max_inflight}): "
                            f"{action.id} sigue en simulación. Sube MANDO_HR_MAX_INFLIGHT solo si hace falta.")
            return None
        if kind in (ActionKind.DISPATCH, ActionKind.RECALL, ActionKind.RESUPPLY):
            hook, build = self.hooks["dispatch"], self._dispatch_payload
        elif kind == ActionKind.ASK:
            follow = bool(action.params.get("followup"))
            hook = self.hooks["followup"] if follow else self.hooks["ask"]
            build = self._followup_payload if follow else self._clarify_payload
        elif kind == ActionKind.NOTIFY:
            hook, build = self.hooks["notify"], self._notify_payload
        elif kind == ActionKind.REQUEST_EXTERNAL:
            hook, build = self.hooks["external"], self._external_payload
        else:
            return None
        if self.launch_mode == "runs":
            slot = {self._dispatch_payload: "dispatch", self._clarify_payload: "ask", self._followup_payload: "followup",
                    self._notify_payload: "notify", self._external_payload: "external"}[build]
            wf = self.workflows.get(slot)
            hook = f"{self.api_base}/workflows/{wf}/runs" if (wf and self.api_base and _env("HR_API_KEY")) else ""
        if not hook:
            return None
        if kind in ALWAYS_APPROVE and not self.is_approved(action.id):
            # segundo cerrojo: sin aprobación humana registrada, esto no sale del edificio
            self.on_log("approval", f"BLOQUEADO: {action.id} ({kind}) sin aprobación registrada. No se envía", action.id)
            return None
        payload = build(action, resource, entry, number)
        return hook, payload

    def _envelope(self, action: Action, message: str, kind: str | None = None) -> dict[str, Any]:
        return {"schema": SCHEMA, "message": message, "session_id": self.session_id, "action_id": action.id,
                "kind": kind or str(action.kind), "t": int(self.world.t), "autonomy": str(action.autonomy),
                "callback_url": self.callback_url, "mode": "live", "lang": str(action.params.get("lang") or "es")}

    def _zone_name(self, zone: str | None) -> str:
        if not zone:
            return "zona sin confirmar"
        return self._zone_spoken.get(zone) or zone.replace("_", " ")

    def _incident(self, action: Action) -> dict[str, Any]:
        return self.incident_lookup(action.incident) or {}

    @staticmethod
    def _priority_label(severity: int) -> str:
        return "roja" if severity >= 8 else "amarilla" if severity >= 5 else "verde"

    def _dispatch_payload(self, a: Action, r: Resource | None, entry: dict[str, Any], number: str) -> dict[str, Any]:
        inc = self._incident(a)
        sev = int(inc.get("severity") or a.params.get("severity") or 5)
        label = self._priority_label(sev)
        zone = a.zone or inc.get("zone")
        zname = self._zone_name(zone)
        what = str(inc.get("label") or inc.get("type") or "incidente").replace("_", " ")
        recall = a.kind == ActionKind.RECALL
        if recall:
            order = f"Deja lo que estás haciendo: te necesitamos en otro incidente. Prioridad {label}."
        elif a.kind == ActionKind.RESUPPLY:
            order = f"Lleva agua a {zname}. Prioridad {label}."
        else:
            order = f"{what.capitalize()} en {zname}. Prioridad {label}. Acude ya."
        p = self._envelope(a, "dispatch_request", "recall" if recall else "dispatch")
        p.update({
            "to_number": number, "resource_id": r.id if r else "", "resource_kind": str(r.kind) if r else "",
            "resource_spoken": self._res_spoken.get(r.id if r else "", r.name if r else ""),
            "leader_name": entry.get("leader_name"), "resource_zone_spoken": self._zone_name(r.zone if r else None),
            "incident_id": a.incident or "", "incident_type": inc.get("type"), "incident_type_spoken": what,
            "zone_id": zone, "zone_spoken": zname, "zone_detail": a.params.get("zone_detail"),
            "severity": sev, "priority": inc.get("priority"), "priority_label": label,
            "order_text": order, "access_hint": a.params.get("access_hint"),
            "sms_text": f"MANDO {a.id}: {what} en {zname.upper()}. Prioridad {label.upper()}. Responde 1 VOY o 2 NO PUEDO.",
            "recall_from_spoken": None, "max_attempts": 1, "ring_timeout_s": 25, "fallback_channel": "sms",
            "sms_reply_timeout_s": 90,
            # quien contesta tiene CARGO: «Jefe de seguridad de sector 2», no «Seguridad 2»
            "contact_title": entry.get("title") or (f"Jefe de {_KIND_ES.get(str(r.kind), 'equipo')} · {r.name}" if r else ""),
        })
        return p

    def _clarify_payload(self, a: Action, r: Resource | None, entry: dict[str, Any], number: str) -> dict[str, Any]:
        p = self._envelope(a, "clarify_request")
        p['contact_title'] = entry.get('title') or (f"Jefe de {_KIND_ES.get(str(r.kind), 'equipo')} · {r.name}" if r else entry.get('role', 'responsable'))
        channel = str(a.channel or "voice")
        reports = a.params.get("reports") or []
        p.update({
            "to_number": number, "channel": channel if channel in ("voice", "sms", "whatsapp") else "voice",
            "contact_role": entry.get("role", "staff"), "contact_name": entry.get("leader_name"),
            "report_id": reports[0] if reports else a.params.get("report"), "incident_id": a.incident,
            "context_text": a.why, "question_key": str(a.params.get("purpose") or "detail"),
            "question_text": str(a.params.get("message") or a.why), "answer_type": str(a.params.get("answer_type") or "free"),
            "options_spoken": a.params.get("options_spoken"), "max_attempts": 1, "reply_timeout_s": 120,
        })
        return p

    def _followup_payload(self, a: Action, r: Resource | None, entry: dict[str, Any], number: str) -> dict[str, Any]:
        inc = self._incident(a)
        zone = a.zone or inc.get("zone")
        p = self._envelope(a, "followup_request", "ask")
        p.update({
            "to_number": number, "channel": "voice", "resource_id": r.id if r else "",
            "resource_spoken": self._res_spoken.get(r.id if r else "", r.name if r else ""),
            "leader_name": entry.get("leader_name"), "incident_id": a.incident or "",
            "incident_type_spoken": str(inc.get("label") or inc.get("type") or "incidente").replace("_", " "),
            "zone_id": zone, "zone_spoken": self._zone_name(zone),
            "dispatch_action_id": a.params.get("dispatch_action_id"), "followup_kind": a.params.get("followup_kind", "arrival"),
            "promised_eta_min": a.params.get("promised_eta_min"), "minutes_since_dispatch": a.params.get("minutes_since_dispatch"),
            "question_text": str(a.params.get("message") or f"¿Has llegado a {self._zone_name(zone)}?"),
            "sms_text": f"MANDO {a.id}: ¿llegaste a {self._zone_name(zone).upper()}? Responde 1 EN EL SITIO, 2 EN CAMINO, "
                        "3 RESUELTO, 4 NECESITO APOYO.",
            "max_attempts": 1, "ring_timeout_s": 25,
        })
        return p

    def _notify_payload(self, a: Action, r: Resource | None, entry: dict[str, Any], number: str) -> dict[str, Any]:
        p = self._envelope(a, "notify_request")
        p['contact_title'] = entry.get('title') or (f"Jefe de {_KIND_ES.get(str(r.kind), 'equipo')} · {r.name}" if r else entry.get('role', 'responsable'))
        channel = str(a.channel or "sms")
        p.update({"to_number": number, "channel": channel if channel in ("voice", "sms", "whatsapp") else "sms",
                  "recipient_role": entry.get("role", "staff"),
                  "message_text": str(a.params.get("message") or a.why), "requires_ack": bool(a.params.get("requires_ack"))})
        return p

    def _external_payload(self, a: Action, r: Resource | None, entry: dict[str, Any], number: str) -> dict[str, Any]:
        inc = self._incident(a)
        ap = self.is_approved(a.id) or {}
        zname = self._zone_name(a.zone or inc.get("zone"))
        what = str(inc.get("label") or inc.get("type") or "incidente").replace("_", " ")
        control = normalize_number(str(self.contacts["roles"].get("control") or "")) or number
        p = self._envelope(a, "external_request")
        fields = {
            "m_major_declared": False,
            "e_exact_location": f"Festival Abierto. {zname.capitalize()}.",
            "t_type": what.capitalize() + ".",
            "h_hazards": str(a.params.get("hazards") or "Sin peligros añadidos confirmados."),
            "a_access": str(a.params.get("access") or "Entrada de vehículos por pasillo sur desde puerta C."),
            "n_casualties": str(a.params.get("casualties") or "Cifra sin cerrar."),
            "e_resources": f"Se pide: {a.params.get('kind', 'apoyo')}. {a.params.get('reason', '')}".strip(),
        }
        p.update(fields)
        p.update({
            "to_number": number, "service_label": str(entry.get("service_label") or a.params.get("kind") or "externo"),
            "approval_id": ap.get("approval_id", ""), "approved_by": ap.get("by", ""), "approved_t": ap.get("t", 0),
            "incident_id": a.incident,
            "parte_text": "Parte de Festival Abierto, centro de control. Incidente mayor: no declarado. "
                          f"Lugar: {fields['e_exact_location']} Tipo: {fields['t_type']} Peligros: {fields['h_hazards']} "
                          f"Acceso: {fields['a_access']} Afectados: {fields['n_casualties']} Recursos: {fields['e_resources']}",
            "callback_number": control, "control_center_number": control,
        })
        return p

    def _post(self, action_id: str, hook: str, payload: dict[str, Any]) -> None:
        self.workflow_status.record('dispatch', 'request')
        headers = {"Content-Type": "application/json"}
        key = _env("HR_API_KEY")
        body: dict[str, Any] = payload
        if self.launch_mode == "runs":
            headers["Authorization"] = f"Bearer {key}"
            body = {"payload": payload, "environment": self.hr_env}
        elif key and _env("HR_HOOK_ENHANCED", default="1") != "0":
            headers["x-api-key"] = key  # solo hace falta con «Enhanced Security» en el trigger; si no, se ignora
        err = ""
        for attempt in range(self.retries + 1):
            if self._stop.is_set() or action_id in self._closed:
                return
            t0 = time.monotonic()
            try:
                resp = httpx.post(hook, json=body, headers=headers, timeout=self.http_timeout_s)
                if resp.status_code < 300:
                    with self._lock:
                        self.stats["hook_rtt_ms"].append(round((time.monotonic() - t0) * 1000))
                        self.stats["real_ok"] += 1
                    try:  # `/runs` devuelve run_id; la respuesta del hook no está documentada: si lo trae, se aprovecha
                        data = resp.json()
                        queued = data.get("queued_run_ids") if isinstance(data, dict) else None
                        run_id = (data.get("run_id") or (queued[0] if isinstance(queued, list) and queued else "")) if isinstance(data, dict) else ""
                        self._bind_run(action_id, str(run_id or ""))
                        self.workflow_status.record('dispatch', 'response', error='', run_url=data.get('run_url'))
                    except (ValueError, AttributeError):
                        pass
                    return
                err = f"HTTP {resp.status_code}"
            except httpx.HTTPError as e:  # timeout, conexión rechazada, DNS
                err = type(e).__name__
            if attempt < self.retries:
                self._stop.wait(0.4)
        self._fall_back(action_id, f"el hook no responde ({err})")
        self.workflow_status.record('dispatch', 'error', error=err)

    # ================================================================ caída a simulación
    def sweep(self) -> None:
        """Pasa a simulación las llamadas reales que llevan demasiado sin resultado. Lo llama `poll` y
        también el servidor con el reloj en pausa."""
        now = time.monotonic()
        with self._lock:
            late = [aid for aid, f in self._inflight.items() if now > f["deadline"]]
        for aid in late:
            self._fall_back(aid, self._fall_back_reason(aid) or f"sin resultado en {self.fallback_s:.0f} s")

    def _fall_back(self, action_id: str, why: str) -> None:
        with self._lock:
            if action_id in self._closed:
                return
            flight = self._inflight.pop(action_id, None)
            if flight is None:
                return
            self._closed.add(action_id)
            self.stats["fallbacks"] += 1
            self.revision += 1
            call = self.calls.get(action_id)
            if call:
                call.update(real=False, fell_back=True, stage="cae a simulación")
            if flight.get("external"):
                if call:
                    call.update(real=True, fell_back=False, stage="sin respuesta")
                self._inbox.append({"action_id": action_id, "result": "no_answer", "text": "Sin respuesta de la persona",
                                    "t": self.world.t, "data": {}, "channel": (call or {}).get("channel")})
            else:
                self.sim.send(flight["action"], flight["resource"])
        self._ledger_event("fallback", action_id, {"why": why, "external": bool(flight.get("external"))})
        self._ledger_episode(action_id, result="no_answer" if flight.get("external") else None,
                             fell_back=not flight.get("external"),
                             real=False if not flight.get("external") else True,
                             text=why)
        who = "Sin respuesta" if flight.get("external") else "HappyRobot no contesta"
        suffix = "Se sigue con la información disponible" if flight.get("external") else "Se sigue en SIMULACIÓN"
        self.on_log("outcome", f"{who} para {action_id}: {why}. {suffix}", action_id, fallback=not flight.get("external"))

    # ================================================================ webhooks entrantes
    def on_event(self, ev: dict[str, Any]) -> dict[str, Any]:
        if self._stop.is_set():
            return {'ok': True, 'stale': True}
        ev = webhook(ev)
        with self._lock:
            out = self._on_event(ev)
            if not out.get('stale'):
                self.workflow_status.record('webcall' if ev.get('channel_used') == 'web_call' else 'dispatch', 'event',
                                            run_url=ev.get('run_url'))
            self.revision += 1
            return out

    def _on_event(self, ev: dict[str, Any]) -> dict[str, Any]:
        """Procesa un mensaje `progress` o `*_result` (del contrato, o el que mandan de verdad los workflows: `type`).
        Devuelve el cuerpo de respuesta del webhook."""
        platform = bool(ev.get("type"))
        ev = normalize_platform_event(webhook(ev))
        event_id = str(ev.get("event_id") or "")
        message = str(ev.get("message") or "")
        action_id = str(ev.get("action_id") or "")
        run_id = str(ev.get("hr_run_id") or ev.get("run_id") or "")
        issued = self._wire_to_action.get(action_id)
        known_run = self._run_to_action.get(run_id) if run_id else None
        if platform and not issued and not known_run:
            self.stats["stale_events"] += 1
            self._ledger_event("stale", action_id or None, {"message": message, "run_id": run_id})
            return {"ok": True, "stale": True}
        if issued:
            action_id = issued
        if run_id:
            if known_run and (not action_id or action_id == known_run):
                action_id = known_run
            elif not known_run and issued:
                # El callback devuelve el nonce que SOLO emitió esta partida.
                self._bind_run(action_id, run_id, ev.get("hr_session_id"))
            else:
                self.stats["stale_events"] += 1
                return {"ok": True, "stale": True}
        with self._lock:
            if event_id and event_id in self._seen_events:
                self.stats["duplicates"] += 1
                self._ledger_event("duplicate", action_id or None, {"event_id": event_id, "message": message})
                return {"ok": True, "duplicate": True}
            if event_id:
                self._seen_events.add(event_id)
        if ev.get("mode") == "test":
            self.stats["test_events"] += 1
            self.on_log("action", f"HappyRobot (modo test, no afecta al mundo): {message} {action_id}", action_id or None)
            return {"ok": True, "duplicate": False}
        if ev.get("session_id") and ev["session_id"] != self.session_id:
            self.stats["stale_events"] += 1
            self.on_log("action", f"Mensaje de una sesión anterior descartado ({message} {action_id})", action_id or None)
            return {"ok": True, "duplicate": False, "stale": True}

        self._latency_from(ev)
        if action_id and action_id not in self.calls:
            self.on_log("action", f"HappyRobot habla de una acción que no es de esta partida ({message} {action_id}): se ignora", None)
            return {"ok": True, "duplicate": False, "unknown_action": True}
        if message == "progress" and ev.get("early_result"):
            if (self.calls.get(action_id) or {}).get('kind') == 'ask':
                return {'ok': True, 'awaiting_answer': True}
            return self._early_result(action_id, ev)
        if message == "progress":
            stage = str(ev.get("stage") or "")
            with self._lock:
                call = self.calls.get(action_id)
                flight = self._inflight.get(action_id)
                if call:
                    call["stage"] = _STAGE_ES.get(stage, stage)
                    if ev.get("channel_used"):
                        call["channel"] = "voice" if ev["channel_used"] == "web_call" else ev["channel_used"]
                if flight and stage == "call_answered":
                    ms = round((time.monotonic() - flight["started"]) * 1000)
                    self.stats["answer_ms"].append(ms)
                    flight["answered_at"] = time.monotonic()
                    if call:
                        call["answer_ms"] = ms
            self.on_log("action", f"HappyRobot {action_id}: {_STAGE_ES.get(stage, stage)}"
                        + (f" — {ev['text']}" if ev.get("text") else ""), action_id, real=True)
            self._ledger_event("progress", action_id, {"stage": stage})
            return {"ok": True, "duplicate": False}

        if message == "transcript":  # línea suelta de la conversación (desde un Tool node o desde el SSE de la sesión)
            self._say(action_id, str(ev.get("role") or "agent"), str(ev.get("text") or ev.get("content") or ""))
            return {"ok": True, "duplicate": False}

        if message in _RESULT_MESSAGES:
            if platform and (self.calls.get(action_id) or {}).get('kind') == 'ask':
                self._transcript_from(action_id, ev.get('transcript'))
                words = [line['text'] for line in self.calls[action_id].get('transcript', []) if line['who'] == 'persona']
                ev['result'] = 'answer' if words else 'no_answer'
                ev['text'] = ' '.join(words)
            with self._lock:
                if action_id in self._closed:
                    late = True
                else:
                    late = False
                    if ev.get("final", True):
                        self._closed.add(action_id)
                        self._inflight.pop(action_id, None)
            if late and action_id in self._early:
                # ya se confirmó en caliente (resultado PROVISIONAL): el final completa la ficha y, si la persona se echó
                # atrás después de confirmar, CORRIGE: vale lo último que dijo
                self._early.discard(action_id)
                self._transcript_from(action_id, ev.get("transcript"))
                with self._lock:
                    call = self.calls.get(action_id)
                    if call is not None and ev.get("call_status"):
                        call["call_status"] = str(ev["call_status"])[:40]
                    before = (call or {}).get("early_result")
                final = str(ev.get("result") or "")
                if ev.get("platform_result") in ("accept", "reject") and before in ("accept", "reject") and final != before:
                    item = self._result_item(action_id, final, ev, ev.get("channel_used") or "voice", {"real": True, "corrects": before})
                    with self._lock:
                        self._inbox.append(item)
                    self.on_log("outcome", f"HappyRobot CORRIGE {action_id}: en caliente dijo «{before}» y al colgar «{final}». Vale lo último", action_id, real=True)
                    return {"ok": True, "duplicate": False, "already_confirmed": True, "corrected": True, "result": final}
                return {"ok": True, "duplicate": False, "already_confirmed": True}
            if late:
                self.on_log("action", f"Resultado tardío de HappyRobot para {action_id}: se ignora (ya estaba cerrada)", action_id)
                return {"ok": True, "duplicate": False, "ignored": True}
            if not ev.get("final", True) and int(ev.get("seq") or 0) < 1:
                return {"ok": True, "duplicate": False}
            channel = ev.get("channel_used")
            data = dict(ev.get("data") or {})
            for k in ("hr_run_id", "call_duration_s", "confirmed_by_repetition", "reason_text", "new_info_text",
                      "answer_value", "zone_id", "status_code", "needs", "new_eta_min", "external_ref", "attempts",
                      "extra_info_text", "question_key"):
                if ev.get(k) is not None:
                    data[k] = ev[k]
            if channel == "web_call":
                channel, data["web_call"] = "voice", True
            data["real"] = True
            if str(ev.get("result")) == "answer" and not any(k in data for k in ("exists", "zone", "type", "severity")):
                data = {}   # respuesta en texto libre: Mando solo la LEE (su parser) si `data` llega vacío
            self._transcript_from(action_id, ev.get("transcript"))
            item = self._result_item(action_id, str(ev.get("result") or "no_answer"), ev, channel, data)
            if item['result'] == 'answer' and platform and (self.calls.get(action_id) or {}).get('kind') == 'ask':
                item['data'] = {}
            with self._lock:
                self._inbox.append(item)
            self._ledger_event("result", action_id, {"result": item["result"], "eta_min": item.get("eta_min")})
            self._ledger_episode(action_id, result=item["result"], text=str(item.get("text") or ""), real=True)
            return {"ok": True, "duplicate": False, "result": item["result"], "eta_min": item["eta_min"]}
        return {"ok": False, "duplicate": False, "error": "unknown_message"}

    def _result_item(self, action_id: str, result: str, ev: dict[str, Any], channel: Any, data: dict[str, Any]) -> dict[str, Any]:
        """El `poll()` que verá Mando. Si la persona aceptó sin decir minutos, la ETA la ESTIMA el backend (y se dice)."""
        eta, text = ev.get("eta_min"), str(ev.get("text") or "")
        if ev.get("platform_result") is not None:
            data["platform_result"] = ev["platform_result"]
            if ev["platform_result"] == "unclear":
                data["unclear"] = True
        for k in ("call_status",):
            if ev.get(k):
                data[k] = str(ev[k])[:40]
        if result == "accept" and eta is None and ev.get("platform_result") is not None:
            eta = self._estimate_eta(action_id)
            if eta is not None:
                data["eta_estimated"] = True
        if not text and ev.get("platform_result") is not None:
            if result == "accept":
                text = (f"Afirmativo. {eta} min." if eta is not None and not data.get("eta_estimated")
                        else f"Afirmativo. Unos {eta} min (ETA estimada por el centro de control)." if eta is not None else "Afirmativo.")
            elif result == "reject":
                text = "Negativo" + (f": {ev['reason_text']}" if ev.get("reason_text") else ".")
            else:
                text = "Respuesta no clara: cuenta como que no contesta." if data.get("unclear") else "No contesta."
        return {"action_id": action_id, "result": result, "text": text, "t": self.world.t, "eta_min": eta,
                "detail": ev.get("detail"), "reason_code": ev.get("reason_code"), "channel": channel, "data": data}

    def _estimate_eta(self, action_id: str) -> int | None:
        with self._lock:
            flight = self._inflight.get(action_id) or {}
            call = self.calls.get(action_id) or {}
        resource = flight.get("resource")
        try:
            r = resource or self.world.observe().resources.get(call.get("resource"))
            return self.world.travel_time(r.zone, call.get("zone"), r.id) if r is not None and call.get("zone") else None
        except Exception:
            return None

    def _early_result(self, action_id: str, ev: dict[str, Any]) -> dict[str, Any]:
        """`dispatch_progress` con AFIRMATIVO/NEGATIVO dentro de la llamada (tool `confirmar_orden` del agente de voz o del
        MCP): Mando lo sabe YA, sin esperar a que cuelguen. El `dispatch_result` del final solo completa la ficha."""
        with self._lock:
            if action_id in self._closed:
                return {"ok": True, "duplicate": False, "already_confirmed": True}
            flight = self._inflight.get(action_id)
        data: dict[str, Any] = {"real": True, "early": True}
        if ev.get("hr_run_id"):
            data["hr_run_id"] = ev["hr_run_id"]
        if ev.get("reason_text"):
            data["reason_text"] = ev["reason_text"]
        channel = ev.get("channel_used") or "voice"
        if channel == "web_call":
            channel, data["web_call"] = "voice", True
        item = self._result_item(action_id, str(ev["early_result"]), ev, channel, data)  # con el vuelo aún abierto: hace falta para la ETA
        with self._lock:
            if action_id in self._closed or self._inflight.get(action_id) is not flight:
                return {"ok": True, "ignored": True}
            self._closed.add(action_id)
            self._early.add(action_id)
            if action_id in self.calls:
                self.calls[action_id]["early_result"] = item["result"]
            self._inflight.pop(action_id, None)
            if flight and "answered_at" not in flight:
                self.stats["answer_ms"].append(round((time.monotonic() - flight["started"]) * 1000))
            self._inbox.append(item)
        self._ledger_event("result", action_id, {"result": item["result"], "early": True})
        self._ledger_episode(action_id, result=item["result"], text=str(item.get("text") or ""), real=True)
        return {"ok": True, "duplicate": False, "result": item["result"], "eta_min": item["eta_min"]}

    def _transcript_from(self, action_id: str, transcript: Any) -> None:
        """La transcripción del webhook final: lista de turnos `{role, content}` o un texto con un turno por línea."""
        if isinstance(transcript, str) and transcript.strip().startswith("["):
            try:
                transcript = json.loads(transcript)
            except ValueError:
                pass
        if isinstance(transcript, list):
            for m in transcript[-12:]:
                if isinstance(m, dict):
                    self._say(action_id, str(m.get("role") or "agent"), str(m.get("content") or m.get("text") or ""))
        elif isinstance(transcript, str):
            for line in transcript.splitlines()[-12:]:
                role, sep, text = line.partition(":")
                known = sep and role.strip().lower() in ("assistant", "agent", "ai", "bot", "user", "human", "caller")
                self._say(action_id, role.strip().lower() if known else "agent", (text if known else line).strip())

    def _latency_from(self, ev: dict[str, Any]) -> None:
        """Latencia por turno de voz, si la plataforma la manda (nombre del campo sin confirmar)."""
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        for k in ("turn_latency_ms", "latency_ms", "avg_turn_latency_ms"):
            v = ev.get(k, data.get(k))
            if isinstance(v, (int, float)) and v > 0:
                self.stats["turn_latency_ms"].append(round(v))
                return

    def _track_result(self, item: dict[str, Any]) -> None:
        action_id = str(item.get("action_id") or "")
        call = self.calls.get(action_id)
        if call is None:
            return
        call.update(result=item.get("result"), text=str(item.get("text") or "")[:160], t_end=self.world.t,
                    eta_min=item.get("eta_min"))
        if call["eta_min"] is None:
            m = re.search(r"(\d+)\s*min", call["text"])
            if m:
                call["eta_min"] = int(m.group(1))
        # Cierra episodio para sim y real. Los caminos reales ya hicieron upsert en on_event;
        # el upsert es idempotente por action_id. No emitimos otro evento «result» aquí.
        self._ledger_episode(action_id, result=call.get("result"), text=str(call.get("text") or ""))

    # ================================================================ API de la plataforma (run, sesión, web call, signals)
    def _api(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._stop.is_set():
            raise RuntimeError('Partida cerrada')
        if not (self.api_base and _env("HR_API_KEY")):
            raise RuntimeError("HR_API_BASE o HR_API_KEY sin configurar")
        resp = httpx.request(method, self.api_base + path, json=body, timeout=self.http_timeout_s,
                             headers={"Authorization": f"Bearer {_env('HR_API_KEY')}"})
        if resp.status_code >= 300:
            raise RuntimeError(f"HTTP {resp.status_code} en {path}")
        return resp.json() if resp.content else {}

    def _bind_run(self, action_id: str, run_id: str, session_id: Any = None) -> None:
        if not run_id or self._stop.is_set():
            return
        with self._lock:
            new = run_id not in self._run_to_action
            self._run_to_action[run_id] = action_id
            self.revision += 1
            call = self.calls.get(action_id)
            if call is not None:
                call["hr_run_id"] = run_id
                if session_id:
                    call["hr_session_id"] = str(session_id)
        if new and self.api_base and _env("HR_API_KEY"):
            threading.Thread(target=self._follow_run, args=(action_id, run_id), daemon=True).start()

    def _follow_run(self, action_id: str, run_id: str) -> None:
        """Busca la sesión del run (hace falta para Signals, escucha y toma) y sigue su transcripción en vivo."""
        session_id = (self.calls.get(action_id) or {}).get("hr_session_id")
        for _ in range(40):
            if self._stop.is_set():
                return
            if session_id or (action_id in self._closed and action_id not in self._early):
                break  # confirmada en caliente = la llamada sigue viva unos segundos: se sigue su transcripción
            try:
                data = self._api("GET", f"/runs/{run_id}/sessions").get("data") or []
                session_id = data[0].get("id") if data else None
            except (RuntimeError, httpx.HTTPError, ValueError):
                pass
            if not session_id:
                self._stop.wait(0.5)
        if not session_id:
            return
        with self._lock:
            if action_id in self.calls:
                self.calls[action_id]["hr_session_id"] = session_id
        for attempt in range(3):  # silencio de red: reconexión acotada, nunca bloquea el reloj
            if self._stop.is_set():
                return
            try:
                with httpx.stream("GET", f"{self.api_base}/sessions/{session_id}/stream", timeout=self.http_timeout_s,
                                  headers={"Authorization": f"Bearer {_env('HR_API_KEY')}"}) as resp:
                    resp.raise_for_status()
                    event = ""
                    for line in resp.iter_lines():
                        if self._stop.is_set():
                            return
                        if line.startswith("event:"):
                            event = line[6:].strip()
                        elif line.startswith("data:") and event in ("message", ""):
                            try:
                                m = json.loads(line[5:])
                            except ValueError:
                                continue
                            if not m.get("is_filler"):
                                self._say(action_id, str(m.get("role") or "agent"), str(m.get("content") or ""))
                        if event == "session_ended":
                            return
            except (httpx.HTTPError, RuntimeError):
                pass
            if attempt < 2:
                self._stop.wait(0.4)
        if not self._stop.is_set():
            self._transcript_at_close(action_id, session_id)

    def _transcript_at_close(self, action_id: str, session_id: str) -> None:
        try:
            for m in self._api("GET", f"/sessions/{session_id}/messages?page_size=100").get("data") or []:
                if not m.get("is_filler"):
                    self._say(action_id, str(m.get("role") or "agent"), str(m.get("content") or ""))
        except (RuntimeError, httpx.HTTPError, ValueError):
            pass

    def _say(self, action_id: str, role: str, text: str) -> None:
        if not text:
            return
        who = "mando" if role in ("assistant", "agent", "ai", "bot") else "persona" if role in ("user", "human", "caller") else role
        with self._lock:
            call = self.calls.get(action_id)
            if call is None:
                return
            lines = call.setdefault("transcript", [])
            if lines and lines[-1]["text"] == text:
                return
            lines.append({"who": who, "text": text[:300]})
            self.revision += 1
            del lines[:-12]
            flight = self._inflight.get(action_id)
            if who == "mando" and flight and flight.get("answered_at") and "first_word" not in flight:
                # el aviso legal («This is a recorded call with an AI agent») suena antes y no es latencia del agente
                raw = (time.monotonic() - flight["answered_at"]) * 1000
                flight["first_word"] = max(0, round(raw - self.disclaimer_s * 1000))
                self.stats["first_word_ms"].append(flight["first_word"])

    def answer_webcall(self, call_id: str) -> dict[str, Any]:
        """La persona ha pulsado DESCOLGAR en su enlace: ahora, y no antes, se pide el token a la plataforma."""
        with self._lock:
            wc = self.webcalls.get(call_id)
            if wc is None:
                raise KeyError(call_id)
            action_id = wc["action_id"]
            if action_id in self._closed:
                raise RuntimeError("la llamada ya no está en curso")
        payload = self.wire_payload(action_id)
        self.workflow_status.record('webcall', 'request')
        try:
            out = self._api("POST", "/voice/tokens/", {"workflow_id": self.workflows["webcall"], "data": payload,
                                                       "env": self.hr_env, "ttl_seconds": 900})
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            self.workflow_status.record('webcall', 'error', error=type(exc).__name__)
            self._fall_back(action_id, 'sin conexión con la plataforma')
            raise
        self.workflow_status.record('webcall', 'response', error='', run_url=out.get('run_url'))
        with self._lock:
            wc["answered"] = True
            flight = self._inflight.get(action_id)
            if flight:
                flight["answered_at"] = time.monotonic()
                flight["deadline"] = time.monotonic() + self.fallback_s
                self.stats["answer_ms"].append(round((flight["answered_at"] - flight["started"]) * 1000))
            if action_id in self.calls:
                self.calls[action_id]["stage"] = "ha descolgado"
        self._bind_run(action_id, str(out.get("run_id") or ""))
        self.on_log("action", f"{wc['title']} descuelga la llamada web ({action_id})", action_id, real=True)
        return {"url": out.get("url"), "token": out.get("token"), "room_name": out.get("room_name"), "run_id": out.get("run_id")}

    def takeover_token(self, action_id: str, takeover: bool) -> dict[str, Any]:
        """Escucha oculta (takeover=False) o TOMA de la llamada por una persona: el agente de voz se cae."""
        call = self.calls.get(action_id) or {}
        session_id = call.get("hr_session_id")
        if not session_id:
            raise RuntimeError("todavía no se conoce la sesión de esa llamada")
        out = self._api("POST", "/voice/tokens/", {"session_id": session_id, "should_takeover": bool(takeover)})
        if takeover:
            with self._lock:
                call["taken_over"] = True
                call["stage"] = "la lleva una persona"
            self.on_log("approval", f"Una persona TOMA la llamada con {call.get('title') or call.get('to')} ({action_id})", action_id)
        return {"url": out.get("url"), "token": out.get("token"), "room_name": out.get("room_name")}

    def signal(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Despierta al agente de voz EN PLENA LLAMADA con información nueva (`POST /signals`, clave `session.<id>`)."""
        t0 = time.monotonic()
        try:
            out = self._api("POST", "/signals", {"key": f"session.{session_id}", "env": self.hr_env, "payload": payload,
                                                 "metadata": {"mando_session": self.session_id}})
            ok, err = True, ""
        except (RuntimeError, httpx.HTTPError, ValueError) as e:
            out, ok, err = {}, False, str(e) or type(e).__name__
        rec = {"session_id": session_id, "payload": payload, "ok": ok, "error": err, "t": self.world.t,
               "rtt_ms": round((time.monotonic() - t0) * 1000), "signal_id": out.get("signal_id")}
        with self._lock:
            self.signals.append(rec)
            if ok:
                self.stats["signal_rtt_ms"].append(rec["rtt_ms"])
        return rec

    def pending_webcalls(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(w) for w in self.webcalls.values()
                    if not w["answered"] and w["action_id"] in self._inflight]

    def live_real_calls(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(self.calls[aid]) for aid in self._inflight if aid in self.calls]

    def change_orders(self, action_id: str, text: str, extra: dict[str, Any] | None = None) -> bool:
        """Cambio de orden a quien está AHORA al teléfono. Sin sesión conocida no se puede: se deja dicho en el log."""
        call = self.calls.get(action_id) or {}
        session_id = call.get("hr_session_id")
        if not session_id:
            self.plan_changes[action_id] = {"text": text, "t": self.world.t}
            self.on_log("action", f"No se puede cambiar la orden en la llamada {action_id}: sesión desconocida. Queda «tomar la llamada» o rellamar", action_id)
            return False
        self.plan_changes[action_id] = {"text": text, "t": self.world.t}
        rec = self.signal(session_id, dict({"type": "orden_cambiada", "orden_cambiada": True, "orden_nueva": text,
                                            "action_id": action_id, "text": text}, **(extra or {})))
        call["signal"] = {"text": text, "ok": rec["ok"], "rtt_ms": rec["rtt_ms"]}
        self.on_log("action", (f"CAMBIO DE ORDEN dentro de la llamada con {call.get('title') or call.get('to')}: «{text}» ({rec['rtt_ms']} ms)"
                               if rec["ok"] else f"El cambio de orden en la llamada {action_id} no salió: {rec['error']}"), action_id, real=True)
        return rec["ok"]

    # ================================================================ consultas síncronas de la plataforma
    def identify(self, from_number: str) -> dict[str, Any]:
        number = normalize_number(from_number)
        for rid, entry in self.contacts["resources"].items():
            e = {"to_number": entry} if isinstance(entry, str) else entry
            if normalize_number(e.get("to_number")) == number:
                with self._lock:
                    pending = next((aid for aid, f in self._inflight.items() if f["action"].resource == rid), None)
                msg = self.payloads.get(pending, {}).get("message") if pending else None
                return {"ok": True, "route": "staff_reply" if pending else "staff_report", "role": "staff",
                        "resource_id": rid, "display_name": self._res_spoken.get(rid, rid),
                        "pending_action_id": pending, "pending_message": msg, "session_id": self.session_id,
                        "lang_hint": "es", "recent_reports": 0}
        return {"ok": True, "route": "public_report", "role": "public", "resource_id": None, "display_name": None,
                "pending_action_id": None, "pending_message": None, "session_id": self.session_id,
                "lang_hint": None, "recent_reports": 0}

    def next_webcall_order(self) -> dict[str, Any] | None:
        with self._lock:
            for aid in self._inflight:
                p = self.payloads.get(aid)
                if p and p.get("message") in ("dispatch_request", "followup_request", "external_request"):
                    return p
        return None

    # ================================================================ para la pantalla
    def view(self) -> dict[str, Any]:
        def avg(xs: list[int]) -> int | None:
            return round(sum(xs) / len(xs)) if xs else None
        with self._lock:
            calls = [{k: v for k, v in c.items() if k != "started"} for c in list(self.calls.values())[-12:]]
            for c in calls:
                c["can_take"] = bool(c.get("real") and not c.get("result") and c.get("hr_session_id") and not c.get("taken_over"))
                c["waiting_pickup"] = bool(c.get("web_call") and not c.get("result") and not c.get("fell_back")
                                           and not self.webcalls.get(c.get("call_id", ""), {}).get("answered"))
                c.pop("call_id", None)        # el secreto del enlace solo lo ve el puesto del operador (/api/webcalls)
                c.pop("hr_session_id", None)
            s = self.stats
            incidents = [self.incident_lookup(c.get("incident")) for c in calls if c.get("incident")]
            calls = privacy.project({"incidents": [i for i in incidents if i], "calls": calls}, [], {}, {})["calls"]
            return privacy.scrub({"mode": self.mode, "calls": calls, "in_flight_real": len(self._inflight),
                    "real_sent": s["real_sent"], "fallbacks": s["fallbacks"],
                    "hook_rtt_ms": avg(s["hook_rtt_ms"]), "answer_ms": avg(s["answer_ms"]),
                    "turn_latency_ms": avg(s["turn_latency_ms"]), "turn_latency_n": len(s["turn_latency_ms"]),
                    "first_word_ms": avg(s["first_word_ms"]), "first_word_n": len(s["first_word_ms"]),
                    "signal_rtt_ms": avg(s["signal_rtt_ms"]), "signals": len(self.signals),
                    "voice_mode": self.voice_mode, "launch_mode": self.launch_mode,
                    "hooks_configured": sorted(k for k, v in self.hooks.items() if v),
                    "real_contacts": sorted(self.contacts["resources"].keys())})
