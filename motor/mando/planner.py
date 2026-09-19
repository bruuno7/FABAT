"""Planificador: de un incidente a un `Plan` con pasos y SUPUESTOS escritos.

Reglas de la casa:
- Si falta un dato imprescindible (zona, qué pasa, confirmación), el primer paso es ASK, no DISPATCH.
- Recurso: el de mejor ETA entre los libres del tipo necesario. Si no hay y el incidente es más
  prioritario que otro ya atendido (por un margen, para no oscilar), RECALL al de menor prioridad.
- Antes de un REROUTE se PROYECTA la ocupación del destino; se elige el de más margen y, aun así, el
  supuesto queda escrito porque la proyección puede fallar.
- Todo plan lleva «reevaluar en N minutos» como supuesto `incident_improving`: si la acción no
  funcionó, se replanifica subiendo un escalón.
"""
from __future__ import annotations

import heapq
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..contracts import (Action, ActionKind, Assumption, Autonomy, Channel, Family, Incident, Resource, ResourceKind,
                         ResourceStatus, Zone)
from .assumptions import metric
from .playbook import Adjustments
from .autonomy import level as autonomy_level
from .lexicon import TypeSpec, spec_for
from .triage import CONFIRM_BELOW, IncidentMeta

HOP_MIN = 2              # minutos por salto si no hay tiempos de tránsito
ACCEPT_MIN = 3           # minutos para que el equipo acepte antes de pasar al siguiente
REVIEW_MIN = 5           # «reevaluar en N minutos»
RECALL_MARGIN = 1.5      # diferencia de prioridad mínima para quitarle un recurso a otro incidente
RECALL_COOLDOWN = 5      # minutos en los que un recurso recién retirado no se vuelve a retirar
DEST_RATIO = 0.85        # el destino de un desvío debe quedar por debajo de este % de su capacidad
PROJECTION_MIN = 10      # horizonte de la proyección de ocupación
AMB_DENSITY = 1.5        # la ambulancia no cruza público por encima de esta densidad (festival.json manda si existe)
FOOT_DENSITY = 5.5       # a pie se avanza, pero a paso de tortuga
SLOW = ((2.0, 1.0), (4.0, 1.5), (5.5, 2.5), (99.0, 4.0))   # densidad → factor de lentitud
WIND_STOP = 70.0
RESUPPLY_MIN = 5         # minutos que tarda en rellenarse un punto de agua una vez llega logística
QUEUE_WALK = 0.05        # fracción de la cola de una puerta que se va andando por minuto a la puerta de desvío
ALLOW_SPLIT = False      # repartir entre dos destinos; apagado porque el simulador guarda un solo desvío por origen

SUBSTITUTES = {"medical": ("ambulance",)}
_NO_REROUTE_TO = ("medical", "backstage", "pmr", "vip", "toilets", "water")
_SPEAK = (Channel.VOICE, Channel.SMS, Channel.WHATSAPP, Channel.RADIO)

LABEL = {
    "cardiac_arrest": "posible parada cardiaca", "unconscious_person": "persona inconsciente",
    "breathing_difficulty": "persona que no puede respirar", "fainting": "desmayo", "seizure": "convulsiones",
    "allergic_reaction": "reacción alérgica", "heat_stroke": "golpe de calor", "intoxication": "intoxicación",
    "injury": "persona herida", "dizziness": "mareo", "crush_risk": "riesgo de aplastamiento",
    "crowd_surge": "aglomeración con empujones", "gate_saturation": "puerta saturada", "bottleneck": "embudo",
    "lost_child": "menor perdido", "storm": "tormenta", "high_wind": "rachas de viento", "heavy_rain": "lluvia intensa",
    "heat_wave": "calor extremo", "weapon": "arma vista", "sexual_assault": "agresión sexual o acoso", "fight": "pelea",
    "theft": "robo", "water_out": "agua agotada", "water_low": "agua a punto de agotarse", "fuel_shortage": "falta combustible",
    "medical_supplies": "falta material médico", "food_shortage": "comida agotada", "fire": "fuego o humo",
    "structure_risk": "estructura en riesgo", "power_outage": "apagón", "network_down": "red caída",
    "sound_failure": "fallo de sonido", "toilets_failure": "baños inutilizados", "payment_down": "pago caído",
    "resource_down": "recurso propio con problemas", "suspicious_object": "objeto sospechoso",
    "transport_cut": "corte de transporte", "artist_delay": "retraso o cancelación del artista", "drone": "dron",
    "heat_cluster": "patrón: varios casos por calor", "intox_cluster": "patrón: varias intoxicaciones",
    "aggression_cluster": "patrón: agresiones repetidas",
    "unknown_medical": "aviso médico sin tipo reconocido", "unknown_crowd": "aviso de multitud sin tipo reconocido",
    "unknown_weather": "aviso meteorológico sin tipo reconocido", "unknown_aggression": "aviso de agresión sin tipo reconocido",
    "unknown_supply": "aviso de suministros sin tipo reconocido", "unknown_infra": "aviso de infraestructura sin tipo reconocido",
    "unknown_resource": "aviso sobre un recurso propio sin tipo reconocido", "unknown_info": "aviso sin aclarar",
    "unknown_external": "aviso externo o amenaza sin tipo reconocido", "unknown": "aviso sin aclarar",
}
ROLE_ES = {"security_lead": "el jefe de seguridad", "medical_lead": "la coordinación médica", "production": "producción",
           "violet_point": "el punto violeta", "coordinator": "el coordinador", "gates": "el personal de puertas",
           "all_leads": "todos los responsables", "stage_manager": "el regidor", "health_authority": "la autoridad sanitaria"}
SERVICE_ES = {"ambulance": "una ambulancia del 112", "police": "la policía", "fire": "los bomberos",
              "transport": "el operador de transporte", "medical": "refuerzo sanitario externo"}
KIND_ES = {"security": "seguridad", "medical": "equipo médico", "ambulance": "ambulancia", "tech": "técnicos",
           "logistics": "logística", "volunteer": "voluntarios"}


