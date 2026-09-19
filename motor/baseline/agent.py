"""Agente de lista fija: lo que hace hoy un centro de control con un protocolo en papel.

No es un hombre de paja: entiende avisos por palabras clave (es/en), manda al recurso libre más
cercano del tipo adecuado, reintenta con el siguiente si el primero no contesta y pide permiso
para lo que siempre lo exige. Lo que NO hace (y es justo lo que el reto pide): fusionar duplicados,
ordenar por gravedad, escribir supuestos, replanificar cuando el mundo cambia, ni preguntar.
`BaselinePlus` añade dos escalones: fusiona duplicados y atiende primero lo más grave.
`BaselineReroute` añade un desvío fijo ante avisos de saturación, sin comprobar sus consecuencias.
"""
from __future__ import annotations

import json
import unicodedata
from collections import deque
from pathlib import Path
from typing import Any

from motor.contracts import (ALWAYS_APPROVE, Action, ActionKind, ActionStatus, Autonomy, Channel, LogEntry,
                             Observation, Report, ResourceStatus)

_FESTIVAL = Path(__file__).resolve().parent.parent / "world" / "festival.json"


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


# (palabras, zona). Orden = prioridad: lo más específico primero.
ZONE_WORDS: list[tuple[tuple[str, ...], str]] = [
    (("puerta a", "gate a", "acceso a", "acceso norte", "entrada norte"), "gate_a"),
    (("puerta b", "gate b", "acceso b", "acceso principal", "entrada principal", "puerta principal", "main gate", "main entrance"), "gate_b"),
    (("puerta c", "gate c", "acceso c", "acceso sur", "entrada sur", "entrada pequena"), "gate_c"),
    (("pmr", "movilidad reducida", "sillas de ruedas", "wheelchair", "accessible platform"), "pmr"),
    (("puesto medico 1", "medical post 1", "enfermeria sur"), "medical_1"),
    (("puesto medico 2", "medical post 2", "enfermeria norte"), "medical_2"),
    (("agua norte", "water point north", "fuente norte"), "water_n"),
    (("agua sur", "water point south", "fuente sur"), "water_s"),
    (("pasillo norte", "north corridor"), "corridor_n"),
    (("pasillo sur", "south corridor", "ruta de ambulancia"), "corridor_s"),
    (("backstage", "camerinos", "detras del escenario"), "backstage"),
    (("lanzadera", "metro", "shuttle", "salida a", "parada de bus", "transport"), "exit_transport"),
    (("foso", "primera fila", "front pit", "frente de escenario", "frente del escenario", "front of the stage",
      "barrera delantera", "front barrier", "front left", "front right", "delante del escenario"), "front_pit"),
    (("vip",), "vip"),
    (("restauracion", "food truck", "foodtruck", "zona de comida", "food court", "food area", "puesto de comida",
      "barras", "comida"), "food"),
    (("banos", "aseos", "toilets", "wc", "lavabos", "restroom"), "toilets"),
    (("pista general", "pista", "zona general", "general area", "main field", "explanada"), "general"),
]

# (palabras, tipo de recurso). Gana el tipo con más palabras encontradas; a igualdad, el que va antes.
KIND_WORDS: list[tuple[tuple[str, ...], str]] = [
    (("parada cardiaca", "cardiac", "no respira", "not breathing", "infarto", "anafilax", "anaphyla", "alergi",
      "desa"), "ambulance"),
    (("inconsciente", "unconscious", "desmay", "faint", "collapsed", "convuls", "seizure", "sangra", "bleeding",
      "herid", "injur", "caido", "caida", "fractura", "sobredosis", "overdose", "intoxic", "golpe de calor",
      "heat stroke", "mareo", "mareado", "dizzy", "sanitario", "vomit", "tobillo", "acorda", "respira", "un medico", "doctor", "lesion", "corte ", "wake up"), "medical"),
    (("agua", "water", "suministro", "combustible", "fuel", "gasoil", "pulseras", "wristband", "baterias",
      "batteries", "se ha acabado", "sin existencias", "ran out", "reparto", "sin producto", "material bajo",
      "repuesto", "reponer", "bajo minimos"), "logistics"),
    (("luz", "apagon", "power", "electric", "generador", "torno", "turnstile", "cashless", "datafono", "pago",
      "averia", "roto", "rota", "broken", "fuga", "inund", "flood", "estructura", "structure",
      "truss", "foco", "lighting", "iluminacion", "alumbrado", "a oscuras", "red caida", "network", "wifi", "vehiculo",
      "no arranca", "mantenimiento", "repetidor", "sin latido", "lector", "no leen", "no funciona", "tecnico"), "tech"),
    (("pelea", "fight", "agres", "assault", "acoso", "harass", "robo", "theft", "carterista", "arma", "weapon",
      "navaja", "knife", "cuchillo", "sospechos", "suspicious", "dron", "drone", "colarse", "saltando", "saltar",
      "sin entrada", "vallado", "vallas", "rina", "botellas", "atascad", "no avanza", "sigue llegando", "cola", "protesta",
      "desbord", "se va de las manos", "apoyo de seguridad", "refuerzo",
      "aglomer", "aplast", "crush", "empuj", "push", "atrapad", "saturad", "demasiada gente", "too many people",
      "muchisima gente", "avalancha", "stampede", "panico", "panic", "perdido", "perdida", "lost", "nino", "child",
      "humo", "smoke", "fuego", "fire", "incendio", "bomba", "bomb", "amenaza", "threat"), "security"),
]

