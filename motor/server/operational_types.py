"""Private persisted records for the operational authority."""
from __future__ import annotations

from typing import NotRequired, TypeAlias, TypedDict

JSON: TypeAlias = None | bool | int | float | str | list["JSON"] | dict[str, "JSON"]
Document: TypeAlias = dict[str, JSON]


class Entity(TypedDict):
    id: str
    version: int


class Actor(Entity):
    name: str
    roles: list[str]
    channel: str
    address: str
    zone: str | None
    availability: str


class Update(TypedDict):
    principal: str
    channel: str
    text: str
    occurred_at: float


class Incident(Entity):
    text: str
    zone: str | None
    priority: float
    status: str
    needs: dict[str, int]
    tasks: dict[str, str]
    why_waiting: str
    created_at: float
    updated_at: float
    reporter_id: str
    reporter_ids: list[str]
    updates: list[Update]
    life_threat: bool
    merged_into: str | None
    review_required: NotRequired[bool]


class Assignment(Entity):
    incident_id: str
    actor_id: str
    role: str
    task_id: str
    zone: str
    status: str
    eta_min: int | None
    expires_at: float
    reason: str
    communication: Document
    followup_confirmed: NotRequired[bool]


class Approval(Entity):
    incident_id: str
    incident_version: int
    status: str
    actions: list[Document]
    content_hash: str
    expires_at: float
    reason: str
    requires_person: bool
    decided_by: str
    note: str


class Delivery(Entity):
    channel: str
    recipient_id: str
    purpose: str
    text: str
    incident_id: str
    assignment_id: str | None
    status: str
    attempts: int
    payload: Document
    last_error: str
    private_detail: str
    provider_id: str
    lease_token: str
    lease_until: float
    worker: str
    next_attempt_at: float


class Event(Entity):
    occurred_at: float
    kind: str
    principal: str
    incident_id: str | None
    assignment_id: str | None
    summary: str


class State(TypedDict):
    schema: int
    revision: int
    zones: list[Document]
    actors: dict[str, Actor]
    incidents: dict[str, Incident]
    assignments: dict[str, Assignment]
    approvals: dict[str, Approval]
    deliveries: dict[str, Delivery]
    events: list[Event]
    reservations: dict[str, str]
    # Espejo de solo lectura de la coordinación que decide HappyRobot por Telegram
    # (`fa-entrada-tg` / `fa-despacho-tg` / `fa-respuesta-tg`). No es autoridad:
    # la interfaz lo pinta y los botones quedan para override humano.
    hr_mirror: NotRequired[Document]
