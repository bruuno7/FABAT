"""Mando: el agente. Implementa `AgentAPI` (tick / approve / snapshot).

Cada tick: avisos → triaje → prioridades → SUPUESTOS de los planes vivos → resultados de acciones y
de comunicaciones → (re)planificación. Todo lo que hace queda en `self.log` con una frase corta.
El núcleo es determinista: mismas observaciones, mismas decisiones.
"""
from __future__ import annotations

from itertools import permutations
from typing import Any, Callable

from ..contracts import (Action, ActionKind, ActionStatus, Assumption, Autonomy, Channel, CommsAPI, Family, Incident,
                         IncidentStatus, LogEntry, Observation, Plan, Report, Resource, ResourceStatus, Zone)
from . import autonomy, priority
from .assumptions import CLOSED, blocked_zones, holds
from .lexicon import spec_for
from .memory import OperationalMemory
from .parser import HeuristicParser, Parser
from .planner import KIND_ES, RECALL_COOLDOWN, Draft, Planner, Travel, es, label
from .playbook import Adjustments, Playbook
from .rehearsal import Rehearsal
from .triage import HOLD_MAX, IncidentMeta, Triage, TriageEvent, confirmed_person_reference
from .tuning import NOMINAL_DUPLICATE_WINDOW, NOMINAL_RESUPPLY_MIN, RESUPPLY_MARGIN_MIN, Params

MAX_REPLANS = 6          # a partir de aquí Mando deja de insistir y pide una decisión humana
QUIET_MIN = 15           # sin avisos, sin recursos y sin acciones pendientes → se da por cerrado
WATCH_DENSITY = 4.5      # vigilancia propia de zonas: personas/m²
WATCH_RATIO = 0.95
CROWD_CLEAR = 0.7        # una aglomeración solo se cierra cuando la zona baja de este % de su capacidad
WAIT_COST_MIN = 30       # reparto global: dejar a alguien sin recurso cuesta como si tardara 30 min en llegar
SERVICE_EST_MIN = 10     # estimación de cuánto ocupa un incidente a un equipo (para decir cuándo se libera)
BAD_DEST_MIN = 15        # minutos en los que no se vuelve a desviar hacia un destino que se saturó
_TERMINAL = (ActionStatus.DONE, ActionStatus.REJECTED, ActionStatus.FAILED, ActionStatus.CANCELLED)
_PENDING = (ActionStatus.PROPOSED, ActionStatus.AWAITING_APPROVAL)
_TALK = (ActionKind.DISPATCH, ActionKind.RECALL, ActionKind.NOTIFY, ActionKind.ASK, ActionKind.RESUPPLY,
         ActionKind.REQUEST_EXTERNAL)
WATER_RATE_TICKS = 6     # minutos de historia con que se estima el consumo de un punto de agua
_NO_WATCH = ("medical", "backstage")
_ANTICIPATE = ("gate", "stage_front", "pmr")