# Reglas de la lista que proponen algo que SIEMPRE exige aprobación humana.
ESCALATION_WORDS: list[tuple[tuple[str, ...], ActionKind, dict[str, Any]]] = [
    (("incendio", "fuego", "fire", "llamas", "flames"), ActionKind.REQUEST_EXTERNAL, {"kind": "fire"}),
    (("arma", "weapon", "navaja", "knife", "bomba", "bomb", "amenaza de", "paquete sospechoso"),
     ActionKind.REQUEST_EXTERNAL, {"kind": "police"}),
    (("parada cardiaca", "cardiac arrest", "no respira", "not breathing"), ActionKind.REQUEST_EXTERNAL,
     {"kind": "ambulance"}),
]


def _zone_distances() -> dict[str, dict[str, float]]:
    """Minutos entre zonas en vacío (Floyd-Warshall sobre festival.json). El agente de lista fija no
    mira la densidad: «el más cercano» es el del plano."""
    fest = json.loads(_FESTIVAL.read_text(encoding="utf-8"))
    ids = [z["id"] for z in fest["zones"]]
    d = {a: {b: (0.0 if a == b else 1e9) for b in ids} for a in ids}
    for e in fest["edges"]:
        a, b = (e.get("a") or e.get("from")), (e.get("b") or e.get("to"))
        if a in d and b in d:
            m = float(e.get("minutes", 1))
            d[a][b] = d[b][a] = min(d[a][b], m)
    for k in ids:
        for i in ids:
            dik = d[i][k]
            for j in ids:
                if dik + d[k][j] < d[i][j]:
                    d[i][j] = dik + d[k][j]
    return d


_DIST: dict[str, dict[str, float]] | None = None


def distances() -> dict[str, dict[str, float]]:
    global _DIST
    if _DIST is None:
        _DIST = _zone_distances()
    return _DIST


class KeywordParser:
    """Parser por palabras clave. Devuelve zona (o None), tipo de recurso y una gravedad tosca."""

    SEVERE = ("no respira", "not breathing", "inconsciente", "unconscious", "parada", "cardiac", "arma", "weapon",
              "aplast", "crush", "fuego", "fire", "incendio", "convuls", "anafilax", "sobredosis", "overdose",
              "atrapad", "avalancha", "sangra")

    def parse(self, rep: Report) -> dict[str, Any]:
        text = _norm(rep.text)
        zone = rep.zone_hint
        if zone is None:
            for words, zid in ZONE_WORDS:
                if any(w in text for w in words):
                    zone = zid
                    break
        kind, best = None, 0
        for words, k in KIND_WORDS:
            hits = sum(1 for w in words if w in text)
            if hits > best:
                kind, best = k, hits
        if rep.channel == Channel.SENSOR and kind is None:
            kind = "security"
        severity = 8 if any(w in text for w in self.SEVERE) else 5
        escalation = None
        for words, akind, params in ESCALATION_WORDS:
            if any(w in text for w in words):
                escalation = (akind, dict(params))
                break
        return {"zone": zone, "kind": kind or "security", "severity": severity, "escalation": escalation}


