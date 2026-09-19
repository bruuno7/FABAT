"""Protocolos de recogida de avisos, como datos (`protocolos.json`).

AVISO: instrucciones de apoyo para una SIMULACIÓN de hackathon. No sustituyen al 112 ni a la
formación; en un despliegue real las valida la dirección sanitaria del evento.

Aquí solo vive la semántica de referencia de las condiciones, para que quien programe el agente de
recogida y quien valide los datos lean lo mismo:

- `answers` = {slot_id: valor}. Un slot sin contestar NO está en el diccionario.
- Un `bool` vale True, False o "unknown" («no sé»).
- Condición = {slot: valor | [valores] | {"gte": n, "lte": n}}; se deben cumplir TODAS las claves.
  Una condición sobre un slot sin contestar no se cumple. La condición vacía {} se cumple siempre.
- Las `red_flags` se evalúan en orden tras cada respuesta y gana la primera que se cumple.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PATH = Path(__file__).with_name("protocolos.json")


def load(path: Path | str = PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _same(got: Any, expected: Any) -> bool:
    """Igualdad sin la trampa de Python de que True == 1."""
    if isinstance(got, bool) or isinstance(expected, bool):
        return got is expected
    return got == expected


def matches(cond: dict[str, Any], answers: dict[str, Any]) -> bool:
    for slot_id, expected in cond.items():
        if slot_id not in answers:
            return False
        got = answers[slot_id]
        if isinstance(expected, dict):
            if isinstance(got, bool) or not isinstance(got, (int, float)):
                return False
            if "gte" in expected and got < expected["gte"]:
                return False
            if "lte" in expected and got > expected["lte"]:
                return False
        elif isinstance(expected, list):
            if not any(_same(got, e) for e in expected):
                return False
        elif not _same(got, expected):
            return False
    return True


def first_flag(protocol: dict, answers: dict[str, Any]) -> dict | None:
    """El `then` de la primera bandera que se cumple, o None."""
    for flag in protocol["red_flags"]:
        if matches(flag["if"], answers):
            return flag["then"]
    return None


def can_dispatch(protocol: dict, answers: dict[str, Any]) -> bool:
    """¿Hay ya lo mínimo para enviar a alguien? (Se envía antes de seguir preguntando.)"""
    return all(s in answers for s in protocol["dispatch_as_soon_as"])


def next_slot(protocol: dict, answers: dict[str, Any]) -> dict | None:
    """Siguiente pregunta pendiente. Con una bandera `dispatch_now` cumplida solo quedan las críticas."""
    then = first_flag(protocol, answers)
    critical_only = bool(then and then.get("dispatch_now")) or protocol.get("sensitive", False)
    for slot in protocol["slots"]:
        if slot["id"] in answers:
            continue
        if "ask_if" in slot and not matches(slot["ask_if"], answers):
            continue
        if critical_only and not slot["critical"]:
            continue
        return slot
    return None
