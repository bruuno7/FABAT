"""Bot de Telegram: el canal del público y del jurado; poll, send_only u off.

Sin webhook y sin túnel: este proceso PREGUNTA a Telegram; nadie entra aquí desde fuera. El token va en
`TELEGRAM_BOT_TOKEN`; si no está, el bot no arranca y el servidor sigue igual (`/api/state` → `telegram.status = "off"`).

Cada mensaje de texto entra como aviso por el mismo camino que `POST /api/report` (canal `whatsapp` del contrato, que es
el del público, con `source = "telegram:<n>"`: un alias por chat, nunca el nombre ni el usuario de Telegram). El bot CONTESTA:
acuse inmediato, UNA instrucción de seguridad de la lista cerrada de `motor/happyrobot/PROMPTS.md`, la pregunta de
aclaración cuando Mando emite un ASK dirigido a ese informante (su respuesta vuelve a Mando como respuesta de
comunicaciones) y el cierre («Equipo en camino» / «Resuelto»). Si el incidente es `reserved`, respuestas neutras: nunca
se repite el contenido.

Comandos: /start · /zona <nombre> · /pulsera <código> · /golpe · /estado. También admite la ubicación compartida.
Este canal solo CREA avisos: nadie cierra accesos ni se declara responsable por aquí, diga lo que diga el texto.
"""
from __future__ import annotations

import math
import os
import queue
import re
import threading
import time
import unicodedata
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import httpx

ACK = "Recibido. Lo paso al centro de control."
CLOSING = {"assigned": "Equipo en camino.", "in_progress": "El equipo ya está en el sitio.", "resolved": "Resuelto. Gracias por avisar.",
           "false_alarm": "Aviso cerrado. Gracias por avisar."}
START = ("Festival Abierto, sistema automático de avisos. Escribe QUÉ pasa y DÓNDE estás: lo recibe el centro de control.\n"
         "Esto es una SIMULACIÓN de un hackathon: no es un servicio de emergencias. Si hay una emergencia real, llama al 112.\n"
         "/zona <nombre> fija dónde estás · /pulsera <código> asocia tu pulsera · /estado · /golpe (rompe el plan)")

# Lista CERRADA de instrucciones de seguridad (motor/happyrobot/PROMPTS.md › C). Texto exacto. A validar por el responsable
# sanitario antes de un uso real. El orden importa: gana la primera que case.
SAFETY: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("not_responding", ("no responde", "no respira", "inconsciente", "desplom", "no se mueve", "infarto", "convuls"),
     "Quédate con la persona. Pide ayuda a gritos al personal con chaleco. Si no respira normal y sabes hacer RCP, empieza."),
    ("bleeding", ("sangr", "hemorrag"), "Aprieta fuerte sobre la herida con una prenda. No sueltes."),
    ("crowd_pressure", ("aplast", "avalancha", "empuj", "agobi", "no podemos salir", "nos aprietan"),
     "No empujes. Brazos delante del pecho. Sal en diagonal hacia los lados cuando puedas."),
    ("fire_or_structure", ("fuego", "humo", "llamas", "quemad", "incendi", "valla", "se ha caido", "se cae", "estructura", "torre"),
     "Aléjate de ahí y no vuelvas. Avisa a los de alrededor."),
    ("aggression", ("pelea", "pegando", "agred", "agres", "acos", "navaja", "cuchillo", "amenaz", "me siguen", "tocando"),
     "Aléjate y no te enfrentes. Ve hacia el personal con chaleco."),
    ("lost_child", ("nino", "nina", "menor", "crio", "perdido", "perdida"), "Quédate con el menor en ese sitio. No os mováis."),
    ("heat", ("calor", "mare", "desmay", "insolacion"), "Llévala a la sombra. Si está despierta, agua a sorbos."),
    ("weather", ("viento", "tormenta", "rayo", "granizo"), "Aléjate de torres, carpas y vallas."),
)
GENERIC_SAFETY = "Ponte en un sitio seguro. Si empeora, escribe otra vez."
_NO_INSTRUCTION = ("gracias", "hola", "cuanto tard", "precio", "entrada", "horario", "jaja")