class Baseline:
    """Lista fija: un aviso → un despacho, por orden de llegada."""

    name = "baseline"
    merge_duplicates = False
    by_severity = False
    max_retries = 2          # «si no contesta, llama al siguiente»: dos intentos más y se acabó
    merge_window_min = 15

    def __init__(self, playbook: Any = None, comms: Any = None, parser: Any = None) -> None:
        self.comms = comms                      # no lo usa: el resultado le llega por `action_results`
        self.parser = parser or KeywordParser()
        self.queue: deque[dict[str, Any]] = deque()
        self.actions: dict[str, Action] = {}
        self.tickets: dict[str, dict[str, Any]] = {}     # un «incidente» por aviso (o por grupo en Plus)
        self.log: list[LogEntry] = []
        self.approved: deque[str] = deque()
        self._n = 0
        self._by_action: dict[str, dict[str, Any]] = {}
        self._escalated: set[tuple[str, str | None]] = set()

    # ---------------------------------------------------------------- utilidades
    def _aid(self) -> str:
        self._n += 1
        return f"b{self._n}"

    def _say(self, t: int, kind: str, text: str, ref: str | None = None, **data: Any) -> None:
        self.log.append(LogEntry(t, kind, text, ref, data))

    def _nearest(self, obs: Observation, kind: str, zone: str, skip: set[str]) -> str | None:
        dist = distances().get(zone, {})
        best, best_d = None, 1e18
        for r in obs.resources.values():
            if str(r.kind) != kind or r.status != ResourceStatus.AVAILABLE or r.id in skip:
                continue
            d = dist.get(r.zone, 1e9)
            if d < best_d or (d == best_d and best is not None and r.id < best):
                best, best_d = r.id, d
        return best

    # ---------------------------------------------------------------- ciclo
    def _intake(self, obs: Observation, out: list[Action]) -> None:
        for rep in obs.new_reports:
            p = self.parser.parse(rep)
            self._say(obs.t, "report", f"{rep.channel}: {rep.text[:90]}", rep.id, parsed={k: p[k] for k in ("zone", "kind")})
            if self.merge_duplicates and p["zone"]:
                dup = next((tk for tk in self.tickets.values()
                            if tk["zone"] == p["zone"] and tk["kind"] == p["kind"] and not tk["closed"]
                            and obs.t - tk["t"] <= self.merge_window_min), None)
                if dup is not None:
                    dup["reports"].append(rep.id)
                    dup["severity"] = max(dup["severity"], p["severity"])
                    a = Action(self._aid(), ActionKind.MERGE, obs.t, incident=dup["id"], zone=p["zone"],
                               params={"reports": list(dup["reports"])}, why="mismo sitio y mismo tipo en 15 min")
                    self.actions[a.id] = a
                    out.append(a)
                    continue
            tk = {"id": f"bt{len(self.tickets) + 1}", "t": obs.t, "zone": p["zone"], "kind": p["kind"],
                  "severity": p["severity"], "reports": [rep.id], "tries": 0, "skip": set(), "closed": False,
                  "dispatched": None}
            self.tickets[tk["id"]] = tk
            if p["zone"] is None:
                tk["closed"] = True
                self._say(obs.t, "incident", "aviso sin zona reconocible: la lista no sabe a dónde mandar", tk["id"])
            else:
                self.queue.append(tk)
            esc = p["escalation"]
            if esc and (str(esc[0]), p["zone"]) not in self._escalated:
                self._escalated.add((str(esc[0]), p["zone"]))
                a = Action(self._aid(), esc[0], obs.t, incident=tk["id"], zone=p["zone"],
                           params={**esc[1], "reports": [rep.id]}, autonomy=Autonomy.APPROVE,
                           status=ActionStatus.AWAITING_APPROVAL, why="lo dice el protocolo; requiere aprobación")
                self.actions[a.id] = a
                out.append(a)
                self._say(obs.t, "approval", f"pide aprobación para {a.kind}", a.id)

    def _results(self, obs: Observation) -> None:
        for res in obs.action_results:
            tk = self._by_action.get(res.id)
            if tk is None or res.kind != ActionKind.DISPATCH:
                continue
            immediate = res.params.get("error") in ("no_answer", "rejected", "resource_offline", "resource_busy",
                                                    "comms_down", "route_blocked")
            if res.status in (ActionStatus.FAILED, ActionStatus.REJECTED) and immediate and tk["dispatched"] == res.id:
                tk["dispatched"] = None
                tk["skip"].add(res.resource)
                if tk["tries"] <= self.max_retries:
                    self.queue.appendleft(tk)   # «si no contesta, llama al siguiente»
                    self._say(obs.t, "outcome", f"{res.resource}: {res.params.get('error')}; se llama al siguiente", res.id)
                else:
                    tk["closed"] = True
                    self._say(obs.t, "outcome", "tres intentos sin éxito: el aviso se queda sin atender", res.id)
            elif res.status == ActionStatus.DONE:
                tk["closed"] = True

    def _dispatch(self, obs: Observation, out: list[Action]) -> None:
        pending = list(self.queue)
        if self.by_severity:
            pending.sort(key=lambda tk: (-tk["severity"], tk["t"]))
        taken: set[str] = set()
        for tk in pending:
            rid = self._nearest(obs, tk["kind"], tk["zone"], tk["skip"] | taken)
            if rid is None:
                continue                         # nadie libre de ese tipo: espera su turno
            taken.add(rid)
            self.queue.remove(tk)
            tk["tries"] += 1
            a = Action(self._aid(), ActionKind.DISPATCH, obs.t, incident=tk["id"], resource=rid, zone=tk["zone"],
                       params={"reports": list(tk["reports"])}, status=ActionStatus.PROPOSED,
                       why=f"{tk['kind']} libre más cercano a {tk['zone']}")
            tk["dispatched"] = a.id
            self.actions[a.id] = a
            self._by_action[a.id] = tk
            out.append(a)
            self._say(obs.t, "action", f"manda {rid} a {tk['zone']}", a.id)

    def tick(self, obs: Observation) -> list[Action]:
        out: list[Action] = []
        while self.approved:
            a = self.actions[self.approved.popleft()]
            a.status = ActionStatus.PROPOSED
            out.append(a)
        self._results(obs)
        self._intake(obs, out)
        self._dispatch(obs, out)
        return out

    def approve(self, action_id: str, ok: bool, note: str = "") -> None:
        a = self.actions.get(action_id)
        if a is None or a.status != ActionStatus.AWAITING_APPROVAL:
            return
        if ok:
            self.approved.append(action_id)
        else:
            a.status = ActionStatus.REJECTED
        self.log.append(LogEntry(a.t, "approval", ("aprobada" if ok else "vetada") + (f": {note}" if note else ""),
                                 action_id))

    def snapshot(self) -> dict[str, Any]:
        incidents = [{"id": tk["id"], "zone": tk["zone"], "severity": tk["severity"], "t_open": tk["t"],
                      "reports": list(tk["reports"]), "needs": {tk["kind"]: 1},
                      "status": "resolved" if tk["closed"] else "open"} for tk in self.tickets.values()]
        return {"agent": self.name, "incidents": incidents, "plans": [],
                "actions": [a.to_dict() for a in self.actions.values()],
                "log": [e.to_dict() for e in self.log], "lessons": []}