def es(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def label(inc: Incident) -> str:
    return LABEL.get(inc.type, inc.type.replace("_", " "))


# -------------------------------------------------------------------- tiempos de tránsito

class Travel:
    """Tiempos entre zonas. Usa `motor/world/festival.json` (aristas con minutos) si existe; si no,
    saltos por `Zone.neighbors`. Entrar en una zona densa cuesta más; la ambulancia no entra si
    la densidad pasa de 4/m²."""

    def __init__(self, festival: str | Path | None = None) -> None:
        self.minutes: dict[tuple[str, str], float] = {}
        self.entry: dict[str, float] = {}     # personas/min que descargan los tornos de cada puerta (plan de aforo)
        self.adjacent: dict[str, list[str]] = {}   # incluye las vías de servicio (solo personal), que `neighbors` no trae
        self.no_vehicles: set[str] = set()         # zonas que la ambulancia no cruza (sí entra si es su destino, a pie)
        self.roles: dict[str, str] = {}            # recurso -> cargo («Jefe de seguridad de sector (foso)»)
        self.amb_density = AMB_DENSITY
        path = Path(festival) if festival else Path(__file__).parent.parent / "world" / "festival.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for e in data.get("edges", []):
                self.minutes[(e["a"], e["b"])] = self.minutes[(e["b"], e["a"])] = float(e["minutes"])
                self.adjacent.setdefault(e["a"], []).append(e["b"])
                self.adjacent.setdefault(e["b"], []).append(e["a"])
            self.entry = {z["id"]: float(z["entry_per_min"]) for z in data.get("zones", []) if z.get("entry_per_min")}
            self.no_vehicles = {z["id"] for z in data.get("zones", []) if z.get("vehicle_transit") is False}
            self.roles = {r["id"]: r["role"] for r in data.get("resources", []) if r.get("role")}
            self.amb_density = float(data.get("params", {}).get("amb_max_density", AMB_DENSITY))
        except (OSError, ValueError, KeyError, TypeError):
            self.minutes, self.entry, self.adjacent = {}, {}, {}

    @staticmethod
    def _slow(density: float) -> float:
        for limit, factor in SLOW:
            if density < limit:
                return factor
        return 4.0

    def to_zone(self, dest: str, zones: dict[str, Zone], ambulance: bool = False,
                avoid: frozenset[str] | set[str] = frozenset()) -> dict[str, tuple[float, list[str]]]:
        """Dijkstra desde el destino: {zona de salida: (minutos, camino hasta el destino sin la salida)}."""
        if dest not in zones:
            return {}
        dist: dict[str, float] = {dest: 0.0}
        nxt: dict[str, str] = {}
        heap = [(0.0, dest)]
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist[u]:
                continue
            zu = zones[u]
            if u != dest and (u in avoid or (ambulance and (zu.density > self.amb_density or u in self.no_vehicles))):
                continue  # se puede salir de aquí hacia el destino, pero no atravesarlo
            cost_in = self._slow(zu.density)  # viajando hacia el destino, se entra en u
            for v in self.adjacent.get(u) or zu.neighbors:
                if v not in zones:
                    continue
                nd = d + self.minutes.get((v, u), HOP_MIN) * cost_in
                if nd < dist.get(v, 1e18):
                    dist[v], nxt[v] = nd, u
                    heapq.heappush(heap, (nd, v))
        out = {}
        for z, d in dist.items():
            path, cur = [], z
            while cur != dest:
                cur = nxt[cur]
                path.append(cur)
            out[z] = (d, path)
        return out


# -------------------------------------------------------------------- borrador de plan

@dataclass
class Draft:
    objective: str
    why: str = ""
    actions: list[Action] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)
    review_min: int = REVIEW_MIN
    unmet: list[str] = field(default_factory=list)                 # tipos de recurso que no se han podido cubrir
    lessons: list[tuple[str, str]] = field(default_factory=list)   # (lección, qué cambió)
    recalls: list[tuple[str, str]] = field(default_factory=list)   # (recurso, incidente al que se le quita)
    notes: list[str] = field(default_factory=list)
    rehearsals: list[str] = field(default_factory=list)            # líneas «ENSAYO: …» para el log
    params: list[tuple[str, str | None, str]] = field(default_factory=list)   # (parámetro aprendido, clave, qué cambió)


