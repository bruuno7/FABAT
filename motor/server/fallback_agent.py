"""Agente de RELLENO. Solo se usa si `motor.mando` no se puede importar: mantiene viva la pantalla
detrás del mismo contrato (`AgentAPI`). No es Mando: un aviso con zona = un incidente, manda el recurso
libre del tipo que sugiere el texto y pide aprobación para evacuar si una zona pasa de 6,5 personas/m².
"""
from __future__ import annotations

from typing import Any

from motor.contracts import (Action, ActionKind, ActionStatus, Assumption, Autonomy, Channel, Incident, IncidentStatus,
                             Family, LogEntry, Observation, Plan, ResourceStatus)

_WORDS = [(("inconsciente", "desmay", "no respira", "collapsed", "sangr", "convuls", "calor"), Family.MEDICAL, "medical", 8),
          (("pelea", "agres", "arma", "acos", "fight"), Family.AGGRESSION, "security", 6),
          (("humo", "fuego", "luz", "valla", "roto"), Family.INFRA, "tech", 6),
          (("agua",), Family.SUPPLY, "logistics", 5),
          (("gente", "atasc", "aplast", "empuj", "agobi"), Family.CROWD, "security", 7)]


class FallbackAgent:
    name = "relleno"

    def __init__(self, playbook: Any = None, comms: Any = None, parser: Any = None) -> None:
        self.comms = comms
        self.incidents: dict[str, Incident] = {}
        self.plans: dict[str, Plan] = {}
        self.actions: dict[str, Action] = {}
        self.log: list[LogEntry] = []
        self._approved: list[Action] = []
        self._n = 0
        self.t = 0

    def _id(self, p: str) -> str:
        self._n += 1
        return f"{p}-{self._n:04d}"

    def tick(self, obs: Observation) -> list[Action]:
        self.t = obs.t
        out, self._approved = list(self._approved), []
        if self.comms is not None:
            self.comms.poll(obs.t)
        busy = {a.resource for a in self.actions.values() if a.status == ActionStatus.EXECUTING}
        for rep in obs.new_reports:
            zone = rep.zone_hint
            text = rep.text.lower()
            fam, need, sev = next(((f, n, s) for words, f, n, s in _WORDS if any(w in text for w in words)),
                                  (Family.INFO, "security", 4))
            same = next((i for i in self.incidents.values() if i.zone == zone and i.family == fam
                         and i.status not in (IncidentStatus.RESOLVED, IncidentStatus.FALSE_ALARM)), None)
            if same is not None:
                same.reports.append(rep.id)
                self.log.append(LogEntry(obs.t, "incident", f"Aviso {rep.id} fusionado con {same.id}", same.id))
                continue
            inc = Incident(self._id("M"), fam, "sin_clasificar", zone, sev, obs.t, needs={need: 1}, reports=[rep.id],
                           priority=float(sev), confidence=0.5 if zone is None else 0.8)
            self.incidents[inc.id] = inc
            self.log.append(LogEntry(obs.t, "incident", f"Nuevo incidente {inc.id}: «{rep.text[:60]}»", inc.id))
            if zone is None:
                continue
            r = next((r for r in obs.resources.values() if str(r.kind) == need
                      and r.status == ResourceStatus.AVAILABLE and r.id not in busy), None)
            if r is None:
                continue
            busy.add(r.id)
            a = Action(self._id("A"), ActionKind.DISPATCH, obs.t, inc.id, r.id, zone, {"reports": [rep.id]},
                       Autonomy.AUTO, ActionStatus.EXECUTING, f"{r.name} es el recurso libre de tipo {need}", Channel.VOICE)
            plan = Plan(self._id("P"), obs.t, f"Atender {inc.id} en {zone}", [a.id],
                        [Assumption(self._id("S"), f"{r.name} sigue disponible", {"kind": "resource_status_is", "resource": r.id})],
                        why="agente de relleno: primer recurso libre")
            self.actions[a.id], self.plans[plan.id] = a, plan
            inc.assigned.append(r.id)
            inc.status = IncidentStatus.ASSIGNED
            self.log.append(LogEntry(obs.t, "action", f"DISPATCH → {r.id}: {a.why}", a.id))
            if self.comms is not None:
                self.comms.send(a, r)
            out.append(a)
        for z in obs.zones.values():
            if z.density > 6.5 and not any(a.kind == ActionKind.EVACUATE and a.zone == z.id for a in self.actions.values()):
                a = Action(self._id("A"), ActionKind.EVACUATE, obs.t, None, None, z.id, {}, Autonomy.APPROVE,
                           ActionStatus.AWAITING_APPROVAL, f"¿EVACUAR {z.name}? Densidad {z.density:.1f} personas/m²")
                self.actions[a.id] = a
                self.log.append(LogEntry(obs.t, "approval", f"PIDE APROBACIÓN {a.id}: {a.why}", a.id))
                out.append(a)
        for res in obs.action_results:
            mine = self.actions.get(res.id)
            if mine is not None:
                mine.status = res.status
        return out

    def approve(self, action_id: str, ok: bool, note: str = "") -> None:
        a = self.actions.get(action_id)
        if a is None or a.status != ActionStatus.AWAITING_APPROVAL:
            return
        a.status = ActionStatus.EXECUTING if ok else ActionStatus.REJECTED
        if ok:
            self._approved.append(a)
        self.log.append(LogEntry(self.t, "approval", f"La persona {'APRUEBA' if ok else 'VETA'} {a.id}" + (f": {note}" if note else ""), a.id))

    def snapshot(self) -> dict[str, Any]:
        return {"t": self.t, "incidents": [i.to_dict() for i in self.incidents.values()],
                "plans": [dict(p.to_dict(), live=True) for p in self.plans.values()],
                "actions": [a.to_dict() for a in self.actions.values()],
                "log": [e.to_dict() for e in self.log], "lessons": {}, "counters": {}}
