"""Contrato común del motor. Todos los módulos importan de aquí y nadie más define estos tipos.

Solo biblioteca estándar. Todo es serializable con `to_dict()` (JSON plano) para el servidor,
el banco de pruebas y los ficheros de casos. El tiempo es siempre `t`: minutos enteros desde el
inicio de la ejecución. Nada de reloj real ni de aleatoriedad sin semilla: mismo caso + misma
semilla = misma ejecución.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Protocol


class _Str(str, Enum):
    def __str__(self) -> str:  # para que el JSON y los logs lleven el valor, no «Clase.MIEMBRO»
        return self.value


class Family(_Str):
    CROWD = "crowd"            # aglomeraciones y flujo
    MEDICAL = "medical"
    WEATHER = "weather"
    AGGRESSION = "aggression"  # agresiones, punto violeta
    SUPPLY = "supply"          # se acaba el agua, la comida, el combustible
    INFRA = "infra"            # luz, estructuras, pago, baños, red
    RESOURCE = "resource"      # un recurso propio falla, no contesta o rechaza
    INFO = "info"              # aviso ambiguo, duplicado, contradictorio o falso
    EXTERNAL = "external"      # transporte, amenaza, artista


class Channel(_Str):
    VOICE = "voice"        # llamada (personal del festival)
    SMS = "sms"
    WHATSAPP = "whatsapp"  # público y jurado
    SENSOR = "sensor"      # contador de aforo, estación meteorológica
    RADIO = "radio"
    OPERATOR = "operator"  # lo teclea la persona del centro de control


class ResourceKind(_Str):
    SECURITY = "security"
    MEDICAL = "medical"
    AMBULANCE = "ambulance"
    TECH = "tech"            # técnicos de infraestructura
    LOGISTICS = "logistics"  # reparto de agua y suministros
    VOLUNTEER = "volunteer"


class ResourceStatus(_Str):
    AVAILABLE = "available"
    EN_ROUTE = "en_route"
    BUSY = "busy"
    OFFLINE = "offline"  # lesionado, fin de turno, bloqueado, no contesta


class IncidentStatus(_Str):
    OPEN = "open"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    FALSE_ALARM = "false_alarm"
    FAILED = "failed"  # se pasó el plazo sin atender: cuenta como fallo en las métricas


class ActionKind(_Str):
    DISPATCH = "dispatch"              # mandar un recurso a un incidente
    RECALL = "recall"                  # quitarle un recurso a una tarea menor
    NOTIFY = "notify"                  # avisar a una persona o canal (sin pedir respuesta)
    ASK = "ask"                        # pedir el dato que falta antes de decidir
    SET_ZONE = "set_zone"              # abrir, restringir o cerrar una zona o puerta
    REROUTE = "reroute"                # desviar el flujo de una zona a otra
    BROADCAST = "broadcast"            # megafonía o pantallas
    REQUEST_EXTERNAL = "request_external"  # 112, policía, bomberos
    EVACUATE = "evacuate"
    STOP_SHOW = "stop_show"
    RESUPPLY = "resupply"
    MERGE = "merge"                    # varios avisos son el mismo incidente
    DISMISS = "dismiss"                # falsa alarma confirmada


class Autonomy(_Str):
    AUTO = "auto"        # el agente lo ejecuta solo
    APPROVE = "approve"  # espera el sí de la persona del centro de control


# Acciones que SIEMPRE requieren aprobación humana. Mando no puede saltárselo.
ALWAYS_APPROVE = frozenset({ActionKind.EVACUATE, ActionKind.STOP_SHOW, ActionKind.REQUEST_EXTERNAL})
# Cerrar una zona también la requiere; restringirla no (ver Action.params["state"]).


class ActionStatus(_Str):
    PROPOSED = "proposed"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"   # p. ej. llamada en curso al jefe de equipo
    DONE = "done"
    REJECTED = "rejected"     # la persona vetó, o el recurso dijo que no
    FAILED = "failed"         # no contestó, canal caído
    CANCELLED = "cancelled"   # el plan se tiró


@dataclass
class Base:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Zone(Base):
    id: str
    name: str
    kind: str                 # gate | stage_front | general | vip | food | toilets | pmr | medical | corridor | backstage | exit_transport
    area_m2: float
    capacity: int             # personas a partir de las cuales la zona está saturada
    occupancy: int = 0
    state: str = "open"       # open | restricted | closed
    neighbors: list[str] = field(default_factory=list)
    flags: dict[str, Any] = field(default_factory=dict)  # power, water_l, shade, structure_ok...

    @property
    def density(self) -> float:  # personas por m²
        return self.occupancy / self.area_m2 if self.area_m2 else 0.0


@dataclass
class Resource(Base):
    id: str
    kind: ResourceKind
    name: str
    zone: str                        # dónde está ahora
    status: ResourceStatus = ResourceStatus.AVAILABLE
    task: str | None = None          # id del incidente
    contact: str = ""                # teléfono del jefe de equipo (en la demo, un móvil del equipo o del jurado)
    eta: int = 0                     # minutos que le faltan para llegar
    shift_ends: int | None = None


@dataclass
class Report(Base):
    """Un aviso tal y como entra: texto libre o lectura de sensor. Es lo ÚNICO que ve Mando del mundo,
    junto con el estado observable (zonas y recursos). La verdad del caso no se le enseña."""
    id: str
    t: int
    channel: Channel
    text: str
    source: str = ""                 # quién avisa: «asistente», «jefe seguridad 2», «contador puerta B»
    lang: str = "es"
    zone_hint: str | None = None     # solo si el canal lo sabe (sensor, QR de zona)
    truth_incident: str | None = None  # SOLO para el banco de pruebas; Mando no debe leerlo


@dataclass
class Incident(Base):
    id: str
    family: Family
    type: str                        # p. ej. «cardiac_arrest», «gate_saturation»
    zone: str | None                 # None = todavía no se sabe dónde
    severity: int                    # 1..10
    t_open: int
    deadline: int | None = None      # minuto a partir del cual cuenta como FAILED
    needs: dict[str, int] = field(default_factory=dict)  # {"medical": 1, "security": 1}
    status: IncidentStatus = IncidentStatus.OPEN
    reports: list[str] = field(default_factory=list)
    assigned: list[str] = field(default_factory=list)
    confidence: float = 1.0          # cuánto se fía Mando de que existe y de dónde está
    priority: float = 0.0            # número que decide quién recibe el recurso escaso
    notes: list[str] = field(default_factory=list)


@dataclass
class Assumption(Base):
    """De qué depende el plan, escrito. Cuando deja de cumplirse, el plan se tira."""
    id: str
    text: str                        # «Puerta A por debajo del 80 % de su capacidad»
    check: dict[str, Any]            # {"kind": "zone_occupancy_below", "zone": "gate_a", "ratio": 0.8}
    holds: bool = True
    broken_at: int | None = None


@dataclass
class Action(Base):
    id: str
    kind: ActionKind
    t: int
    incident: str | None = None
    resource: str | None = None
    zone: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    autonomy: Autonomy = Autonomy.AUTO
    status: ActionStatus = ActionStatus.PROPOSED
    why: str = ""                    # explicación corta para la pantalla y el informe
    channel: Channel | None = None   # por dónde se ejecuta si implica hablar con alguien


@dataclass
class Plan(Base):
    id: str
    t: int
    objective: str
    steps: list[str] = field(default_factory=list)        # ids de Action, en orden
    assumptions: list[Assumption] = field(default_factory=list)
    supersedes: str | None = None
    invalidated_by: str | None = None                     # id de la Assumption rota
    why: str = ""


@dataclass
class LogEntry(Base):
    t: int
    kind: str      # report | incident | plan | assumption_broken | action | outcome | approval | lesson | chaos
    text: str
    ref: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Observation(Base):
    """Lo que Mando ve en cada tick."""
    t: int
    zones: dict[str, Zone]
    resources: dict[str, Resource]
    new_reports: list[Report]
    action_results: list[Action]          # acciones cuyo estado cambió desde el tick anterior
    weather: dict[str, Any] = field(default_factory=dict)  # temp_c, wind_kmh, rain, alert
    clock: dict[str, Any] = field(default_factory=dict)    # day, hhmm, show_phase


# ---------------------------------------------------------------- interfaces entre módulos

class WorldAPI(Protocol):
    """motor/world: simulador determinista del festival."""
    t: int
    def observe(self) -> Observation: ...
    def apply(self, action: Action) -> Action: ...     # devuelve la acción con su nuevo estado
    def inject(self, event: dict[str, Any]) -> None:   # golpe del jurado o de Caos (formato en INTERFACES.md)
        ...
    def step(self) -> None: ...                        # avanza un minuto
    def truth(self) -> dict[str, Any]: ...             # verdad completa, SOLO para métricas
    def clone(self) -> "WorldAPI": ...                 # para que Caos mire hacia delante
    def done(self) -> bool: ...


class CommsAPI(Protocol):
    """Hablar con personas. La implementación real llama a HappyRobot; la simulada contesta sola."""
    def send(self, action: Action, resource: Resource | None) -> None: ...
    def poll(self, t: int) -> list[dict[str, Any]]: ...  # respuestas: accept | reject | no_answer | answer


class AgentAPI(Protocol):
    """motor/mando y motor/baseline: mismo contrato para poder compararlos."""
    def tick(self, obs: Observation) -> list[Action]: ...
    def approve(self, action_id: str, ok: bool, note: str = "") -> None: ...
    def snapshot(self) -> dict[str, Any]: ...  # incidents, plans, actions, log, lessons: lo que pinta la pantalla
