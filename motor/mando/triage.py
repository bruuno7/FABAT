"""Triaje: de avisos sueltos a incidentes.

- Correlación: mismo grupo de tipos + misma zona dentro de una ventana → MERGE (sube la confianza).
- Versiones contradictorias → baja la confianza y se pide aclaración (ASK).
- Falsas alarmas: un aviso único y poco fiable queda retenido hasta confirmarse, SALVO riesgo vital.
- Patrones: varios casos relacionados en poco tiempo son un problema de fondo, no N casos.

Triaje no emite acciones: devuelve `TriageEvent` y Mando decide qué hacer con ellos.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..contracts import Channel, Family, Incident, IncidentStatus, Report
from .assumptions import CLOSED
from .lexicon import TYPES, spec_for

MERGE_WINDOW = 15        # minutos sin avisos nuevos a partir de los cuales un aviso igual es otro incidente
CONFIRM_BELOW = 0.5      # por debajo, no se gasta un equipo sin confirmar (salvo riesgo vital)
HOLD_MAX = 8             # minutos retenido sin confirmación → falsa alarma
NEIGHBOR_WINDOW = 6      # minutos en los que un aviso igual en la zona de al lado se toma por el mismo incidente
NEIGHBOR_FAMILIES = (Family.CROWD, Family.INFRA, Family.WEATHER, Family.SUPPLY, Family.EXTERNAL, Family.INFO)
CONTRADICTION_GAP = 4    # diferencia de gravedad entre versiones que cuenta como contradicción
# «asistente» no identifica a nadie: dos avisos con ese origen son dos personas distintas
GENERIC_SOURCES = frozenset({"", "asistente", "publico", "público", "attendee", "anonimo", "anónimo", "whatsapp", "sms"})


@dataclass
class IncidentMeta:
    """Lo que Mando necesita recordar de un incidente y no cabe en el tipo del contrato."""
    group: str
    origin: str = "report"            # report | watch | pattern
    life_threat: bool = False
    threat: bool = False
    sitewide: bool = False
    heat: bool = False
    minors: bool = False
    reserved: bool = False            # caso sensible (violencia sexual, menores, amenaza): ni megafonía ni pantalla pública
    count: int = 1
    sources: set[str] = field(default_factory=set)
    reporter: str = ""                # quién dio el primer aviso y por dónde: a él se le pregunta
    reporter_channel: Channel | None = None
    last_report_t: int = 0
    missing: list[str] = field(default_factory=list)
    hold: bool = False                # retenido a la espera de confirmación
    hold_since: int = 0
    contradicted: bool = False
    ask: str | None = None            # id del ASK vivo
    asks: int = 0
    excluded: set[str] = field(default_factory=set)   # recursos que rechazaron o no contestaron
    avoid: set[str] = field(default_factory=set)      # zonas que rompieron un supuesto
    vetoed: set[str] = field(default_factory=set)     # tipos de acción vetados por la persona
    level: int = 0                    # escalón de respuesta: sube cuando la acción no funcionó
    replans: int = 0
    plan: str | None = None
    dirty: str | None = None          # motivo por el que hay que (re)planificar
    broken: str | None = None         # id del supuesto roto que provocó el replan
    first_action_t: int | None = None
    seen_on_scene: bool = False
    checked_empty: int | None = None  # minuto en que un equipo llegó y no encontró nada
    queued_logged: bool = False
    gave_up: bool = False
    members: list[str] = field(default_factory=list)  # incidentes de un patrón
    factors: tuple = ()
    boost: float = 0.0
    lessons_logged: set[str] = field(default_factory=set)
    sigs: set[tuple] = field(default_factory=set)     # acciones ya lanzadas: un replan no las repite
    review_times: list[int] = field(default_factory=list)   # minutos en que «reevaluar en N min» salió mal
    broken_kind: str | None = None


@dataclass
class TriageEvent:
    kind: str          # new | merge | contradiction | all_clear | noise | pattern
    incident: Incident | None
    text: str
    data: dict[str, Any] = field(default_factory=dict)


# (nombre, tipo del patrón, atributo o grupos que cuentan, n, ventana, misma zona)
PATTERNS = [
    ("heat", "heat_cluster", 3, 10, False),
    ("intox", "intox_cluster", 3, 20, False),
    ("aggression", "aggression_cluster", 3, 15, True),
]


class Triage:
    def __init__(self, incidents: dict[str, Incident], meta: dict[str, IncidentMeta],
                 new_id: Callable[[], str]) -> None:
        self.incidents = incidents
        self.meta = meta
        self.new_id = new_id
        self.live: list[Incident] = []            # incidentes no cerrados, los mantiene Mando
        self.zones: dict[str, Any] = {}           # última observación, para saber qué zonas son vecinas
        self._pattern_until: dict[str, int] = {}
        self.merge_window = MERGE_WINDOW          # parámetro `duplicate_window_min` (solo se alarga con aprobación)

    # ---------------------------------------------------------------- correlación
    def _find(self, p: dict[str, Any], report: Report, t: int) -> Incident | None:
        """Incidente vivo al que pertenece este aviso, o None. Puntos: 4 misma zona (o tipo de recinto entero) ·
        3 mismo informante del personal · 2 mismo tipo sin zona o (si no va de personas) en la zona vecina · 1 mismo grupo sin zona.
        Con 2 puntos o menos solo se funde si no hay ambigüedad, y nunca un riesgo vital: dos desmayos sin zona
        pueden ser dos personas, así que se pregunta."""
        spec = spec_for(p["type"], p["family"])
        best, best_score, ties = None, 0, 0
        for inc in self.live:
            m = self.meta[inc.id]
            # la ventana aprendida (más larga) NUNCA se aplica a un riesgo vital: a los 20 min puede ser otra persona
            window = MERGE_WINDOW if (spec.life_threat or m.life_threat or p.get("life_threat")) else self.merge_window
            if m.origin == "pattern" or t - m.last_report_t > window:
                continue
            same_type = inc.type == p["type"]
            same_kind = same_type or m.group == spec.group
            same_zone = bool(p["zone"]) and p["zone"] == inc.zone
            same_source = report.source in m.sources and report.source.lower() not in GENERIC_SOURCES
            if not (same_kind or (p["type"].startswith("unknown") and same_zone)
                    or (p["all_clear"] and (same_zone or same_source))):
                continue
            if same_zone or (m.sitewide and same_kind and not (p["zone"] and inc.zone)):
                score = 4
            elif p["zone"] and inc.zone:
                near = self.zones.get(inc.zone)
                # personas (médico, agresión) no se funden entre zonas: al lado puede haber OTRA persona
                score = 2 if (same_type and spec.family in NEIGHBOR_FAMILIES and near is not None
                              and p["zone"] in near.neighbors and t - m.last_report_t <= NEIGHBOR_WINDOW) else 0
            elif same_source:
                score = 3
            elif spec.life_threat and not p["all_clear"]:
                # un riesgo vital sin zona no se funde con otro ya localizado (puede ser otra persona); al revés sí:
                # el incidente que esperaba su ubicación la recibe y sale el equipo
                score = 2 if (p["zone"] and not inc.zone) else 0
            else:
                score = 2 if same_type else 1
            if not score:
                continue
            if score > best_score or (score == best_score and m.last_report_t > self.meta[best.id].last_report_t):
                ties = 1 if score > best_score else ties + 1
                best, best_score = inc, score
            elif score == best_score:
                ties += 1
        return None if best_score <= 2 and ties > 1 else best

    def ingest(self, report: Report, p: dict[str, Any], t: int) -> TriageEvent:
        if p.get("informational"):
            return TriageEvent("noise", None, f"lectura normal de {report.source or report.channel}")
        inc = self._find(p, report, t)
        if p["all_clear"]:
            if inc is None:
                return TriageEvent("noise", None, "aviso de «todo en orden» sin incidente asociado")
            return self._all_clear(inc, report, p, t)
        if inc is None:
            return self._open(report, p, t)
        return self._merge(inc, report, p, t)

    def _open(self, report: Report, p: dict[str, Any], t: int) -> TriageEvent:
        spec = spec_for(p["type"], p["family"])
        inc = Incident(
            id=self.new_id(), family=Family(p["family"]), type=p["type"], zone=p["zone"], severity=p["severity"],
            t_open=t, deadline=t + spec.deadline if spec.deadline else None, needs=dict(p["needs"]),
            reports=[report.id], confidence=p["confidence"])
        life = bool(p.get("life_threat", spec.life_threat))
        m = IncidentMeta(group=spec.group, life_threat=life, threat=bool(p.get("threat", spec.threat)),
                         sitewide=bool(p.get("sitewide", spec.sitewide)), heat=spec.heat,
                         minors=bool(p.get("minors")), count=int(p.get("count", 1)),
                         reserved=bool(p.get("reserved", spec.reserved)),
                         sources={report.source} if report.source else set(), last_report_t=t,
                         reporter=report.source, reporter_channel=report.channel,
                         missing=list(p["missing"]), dirty="nuevo")
        m.hold = not life and inc.confidence < CONFIRM_BELOW
        m.hold_since = t
        self.incidents[inc.id], self.meta[inc.id] = inc, m
        self.live.append(inc)
        return TriageEvent("new", inc, "", {"hold": m.hold})

    def _merge(self, inc: Incident, report: Report, p: dict[str, Any], t: int) -> TriageEvent:
        m = self.meta[inc.id]
        inc.reports.append(report.id)
        new_source = report.source not in m.sources or report.source.lower() in GENERIC_SOURCES
        if report.source:
            m.sources.add(report.source)
        quiet_min = t - m.last_report_t           # minutos que llevaba el incidente sin avisos nuevos
        m.last_report_t = t
        m.minors = m.minors or bool(p.get("minors"))
        m.reserved = m.reserved or bool(p.get("reserved"))
        m.count = max(m.count, int(p.get("count", 1)))

        contradiction = None
        if p.get("vitals_ok") and inc.type in ("cardiac_arrest", "unconscious_person"):
            contradiction = "un aviso dice que no respira o no reacciona y otro que sí"
        elif inc.type in p.get("negated", ()):
            contradiction = "un aviso lo confirma y otro lo niega"
        elif not p["type"].startswith("unknown") and abs(p["severity"] - inc.severity) >= CONTRADICTION_GAP:
            contradiction = f"las versiones no coinciden en la gravedad ({inc.severity} frente a {p['severity']})"

        data: dict[str, Any] = {"quiet_min": quiet_min, "gap_min": t - inc.t_open}
        if p["zone"] and not inc.zone:
            inc.zone = p["zone"]
            m.missing = [x for x in m.missing if x != "zone"]
            m.dirty = m.dirty or f"ya se sabe la zona: {inc.zone}"
            data["zone_found"] = inc.zone

        if contradiction:
            m.contradicted = True
            inc.confidence = round(inc.confidence * 0.6, 2)
            inc.notes.append(contradiction)
            # ante la duda manda la versión grave: no se rebaja nada por un aviso contradictorio
            if p["severity"] > inc.severity and p["confidence"] >= CONFIRM_BELOW:
                self._upgrade(inc, m, p, t)
            return TriageEvent("contradiction", inc, contradiction, data)

        if p["type"].startswith("unknown"):
            inc.confidence = round(min(0.99, inc.confidence + 0.02), 2)
        elif new_source:
            inc.confidence = round(1 - (1 - inc.confidence) * (1 - 0.6 * p["confidence"]), 2)
        else:
            inc.confidence = round(min(0.99, inc.confidence + 0.02), 2)
        if not p["type"].startswith("unknown") and m.missing and "type" in m.missing:
            m.missing.remove("type")
            self._upgrade(inc, m, p, t, force=True)
        elif p["severity"] > inc.severity and p["confidence"] >= CONFIRM_BELOW:
            self._upgrade(inc, m, p, t)
        if not p["type"].startswith("unknown") and p["confidence"] >= CONFIRM_BELOW and (m.checked_empty is None or p.get("staff")):
            # mismo incidente, pero este aviso pide algo que aún no se había pedido (no multiplica: es el máximo)
            grown = {k: n for k, n in p["needs"].items() if n > inc.needs.get(k, 0)}
            if grown:
                inc.needs.update(grown)
                m.dirty = m.dirty or "un aviso nuevo pide " + ", ".join(f"{n} de {k}" for k, n in grown.items())
        if m.hold and inc.confidence >= CONFIRM_BELOW:
            m.hold = False
            m.dirty = "confirmado por un segundo aviso"
            data["confirmed"] = True
        return TriageEvent("merge", inc, "", data)

    def _upgrade(self, inc: Incident, m: IncidentMeta, p: dict[str, Any], t: int, force: bool = False) -> None:
        spec = spec_for(p["type"], p["family"])
        before = dict(inc.needs)
        if force or spec.severity >= spec_for(inc.type, inc.family).severity:
            inc.type, inc.family = p["type"], Family(p["family"])
            m.group, m.heat = spec.group, spec.heat
            if spec.deadline:
                inc.deadline = min(inc.deadline, t + spec.deadline) if inc.deadline else t + spec.deadline
        inc.severity = max(inc.severity, p["severity"]) if not force else p["severity"]
        for k, n in p["needs"].items():
            inc.needs[k] = max(inc.needs.get(k, 0), n)
        became_vital = bool(p.get("life_threat")) and not m.life_threat
        m.life_threat = m.life_threat or bool(p.get("life_threat"))
        m.threat = m.threat or bool(p.get("threat"))
        if became_vital:
            m.hold = False
        if inc.needs != before or became_vital or force:
            m.dirty = m.dirty or f"sube la gravedad a {inc.severity} ({inc.type})"

    def _all_clear(self, inc: Incident, report: Report, p: dict[str, Any], t: int) -> TriageEvent:
        m = self.meta[inc.id]
        inc.reports.append(report.id)
        m.last_report_t = t
        credible = bool(p.get("staff")) or p["confidence"] >= 0.8
        if not credible:
            inc.confidence = round(inc.confidence * 0.6, 2)
            if m.life_threat or inc.confidence >= 0.3:
                m.contradicted = True
                inc.notes.append("un aviso del público dice que no pasa nada")
                return TriageEvent("contradiction", inc, "un aviso lo confirma y otro dice que no pasa nada")
        return TriageEvent("all_clear", inc, f"{report.source or 'un aviso'} dice que no pasa nada")

    # ---------------------------------------------------------------- falsas alarmas y patrones
    def expire_holds(self, t: int) -> list[Incident]:
        """Retenidos que nadie confirmó a tiempo."""
        return [i for i in self.live if self.meta[i.id].hold and t - self.meta[i.id].hold_since >= HOLD_MAX]

    def detect_patterns(self, t: int) -> list[TriageEvent]:
        events = []
        for name, ptype, n, window, same_zone in PATTERNS:
            if self._pattern_until.get(name, -1) >= t:
                continue
            members = [i for i in self.incidents.values()
                       if t - i.t_open <= window and i.status != IncidentStatus.FALSE_ALARM
                       and not self.meta[i.id].hold and self._counts_for(name, i)]
            zones: dict[str, int] = {}
            for i in members:
                if i.zone:
                    zones[i.zone] = zones.get(i.zone, 0) + max(1, self.meta[i.id].count)
            total = sum(max(1, self.meta[i.id].count) for i in members)
            zone = min(zones, key=lambda z: (-zones[z], z)) if zones else None
            if same_zone:
                total = zones.get(zone, 0) if zone else 0
                members = [i for i in members if i.zone == zone]
            if total < n:
                continue
            self._pattern_until[name] = t + 30
            spec = TYPES[ptype]
            inc = Incident(id=self.new_id(), family=spec.family, type=ptype, zone=zone, severity=spec.severity,
                           t_open=t, deadline=t + spec.deadline, needs=dict(spec.needs),
                           reports=[r for i in members for r in i.reports], confidence=0.9)
            self.incidents[inc.id] = inc
            self.meta[inc.id] = IncidentMeta(group=spec.group, origin="pattern", last_report_t=t, dirty="patrón",
                                             members=[i.id for i in members], sitewide=zone is None)
            self.live.append(inc)
            events.append(TriageEvent("pattern", inc, "", {"n": total, "window": window,
                                                           "members": [i.id for i in members]}))
        return events

    def _counts_for(self, pattern: str, inc: Incident) -> bool:
        m = self.meta[inc.id]
        if pattern == "heat":
            return m.heat
        if pattern == "intox":
            return m.group == "intox"
        return inc.family == Family.AGGRESSION and m.origin != "pattern"


__all__ = ["Triage", "TriageEvent", "IncidentMeta", "CLOSED", "CONFIRM_BELOW", "HOLD_MAX", "MERGE_WINDOW"]
