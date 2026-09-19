"""Comunicaciones simuladas: las personas al otro lado del teléfono. Implementa `CommsAPI`."""
from __future__ import annotations

import random
from typing import Any

from motor.contracts import Action, ActionKind, Resource

from .world import World


class SimComms:
    """Contesta sola según el estado del mundo (`resource_no_answer`, `resource_rejects`,
    `comms_down`, recurso OFFLINE) más una pequeña probabilidad con semilla propia,
    separada de la del mundo para no alterar su RNG ni el de sus clones."""

    def __init__(self, world: World, seed: int = 0, p_reject: float = 0.04, p_no_answer: float = 0.03):
        self.world = world
        self.rng = random.Random((seed * 2654435761) ^ 0x5EED)
        self.p_reject = p_reject
        self.p_no_answer = p_no_answer
        self._pending: list[dict[str, Any]] = []

    def send(self, action: Action, resource: Resource | None = None) -> None:
        w = self.world
        roll, delay = self.rng.random(), self.rng.randint(1, 3)  # siempre dos tiradas por envío
        data: dict[str, Any] = {}
        state = w.contact_state(resource.id) if resource is not None else "ok"
        # capa «ops» del caso: cada persona coge el teléfono a su manera (el agente no lo sabe: lo observa)
        who = (getattr(w, "ops", None) or {}).get("contact", {}).get(resource.id, {}) if resource is not None else {}
        p_reject, p_no_answer = who.get("p_reject", self.p_reject), who.get("p_no_answer", self.p_no_answer)
        if w.channel_down(action.channel):
            result, text, delay = "no_answer", "Canal caído: el mensaje no ha salido.", 1
        elif state in ("offline", "no_answer"):
            result, text, delay = "no_answer", "No contesta.", 2
        elif action.kind == ActionKind.ASK:
            result = "answer"
            text, data = w.answer_for(action)
        elif resource is None:
            result, text, delay = "accept", "Mensaje entregado.", 1
        elif state == "rejects" or (action.kind == ActionKind.DISPATCH and roll < p_reject):
            result, text, delay = "reject", "Estoy con otro incidente, no puedo ir ahora.", 1
        elif action.kind == ActionKind.DISPATCH and roll < p_reject + p_no_answer:
            result, text, delay = "no_answer", "No contesta.", 2
        else:
            result, delay = "accept", 1
            dest = action.zone or action.params.get("zone")
            eta = w.travel_time(resource.zone, dest, resource.id) if dest else None
            text = f"Recibido, vamos para allá. Unos {eta} min." if eta is not None else "Recibido."
        self._pending.append({"action_id": action.id, "result": result, "text": text, "t": w.t + delay, "data": data})

    def poll(self, t: int) -> list[dict[str, Any]]:
        ready = [p for p in self._pending if p["t"] <= t]
        if ready:
            self._pending = [p for p in self._pending if p["t"] > t]
        return ready