class Mando:
    def __init__(self, playbook: Playbook | None = None, comms: CommsAPI | None = None,
                 parser: Parser | None = None, *, twin: Callable[[], Any] | None = None, watch_zones: bool = True,
                 festival: str | None = None, params: Params | dict[str, Any] | str | None = None,
                 memory: OperationalMemory | None = None) -> None:
        # `params`: None = Mando de siempre, sin anticipar nada (las cifras anteriores no cambian); `Params.initial()` =
        # valores de ficha; `Params.load()` o "approved" = ficha + cambios APROBADOS por una persona (tuning.py).
        if isinstance(params, str):
            params = Params.load(None if params == "approved" else params)
        elif isinstance(params, dict):
            params = Params.from_dict(params)
        self.params: Params | None = params
        self.memory = memory                        # memoria operativa: solo apunta lo que Mando observa
        self.params_applied: dict[str, int] = {}
        self.points: dict[str, str] = {}            # incidente -> punto concreto que dio quien avisó
        self._water_hist: dict[str, list[float]] = {}
        self._closed_t: dict[str, int] = {}         # incidente -> minuto en que Mando lo cerró
        self._calm_min = 0
        self.playbook = playbook if playbook is not None else Playbook()
        self.comms = comms
        self.parser = parser or HeuristicParser()
        self.planner = Planner(Travel(festival))
        self.rehearsal = Rehearsal(twin)           # ensayo previo en un gemelo del recinto; sin gemelo, proyección analítica
        self.watch = watch_zones

        self.t = 0
        self.zones: dict[str, Zone] = {}
        self.resources: dict[str, Resource] = {}
        self.weather: dict[str, Any] = {}
        self.clock: dict[str, Any] = {}
        self.trend: dict[str, float] = {}           # variación de densidad por minuto (media móvil)
        self._prev_density: dict[str, float] = {}

        self.incidents: dict[str, Incident] = {}
        self.meta: dict[str, IncidentMeta] = {}
        self.plans: dict[str, Plan] = {}
        self.plan_incident: dict[str, str] = {}
        self.live_plans: dict[str, Plan] = {}
        self.review_at: dict[str, int] = {}
        self.actions: dict[str, Action] = {}
        self.accepted: set[str] = set()
        self.assign: dict[str, tuple[str, str]] = {}   # recurso -> (incidente, necesidad que cubre)
        self.recall_until: dict[str, int] = {}
        self.reroutes: dict[str, str] = {}             # desvíos activos: origen -> destino
        self.restricted: dict[str, str] = {}           # zonas que Mando restringió -> incidente
        self.bad_dest: dict[str, int] = {}             # destinos que ya fallaron: nadie desvía hacia ellos hasta t
        self.sig_of: dict[str, tuple] = {}
        self.log: list[LogEntry] = []
        self.lesson_candidates: list[dict[str, Any]] = []
        self.lessons_applied: dict[str, int] = {}
        self.counters = {"reports": 0, "incidents": 0, "merges": 0, "false_alarms": 0, "replans": 0,
                         "assumptions_broken": 0, "approvals": 0, "vetoes": 0, "recalls": 0, "asks": 0,
                         "patterns": 0, "wasted_dispatches": 0, "lessons_applied": 0, "resolved": 0,
                         "rehearsals": 0, "escalations": 0, "params_applied": 0, "human_decision_latency": {}}

        self._ids: dict[str, int] = {}
        self.triage = Triage(self.incidents, self.meta, lambda: self.new_id("M"))
        if self.params is not None:
            self.triage.merge_window = self.params.duplicate_window_min
        self.live = self.triage.live
        self._out: list[Action] = []
        self._approved: list[Action] = []
        self._inflight: dict[str, ActionStatus] = {}
        self._dispatch_of: dict[str, str] = {}         # recurso -> acción que lo movió
        self._moving: set[str] = set()
        self._seen_reports: set[str] = set()
        self._waiting: dict[str, list[str]] = {}       # incidente -> tipos de recurso que le faltan
        self._carry: dict[str, list[str]] = {}         # incidente -> acciones pendientes que hereda el plan nuevo
        self._sms_retry: set[str] = set()
        self._why_waits: dict[str, str] = {}           # incidente -> por qué espera (tablero de frentes)
        self._reserved_for: dict[tuple[str, str], list[str]] = {}   # (incidente, necesidad) -> recursos que le tocan
        self._on_scene_since: dict[str, int] = {}
        self._review_entry: dict[str, LogEntry] = {}   # una sola línea de log por incidente para los «reevaluar»

    # ================================================================ utilidades
    def new_id(self, prefix: str) -> str:
        n = self._ids[prefix] = self._ids.get(prefix, 0) + 1
        return f"{prefix}-{n:03d}" if prefix in ("M", "P") else f"{prefix}-{n:04d}"

    def _log(self, kind: str, text: str, ref: str | None = None, **data: Any) -> LogEntry:
        act = self.actions.get(ref or "")
        m = self.meta.get(data.get("incident") or (act.incident if act is not None else None) or ref or "")
        if data.get("reserved") or (m is not None and m.reserved):
            data["reserved"] = True     # `snapshot()` sustituye el texto por «incidente reservado»
        else:
            data.pop("reserved", None)
        entry = LogEntry(self.t, kind, text, ref, data)
        self.log.append(entry)
        return entry

    def on_scene(self, incident_id: str) -> bool:
        inc = self.incidents[incident_id]
        if self.meta[incident_id].seen_on_scene:
            return True
        return any(self.resources[r].status == ResourceStatus.BUSY for r in inc.assigned if r in self.resources)

    def _where(self, inc: Incident) -> str:
        z = self.zones.get(inc.zone) if inc.zone else None
        return f" en {z.name}" if z else (" (zona sin confirmar)" if not self.meta[inc.id].sitewide else "")

    def _adjust(self, inc: Incident) -> Adjustments:
        z = self.zones.get(inc.zone) if inc.zone else None
        return self.playbook.apply({
            "type": inc.type, "family": str(inc.family), "zone": inc.zone, "zone_kind": z.kind if z else None,
            "severity": inc.severity, "weather": self.weather, "clock": self.clock,
            "zone_density": z.density if z else 0.0, "zone_state": z.state if z else None,
            "zone_ratio": z.occupancy / z.capacity if z and z.capacity else 0.0})

    # ================================================================ AgentAPI
    def tick(self, obs: Observation) -> list[Action]:
        self.t = obs.t
        self.zones, self.resources, self.weather, self.clock = obs.zones, obs.resources, obs.weather, obs.clock
        self.triage.zones = obs.zones
        self.rehearsal.used = 0
        self._out = out = []
        if self._approved:
            for a in self._approved:
                out.append(a)
                self._send(a)
            self._approved = []
        self._update_trend()
        if self.memory is not None:
            self.memory.on_tick(obs.t, obs.zones, obs.weather)

        opened = False
        for report in obs.new_reports:
            if report.id not in self._seen_reports:
                self._seen_reports.add(report.id)
                opened = self._ingest(report) or opened
        if self.watch:
            opened = self._watch_zones() or opened
        if self.params is not None:
            opened = self._watch_supplies() or opened
        if opened:
            for ev in self.triage.detect_patterns(self.t):
                self._on_pattern(ev)
        for inc in self.triage.expire_holds(self.t):
            self._close(inc, IncidentStatus.FALSE_ALARM, f"nadie lo confirmó en {HOLD_MAX} min: no se gasta un equipo")

        self._prioritize()
        self._check_assumptions()
        self._process_results(obs.action_results)
        self._process_comms()
        self._observe_resources()
        if self.params is not None:
            self._standdown_weather()
        self._plan_dirty()
        self._escalate_cards()
        self.counters["rehearsals"] = self.rehearsal.total
        return out

    def approve(self, action_id: str, ok: bool, note: str = "") -> None:
        a = self.actions.get(action_id)
        if a is None or a.status != ActionStatus.AWAITING_APPROVAL:
            return
        inc = self.incidents.get(a.incident or "")
        card = a.params.get("decision_card") or {}
        if ok and a.kind == ActionKind.EVACUATE and a.params.get("prepared") and not note.strip().upper().startswith("EVACUAR"):
            # una evacuación «preparada» ante una amenaza no la ejecuta un aprobador automático ni un sí genérico
            self._log("approval", f"Aprobación genérica RECHAZADA para {a.id}: una evacuación preparada exige la orden expresa "
                      "«EVACUAR …» de quien decide", a.id, ok=None, reserved=self._is_reserved(inc))
            return
        latency = self.t - int(card.get("asked_at", a.t))
        self.counters["human_decision_latency"][a.id] = latency
        if card:
            card["answered_at"] = self.t
        if ok:
            a.status = ActionStatus.EXECUTING
            if note:
                a.params["operator_note"] = note
            self._approved.append(a)       # sale en el siguiente tick para que el bucle la aplique
            self._inflight[a.id] = a.status
            self._log("approval", f"{card.get('addressee', 'La persona')} APRUEBA «{a.kind}»" + (f" en {a.zone}" if a.zone else "")
                      + f" a los {latency} min" + (f": {note}" if note else ""), a.id, ok=True, latency_min=latency,
                      reserved=self._is_reserved(inc))
            return
        a.status = ActionStatus.REJECTED
        a.params["operator_note"] = note
        self.counters["vetoes"] += 1
        self._log("approval", f"{card.get('addressee', 'La persona')} VETA «{a.kind}»" + (f" en {a.zone}" if a.zone else "")
                  + f" a los {latency} min" + (f": {note}" if note else ""), a.id, ok=False, latency_min=latency,
                  reserved=self._is_reserved(inc))
        lesson = autonomy.veto_lesson(a, inc, note, len(self.lesson_candidates) + 1)
        self.lesson_candidates.append(lesson)
        self._log("lesson", f"Lección candidata {lesson['id']}: {lesson['text']}", lesson["id"], candidate=True)
        if inc is not None and inc.status not in CLOSED:
            m = self.meta[inc.id]
            m.vetoed.add(f"{a.kind}:{a.params.get('state')}" if a.kind == ActionKind.SET_ZONE else str(a.kind))
            m.dirty = f"la persona vetó «{a.kind}»: se propone la alternativa ({autonomy.ALTERNATIVE.get(a.kind, 'siguiente opción')})"

    def snapshot(self, full: bool = False) -> dict[str, Any]:
        """JSON para la pantalla. Por defecto es la vista PÚBLICA: los incidentes reservados (violencia sexual, menores,
        amenazas) salen sin texto, sin tipo y sin zona. `full=True` es la vista del centro de control."""
        hidden = {i for i, m in self.meta.items() if m.reserved} if not full else set()
        mask = "incidente reservado"
        incidents = []
        for inc in sorted(self.incidents.values(), key=lambda i: (i.status in CLOSED, priority.sort_key(i))):
            m = self.meta[inc.id]
            d = inc.to_dict()
            d.update(label=label(inc), explain=priority.explain(inc.priority, m.factors), origin=m.origin,
                     life_threat=m.life_threat, threat=m.threat, hold=m.hold, contradicted=m.contradicted,
                     plan=m.plan, replans=m.replans, level=m.level, waiting=self._waiting.get(inc.id, []),
                     first_action_t=m.first_action_t, members=m.members, reserved=m.reserved, merged_into=m.merged_into)
            if inc.id in hidden:
                d.update(label=mask, type="reserved", zone=None, notes=[], explain=f"prioridad {es(inc.priority)}")
            incidents.append(d)
        plans = []
        for p in self.plans.values():
            d = p.to_dict()
            d.update(incident=self.plan_incident.get(p.id), live=p.id in self.live_plans,
                     review_at=self.review_at.get(p.id))
            if d["incident"] in hidden:
                d.update(objective=mask, why=mask)
                for x in d["assumptions"]:
                    x.update(text=mask, check={"kind": x["check"].get("kind")})
            plans.append(d)
        actions = []
        for a in self.actions.values():
            d = a.to_dict()
            if a.incident in hidden:
                card = d["params"].get("decision_card")
                d.update(why=mask, zone=None, params={"decision_card": {k: card[k] for k in ("window_min", "asked_at", "escalate_at")}}
                         if card else {})
            actions.append(d)
        log = []
        for e in self.log:
            d = e.to_dict()
            if not full and e.data.get("reserved"):
                d.update(text=mask, data={"reserved": True})
            log.append(d)
        latency = self.counters["human_decision_latency"]
        return {
            "t": self.t,
            "incidents": incidents,
            "fronts": self._fronts(hidden),
            "plans": plans,
            "actions": actions,
            "pending_approvals": [a.id for a in self.actions.values() if a.status == ActionStatus.AWAITING_APPROVAL],
            "resources": [{**r.to_dict(), "assigned_to": self.assign.get(r.id, (None,))[0],
                           "role": self.planner.travel.roles.get(r.id),
                           **({"zone": None, "task": None, "assigned_to": "reserved"}
                              if self.assign.get(r.id, (None,))[0] in hidden else {})}
                          for r in self.resources.values()],
            "log": log,
            "counters": dict(self.counters, human_decision_latency=dict(latency),
                             human_decision_latency_mean=round(sum(latency.values()) / len(latency), 1) if latency else None),
            "lessons": {"applied": dict(self.lessons_applied), "candidates": list(self.lesson_candidates),
                        "playbook": [x["id"] for x in self.playbook.lessons]},
            "params": {"active": self.params is not None, **(self.params.to_dict() if self.params is not None else {}),
                       "applied": dict(self.params_applied)},
        }

    def _fronts(self, hidden: set[str] = frozenset()) -> list[dict[str, Any]]:
        """Tablero de frentes: por incidente vivo, quién va, cuándo llega y, si espera, por qué."""
        out = []
        for inc in self.live:
            team = []
            for rid in inc.assigned:
                r = self.resources.get(rid)
                if r is not None:
                    team.append({"resource": rid, "status": str(r.status), "eta": r.eta})
            out.append({"incident": inc.id, "label": "incidente reservado" if inc.id in hidden else label(inc),
                        "zone": None if inc.id in hidden else inc.zone, "status": str(inc.status),
                        "priority": inc.priority, "life_threat": self.meta[inc.id].life_threat, "team": team,
                        "eta": min((x["eta"] for x in team if x["status"] == "en_route"), default=None),
                        "waiting": inc.id in self._why_waits, "why_waiting": self._why_waits.get(inc.id)})
        return out

    # ================================================================ 1 · avisos y triaje
    def _update_trend(self) -> None:
        prev, trend = self._prev_density, self.trend
        for zid, z in self.zones.items():
            d = z.occupancy / z.area_m2 if z.area_m2 else 0.0
            if zid in prev:
                trend[zid] = 0.5 * trend.get(zid, 0.0) + 0.5 * (d - prev[zid])
            prev[zid] = d

    def _ingest(self, report: Report) -> bool:
        self.counters["reports"] += 1
        p = self.parser.parse(report, self.zones)
        z = self.zones.get(p["zone"]) if p["zone"] else None
        sensor = p.get("sensor") or {}
        # una lectura de sensor que no cuadra con lo que se ve en la zona es una lectura espuria
        if report.channel == Channel.SENSOR and z is not None and p["family"] == Family.CROWD:
            said = sensor.get("density") or (sensor["occupancy"] / z.area_m2 if sensor.get("occupancy") and z.area_m2 else None)
            if said and z.density < 0.6 * said:
                p["confidence"] = 0.3
                p["life_threat"] = False
                self._log("report", f"Lectura dudosa de {report.source}: dice {es(said)}/m² y en {z.name} se observan "
                          f"{es(z.density)}/m²", report.id)
        what = "todo en orden" if p["all_clear"] else label(Incident("", p["family"], p["type"], None, 0, 0))
        self._log("report", f"[{report.channel}] {report.source or 'anónimo'}: «{report.text[:90]}» → {what}"
                  + (f" en {z.name}" if z else "") + f" (confianza {round(p['confidence'] * 100)} %)", report.id,
                  parsed={"type": p["type"], "zone": p["zone"], "severity": p["severity"], "missing": p["missing"]},
                  reserved=bool(p.get("reserved")))
        ev = self.triage.ingest(report, p, self.t)
        return self._on_event(ev, report)

    def _on_event(self, ev: TriageEvent, report: Report) -> bool:
        inc = ev.incident
        if ev.kind == "noise" or inc is None:
            self._log("report", f"Sin acción: {ev.text}", report.id)
            return False
        m = self.meta[inc.id]
        if ev.kind == "new":
            if self.memory is not None:
                self.memory.on_incident(inc, "zone" in m.missing and not m.sitewide)
            self.counters["incidents"] += 1
            self._log("incident", f"Nuevo {inc.id}: {label(inc)}{self._where(inc)}, gravedad {inc.severity}, confianza "
                      f"{round(inc.confidence * 100)} %" + (" · retenido hasta confirmar" if m.hold else "")
                      + (" · RIESGO VITAL: se despacha sin esperar" if m.life_threat else ""), inc.id)
            if inc.type.startswith("unknown"):
                self._log("incident", f"{inc.id}: tipo no reconocido: actúo por familia y señales (familia {inc.family}"
                          + (", riesgo vital → equipo médico ya" if m.life_threat else "")
                          + (", posible amenaza → decide una persona" if m.threat else "")
                          + ("; el resto se pregunta" if not m.threat else "") + ")", inc.id, generic=True)
            return True
        if ev.kind == "merge":
            if self.memory is not None:
                self.memory.on_merge(inc, int(ev.data.get("gap_min", 0)), int(ev.data.get("quiet_min", 0)))
            if self.params is not None and ev.data.get("quiet_min", 0) > NOMINAL_DUPLICATE_WINDOW:
                self._param("duplicate_window_min", None, f"el aviso {report.id} llega {ev.data['quiet_min']} min después del último "
                            f"de {inc.id}; con la ventana de {NOMINAL_DUPLICATE_WINDOW} min habría abierto otro incidente y movido otro equipo",
                            incident=inc.id)
            self.counters["merges"] += 1
            text = (f"Aviso {report.id} es el mismo incidente {inc.id} ({len(inc.reports)} avisos, confianza "
                    f"{round(inc.confidence * 100)} %): no se manda otro equipo")
            if ev.data.get("zone_found"):
                text += f" · ya se sabe la zona: {ev.data['zone_found']}"
            if ev.data.get("confirmed"):
                text += " · confirmado, se libera la retención"
            self._emit(ActionKind.MERGE, inc, text, params={"report": report.id, "reports": list(inc.reports)},
                       status=ActionStatus.DONE)
            if ev.data.get("zone_found"):
                self._fold_duplicate(inc)
            return False
        if ev.kind == "contradiction":
            self._log("incident", f"{inc.id}: versiones contradictorias ({ev.text}); confianza baja a "
                      f"{round(inc.confidence * 100)} % y se pregunta", inc.id)
            if ("ask", inc.zone, "ask:clarify") not in m.sigs:
                m.dirty = m.dirty or "versiones contradictorias"
            return False
        if ev.kind == "all_clear":
            status = IncidentStatus.RESOLVED if m.seen_on_scene else IncidentStatus.FALSE_ALARM
            self._close(inc, status, ev.text)
        return False

    def _on_pattern(self, ev: TriageEvent) -> None:
        inc = ev.incident
        self.counters["patterns"] += 1
        self.counters["incidents"] += 1
        self._log("incident", f"PATRÓN {inc.id}: {ev.data['n']} casos relacionados en {ev.data['window']} min "
                  f"({', '.join(ev.data['members'])}). No son casos sueltos: se actúa sobre la causa", inc.id, **ev.data)

    def _watch_zones(self) -> bool:
        """Vigilancia propia: Mando no espera a que alguien avise de una zona que ya ve saturada."""
        opened = False
        for z in self.zones.values():
            if not z.capacity or z.kind in _NO_WATCH:
                continue
            dens = z.occupancy / z.area_m2 if z.area_m2 else 0.0
            ratio = z.occupancy / z.capacity
            rising = self.trend.get(z.id, 0.0) * z.area_m2 * 10 / z.capacity
            early = z.kind in _ANTICIPATE and ratio >= 0.85 and ratio + rising >= 1.0   # solo donde hay cola que gestionar
            if not (dens >= WATCH_DENSITY or ratio >= (WATCH_RATIO if z.kind in _ANTICIPATE else 1.0) or early):
                continue
            if any(i.zone == z.id and i.family == Family.CROWD for i in self.live):
                continue
            if z.id in self.reroutes.values() and dens < 5.0:
                continue  # destino de un desvío nuestro: lo vigila el supuesto de ese plan, que es quien debe corregir
            if dens >= 6.0:
                type_, sev, needs = "crush_risk", 9, {"security": 2}
            elif dens >= 5.0:
                type_, sev, needs = "crush_risk", 8, {"security": 1}
            else:
                type_, sev, needs = ("gate_saturation" if z.kind == "gate" else "bottleneck"), 6, {}
            spec = spec_for(type_)
            p = {"type": type_, "family": spec.family, "zone": z.id, "severity": sev, "needs": needs,
                 "confidence": 0.9, "missing": [], "life_threat": False, "sitewide": False}
            pseudo = Report(id=f"obs-{z.id}-{self.t}", t=self.t, channel=Channel.SENSOR, text="", source="observación propia")
            inc = self.triage._open(pseudo, p, self.t).incident
            self.meta[inc.id].origin = "watch"
            self.counters["incidents"] += 1
            self._log("incident", f"Nuevo {inc.id} por observación propia: {z.name} al {round(ratio * 100)} % "
                      f"({es(dens)}/m²)" + (f", subiendo: {round((ratio + rising) * 100)} % en 10 min" if rising > 0.01 else ""),
                      inc.id)
            opened = True
        return opened

    # ================================================================ 1 bis · parámetros operativos (tuning.py)
    def _param(self, param: str, key: str | None, what: str, incident: str | None = None) -> None:
        """Cada vez que un parámetro APRENDIDO Y APROBADO cambia una decisión, queda en el log con su evidencia."""
        name = f"{param}[{key}]" if key else param
        self.counters["params_applied"] += 1
        self.params_applied[name] = self.params_applied.get(name, 0) + 1
        cite = self.params.cite(param, key) if self.params is not None else ""
        self._log("param", f"Parámetro aprendido {name}" + (f" ({cite})" if cite else "") + f": {what}", name,
                  incident=incident, param=param, key=key)

    def _watch_supplies(self) -> bool:
        """Anticipar la reposición: litros / consumo observado por minuto = minutos que quedan. Si quedan menos que lo
        que tarda la reposición (de ficha, o el tiempo REAL observado y aprobado) más el margen, se pide ya."""
        opened = False
        for z in self.zones.values():
            if "water_l" not in z.flags:
                continue
            level = float(z.flags.get("water_l") or 0.0)
            hist = self._water_hist.setdefault(z.id, [])
            hist.append(level)
            del hist[:-(WATER_RATE_TICKS + 1)]
            drops = [a - b for a, b in zip(hist, hist[1:]) if 0 < a - b < 400]
            if level <= 0 or len(drops) < 3:
                continue
            rate = sum(drops) / len(drops)
            left = level / rate
            lead, learned = self.params.lead(z.id)
            mine = [i for i in self.live if i.zone == z.id and self.meta[i.id].group == "water"]
            for i in mine:      # un incidente de agua que Mando sigue VIENDO no caduca: el «depósito a 0» que llegue es el mismo
                self.meta[i.id].last_report_t = self.t
            if left > lead + RESUPPLY_MARGIN_MIN:
                continue
            if mine or any(
                    a.kind == ActionKind.RESUPPLY and a.zone == z.id and a.status in (*_PENDING, ActionStatus.EXECUTING)
                    for a in self.actions.values()):
                continue
            spec = spec_for("water_low")
            p = {"type": "water_low", "family": spec.family, "zone": z.id, "severity": spec.severity, "needs": dict(spec.needs),
                 "confidence": 0.95, "missing": [], "life_threat": False, "sitewide": False}
            pseudo = Report(id=f"obs-water-{z.id}-{self.t}", t=self.t, channel=Channel.SENSOR, text="", source="observación propia")
            inc = self.triage._open(pseudo, p, self.t).incident
            self.meta[inc.id].origin = "watch"
            self.counters["incidents"] += 1
            self._log("incident", f"Nuevo {inc.id} por observación propia: {z.name} tiene {round(level)} l y gasta {es(rate)} l/min: "
                      f"quedan ~{round(left)} min y la reposición tarda ~{lead} min (+{RESUPPLY_MARGIN_MIN} de margen): se pide YA", inc.id)
            if learned and left > NOMINAL_RESUPPLY_MIN + RESUPPLY_MARGIN_MIN:
                self._param("resupply_lead_min", z.id, f"reposición de {z.name} pedida con ~{round(left)} min de agua; con el valor de "
                            f"ficha ({NOMINAL_RESUPPLY_MIN} min) se habría esperado ~{round(left - NOMINAL_RESUPPLY_MIN - RESUPPLY_MARGIN_MIN)} min más",
                            incident=inc.id)
            opened = True
        return opened

    def _standdown_weather(self) -> None:
        """Parámetro `weather_standdown_min`: tras N minutos seguidos en calma (sin viento de preaviso ni lluvia) y sin
        avisos nuevos, se cancelan los PREPARATIVOS de una alerta que no llegó. No toca ningún umbral: si el viento
        vuelve a subir, el aviso de la estación abre otro incidente y se actúa igual que siempre."""
        calm = int(self.weather.get("wind_level") or 0) == 0 and not self.weather.get("rain")
        self._calm_min = self._calm_min + 1 if calm else 0
        n = self.params.weather_standdown_min
        if n is None or self._calm_min < n:
            return
        for inc in list(self.live):
            m = self.meta[inc.id]
            if inc.family != Family.WEATHER or m.heat or inc.type == "heat_wave" or m.life_threat or m.origin == "pattern" \
                    or self.t - m.last_report_t < n:
                continue
            pending = [a for a in self.actions.values() if a.incident == inc.id and a.status in _PENDING]
            self._param("weather_standdown_min", None, f"{self._calm_min} min seguidos en calma y sin avisos nuevos: se cancelan los "
                        f"preparativos de {inc.id} ({len(pending)} acciones pendientes, {len(inc.assigned)} equipos liberados)",
                        incident=inc.id)
            for rid in list(inc.assigned):
                r = self.resources.get(rid)
                if r is not None and r.status == ResourceStatus.EN_ROUTE:
                    self._emit(ActionKind.RECALL, inc, f"{r.name} vuelve: la alerta se ha desactivado", resource=rid, zone=inc.zone,
                               channel=Channel.VOICE, params={"message": "Alerta desactivada, volved a vuestra posición."})
            self._close(inc, IncidentStatus.RESOLVED, "alerta meteorológica desactivada: preparativos cancelados")

    # ================================================================ 2 · prioridades
    def _prioritize(self) -> None:
        live, zones, trend, meta, t = self.live, self.zones, self.trend, self.meta, self.t
        lessons = bool(self.playbook.lessons)
        for inc in live:
            m = meta[inc.id]
            if lessons:
                adj = self._adjust(inc)
                m.boost = adj.boost
                if adj.boost and adj.applied:
                    for lid in adj.applied:
                        if lid not in m.lessons_logged and self.playbook.get(lid)["then"].get("priority_boost"):
                            self._lesson(lid, inc, f"prioridad de {inc.id} {'+' if adj.boost > 0 else '−'}{es(abs(adj.boost))}")
            inc.priority, m.factors = priority.compute(
                inc, zones.get(inc.zone) if inc.zone else None, t, trend.get(inc.zone, 0.0) if inc.zone else 0.0,
                life_threat=m.life_threat, minors=m.minors, boost=m.boost)
        if len(live) > 1:
            live.sort(key=priority.sort_key)

    def _lesson(self, lesson_id: str, inc: Incident, what: str) -> None:
        m = self.meta[inc.id]
        key = f"{lesson_id}:{what}"
        if key in m.lessons_logged:
            return
        m.lessons_logged.add(key)
        m.lessons_logged.add(lesson_id)
        self.counters["lessons_applied"] += 1
        self.lessons_applied[lesson_id] = self.lessons_applied.get(lesson_id, 0) + 1
        self._log("lesson", f"Lección {lesson_id} aplicada: {what} — {self.playbook.describe(lesson_id)}", lesson_id,
                  incident=inc.id)

    # ================================================================ 3 · supuestos
    def _check_assumptions(self) -> None:
        for plan in list(self.live_plans.values()):
            for a in plan.assumptions:
                if a.holds and not holds(a, self):
                    self._break(plan, a)
                    break

    def _break(self, plan: Plan, a: Assumption, detail: str = "") -> None:
        """Un supuesto deja de cumplirse: el plan se tira, se cancela lo pendiente y el incidente se replanifica."""
        if plan.id not in self.live_plans:
            return
        a.holds, a.broken_at = False, self.t
        plan.invalidated_by = a.id
        del self.live_plans[plan.id]
        self.counters["assumptions_broken"] += 1
        inc = self.incidents[self.plan_incident[plan.id]]
        m = self.meta[inc.id]
        c = a.check
        kind = c["kind"]
        now = ""
        zone = self.zones.get(c.get("zone", ""))
        if kind == "zone_occupancy_below" and zone is not None:
            now = f" (ahora {zone.occupancy}/{zone.capacity}, {round(zone.occupancy / zone.capacity * 100)} %)"
            if c.get("own_action") in self.actions:
                now += " — en parte por nuestro propio desvío"
        elif kind == "route_clear":
            now = " (" + ", ".join(f"{z} a {es(self.zones[z].density)}/m²" for z in blocked_zones(a, self)) + ")"
        m.broken_kind = kind
        if kind == "incident_improving":
            m.review_times.append(self.t)
        if kind == "incident_improving" and len(m.review_times) > 1 and inc.id in self._review_entry:
            # las revisiones repetidas de un mismo incidente no llenan la pantalla: una sola línea que se actualiza
            entry = self._review_entry[inc.id]
            self.log.remove(entry)      # la línea agrupada se pone al día y baja al final: el log sigue siendo cronológico
            self.log.append(entry)
            entry.t = self.t
            entry.text = (f"{inc.id}: reevaluado {len(m.review_times)} veces (t = {', '.join(map(str, m.review_times))}) y sigue "
                          f"sin mejorar; escalón de respuesta {m.level + 1}")
            entry.data.update(times=list(m.review_times), plan=plan.id)
        else:
            entry = self._log("assumption_broken", f"SUPUESTO ROTO en {plan.id}: «{a.text}»{now}{detail}. El plan se tira",
                              a.id, plan=plan.id, incident=inc.id, check=dict(c))
            if kind == "incident_improving":
                self._review_entry[inc.id] = entry

        touched = set(blocked_zones(a, self))
        m.avoid |= touched
        rid = c.get("resource") or (self.actions[c["action"]].resource if kind == "action_accepted_within"
                                    and c.get("action") in self.actions else None)
        if kind in ("resource_status_is", "action_accepted_within") and rid:
            touched.add(rid)
            self._drop_resource(inc, rid, exclude=True)
            r = self.resources.get(rid)
            self._emit(ActionKind.NOTIFY, inc, f"{r.name if r else rid} "
                       + ("está fuera de servicio" if kind == "resource_status_is" else "no acepta o no contesta")
                       + ": el coordinador tiene que saberlo", channel=Channel.RADIO,
                       params={"to": "coordinator", "about": rid, "message": f"{rid} no disponible para {inc.id}."})
        elif kind in ("incident_improving", "weather_below"):
            m.level += 1
        if kind == "zone_occupancy_below":
            self.bad_dest[c["zone"]] = self.t + BAD_DEST_MIN

        carry = []
        for aid in plan.steps:
            act = self.actions[aid]
            if act.status not in _PENDING:
                continue
            if act.zone in touched or act.params.get("to") in touched or act.resource in touched:
                act.status = ActionStatus.CANCELLED
                self._forget(act)
                self._log("action", f"Cancelada {act.id} ({act.kind}): dependía del supuesto roto", act.id)
            else:
                carry.append(aid)
        self._carry[inc.id] = carry
        m.broken = a.id
        m.dirty = f"se rompió el supuesto «{a.text}»{now}"

    def _forget(self, act: Action) -> None:
        sig = self.sig_of.pop(act.id, None)
        inc = self.triage.canonical(act.incident or "")
        if sig and inc is not None:
            self.meta[inc.id].sigs.discard(sig)
        self._inflight.pop(act.id, None)

    def _drop_resource(self, inc: Incident, rid: str, exclude: bool) -> None:
        if rid in inc.assigned:
            inc.assigned.remove(rid)
        if self.assign.get(rid, (None,))[0] == inc.id:
            del self.assign[rid]
        self._moving.discard(rid)
        self._on_scene_since.pop(rid, None)
        if exclude:
            self.meta[inc.id].excluded.add(rid)

    # ================================================================ 4 · resultados
    def _process_results(self, results: list[Action]) -> None:
        for res in results:
            mine = self.actions.get(res.id)
            if mine is not None and mine is not res:
                mine.status = res.status
                mine.params.update(res.params)
        for aid, last in list(self._inflight.items()):
            a = self.actions[aid]
            if a.status == last:
                continue
            self._inflight[aid] = a.status
            if a.status in _TERMINAL:
                del self._inflight[aid]
            if self.memory is not None:
                self.memory.on_action_status(a, self.t)
            self._on_status(a)

    def _on_status(self, a: Action) -> None:
        inc = self.triage.canonical(a.incident or "")
        moves = a.kind in (ActionKind.DISPATCH, ActionKind.RESUPPLY)
        r = self.resources.get(a.resource or "")
        who = r.name if r else (a.resource or "")
        error = str(a.params.get("error", ""))
        if a.status == ActionStatus.DONE:
            if not moves or inc is None:
                if a.kind == ActionKind.REQUEST_EXTERNAL:
                    self._log("outcome", f"Llega la ayuda externa pedida en {a.id}", a.id)
                return
            self.accepted.add(a.id)
            if a.params.get("outcome") == "nothing_found":
                self.counters["wasted_dispatches"] += 1
                self._log("outcome", f"{who} llega a {a.zone} y no encuentra nada: despacho desperdiciado", a.id,
                          wasted=True, incident=inc.id)
                if self.memory is not None:
                    # ¿duplicado que no se supo fundir? Solo si había OTRO incidente igual en la misma zona, CONFIRMADO en
                    # el sitio y todavía abierto cuando entró este aviso. Si no, es una falsa alarma y no enseña nada.
                    group = self.meta[inc.id].group
                    gaps = [inc.t_open - o.t_open for o in self.incidents.values()
                            if o is not inc and o.zone == inc.zone and self.meta[o.id].group == group
                            and self.meta[o.id].origin == "report" and self.meta[o.id].seen_on_scene
                            and o.t_open <= inc.t_open <= self._closed_t.get(o.id, self.t)]
                    self.memory.on_wasted(inc, min(gaps) if gaps else None)
                self._drop_resource(inc, a.resource, exclude=False)
                self.meta[inc.id].checked_empty = self.t
                if inc.status not in CLOSED and not inc.assigned and not self._still_crowded(inc, "no hace falta equipo en el sitio"):
                    self._close(inc, IncidentStatus.FALSE_ALARM, f"{who} no encontró nada en el sitio")
            elif inc.status not in CLOSED:
                m = self.meta[inc.id]
                first = not m.seen_on_scene
                m.seen_on_scene = True
                inc.status = IncidentStatus.IN_PROGRESS
                self._log("outcome", f"{who} está en el sitio ({inc.id}, {self.t - inc.t_open} min desde el aviso)", a.id)
                if first and self.comms is not None and a.kind == ActionKind.DISPATCH:
                    self._emit(ActionKind.ASK, inc, "el primer equipo en el sitio confirma qué hace falta de verdad",
                               resource=a.resource, channel=Channel.VOICE,
                               params={"purpose": "sitrep", "to": a.resource, "reports": inc.reports[::-1],
                                       "message": "¿Qué os encontráis? ¿Necesitáis algo más?"})
        elif a.status in (ActionStatus.REJECTED, ActionStatus.FAILED) and moves and inc is not None:
            if error == "incident_closed":
                self._drop_resource(inc, a.resource, exclude=False)
                if inc.status not in CLOSED and not self._still_crowded(inc, "el equipo ya no hace falta"):
                    self._close(inc, IncidentStatus.RESOLVED, "el incidente ya estaba cerrado cuando salió el equipo")
            elif error == "comms_down" and a.channel == Channel.VOICE and a.id not in self._sms_retry:
                self._resend_sms(a, inc)
            else:
                reason = {"rejected": "rechaza", "resource_busy": "está ocupado", "resource_offline": "está fuera de servicio",
                          "no_answer": "no contesta", "route_blocked": "no tiene ruta"}.get(error, "rechaza" if a.status == ActionStatus.REJECTED else "no contesta")
                self._dispatch_failed(a, inc, reason)
        elif a.status == ActionStatus.CANCELLED and moves and inc is not None and inc.status not in CLOSED:
            if error in ("incident_resolved", "incident_failed"):
                self._drop_resource(inc, a.resource, exclude=False)
                if not self._still_crowded(inc, "el equipo ya no hace falta"):
                    self._close(inc, IncidentStatus.RESOLVED if error == "incident_resolved" else IncidentStatus.FAILED,
                            "el incidente se cerró antes de que llegara el equipo")
        elif a.status == ActionStatus.FAILED:
            self._log("outcome", f"Falla {a.id} ({a.kind}" + (f" → {a.zone}" if a.zone else "") + f"): {error or 'sin detalle'}", a.id)
            self._forget(a)

    def _dispatch_failed(self, a: Action, inc: Incident, reason: str, recall: bool = False) -> None:
        """RECHAZA o NO CONTESTA → siguiente mejor recurso, vía el supuesto «acepta en N min»."""
        if a.id in self.accepted and not recall:
            return
        r = self.resources.get(a.resource or "")
        who = r.name if r else a.resource
        self._log("outcome", f"{who} {reason} ({a.id}): se busca el siguiente mejor recurso", a.id, incident=inc.id)
        if recall and r is not None and r.status in (ResourceStatus.EN_ROUTE, ResourceStatus.BUSY):
            self._emit(ActionKind.RECALL, inc, f"{who} {reason}: se le libera para no bloquearlo", resource=r.id,
                       zone=inc.zone, channel=Channel.SMS, params={"message": "Orden anulada."})
        plan = self.live_plans.get(self.meta[inc.id].plan or "")
        hit = next((s for s in plan.assumptions if s.holds and s.check.get("action") == a.id), None) if plan else None
        if hit is not None:
            self._break(plan, hit, f" — {who} {reason}")
        elif inc.status not in CLOSED:
            self._drop_resource(inc, a.resource, exclude=True)
            self.meta[inc.id].dirty = f"{who} {reason}"

    def _resend_sms(self, a: Action, inc: Incident) -> None:
        self._sms_retry.add(a.id)
        self._forget(a)
        if a.resource:
            self._drop_resource(inc, a.resource, exclude=False)
        b = self._emit(a.kind, inc, f"voz caída: el mismo mensaje de {a.id} sale por SMS", resource=a.resource,
                       zone=a.zone, channel=Channel.SMS, params={**{k: v for k, v in a.params.items() if k != "error"},
                                                                 "retry_of": a.id})
        self._sms_retry.add(b.id)
        if a.resource and a.kind in (ActionKind.DISPATCH, ActionKind.RESUPPLY):
            self.assign[a.resource] = (inc.id, a.params.get("need", "logistics"))
            inc.assigned.append(a.resource)
            self._dispatch_of[a.resource] = b.id
            plan = self.live_plans.get(self.meta[inc.id].plan or "")
            if plan is not None:  # el supuesto de aceptación pasa a vigilar el SMS
                plan.steps.append(b.id)
                for s in plan.assumptions:
                    if s.check.get("action") == a.id:
                        s.check.update(action=b.id, since=self.t)

    def _process_comms(self) -> None:
        if self.comms is None:
            return
        for reply in self.comms.poll(self.t):
            ref = reply.get("action_id") or reply.get("action")
            a = self.actions.get(ref.id if isinstance(ref, Action) else ref)
            if a is None:
                continue
            result = str(reply.get("result") or reply.get("reply") or reply.get("kind") or reply.get("status") or "")
            text = str(reply.get("text") or "")
            if self.memory is not None:
                self.memory.on_reply(a, result, self.t)
            inc = self.triage.canonical(a.incident or "")
            r = self.resources.get(a.resource or "")
            who = r.name if r else a.params.get("to") or "destinatario"
            if result == "accept":
                if a.kind in (ActionKind.DISPATCH, ActionKind.RESUPPLY):
                    self.accepted.add(a.id)
                    self._log("outcome", f"{who} acepta" + (f": «{text[:70]}»" if text else ""), a.id)
            elif result == "answer":
                if inc is not None:
                    self._on_answer(a, inc, text, reply.get("data") or {})
            elif result in ("reject", "no_answer", "failed", "channel_down"):
                down = result == "channel_down" or "canal" in text.lower() or reply.get("error") == "comms_down"
                if a.status in (ActionStatus.REJECTED, ActionStatus.FAILED, ActionStatus.CANCELLED):
                    continue  # el mundo ya lo dijo y ya está tratado
                if down and a.channel == Channel.VOICE and a.id not in self._sms_retry and inc is not None:
                    self._log("outcome", f"Voz caída al llamar a {who}", a.id)
                    if a.kind in (ActionKind.DISPATCH, ActionKind.RESUPPLY) and a.id in self.accepted:
                        continue
                    self._resend_sms(a, inc)
                elif a.kind in (ActionKind.DISPATCH, ActionKind.RESUPPLY) and inc is not None:
                    self._dispatch_failed(a, inc, "rechaza" if result == "reject" else "no contesta", recall=True)
                elif a.kind == ActionKind.ASK and inc is not None:
                    self._log("outcome", f"Sin respuesta a la pregunta {a.id}", a.id)
                    if self.memory is not None:
                        self.memory.on_ask_unanswered(a)
                    if self.meta[inc.id].ask == a.id:
                        self.meta[inc.id].ask = None

    def _on_answer(self, a: Action, inc: Incident, text: str, data: dict[str, Any]) -> None:
        m = self.meta[inc.id]
        if m.ask == a.id:
            m.ask = None
        if inc.status in CLOSED:
            return
        if a.params.get("purpose") == "identity":
            self._on_identity(a, inc, text)
            return
        if a.params.get("purpose") == "point":
            self._on_point(a, inc, str(data.get("point") or ""))
            return      # de esta respuesta solo se usa el punto: así lo aprendido no se confunde con «preguntar más»
        p = None
        exists = data.get("exists")
        if not data and text:
            p = self.parser.parse(Report(id=f"ans-{a.id}", t=self.t, channel=a.channel or Channel.VOICE, text=text,
                                         source=str(a.params.get("to", ""))), self.zones)
            exists = False if p["all_clear"] else True if (not p["type"].startswith("unknown") or p["zone"]) else None
            data = {"zone": p["zone"], "severity": p["severity"] if not p["type"].startswith("unknown") else None,
                    "type": p["type"] if not p["type"].startswith("unknown") else None, "family": p["family"]}
        self._log("outcome", f"Respuesta a {a.id}: «{text[:90]}»", a.id, incident=inc.id)
        if exists is False:
            self._close(inc, IncidentStatus.RESOLVED if m.seen_on_scene else IncidentStatus.FALSE_ALARM,
                        "quien está en el sitio dice que no pasa nada")
            return
        if exists is None:
            return
        changed = []
        if data.get("zone") in self.zones and data["zone"] != inc.zone:
            inc.zone = data["zone"]
            changed.append(f"zona {inc.zone}")
        if data.get("type") and (inc.type.startswith("unknown") or "type" in m.missing):
            inc.type = str(data["type"])
            spec = spec_for(inc.type, data.get("family"))
            inc.family, m.group = spec.family, spec.group
            m.reserved = m.reserved or spec.reserved
            m.life_threat, m.threat = m.life_threat or spec.life_threat, m.threat or spec.threat
            if not inc.needs:
                inc.needs = dict(spec.needs)
            changed.append(label(inc))
        if data.get("severity") and int(data["severity"]) != inc.severity:
            inc.severity = max(1, min(10, int(data["severity"])))
            changed.append(f"gravedad {inc.severity}")
        if isinstance(data.get("needs"), dict) and data["needs"] != inc.needs:
            inc.needs = {str(k): int(n) for k, n in data["needs"].items()}
            changed.append("hace falta " + ", ".join(f"{n} de {KIND_ES.get(k, k)}" for k, n in inc.needs.items()))
        if data.get("deadline") is not None:
            inc.deadline = int(data["deadline"])
        if changed and self._fold_duplicate(inc):
            return
        was_blocked = m.hold or m.missing or m.contradicted
        inc.confidence = max(inc.confidence, 0.9)
        m.hold, m.contradicted = False, False
        m.missing = [item for item in m.missing if item == "identity"]
        have: dict[str, int] = {}
        for rid in inc.assigned:
            k = self.assign.get(rid, (None, ""))[1]
            have[k] = have.get(k, 0) + 1
        deficit = any(n > have.get(k, 0) + (have.get("ambulance", 0) if k == "medical" else 0) for k, n in inc.needs.items())
        if was_blocked or deficit:
            m.dirty = "confirmado por quien está en el sitio" + (": " + ", ".join(changed) if changed else "")

    def _on_identity(self, a: Action, inc: Incident, text: str) -> None:
        """Reconciliar una víctima confirmada, no el parecido entre dos avisos.

        Los equipos que ya salieron siguen atendiendo; sus callbacks se resuelven por el alias,
        sin reescribir la orden original ni volver a despachar. Se elimina solo la demanda doble.
        """
        m = self.meta[inc.id]
        ref = confirmed_person_reference(text)
        other = self.triage.canonical(ref or "")
        if (a.kind != ActionKind.ASK or a.incident != inc.id or "identity" not in m.missing
                or a.status in (ActionStatus.CANCELLED, ActionStatus.REJECTED, ActionStatus.FAILED)
                or other is None or other is inc or other.status in CLOSED
                or inc.family != Family.MEDICAL or other.family != Family.MEDICAL
                or m.origin != "report" or self.meta[other.id].origin != "report"
                or (inc.zone and other.zone and inc.zone != other.zone)):
            self._log("outcome", f"Identidad no confirmada en respuesta a {a.id}; se mantienen ambas demandas",
                      a.id, incident=inc.id)
            return
        om = self.meta[other.id]
        other.reports.extend(r for r in inc.reports if r not in other.reports)
        other.zone = other.zone or inc.zone
        if inc.severity > other.severity:
            other.type, other.severity, om.group = inc.type, inc.severity, m.group
        for kind, n in inc.needs.items():
            other.needs[kind] = max(other.needs.get(kind, 0), n)
        if inc.deadline is not None:
            other.deadline = min(other.deadline, inc.deadline) if other.deadline is not None else inc.deadline
        other.confidence = max(other.confidence, inc.confidence)
        om.sources |= m.sources
        om.last_report_t = max(om.last_report_t, m.last_report_t)
        om.life_threat, om.reserved = om.life_threat or m.life_threat, om.reserved or m.reserved
        om.heat, om.minors = om.heat or m.heat, om.minors or m.minors
        om.threat = om.threat or m.threat
        om.count = max(om.count, m.count)
        om.seen_on_scene = om.seen_on_scene or m.seen_on_scene
        om.contradicted = om.contradicted or m.contradicted
        om.excluded |= m.excluded
        om.avoid |= m.avoid
        om.vetoed |= m.vetoed
        om.sigs |= m.sigs
        if inc.id in self.points and other.id not in self.points:
            self.points[other.id] = self.points[inc.id]
        om.missing = [x for x in om.missing if x != "identity" and (x != "zone" or not other.zone)]
        m.missing = [x for x in m.missing if x != "identity"]
        times = [t for t in (om.first_action_t, m.first_action_t) if t is not None]
        om.first_action_t = min(times) if times else None
        for rid in inc.assigned:
            _, need = self.assign[rid]
            self.assign[rid] = (other.id, need)
            if rid not in other.assigned:
                other.assigned.append(rid)
        inc.assigned.clear()  # _close no debe soltar una reserva que ahora pertenece al incidente canónico
        if other.assigned:
            other.status = IncidentStatus.IN_PROGRESS if om.seen_on_scene else IncidentStatus.ASSIGNED
        source_plan = self.live_plans.get(m.plan or "")
        target_plan = self.live_plans.get(om.plan or "")
        if source_plan is not None:
            for assumption in source_plan.assumptions:
                if assumption.check.get("incident") == inc.id:
                    assumption.check["incident"] = other.id
            if target_plan is not None:
                target_plan.assumptions.extend(source_plan.assumptions)
                target_plan.steps.extend(source_plan.steps)
            else:
                self.plan_incident[source_plan.id] = other.id
                om.plan, m.plan = source_plan.id, None
        m.merged_into = other.id
        inc.needs.clear()
        inc.notes.append(f"Identidad confirmada por {a.id}: duplicado de {other.id}")
        other.notes.append(f"Identidad confirmada por {a.id}: incorpora {inc.id}")
        self.counters["merges"] += 1
        self._emit(ActionKind.MERGE, other, f"{a.id} confirma que {inc.id} es la misma persona que {other.id}; "
                   "se elimina la demanda redundante y se conservan los equipos en curso",
                   params={"merged": inc.id, "identity_answer": a.id, "reports": list(other.reports)},
                   status=ActionStatus.DONE)
        self._close(inc, IncidentStatus.RESOLVED, f"identidad confirmada: duplicado de {other.id}, no alta de la víctima")
        om.dirty = f"identidad confirmada por {a.id}: demanda reconciliada con {inc.id}"

    def _on_point(self, a: Action, inc: Incident, point: str) -> None:
        """Quien avisó da un punto concreto: se le pasa al equipo que va de camino (o que ya está buscando)."""
        if not point:
            self._log("outcome", f"Respuesta a {a.id}: quien avisó no sabe dar un punto concreto", a.id, incident=inc.id)
            return
        self.points[inc.id] = point
        told = []
        for rid in inc.assigned:
            r = self.resources.get(rid)
            if r is not None and r.status == ResourceStatus.EN_ROUTE:
                told.append(r.name)
                self._emit(ActionKind.NOTIFY, inc, f"punto concreto para {r.name}: junto a {point}", resource=rid,
                           channel=Channel.VOICE, params={"to": rid, "point": point, "about": inc.id,
                                                          "message": f"La persona está junto a {point}."})
        self._param("require_precise_location", inc.zone, f"{inc.id}: quien avisó dice «junto a {point}»"
                    + (f"; se le pasa a {', '.join(told)}" if told else "; queda apuntado para el equipo que salga"), incident=inc.id)

    def _fold_duplicate(self, inc: Incident) -> bool:
        """Al saber por fin dónde (o qué) es, puede resultar que ya se estaba atendiendo: se funde, no se duplica."""
        m = self.meta[inc.id]
        if inc.assigned or not inc.zone or inc.family == Family.MEDICAL:
            return False
        for other in self.live:
            om = self.meta[other.id]
            if other is inc or other.zone != inc.zone or om.origin == "pattern":
                continue
            if other.type == inc.type or om.group == m.group:
                other.reports.extend(r for r in inc.reports if r not in other.reports)
                other.confidence = round(max(other.confidence, inc.confidence), 2)
                om.last_report_t = self.t
                self.counters["merges"] += 1
                self._emit(ActionKind.MERGE, other, f"{inc.id} resulta ser el mismo incidente que {other.id} "
                           f"({label(other)}{self._where(other)}): se funden y no se manda otro equipo",
                           params={"merged": inc.id, "reports": list(other.reports)}, status=ActionStatus.DONE)
                inc.notes.append(f"duplicado de {other.id}")
                self._close(inc, IncidentStatus.RESOLVED, f"era un duplicado de {other.id}")
                return True
        return False

    def _observe_resources(self) -> None:
        resources, moving = self.resources, self._moving
        for rid, (iid, _) in list(self.assign.items()):
            r = resources.get(rid)
            if r is None:
                continue
            if r.status in (ResourceStatus.EN_ROUTE, ResourceStatus.BUSY):
                if r.status == ResourceStatus.BUSY:
                    self._on_scene_since.setdefault(rid, self.t)
                if rid not in moving:
                    moving.add(rid)
                    if rid in self._dispatch_of:
                        self.accepted.add(self._dispatch_of[rid])
            elif r.status == ResourceStatus.AVAILABLE and rid in moving:
                inc = self.incidents[iid]
                self._drop_resource(inc, rid, exclude=False)
                if inc.status not in CLOSED and self.meta[iid].seen_on_scene and not inc.assigned \
                        and not self._still_crowded(inc, f"{r.name} termina"):
                    self._close(inc, IncidentStatus.RESOLVED, f"{r.name} termina y vuelve a estar libre")
        t = self.t
        for inc in list(self.live):
            m = self.meta[inc.id]
            if inc.assigned or m.hold or m.ask:
                continue
            z = self.zones.get(inc.zone) if inc.zone else None
            if inc.family == Family.CROWD and z is not None and z.capacity and m.plan and t - inc.t_open >= 5 \
                    and z.occupancy < CROWD_CLEAR * z.capacity and inc.type != "lost_child":
                self._close(inc, IncidentStatus.RESOLVED, f"{z.name} baja al {round(z.occupancy / z.capacity * 100)} %")
            elif t - m.last_report_t >= QUIET_MIN and m.plan and inc.id not in self._waiting \
                    and not any(self.actions[s].status in _PENDING for s in self.plans[m.plan].steps):
                self._close(inc, IncidentStatus.RESOLVED, f"{QUIET_MIN} min sin novedades y sin nada pendiente")

    def _still_crowded(self, inc: Incident, why: str) -> bool:
        """Una aglomeración que se sigue VIENDO no se cierra porque el equipo haya terminado: queda en gestión de flujo."""
        z = self.zones.get(inc.zone) if inc.zone else None
        if inc.family != Family.CROWD or inc.type == "lost_child" or z is None or not z.capacity \
                or z.occupancy < CROWD_CLEAR * z.capacity:
            return False
        if inc.needs:
            inc.needs = {}
            self._waiting.pop(inc.id, None)
            self._log("incident", f"{inc.id}: {why}, pero {z.name} sigue al {round(z.occupancy / z.capacity * 100)} %: "
                      "se mantiene abierto solo con gestión de flujo", inc.id)
        return True

    def _close(self, inc: Incident, status: IncidentStatus, why: str) -> None:
        if inc.status in CLOSED:
            return
        m = self.meta[inc.id]
        inc.status = status
        self._closed_t[inc.id] = self.t
        if inc in self.live:
            self.live.remove(inc)
        self._waiting.pop(inc.id, None)
        m.dirty, m.hold = None, False
        if m.plan in self.live_plans:
            del self.live_plans[m.plan]
        for a in [a for a in self.actions.values() if a.incident == inc.id and a.status in _PENDING]:
            a.status = ActionStatus.CANCELLED
            self._inflight.pop(a.id, None)
        if status == IncidentStatus.FALSE_ALARM:
            self.counters["false_alarms"] += 1
            self._emit(ActionKind.DISMISS, inc, f"Falsa alarma {inc.id} ({label(inc)}{self._where(inc)}): {why}",
                       params={"reports": list(inc.reports)}, status=ActionStatus.DONE)
        else:
            self.counters["resolved"] += status == IncidentStatus.RESOLVED
            self._log("incident", f"{inc.id} {'resuelto' if status == IncidentStatus.RESOLVED else 'FALLIDO'}: {why}", inc.id)
        # se deshace lo que Mando dejó puesto para este incidente: desvíos y restricciones no se quedan huérfanos
        if inc.zone in self.reroutes and not any(i.zone == inc.zone and i.family == Family.CROWD for i in self.live):
            self._emit(ActionKind.REROUTE, inc, f"{inc.id} cerrado: se retira el desvío {inc.zone} → {self.reroutes[inc.zone]}",
                       zone=inc.zone, params={"cancel": True})
        for zid in [z for z, iid in self.restricted.items() if iid == inc.id]:
            if self.zones.get(zid) is not None and self.zones[zid].state == "restricted":
                self._emit(ActionKind.SET_ZONE, inc, f"{inc.id} cerrado: {zid} vuelve a abrirse", zone=zid,
                           params={"state": "open"})
            self.restricted.pop(zid, None)
        for rid in list(inc.assigned):
            r = self.resources.get(rid)
            if status == IncidentStatus.FALSE_ALARM and r is not None and r.status == ResourceStatus.EN_ROUTE:
                self._emit(ActionKind.RECALL, inc, f"{r.name} vuelve: era una falsa alarma", resource=rid, zone=inc.zone,
                           channel=Channel.VOICE, params={"message": "Falsa alarma, volved a vuestra posición."})
                self.counters["wasted_dispatches"] += 1
            self._drop_resource(inc, rid, exclude=False)

    # ================================================================ 5 · planificar
    def _allocate(self, todo: list[Incident]) -> None:
        """Reparto GLOBAL de los recursos libres entre todos los incidentes que piden: no gana el primero que llega.
        Se sirve primero a los de riesgo vital y luego por prioridad; entre los servidos se minimiza la suma de
        prioridad × minutos de llegada. El que se queda sin recurso queda explicado (`fronts[].why_waiting`)."""
        self._reserved_for = {}
        demands: dict[str, list[Incident]] = {}
        for inc in todo:
            m = self.meta[inc.id]
            if not inc.zone or inc.zone not in self.zones or m.hold or ("type" in m.missing and not m.life_threat) \
                    or ("zone" in m.missing and not m.sitewide):
                continue
            have: dict[str, int] = {}
            for rid in inc.assigned:
                k = self.assign.get(rid, (None, ""))[1]
                have[k] = have.get(k, 0) + 1
            for kind, n in inc.needs.items():
                if kind == "ambulance" and inc.confidence < 0.5:
                    continue
                demands.setdefault(kind, []).extend([inc] * max(0, n - have.get(kind, 0)))
        waits: dict[str, str] = {}
        for kind, slots in demands.items():
            free = [r for r in self.resources.values() if str(r.kind) == kind and r.status == ResourceStatus.AVAILABLE
                    and r.id not in self.assign]
            if len(slots) < 2 and free:
                continue   # sin competencia: lo resuelve el planificador con el mejor por ETA
            slots.sort(key=lambda i: (not self.meta[i.id].life_threat, *priority.sort_key(i)))
            served, unserved = slots[:len(free)], slots[len(free):]
            going: dict[str, tuple[str, float]] = {}    # recurso -> (incidente al que va este tick, minutos de llegada)
            if len(served) >= 2:
                eta = {i.id: {z: v[0] for z, v in self.planner.travel.to_zone(
                    i.zone, self.zones, kind == "ambulance", self.meta[i.id].avoid).items()} for i in served}

                pen = {r.id: self.params.contact_penalty(kind, r.id) if self.params is not None else 0.0 for r in free}

                def cost(order: tuple) -> float:
                    return sum(i.priority * (eta[i.id].get(r.zone, WAIT_COST_MIN) + pen[r.id] if r.id not in self.meta[i.id].excluded
                                             else WAIT_COST_MIN) for i, r in zip(served, order))
                pool = free if len(free) <= 6 else free[:6]
                best = min(permutations(pool, len(served)), key=lambda o: (cost(o), [r.id for r in o])) \
                    if len(served) <= len(pool) else tuple(pool)
                for i, r in zip(served, best):
                    self._reserved_for.setdefault((i.id, kind), []).append(r.id)
                    going[r.id] = (i.id, eta[i.id].get(r.zone, 3.0))
            for i in unserved:
                self._reserved_for.setdefault((i.id, kind), [])
                waits.setdefault(i.id, self._why_wait(i, kind, going))
        for iid, text in waits.items():
            if self._why_waits.get(iid) != text:
                self._why_waits[iid] = text
                self._log("plan", text, iid, incident=iid, waiting=True)
        for iid in [i for i in self._why_waits if i not in waits and (self.incidents[i].assigned or self.incidents[i].status in CLOSED)]:
            del self._why_waits[iid]

    def _why_wait(self, inc: Incident, kind: str, going: dict[str, tuple[str, float]] | None = None) -> str:
        m = self.meta[inc.id]
        text = (f"{inc.id} espera {KIND_ES.get(kind, kind)}: prioridad {es(inc.priority)}, "
                + ("RIESGO VITAL: se retira un equipo a otro incidente" if m.life_threat else "sin riesgo vital"))
        soonest = None
        for rid, (iid, k) in self.assign.items():
            r = self.resources.get(rid)
            if r is None or str(r.kind) != kind or iid == inc.id:
                continue
            left = r.eta + max(0, SERVICE_EST_MIN - (self.t - self._on_scene_since.get(rid, self.t)))
            if soonest is None or left < soonest[0]:
                soonest = (left, r, iid)
        for rid, (iid, minutes) in (going or {}).items():   # los que salen en este mismo tick hacia otro incidente
            left = round(minutes) + SERVICE_EST_MIN
            if soonest is None or left < soonest[0]:
                soonest = (left, self.resources[rid], iid)
        if soonest is not None:
            text += f"; le llega {soonest[1].name} en ~{soonest[0]} min, cuando acabe {soonest[2]}"
        else:
            text += f"; no hay ningún equipo de {KIND_ES.get(kind, kind)} en servicio"
        return text

    @property
    def reserved_for(self) -> dict[tuple[str, str], list[str]]:
        return self._reserved_for

    def _plan_dirty(self) -> None:
        if self._waiting:
            free = {str(r.kind) for r in self.resources.values()
                    if r.status == ResourceStatus.AVAILABLE and r.id not in self.assign}
            for iid, kinds in list(self._waiting.items()):
                if any(k in free or (k == "medical" and "ambulance" in free) for k in kinds):
                    self.meta[iid].dirty = self.meta[iid].dirty or "se libera un recurso que hacía falta"
        todo = [i for i in self.live if self.meta[i.id].dirty and i.status not in CLOSED]
        if todo:
            self._allocate(todo)
        for inc in todo:
            m = self.meta[inc.id]
            if not m.dirty or inc.status in CLOSED:
                continue
            reason, m.dirty = m.dirty, None
            if m.replans >= MAX_REPLANS and m.broken:
                if not m.gave_up:
                    m.gave_up = True
                    self._emit(ActionKind.NOTIFY, inc, f"{MAX_REPLANS} planes seguidos no han funcionado en {inc.id}: "
                               "Mando deja de insistir y pide una decisión humana", channel=Channel.OPERATOR,
                               params={"to": "operator", "escalate": True, "message": f"Decide tú sobre {inc.id}."})
                continue
            adj = self._adjust(inc)
            draft = self.planner.build(inc, m, self, adj)
            if draft is None and not m.broken:
                if not m.queued_logged and inc.needs and not inc.assigned:
                    m.queued_logged = True
                    self._waiting[inc.id] = list(inc.needs)
                    self._log("plan", f"{inc.id} en cola: no hay recurso libre ni incidente menos prioritario al que quitárselo", inc.id)
                continue
            self._register(inc, m, draft or Draft(objective=f"{label(inc).capitalize()}{self._where(inc)}"), reason)

    def _register(self, inc: Incident, m: IncidentMeta, d: Draft, reason: str) -> None:
        old = self.plans.get(m.plan or "")
        plan = Plan(id=self.new_id("P"), t=self.t, objective=d.objective, supersedes=old.id if old else None)
        steps = [s for s in self._carry.pop(inc.id, []) if self.actions[s].status in _PENDING]
        if old is not None:
            # lo que seguía siendo cierto del plan anterior sigue vigilándose en el nuevo
            for s in old.assumptions:
                c = s.check
                if not s.holds or c["kind"] == "incident_improving" or c.get("zone") in m.avoid \
                        or c.get("resource") in m.excluded or (c["kind"] == "action_accepted_within" and c["action"] in self.accepted) \
                        or (c.get("resource") and c["resource"] not in inc.assigned):
                    continue
                if c["kind"] == "route_clear":
                    c["zones"] = [z for z in c["zones"] if z not in m.avoid]
                plan.assumptions.append(s)
            self.live_plans.pop(old.id, None)
            m.replans += 1
            self.counters["replans"] += 1
        plan.assumptions.extend(d.assumptions)
        parts = [reason] if old is not None else []
        parts += d.notes
        if not d.actions and old is not None:
            parts.append("no hay alternativa automática mejor: se mantiene lo ya lanzado")
        plan.why = "; ".join(x for x in parts if x) or "primer plan"
        self.plans[plan.id], self.plan_incident[plan.id] = plan, inc.id
        self.live_plans[plan.id] = plan
        self.review_at[plan.id] = self.t + d.review_min
        m.plan, m.broken, m.queued_logged = plan.id, None, False
        if d.unmet:
            self._waiting[inc.id] = list(d.unmet)
        else:
            self._waiting.pop(inc.id, None)

        for line in d.rehearsals:
            self._log("plan", line, plan.id, incident=inc.id, rehearsal=True)
        head = f"Plan {plan.id} para {inc.id}" if old is None else f"Plan {plan.id} SUSTITUYE a {old.id} ({inc.id})"
        quiet = old is not None and not d.actions and m.broken_kind == "incident_improving" and len(m.review_times) > 1
        if not quiet:   # una revisión repetida que no cambia nada ya está contada en su línea agrupada
            self._log("plan", f"{head}: {d.objective}. Porque: {plan.why}. {len(d.actions)} pasos, "
                      f"{len(plan.assumptions)} supuestos, reevaluar en {d.review_min} min", plan.id,
                      incident=inc.id, supersedes=plan.supersedes,
                      assumptions=[s.text for s in plan.assumptions])
        m.broken_kind = None
        for lid, what in d.lessons:
            if lid:
                self._lesson(lid, inc, what)
        for param, key, what in d.params:
            self._param(param, key, what, incident=inc.id)
        for a in d.actions:
            self._launch(a, inc)
            steps.append(a.id)
        plan.steps = steps
        for rid, victim_id in d.recalls:
            self._after_recall(rid, victim_id, inc)

    def _after_recall(self, rid: str, victim_id: str, winner: Incident) -> None:
        victim, vm = self.incidents[victim_id], self.meta[victim_id]
        self.counters["recalls"] += 1
        self.recall_until[rid] = self.t + RECALL_COOLDOWN
        if rid in victim.assigned:
            victim.assigned.remove(rid)
        self._moving.discard(rid)
        recall = next((a for a in reversed(self.actions.values())
                       if a.kind == ActionKind.RECALL and a.resource == rid), None)
        old = self.live_plans.pop(vm.plan or "", None)
        if old is not None:
            old.invalidated_by = f"recall:{recall.id if recall else rid}"
        if not victim.assigned:
            victim.status = IncidentStatus.OPEN
        vm.dirty = f"{rid} se fue a {winner.id}, más prioritario ({es(winner.priority)} frente a {es(victim.priority)})"

    def _launch(self, a: Action, inc: Incident | None) -> None:
        """Registra una acción: autonomía, tarjeta de decisión si espera aprobación, log, y envío si hay que hablar."""
        zone = self.zones.get(a.zone or "")
        autonomy.gate(a, zone.kind if zone else None)
        if a.autonomy == Autonomy.APPROVE:
            self._decision_card(a, inc)
        self.actions[a.id] = a
        self._out.append(a)
        if a.status not in _TERMINAL:
            self._inflight[a.id] = a.status
        m = self.meta.get(inc.id) if inc is not None else None
        if a.kind == ActionKind.DISPATCH or a.kind == ActionKind.RESUPPLY:
            if a.resource:
                self._dispatch_of[a.resource] = a.id
            if inc is not None and inc.status == IncidentStatus.OPEN:
                inc.status = IncidentStatus.ASSIGNED
        elif a.kind == ActionKind.REROUTE and a.zone:
            if a.params.get("cancel"):
                self.reroutes.pop(a.zone, None)
            elif a.params.get("to"):
                self.reroutes[a.zone] = a.params["to"]
        elif a.kind == ActionKind.SET_ZONE and a.zone:
            if a.params.get("state") == "restricted" and inc is not None:
                self.restricted[a.zone] = inc.id
            else:
                self.restricted.pop(a.zone, None)
        elif a.kind == ActionKind.ASK:
            self.counters["asks"] += 1
        if m is not None and m.first_action_t is None and a.kind not in (ActionKind.MERGE, ActionKind.DISMISS):
            m.first_action_t = self.t
        if self.memory is not None:
            self.memory.on_preparation(a, inc)
        target = a.resource or a.params.get("to") or a.zone or ""
        if a.autonomy == Autonomy.APPROVE:
            self.counters["approvals"] += 1
            card = a.params["decision_card"]
            self._log("approval", f"PIDE DECISIÓN {a.id} a {card['addressee']}: {a.why} [{autonomy.card_line(card)}; "
                      f"si no contesta, en {card['escalate_at'] - self.t} min sube a {card['deputy']}]", a.id,
                      incident=a.incident, reserved=self._is_reserved(inc))
            return
        self._log("action", f"{str(a.kind).upper()}" + (f" → {target}" if target else "") + f": {a.why}", a.id,
                  incident=a.incident)
        self._send(a)

    def _is_reserved(self, inc: Incident | None) -> bool:
        return inc is not None and self.meta[inc.id].reserved

    def _decision_card(self, a: Action, inc: Incident | None) -> None:
        """Las dos ramas (si aprueba / si veta) ensayadas en el gemelo, a quién va, ventana y escalada al suplente."""
        approved = vetoed = None
        flow = a.kind in (ActionKind.STOP_SHOW, ActionKind.EVACUATE, ActionKind.SET_ZONE, ActionKind.BROADCAST, ActionKind.REROUTE)
        watch = [z for z in dict.fromkeys([a.zone or (inc.zone if inc else None), a.params.get("to")]) if z in self.zones]
        if a.kind == ActionKind.STOP_SHOW:
            watch += [z.id for z in self.zones.values() if z.kind == "stage_front" and z.id not in watch]
        if flow and watch and self.rehearsal.available:
            # lo que este tick ya se ha lanzado solo para el mismo incidente entra en las dos ramas
            context = [x for x in self._out if x is not a and x.incident == a.incident and x.status == ActionStatus.EXECUTING
                       and x.kind in (ActionKind.SET_ZONE, ActionKind.REROUTE, ActionKind.DISPATCH)]
            vetoed = self.rehearsal.run("si no", context, watch)
            approved = self.rehearsal.run("si se aprueba", context + [a], watch)
        m = self.meta.get(inc.id) if inc is not None else None
        a.params["decision_card"] = autonomy.decision_card(a, inc, self.t, approved, vetoed,
                                                           life_threat=bool(m and m.life_threat))

    def _escalate_cards(self) -> None:
        """Nadie contesta: la decisión sube al suplente de la cadena de mando y queda escrito quién tardó cuánto."""
        for a in list(self.actions.values()):
            if a.status != ActionStatus.AWAITING_APPROVAL:
                continue
            card = a.params.get("decision_card")
            if not card or card.get("escalated_at") is not None or self.t < card["escalate_at"]:
                continue
            card["escalated_at"] = self.t
            self.counters["escalations"] += 1
            inc = self.incidents.get(a.incident or "")
            self._emit(ActionKind.NOTIFY, inc, f"{card['addressee']} lleva {self.t - card['asked_at']} min sin contestar a {a.id} "
                       f"(«{a.kind}»): sube a {card['deputy']}", zone=a.zone, channel=Channel.VOICE,
                       params={"to": card["deputy"], "escalate": True, "about": a.id,
                               "message": f"Decisión pendiente {a.id}: {a.params.get('reason', a.why)} {autonomy.card_line(card)}"})

    def _send(self, a: Action) -> None:
        if a.kind in _TALK and a.status == ActionStatus.EXECUTING:
            if self.memory is not None:
                self.memory.on_sent(a, self.resources.get(a.resource or ""))
            if self.comms is not None:
                self.comms.send(a, self.resources.get(a.resource or ""))

    def _emit(self, kind: ActionKind, inc: Incident | None, why: str, *, resource: str | None = None,
              zone: str | None = None, channel: Channel | None = None, params: dict[str, Any] | None = None,
              status: ActionStatus | None = None) -> Action:
        """Acción suelta, fuera de un plan (MERGE, DISMISS, avisos al coordinador, reenvíos)."""
        a = Action(id=self.new_id("A"), kind=kind, t=self.t, incident=inc.id if inc else None, resource=resource,
                   zone=zone or (inc.zone if inc else None), params=params or {}, why=why, channel=channel)
        if status is not None:  # contabilidad interna: nace terminada
            a.status = status
            self.actions[a.id] = a
            self._out.append(a)
            self._log("action", why if kind in (ActionKind.MERGE, ActionKind.DISMISS) else f"{str(kind).upper()}: {why}",
                      a.id, incident=a.incident)
            return a
        self._launch(a, inc)
        return a