class _Build:
    """Estado de la construcción de UN plan."""

    def __init__(self, planner: "Planner", inc: Incident, m: IncidentMeta, v: Any, adj: Adjustments) -> None:
        self.p, self.inc, self.m, self.v, self.adj = planner, inc, m, v, adj
        self.zone: Zone | None = v.zones.get(inc.zone) if inc.zone else None
        self.d = Draft(objective=f"{label(inc).capitalize()}" + (f" en {self.zone.name}" if self.zone else ""))
        self.max_eta = 0.0

    # ---------------------------------------------------------------- piezas
    def act(self, kind: ActionKind, why: str, *, zone: str | None = None, resource: str | None = None,
            params: dict[str, Any] | None = None, channel: Channel | None = None, sig: Any = None) -> Action | None:
        params = params or {}
        key = (str(kind), zone, sig if sig is not None else params.get("to") or params.get("state") or resource)
        veto_key = f"{kind}:{params['state']}" if kind == ActionKind.SET_ZONE else str(kind)
        if key in self.m.sigs or veto_key in self.m.vetoed:
            return None
        if kind == ActionKind.BROADCAST and self.m.reserved:
            return None   # caso reservado: jamás por megafonía
        lesson = self.adj.forbidden(str(kind), zone=zone, to=params.get("to"), state=params.get("state"))
        if lesson:
            self.d.lessons.append((lesson, f"no se propone «{kind}»" + (f" hacia {params['to']}" if params.get("to") else "")))
            return None
        a = Action(id=self.v.new_id("A"), kind=kind, t=self.v.t, incident=self.inc.id, resource=resource, zone=zone,
                   params=params, why=why, channel=channel)
        self.m.sigs.add(key)
        self.v.sig_of[a.id] = key
        self.d.actions.append(a)
        return a

    def assume(self, text: str, **check: Any) -> Assumption:
        a = Assumption(id=self.v.new_id("S"), text=text, check=check)
        self.d.assumptions.append(a)
        return a

    def notify(self, to: str, message: str, why: str, channel: Channel = Channel.RADIO) -> None:
        self.act(ActionKind.NOTIFY, why, zone=self.inc.zone, params={"to": to, "message": message}, channel=channel)

    def broadcast(self, message: str, why: str, zone: str | None = None) -> None:
        self.act(ActionKind.BROADCAST, why, zone=zone or self.inc.zone, params={"message": message}, sig="pa")

    def restrict(self, why: str) -> None:
        if self.zone is not None and self.zone.state == "open":
            self.act(ActionKind.SET_ZONE, why, zone=self.zone.id, params={"state": "restricted"})

    def external(self, service: str, why: str) -> None:
        self.act(ActionKind.REQUEST_EXTERNAL, why, zone=self.inc.zone, channel=Channel.VOICE,
                 params={"kind": service, "service": service, "reports": self.inc.reports[::-1],
                         "message": f"{label(self.inc)} en {self.zone.name if self.zone else 'el recinto'}"})

    def ask(self, purpose: str, question: str, why: str) -> None:
        m = self.m
        if m.reserved:   # no se repite el contenido al informante ni se le pide relato: solo lo imprescindible
            question = {"zone": "Hemos recibido tu aviso. ¿Dónde estás? Dime la puerta o la zona más cercana.",
                        "confirm": "Hemos recibido tu aviso. ¿Sigues necesitando ayuda?"}.get(purpose, "Hemos recibido tu aviso. Va alguien a ayudarte.")
        if m.reporter_channel in _SPEAK and m.origin == "report":
            to, channel = m.reporter or "quien avisó", m.reporter_channel
        else:
            to, channel = "responsable de zona", Channel.RADIO
        a = self.act(ActionKind.ASK, why, zone=self.inc.zone, channel=channel, sig=f"ask:{purpose}",
                     params={"to": to, "purpose": purpose, "message": question, "reports": self.inc.reports[::-1]})
        if a is not None:
            m.ask, m.asks = a.id, m.asks + 1

    def ask_point(self) -> None:
        """Parámetro `require_precise_location`: «General» es demasiado amplio. Se pide un punto concreto a quien avisó
        MIENTRAS el equipo va de camino: nunca retrasa el despacho."""
        m, z = self.m, self.zone
        if m.reporter_channel in _SPEAK and m.origin == "report":
            to, channel = m.reporter or "quien avisó", m.reporter_channel
        else:
            to, channel = "responsable de zona", Channel.RADIO
        a = self.act(ActionKind.ASK, f"{z.name if z else 'la zona'} es demasiado amplia: se pide un punto concreto mientras el equipo va de camino",
                     zone=self.inc.zone, channel=channel, sig="ask:point",
                     params={"to": to, "purpose": "point", "precise": True, "reports": self.inc.reports[::-1],
                             "message": "Va un equipo hacia ti. ¿Junto a qué torre, puesto o acceso numerado estás?"})
        if a is not None:
            self.d.params.append(("require_precise_location", self.inc.zone,
                                  f"se pide a quien avisó de {self.inc.id} un punto concreto (torre, puesto o acceso)"))

    # ---------------------------------------------------------------- recursos
    def _options(self, kind: str) -> list[tuple[float, str, Resource, list[str], float]]:
        v, m, inc = self.v, self.m, self.inc
        kinds = (kind,) + tuple(k for k in SUBSTITUTES.get(kind, ()) if k in self.adj.prefer)
        routes = {amb: self.p.travel.to_zone(inc.zone, v.zones, amb, m.avoid) for amb in (False, True)}
        # reparto global: lo que el reparto conjunto de este tick ha dado a OTRO incidente no se toca
        mine = v.reserved_for.get((inc.id, kind))
        taken = {rid for (iid, _), rids in v.reserved_for.items() if iid != inc.id for rid in rids}
        out = []
        for r in v.resources.values():
            if r.kind not in kinds or r.status != ResourceStatus.AVAILABLE or r.id in v.assign or r.id in m.excluded:
                continue
            if r.id in taken or (mine is not None and r.id not in mine):
                continue
            hit = routes[r.kind == ResourceKind.AMBULANCE].get(r.zone)
            if hit is None:
                continue
            eta = max(1.0, hit[0])
            if r.shift_ends is not None and r.shift_ends <= v.t + eta:
                continue
            bonus = 3.0 if (r.id in self.adj.prefer or str(r.kind) in self.adj.prefer) else 0.0
            # parámetro `contact_order`: minutos que se esperan perder si no coge el teléfono (0 sin parámetros aprobados)
            penalty = v.params.contact_penalty(str(r.kind), r.id) if v.params is not None else 0.0
            out.append((eta - bonus + penalty, r.id, r, hit[1], eta))
        out.sort(key=lambda o: o[:2])
        return out

    def _recall(self, kind: str) -> tuple[Resource, Incident] | None:
        """Recurso ocupado en el incidente de MENOR prioridad, si la diferencia supera el margen."""
        v, best = self.v, None
        for rid, (iid, _) in v.assign.items():
            r, victim = v.resources.get(rid), v.incidents.get(iid)
            if r is None or victim is None or r.kind != kind or iid == self.inc.id or rid in self.m.excluded:
                continue
            if r.status == ResourceStatus.OFFLINE or v.recall_until.get(rid, -1) > v.t or v.meta[iid].life_threat:
                continue
            if victim.priority + RECALL_MARGIN > self.inc.priority:
                continue
            if best is None or (victim.priority, rid) < (best[1].priority, best[0].id):
                best = (r, victim)
        return best

    def dispatch(self, kind: str, n: int = 1, *, reason: str = "", preventive: bool = False) -> int:
        """Despacha hasta `n` recursos de un tipo. Devuelve cuántos ha conseguido."""
        inc, v = self.inc, self.v
        if not inc.zone or inc.zone not in v.zones:
            return 0
        got = 0
        for _ in range(n):
            options = self._options(kind)
            recalled = None
            if options:
                pick = self._rehearse_ambulance(options) if kind == "ambulance" else None
                _, _, r, path, eta = pick or options[0]
                self._contact_note(kind, options, r)
                role = self.p.travel.roles.get(r.id)
                why = f"{r.name}{f' ({role})' if role else ''}: el más rápido de {KIND_ES.get(kind, kind)} libre, {round(eta)} min"
                if len(options) > 1:
                    why += f" (siguiente: {options[1][2].name})"
                if r.id in self.adj.prefer or str(r.kind) in self.adj.prefer:
                    lesson = next((x for x in self.adj.applied), "")
                    self.d.lessons.append((lesson, f"se prefiere {r.name}"))
            elif not preventive and (recalled := self._recall(kind)):
                r, victim = recalled
                hit = self.p.travel.to_zone(inc.zone, v.zones, r.kind == ResourceKind.AMBULANCE, self.m.avoid).get(r.zone)
                eta, path = (max(1.0, hit[0]), hit[1]) if hit else (HOP_MIN * 2.0, [])
                text = (f"{r.name} deja «{label(victim)}» (prioridad {es(victim.priority)}) para «{label(inc)}» "
                        f"(prioridad {es(inc.priority)}): no queda {KIND_ES.get(kind, kind)} libre")
                self.act(ActionKind.RECALL, text, zone=victim.zone, resource=r.id, channel=Channel.VOICE,
                         params={"from_incident": victim.id, "for_incident": inc.id,
                                 "message": f"Dejad lo que estáis haciendo: hay algo más grave en {inc.zone}."},
                         sig=f"recall:{r.id}:{v.t}")
                self.d.recalls.append((r.id, victim.id))
                why = f"{r.name}, retirado de un incidente menos prioritario, {round(eta)} min"
            else:
                if kind not in self.d.unmet:
                    self.d.unmet.append(kind)
                break
            msg = f"{label(inc).capitalize()} en {v.zones[inc.zone].name}. {reason}".strip()
            a = self.act(ActionKind.DISPATCH, why + (f" · {reason}" if reason else ""), zone=inc.zone, resource=r.id,
                         channel=Channel.VOICE, sig=f"go:{r.id}:{v.t}",
                         params={"need": kind, "eta": round(eta), "route": path, "message": msg, "type": inc.type,
                                 **({"point": v.points[inc.id]} if inc.id in getattr(v, "points", {}) else {}),
                                 **({} if preventive else {"reports": inc.reports[::-1]})})
            if a is None:
                break
            v.assign[r.id] = (inc.id, kind)
            inc.assigned.append(r.id)
            self.max_eta = max(self.max_eta, eta)
            got += 1
            self.assume(f"{r.name} acepta en {ACCEPT_MIN} min", kind="action_accepted_within", action=a.id,
                        since=v.t, minutes=ACCEPT_MIN)
            self.assume(f"{r.name} sigue operativo", kind="resource_status_is", resource=r.id,
                        status=["available", "en_route", "busy"])
            mid = [z for z in path[:-1] if z not in self.m.avoid]
            if mid:
                limit = AMB_DENSITY if r.kind == ResourceKind.AMBULANCE else FOOT_DENSITY
                self.assume(f"camino despejado por {', '.join(mid)} (menos de {es(limit)}/m²)", kind="route_clear",
                            zones=mid, density=limit, resource=r.id)
        return got

    def _contact_note(self, kind: str, options: list, chosen: Resource) -> None:
        """Si el orden de contacto aprendido cambia a quién se llama (frente al más rápido), queda dicho."""
        params = self.v.params
        if params is None or len(options) < 2 or kind not in params.contact_order:
            return
        pure = min(options, key=lambda o: (o[0] - params.contact_penalty(str(o[2].kind), o[1]), o[1]))
        if pure[1] == chosen.id:
            return
        c = params.contact_order[kind]
        rate, n = c.get("rate", {}), c.get("n", {})
        self.d.params.append(("contact_order", kind,
                              f"para {self.inc.id} se llama a {chosen.name} (contesta el {round(100 * rate.get(chosen.id, 1))} %, "
                              f"N={n.get(chosen.id, 0)}) antes que a {pure[2].name} ({round(100 * rate.get(pure[1], 1))} %, "
                              f"N={n.get(pure[1], 0)}), aunque está {round(pure[4])} min frente a {round(options[0][4])}"))

    def _rehearse_ambulance(self, options: list) -> tuple | None:
        """La ambulancia no cruza público: antes de mandarla se ensaya si llega y cuándo (criterio: ETA ensayada)."""
        reh, inc = self.v.rehearsal, self.inc
        if reh is None or not reh.available:
            return None
        results = []
        for opt in options[:2]:
            r = opt[2]
            o = reh.run(f"{r.name} → {inc.zone}", [Action(id="x", kind=ActionKind.DISPATCH, t=self.v.t, resource=r.id,
                                                          zone=inc.zone, params={"reports": inc.reports[::-1]})],
                        [inc.zone], horizon=15, resources=[r.id])
            if o is not None:
                results.append((o.arrival.get(r.id, 99), opt, o))
        if not results:
            return None
        self.d.rehearsals.append("ENSAYO (15 min) de ruta sanitaria: " + " · ".join(
            f"{opt[2].name} → " + (f"llega en {eta} min ✓" if eta < 99 else "no llega en 15 min ✗") for eta, opt, _ in results))
        eta, opt, _ = min(results, key=lambda x: (x[0], x[1][1]))
        if eta >= 99:
            self.d.notes.append("ensayado: la ambulancia no llega en 15 min por ninguna ruta; va el equipo a pie")
            return None
        return (*opt[:4], float(eta))

    def cover_needs(self) -> None:
        inc, v = self.inc, self.v
        have: dict[str, int] = {}
        for rid in inc.assigned:
            kind = v.assign.get(rid, (None, None))[1]
            if kind:
                have[kind] = have.get(kind, 0) + 1
        order = sorted(inc.needs, key=lambda k: (k not in ("medical", "ambulance"), k))
        for kind in order:
            # un aviso de riesgo vital sin confirmar mueve al equipo a pie ya; la ambulancia espera la confirmación
            if kind == "ambulance" and inc.confidence < CONFIRM_BELOW:
                self.d.notes.append("ambulancia a la espera de confirmación")
                continue
            missing = inc.needs[kind] - have.get(kind, 0)
            if missing > 0:
                self.dispatch(kind, missing)

    # ---------------------------------------------------------------- desvío con proyección
    def reroute(self) -> bool:
        """Desvío con proyección de flujo. Lo que llega al origen ≈ lo que crece + lo que descargan sus tornos;
        cada destino admite lo que le sobra de descarga más la mitad del hueco que le queda hasta el límite.
        La fracción se ajusta a ese presupuesto. Aun así la proyección puede fallar: el supuesto queda escrito."""
        v, src, m = self.v, self.zone, self.m
        if src is None or not src.capacity:
            return False
        limit = self.adj.threshold("zone_occupancy_below", "ratio", DEST_RATIO)
        if "zone_occupancy_below" in self.adj.thresholds:
            self.d.lessons.append((self.adj.threshold_source["zone_occupancy_below"],
                                   f"el destino del desvío debe quedar por debajo del {round(limit * 100)} %"))
        current = v.reroutes.get(src.id) or src.flags.get("reroute_to")
        entry = self.p.travel.entry

        def grow(z: Zone) -> float:
            return max(0.0, v.trend.get(z.id, 0.0) * z.area_m2)

        def out(z: Zone) -> float:
            return entry.get(z.id, 0.0) * float(z.flags.get("flow_factor", 1.0))

        if m.broken and current and src.occupancy < 0.6 * src.capacity and grow(src) == 0:
            # el destino falló y el origen ya está tranquilo: el desvío sobra y solo puede hacer daño
            self.act(ActionKind.REROUTE, f"{src.name} ya está al {round(src.occupancy / src.capacity * 100)} %: "
                     f"se retira el desvío hacia {current}", zone=src.id, params={"cancel": True}, sig=f"cancel:{v.t}")
            return False
        if current and current not in m.avoid:
            return True  # el desvío en marcha sigue siendo válido: no se cambia de destino sin motivo
        busy = {i.zone for i in v.live if i.family == Family.CROWD and i.id != self.inc.id} | set(v.reroutes)
        if src.kind == "gate":
            pool = [z for z in v.zones.values() if z.kind == "gate" and z.id != src.id]
        else:
            pool = [v.zones[n] for n in src.neighbors if n in v.zones and v.zones[n].kind not in _NO_REROUTE_TO]
        inflow = grow(src) + out(src)
        if inflow <= 0:
            inflow = max(src.occupancy - 0.8 * src.capacity, 0.05 * src.capacity) / PROJECTION_MIN
        walk = QUEUE_WALK * src.occupancy if src.kind == "gate" else 0.0   # parte de la cola se va andando al destino
        ranked = []
        for z in sorted(pool, key=lambda z: z.id):
            if z.state != "open" or z.id in m.avoid or z.id in busy or not z.capacity or v.bad_dest.get(z.id, -1) > v.t:
                continue
            lesson = self.adj.forbidden("reroute", zone=src.id, to=z.id)
            if lesson:
                self.d.lessons.append((lesson, f"no se desvía hacia {z.name}"))
                continue
            absorb = max(0.0, 0.7 * out(z) - grow(z))
            room = max(0.0, (limit * z.capacity - z.occupancy) / PROJECTION_MIN - (grow(z) if absorb == 0 else 0.0))
            fraction = max(0.1, min(0.6, (absorb + 0.5 * room - walk) / inflow))
            net = max(0.0, fraction * inflow + walk - absorb) + (grow(z) if absorb == 0 else 0.0)
            projected = z.occupancy + net * PROJECTION_MIN
            if projected < limit * z.capacity:
                ranked.append((round(fraction, 2), limit * z.capacity - projected, z, projected))
        ranked.sort(key=lambda x: (-x[0], -x[1], x[2].id))
        if not ranked:
            if current:
                self.act(ActionKind.REROUTE, f"se anula el desvío hacia {current}: ya no hay ningún destino con margen",
                         zone=src.id, params={"cancel": True}, sig=f"cancel:{v.t}")
            self.d.notes.append("ningún destino con margen para desviar")
            return False
        chosen = self._rehearse_reroute(src, ranked, inflow)
        if chosen is False:
            return False
        for fraction, _, z, projected in ([chosen[:4]] if chosen else ranked[:2 if ALLOW_SPLIT else 1]):
            outcome = chosen[4] if chosen else None
            peak = outcome.peak.get(z.id, 0.0) if outcome else projected / z.area_m2 if z.area_m2 else 0.0
            others = "; ".join(f"{o.name} admitiría el {round(f * 100)} %" for f, _, o, _ in ranked[1:3] if o.id != z.id)
            if outcome:
                why = (f"ENSAYADO {outcome.minutes} min en el gemelo: con el {round(fraction * 100)} % hacia {z.name}, {z.name} llega a "
                       f"{es(peak)}/m² ({round(peak * z.area_m2 / z.capacity * 100)} %) en {outcome.peak_at.get(z.id, 0)} min y "
                       f"{src.name} queda en {es(outcome.final.get(src.id, 0.0))}/m²")
            else:
                why = (f"{z.name} es el destino que más flujo admite: {z.occupancy}/{z.capacity} ahora; con el "
                       f"{round(fraction * 100)} % de lo que llega a {src.name} (~{round(fraction * inflow)} pers/min) quedaría al "
                       f"{round(projected / z.capacity * 100)} % en {PROJECTION_MIN} min" + (f" ({others})" if others else ""))
            a = self.act(ActionKind.REROUTE, why, zone=src.id,
                         params={"to": z.id, "fraction": fraction, "people_per_min": round(fraction * inflow),
                                 "projected_ratio": round(projected / z.capacity, 2), "dest_peak_density": round(peak, 2),
                                 "rehearsed": outcome.to_dict() if outcome else None,
                                 "message": f"Acceso por {z.name}: menos espera."})
            if a is None:
                continue
            tested = (f"ensayado: {z.name} llega al {round(peak * z.area_m2 / z.capacity * 100)} % en {outcome.peak_at.get(z.id, 0)} min; "
                      if outcome else f"proyectado: {z.name} al {round(projected / z.capacity * 100)} % en {PROJECTION_MIN} min; ")
            self.assume(f"{tested}supuesto: {z.name} sigue por debajo del {round(limit * 100)} % de su capacidad pese al desvío",
                        kind="zone_occupancy_below", zone=z.id, ratio=limit, own_action=a.id)
            self.assume(f"{z.name} sigue abierta", kind="zone_state_is", zone=z.id, state="open")
        return True

    def _flow_context(self) -> list[Action]:
        """Lo que este mismo plan ya ha decidido ejecutar solo y cambia el flujo: entra en todos los ensayos."""
        return [a for a in self.d.actions if a.kind in (ActionKind.SET_ZONE, ActionKind.DISPATCH)
                and autonomy_level(a) == Autonomy.AUTO]

    def _rehearse_reroute(self, src: Zone, ranked: list, inflow: float):
        """Ensaya 2–4 alternativas en el gemelo. Devuelve (fracción, margen, zona, proyectado, resultado), None si no
        hay gemelo (vale la proyección analítica) o False si lo mejor es NO desviar."""
        reh = self.v.rehearsal
        if reh is None or not reh.available:
            return None
        names = {z.id: z.name for z in self.v.zones.values()}
        context = self._flow_context()
        alts: list[tuple[str, tuple | None, float]] = []
        for fraction, margin, z, projected in ranked[:2]:
            alts.append((f"{round(fraction * 100)} % a {z.name}", (fraction, margin, z, projected), fraction))
        best = ranked[0]
        if best[0] < 0.6:
            alts.insert(1, (f"todo lo desviable (60 %) a {best[2].name}", (0.6, best[1], best[2], best[3]), 0.6))
        alts.append(("sin desvío", None, 0.0))
        outcomes = []
        for text, cand, fraction in alts[:4]:
            actions = list(context)
            watch = [src.id]
            if cand is not None:
                actions.append(Action(id="x", kind=ActionKind.REROUTE, t=self.v.t, zone=src.id,
                                      params={"to": cand[2].id, "fraction": fraction}))
                watch.append(cand[2].id)
            o = reh.run(text, actions, watch)
            if o is not None:
                outcomes.append((o, cand))
        if not outcomes:
            return None
        self.d.rehearsals.append(f"ENSAYO ({outcomes[0][0].minutes} min) para {src.name}: "
                                 + " · ".join(o.line(names) for o, _ in outcomes))
        o, cand = min(outcomes, key=lambda oc: oc[0].key)
        if cand is None:
            self.d.notes.append("ensayado: desviar no mejora nada, se deja el flujo como está")
            return False
        return (*cand, o)

    def improving(self) -> None:
        inc = self.inc
        minutes = max(REVIEW_MIN, round(self.max_eta) + 3)
        params = self.v.params
        if params is not None and inc.family == Family.WEATHER and params.weather_followup_min < min(minutes, REVIEW_MIN):
            minutes = params.weather_followup_min
            self.d.params.append(("weather_followup_min", None, f"el aviso meteorológico {inc.id} se revisa cada {minutes} min"))
        self.d.review_min = minutes
        value = metric(inc, self.v)
        safe = 0.8 if inc.family == Family.CROWD else None
        what = "la ocupación baja" if inc.family == Family.CROWD else "hay un equipo en el sitio" if inc.assigned \
            else "la situación mejora"
        self.assume(f"reevaluar en {minutes} min: {what}", kind="incident_improving", incident=inc.id,
                    since=self.v.t, minutes=minutes, baseline=value, safe=safe)