# Coordenadas FICTICIAS: el recinto no existe. Centro de cada zona del plano (x, y en metros desde la esquina noroeste) sobre
# un origen inventado. Sirven para traducir una ubicación compartida a «la zona más cercana»; no localizan a nadie de verdad.
ORIGIN = (40.4000, -3.7000)
_LAYOUT_M = {"gate_a": (25, 31), "gate_b": (25, 88), "gate_c": (25, 144), "food": (76, 20), "toilets": (117, 20),
             "water_n": (151, 20), "medical_2": (184, 20), "vip": (221, 20), "corridor_n": (147, 50), "general": (131, 88),
             "front_pit": (213, 88), "backstage": (275, 88), "corridor_s": (147, 126), "exit_transport": (79, 155),
             "water_s": (122, 155), "medical_1": (156, 155), "pmr": (190, 155)}
_M_LAT = 1 / 111_320.0
_M_LON = 1 / (111_320.0 * math.cos(math.radians(ORIGIN[0])))
ZONE_COORDS = {z: (round(ORIGIN[0] - y * _M_LAT, 6), round(ORIGIN[1] + x * _M_LON, 6)) for z, (x, y) in _LAYOUT_M.items()}
_SPAN_M = (300.0, 175.0)


def _plain(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")


def safety_instruction(text: str) -> tuple[str, str] | None:
    """(clave, texto exacto) de la lista cerrada, o None si no toca (saludo, consulta, broma)."""
    plain = _plain(text)
    for key, words, say in SAFETY:
        if any(w in plain for w in words):
            return key, say
    if len(plain) < 12 or any(w in plain for w in _NO_INSTRUCTION):
        return None
    return "generic_stay_safe", GENERIC_SAFETY


def nearest_zone(lat: float, lon: float) -> tuple[str, bool]:
    """Zona más cercana a una ubicación. Si la persona está lejos del recinto ficticio (lo normal: está en su asiento),
    la ubicación se PLIEGA sobre el plano para que dos asientos distintos caigan en zonas distintas. Devuelve (zona, plegada)."""
    def dist_m(a: tuple[float, float]) -> float:
        return math.hypot((lat - a[0]) / _M_LAT, (lon - a[1]) / _M_LON)
    zone = min(ZONE_COORDS, key=lambda z: dist_m(ZONE_COORDS[z]))
    if dist_m(ZONE_COORDS[zone]) <= 2000:
        return zone, False
    x = ((lon - ORIGIN[1]) / _M_LON) % _SPAN_M[0]
    y = ((ORIGIN[0] - lat) / _M_LAT) % _SPAN_M[1]
    return min(_LAYOUT_M, key=lambda z: math.hypot(x - _LAYOUT_M[z][0], y - _LAYOUT_M[z][1])), True


def match_zone(text: str, zones: dict[str, str]) -> str | None:
    """«puerta b», «baños», «frente», «gate_b»… → id de zona. Tolerante con tildes y mayúsculas."""
    q = _plain(text).strip()
    if not q:
        return None
    if q in zones:
        return q
    if q in ("escenario", "escenario principal", "escenario uno", "escenario 1"):
        return "front_pit" if "front_pit" in zones else None
    if q in ("escenario dos", "escenario 2", "escenario secundario", "segundo escenario", "secundario"):
        return "stage_2" if "stage_2" in zones else None
    names = {z: _plain(n) for z, n in zones.items()}
    m = re.fullmatch(r"(?:puerta\s*)?([abc])", q)
    if m:
        return f"gate_{m.group(1)}"
    for z, n in names.items():
        if q == n or q == re.sub(r"\s*\(.*", "", n):
            return z
    hits = [z for z, n in names.items() if q in n or all(w in n for w in q.split())]
    return hits[0] if len(hits) == 1 else (sorted(hits, key=lambda z: len(names[z]))[0] if hits else None)


class TelegramBot:
    def __init__(self, token: str, *, get_session: Callable[[], Any], submit_report: Callable[..., dict[str, Any]],
                 submit_strike: Callable[..., dict[str, Any]], strike_presets: dict[str, dict[str, Any]],
                 wristband: Callable[[str], dict[str, Any] | None] | None = None, api_base: str | None = None,
                 poll_timeout: int | None = None) -> None:
        self.token = token
        self.mode = os.environ.get("TELEGRAM_MODE", "poll")
        if self.mode not in ("poll", "send_only", "off"):
            raise ValueError("TELEGRAM_MODE debe ser poll, send_only u off")
        self.api = (api_base or os.environ.get("TELEGRAM_API_BASE") or "https://api.telegram.org").rstrip("/")
        self.get_session, self.submit_report, self.submit_strike = get_session, submit_report, submit_strike
        self.strike_presets, self.wristband = strike_presets, wristband or (lambda code: None)
        self.poll_timeout = int(poll_timeout if poll_timeout is not None else os.environ.get("TELEGRAM_POLL_TIMEOUT_S", "25"))
        self.rate_max = int(os.environ.get("TELEGRAM_RATE_MAX", "6"))
        self.rate_window = float(os.environ.get("TELEGRAM_RATE_WINDOW_S", "60"))
        self.max_chars = int(os.environ.get("TELEGRAM_MAX_CHARS", "400"))
        self.status, self.username, self.error = "starting", "", ""
        self.chat_hub: Any = None   # lo pone el servidor: con `motor.intake` disponible, cada chat es una sesión de recogida
        self.on_change: Callable[[], None] | None = None   # el servidor reconstruye su estado cuando el bot cambia de estado
        self.stats = {"updates": 0, "reports": 0, "replies": 0, "asks": 0, "answers": 0, "rate_limited": 0, "too_long": 0}
        self.chats: dict[int, dict[str, Any]] = {}
        self._alias: dict[str, int] = {}             # «telegram:3» -> chat_id
        self._lock = threading.RLock()
        self._outbox: "queue.Queue[tuple[int, str, dict[str, Any] | None]]" = queue.Queue()
        self._stop = threading.Event()
        self._updates = ThreadPoolExecutor(max_workers=8, thread_name_prefix="telegram-update")
        self._update_slots = threading.BoundedSemaphore(32)
        self._offset = 0
        self._session_id = ""
        self._client = httpx.Client(timeout=self.poll_timeout + 10)
        self._threads = [threading.Thread(target=self._poll_loop, name="telegram-poll", daemon=True),
                         threading.Thread(target=self._notify_loop, name="telegram-notify", daemon=True)]

    # ---------------------------------------------------------------- vida
    def start(self) -> "TelegramBot":
        for t in self._threads:
            t.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._updates.shutdown(wait=False, cancel_futures=True)
        try:
            self._client.close()
        except Exception:
            pass

    def _changed(self) -> None:
        try:
            if self.on_change is not None:
                self.on_change()
        except Exception:
            pass

    def view(self) -> dict[str, Any]:
        """Lo que sale en `/api/state`: nunca el token, ni chat_id, ni nombres de usuario."""
        return {"status": self.status, "mode": self.mode, "bot": self.username, "link": f"https://t.me/{self.username}" if self.username else None,
                "error": self.error or None, "chats": len(self.chats), **self.stats}

    # ---------------------------------------------------------------- Bot API
    def _call(self, method: str, payload: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        resp = self._client.post(f"{self.api}/bot{self.token}/{method}", json=payload or {}, timeout=timeout or 10)
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"{method}: {data.get('error_code')} {data.get('description')}")
        return data.get("result")

    def send(self, chat_id: int, text: str, markup: dict[str, Any] | None = None) -> None:
        self._outbox.put((chat_id, text, markup))

    def _flush(self) -> None:
        while True:
            try:
                chat_id, text, markup = self._outbox.get_nowait()
            except queue.Empty:
                return
            body: dict[str, Any] = {"chat_id": chat_id, "text": text[:1000]}
            if markup:
                body["reply_markup"] = markup
            try:
                self._call("sendMessage", body)
                self.stats["replies"] += 1
            except Exception as e:  # un envío fallido no tumba el bot
                self.error = f"sendMessage: {type(e).__name__}"

    def _poll_loop(self) -> None:
        backoff = 1.0
        failures = 0
        while not self._stop.is_set():
            try:
                if self.status != "on":
                    me = self._call("getMe")
                    self.username = str(me.get("username") or "")
                    # lo que se escribió con el bot parado no entra en esta partida
                    old = self._call("getUpdates", {"offset": -1, "timeout": 0}) if self.mode == "poll" else []
                    if old:
                        self._offset = int(old[-1]["update_id"]) + 1
                    self.status, self.error = "on", ""
                    self._changed()
                if self.mode == "send_only":
                    self._stop.wait(1)
                    continue
                updates = self._call("getUpdates", {"offset": self._offset, "timeout": self.poll_timeout,
                                                    "allowed_updates": ["message", "callback_query"]},
                                     timeout=self.poll_timeout + 8)
                failures, backoff = 0, 1.0
                for u in updates or []:
                    while not self._stop.is_set():
                        if self._update_slots.acquire(timeout=0.1):
                            break
                    else:
                        return
                    try:
                        future = self._updates.submit(self._handle_and_flush, u)
                    except RuntimeError:
                        self._update_slots.release()
                        if self._stop.is_set():
                            return
                        raise
                    future.add_done_callback(lambda _: self._update_slots.release())
                    self._offset = max(self._offset, int(u["update_id"]) + 1)
                    self.stats["updates"] += 1
            except Exception as e:
                if self._stop.is_set():
                    return
                self.status, self.error = "error", f"{type(e).__name__}: {e}".replace(self.token, "***")[:160]
                self._changed()
                failures += 1
                if failures >= 5:
                    return
                self._stop.wait(backoff)
                backoff = min(30.0, backoff * 2)

    def _handle_and_flush(self, update: dict[str, Any]) -> None:
        if self._stop.is_set():
            return
        try:
            self._handle(update)
        except Exception as e:
            self.error = f"update: {type(e).__name__}: {e}"[:160]
        self._flush()

    # ---------------------------------------------------------------- mensajes
    def _chat(self, chat_id: int) -> dict[str, Any]:
        with self._lock:
            c = self.chats.get(chat_id)
            if c is None:
                n = len(self.chats) + 1
                c = self.chats[chat_id] = {"alias": f"telegram:{n}", "zone": None, "wristband": None, "reports": [], "ask": None,
                                           "hits": deque(), "warned": 0.0, "told": {}}
                self._alias[c["alias"]] = chat_id
            return c

    def _allowed(self, c: dict[str, Any]) -> bool:
        now = time.monotonic()
        hits: deque = c["hits"]
        while hits and now - hits[0] > self.rate_window:
            hits.popleft()
        if len(hits) >= self.rate_max:
            self.stats["rate_limited"] += 1
            return False
        hits.append(now)
        return True

    def _handle(self, u: dict[str, Any]) -> None:
        self._sync_session()
        cq = u.get("callback_query")
        if cq:
            return self._on_button(cq)
        msg = u.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        if chat_id is None:
            return
        c = self._chat(int(chat_id))
        if not self._allowed(c):
            if time.monotonic() - c["warned"] > self.rate_window:   # se avisa UNA vez por ventana: el bot no amplifica
                c["warned"] = time.monotonic()
                self.send(chat_id, "Demasiados mensajes seguidos. Espera un minuto. Tus avisos anteriores ya están en el centro de control.")
            return
        if msg.get("location"):
            return self._on_location(chat_id, c, msg["location"])
        text = str(msg.get("text") or "").strip()
        if not text:
            return self.send(chat_id, "Solo entiendo texto o tu ubicación. Escribe qué pasa y dónde.")
        if len(text) > self.max_chars:
            self.stats["too_long"] += 1
            return self.send(chat_id, f"Mensaje demasiado largo (máximo {self.max_chars} caracteres). Resúmelo: qué pasa y dónde.")
        if text.startswith("/"):
            return self._on_command(chat_id, c, text)
        if c["ask"] and self._answer(chat_id, c, text):
            return
        self._report(chat_id, c, text, metadata=msg.get('metadata'))

    def _zones(self) -> dict[str, str]:
        return {z["id"]: z["name"] for z in self.get_session().festival["zones"]}

    def _on_command(self, chat_id: int, c: dict[str, Any], text: str) -> None:
        cmd, _, arg = text.partition(" ")
        cmd, arg = cmd.split("@")[0].lower(), arg.strip()
        if cmd in ("/start", "/ayuda", "/help"):
            return self.send(chat_id, START)
        if cmd == "/zona":
            zones = self._zones()
            z = match_zone(arg, zones)
            if z is None:
                return self.send(chat_id, "No conozco esa zona. Prueba: " + " · ".join(re.sub(r"\s*\(.*", "", n) for n in zones.values()))
            c["zone"] = z
            if c["ask"] and self._answer(chat_id, c, f"Estoy en {zones[z]}"):
                return
            return self.send(chat_id, f"Zona fijada: {zones[z]}. Tus avisos saldrán con esa zona.")
        if cmd == "/pulsera":
            prof = self.wristband(arg)
            if prof is None:
                return self.send(chat_id, "No encuentro esa pulsera. El código está impreso en ella (por ejemplo FA-1007).")
            c["wristband"] = prof["code"]
            tags = ", ".join(prof.get("tags") or []) or "sin etiquetas de asistencia"
            return self.send(chat_id, f"Pulsera {prof['code']} asociada a tus avisos: acceso {prof['access']} · {tags}. "
                                      "Perfil de demostración, inventado. La pulsera NO da tu ubicación: dila tú.")
        if cmd == "/estado":
            return self.send(chat_id, self._status_text(c))
        if cmd == "/golpe":
            left = self.get_session().jury_left()
            if left <= 0:
                return self.send(chat_id, "El jurado ya ha gastado sus 3 golpes en esta partida.")
            rows = [[{"text": p["label"], "callback_data": f"golpe:{k}"}] for k, p in self.strike_presets.items()]
            return self.send(chat_id, f"Rompe el plan. Quedan {left} de 3 golpes entre todos. Elige uno y mira la pantalla grande:",
                             {"inline_keyboard": rows})
        self.send(chat_id, "No conozco ese comando. /start para ver qué puedes hacer.")

    def _on_button(self, cq: dict[str, Any]) -> None:
        chat_id = ((cq.get("message") or {}).get("chat") or {}).get("id")
        key = str(cq.get("data") or "").removeprefix("golpe:")
        try:
            self._call("answerCallbackQuery", {"callback_query_id": cq.get("id")})
        except Exception:
            pass
        if chat_id is None or key not in self.strike_presets:
            return
        c = self._chat(int(chat_id))
        if not self._allowed(c):
            return
        try:
            out = self.submit_strike(key, author=c["alias"])
            self.send(chat_id, f"Golpe lanzado: {out['strike']['label']}. Quedan {out['left']}. Si rompe un supuesto, Mando tira el plan y hace otro.")
        except PermissionError as e:
            self.send(chat_id, str(e))
        except ValueError:
            self.send(chat_id, "Ese golpe no existe.")

    def _on_location(self, chat_id: int, c: dict[str, Any], loc: dict[str, Any]) -> None:
        try:
            zone, folded = nearest_zone(float(loc["latitude"]), float(loc["longitude"]))
        except (KeyError, TypeError, ValueError):
            return
        name = self._zones().get(zone, zone)
        c["zone"] = zone
        if c["ask"] and self._answer(chat_id, c, f"Estoy en {name}"):
            return
        self.send(chat_id, f"Zona fijada: {name}." + (" (El recinto es ficticio: tu ubicación real se ha trasladado al plano.)" if folded else "")
                  + " Ahora escribe qué pasa.")

    def _report(self, chat_id: int, c: dict[str, Any], text: str, metadata: dict | None = None) -> None:
        metadata = metadata or {}
        hub = self.chat_hub
        if hub is not None and hub.available:   # EXACTAMENTE la misma sesión de recogida que la web, una por chat
            c["hub"] = True
            turn = hub.turn(f"tg-{c['alias']}", text, channel="telegram", zone_hint=c["zone"], pulsera=c["wristband"],
                            lang=metadata.get('lang', 'es'), pre_extracted=metadata.get('extracted') or None,
                            push=lambda t, chat_id=chat_id: self.send(chat_id, t))
            for rid in turn.get("reports") or []:
                c["reports"].append(rid)
            self.stats["reports"] += len(turn.get("reports") or [])
            for line in (turn.get("say"), turn.get("instruction")):
                if line:
                    self.send(chat_id, "\n".join(line.get("steps", [])) if isinstance(line, dict) else str(line))
            return
        out = self.submit_report("whatsapp", text, c["zone"], source=c["alias"], wristband=c["wristband"],
                                 lang=metadata.get('lang', 'es'), extracted=metadata.get('extracted'),
                                 delegate=not bool(metadata.get('extracted')))
        rid = out.get("report_id")
        if rid:
            c["reports"].append(rid)
            del c["reports"][:-10]
        self.stats["reports"] += 1
        self.send(chat_id, ACK)
        inst = safety_instruction(text)
        if inst is not None:
            self.send(chat_id, inst[1])
        if not c["zone"] and rid:
            self.send(chat_id, "Si puedes, dime dónde estás: /zona puerta b, o comparte tu ubicación.")

    # ---------------------------------------------------------------- preguntas de Mando
    def route_ask(self, session: Any, action: Any) -> bool:
        """Lo llama `HappyRobotComms.send` con cada ASK. True = esta pregunta es para alguien que avisó por Telegram."""
        if (session is not self.get_session() or self.status != "on" or action.resource
                or action.params.get("purpose") == "sitrep" or action.params.get("to") in session.world.resources):
            return False
        m = re.match(r"telegram:\d+", str(action.params.get("to") or ""))
        with self._lock:
            chat_id = self._alias.get(m.group(0)) if m else None
            if chat_id is None:
                mine = {rid: cid for cid, c in self.chats.items() for rid in c["reports"]}
                chat_id = next((mine[r] for r in action.params.get("reports") or [] if r in mine), None)
            if chat_id is None:
                return False
            self.chats[chat_id]["ask"] = action.id
        question = str(action.params.get("message") or "¿Puedes darme más detalles?")
        self.stats["asks"] += 1
        self.send(chat_id, "Centro de control: " + question)   # si es reservado, Mando ya manda una pregunta neutra
        return True

    def _answer(self, chat_id: int, c: dict[str, Any], text: str) -> bool:
        action_id, c["ask"] = c["ask"], None
        if not self.get_session().comms.answer_external(action_id, text):
            return False   # la pregunta ya caducó (contestó la simulación): lo que escribe entra como aviso nuevo
        self.stats["answers"] += 1
        self.send(chat_id, "Gracias. Lo paso al centro de control.")
        return True

    # ---------------------------------------------------------------- estado y cierres
    def _incident_of(self, c: dict[str, Any]) -> dict[str, Any] | None:
        st = self.get_session().state()
        for rid in reversed(c["reports"]):
            inc = next((i for i in st.get("incidents", []) if rid in i.get("reports", [])), None)
            if inc is not None:
                return inc
        return None

    def _status_text(self, c: dict[str, Any]) -> str:
        if not c["reports"]:
            return "Todavía no has mandado ningún aviso en esta partida."
        inc = self._incident_of(c)
        if inc is None:
            return "Aviso recibido. El centro de control todavía no lo ha clasificado."
        if inc.get("reserved") or inc.get("zone_masked"):
            return "Tu aviso está en el centro de control y se está atendiendo."   # reservado: ni tipo, ni zona, ni detalle
        s = self.get_session()
        info = s.report_status(c["reports"][-1]) if hasattr(s, "report_status") else {}
        state = {"open": "sin equipo asignado todavía", "assigned": "equipo en camino", "in_progress": "equipo en el sitio",
                 "resolved": "resuelto", "false_alarm": "cerrado", "failed": "no se llegó a tiempo"}.get(str(inc.get("status")), "en curso")
        merged = f" Fusionado con {info['merged_with']} aviso(s) del mismo incidente." if info.get("merged_with") else ""
        return f"Tu aviso: {inc.get('label') or 'incidente'} · prioridad {inc.get('priority')} · {state}.{merged}"

    def _sync_session(self) -> None:
        sid = getattr(self.get_session(), "session_id", "")
        if sid != self._session_id:
            self._session_id = sid
            with self._lock:
                self.chats.clear()
                self._alias.clear()
                while not self._outbox.empty():
                    try:
                        self._outbox.get_nowait()
                    except queue.Empty:
                        break

    def receive_report(self, reply_to: str, text: str, metadata: dict | None = None) -> dict[str, Any]:
        """Entrada del puente autenticado; usa el mismo chat que getUpdates."""
        chat_id = int(str(reply_to).removeprefix("tg:"))
        self._sync_session()
        if metadata and (metadata.get('zone') or metadata.get('where')):
            self._chat(chat_id)['zone'] = metadata.get('zone') or metadata.get('where')
        self._handle({"message": {"chat": {"id": chat_id}, "text": text, 'metadata': metadata}})
        c = self._chat(chat_id)
        return {"ok": True, "duplicate": False, "report_id": c["reports"][0] if c["reports"] else None}

    def _notify_loop(self) -> None:
        """Cierre del circuito con quien avisó: «Equipo en camino» y «Resuelto», una vez cada uno."""
        while not self._stop.wait(1.0):
            if self.status != "on":
                continue
            try:
                self._sync_session()
                with self._lock:
                    chats = list(self.chats.items())
                for chat_id, c in chats:
                    if c.get("hub"):
                        continue   # a ese chat ya le cuenta los cambios su sesión de recogida
                    inc = self._incident_of(c) if c["reports"] else None
                    if inc is None:
                        continue
                    status = str(inc.get("status"))
                    told = c["told"].setdefault(inc["id"], set())
                    if status in CLOSING and status not in told and not (status == "in_progress" and "assigned" in told):
                        told.add(status)
                        self.send(chat_id, CLOSING[status])
                self._flush()
            except Exception as e:
                self.error = f"notify: {type(e).__name__}"


def start_from_env(**kwargs: Any) -> TelegramBot | None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    return TelegramBot(token, **kwargs).start() if token and os.environ.get("TELEGRAM_MODE", "poll") != "off" else None
