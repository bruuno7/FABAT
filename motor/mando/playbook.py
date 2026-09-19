"""El manual que aprende: lecciones en JSON que ajustan cómo prioriza y planifica Mando.

Formato de una lección (todas las claves de `when` y `then` son opcionales):

    {"id": "L-014",
     "text": "frase corta para la pantalla",
     "when": {"type": "gate_saturation" | ["a", "b"],   "family": "crowd",
              "zone": "gate_b" | [...],                 "zone_kind": "gate",
              "severity_min": 7,
              "weather": {"temp_c_above": 35, "wind_kmh_above": 50, "rain": true, "alert": "amarilla"},
              "state": {"show_phase": "headliner", "day": 2, "zone_density_above": 4.0,
                        "zone_ratio_above": 0.8, "zone_state": "restricted"}},
     "then": {"priority_boost": 1.0,                              # se suma, acotado a ±2 en total
              "prefer_resource": "ambulance" | "med_2",           # tipo o id de recurso
              "pre_action": {"kind": "broadcast", "zone": "...", "params": {...}},   # obligatoria antes del plan
              "forbid_action": {"kind": "reroute", "to": "gate_a"},                 # `to`/`zone`/`state` opcionales
              "assumption_threshold": {"zone_occupancy_below": {"ratio": 0.7}}},    # por tipo de supuesto
     "source": "run c-000123 | veto del operador",
     "evidence_n": 12}

Una lección NUNCA puede rebajar la aprobación humana: eso lo decide `autonomy.py`, que no lee el manual.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SEED_PATH = Path(__file__).with_name("playbook.seed.json")


@dataclass
class Adjustments:
    boost: float = 0.0
    prefer: list[str] = field(default_factory=list)
    pre_actions: list[tuple[str, dict]] = field(default_factory=list)   # (id de lección, acción)
    forbid: list[tuple[str, dict]] = field(default_factory=list)
    thresholds: dict[str, dict[str, Any]] = field(default_factory=dict)
    threshold_source: dict[str, str] = field(default_factory=dict)      # tipo de supuesto -> id de lección
    applied: list[str] = field(default_factory=list)                    # ids que encajaron

    def forbidden(self, kind: str, **fields: Any) -> str | None:
        """Id de la lección que prohíbe esta acción, o None."""
        for lid, rule in self.forbid:
            if str(rule.get("kind")) != str(kind):
                continue
            if all(k not in rule or _match(rule[k], v) for k, v in fields.items()):
                return lid
        return None

    def threshold(self, check_kind: str, key: str, default: float) -> float:
        return self.thresholds.get(check_kind, {}).get(key, default)


_EMPTY = Adjustments()


def _match(expected: Any, value: Any) -> bool:
    if isinstance(expected, list):
        return any(str(e) == str(value) for e in expected)
    return str(expected) == str(value)


class Playbook:
    def __init__(self, lessons: list[dict[str, Any]] | None = None) -> None:
        self.lessons: list[dict[str, Any]] = []
        self._by_key: dict[str, list[dict]] = {}
        for lesson in lessons or []:
            self.add(lesson)

    # ---------------------------------------------------------------- persistencia
    @classmethod
    def load(cls, path: str | Path | None = None) -> "Playbook":
        p = Path(path) if path else SEED_PATH
        if not p.exists():
            return cls()
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls(data["lessons"] if isinstance(data, dict) else data)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({"lessons": self.lessons}, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")

    def add(self, lesson: dict[str, Any]) -> None:
        if not lesson.get("id"):
            lesson = {**lesson, "id": f"L-{len(self.lessons) + 1:03d}"}
        lesson.setdefault("when", {})
        lesson.setdefault("then", {})
        self.lessons.append(lesson)
        # Índice por tipo o familia para no recorrer todo el manual en cada tick
        when = lesson["when"]
        keys = when.get("type") or when.get("family") or "*"
        for k in keys if isinstance(keys, list) else [keys]:
            self._by_key.setdefault(str(k), []).append(lesson)

    def get(self, lesson_id: str) -> dict[str, Any] | None:
        return next((x for x in self.lessons if x["id"] == lesson_id), None)

    # ---------------------------------------------------------------- consulta
    @staticmethod
    def _holds(when: dict[str, Any], ctx: dict[str, Any]) -> bool:
        for key in ("type", "family", "zone", "zone_kind"):
            if key in when and not _match(when[key], ctx.get(key)):
                return False
        if ctx.get("severity", 0) < when.get("severity_min", 0):
            return False
        weather = ctx.get("weather") or {}
        for k, v in (when.get("weather") or {}).items():
            if k.endswith("_above"):
                if not (weather.get(k[:-6]) is not None and weather[k[:-6]] > v):
                    return False
            elif k.endswith("_below"):
                if not (weather.get(k[:-6]) is not None and weather[k[:-6]] < v):
                    return False
            elif not _match(v, weather.get(k)):
                return False
        clock = ctx.get("clock") or {}
        for k, v in (when.get("state") or {}).items():
            if k == "zone_density_above":
                if not ctx.get("zone_density", 0.0) > v:
                    return False
            elif k == "zone_ratio_above":
                if not ctx.get("zone_ratio", 0.0) > v:
                    return False
            elif k == "zone_state":
                if not _match(v, ctx.get("zone_state")):
                    return False
            elif not _match(v, clock.get(k)):
                return False
        return True

    def apply(self, ctx: dict[str, Any]) -> Adjustments:
        """Ajustes que el manual impone a un incidente en este contexto.
        ctx: type, family, zone, zone_kind, severity, weather, clock, zone_density, zone_ratio, zone_state."""
        if not self.lessons:
            return _EMPTY
        pool = (self._by_key.get(str(ctx.get("type")), ()), self._by_key.get(str(ctx.get("family")), ()),
                self._by_key.get("*", ()))
        adj: Adjustments | None = None
        for lessons in pool:
            for lesson in lessons:
                if lesson["id"] in (adj.applied if adj else ()) or not self._holds(lesson["when"], ctx):
                    continue
                adj = adj or Adjustments()
                adj.applied.append(lesson["id"])
                then = lesson["then"]
                adj.boost += float(then.get("priority_boost", 0.0))
                if then.get("prefer_resource"):
                    adj.prefer.append(str(then["prefer_resource"]))
                if then.get("pre_action"):
                    adj.pre_actions.append((lesson["id"], then["pre_action"]))
                if then.get("forbid_action"):
                    adj.forbid.append((lesson["id"], then["forbid_action"]))
                for kind, values in (then.get("assumption_threshold") or {}).items():
                    adj.thresholds.setdefault(kind, {}).update(values)
                    adj.threshold_source[kind] = lesson["id"]
        return adj or _EMPTY

    def describe(self, lesson_id: str) -> str:
        lesson = self.get(lesson_id) or {}
        return lesson.get("text") or json.dumps(lesson.get("then", {}), ensure_ascii=False)