class Planner:
    def __init__(self, travel: Travel | None = None) -> None:
        self.travel = travel or Travel()

    def build(self, inc: Incident, m: IncidentMeta, v: Any, adj: Adjustments) -> Draft | None:
        b = _Build(self, inc, m, v, adj)
        for lesson, pre in adj.pre_actions:
            a = b.act(ActionKind(pre["kind"]), f"acción previa obligatoria del manual ({lesson})",
                      zone=pre.get("zone") or inc.zone, params=dict(pre.get("params") or {}), sig=f"pre:{lesson}")
            if a is not None:
                b.d.lessons.append((lesson, f"primero «{a.kind}»"))

        if self._ask_first(b):
            return self._finish(b)
        if not inc.zone and m.sitewide:
            default = {"transport_cut": "exit_transport"}.get(inc.type) or (
                next((z.id for z in v.zones.values() if z.kind == "stage_front"), None)
                if inc.type in ("artist_delay", "storm") else None)
            if default in v.zones:
                inc.zone, b.zone = default, v.zones[default]
        self._respond(b)
        self._after_veto(b)
        if b.d.actions or b.d.assumptions:
            b.improving()
        return self._finish(b)

    @staticmethod
    def _finish(b: _Build) -> Draft | None:
        d = b.d
        if not d.actions:
            return None
        if d.unmet:
            d.notes.append("sin " + ", ".join(KIND_ES.get(k, k) for k in d.unmet) + " libre: en cola")
        return d

    # ---------------------------------------------------------------- primero preguntar
    @staticmethod
    def _ask_first(b: _Build) -> bool:
        """True si el plan se queda en preguntar (todavía no se puede actuar con sentido)."""
        inc, m = b.inc, b.m
        what = label(inc)
        if "zone" in m.missing and not m.sitewide:
            b.ask("zone", f"Hemos recibido tu aviso ({what}). ¿Dónde estás? Dime la puerta o la zona más cercana.",
                  "falta la zona: sin saber dónde, mandar un equipo es perderlo")
            b.d.objective = f"Localizar: {what}"
            return True
        if "type" in m.missing:
            # Tipo no reconocido: política conservadora por familia y señales, nunca protocolo inventado.
            b.ask("type", "¿Qué está pasando exactamente? ¿Hay alguien herido o en peligro? ¿Qué necesitáis?",
                  "tipo no reconocido: se pregunta lo que falta antes de decidir nada más")
            if m.threat:       # amenaza o sospecha → decide una persona, Mando solo prepara y avisa
                Planner._escalate(b)
                b.d.objective = "Escalar a la persona: posible amenaza sin tipo reconocido" + (f" en {b.zone.name}" if b.zone else "")
                return True
            if m.life_threat:  # riesgo vital → sale ya el recurso genérico adecuado (equipo médico) y se pregunta mientras
                b.d.objective = "Riesgo vital sin tipo reconocido" + (f" en {b.zone.name}" if b.zone else "")
                return False
            b.d.objective = "Aclarar un aviso de tipo no reconocido" + (f" en {b.zone.name}" if b.zone else "")
            return True
        if m.hold:
            b.ask("confirm", f"Nos llega un aviso de {what}" + (f" en {b.zone.name}" if b.zone else "")
                  + ". ¿Puedes confirmarlo?", f"un solo aviso y poco fiable (confianza {round(inc.confidence * 100)} %): "
                  "se confirma antes de gastar un equipo")
            b.d.objective = f"Confirmar: {what}" + (f" en {b.zone.name}" if b.zone else "")
            return True
        if m.contradicted:
            b.ask("clarify", f"Nos llegan versiones distintas sobre {what}"
                  + (f" en {b.zone.name}" if b.zone else "") + ". ¿Qué ves ahora mismo?",
                  "versiones contradictorias: " + (inc.notes[-1] if inc.notes else "no coinciden"))
            if not m.life_threat and inc.confidence < CONFIRM_BELOW:
                return True
        elif m.life_threat and inc.confidence < CONFIRM_BELOW:
            b.ask("confirm", f"Va un equipo médico hacia {b.zone.name if b.zone else 'allí'}. ¿La persona respira? ¿Está consciente?",
                  "riesgo vital con poca confianza: el equipo sale ya y se confirma mientras llega")
        return False

    # ---------------------------------------------------------------- respuesta
    def _respond(self, b: _Build) -> None:
        """Protocolo del tipo (ficha del léxico) + lo que añade lo que se OBSERVA: densidad, agua, viento."""
        inc, m, z, v = b.inc, b.m, b.zone, b.v
        spec = spec_for(inc.type, inc.family)
        what, where = label(inc).capitalize(), (f" en {z.name}" if z else "")
        sure = inc.confidence >= CONFIRM_BELOW     # nada drástico ni externo sobre un aviso sin confirmar

        if m.origin == "pattern":
            n = len(m.members)
            if inc.type == "heat_cluster":
                self._water(b)
                b.broadcast(spec.broadcast, f"{n} casos por calor en 10 min no son {n} casos: es un problema de agua y sombra")
            for role in spec.notify:
                b.notify(role, f"{what}: {n} casos relacionados{where}. Reforzad y vigilad la causa.",
                         "un patrón pide actuar sobre la causa, no mandar un equipo por caso")
            return

        if m.threat:
            self._escalate(b)
        if inc.type in ("water_out", "water_low", "heat_wave"):
            self._water_point(b)     # antes que nada: el RESUPPLY es quien cubre la necesidad de logística
        b.cover_needs()
        if v.params is not None and z is not None and v.params.precise(z.id) and m.origin == "report" and not m.reserved \
                and inc.family in (Family.MEDICAL, Family.AGGRESSION) and inc.id not in v.points:
            b.ask_point()
        if inc.family == Family.CROWD and z is not None:
            self._crowd(b, spec)
        else:
            if spec.restrict:
                b.restrict(f"{label(inc)}: se limita la entrada a la zona mientras se resuelve, sin cerrarla")
            if spec.reroute and inc.type != "water_out":
                b.reroute()
            if spec.broadcast and not m.threat:
                b.broadcast(spec.broadcast, "megafonía y pantallas: si la gente sabe qué pasa, no se agolpa")
        for role in spec.notify:
            b.notify(role, f"{what}{where}.", f"{ROLE_ES.get(role, role)} tiene que saberlo para coordinar su parte")
        if inc.family == Family.MEDICAL and m.count >= 5 and not spec.external:
            b.external("ambulance", f"{m.count} afectados: hace falta apoyo sanitario externo")
        if not sure:
            return
        if spec.external:
            b.external(spec.external, f"{label(inc)}: corresponde a {SERVICE_ES.get(spec.external, spec.external)}")
        if inc.family == Family.WEATHER:
            self._weather(b, spec)
        elif spec.stop_show and inc.family != Family.CROWD:
            b.act(ActionKind.STOP_SHOW, f"{label(inc)} (gravedad {inc.severity}): el protocolo pide parar", zone=inc.zone,
                  params={"minutes": 15})
        if spec.evacuate and (m.threat or m.level >= 1 or inc.severity >= 9) and inc.family != Family.WEATHER:
            why = ("evacuación PREPARADA, no ejecutada: rutas y equipos listos por si la policía la pide" if m.threat
                   else f"{label(inc)} sin controlar: sacar al público de la zona")
            b.act(ActionKind.EVACUATE, why, zone=inc.zone, params={"prepared": True} if m.threat else {})
        if spec.close and z is not None:
            b.act(ActionKind.SET_ZONE, f"{label(inc)}: nadie debajo hasta que técnicos lo revisen", zone=z.id,
                  params={"state": "closed"})

    def _crowd(self, b: _Build, spec: TypeSpec) -> None:
        inc, m, z = b.inc, b.m, b.zone
        dens = z.density
        # lo que se OBSERVA manda: un aviso alarmista en una zona medio vacía no justifica cortar la entrada
        critical = dens >= 5.0 or ((spec.restrict or inc.severity >= 8) and dens >= 3.0) or z.kind == "pmr"
        if critical or z.occupancy >= 0.95 * z.capacity:
            b.restrict(f"{z.name} a {es(dens)}/m² ({z.occupancy}/{z.capacity}): se corta la entrada sin cerrar la zona")
        if spec.reroute or critical:
            b.reroute()
        if spec.broadcast:
            b.broadcast(spec.broadcast, "megafonía y pantallas: la gente se reparte sola si sabe adónde ir")
        if critical and "security_lead" not in spec.notify:
            b.notify("security_lead", f"Densidad {es(dens)}/m² en {z.name}.", "el jefe de seguridad tiene que saberlo ya")
        if inc.confidence < CONFIRM_BELOW:
            return
        if (spec.stop_show or z.kind == "stage_front") and (dens >= 5.0 or m.level >= 1 or inc.severity >= 9):
            b.act(ActionKind.STOP_SHOW, f"{es(dens)}/m² en {z.name}" + (" y la respuesta anterior no bastó" if m.level else "")
                  + ": parar la música es lo único que quita presión en minutos", zone=z.id, params={"minutes": 10})
        if dens >= 6.5 and m.level >= 1:
            b.act(ActionKind.EVACUATE, f"{es(dens)}/m², por encima del umbral de aplastamiento, y sigue sin bajar", zone=z.id)
        if z.kind == "gate" and m.level >= 2 and dens >= 4.0:
            b.act(ActionKind.SET_ZONE, "dos respuestas seguidas no han bajado la ocupación: cerrar la puerta",
                  zone=z.id, params={"state": "closed"})

    def _weather(self, b: _Build, spec: TypeSpec) -> None:
        inc, v = b.inc, b.v
        wind = float(v.weather.get("wind_kmh") or 0)
        if spec.stop_show or wind >= WIND_STOP or int(v.weather.get("wind_level") or 0) >= 3 or b.m.level >= 1:
            b.act(ActionKind.STOP_SHOW, f"{label(inc)} (gravedad {inc.severity})" + (f", viento de {round(wind)} km/h" if wind else "")
                  + ": el protocolo pide parar antes de que algo caiga", zone=inc.zone, params={"minutes": 20})
            if spec.evacuate and b.zone is not None:
                b.act(ActionKind.EVACUATE, "estructuras en riesgo con público debajo: despejar la zona", zone=inc.zone)
        elif "wind_kmh" in v.weather and inc.type == "high_wind":
            b.assume(f"el viento se mantiene por debajo de {round(WIND_STOP)} km/h", kind="weather_below",
                     key="wind_kmh", value=WIND_STOP)

    def _water_point(self, b: _Build) -> None:
        """Agua: rellenar y, mientras tanto, decir dónde SÍ hay (con el supuesto de que allí no se acaba)."""
        inc, v = b.inc, b.v
        point = self._water(b)
        if inc.type != "water_out" or b.zone is None or "water_l" not in b.zone.flags:
            return
        other = next((z for z in sorted(v.zones.values(), key=lambda z: z.id)
                      if "water_l" in z.flags and z.id != inc.zone and z.flags["water_l"] > 200), None)
        if other is not None:
            b.act(ActionKind.REROUTE, f"mientras se rellena, el agua está en {other.name} ({round(other.flags['water_l'])} l)",
                  zone=inc.zone, params={"to": other.id, "message": f"Agua disponible en {other.name}."})
            b.assume(f"{other.name} conserva agua (más de 200 l)", kind="supply_above", zone=other.id,
                     flag="water_l", value=200)
            b.broadcast(f"Punto de agua sin servicio unos minutos. Hay agua en {other.name}.", "se dice dónde SÍ hay agua",
                        zone=inc.zone)
        if point is None and "logistics" not in b.d.unmet:
            b.d.unmet.append("logistics")

    def _water(self, b: _Build) -> Zone | None:
        """RESUPPLY al punto de agua del incidente o, si no es uno, al que menos agua tenga."""
        v = b.v
        points = [z for z in v.zones.values() if "water_l" in z.flags]
        if not points:
            return None
        here = b.zone if b.zone is not None and "water_l" in b.zone.flags else None
        point = here or min(points, key=lambda z: (z.flags["water_l"], z.id))
        mine = [rid for rid in b.inc.assigned if v.assign.get(rid, (None, ""))[1] == "logistics"]
        if mine:
            return point
        options = [r for r in sorted(v.resources.values(), key=lambda r: r.id) if r.kind == ResourceKind.LOGISTICS
                   and r.status == ResourceStatus.AVAILABLE and r.id not in v.assign and r.id not in b.m.excluded]
        if not options:
            return None
        r = options[0]
        hit = self.travel.to_zone(point.id, v.zones).get(r.zone)
        b.max_eta = max(b.max_eta, (hit[0] if hit else 4.0) + RESUPPLY_MIN)
        a = b.act(ActionKind.RESUPPLY, f"{r.name} rellena {point.name} ({round(point.flags['water_l'])} l restantes)",
                  zone=point.id, resource=r.id, channel=Channel.VOICE, sig=f"water:{point.id}",
                  params={"need": "logistics", "message": f"Llevad agua a {point.name}.", "reports": b.inc.reports[::-1]})
        if a is not None:
            v.assign[r.id] = (b.inc.id, "logistics")
            b.inc.assigned.append(r.id)
            b.assume(f"{r.name} sigue operativo", kind="resource_status_is", resource=r.id,
                     status=["available", "en_route", "busy"])
        return point

    # ---------------------------------------------------------------- amenazas y vetos
    @staticmethod
    def _escalate(b: _Build) -> None:
        inc = b.inc
        b.act(ActionKind.NOTIFY, "ante una amenaza Mando no decide: prepara y pasa la decisión a la persona",
              zone=inc.zone, channel=Channel.OPERATOR, sig="escalate",
              params={"to": "operator", "escalate": True,
                      "message": f"DECISIÓN HUMANA: {label(inc)}" + (f" en {inc.zone}" if inc.zone else "")
                                 + ". Seguridad va de camino; policía y evacuación quedan a tu aprobación."})

    @staticmethod
    def _after_veto(b: _Build) -> None:
        """La persona dijo que no: se propone el escalón siguiente, menos drástico."""
        m, z = b.m, b.zone
        if "evacuate" in m.vetoed and z is not None:
            b.restrict("evacuación vetada: se restringe la entrada")
            b.reroute()
            b.broadcast(f"{z.name} está llena: usad las zonas de alrededor.", "evacuación vetada: se reparte al público con megafonía")
        if "stop_show" in m.vetoed and z is not None:
            b.broadcast("Por favor, dad un paso atrás y dejad espacio delante.", "parada vetada: mensaje de calma desde el escenario", zone=z.id)
            if not any(a.kind == ActionKind.DISPATCH for a in b.d.actions):
                b.dispatch("security", 1, reason="Refuerzo: la parada del concierto fue vetada.")
        if "request_external" in m.vetoed:
            b.notify("coordinator", "Ayuda externa vetada: se resuelve con recursos propios; 112 preavisado.",
                     "petición externa vetada: se deja preavisado")
        if "set_zone:closed" in m.vetoed and z is not None:
            b.restrict("cierre vetado: se restringe en vez de cerrar")


__all__ = ["Planner", "Travel", "Draft", "label", "es", "ACCEPT_MIN", "REVIEW_MIN", "RECALL_MARGIN",
           "RECALL_COOLDOWN", "DEST_RATIO"]
