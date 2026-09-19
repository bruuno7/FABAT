"""Agente de RECOGIDA en la web y en Telegram: la persona HABLA y el agente la guía y pregunta lo que falta.

La conversación la lleva `motor.intake.IntakeSession` (otro módulo: `receive(text) -> Turn` con `say`, `instruction`,
`reports`, `state`, `why_next`, `done`; `mando_asks(question)`; `notify(status)`). Aquí solo está la fontanería:

- `POST /api/chat` crea o continúa una sesión; cada `Report` que emite la sesión entra al mundo por el MISMO camino que
  `/api/report`, y el primero sale en cuanto hay lo mínimo (no se espera a terminar la conversación). Las actualizaciones
  quedan enlazadas al primer aviso.
- Un ASK de Mando dirigido a ese informante se inyecta en SU conversación (`mando_asks`) y lo que conteste vuelve a Mando.
- Los cambios de estado de su incidente se le cuentan por `GET /api/chat/{id}/events` (SSE), pasando por `notify`.

Todo es tolerante a que `motor/intake` no exista todavía: `/api/chat` degrada a `/api/report` y lo DICE en la respuesta.
"""
from __future__ import annotations

import inspect
import secrets
import threading
import time
from collections import deque
from typing import Any, Callable

from .telegram_bot import ACK, safety_instruction
from .privacy import scrub

STATUS_ES = {"assigned": "Equipo asignado y en camino.", "calling": "Estamos llamando al equipo.", "accepted": "El equipo ha aceptado y va para allá.",
             "rejected": "Ese equipo no puede ir: buscamos otro.", "on_scene": "El equipo ya está en el sitio.", "resolved": "Resuelto. Gracias por avisar.",
             "closed": "Aviso cerrado. Gracias por avisar."}
NEUTRAL = "Tu aviso está en el centro de control y se está atendiendo."


