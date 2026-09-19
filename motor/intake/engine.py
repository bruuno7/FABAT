"""Agente de recogida: conversa con quien avisa, va rellenando los datos del protocolo y se los pasa a Mando
sobre la marcha. Determinista y explicable: sin LLM, sin red, sin reloj y sin azar (mismos mensajes = mismos turnos).

Tres reglas que no se negocian:
1. NUNCA retrasa el envío: el primer `Report` sale en cuanto hay riesgo vital o se cumplen los `dispatch_as_soon_as`,
   marcado como parcial; cada dato nuevo sale como ACTUALIZACIÓN enlazada al mismo aviso.
2. Las instrucciones previas a la llegada salen SOLO de la lista del protocolo. Ni el motor ni el gancho `understand`
   pueden redactar una.
3. No diagnostica, no promete tiempos, no da órdenes de evacuar y no obedece órdenes de quien escribe.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..contracts import Channel, Report, Zone
from ..mando.parser import HeuristicParser, normalize
from . import nlu

HERE = Path(__file__).resolve().parent
REAL_PROTOCOLS = HERE.parent / "protocolos" / "protocolos.json"
SAMPLE_PROTOCOLS = HERE / "protocolos.sample.json"

# canal real → canal del contrato (`telegram` y `web` no existen en `Channel`; mismo criterio que motor/server/intake.py)
CHANNELS = {"voice": Channel.VOICE, "web_call": Channel.VOICE, "phone": Channel.VOICE, "sms": Channel.SMS,
            "email": Channel.SMS, "telegram": Channel.WHATSAPP, "whatsapp": Channel.WHATSAPP, "web": Channel.WHATSAPP,
            "radio": Channel.RADIO, "operator": Channel.OPERATOR}
DEFAULTS = {"max_questions": 5, "unknown_twice": 2, "silence_s": 60, "off_topic_turns": 3, "max_asks_per_slot": 2}

# Frase que el parser de Mando lee como ese tipo (lo comprueba test_intake). Si el tipo no está aquí se usa un patrón
# literal de su ficha en el léxico de Mando.
TYPE_PHRASE = {
    "fainting": "desmayo", "unconscious_person": "persona inconsciente", "cardiac_arrest": "no respira",
    "heat_stroke": "golpe de calor", "crowd_surge": "mucha gente empujando", "crush_risk": "riesgo de aplastamiento",
    "fight": "pelea", "injury": "persona herida", "sexual_assault": "aviso para el punto violeta",
    "lost_child": "menor perdido", "weapon": "hay un arma", "seizure": "convulsiones", "fire": "fuego",
    "breathing_difficulty": "se ahoga", "allergic_reaction": "reacción alérgica", "intoxication": "intoxicación",
    "dizziness": "mareo", "gate_saturation": "acceso saturado", "structure_risk": "riesgo en una estructura",
    "suspicious_object": "objeto sospechoso", "water_out": "no queda agua", "power_outage": "apagón", "storm": "tormenta",
    "high_wind": "rachas de viento", "theft": "robo", "toilets_failure": "baños atascados",
    # pistas que usan los protocolos reales (nombres de la taxonomía de casos, no del léxico de Mando). `cardiac_arrest`
    # como PISTA de protocolo no afirma que no respire: eso solo lo dice el dato «no respira».
    "anaphylaxis": "reacción alérgica", "trauma_fall": "persona herida", "intoxication_overdose": "intoxicación",
    "crowd_surge_general": "mucha gente empujando", "small_fire": "fuego", "strong_wind_gusts": "rachas de viento",
    "lightning_nearby": "tormenta con rayos", "sexual_assault_report": "aviso para el punto violeta",
    "chemical_submission": "aviso para el punto violeta", "power_outage_food": "apagón", "toilets_blocked": "baños atascados",
    "weapon_seen": "hay un arma", "bomb_threat_call": "amenaza",
}
_HINT_ONLY = {"cardiac_arrest": "persona inconsciente"}

_T = {
    "ack_first": {"es": "Entendido.", "en": "Understood."},
    "ack": {"es": "Anotado.", "en": "Noted."},
    "ok": {"es": "De acuerdo.", "en": "All right."},
    "ack_facts": {"es": "Anotado: {facts}.", "en": "Noted: {facts}."},
    "sent": {"es": "Ya he pasado el aviso al centro de control.", "en": "I have passed this on to the control centre."},
    "sent_reserved": {"es": "Ya lo he pasado, en reservado, a una persona responsable.",
                      "en": "I have passed it on, in private, to a responsible person."},
    "reserved_ack": {"es": "Gracias por decírmelo. Esto lo trata una persona, en privado.",
                     "en": "Thank you for telling me. A person will handle this, in private."},
    "do_now": {"es": "Haz esto ahora:", "en": "Do this now:"},
    "contain": {"es": "Estoy contigo, vamos paso a paso.", "en": "I am with you, one step at a time."},
    "order": {"es": "Eso no se ordena por aquí: lo decide una persona del centro de control. Yo recojo tu aviso.",
              "en": "That cannot be ordered from here: a person at the control centre decides it. I take your report."},
    "role": {"es": "No puedo cambiar de tarea: solo recojo avisos de emergencia del recinto.",
             "en": "I cannot change my task: I only take emergency reports for the venue."},
    "off_topic": {"es": "Solo atiendo avisos de emergencia del recinto.", "en": "I only handle emergency reports for the venue."},
    "tell_me": {"es": "Cuéntame qué pasa y dónde.", "en": "Tell me what is happening and where."},
    "close": {"es": "Tu aviso está en el centro de control. Si cambia algo, escríbeme.",
              "en": "Your report is with the control centre. If anything changes, message me."},
    "close_voice": {"es": "Tu aviso está en el centro de control. Si cambia algo, dímelo.",
                    "en": "Your report is with the control centre. If anything changes, tell me."},
    "close_empty": {"es": "Cierro la conversación. Si pasa algo, escríbeme.", "en": "I am closing this chat. If something happens, message me."},
    "silence": {"es": "No recibo respuesta. He pasado el aviso con lo que tengo. Escríbeme cuando puedas.",
                "en": "I am not getting a reply. I have passed on what I have. Message me when you can."},
    "all_clear": {"es": "Gracias por decirlo. Se lo paso al centro de control.", "en": "Thanks for telling me. I am passing it on to the control centre."},
    "retry": {"es": "Si puedes comprobarlo: ", "en": "If you can check: "},
    "other": {"es": "Sobre lo otro ({label}): ", "en": "About the other thing ({label}): "},
    "landmark": {"es": "¿Qué ves cerca: una puerta, una barra, los baños, el escenario?",
                 "en": "What can you see nearby: a gate, a bar, the toilets, the stage?"},
    "why_location": {"es": "sin saber dónde no puedo mandar a nadie", "en": "without a place I cannot send anyone"},
    "why_landmark": {"es": "con un punto de referencia sé qué equipo está más cerca", "en": "with a landmark I know which team is closest"},
    "why_mando": {"es": "lo pregunta el centro de control para decidir", "en": "the control centre asks this in order to decide"},
    "police": {"es": "La policía solo se avisa si tú quieres.", "en": "The police are only called if you want."},
    "empty": {"es": "No te he leído. ", "en": "I did not get that. "},
    "no_diagnosis": {"es": "No puedo decirte qué le pasa: eso lo valora el equipo sanitario.",
                     "en": "I cannot tell you what is wrong: the medical team assesses that."},
    "no_eta": {"es": "No puedo darte un tiempo. Tu aviso ya está en el centro de control.",
               "en": "I cannot give you a time. Your report is already with the control centre."},
    "again": {"es": "No lo he entendido bien.", "en": "I did not quite get that."},
    "yes_no": {"es": " Dime sí o no.", "en": " Tell me yes or no."},
}
_STATUS = {
    "received": {"es": "El centro de control ya tiene tu aviso.", "en": "The control centre has your report."},
    "held": {"es": "El centro de control está confirmando el aviso.", "en": "The control centre is confirming the report."},
    "dispatched": {"es": "Ya va {team} hacia ti{eta}.", "en": "{team} is on the way to you{eta}."},
    "en_route": {"es": "Ya va {team} hacia ti{eta}.", "en": "{team} is on the way to you{eta}."},
    "on_scene": {"es": "El equipo dice que ya está en el sitio. Hazle señas.", "en": "The team says it is on site. Wave at them."},
    "delayed": {"es": "El equipo que iba ha tenido un problema. Ya sale otro.", "en": "The team on its way had a problem. Another one is leaving now."},
    "reassigned": {"es": "El equipo que iba ha tenido un problema. Ya sale otro.", "en": "The team on its way had a problem. Another one is leaving now."},
    "awaiting_approval": {"es": "Una persona del centro de control lo está decidiendo ahora.", "en": "A person at the control centre is deciding this now."},
    "merged": {"es": "Ya había un aviso de esto. He sumado lo que me has contado.", "en": "There was already a report about this. I added what you told me."},
    "resolved": {"es": "El centro de control da el aviso por atendido. Gracias.", "en": "The control centre marks this as attended. Thank you."},
    "false_alarm": {"es": "El centro de control ha cerrado el aviso. Gracias.", "en": "The control centre has closed the report. Thank you."},
    "handoff": {"es": "Te paso con una persona del centro de control.", "en": "I am putting you through to a person at the control centre."},
}
_TEAM = {"medical": ("un equipo sanitario", "A medical team"), "ambulance": ("una ambulancia", "An ambulance"),
         "security": ("un equipo de seguridad", "A security team"), "tech": ("un equipo técnico", "A technical team"),
         "logistics": ("un equipo de logística", "A logistics team"), "volunteer": ("un voluntario", "A volunteer"),
         None: ("un equipo", "A team")}


def load_protocols(path: str | Path | None = None) -> dict[str, Any]:
    """Primero `motor/protocolos/protocolos.json` (el real); si no existe o está a medio escribir, la muestra."""
    for p in ([Path(path)] if path else [REAL_PROTOCOLS, SAMPLE_PROTOCOLS]):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("protocols"), list) and data["protocols"]:
            data["_path"] = str(p)
            return data
    raise FileNotFoundError("no hay ningún protocolos.json legible")


def never_patterns(items: list[Any]) -> list[re.Pattern]:
    """`never_say` → patrones sobre texto normalizado. Acepta frases sueltas o fichas {"es": "«a» / «b»", "en": ..., "why": ...};
    de una ficha solo cuentan los trozos entre «comillas» (el resto es explicación) y «X» vale por cualquier palabra."""
    out: list[re.Pattern] = []
    for it in items:
        texts = [str(v) for k, v in it.items() if k in ("es", "en", "text", "phrase")] if isinstance(it, dict) else [str(it)]
        for txt in texts:
            quoted = re.findall(r"«([^»]+)»", txt)
            for chunk in (quoted if quoted else ([txt] if not isinstance(it, dict) else [])):
                for piece in chunk.split(" / "):
                    n = normalize(piece.replace("…", " "))
                    if len(n) >= 4:
                        out.append(re.compile(r"\b" + re.escape(n).replace(r"\ x\ ", r"\ \w+\ ") + r"\b"))
    return out


def load_zones() -> dict[str, Zone]:
    from ..world.world import load_festival
    return {z["id"]: Zone(z["id"], z.get("name", z["id"]), z.get("kind", "general"), float(z.get("area_m2", 1)),
                          int(z.get("capacity", 0)), neighbors=list(z.get("neighbors", [])))
            for z in load_festival()["zones"]}


def _loc(d: Any, lang: str) -> str:
    if isinstance(d, dict):
        return str(d.get(lang) or d.get("es") or d.get("en") or "")
    return str(d or "")


def _matches(cond: Any, value: Any) -> bool:
    """Valor de un `if`/`ask_if`: literal, lista (= cualquiera de) o {"gte"|"gt"|"lte"|"lt"|"in": x}."""
    if isinstance(cond, dict):
        try:
            return all({"gte": value >= v, "gt": value > v, "lte": value <= v, "lt": value < v,
                        "in": value in v if isinstance(v, list) else False}.get(op, False) for op, v in cond.items())
        except TypeError:
            return False
    if isinstance(cond, list):
        return value in cond
    if isinstance(cond, bool) or isinstance(value, bool):      # True no es 1
        return isinstance(cond, bool) and isinstance(value, bool) and cond == value
    return value == cond


@dataclass
class SlotValue:
    value: Any
    confidence: float
    source: str            # user | answer | channel | mando_parser | understand | inherited
    turn: int

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "confidence": self.confidence, "source": self.source, "turn": self.turn}


@dataclass
class Thread:
    """Un incidente dentro de la conversación (un mensaje puede abrir dos)."""
    id: str                                   # id raíz del aviso: todos sus `Report` empiezan por él
    proto: dict[str, Any]
    slots: dict[str, SlotValue] = field(default_factory=dict)
    gave_up: dict[str, str] = field(default_factory=dict)     # slot -> unknown | unanswered
    dunno: dict[str, int] = field(default_factory=dict)
    asks: dict[str, int] = field(default_factory=dict)
    texts: list[str] = field(default_factory=list)            # lo que ha dicho la persona sobre este incidente
    reserved: bool = False
    parser_life: bool = False                 # el parser de Mando vio señal de riesgo vital en el texto
    parser_type: str = ""
    life_risk: bool = False
    severity_min: int = 0
    needs: dict[str, int] = field(default_factory=dict)
    dispatch_now: bool = False
    fired: list[int] = field(default_factory=list)            # índices de red_flags que ya saltaron
    given: list[str] = field(default_factory=list)            # instrucciones ya dadas
    flag_hint: str = ""                       # `mando_type_hint` de la señal que manda, si lo trae
    dispatched: bool = False
    n_reports: int = 0
    sent: dict[str, Any] = field(default_factory=dict)        # último valor de cada slot enviado a Mando
    closed: bool = False
    landmark_asked: bool = False
    prank: bool = False                       # parece una broma: se reenvía marcada y no se pregunta nada
    assumed: list[str] = field(default_factory=list)          # datos vitales que nadie pudo confirmar: se asume lo peor

    def has(self, slot: str) -> bool:
        return slot in self.slots

    def val(self, slot: str) -> Any:
        return self.slots[slot].value if slot in self.slots else None


@dataclass
class Turn:
    say: str
    instruction: dict[str, Any] | None
    reports: list[Report]
    state: dict[str, Any]
    why_next: str
    done: bool
    lang: str = "es"
    ask: dict[str, Any] | None = None          # {"thread","slot","type","options"}: para pintar respuestas rápidas
    report_meta: list[dict[str, Any]] = field(default_factory=list)   # en paralelo a `reports`: partial, reserved, needs…
    answers: list[dict[str, Any]] = field(default_factory=list)       # respuestas a preguntas de Mando (ASK)
    flags: list[str] = field(default_factory=list)                    # order_refused, off_topic, contained, lang_switch…
    question: str = ""                         # la pregunta de `say`, aparte (para pintarla distinta o decirla al final)

    def speech(self) -> str:
        """Todo en una sola locución, para voz: acuse, pasos de la instrucción y, al final, la pregunta."""
        if not self.instruction:
            return self.say
        head = self.say[:len(self.say) - len(self.question)].strip() if self.question and self.say.endswith(self.question) else self.say
        steps = _T["do_now"][self.lang] + " " + " ".join(self.instruction["steps"])
        return " ".join(x for x in (head, steps, self.question if head != self.say else "") if x)

    def to_dict(self) -> dict[str, Any]:
        return {"say": self.say, "instruction": self.instruction, "reports": [r.to_dict() for r in self.reports],
                "report_meta": self.report_meta, "state": self.state, "why_next": self.why_next, "done": self.done,
                "lang": self.lang, "ask": self.ask, "answers": self.answers, "flags": self.flags, "question": self.question}


class IntakeSession:
    """Una sesión por conversación. `receive(text)` por cada mensaje de la persona; `mando_asks()` y `notify()` para lo
    que viene de Mando; `silence(segundos)` cuando nadie contesta."""

    def __init__(self, channel: Channel | str = "web", lang: str | None = None, zone_hint: str | None = None,
                 profile: dict[str, Any] | None = None, protocols: dict[str, Any] | None = None,
                 understand: Callable[[str, str, list[dict[str, Any]]], dict[str, Any]] | None = None, *,
                 session_id: str = "S1", zones: dict[str, Zone] | None = None, t: int = 0) -> None:
        self.real_channel = str(channel)
        self.channel = channel if isinstance(channel, Channel) else CHANNELS.get(str(channel).lower(), Channel.WHATSAPP)
        self.lang = lang if lang in ("es", "en") else None
        self.fixed_lang = False
        self.profile = dict(profile or {})
        self.data = protocols if protocols is not None else load_protocols()
        self.glob: dict[str, Any] = self.data.get("global") or {}
        self.protocols: list[dict[str, Any]] = list(self.data["protocols"])
        self.understand = understand
        self.session_id = session_id
        self.zones = zones if zones is not None else load_zones()
        self.zone_hint = zone_hint if zone_hint in self.zones else None
        self.t = t
        self.limits = dict(DEFAULTS)
        for rule in self.glob.get("stop_rules") or []:
            if isinstance(rule, dict):
                key = rule.get("id") or rule.get("rule") or rule.get("when")
                if key in self.limits and isinstance(rule.get("value"), (int, float)):
                    self.limits[str(key)] = int(rule["value"])
        self._never = never_patterns(self.glob.get("never_say") or [])
        self._parser = HeuristicParser()
        self._triggers = {p["id"]: self._compile_triggers(p) for p in self.protocols}
        self._generic = next((p for p in self.protocols if p["id"] in ("generic", "other", "otro", "generico")),
                             next((p for p in self.protocols if not any((p.get("triggers") or {}).values())), self.protocols[-1]))
        self.threads: list[Thread] = []
        self.active: Thread | None = None
        self.pending: tuple[str, str] | None = None        # (thread id, slot) de la pregunta que está en el aire
        self.questions_asked = 0
        self.turn_no = 0
        self.off_topic = 0
        self.contained = 0
        self.done = False
        self._mando_q: dict[str, Any] | None = None
        self._was_pending: tuple[str, str] | None = None
        self._mando_n = 0
        self.transcript: list[dict[str, str]] = []

    # ------------------------------------------------------------------ utilidades
    def _compile_triggers(self, proto: dict[str, Any]) -> list[tuple[re.Pattern, bool]]:
        out = []
        trig = proto.get("triggers") or {}
        for phrases in (trig.values() if isinstance(trig, dict) else [trig]):
            for ph in phrases or []:
                n = normalize(str(ph))
                if n:
                    weak = len(n.split()) == 1 and bool(self._parser.find_zones(n, self.zones))
                    out.append((re.compile(r"\b" + re.escape(n)), weak))
        return out

    def _tr(self, key: str, **kw: Any) -> str:
        return _T[key][self.lang or "es"].format(**kw)

    def _slot_def(self, th: Thread, slot: str) -> dict[str, Any]:
        return next((s for s in th.proto.get("slots", []) if s["id"] == slot), {"id": slot, "type": "text"})

    @staticmethod
    def _loc_slot(proto: dict[str, Any]) -> str | None:
        return next((s["id"] for s in proto.get("slots", []) if s.get("type") == "zone_point"), None)

    def _source(self) -> str:
        if self.profile.get("verified_staff") and self.profile.get("role"):
            return str(self.profile["role"])[:40]
        return f"asistente {self.session_id}"

    def _new_thread(self, proto: dict[str, Any], reserved: bool = False) -> Thread:
        th = Thread(id=f"R-{self.session_id}-{len(self.threads) + 1}", proto=proto,
                    reserved=bool(proto.get("sensitive")) or reserved)
        loc = self._loc_slot(proto)
        if loc and self.zone_hint:
            th.slots[loc] = SlotValue({"zone": self.zone_hint, "point": None}, 0.9, "channel", self.turn_no)
        self.threads.append(th)
        return th

    # ------------------------------------------------------------------ qué protocolo
    def _hits(self, norm: str) -> dict[str, bool]:
        """{protocolo: ¿algún disparador FUERTE?}. Un disparador que solo nombra un sitio («baños», «tornos») es débil:
        «estamos en los baños» dice dónde, no qué pasa; solo decide si ningún otro protocolo encaja."""
        out: dict[str, bool] = {}
        for p in self.protocols:
            for rx, weak in self._triggers[p["id"]]:
                m = rx.search(norm)
                if m and not (nlu.NEGATOR.search(norm[:m.start()]) and not rx.pattern.startswith(r"\bno\ ")):
                    out[p["id"]] = out.get(p["id"], False) or not weak
        return out

    def _best(self, norm: str, parsed: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
        """(protocolo, ¿solo por disparadores débiles?). Entre los que encajan gana el que va ANTES en el fichero
        (van de más a menos crítico): es la regla de desempate de los propios protocolos."""
        hits = self._hits(norm)
        ptype = str(parsed.get("type") or "unknown")
        if not ptype.startswith("unknown"):      # el parser de Mando reconoce el tipo aunque ningún disparador lo nombre
            for p in self.protocols:
                hint = p.get("mando_type_hint")
                for h in (hint if isinstance(hint, list) else [hint] if hint else []):
                    if h and (str(h).startswith(ptype) or ptype.startswith(str(h))):
                        hits[p["id"]] = True
        for strong in (True, False):
            found = next((p for p in self.protocols if hits.get(p["id"]) is strong), None)
            if found is not None:
                return found, not strong
        return None, False

    def _parse(self, text: str) -> dict[str, Any]:
        return self._parser.parse(Report(id="probe", t=self.t, channel=self.channel, text=text, source=self._source(),
                                         zone_hint=None), self.zones)

    def _segments(self, low: str) -> list[dict[str, Any]]:
        """Incidentes que trae el mensaje. Lo normal es UNO. Son dos solo si hay una señal clara: un conector («además»,
        «también»), dos sitios distintos, o una persona en riesgo vital dentro de otro problema («pelea y uno no respira»)."""
        pieces, last, conn = [], 0, False
        for m in nlu.SPLIT.finditer(low):
            chunk = low[last:m.start()].strip()
            if chunk:
                pieces.append((chunk, conn))
            conn = conn if not chunk else False
            conn = conn or bool(nlu.CONNECTOR.search(m.group(0)))
            last = m.end()
        if low[last:].strip():
            pieces.append((low[last:].strip(), conn))
        kept: list[dict[str, Any]] = []
        loose: list[str] = []
        for chunk, connector in pieces:
            _, norm = nlu.prep(chunk)
            parsed = self._parse(chunk)
            proto, weak = self._best(norm, parsed)
            zones = self._parser.find_zones(norm, self.zones)
            g = {"proto": proto, "text": chunk, "zones": zones, "connector": connector,
                 "life": bool(parsed.get("life_threat")), "family": (proto or {}).get("family")}
            if proto is None or weak:
                (kept[-1]["extra"] if kept else loose).append(chunk)
                if kept:
                    kept[-1]["zones"] += [z for z in zones if z not in kept[-1]["zones"]]
                continue
            first = kept[0] if kept else None
            separate = first is None or (proto["id"] != first["proto"]["id"] and (
                connector
                or (zones and first["zones"] and zones[0] != first["zones"][0])
                or (g["life"] and g["family"] == "medical" and first["family"] != "medical")
                or (first["life"] and first["family"] == "medical" and g["family"] != "medical")))
            if separate and not any(k["proto"]["id"] == proto["id"] for k in kept):
                g["extra"] = []
                kept.append(g)
            else:
                target = next((k for k in kept if k["proto"]["id"] == proto["id"]), kept[0])
                target["extra"].append(chunk)
                target["zones"] += [z for z in zones if z not in target["zones"]]
        if not kept:
            return []
        kept[0]["text"] = ". ".join(loose + [kept[0]["text"]])
        for k in kept:
            k["text"] = ". ".join([k["text"]] + k.pop("extra"))
            _, knorm = nlu.prep(k["text"])
            k["proto"] = self._best(knorm, self._parse(k["text"]))[0] or k["proto"]    # con todo su texto delante
        return kept

    # ------------------------------------------------------------------ slots
    def _set(self, th: Thread, slot: str, value: Any, conf: float, source: str) -> bool:
        old = th.slots.get(slot)
        if old is not None and old.value == value:
            old.confidence = max(old.confidence, conf)
            return False
        if old is not None and source in ("understand", "mando_parser", "inherited"):
            return False                      # lo que dijo la persona no lo pisa una fuente más débil
        if old is not None and conf < 0.65 <= old.confidence:
            return False                      # un indicio («se ha desmayado») no pisa una respuesta clara
        th.slots[slot] = SlotValue(value, round(conf, 2), source, self.turn_no)
        th.gave_up.pop(slot, None)
        return True

    def _location(self, low: str, norm: str, th: Thread, slot: str, pending: bool) -> bool:
        zones = self._parser.find_zones(norm, self.zones)
        m = nlu.POINT.search(low)
        point = f"{m.group(1)} {m.group(2).strip()}" if m else None
        old = th.val(slot) or {}
        zone = zones[0] if zones else None
        if old.get("zone") and zone and zone != old["zone"] and not pending:
            zone = None                      # «ha ido al baño» en otra respuesta no mueve el incidente
        if not zone and not point and pending and not nlu.DUNNO.search(norm) and nlu.bare_yes_no(low) is None \
                and len(norm) >= 3 and not nlu.ORDER.search(norm) and not nlu.ROLE.search(norm):
            point = low.strip(" .,;:!?¿¡")[:80]
        if not zone and not point:
            return False
        value = {"zone": zone or old.get("zone"), "point": point or old.get("point")}
        conf = 0.4 if not value["zone"] else 0.7 if (point or nlu.HEDGE.search(norm)) else 0.8
        return self._set(th, slot, value, max(conf, 0.0), "answer" if pending else "user")

    def _extract(self, th: Thread, low: str, norm: str) -> list[str]:
        """Rellena TODOS los slots que el mensaje permita, no solo el que se preguntó. Devuelve los que cambian."""
        changed: list[str] = []
        pend = self.pending[1] if self.pending and self.pending[0] == th.id else None
        # «no sé si respira»: eso es una duda sobre `breathing`, no un «respira»
        doubts: set[str] = set()
        for m in nlu.DUNNO_ABOUT.finditer(norm):
            clause = m.group(1)
            for s in th.proto.get("slots", []):
                c = nlu.concept_for(s["id"], s.get("type", "text"))
                if s.get("type") == "bool" and c and nlu.detect_bool(c, clause):
                    doubts.add(s["id"])
            norm = norm.replace(m.group(0), " ")
        yn = nlu.bare_yes_no(low)
        for s in th.proto.get("slots", []):
            sid, typ = s["id"], s.get("type", "text")
            is_pend = sid == pend
            concept = nlu.concept_for(sid, typ)
            if sid in doubts:
                continue
            if typ == "zone_point":
                if self._location(low, norm, th, sid, is_pend):
                    changed.append(sid)
            elif typ == "bool":
                hit = None
                forced = nlu.match_phrases(s.get("match"), norm)
                if forced is not None:
                    hit = (forced, 0.85)
                elif concept:
                    hit = nlu.detect_bool(concept, norm)
                if is_pend and yn is not None and (hit is None or hit[1] < 0.65):
                    hit = (yn, 0.9)
                if hit and self._set(th, sid, hit[0], hit[1], "answer" if is_pend else "user"):
                    changed.append(sid)
            elif typ == "number":
                n = nlu.detect_number(concept, norm) if concept else None
                if n is None and is_pend:
                    n = nlu.any_number(norm)
                if n is not None and 0 <= n < 1000 and self._set(th, sid, int(n), 0.85, "answer" if is_pend else "user"):
                    changed.append(sid)
            elif typ == "enum":
                # sin que se haya preguntado, un enum solo se rellena si su `ask_if` se cumple: si no, no viene a cuento
                relevant = is_pend or not s.get("ask_if") or self._holds(s["ask_if"], self._answers(th))
                opt = nlu.detect_enum(s.get("options") or [], norm, is_pend) if relevant else None
                if opt is not None and self._set(th, sid, opt, 0.85, "answer" if is_pend else "user"):
                    changed.append(sid)
            else:
                txt = nlu.detect_text(concept, low) if concept else None
                if txt is None and is_pend and not nlu.DUNNO.search(norm) and len(norm) >= 2:
                    txt = low.strip(" .,;:!?¿¡")[:160]
                elif txt is None and concept == "what" and not th.has(sid) and len(norm.split()) >= 3:
                    txt = low.strip(" .,;:!?¿¡")[:160]
                if txt and self._set(th, sid, txt, 0.7 if is_pend else 0.5, "answer" if is_pend else "user"):
                    changed.append(sid)
        # «no lo sé»
        targets = set(doubts)
        if pend and pend not in changed and nlu.DUNNO.search(norm):
            targets.add(pend)
        for sid in targets:
            if th.has(sid):
                continue
            th.dunno[sid] = th.dunno.get(sid, 0) + 1
            critical = bool(self._slot_def(th, sid).get("critical"))
            if th.dunno[sid] >= (self.limits["unknown_twice"] if critical else 1):
                th.gave_up[sid] = "unknown"
        return changed

    def _hook(self, th: Thread, raw: str) -> list[str]:
        """Gancho `understand`: solo puede proponer valores de slots ABIERTOS y del tipo correcto. Nada más entra."""
        if self.understand is None:
            return []
        open_slots = [{"id": s["id"], "type": s.get("type", "text"), "options": s.get("options"),
                       "question": _loc(s.get("question"), self.lang or "es")}
                      for s in th.proto.get("slots", []) if not th.has(s["id"])]
        if not open_slots:
            return []
        try:
            got = self.understand(raw, self.lang or "es", open_slots)
        except Exception:                      # el modelo falla o no hay red: valen las reglas
            return []
        if not isinstance(got, dict):
            return []
        changed = []
        allowed = {s["id"]: s for s in open_slots}
        for sid, v in got.items():
            s = allowed.get(sid)
            if s is None:
                continue
            ok, value = self._validate(s, v)
            if ok and self._set(th, sid, value, 0.6, "understand"):
                changed.append(sid)
        return changed

    def _validate(self, slot: dict[str, Any], v: Any) -> tuple[bool, Any]:
        typ = slot["type"]
        if typ == "bool":
            if isinstance(v, bool):
                return True, v
            w = normalize(str(v))
            return (True, True) if w in ("si", "yes", "true") else (True, False) if w in ("no", "false") else (False, None)
        if typ == "number":
            try:
                n = int(float(v))
            except (TypeError, ValueError):
                return False, None
            return (0 <= n < 1000 and not isinstance(v, bool)), n
        if typ == "enum":
            ids = [o.get("id") if isinstance(o, dict) else o for o in slot.get("options") or []]
            return v in ids, v
        if typ == "zone_point":
            zone = v.get("zone") if isinstance(v, dict) else v if isinstance(v, str) and v in self.zones else None
            point = v.get("point") if isinstance(v, dict) else None if zone else v
            zone = zone if zone in self.zones else None
            point = re.sub(r"\s+", " ", str(point))[:80] if isinstance(point, str) and point.strip() else None
            return bool(zone or point), {"zone": zone, "point": point}
        if isinstance(v, str) and v.strip():
            return True, re.sub(r"\s+", " ", v).strip()[:160]
        return False, None

    # ------------------------------------------------------------------ señales de alarma
    # Semántica de referencia (motor/protocolos/__init__.py): un slot sin contestar no cumple ninguna condición; «no lo sé»
    # vale "unknown"; las señales se evalúan EN ORDEN y gana la primera que se cumple.
    def _answers(self, th: Thread) -> dict[str, Any]:
        out: dict[str, Any] = {k: v.value for k, v in th.slots.items()}
        for sid in list(th.dunno) + list(th.gave_up):
            out.setdefault(sid, "unknown")           # desde el PRIMER «no sé»: la duda no retrasa el envío
        return out

    @staticmethod
    def _holds(cond: dict[str, Any], answers: dict[str, Any]) -> bool:
        return all(k in answers and _matches(v, answers[k]) for k, v in (cond or {}).items())

    def _first_flag(self, th: Thread, answers: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]] | None:
        answers = self._answers(th) if answers is None else answers
        for i, f in enumerate(th.proto.get("red_flags") or []):
            if self._holds(f.get("if") or {}, answers):
                return i, f
        return None

    def _evaluate(self, th: Thread) -> dict[str, Any] | None:
        """Aplica la señal que manda ahora y devuelve su instrucción si aún no se ha dado (sin darla por dada)."""
        th.life_risk = th.life_risk or th.parser_life
        hit = self._first_flag(th)
        if hit is None:
            return None
        i, f = hit
        then = f.get("then") or {}
        th.flag_hint = str(then.get("mando_type_hint") or "") or th.flag_hint
        th.life_risk = th.life_risk or bool(then.get("life_risk"))
        th.severity_min = max(th.severity_min, int(then.get("severity_min") or 0))
        th.dispatch_now = th.dispatch_now or bool(then.get("dispatch_now"))
        for k, n in (then.get("needs") or {}).items():
            th.needs[k] = max(th.needs.get(k, 0), int(n))
        if i not in th.fired:
            th.fired.append(i)
        # datos que nadie pudo confirmar y de los que depende esta señal: se dice, para que control lo sepa
        th.assumed = sorted(k for k in (f.get("if") or {}) if not th.has(k))
        iid = then.get("instruction")
        if not iid or iid in th.given:
            return None
        spec = next((x for x in th.proto.get("instructions") or [] if x.get("id") == iid), None)
        if spec is None:
            return None                      # la señal nombra una instrucción que no está en la lista: no se inventa
        steps = spec.get("steps") or {}
        if isinstance(steps, dict):
            steps = steps.get(self.lang or "es") or steps.get("es") or steps.get("en") or []
        if not steps:
            return None
        return {"id": iid, "steps": [str(x) for x in steps], "source": spec.get("source", ""), "thread": th.id,
                "severity": int(then.get("severity_min") or 0), "life_risk": th.life_risk}

    @staticmethod
    def _give(th: Thread, ins: dict[str, Any]) -> None:
        th.given.append(ins["id"])

    # ------------------------------------------------------------------ política de la siguiente pregunta
    def _askable(self, th: Thread, s: dict[str, Any]) -> bool:
        sid = s["id"]
        if th.has(sid) and not (s.get("type") == "zone_point" and sid == self._loc_slot(th.proto)
                                and not (th.val(sid) or {}).get("zone") and not th.landmark_asked):
            return False
        if sid in th.gave_up or th.asks.get(sid, 0) >= self.limits["max_asks_per_slot"]:
            return False
        if s.get("ask_if") and not self._holds(s["ask_if"], self._answers(th)):
            return False
        hands_busy = any("cpr" in g for g in th.given)       # quien hace compresiones no contesta preguntas
        if hands_busy and s.get("type") != "zone_point":
            return False
        if th.reserved:                      # caso sensible: solo lo imprescindible, nunca detalles
            if not th.proto.get("sensitive"):
                return s.get("type") == "zone_point" and sid == self._loc_slot(th.proto)
            return bool(s.get("critical"))
        hit = self._first_flag(th)
        if hit is not None and (hit[1].get("then") or {}).get("dispatch_now") and not s.get("critical"):
            return False                     # con la ayuda ya en camino solo quedan las preguntas críticas
        return True

    def value_of(self, th: Thread, s: dict[str, Any]) -> tuple[int, str]:
        """Valor de la información de un slot abierto, y el motivo. Se pregunta lo que más puede cambiar la decisión:
        ¿qué pasaría con la primera señal que manda si este slot tomara cada uno de sus valores posibles?"""
        sid = s["id"]
        if s.get("type") == "zone_point" and sid == self._loc_slot(th.proto):
            return (95, "landmark") if th.has(sid) else (100, "where")
        answers = self._answers(th)
        now = self._first_flag(th, answers)
        now_then = (now[1].get("then") or {}) if now else {}
        life = decide = 0
        values: list[Any] = [True, False] if s.get("type") == "bool" else \
            [o.get("id") if isinstance(o, dict) else o for o in s.get("options") or []] if s.get("type") == "enum" else []
        for f in th.proto.get("red_flags") or []:
            cond = f.get("if") or {}
            if sid in cond and s.get("type") not in ("bool", "enum"):
                values = values + [v for v in ([cond[sid]] if not isinstance(cond[sid], (list, dict)) else [])]
                if isinstance(cond[sid], dict):
                    values = values + [n for n in cond[sid].values() if isinstance(n, (int, float))]
        for v in values:
            hit = self._first_flag(th, {**answers, sid: v})
            then = (hit[1].get("then") or {}) if hit else {}
            if hit is None or (now is not None and hit[0] == now[0]):
                continue
            changes = (then.get("instruction") != now_then.get("instruction")
                       or int(then.get("severity_min") or 0) > th.severity_min
                       or any(int(n) > th.needs.get(k, 0) for k, n in (then.get("needs") or {}).items())
                       or (bool(then.get("life_risk")) and not th.life_risk))
            if not changes:
                continue
            if then.get("life_risk"):
                life += 1
            else:
                decide += 1
        if life:
            return 90 + 2 * life, "life_risk"
        if not th.dispatched and sid in (th.proto.get("dispatch_as_soon_as") or []):
            return 85, "dispatch"
        if decide:
            return 60 + decide, "resource"
        if s.get("critical"):
            return 50, "critical"
        return 0, "none"

    def _next_question(self) -> tuple[Thread, dict[str, Any], str] | None:
        if self.questions_asked >= self.limits["max_questions"]:
            return None
        order = ([self.active] if self.active else []) + [t for t in self.threads if t is not self.active]
        order.sort(key=lambda t: (not t.life_risk,))          # estable: primero el hilo con riesgo vital
        for th in order:
            if th.closed or th.prank or sum(th.dunno.values()) >= 3:      # quien avisa no lo ve: no se le sigue preguntando
                continue
            best = None
            for i, s in enumerate(th.proto.get("slots", [])):
                if not self._askable(th, s):
                    continue
                score, reason = self.value_of(th, s)
                if score > 0 and (best is None or score > best[0]):
                    best = (score, i, s, reason)
            if best:
                return th, best[2], best[3]
        return None

    # ------------------------------------------------------------------ avisos para Mando
    def _type_phrase(self, th: Thread) -> str:
        # Primero el tipo que el parser de Mando YA leyó en el primer aviso (así la actualización cae en el mismo
        # incidente); si no reconoció ninguno, la pista del protocolo o de la señal que manda.
        hint = th.flag_hint or th.proto.get("mando_type_hint")
        hint = hint[0] if isinstance(hint, list) and hint else hint
        type_ = th.parser_type if th.parser_type and not th.parser_type.startswith("unknown") else hint
        if not type_:
            return ""
        if type_ == hint and type_ != th.parser_type and type_ in _HINT_ONLY:
            return _HINT_ONLY[type_]
        if type_ in TYPE_PHRASE:
            return TYPE_PHRASE[type_]
        from ..mando.lexicon import TYPES
        spec = TYPES.get(str(type_))
        return next((p for p in (spec.patterns if spec else ()) if re.fullmatch(r"[a-z ]+", p)), "")

    def _facts(self, th: Thread, only: list[str] | None = None) -> list[str]:
        out = []
        for s in th.proto.get("slots", []):
            sid = s["id"]
            if s.get("type") == "zone_point" or not th.has(sid) or (only is not None and sid not in only):
                continue
            f = nlu.fact(nlu.concept_for(sid, s.get("type", "text")), sid, th.val(sid))
            if f:
                out.append(f)
        return out

    def _where(self, th: Thread) -> tuple[str | None, str]:
        loc = th.val(self._loc_slot(th.proto) or "") or {}
        zone, point = loc.get("zone"), loc.get("point")
        txt = (f" Zona {zone}." if zone else " Zona sin confirmar.") + (f" Punto: {point}." if point and not th.reserved else "")
        return zone, txt

    def _emit(self, th: Thread, changed: list[str], reports: list[Report], metas: list[dict[str, Any]],
              note: str = "", force: bool = False) -> None:
        first = not th.dispatched
        loc_slot = self._loc_slot(th.proto)
        news = [sid for sid in th.slots if th.sent.get(sid) != th.val(sid)]
        unsure = ""
        if th.assumed and th.sent.get("_assumed") != th.assumed:
            unsure = f" Sin confirmar por quien avisa ({', '.join(th.assumed)}): se actúa como en el peor caso."
            news = news or ["_assumed"]
        if first:
            dsa = th.proto.get("dispatch_as_soon_as") or []
            ready = th.life_risk or th.dispatch_now or th.reserved or th.prank or (bool(dsa) and all(th.has(s) for s in dsa)) \
                or (not dsa and loc_slot is not None and th.has(loc_slot))
            if not (ready or force):
                return
        elif not news and not note:
            return
        zone, where = self._where(th)
        partial = self._open_decisive(th)
        tag = ("[RESERVADO] " if th.reserved else "") + ("[POSIBLE BROMA] " if th.prank else "") + ("[PARCIAL] " if partial else "")
        # Solo si el parser de Mando NO ve ya el riesgo vital en el texto (calor con confusión, p. ej.). Si lo ve, el
        # añadido inflaría la gravedad del primer aviso y Mando no subiría de tipo al llegar «no respira».
        urgent = " URGENTE, muy grave." if th.life_risk and th.severity_min >= 9 and not th.parser_life else ""
        if first:
            rid = th.id
            facts = self._facts(th)
            if th.reserved:
                body = f"Aviso reservado {rid}: {self._type_phrase(th) or 'caso sensible'}"
            else:
                quote = re.sub(r"\s+", " ", " ".join(th.texts)).strip()[:280]
                phrase = self._type_phrase(th) if th.parser_type.startswith("unknown") or not th.parser_type else ""
                body = f"Aviso {rid}: «{quote}»" + (f". Tipo: {phrase}" if phrase else "")
            text = f"{tag}{body}." + (f" Datos: {'; '.join(facts)}." if facts else "") + where + unsure + urgent
            if th.prank:
                text += " Parece una broma de quien avisa: sin confirmar."
            tags = [str(x) for x in self.profile.get("tags") or []]
            if tags and not th.reserved:
                text += " Etiquetas de asistencia: " + ", ".join(tags) + "."
        else:
            rid = f"{th.id}.u{th.n_reports}"
            facts = self._facts(th, news)
            phrase = self._type_phrase(th)
            if not phrase and th.texts and not th.reserved:      # sin tipo reconocible: la cita original es lo que Mando casa
                phrase = "«" + re.sub(r"\s+", " ", th.texts[0]).strip()[:160] + "»"
            bits = [b for b in ([phrase] if phrase and not note.startswith("!") else []) + facts if b]
            text = f"{tag}ACTUALIZACIÓN del aviso {th.id}: " + (note.lstrip("!") + " " if note else "") + "; ".join(bits)
            text = text.rstrip(" ;:") + "." + (where if not note.startswith("!") else "") + unsure + urgent
        th.n_reports += 1
        th.dispatched = True
        for sid in th.slots:
            th.sent[sid] = th.val(sid)
        th.sent["_assumed"] = list(th.assumed)
        reports.append(Report(id=rid, t=self.t, channel=self.channel, text=text, source=self._source(),
                              lang=self.lang or "es", zone_hint=zone))
        metas.append({"report_id": rid, "root": th.id, "update": not first, "partial": partial, "reserved": th.reserved,
                      "protocol": th.proto["id"], "family": th.proto.get("family"), "life_risk": th.life_risk,
                      "severity_min": th.severity_min, "needs": dict(th.needs), "zone": zone,
                      "slots": {k: v.value for k, v in th.slots.items()}, "changed": news if not first else sorted(th.slots),
                      "assumed": list(th.assumed), "possible_prank": th.prank,
                      "handoff": th.proto.get("handoff"), "real_channel": self.real_channel,
                      "verbatim": list(th.texts) if th.reserved else None})

    def _open_decisive(self, th: Thread) -> bool:
        return any(self._askable(th, s) and self.value_of(th, s)[0] > 0 for s in th.proto.get("slots", []))

    # ------------------------------------------------------------------ el turno
    def opening(self) -> Turn:
        self.lang = self.lang or "es"
        return self._turn(_loc(self.glob.get("opening"), self.lang) or self._tr("tell_me"), None, [], [], "", [], [])

    def receive(self, text: str, t: int | None = None) -> Turn:
        self.turn_no += 1
        if t is not None:
            self.t = t
        self._was_pending = self.pending      # a qué estaba contestando la persona en este turno
        raw = (text or "").strip()
        self.transcript.append({"who": "person", "text": raw})
        flags: list[str] = []
        reports: list[Report] = []
        metas: list[dict[str, Any]] = []
        answers: list[dict[str, Any]] = []
        low, norm = nlu.prep(raw)
        if not norm:
            self.lang = self.lang or "es"
            return self._finish(self._tr("empty"), None, reports, metas, answers, flags + ["empty"], recount=False)
        new_lang = nlu.detect_lang(norm, self.lang)
        if self.lang is not None and new_lang != self.lang:
            flags.append("lang_switch")
        self.lang = new_lang
        self.done = False

        head: list[str] = []
        order, role = bool(nlu.ORDER.search(norm)), bool(nlu.ROLE.search(norm))
        if role:
            head.append(self._tr("role"))
            flags.append("role_refused")
        elif order:
            head.append(self._tr("order"))
            flags.append("order_refused")
        asking = "?" in raw
        diag = asking and bool(nlu.DIAGNOSIS_Q.search(norm))
        eta = asking and bool(nlu.ETA_Q.search(norm))
        if diag:
            head.append(self._tr("no_diagnosis"))
            flags.append("no_diagnosis")
        if eta:
            head.append(self._tr("no_eta"))
            flags.append("no_eta")
        aside = role or diag or eta          # nada de esto abre ni cambia un aviso
        if nlu.is_distressed(raw, norm) and self.contained < 1 and not (order or aside):
            self.contained += 1
            head.append(self._tr("contain"))
            flags.append("contained")

        # respuesta a una pregunta de Mando: sale tal cual hacia control, además de lo que se entienda de ella
        mq, self._mando_q = self._mando_q, None
        if mq is not None:
            zones = self._parser.find_zones(norm, self.zones)
            answers.append({"ask_id": mq.get("ask_id"), "question": mq["question"], "text": raw,
                            "zone": zones[0] if zones else None, "thread": mq.get("thread")})

        parsed = self._parse(raw)
        # desmentido («era broma», «falsa alarma»)
        if nlu.ALL_CLEAR.search(norm) and self.threads:
            for th in [x for x in self.threads if not x.closed]:
                if th.dispatched:
                    self._emit(th, [], reports, metas, note="!quien avisó dice que ya está bien, falsa alarma: «" + raw[:120] + "»")
                th.closed = True
            self.pending = None
            flags.append("all_clear")
            return self._finish(" ".join(head + [self._tr("all_clear")]), None, reports, metas, answers, flags, close=True)

        touched = self._route(raw, low, norm, parsed, flags, aside, order)
        if not touched and mq is not None:
            th = next((x for x in self.threads if x.id == mq.get("thread")), self.active)
            touched = [(th, [])] if th is not None else []
        if not touched:
            self.off_topic += 1
            close = bool(nlu.LEAVING.search(norm)) or (not self.threads and self.off_topic >= self.limits["off_topic_turns"])
            if not (aside or order):
                flags.append("off_topic")
                if nlu.CHITCHAT.search(norm) or nlu.LAUGH.search(norm) or close:
                    head.append(self._tr("off_topic"))
            if not any(not x.closed for x in self.threads) and not close:
                head.append(self._tr("tell_me"))
            return self._finish(" ".join(head), None, reports, metas, answers, flags, close=close, recount=False)

        candidates = [ins for ins in (self._evaluate(th) for th in self.threads if not th.closed) if ins]
        instruction = max(candidates, key=lambda i: (i["life_risk"], i["severity"]), default=None)
        if instruction is not None:          # una por turno; la de otro hilo sale en el turno siguiente
            self._give(next(t for t in self.threads if t.id == instruction["thread"]), instruction)
        for th, changed in touched:
            note = ""
            if mq is not None and th.id == (mq.get("thread") or th.id):
                note = f"respuesta a la pregunta de control «{mq['question'][:80]}»: «{raw[:160]}»."
                mq = None
            self._emit(th, changed, reports, metas, note=note)
        if touched and all(th.prank for th, _ in touched):      # broma: reenviada y fuera; la conversación no cambia
            for th, _ in touched:
                th.closed = True
            self.off_topic += 1
            head.append(self._tr("off_topic"))
            if not any(not x.closed for x in self.threads):
                head.append(self._tr("tell_me"))
            return self._finish(" ".join(head), None, reports, metas, answers, flags, recount=False)

        ackd = self._ack(touched, reports)
        leaving = bool(nlu.LEAVING.search(norm))
        return self._finish(" ".join(h for h in head + ackd if h), instruction, reports, metas, answers, flags, close=leaving)

    def _route(self, raw: str, low: str, norm: str, parsed: dict[str, Any], flags: list[str],
               blocked: bool, order: bool) -> list[tuple[Thread, list[str]]]:
        """Decide a qué hilo(s) pertenece el mensaje, abre los que hagan falta y extrae los slots."""
        touched: list[tuple[Thread, list[str]]] = []
        if blocked:
            return touched
        groups = self._segments(low)
        specific = [g for g in groups if g["proto"] is not None]
        active = self.active if self.active and not self.active.closed else None

        if active is None:
            if not specific:
                content = (not str(parsed.get("type", "unknown")).startswith("unknown") or parsed.get("zone")
                           or parsed.get("life_threat") or str(parsed.get("family")) != "info" or len(norm.split()) >= 5)
                known = not str(parsed.get("type", "unknown")).startswith("unknown")
                if not content or (order and not known) or nlu.CHITCHAT.search(norm):
                    return []
                weak_proto = self._best(norm, parsed)[0]       # solo disparadores débiles («los baños…»), o nada
                specific = [{"proto": weak_proto or self._generic, "text": low, "zones": [], "connector": False}]
                if nlu.LAUGH.search(norm) and not known:
                    # Parece una broma: no se conversa sobre ella, pero NUNCA se descarta. Sale hacia Mando marcada
                    # como tal; filtrar es cosa de Mando y de las personas.
                    th = self._new_thread(self._generic)
                    th.prank = True
                    self._absorb(th, low, raw)
                    flags.append("possible_prank")
                    return [(th, [])]
            for g in specific:
                th = self._new_thread(g["proto"])
                self._absorb(th, g["text"] if len(specific) > 1 else low, raw if len(specific) == 1 else g["text"])
                touched.append((th, sorted(th.slots)))
            first_loc = next((t.val(self._loc_slot(t.proto) or "") for t, _ in touched if t.val(self._loc_slot(t.proto) or "")), None)
            for th, _ in touched:           # «pelea en la barra y uno no respira»: es el mismo sitio
                ls = self._loc_slot(th.proto)
                if ls and not th.has(ls) and first_loc:
                    th.slots[ls] = SlotValue(dict(first_loc), 0.6, "inherited", self.turn_no)
            self.active = max((t for t, _ in touched), key=lambda t: (t.life_risk or t.parser_life, -self.threads.index(t)))
            if len(touched) > 1:
                flags.append("two_incidents")
            return touched

        # conversación en marcha: primero, lo que responde al hilo activo
        before = dict(active.slots)
        pend = self.pending[1] if self.pending and self.pending[0] == active.id else None
        changed = self._absorb(active, low, raw)
        answered = pend is not None and (active.has(pend) and before.get(pend) is not active.slots.get(pend))
        # ¿trae además otro incidente? Solo si es de otra familia y hay una señal clara de que es otra cosa
        for g in specific:
            p = g["proto"]
            if p["id"] == active.proto["id"] or any(t.proto["id"] == p["id"] and not t.closed for t in self.threads):
                continue
            if active.proto is self._generic:      # el aviso vago se concreta: mismo hilo, mismo id de aviso
                self._convert(active, p)
                changed = sorted(active.slots)
                continue
            if p.get("family") == active.proto.get("family") or answered:
                continue
            zone_a = (active.val(self._loc_slot(active.proto) or "") or {}).get("zone")
            other_zone = any(z != zone_a for z in g["zones"]) if zone_a else False
            vital = bool(parsed.get("life_threat")) and p.get("family") == "medical" and not active.life_risk
            if g["connector"] or other_zone or nlu.CONNECTOR.search(norm) or vital:
                th = self._new_thread(p)
                self._absorb(th, g["text"], g["text"])
                ls, la = self._loc_slot(p), active.val(self._loc_slot(active.proto) or "")
                if ls and not th.has(ls) and la and not other_zone:
                    th.slots[ls] = SlotValue(dict(la), 0.6, "inherited", self.turn_no)
                touched.append((th, sorted(th.slots)))
                flags.append("two_incidents")
        if changed or answered or not touched:
            touched.insert(0, (active, changed))
        if not changed and not answered and len(touched) == 1 and touched[0][0] is active \
                and (nlu.CHITCHAT.search(norm) or nlu.LAUGH.search(norm) or nlu.ORDER.search(norm) or nlu.ROLE.search(norm)):
            return []
        return touched

    def _absorb(self, th: Thread, low: str, raw: str) -> list[str]:
        _, norm = nlu.prep(low)
        short = len(norm.split()) <= 6
        if not th.texts or not (short and (nlu.DUNNO.search(norm) or nlu.bare_yes_no(low) is not None)):
            th.texts.append(raw.strip())      # «sí», «no lo sé»: no son parte del relato que se cita a Mando
        p = self._parse(low)
        th.parser_life = th.parser_life or bool(p.get("life_threat")) and not p.get("all_clear")
        # sensible aunque el protocolo no lo marque: violencia sexual, menores. (Un arma no cambia el tono de la
        # conversación: Mando ya reserva ese incidente por su cuenta.)
        th.reserved = th.reserved or str(p.get("type")) in ("sexual_assault", "lost_child") \
            or (bool(p.get("minors")) and str(p.get("family")) == "aggression")
        if not th.parser_type or th.parser_type.startswith("unknown"):
            th.parser_type = str(p.get("type") or "")
        changed = self._extract(th, low, norm)
        changed += [c for c in self._hook(th, raw) if c not in changed]
        return changed

    def _convert(self, th: Thread, proto: dict[str, Any]) -> None:
        """El aviso genérico resulta ser de un protocolo concreto: se conserva el hilo y se relee lo dicho."""
        loc_old, loc_new = self._loc_slot(th.proto), self._loc_slot(proto)
        keep = th.slots.get(loc_old) if loc_old else None
        th.proto, th.slots, th.gave_up, th.dunno, th.asks = proto, {}, {}, {}, {}
        th.reserved = th.reserved or bool(proto.get("sensitive"))
        if keep is not None and loc_new:
            th.slots[loc_new] = keep
        pending, self.pending = self.pending, None
        for txt in th.texts:
            low, norm = nlu.prep(txt)
            self._extract(th, low, norm)
        self.pending = None if pending and pending[0] == th.id else pending

    def _ack(self, touched: list[tuple[Thread, list[str]]], reports: list[Report]) -> list[str]:
        out: list[str] = []
        lang = self.lang or "es"
        first = any(not r.id.count(".u") for r in reports)
        th0 = touched[0][0] if touched else None
        if th0 is not None and th0.reserved:
            rh = self.glob.get("reserved_handling") or {}
            if th0.n_reports <= 1 and first:
                out.append(_loc(rh.get("ack") or ({k: rh[k] for k in ("es", "en") if k in rh} or None), lang) or self._tr("reserved_ack"))
                out.append(self._tr("sent_reserved"))
                ext = (th0.proto.get("handoff") or {}).get("external") or {}
                if (th0.proto.get("handoff") or {}).get("police") or (isinstance(ext, dict) and ext.get("requires_consent")):
                    out.append(_loc(rh.get("police"), lang) or self._tr("police"))
            else:
                out.append(self._tr("ack"))
            return out
        facts = []
        for th, changed in touched:
            for sid in changed:
                s = self._slot_def(th, sid)
                if s.get("type") == "zone_point":
                    loc = th.val(sid) or {}
                    if loc.get("point"):
                        facts.append(loc["point"])
                    elif loc.get("zone") and th.slots[sid].source != "channel":
                        facts.append(self.zones[loc["zone"]].name.split(" (")[0].lower())
                else:
                    a = nlu.ack(nlu.concept_for(sid, s.get("type", "text")), th.val(sid), lang)
                    if a:
                        facts.append(a)
        facts = list(dict.fromkeys(facts))
        facts = [f for f in facts if not any(f != g and f in g for g in facts)][:3]
        noted = any(changed for _, changed in touched)
        out.append(self._tr("ack_facts", facts=", ".join(facts)) if facts else
                   self._tr("ack_first" if self.turn_no == 1 else "ack" if noted else "ok"))
        if first:
            out.append(self._tr("sent"))
        return out

    def _finish(self, head: str, instruction: dict[str, Any] | None, reports: list[Report], metas: list[dict[str, Any]],
                answers: list[dict[str, Any]], flags: list[str], close: bool = False, recount: bool = True) -> Turn:
        """Añade la pregunta (como mucho UNA), decide si la conversación ha terminado y monta el turno."""
        question, why, ask = "", "", None
        nxt = None if close else self._next_question()
        if nxt is None and not close and not any(not t.closed for t in self.threads):
            # todavía no hay ningún aviso abierto (saludo, broma, orden): ni pregunta de protocolo ni cierre
            return self._turn(head, instruction, reports, metas, "", answers, flags)
        if nxt is not None:
            th, s, reason = nxt
            sid = s["id"]
            repeat = self.pending == (th.id, sid) and not recount      # vuelve a SU pregunta tras una orden o una broma
            if s.get("type") == "zone_point" and th.has(sid):
                lq = self.glob.get("location_questions") or []
                q = _loc(lq[1], self.lang or "es") if len(lq) > 1 and isinstance(lq[1], (dict, str)) else ""
                question, why = q or self._tr("landmark"), self._tr("why_landmark")
                th.landmark_asked = True
            else:
                question = _loc(s.get("question"), self.lang or "es")
                why = _loc(s.get("why"), self.lang or "es") or (self._tr("why_location") if s.get("type") == "zone_point" else "")
                if self._was_pending == (th.id, sid) and not th.dunno.get(sid) and not repeat:   # contestó y no se entendió
                    head = (head + " " if head else "") + self._tr("again") if self._tr("again") not in head else head
                    question += self._tr("yes_no") if s.get("type") == "bool" else ""
                if th.dunno.get(sid) and not repeat:
                    if s.get("type") == "zone_point":
                        question, why = self._tr("landmark"), self._tr("why_landmark")
                    else:
                        question = self._tr("retry") + question[:1].lower() + question[1:] if not question.startswith("¿") \
                            else self._tr("retry") + question
            if th is not self.active and len([t for t in self.threads if not t.closed]) > 1:
                question = self._tr("other", label=_loc(th.proto.get("label"), self.lang or "es").lower()) + question \
                    if not th.reserved else question
            if not repeat:
                th.asks[sid] = th.asks.get(sid, 0) + 1
                self.questions_asked += 1
            self.active = th
            self.pending = (th.id, sid)
            ask = {"thread": th.id, "slot": sid, "type": s.get("type", "text"), "options": s.get("options"), "reason": reason}
        else:
            if self.pending:
                th = next((t for t in self.threads if t.id == self.pending[0]), None)
                if th is not None and not th.has(self.pending[1]) and self.pending[1] not in th.gave_up:
                    th.gave_up[self.pending[1]] = "unanswered"
            self.pending = None
            for th in self.threads:          # al cerrar, nada se queda sin salir hacia Mando
                if th.closed:
                    continue
                ins = self._evaluate(th)     # lo que quedó sin contestar puede obligar a asumir lo peor
                if ins is not None and instruction is None:
                    instruction = ins
                    self._give(th, ins)
                if th.slots or th.texts:
                    self._emit(th, [], reports, metas, force=True)
            self.done = True
            head = (head + " " if head else "") + (
                self._tr("close_empty") if not self.threads else
                self._tr("close_voice" if self.channel == Channel.VOICE else "close"))
        return self._turn(head, instruction, reports, metas, why, answers, flags, ask, question)

    def _turn(self, head: str, instruction: dict[str, Any] | None, reports: list[Report], metas: list[dict[str, Any]],
              why: str, answers: list[dict[str, Any]], flags: list[str], ask: dict[str, Any] | None = None,
              question: str = "") -> Turn:
        head = self._guard(re.sub(r"\s+", " ", head).strip())
        say = f"{head} {question}".strip()
        self.transcript.append({"who": "agent", "text": say})
        if instruction is not None:
            instruction = {k: v for k, v in instruction.items() if k not in ("severity", "life_risk")}
        return Turn(say=say, instruction=instruction, reports=reports, state=self.state(), why_next=why, done=self.done,
                    lang=self.lang or "es", ask=ask, report_meta=metas, answers=answers, flags=flags, question=question)

    def _guard(self, say: str) -> str:
        """Última barrera: ninguna frase de `never_say` sale, venga de donde venga."""
        if not self._never:
            return say
        keep = [s for s in re.split(r"(?<=[.!?])\s+", say) if not any(n.search(normalize(s)) for n in self._never)]
        return " ".join(keep)

    # ------------------------------------------------------------------ lo que viene de Mando
    def mando_asks(self, question: str | dict[str, str], ask_id: str | None = None, purpose: str | None = None,
                   thread: str | None = None) -> Turn:
        """Una pregunta de Mando (ASK) entra por la misma conversación. La respuesta vuelve en `Turn.answers` del turno
        siguiente y como ACTUALIZACIÓN del aviso. No cuenta para el máximo de preguntas: no es del agente."""
        self.lang = self.lang or "es"
        q = _loc(question, self.lang).strip()
        q = q if q.endswith("?") else q.rstrip(".") + "?"
        th = next((t for t in self.threads if t.id == thread), self.active)
        self._mando_q = {"ask_id": ask_id or f"ASK-{self.session_id}-{self._mando_n + 1}", "question": q,
                         "thread": th.id if th else None, "purpose": purpose}
        self._mando_n += 1
        loc = self._loc_slot(th.proto) if th else None
        self.pending = None                  # la pregunta propia que estaba en el aire se aparca: ahora se contesta a Mando
        if th and loc and purpose in ("zone", "point", "location"):
            self.pending, self.active = (th.id, loc), th
        self.done = False
        q = re.sub(r"\?(?=.*\?)", ".", q)       # como mucho una pregunta por turno, también si la redacta Mando
        return self._turn("", None, [], [], self._tr("why_mando"), [], ["mando_ask"],
                          {"thread": th.id if th else None, "slot": None, "type": "text", "options": None, "reason": "mando"}, q)

    def notify(self, status: str | dict[str, Any], **data: Any) -> Turn:
        """Estado de Mando → frase llana. El tiempo, si viene, es el que calcula Mando y se dice como estimación."""
        self.lang = self.lang or "es"
        info = dict(status) if isinstance(status, dict) else {"status": status}
        info.update(data)
        key = str(info.get("status") or "received")
        th = next((t for t in self.threads if t.id == info.get("thread")), self.active)
        tpl = _STATUS.get(key, _STATUS["received"])[self.lang]
        kind = None if (th and th.reserved) else info.get("kind")
        team = _TEAM.get(kind, _TEAM[None])[0 if self.lang == "es" else 1]
        if th and th.reserved and key in ("dispatched", "en_route"):
            team = "una persona responsable" if self.lang == "es" else "A responsible person"
        eta = info.get("eta", info.get("eta_min"))
        eta_txt = ""
        if isinstance(eta, (int, float)) and eta > 0:
            eta_txt = f". Tiempo estimado: unos {int(round(eta))} minutos" if self.lang == "es" else f". Estimated time: about {int(round(eta))} minutes"
        say = tpl.format(team=team, eta=eta_txt)
        return self._turn(say, None, [], [], "", [], [f"status:{key}"])

    def silence(self, seconds: float) -> Turn | None:
        """Nadie contesta. Pasado el umbral, cierra con lo que tiene (y lo que no había salido, sale)."""
        if self.done or seconds < self.limits["silence_s"]:
            return None
        self.lang = self.lang or "es"
        reports: list[Report] = []
        metas: list[dict[str, Any]] = []
        if self.pending:
            th = next((t for t in self.threads if t.id == self.pending[0]), None)
            if th is not None:
                th.gave_up[self.pending[1]] = "unanswered"
        self.pending, self._mando_q = None, None
        for th in self.threads:
            if not th.closed and (th.slots or th.texts):
                self._emit(th, [], reports, metas, force=True,
                           note="" if not th.dispatched else "quien avisó ha dejado de escribir; la recogida se cierra con lo que hay.")
        self.done = True
        return self._turn(self._tr("silence") if self.threads else self._tr("close_empty"), None, reports, metas, "", [], ["silence"])

    # ------------------------------------------------------------------ estado para la pantalla
    def state(self) -> dict[str, Any]:
        threads = []
        for th in self.threads:
            slots = {}
            for s in th.proto.get("slots", []):
                sid = s["id"]
                base = {"type": s.get("type", "text"), "critical": bool(s.get("critical")),
                        "label": _loc(s.get("question"), self.lang or "es")}
                if th.has(sid):
                    slots[sid] = {**base, **th.slots[sid].to_dict(), "status": "known"}
                else:
                    slots[sid] = {**base, "value": None, "confidence": 0.0, "source": None, "turn": None,
                                  "status": th.gave_up.get(sid, "open")}
            threads.append({"id": th.id, "protocol": th.proto["id"], "label": _loc(th.proto.get("label"), self.lang or "es"),
                            "family": th.proto.get("family"), "reserved": th.reserved, "life_risk": th.life_risk,
                            "severity_min": th.severity_min, "needs": dict(th.needs), "dispatched": th.dispatched,
                            "reports": th.n_reports, "instructions_given": list(th.given), "closed": th.closed,
                            "assumed": list(th.assumed),
                            "slots": slots})
        act = next((t for t in threads if self.active and t["id"] == self.active.id), None)
        return {"session": self.session_id, "lang": self.lang, "channel": self.real_channel, "turn": self.turn_no,
                "questions_asked": self.questions_asked, "max_questions": self.limits["max_questions"],
                "active": act["id"] if act else None, "slots": act["slots"] if act else {}, "threads": threads,
                "pending": {"thread": self.pending[0], "slot": self.pending[1]} if self.pending else None,
                "done": self.done, "protocols_file": Path(str(self.data.get("_path", "inline"))).name}