class BaselinePlus(Baseline):
    """Segundo escalón: fusiona avisos del mismo sitio y tipo (15 min) y atiende primero lo grave."""

    name = "baseline_plus"
    merge_duplicates = True
    by_severity = True


class BaselineReroute(Baseline):
    """Tercer escalón: ante un aviso de puerta saturada, desvía el 60 % según el manual."""

    name = "baseline_reroute"
    destinations = {"gate_b": "gate_a", "gate_a": "gate_b", "gate_c": "gate_b"}
    saturation_words = ("saturad", "atascad", "no avanza", "aglomer", "demasiada gente", "muchisima gente",
                        "saturated", "jammed", "overcrowd", "too many people", "not moving")

    def _intake(self, obs: Observation, out: list[Action]) -> None:
        super()._intake(obs, out)
        for rep in obs.new_reports:
            text = _norm(rep.text)
            if not any(word in text for word in self.saturation_words):
                continue
            zone = self.parser.parse(rep)["zone"]
            destination = self.destinations.get(zone)
            if destination is None:
                continue
            # El procedimiento se activa una vez por puerta y nunca revisa ni retira el desvío.
            if any(a.kind == ActionKind.REROUTE and a.zone == zone for a in self.actions.values()):
                continue
            a = Action(self._aid(), ActionKind.REROUTE, obs.t, zone=zone,
                       params={"to": destination, "fraction": 0.6},
                       why="puerta saturada: el manual desvía el 60 % a la puerta vecina")
            self.actions[a.id] = a
            out.append(a)
            self._say(obs.t, "action", f"desvía el 60 % de {zone} a {destination} según el manual", a.id)


assert all(k in ALWAYS_APPROVE for _, k, _ in ESCALATION_WORDS)