def load_intake() -> Any:
    """La clase `IntakeSession`, o None si `motor/intake` todavía no existe o no se puede importar."""
    try:
        from motor.intake import IntakeSession  # type: ignore[import-not-found]
        return IntakeSession
    except Exception:
        return None


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _plainify(x: Any) -> Any:
    if hasattr(x, "to_dict"):
        x = x.to_dict()
    if isinstance(x, dict):
        return {str(k): _plainify(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [_plainify(v) for v in x]
    return x if isinstance(x, (str, int, float, bool)) or x is None else str(x)


def app_state(state: dict) -> dict:
    state = _plainify(state)
    slots = state.get("slots", {})
    if isinstance(slots, dict):
        state["slots"] = [dict(id=k, label=v.get("label") or k, value=v.get("value"), confidence=v.get("confidence", 0))
                          for k, v in slots.items() if isinstance(v, dict)]
    else:
        state["slots"] = slots if isinstance(slots, list) else []
    return scrub(state)


def instruction_view(value: Any, lang: str) -> dict | None:
    if not value:
        return None
    out = dict(value) if isinstance(value, dict) else {"id": "safety", "steps": [str(value)]}
    out.setdefault("title", "What to do now" if lang == "en" else "Qué hacer ahora")
    out.setdefault("id", "safety")
    # El metrónomo solo acompaña una instrucción explícita de compresiones, no una hipótesis condicional.
    steps = out.get("steps") or []
    out["steps"] = [str(x) for x in steps]
    out.setdefault("metronome", out["id"] in ("cpr", "hands_only_cpr", "cpr_hands_only", "rcp", "start_cpr"))
    return out


def quick_replies(ask: Any, lang: str) -> list:
    if not isinstance(ask, dict):
        return []
    if ask.get("type") in ("bool", "boolean"):
        return ["Yes", "No", "I don't know"] if lang == "en" else ["Sí", "No", "No lo sé"]
    out = []
    for option in ask.get("options") or []:
        if isinstance(option, dict):
            label = option.get("label") or option.get("value") or option.get("id")
            if isinstance(label, dict):
                label = label.get(lang) or label.get("es")
            out.append({"label": label, "value": option.get("value", option.get("id", label))})
        else:
            out.append(str(option))
    return out


class ChatHub:
    def __init__(self, get_session: Callable[[], Any], submit_report: Callable[..., dict[str, Any]],
                 understand: Callable[[str, str, str | None, str], dict[str, Any] | None] | None = None,
                 wristband: Callable[[str | None], dict[str, Any] | None] | None = None) -> None:
        self.get_session, self.submit_report = get_session, submit_report
        self.understand, self.wristband = understand, wristband or (lambda code: None)
        self.chats: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._mando_session = ""
        self._thread = threading.Thread(target=self._watch, name="chat-notify", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def available(self) -> bool:
        return load_intake() is not None

    # ---------------------------------------------------------------- sesiones
    def _new_intake(self, channel: str, lang: str, zone_hint: str | None, profile: dict[str, Any] | None, session_id: str) -> Any:
        cls = load_intake()
        if cls is None:
            return None
        def understand(text, detected_lang=lang, slots=None):
            if self.understand is None:
                return {}
            extracted = self.understand(text, channel, zone_hint, detected_lang) or {}
            aliases = {"breathing_normal": "breathing_normally", "location_point": "location"}
            out = {}
            for slot in slots or []:
                key = slot["id"]
                value = extracted.get(key, extracted.get(aliases.get(key, "")))
                if slot.get("type") == "bool" and isinstance(value, str):
                    value = {"true": True, "si": True, "sí": True, "yes": True, "false": False, "no": False}.get(value.lower())
                if value is not None:
                    out[key] = {"value": value, "confidence": 0.7}
            return out
        offered = {"channel": channel, "lang": lang, "zone_hint": zone_hint, "profile": profile, "understand": understand,
                   "session_id": session_id, "t": self.get_session().world.t, "zones": self.get_session().world.observe().zones}
        try:
            accepted = inspect.signature(cls).parameters
            if not any(p.kind == p.VAR_KEYWORD for p in accepted.values()):
                offered = {k: v for k, v in offered.items() if k in accepted}
            return cls(**offered)
        except Exception:
            return None

    def _chat(self, sid: str | None, channel: str, lang: str, zone_hint: str | None, pulsera: str | None) -> dict[str, Any]:
        with self._lock:
            c = self.chats.get(sid or "")
            if c is None:
                sid = sid if sid and sid.startswith("tg-") else "c-" + secrets.token_urlsafe(6)
                c = self.chats[sid] = {"id": sid, "n": len(self.chats) + 1, "channel": channel, "lang": lang, "zone": zone_hint,
                                       "pulsera": pulsera, "intake": self._new_intake(channel, lang, zone_hint, self.wristband(pulsera), sid),
                                       "reports": [], "ask": None, "events": deque(maxlen=50), "seq": 0, "told": None,
                                       "state": {}, "instruction": None, "done": False}
            if zone_hint:
                c["zone"] = zone_hint
            if pulsera:
                c["pulsera"] = pulsera
            return c

    def source(self, c: dict[str, Any]) -> str:
        return c["id"].replace("tg-", "", 1) if c["id"].startswith("tg-telegram:") else c.get("source") or f"chat:{c['n']}"

    # ---------------------------------------------------------------- un turno
    def turn(self, sid: str | None, text: str, *, channel: str = "web", lang: str = "es", zone_hint: str | None = None,
             pulsera: str | None = None, source: str | None = None, preset: str | None = None, client_id: str | None = None, push: Callable[[str], None] | None = None) -> dict[str, Any]:
        """Bloquea lo que tarde el entendimiento delegado: llamar fuera del bucle asyncio."""
        self._sync()
        text = (text or "").strip()[:400]
        c = self._chat(sid, channel, lang, zone_hint, pulsera)
        c["seen"] = time.monotonic()
        c["lang"] = lang if lang in ("en", "es") else c["lang"]
        if source and not source.startswith("telegram:"):
            c["source"] = source[:40]
        c["preset"] = preset or c.get("preset")
        c["client_id"] = client_id or c.get("client_id")
        if push is not None:
            c["push"] = push   # Telegram no tiene SSE: lo que haya que contarle se le EMPUJA por el bot
        answered = False
        if c["ask"]:
            aid, c["ask"] = c["ask"], None
            answered = bool(self.get_session().comms.answer_external(aid, text, channel="telegram" if c["id"].startswith("tg-") else "web"))
        if c["intake"] is None:
            return self._degraded(c, text, answered)
        try:
            turn = c["intake"].receive(text)
        except Exception as e:   # el agente de recogida falla: el aviso NO se pierde
            out = self._degraded(c, text, answered)
            out["why"] = (f"Guided intake failed ({type(e).__name__}); your message was sent directly." if c["lang"] == "en"
                          else f"el agente de recogida falló ({type(e).__name__}): este mensaje ha entrado como aviso directo")
            return out
        new = []
        metas = _get(turn, "report_meta") or []
        for n, rep in enumerate(_get(turn, "reports") or []):
            rid = self._submit(c, rep, answered, metas[n] if n < len(metas) else {})
            if rid:
                new.append(rid)
        c["state"] = app_state(_get(turn, "state") or {})
        c["instruction"] = instruction_view(_get(turn, "instruction"), c["lang"]) or c["instruction"]
        c["done"] = bool(_get(turn, "done"))
        self._publish(c)
        return {"ok": True, "session_id": c["id"], "degraded": False, "say": _get(turn, "say") or "", "instruction": c["instruction"], "quick_replies": quick_replies(_get(turn, "ask"), c["lang"]),
                "reports": new, "report_id": c["reports"][0] if c["reports"] else None, "state": c["state"],
                "why_next": _get(turn, "why_next"), "done": c["done"], "answered_mando": answered}

    def _submit(self, c: dict[str, Any], rep: Any, answered: bool, meta: dict | None = None) -> str | None:
        text = str(_get(rep, "text") or "").strip()
        if not text or (answered and c["reports"]):
            return None   # era la respuesta a Mando: ya ha vuelto por comunicaciones, no se duplica como aviso
        meta = meta or {}
        root = meta.get("root", "default")
        roots = c.setdefault("roots", {})
        zone = _get(rep, "zone_hint") or c["zone"]
        ch = str(_get(rep, "channel") or "whatsapp")
        out = self.submit_report(ch if ch in ("voice", "sms", "whatsapp") else "whatsapp", text, zone, source=self.source(c),
                                 lang=str(_get(rep, "lang") or c["lang"]), wristband=c["pulsera"],
                                 via="telegram" if c["id"].startswith("tg-") else "chat", delegate=False,
                                 update_of=roots.get(root), preset=c.get("preset") if not c["reports"] else None,
                                 extracted={"sensitive": True} if meta.get("reserved") else None,
                                 understood="happyrobot" if _get(rep, "understood") == "happyrobot" else None)
        rid = out.get("report_id")
        if rid:
            c["reports"].append(rid)
            roots.setdefault(root, rid)
        return rid

    def _degraded(self, c: dict[str, Any], text: str, answered: bool) -> dict[str, Any]:
        rid = None
        if text and not answered:
            out = self.submit_report("whatsapp", text, c["zone"], source=self.source(c), lang=c["lang"], wristband=c["pulsera"],
                                     via="telegram" if c["id"].startswith("tg-") else "chat", preset=c.get("preset"))
            rid = out.get("report_id")
            if rid:
                c["reports"].append(rid)
        inst = safety_instruction(text)
        value = {"id": inst[0], "steps": [inst[1]]} if inst else None
        if c["lang"] == "en":
            value = {"id": "stay_safe", "steps": ["Move to a safe place. If anything changes, message us again."]}
        c["instruction"] = instruction_view(value, c["lang"]) or c["instruction"]
        c["state"] = {"slots": [{"id": "location", "label": "Location" if c["lang"] == "en" else "Dónde",
                                  "value": c["zone"], "confidence": 1 if c["zone"] else 0}]}
        self._publish(c)
        return {"ok": True, "session_id": c["id"], "degraded": True, "say": ("Thank you. I have passed this on to the control centre." if c["lang"] == "en"
                        else "Gracias. Lo paso al centro de control." if answered else ACK),
                "instruction": c["instruction"], "quick_replies": [], "reports": [rid] if rid else [], "report_id": c["reports"][0] if c["reports"] else None,
                "state": c["state"], "why_next": None, "done": True, "answered_mando": answered,
                "why": "Guided intake is unavailable; your message was sent directly." if c["lang"] == "en" else "motor.intake no está disponible: /api/chat degrada a /api/report (un mensaje = un aviso)"}

    def _publish(self, c: dict[str, Any]) -> None:
        """Las fichas de la conversación, junto a sus avisos en la pantalla de mando."""
        s = self.get_session()
        for n, rid in enumerate(c["reports"]):
            meta = s._report_meta.setdefault(rid, {})
            meta["chat"] = {"session": c["n"], "state": c["state"], "instruction": c["instruction"], "done": c["done"],
                            "update_of": c["reports"][0] if n else None}
        s._rebuild()

    # ---------------------------------------------------------------- preguntas de Mando
    def route_ask(self, session: Any, action: Any) -> str:
        """¿Esta pregunta es para alguien que está en una conversación? Devuelve el canal ("web" | "telegram") o ""."""
        if (session is not self.get_session() or action.resource or action.params.get("purpose") == "sitrep"
                or action.params.get("to") in session.world.resources
                or str(action.params.get("to") or "").startswith("responsable")):
            return ""
        wanted = set(action.params.get("reports") or [])
        to = str(action.params.get("to") or "")
        with self._lock:
            c = next((c for c in self.chats.values() if wanted & set(c["reports"]) or (to and to == self.source(c))), None)
            if c is None or (not c["id"].startswith("tg-") and time.monotonic() - c.get("seen", 0) > 30):
                return ""   # nadie mirando esa conversación: que conteste quien contestaba antes
            c["ask"] = action.id
        question = str(action.params.get("message") or "¿Puedes darme más detalles?")
        say = question
        if c["intake"] is not None and hasattr(c["intake"], "mando_asks"):
            try:
                t = c["intake"].mando_asks(question)
                say = (_get(t, "say") if not isinstance(t, str) else t) or question
            except Exception:
                pass
        if c["lang"] == "en" and "¿" in say:
            say = {"zone": "Where exactly are you?", "location": "Where exactly are you?", "confirm": "Is this still happening?"}.get(
                action.params.get("purpose"), "Can you give the control centre more details?")
        self._event(c, "ask", say, action_id=action.id)
        return "telegram" if c["id"].startswith("tg-") else "web"

    # ---------------------------------------------------------------- avisos de estado
    def _event(self, c: dict[str, Any], kind: str, text: str, **extra: Any) -> None:
        c["seq"] += 1
        text = scrub(text)
        c["events"].append(dict({"seq": c["seq"], "type": kind, "text": text}, **extra))
        if c.get("push") is not None:
            try:
                c["push"]((("Control centre: " if c["lang"] == "en" else "Centro de control: ") if kind == "ask" else "") + text)
            except Exception:
                pass

    def events_after(self, sid: str, seq: int) -> list[dict[str, Any]] | None:
        with self._lock:
            c = self.chats.get(sid)
            if c is None:
                return None
            c["seen"] = time.monotonic()
            return [e for e in c["events"] if e["seq"] > seq]

    def _sync(self) -> None:
        sid = getattr(self.get_session(), "session_id", "")
        if sid != self._mando_session:
            self._mando_session = sid
            with self._lock:
                for c in self.chats.values():
                    c.update(reports=[], roots={}, ask=None, told=None, state={}, instruction=None, done=False)
                    c["events"].clear()
                    c["intake"] = self._new_intake(c["channel"], c["lang"], c["zone"], self.wristband(c["pulsera"]), c["id"])

    def _status_of(self, c: dict[str, Any]) -> tuple[str, bool] | None:
        s = self.get_session()
        info = s.report_status(c["reports"][0])
        if not info.get("found"):
            return None
        status, call = str(info.get("status")), info.get("call") or {}
        if status in ("resolved",):
            key = "resolved"
        elif status in ("false_alarm", "failed"):
            key = "closed" if status == "false_alarm" else ""
        elif status == "in_progress":
            key = "on_scene"
        elif call.get("state") == "acepta":
            key = "accepted"
        elif call.get("state") in ("rechaza", "no contesta"):
            key = "rejected"
        elif call.get("state") == "llamando":
            key = "calling"
        else:
            key = "assigned" if status == "assigned" else ""
        return (key, bool(info.get("reserved"))) if key else None

    def _watch(self) -> None:
        while not self._stop.wait(0.5):
            try:
                self._sync()
                with self._lock:
                    chats = [c for c in self.chats.values() if c["reports"]]
                for c in chats:
                    got = self._status_of(c)
                    if got is None or got[0] == c["told"]:
                        continue
                    c["told"] = got[0]
                    text = NEUTRAL if got[1] and got[0] not in ("resolved", "closed") else STATUS_ES[got[0]]
                    if c["intake"] is not None and hasattr(c["intake"], "notify"):
                        try:
                            t = c["intake"].notify(got[0])
                            text = ((_get(t, "say") if not isinstance(t, str) else t) or text) if not got[1] else text
                        except Exception:
                            pass
                    if c["lang"] == "en" and (got[1] or c["intake"] is None):
                        text = {"assigned": "A team has been assigned.", "calling": "We are calling a team.",
                                "accepted": "The team has accepted the assignment.", "rejected": "We are looking for another team.",
                                "on_scene": "The team is on scene.", "resolved": "Resolved. Thank you for reporting it.",
                                "closed": "Your report is closed."}.get(got[0], "The control centre has your report.")
                        if got[1]:
                            text = "The control centre is handling your report privately."
                    self._event(c, "status", text, status=got[0])
            except Exception:
                pass
