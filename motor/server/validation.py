"""Validación de entradas antes de cambiar el mundo o consumir una confirmación."""
import math
from typing import Any

from motor.contracts import Channel, Family, ResourceKind


def number(value: Any, name: str, lo: float, hi: float, integer: bool = False) -> None:
    if type(value) not in (int, float) or not lo <= value <= hi or not math.isfinite(value) or (integer and type(value) is not int):
        raise ValueError(f"{name}: número válido entre {lo} y {hi} requerido")


def strike_effect(effect: Any, world: Any) -> dict[str, Any]:
    if not isinstance(effect, dict):
        raise ValueError("effect debe ser un objeto")
    e = dict(effect)
    kind = e.get("kind")
    fields = {
        "resource_offline": {"resource", "n"}, "resource_online": {"resource"},
        "resource_no_answer": {"resource", "n"}, "resource_rejects": {"resource", "n"},
        "zone_state": {"zone", "state"}, "zone_inflow": {"zone", "per_min", "n"},
        "zone_flag": {"zone", "flag", "value"}, "weather": {"temp_c", "wind_kmh", "rain", "alert"},
        "comms_down": {"channel", "n"}, "transport_cut": {"factor", "n"}, "incident": {"incident", "reports"},
    }
    if not isinstance(kind, str) or kind not in fields or set(e) - fields[kind] - {"kind", "reason"}:
        raise ValueError("efecto o campos desconocidos")
    if "reason" in e and (not isinstance(e["reason"], str) or len(e["reason"]) > 400):
        raise ValueError("reason inválido")
    if "n" in e:
        number(e["n"], "n", 1, 180, True)
    if kind.startswith("resource_"):
        rid = e.get("resource")
        if rid == "auto" and kind == "resource_no_answer":
            moving = [r for r in world.observe().resources.values() if str(r.status) == "en_route"]
            rid = e["resource"] = moving[0].id if moving else "sec_2"
        if not isinstance(rid, str) or rid not in world.resources:
            raise ValueError("recurso desconocido")
    if kind.startswith("zone_"):
        if not isinstance(e.get("zone"), str) or e["zone"] not in world.L.idx:
            raise ValueError("zona desconocida")
    if kind == "zone_state" and e.get("state") not in tuple(world.P["state_inflow"]):
        raise ValueError("estado desconocido")
    if kind == "zone_inflow":
        number(e.get("per_min"), "per_min", 0, 5000)
    if kind == "zone_flag":
        flag, value = e.get("flag"), e.get("value")
        if flag in ("power", "shade", "blocked"):
            if type(value) is not bool:
                raise ValueError("value debe ser booleano")
        elif flag in ("water_l", "water_capacity_l", "flow_factor"):
            number(value, "value", 0, 5 if flag == "flow_factor" else 100000)
        else:
            raise ValueError("flag desconocido")
    if kind == "weather":
        if "temp_c" in e:
            number(e["temp_c"], "temp_c", -30, 60)
        if "wind_kmh" in e:
            number(e["wind_kmh"], "wind_kmh", 0, 250)
        if "rain" in e and type(e["rain"]) is not bool:
            raise ValueError("rain debe ser booleano")
        if "alert" in e and (not isinstance(e["alert"], str) or len(e["alert"]) > 80):
            raise ValueError("alert inválida")
    if kind == "transport_cut":
        number(e.get("factor", 0), "factor", 0, 1)
    if kind == "comms_down" and e.get("channel") not in ("all", *(str(c) for c in Channel)):
        raise ValueError("canal desconocido")
    if kind == "incident":
        d = e.get("incident")
        if not isinstance(d, dict) or set(d) - {"id", "family", "type", "zone", "severity", "deadline", "needs", "service_min", "notes"}:
            raise ValueError("incident inválido")
        if d.get("family") not in tuple(str(f) for f in Family) or d.get("zone") not in tuple(world.L.ids):
            raise ValueError("familia o zona inválida")
        for key in ("id", "type"):
            if key in d and (not isinstance(d[key], str) or not 1 <= len(d[key]) <= 80):
                raise ValueError(f"{key} inválido")
        number(d.get("severity", 5), "severity", 1, 10, True)
        for key in ("deadline", "service_min"):
            if key in d:
                number(d[key], key, 1, 1440, True)
        needs = d.get("needs", {})
        if not isinstance(needs, dict) or set(needs) - {str(r) for r in ResourceKind}:
            raise ValueError("needs inválido")
        for value in needs.values():
            number(value, "needs", 0, 20, True)
        if "notes" in d and (not isinstance(d["notes"], list) or any(not isinstance(n, str) or len(n) > 400 for n in d["notes"])):
            raise ValueError("notes inválido")
        reports = e.get("reports", [])
        if not isinstance(reports, list) or len(reports) > 20:
            raise ValueError("reports inválido")
        for report in reports:
            if not isinstance(report, dict) or set(report) - {"id", "channel", "text", "source", "lang", "zone_hint"}:
                raise ValueError("report inválido")
            if any(not isinstance(v, str) or len(v) > 400 for v in report.values()):
                raise ValueError("report inválido")
            if "zone_hint" in report and report["zone_hint"] not in world.L.idx:
                raise ValueError("zona desconocida")
    return e


