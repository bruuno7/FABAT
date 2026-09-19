"""De la memoria operativa a CAMBIOS DE PARÁMETROS revisables por una persona. No son reglas ni lecciones.

    memory = OperationalMemory.load()                    # motor/mando/memory.day1.json
    proposals = propose(memory)                          # lista de `Change`, cada uno con valor anterior, nuevo, N y texto
    proposals.approve("C-01"); proposals.reject("C-02")  # lo decide una PERSONA
    proposals.write_approved()                           # solo lo aprobado pasa a motor/mando/params.approved.json
    Mando(params=Params.load())                          # Mando lo usa y deja en el log cada decisión que cambia

Parámetros que se pueden ajustar (lista cerrada, `TUNABLE`):
  resupply_lead_min[punto]        pedir la reposición cuando litros / consumo por minuto < este tiempo + margen
  contact_order[tipo de recurso]  a quién se llama primero, según la tasa de respuesta observada (suavizada)
  require_precise_location[zona]  en zonas amplias, pedir a quien avisa un punto concreto: torre, puesto, acceso
  duplicate_window_min            minutos en los que un aviso igual en la misma zona es el mismo incidente
  weather_followup_min            cada cuánto se revisa un aviso meteorológico abierto
  weather_standdown_min           minutos seguidos en calma para cancelar los preparativos de una alerta

LO QUE NUNCA SE AJUSTA (`SAFETY_LOCKED`): los criterios de seguridad. Que la tormenta no llegara ayer no enseña a
ignorar el aviso de hoy: el viento de parada, los escalones de viento, las densidades de alerta y de aplastamiento, y
qué exige aprobación humana no están en `TUNABLE`, `Params` rechaza un fichero que los traiga y hay un test.
Tampoco se proponen cambios «hacia el riesgo»: la reposición nunca se pide MÁS TARDE que el valor de ficha y la
ventana de duplicados nunca se acorta.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .memory import OperationalMemory

APPROVED_PATH = Path(__file__).parent / "params.approved.json"
PROPOSED_PATH = Path(__file__).parent / "params.proposed.json"

NOMINAL_RESUPPLY_MIN = 10     # valor «de ficha» del plan de operaciones: ~4 min de trayecto + 5 de llenado + 1
RESUPPLY_MARGIN_MIN = 3       # margen fijo sobre el tiempo de reposición
NOMINAL_DUPLICATE_WINDOW = 15
NOMINAL_FOLLOWUP_MIN = 5
FAIL_COST_MIN = 3.0           # minutos que se pierden cuando alguien no contesta, si no hay nada observado
MIN_N = 5                     # por debajo, «evidencia limitada»: cambio conservador y el operador simulado lo rechaza
SHRINK_K = 3                  # con N pequeño el valor nuevo se queda cerca del anterior: viejo + (obs − viejo)·N/(N+K)
PRIOR_N = 5                   # suavizado de tasas: cada recurso empieza con 5 llamadas «a la media de su tipo»
MAX_LEAD_MIN = 45
MAX_DUPLICATE_WINDOW = 30
MIN_STANDDOWN_MIN = 10

TUNABLE = ("resupply_lead_min", "contact_order", "require_precise_location", "duplicate_window_min",
           "weather_followup_min", "weather_standdown_min")
SAFETY_LOCKED = ("wind_stop_kmh", "wind_steps_kmh", "watch_density", "crush_density", "amb_max_density",
                 "always_approve", "approve_reroute_density", "confirm_below", "life_threat_dispatch")
SAFETY_NOTE = ("No cambia ningún criterio de seguridad: viento de parada 70 km/h, escalones 40/50/60, densidades de "
               "alerta y aprobación humana para parar, evacuar o pedir ayuda externa siguen igual.")


def _es(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def _pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return float(s[min(len(s) - 1, int(q * len(s)))])


# ---------------------------------------------------------------------------------------------- parámetros

class Params:
    """Configuración operativa de Mando. `Params.initial()` = valores de ficha; `Params.load()` = ficha + lo APROBADO."""

    def __init__(self, values: dict[str, Any] | None = None, evidence: dict[str, str] | None = None) -> None:
        values = dict(values or {})
        bad = [k for k in values if k not in TUNABLE]
        if bad:
            locked = [k for k in bad if k in SAFETY_LOCKED]
            raise ValueError(f"parámetros no ajustables: {bad}" + (f" (criterios de seguridad: {locked})" if locked else ""))
        self.resupply_lead_min: dict[str, int] = {str(k): int(v) for k, v in (values.get("resupply_lead_min") or {}).items()}
        self.contact_order: dict[str, dict[str, Any]] = dict(values.get("contact_order") or {})
        self.require_precise_location: dict[str, bool] = {str(k): bool(v) for k, v in
                                                          (values.get("require_precise_location") or {}).items()}
        self.duplicate_window_min = int(values.get("duplicate_window_min") or NOMINAL_DUPLICATE_WINDOW)
        self.weather_followup_min = int(values.get("weather_followup_min") or NOMINAL_FOLLOWUP_MIN)
        standdown = values.get("weather_standdown_min")
        self.weather_standdown_min: int | None = int(standdown) if standdown else None
        self.evidence = dict(evidence or {})        # "param[clave]" -> «N=6»: lo que se cita en el log
        # nunca hacia el riesgo, venga de donde venga el fichero
        self.resupply_lead_min = {z: max(NOMINAL_RESUPPLY_MIN, v) for z, v in self.resupply_lead_min.items()}
        self.duplicate_window_min = max(NOMINAL_DUPLICATE_WINDOW, self.duplicate_window_min)
        if self.weather_standdown_min is not None:
            self.weather_standdown_min = max(MIN_STANDDOWN_MIN, self.weather_standdown_min)

    @classmethod
    def initial(cls) -> "Params":
        return cls()

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Params":
        path = Path(path) if path else APPROVED_PATH
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data.get("values") or {}, data.get("evidence") or {})

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Params":
        data = data or {}
        return cls(data.get("values") or {}, data.get("evidence") or {})

    def to_dict(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        if self.resupply_lead_min:
            values["resupply_lead_min"] = dict(self.resupply_lead_min)
        if self.contact_order:
            values["contact_order"] = json.loads(json.dumps(self.contact_order))
        if self.require_precise_location:
            values["require_precise_location"] = dict(self.require_precise_location)
        if self.duplicate_window_min != NOMINAL_DUPLICATE_WINDOW:
            values["duplicate_window_min"] = self.duplicate_window_min
        if self.weather_followup_min != NOMINAL_FOLLOWUP_MIN:
            values["weather_followup_min"] = self.weather_followup_min
        if self.weather_standdown_min is not None:
            values["weather_standdown_min"] = self.weather_standdown_min
        return {"values": values, "evidence": dict(self.evidence)}

    # -- lo que consulta Mando -------------------------------------------------------------------
    def lead(self, zone: str) -> tuple[int, bool]:
        """(minutos de antelación, ¿es un valor aprendido?)."""
        if zone in self.resupply_lead_min:
            return self.resupply_lead_min[zone], True
        return NOMINAL_RESUPPLY_MIN, False

    def contact_penalty(self, kind: str, resource_id: str) -> float:
        """Minutos ESPERADOS que se pierden llamando a este recurso: (1 − tasa de respuesta) × coste de un intento fallido."""
        c = self.contact_order.get(kind)
        if not c or resource_id not in c.get("rate", {}):
            return 0.0
        return (1.0 - float(c["rate"][resource_id])) * float(c.get("fail_cost_min", FAIL_COST_MIN))

    def precise(self, zone: str | None) -> bool:
        return bool(zone) and bool(self.require_precise_location.get(zone))

    def cite(self, param: str, key: str | None = None) -> str:
        return self.evidence.get(f"{param}[{key}]" if key else param, "")


# ---------------------------------------------------------------------------------------------- propuestas

@dataclass
class Change:
    id: str
    param: str
    key: str | None
    old: Any
    new: Any
    n: int
    text: str                        # una línea para la pantalla
    evidence: dict[str, Any] = field(default_factory=dict)
    limited: bool = False            # N < MIN_N: «evidencia limitada», cambio conservador
    status: str = "proposed"         # proposed | approved | rejected
    decided_by: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Proposals:
    def __init__(self, changes: list[Change], unchanged: list[dict[str, Any]] | None = None,
                 base: Params | None = None) -> None:
        self.changes = changes
        self.unchanged = unchanged or []      # lo que se miró y NO se propone cambiar, con su porqué y su N
        self.base = base or Params.initial()

    def get(self, change_id: str) -> Change:
        for c in self.changes:
            if c.id == change_id:
                return c
        raise KeyError(change_id)

    def approve(self, change_id: str, by: str = "operador", note: str = "") -> Change:
        c = self.get(change_id)
        c.status, c.decided_by, c.note = "approved", by, note
        return c

    def reject(self, change_id: str, by: str = "operador", note: str = "") -> Change:
        c = self.get(change_id)
        c.status, c.decided_by, c.note = "rejected", by, note
        return c

    def approved_params(self) -> Params:
        """Ficha + SOLO lo aprobado. Lo propuesto sin decidir y lo rechazado no entra."""
        data = self.base.to_dict()
        values, evidence = data["values"], data["evidence"]
        for c in self.changes:
            if c.status != "approved":
                continue
            if c.key is None:
                values[c.param] = c.new
            else:
                values.setdefault(c.param, {})[c.key] = c.new
            evidence[f"{c.param}[{c.key}]" if c.key else c.param] = f"N={c.n}" + (", evidencia limitada" if c.limited else "")
        return Params(values, evidence)

    def to_dict(self) -> dict[str, Any]:
        return {"changes": [c.to_dict() for c in self.changes], "unchanged": list(self.unchanged),
                "safety_note": SAFETY_NOTE, "safety_locked": list(SAFETY_LOCKED), "tunable": list(TUNABLE)}

    def save(self, path: str | Path | None = None) -> Path:
        path = Path(path) if path else PROPOSED_PATH
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        return path

    def write_approved(self, path: str | Path | None = None) -> Path:
        path = Path(path) if path else APPROVED_PATH
        data = self.approved_params().to_dict()
        data["approved_changes"] = [c.id for c in self.changes if c.status == "approved"]
        data["safety_note"] = SAFETY_NOTE
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        return path


def simulated_operator(proposals: Proposals, mode: str = "criterion", decisions: dict[str, bool] | None = None) -> Proposals:
    """Quién aprueba en el banco de pruebas. Criterio FIJO y documentado (`mode="criterion"`): aprueba un cambio si
    se apoya en N ≥ MIN_N observaciones; con evidencia limitada lo RECHAZA y pide más datos. `all` / `none` / `file`
    (un dict {id: true|false}; lo que no esté en el fichero queda sin aprobar)."""
    for c in proposals.changes:
        if mode == "all":
            ok, why = True, "--approve all"
        elif mode == "none":
            ok, why = False, "--approve none"
        elif mode == "file":
            ok, why = bool((decisions or {}).get(c.id, False)), "decisión leída de fichero"
        else:
            ok = not c.limited and c.param in TUNABLE
            why = f"N={c.n} ≥ {MIN_N}" if ok else f"evidencia limitada (N={c.n} < {MIN_N}): faltan datos"
        (proposals.approve if ok else proposals.reject)(c.id, by=f"operador simulado ({mode})", note=why)
    return proposals


def _shrunk(old: float, observed: float, n: int) -> float:
    return old + (observed - old) * n / (n + SHRINK_K)


def propose(memory: OperationalMemory, base: Params | None = None, names: dict[str, str] | None = None) -> Proposals:
    """Determinista: misma memoria, mismas propuestas e ids. `names`: id → nombre para los textos de pantalla."""
    base = base or Params.initial()
    names = names or {}
    d = memory.data
    changes: list[Change] = []
    same: list[dict[str, Any]] = []

    def nm(x: str) -> str:
        return names.get(x, x)

    def add(param: str, key: str | None, old: Any, new: Any, n: int, text: str, evidence: dict[str, Any]) -> None:
        limited = n < MIN_N
        changes.append(Change(f"C-{len(changes) + 1:02d}", param, key, old, new, n,
                              text + (" — EVIDENCIA LIMITADA, cambio conservador" if limited else ""), evidence, limited))

    # 1 · antelación de la reposición, por punto
    for zone in sorted(d["resupply"]):
        r = d["resupply"][zone]
        n, old = int(r["n"]), base.lead(zone)[0]
        if not n:
            continue
        mean, p80 = sum(r["minutes"]) / n, _pct(r["minutes"], 0.8)
        target = p80 if n >= MIN_N else _shrunk(old, mean, n)
        new = min(MAX_LEAD_MIN, math.ceil(target))
        ev = {"minutes_mean": round(mean, 1), "minutes_p80": p80, "dry_before_refill": r["dry_before_refill"],
              "consumption_l_per_min": round(d["consumption"].get(zone, {}).get("sum_l", 0.0)
                                             / max(1, d["consumption"].get(zone, {}).get("n_ticks", 0)), 1)}
        if new - old < 2:       # nunca se pide MÁS TARDE que el valor de ficha, y no se toca por 1 minuto
            same.append({"param": "resupply_lead_min", "key": zone, "n": n, "value": old, "evidence": ev,
                         "text": f"Reposición en {nm(zone)}: tardó {_es(mean)} min de media (N={n}); la antelación de {old} min ya lo cubre"})
            continue
        add("resupply_lead_min", zone, old, new, n,
            f"Reposición en {nm(zone)}: tardó {_es(mean)} min de media (N={n}; {r['dry_before_refill']} veces el depósito llegó a 0 antes); "
            f"propongo pedirla {new - old} min antes (con {new} min de margen en vez de {old})", ev)

    # 2 · orden de contacto, por tipo de recurso
    kinds: dict[str, dict[str, dict[str, Any]]] = {}
    for rid in sorted(d["contacts"]):
        c = d["contacts"][rid]
        sent = sum(ch["sent"] for ch in c["channels"].values())
        ok = sum(ch["accept"] for ch in c["channels"].values())
        if sent >= MIN_N:       # con menos llamadas (p. ej. un refuerzo externo que vino una vez) no entra en el orden: sin penalización
            kinds.setdefault(c["kind"], {})[rid] = {"sent": sent, "accept": ok, "lost": list(c.get("lost_min", []))}
    for kind in sorted(kinds):
        rs = kinds[kind]
        total, ok = sum(x["sent"] for x in rs.values()), sum(x["accept"] for x in rs.values())
        if len(rs) < 2:
            continue
        pooled = ok / total
        rate = {rid: round((x["accept"] + PRIOR_N * pooled) / (x["sent"] + PRIOR_N), 3) for rid, x in rs.items()}
        order = sorted(rate, key=lambda rid: (-rate[rid], rid))
        lost = [m for x in rs.values() for m in x["lost"]]
        ev = {"sent": {rid: x["sent"] for rid, x in rs.items()}, "accepted": {rid: x["accept"] for rid, x in rs.items()},
              "smoothed_rate": rate, "pooled_rate": round(pooled, 3)}
        if rate[order[0]] - rate[order[-1]] < 0.15:
            same.append({"param": "contact_order", "key": kind, "n": total, "value": None, "evidence": ev,
                         "text": f"Contacto de {kind}: todos contestan parecido ({round(pooled * 100)} % de media, N={total}); se sigue llamando al más cercano"})
            continue
        worst, best = order[-1], order[0]
        n_min = min(rs[worst]["sent"], rs[best]["sent"])
        new = {"order": order, "rate": rate, "n": {rid: x["sent"] for rid, x in rs.items()},
               "fail_cost_min": round(sum(lost) / len(lost), 1) if lost else FAIL_COST_MIN}
        changes.append(Change(
            f"C-{len(changes) + 1:02d}", "contact_order", kind, None, new, total,
            f"Contacto de {kind}: {nm(worst)} aceptó {rs[worst]['accept']} de {rs[worst]['sent']} llamadas y {nm(best)} "
            f"{rs[best]['accept']} de {rs[best]['sent']} (N={total}); propongo llamar primero a quien contesta, salvo que esté mucho más lejos"
            + (" — EVIDENCIA LIMITADA, cambio conservador (tasas suavizadas hacia la media)" if n_min < MIN_N else ""),
            ev, limited=n_min < MIN_N))

    # 3 · pedir un punto concreto en zonas amplias
    for zone in sorted(d["locate"]["search"]):
        s = d["locate"]["search"][zone]
        n = int(s["n"])
        if not n or base.precise(zone):
            continue
        mean = sum(s["minutes"]) / n
        ev = {"search_min_mean": round(mean, 1), "search_min_p80": _pct(s["minutes"], 0.8)}
        if mean < 3.0:
            same.append({"param": "require_precise_location", "key": zone, "n": n, "value": False, "evidence": ev,
                         "text": f"En {nm(zone)} se da con la persona en {_es(mean)} min de media (N={n}): no hace falta pedir más"})
            continue
        add("require_precise_location", zone, False, True, n,
            f"En {nm(zone)} el equipo tardó {_es(mean)} min de media en dar con la persona (N={n}): «{nm(zone)}» es demasiado amplio; "
            "propongo que el ASK pida un punto concreto (torre, puesto o acceso numerado) mientras el equipo va de camino", ev)

    # 4 · ventana de duplicados (solo se alarga, nunca se acorta)
    dup = d["duplicates"]
    gaps, missed = dup.get("merge_quiet_min") or dup["merge_gap_min"], dup["missed_gap_min"]
    n = len(gaps) + len(missed)
    old = base.duplicate_window_min
    ev = {"reports": dup["reports"], "incidents": dup["incidents"], "merged": len(gaps),
          "merge_gap_p95": _pct(gaps, 0.95) if gaps else None, "teams_moved_for_nothing": dup["teams_moved_for_nothing"],
          "teams_moved_by_duplicate": dup["teams_moved_by_duplicate"], "missed_gap_p90": _pct(missed, 0.9) if missed else None}
    late = [g for g in missed if g > old]
    if len(late) >= 1:
        target = _pct(late, 0.9) + 2 if len(late) >= MIN_N else _shrunk(old, _pct(late, 0.9) + 2, len(late))
        new = min(MAX_DUPLICATE_WINDOW, math.ceil(target))
        if new > old:
            add("duplicate_window_min", None, old, new, len(late),
                f"Duplicados: {len(late)} equipos llegaron y no encontraron nada donde ya había otro incidente igual, confirmado y abierto, "
                f"avisado más de {old} min antes (hasta {_es(max(late), 0)} min): probable duplicado fuera de ventana; propongo alargarla a "
                f"{new} min (nunca para riesgo vital)", ev)
    if not changes or changes[-1].param != "duplicate_window_min":
        same.append({"param": "duplicate_window_min", "key": None, "n": n, "value": old, "evidence": ev,
                     "text": f"Duplicados: {len(gaps)} avisos repetidos fundidos"
                             + (f", el 95 % a ≤ {_es(_pct(gaps, 0.95), 0)} min del aviso anterior" if gaps else "")
                             + f"; {dup['teams_moved_by_duplicate']} equipos movidos por un duplicado, ninguno fuera de la ventana de {old} min: no se toca (N={n})"})

    # 5 · alertas meteorológicas: SOLO seguimiento y cancelación de preparativos. Los umbrales no se tocan.
    eps = d["weather"]["episodes"]
    quiet = [e for e in eps if e["outcome"] == "no_llego"]
    came = [e for e in eps if e["outcome"] == "llego"]
    cleared = [e["minutes_to_clear"] for e in quiet if e.get("minutes_to_clear") is not None]
    ev = {"alerts": len(eps), "did_not_arrive": len(quiet), "arrived": len(came),
          "minutes_to_clear_mean": round(sum(cleared) / len(cleared), 1) if cleared else None,
          "preparations": sum(len(e["preparations"]) for e in eps)}
    if cleared and base.weather_standdown_min is None:
        add("weather_standdown_min", None, None, MIN_STANDDOWN_MIN, len(cleared),
            f"Meteorología: {len(quiet)} de {len(eps)} alertas de viento no llegaron a más y se desactivaron a los "
            f"{_es(sum(cleared) / len(cleared))} min de media (N={len(cleared)}); propongo cancelar los preparativos tras "
            f"{MIN_STANDDOWN_MIN} min seguidos en calma, en vez de dejarlos abiertos. {SAFETY_NOTE}", ev)
    fast = [e for e in came if e.get("minutes_to_level2") is not None and e["minutes_to_level2"] < base.weather_followup_min]
    if fast and base.weather_followup_min > 3:
        add("weather_followup_min", None, base.weather_followup_min, 3, len(fast),
            f"Meteorología: en {len(fast)} alertas el viento pasó de preaviso a riesgo en menos de {base.weather_followup_min} min; "
            f"propongo revisar cada 3 min mientras haya alerta. {SAFETY_NOTE}", ev)
    if not eps:
        same.append({"param": "weather", "key": None, "n": 0, "value": None, "evidence": ev,
                     "text": "Meteorología: ninguna alerta de viento observada; no se propone nada"})
    return Proposals(changes, same, base)


__all__ = ["Params", "Change", "Proposals", "propose", "simulated_operator", "TUNABLE", "SAFETY_LOCKED", "SAFETY_NOTE",
           "APPROVED_PATH", "PROPOSED_PATH", "NOMINAL_RESUPPLY_MIN", "RESUPPLY_MARGIN_MIN", "MIN_N"]
