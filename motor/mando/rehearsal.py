"""Ensayo previo: antes de ejecutar una decisión con efectos de flujo o de ruta, Mando la prueba en un GEMELO del
recinto (copia del estado de ahora, sin futuro) y elige entre alternativas con un criterio explícito.

Del gemelo solo se usa `apply(action)`, `step()` y `observe()` (zonas, recursos). Nunca `truth()`: el gemelo conserva
los incidentes verdaderos y leerlos sería trampa. Horizonte corto (12 min): el gemelo supone que una oleada en curso
sigue al ritmo actual, así que a 30 min sobreestima; por eso los supuestos se escriben a ese horizonte y se reensaya
al reevaluar.

Criterio de elección, en este orden: (1) nadie por encima de 6,5/m² (aplastamiento); (2) menos minutos por encima de
4/m² sumando las zonas vigiladas; (3) pico de densidad más bajo; (4) la alternativa menos intrusiva (la primera de la lista).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable

from ..contracts import Action, ActionStatus

HORIZON_MIN = 12
BUDGET_PER_TICK = 20
SAFE_DENSITY = 4.0       # por debajo, un desvío se ejecuta solo; por encima, lo decide una persona
CRUSH_DENSITY = 6.5


def es(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


@dataclass
class Outcome:
    label: str
    actions: list[Action]
    minutes: int = 0
    peak: dict[str, float] = field(default_factory=dict)        # zona -> densidad máxima
    peak_at: dict[str, int] = field(default_factory=dict)       # zona -> minuto (relativo) del máximo
    over4: dict[str, int] = field(default_factory=dict)         # zona -> minutos por encima de 4/m²
    crush_at: dict[str, int] = field(default_factory=dict)      # zona -> primer minuto por encima de 6,5/m²
    final: dict[str, float] = field(default_factory=dict)
    arrival: dict[str, int] = field(default_factory=dict)       # recurso -> minuto en que llega (BUSY en destino)

    @property
    def worst(self) -> float:
        return max(self.peak.values(), default=0.0)

    @property
    def ok(self) -> bool:
        return self.worst < SAFE_DENSITY

    @property
    def key(self) -> tuple:
        return (bool(self.crush_at), sum(self.over4.values()), round(self.worst, 2))

    def zone_text(self, zone: str, name: str | None = None) -> str:
        return f"{name or zone} {es(self.peak.get(zone, 0.0))}/m² en {self.peak_at.get(zone, 0)} min"

    def line(self, names: dict[str, str]) -> str:
        zone = max(self.peak, key=lambda z: self.peak[z]) if self.peak else None
        body = self.zone_text(zone, names.get(zone)) if zone else "sin datos"
        return f"{self.label} → {body} {'✓' if self.ok else '✗'}"

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "minutes": self.minutes, "peak_density": {z: round(v, 2) for z, v in self.peak.items()},
                "peak_at_min": dict(self.peak_at), "minutes_over_4": dict(self.over4), "crush_at_min": dict(self.crush_at),
                "final_density": {z: round(v, 2) for z, v in self.final.items()}, "ok": self.ok}


class Rehearsal:
    """`twin` es un callable sin argumentos que devuelve un gemelo del mundo actual (p. ej. `world.twin`)."""

    def __init__(self, twin: Callable[[], Any] | None, horizon: int = HORIZON_MIN, budget: int = BUDGET_PER_TICK) -> None:
        self.twin = twin
        self.horizon = horizon
        self.budget = budget
        self.used = 0            # ensayos en este tick (Mando lo pone a cero en cada tick)
        self.total = 0

    @property
    def available(self) -> bool:
        return self.twin is not None and self.used < self.budget

    def run(self, label: str, actions: list[Action], watch: list[str], horizon: int | None = None,
            resources: list[str] | None = None) -> Outcome | None:
        """Ensaya `actions` en un gemelo y devuelve lo que pasa en las zonas `watch`. None si no hay gemelo o presupuesto."""
        if not self.available:
            return None
        self.used += 1
        self.total += 1
        try:
            tw = self.twin()
            for i, a in enumerate(actions):   # copias: el gemelo muta las acciones y las de verdad no se tocan
                tw.apply(replace(a, id=f"E{self.total}-{i}", params=dict(a.params), status=ActionStatus.EXECUTING))
            out = Outcome(label, actions, minutes=horizon or self.horizon)
            for minute in range(1, out.minutes + 1):
                tw.step()
                obs = tw.observe()
                for z in watch:
                    zone = obs.zones.get(z)
                    if zone is None:
                        continue
                    d = zone.occupancy / zone.area_m2 if zone.area_m2 else 0.0
                    if d > out.peak.get(z, -1.0):
                        out.peak[z], out.peak_at[z] = d, minute
                    if d > SAFE_DENSITY:
                        out.over4[z] = out.over4.get(z, 0) + 1
                    if d > CRUSH_DENSITY and z not in out.crush_at:
                        out.crush_at[z] = minute
                    out.final[z] = d
                for rid in resources or ():
                    r = obs.resources.get(rid)
                    if r is not None and rid not in out.arrival and str(r.status) == "busy":
                        out.arrival[rid] = minute
            return out
        except Exception:   # un gemelo que falla no puede tumbar a Mando: se sigue con la proyección analítica
            return None

    @staticmethod
    def choose(outcomes: list[Outcome]) -> Outcome | None:
        return min(outcomes, key=lambda o: o.key) if outcomes else None