def webhook(event: Any) -> dict:
    """La plataforma serializa algunos números como texto; las estructuras y booleanos sí son estrictos."""
    if not isinstance(event, dict):
        raise ValueError("evento debe ser objeto")
    ev = dict(event)
    for key in ("data", "report", "extracted"):
        if key in ev and not isinstance(ev[key], dict):
            raise ValueError(f"{key} debe ser objeto")
    data = dict(ev.get("data", {}))
    # El adaptador traslada estos campos de primer nivel a data: se valida su valor efectivo.
    if ev.get("needs") is not None:
        data["needs"] = ev["needs"]
    for key in ("exists", "confirmed_by_repetition", "reserved", "sensitive"):
        if key in data and type(data[key]) is not bool:
            raise ValueError(f"data.{key} debe ser booleano")
    for key in ("zone", "type", "family", "point"):
        if data.get(key) is not None and not isinstance(data[key], str):
            raise ValueError(f"data.{key} debe ser texto")
    if data.get("family") is not None and data["family"] not in tuple(str(f) for f in Family):
        raise ValueError("data.family desconocida")
    for key, lo, hi in (("severity", 1, 10), ("deadline", 0, 10000)):
        if key in data and data[key] is not None:
            number(data[key], f"data.{key}", lo, hi, True)
    if "needs" in data:
        if not isinstance(data["needs"], dict) or set(data["needs"]) - {str(r) for r in ResourceKind}:
            raise ValueError("data.needs inválido")
        for value in data["needs"].values():
            number(value, "data.needs", 0, 20, True)
    for key in ("final", "partial", "confirmed_by_repetition"):
        if key in ev and type(ev[key]) is not bool:
            raise ValueError(f"{key} debe ser booleano")
    for key in ("action_id", "event_id", "hr_run_id", "run_id", "session_id", "hr_session_id", "type", "message",
                "result", "stage", "channel_used", "text", "content", "reason", "report_ref", "field", "value"):
        if ev.get(key) is not None and not isinstance(ev[key], str):
            raise ValueError(f"{key} debe ser texto")
    if "seq" in ev:
        number(ev["seq"], "seq", 0, 100000, True)
    for key in ("latency_ms", "turn_latency_ms", "avg_turn_latency_ms"):
        if key in ev:
            number(ev[key], key, 0, 3600000)
        if key in ev.get("data", {}):
            number(ev["data"][key], key, 0, 3600000)
    if isinstance(ev.get("eta_min"), (dict, list, bool)):
        raise ValueError("eta_min inválido")
    if isinstance(ev.get("eta_min"), (int, float)):
        number(ev["eta_min"], "eta_min", 0, 240)
    if "transcript" in ev and not isinstance(ev["transcript"], (str, list)) and ev["transcript"] is not None:
        raise ValueError("transcript inválido")
    rep = ev.get("report", {})
    for key in ("text", "zone_hint", "channel", "source", "lang"):
        if rep.get(key) is not None and not isinstance(rep[key], str):
            raise ValueError(f"report.{key} debe ser texto")
    if (ev.get("type") or ev.get("message")) == "public_report":
        if not any(str(v or '').strip() for v in (rep.get("text"), ev.get("text"), ev.get("description"), ev.get("extracted", {}).get("description"), ev.get("transcript"))):
            raise ValueError("el aviso no trae texto")
    return ev
