"""Memoria operativa: RESULTADOS OBSERVADOS durante la jornada, no reglas.

Qué guarda (todo con su N), siempre a partir de lo que Mando VE: la `Observation` de cada minuto, sus propias
acciones y lo que le contestan por `CommsAPI`. Nunca `world.truth()`, nunca `Report.truth_incident`, nunca
`expected` de un caso: este módulo no importa nada del simulador ni de `motor/cases` (hay test).

  a) reposiciones: minutos reales desde que se PIDE un RESUPPLY hasta que acaba (DONE), por punto de agua; ritmo de
     consumo observado (`flags.water_l` minuto a minuto) y roturas de stock vistas (depósito a 0);
  b) contactos: por recurso y canal, aceptó / rechazó / no contestó y minutos hasta aceptar;
  c) localización: avisos que llegaron sin zona y minutos hasta saberla (ASK → respuesta); y, en zonas amplias,
     minutos que el equipo tardó en dar con la persona (lo cuenta el equipo al llegar: `params.search_min`);
  d) duplicados: avisos por incidente, minutos entre el primer aviso y los repetidos, equipos movidos para nada
     cuando ya había otro incidente igual en la misma zona;
  e) alertas meteorológicas: aviso, preparativos y desenlace (llegó / no llegó, minutos hasta desactivarse).

Se serializa a JSON (`motor/mando/memory.day1.json`). `tuning.py` la lee y propone cambios de PARÁMETROS.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..contracts import Action, ActionKind, ActionStatus, Family, Incident, Resource, Zone

DEFAULT_PATH = Path(__file__).parent / "memory.day1.json"
_JUMP_L = 400.0          # un salto mayor en un minuto no es consumo: es un relleno o una avería


def dumps(data: dict[str, Any]) -> str:
    """JSON legible: sangrado, pero las listas de minutos en una sola línea (si no, el fichero tiene 12.000 líneas)."""
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)
    return re.sub(r"\[\s+((?:-?[\d.]+,\s+)*-?[\d.]+)\s+\]", lambda m: "[" + re.sub(r"\s+", " ", m.group(1)) + "]", text)


def _empty() -> dict[str, Any]:
    return {"version": 1, "runs": 0, "minutes_observed": 0,
            "resupply": {},      # punto -> {"n", "minutes": [...], "litres_at_request": [...], "dry_before_refill": n}
            "consumption": {},   # punto -> {"n_ticks", "sum_l", "max_l_per_min"}
            "stockouts": {},     # punto -> {"n", "dry_minutes"}
            "contacts": {},      # recurso -> {"kind", "channels": {canal: {"sent","accept","reject","no_answer","accept_min":[...]}},
                                 #             "lost_min": [...]}   minutos perdidos en cada intento fallido
            "locate": {"no_zone_reports": 0, "ask_zone_min": [], "ask_zone_unanswered": 0,
                       "search": {}},   # zona -> {"n", "minutes": [...], "with_point": {"n", "minutes": [...]}}
            "duplicates": {"incidents": 0, "incidents_with_duplicates": 0, "reports": 0, "merge_gap_min": [], "merge_quiet_min": [],
                           "teams_moved_for_nothing": 0, "teams_moved_by_duplicate": 0, "missed_gap_min": []},
            "weather": {"episodes": []}}


class OperationalMemory:
    """Se engancha a Mando (`Mando(memory=...)`), que la llama en cada punto donde OBSERVA algo."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = data if data is not None else _empty()
        self._level: dict[str, float] = {}             # último nivel visto por punto de agua
        self._dry: set[str] = set()
        self._resupply: dict[str, dict[str, Any]] = {}  # acción RESUPPLY viva -> {zone, t, dry}
        self._sent: dict[str, dict[str, Any]] = {}      # intento de contacto vivo -> {resource, channel, t}
        self._asks: dict[str, int] = {}                 # ASK de zona vivo -> minuto en que salió
        self._episode: dict[str, Any] | None = None
        self._calm = 0
        self._t = 0

    # ------------------------------------------------------------------ lo que se ve en cada minuto
    def on_tick(self, t: int, zones: dict[str, Zone], weather: dict[str, Any]) -> None:
        d = self.data
        self._t = t
        d["minutes_observed"] += 1
        for zid, z in zones.items():
            if "water_l" not in z.flags:
                continue
            level = float(z.flags.get("water_l") or 0.0)
            prev = self._level.get(zid)
            if prev is not None and 0 < prev - level < _JUMP_L:
                c = d["consumption"].setdefault(zid, {"n_ticks": 0, "sum_l": 0.0, "max_l_per_min": 0.0})
                c["n_ticks"] += 1
                c["sum_l"] = round(c["sum_l"] + prev - level, 1)
                c["max_l_per_min"] = max(c["max_l_per_min"], round(prev - level, 1))
            s = d["stockouts"].setdefault(zid, {"n": 0, "dry_minutes": 0})
            if level <= 0:
                s["dry_minutes"] += 1
                if zid not in self._dry:
                    self._dry.add(zid)
                    s["n"] += 1
                for job in self._resupply.values():
                    if job["zone"] == zid:
                        job["dry"] = True
            else:
                self._dry.discard(zid)
            self._level[zid] = level
        self._weather(t, weather)

    def _weather(self, t: int, w: dict[str, Any]) -> None:
        level = int(w.get("wind_level") or 0)
        wind = float(w.get("wind_kmh") or 0.0)
        ep = self._episode
        if ep is None:
            if level >= 1:
                self._episode = {"t": t, "alert": w.get("alert"), "first_level": level, "max_level": level,
                                 "max_wind_kmh": wind, "rain": bool(w.get("rain")), "preparations": [],
                                 "structure_reports": 0, "minutes_to_clear": None, "outcome": None,
                                 "minutes_to_level2": 0 if level >= 2 else None}
                self._calm = 0
            return
        if level >= 2 and ep["minutes_to_level2"] is None:
            ep["minutes_to_level2"] = t - ep["t"]
        ep["max_level"], ep["max_wind_kmh"] = max(ep["max_level"], level), max(ep["max_wind_kmh"], wind)
        self._calm = self._calm + 1 if level == 0 else 0
        if self._calm >= 3:     # tres minutos seguidos por debajo del primer escalón: la alerta se da por desactivada
            ep["minutes_to_clear"] = t - self._calm + 1 - ep["t"]
            self._close_episode()

    def _close_episode(self) -> None:
        ep, self._episode = self._episode, None
        if ep is None:
            return
        ep["outcome"] = "llego" if ep["max_level"] >= 2 or ep["structure_reports"] else "no_llego"
        self.data["weather"]["episodes"].append(ep)

    # ------------------------------------------------------------------ lo que Mando hace y lo que le contestan
    def on_sent(self, a: Action, resource: Resource | None) -> None:
        """Mando llama o escribe a alguien."""
        if a.kind == ActionKind.RESUPPLY and a.zone:
            level = self._level.get(a.zone)
            self._resupply[a.id] = {"zone": a.zone, "t": a.t, "dry": level is not None and level <= 0, "litres": level}
        if resource is not None and a.kind in (ActionKind.DISPATCH, ActionKind.RESUPPLY):
            c = self.data["contacts"].setdefault(resource.id, {"kind": str(resource.kind), "channels": {}, "lost_min": []})
            ch = c["channels"].setdefault(str(a.channel or "voice"), {"sent": 0, "accept": 0, "reject": 0, "no_answer": 0,
                                                                     "accept_min": []})
            ch["sent"] += 1
            self._sent[a.id] = {"resource": resource.id, "channel": str(a.channel or "voice"), "t": self._t}
        if a.kind == ActionKind.ASK and a.params.get("purpose") == "zone":
            self._asks[a.id] = self._t

    def _contact_result(self, action_id: str, result: str, t: int) -> None:
        job = self._sent.pop(action_id, None)
        if job is None:          # ya contado (el mundo y la llamada dicen lo mismo): un intento, un resultado
            return
        c = self.data["contacts"][job["resource"]]
        ch = c["channels"][job["channel"]]
        ch[result] += 1
        if result == "accept":
            ch["accept_min"].append(t - job["t"])
        else:
            c["lost_min"].append(max(1, t - job["t"]))

    def on_reply(self, a: Action, result: str, t: int) -> None:
        """Respuesta por `CommsAPI`: accept | reject | no_answer | answer."""
        if result in ("accept", "reject", "no_answer"):
            self._contact_result(a.id, result, t)
        elif result == "answer" and a.id in self._asks:
            self.data["locate"]["ask_zone_min"].append(t - self._asks.pop(a.id))

    def on_ask_unanswered(self, a: Action) -> None:
        if self._asks.pop(a.id, None) is not None:
            self.data["locate"]["ask_zone_unanswered"] += 1

    def on_action_status(self, a: Action, t: int) -> None:
        """Cambio de estado de una acción propia, tal y como llega en `Observation.action_results`."""
        error = str(a.params.get("error") or "")
        if a.kind in (ActionKind.DISPATCH, ActionKind.RESUPPLY):
            if a.status == ActionStatus.REJECTED or error == "rejected":
                self._contact_result(a.id, "reject", t)
            elif a.status == ActionStatus.FAILED and error in ("no_answer", "resource_offline"):
                self._contact_result(a.id, "no_answer", t)
            elif a.status == ActionStatus.DONE:
                self._contact_result(a.id, "accept", t)     # llegó sin que nadie dijera «acepto»: aceptó
        if a.kind == ActionKind.RESUPPLY and a.id in self._resupply and a.status in (
                ActionStatus.DONE, ActionStatus.FAILED, ActionStatus.REJECTED, ActionStatus.CANCELLED):
            job = self._resupply.pop(a.id)
            if a.status == ActionStatus.DONE:
                r = self.data["resupply"].setdefault(job["zone"], {"n": 0, "minutes": [], "litres_at_request": [],
                                                                   "dry_before_refill": 0})
                r["n"] += 1
                r["minutes"].append(t - job["t"])
                r["litres_at_request"].append(round(job["litres"] or 0.0))
                r["dry_before_refill"] += bool(job["dry"])
        if a.kind == ActionKind.DISPATCH and a.status == ActionStatus.DONE and "search_min" in a.params and a.zone:
            s = self.data["locate"]["search"].setdefault(a.zone, {"n": 0, "minutes": [], "with_point": {"n": 0, "minutes": []}})
            s = s["with_point"] if a.params.get("point") else s
            s["n"] += 1
            s["minutes"].append(int(a.params["search_min"]))

    # ------------------------------------------------------------------ avisos, duplicados, preparativos
    def on_incident(self, inc: Incident, zone_missing: bool) -> None:
        self.data["duplicates"]["incidents"] += 1
        self.data["duplicates"]["reports"] += 1
        if zone_missing:
            self.data["locate"]["no_zone_reports"] += 1

    def on_merge(self, inc: Incident, gap_min: int, quiet_min: int = 0) -> None:
        """Aviso repetido fundido: minutos desde el PRIMER aviso del incidente y desde el aviso ANTERIOR."""
        d = self.data["duplicates"]
        d["reports"] += 1
        d["merge_gap_min"].append(int(gap_min))
        d["merge_quiet_min"].append(int(quiet_min))
        if len(inc.reports) == 2:
            d["incidents_with_duplicates"] += 1

    def on_wasted(self, inc: Incident, twin_gap_min: int | None) -> None:
        """Un equipo llegó y no había nada. `twin_gap_min`: si Mando tenía OTRO incidente del mismo grupo en la misma
        zona, minutos entre los dos (un duplicado que no supo fundir); None si no lo había (falsa alarma)."""
        d = self.data["duplicates"]
        d["teams_moved_for_nothing"] += 1
        if twin_gap_min is not None:
            d["teams_moved_by_duplicate"] += 1
            d["missed_gap_min"].append(int(twin_gap_min))

    def on_preparation(self, a: Action, inc: Incident | None, text: str = "") -> None:
        """Acción lanzada por un incidente meteorológico mientras hay una alerta abierta."""
        if self._episode is None or inc is None:
            return
        if inc.family == Family.WEATHER:
            self._episode["preparations"].append(str(a.kind))
        elif inc.type == "structure_risk":
            self._episode["structure_reports"] += 1

    def end_run(self) -> None:
        self._close_episode()
        self.data["runs"] += 1

    # ------------------------------------------------------------------ JSON
    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.data))

    @classmethod
    def merge(cls, parts: list[dict[str, Any]]) -> "OperationalMemory":
        """Suma las memorias de muchas ejecuciones (una «jornada») en una sola. Determinista: en el orden dado."""
        out = cls()
        for p in parts:
            _add(out.data, p)
        return out

    def save(self, path: str | Path | None = None, source: dict[str, Any] | None = None) -> Path:
        path = Path(path) if path else DEFAULT_PATH
        data = self.to_dict()
        if source:
            data["source"] = source
        data["n_by_parameter"] = self.n_by_parameter()
        path.write_text(dumps(data), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path | None = None) -> "OperationalMemory":
        data = json.loads(Path(path or DEFAULT_PATH).read_text(encoding="utf-8"))
        base = _empty()
        _add(base, {k: v for k, v in data.items() if k in base})
        return cls(base)

    def n_by_parameter(self) -> dict[str, Any]:
        """N de observaciones detrás de cada parámetro que `tuning.py` puede proponer."""
        d = self.data
        by_kind: dict[str, int] = {}
        for c in d["contacts"].values():
            by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + sum(ch["sent"] for ch in c["channels"].values())
        return {"resupply_lead_min": {z: r["n"] for z, r in d["resupply"].items()},
                "contact_order": by_kind,
                "require_precise_location": {z: s["n"] for z, s in d["locate"]["search"].items()},
                "duplicate_window_min": len(d["duplicates"]["merge_gap_min"]) + len(d["duplicates"]["missed_gap_min"]),
                "weather_followup": len(d["weather"]["episodes"])}


def _add(into: dict[str, Any], part: dict[str, Any]) -> None:
    """Suma recursiva: números se suman, listas se concatenan, `max_*` toma el máximo, el resto se conserva."""
    for k, v in part.items():
        if k == "version":
            continue
        if isinstance(v, dict):
            _add(into.setdefault(k, {}), v)
        elif isinstance(v, list):
            into.setdefault(k, [])
            into[k] = into[k] + v
        elif isinstance(v, bool) or not isinstance(v, (int, float)):
            into.setdefault(k, v)
        elif k.startswith("max_"):
            into[k] = max(into.get(k, v), v)
        else:
            into[k] = round(into.get(k, 0) + v, 1) if isinstance(v, float) else into.get(k, 0) + v


__all__ = ["OperationalMemory", "DEFAULT_PATH", "dumps"]
