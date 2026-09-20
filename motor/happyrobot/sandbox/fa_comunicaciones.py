"""Pasos puros de fa-comunicaciones y su recuperación programada.

El Cron de HappyRobot entra una vez por tick. Este módulo solo acota, decide y
resume: quien entrega es el puente, que reclama un lease y confirma con el
proveedor. Aquí no se envía nada, no se eligen destinatarios de negocio y un
resultado ambiguo nunca se convierte en entregado.
"""
import json
import re

if "OperationError" not in globals():
    from .fa_operaciones import OperationError


MAX_TICK = 16
DEFAULT_TICK = 8
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.~:-]{0,119}\Z")
DELIVERED = {"succeeded", "simulated"}
RESCHEDULED = {"deferred", "pending"}
STALLED = {"failed"}
AMBIGUOUS = {"unknown"}
IN_FLIGHT = {"sending", "unavailable", "missing"}
KNOWN = DELIVERED | RESCHEDULED | STALLED | AMBIGUOUS | IN_FLIGHT
COUNTERS = ("processed", "delivered", "simulated", "rescheduled", "stalled", "ambiguous", "in_flight", "unrecognized")


def value(input_data, key):
    parsed = input_data.get(key)
    return json.loads(parsed) if isinstance(parsed, str) else parsed


def bounded_limit(raw):
    """En la plataforma los valores llegan como texto (Plate), así que se acepta
    una cadena de dígitos; cualquier otra cosa se rechaza en vez de recortarse."""
    if raw in (None, ""):
        return DEFAULT_TICK
    if isinstance(raw, str):
        if not raw.isdigit():
            raise OperationError("invalid_recovery_limit")
        raw = int(raw)
    if type(raw) is not int or not 1 <= raw <= MAX_TICK:
        raise OperationError("invalid_recovery_limit")
    return raw


def recover_input(input_data):
    """Cuerpo acotado para el tick de recuperación del outbox. Un tick nunca pide
    más de MAX_TICK, así que un Cron rápido no puede convertirse en un reenvío
    masivo ni saltarse el lease del puente."""
    try:
        limit = bounded_limit(input_data.get("limit"))
        return {"status": "ready", "path": "/outbox/recover", "limit": limit,
                "body_json": json.dumps({"limit": limit})}
    except (OperationError, ValueError, TypeError, AttributeError):
        return {"status": "rejected", "path": "", "limit": 0, "body_json": "{}"}


def inbox_input(input_data):
    """Ids pendientes de inbox que toca reintentar. Se acotan y se rechazan
    duplicados: reintentar dos veces el mismo evento no es una recuperación."""
    try:
        items = value(input_data, "items_json")
        if items is None:
            items = []
        if not isinstance(items, list) or len(items) > MAX_TICK:
            raise OperationError("invalid_inbox_batch")
        ids = []
        for item in items:
            if not isinstance(item, str) or not ID.fullmatch(item):
                raise OperationError("invalid_inbox_batch")
            if item in ids:
                raise OperationError("duplicate_inbox_batch")
            ids.append(item)
        return {"status": "ready", "ids_json": json.dumps(ids), "count": len(ids)}
    except (OperationError, ValueError, TypeError, AttributeError):
        return {"status": "rejected", "ids_json": "[]", "count": 0}


def summary_input(input_data):
    """Clasifica el resultado de un tick. `unknown` significa que el proveedor no
    confirmó nada: se cuenta aparte y exige atención, nunca se presenta como
    entrega confirmada ni autoriza un reenvío automático."""
    counts = {name: 0 for name in COUNTERS}
    try:
        results = value(input_data, "results_json")
        if not isinstance(results, list) or len(results) > MAX_TICK:
            raise OperationError("invalid_results")
        for item in results:
            if not isinstance(item, dict):
                raise OperationError("invalid_results")
            status = item.get("status")
            if not isinstance(status, str) or status not in KNOWN:
                counts["unrecognized"] += 1
                continue
            counts["processed"] += 1
            for name, group in (("delivered", {"succeeded"}), ("simulated", {"simulated"}),
                                ("rescheduled", RESCHEDULED), ("stalled", STALLED),
                                ("ambiguous", AMBIGUOUS), ("in_flight", IN_FLIGHT)):
                if status in group:
                    counts[name] += 1
                    break
    except (OperationError, ValueError, TypeError, AttributeError):
        return {"status": "rejected", "summary_json": json.dumps({name: 0 for name in COUNTERS}), "needs_attention": True}
    counts["needs_attention"] = counts["stalled"] + counts["ambiguous"] + counts["unrecognized"] > 0
    return {"status": "ready", "summary_json": json.dumps(counts), "needs_attention": counts["needs_attention"]}
