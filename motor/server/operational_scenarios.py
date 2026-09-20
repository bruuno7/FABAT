"""Escenarios de SIMULACIÓN sobre la autoridad SQLite, nunca otro planificador.

Ejecutar desde la raíz: python -m motor.server.operational_scenarios --output DIR_NUEVO.
El presupuesto predeterminado es N=200 semillas × 100 eventos, no 20.000 tests.
Los eventos son recetas simbólicas reproducibles: no dependen de UUID aleatorios.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import random
import sqlite3
import subprocess
import tempfile
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import ExitStack, closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from unittest.mock import patch

from .operational import ACTIVE, GRAVE, OperationalError
from .operational_service import OperationalService
from .operational_types import JSON, Document, State
from .operational_worker import DeliveryWorker

ROOT = Path(__file__).resolve().parents[2]
FESTIVAL: Document = {"zones": [
    {"id": "front_pit", "name": "Escenario 1", "kind": "stage"},
    {"id": "gate_a", "name": "Puerta A", "kind": "gate"},
    {"id": "gate_b", "name": "Puerta B", "kind": "gate"},
]}
TEXTS = ("Persona desmayada", "Persona con golpe de calor", "Aglomeración peligrosa",
         "Agresión a una persona", "Fallo eléctrico", "Necesitamos ayuda", "Persona no respira")
COLLECTIONS = ("actors", "incidents", "assignments", "approvals", "deliveries")
SYNTHETIC_SECRET = "synthetic-scenarios-not-a-provider-secret"


@dataclass
class Clock:
    now: float = 1000.0

    def __call__(self) -> float:
        return self.now


class InvariantFailure(AssertionError):
    """Código estable para reducir un fallo sin confundirlo con otro."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def require(condition: bool, code: str) -> None:
    if not condition:
        raise InvariantFailure(code)


@contextmanager
def offline() -> Iterator[None]:
    """Ni configuración ambiental ni una regresión pueden contactar proveedores."""
    environment = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR") if key in os.environ}
    environment.update(MANDO_EXTERNAL_DELIVERY="0", TELEGRAM_MODE="off")
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, environment, clear=True))
        for target in ("httpx.post", "httpx.request", "httpx.Client.send", "httpx.AsyncClient.send",
                       "socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex",
                       "socket.getaddrinfo"):
            stack.enter_context(patch(target, side_effect=InvariantFailure("network_attempt")))
        yield


def open_service(path: Path, clock: Clock) -> OperationalService:
    # La ruta siempre procede del directorio recién creado, nunca de MANDO_OPERATIONAL_DB.
    return OperationalService(path, FESTIVAL, clock=clock, callback_secret=SYNTHETIC_SECRET)


def persisted(path: Path) -> State:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
        row = database.execute("SELECT body FROM operational_state WHERE id=1").fetchone()
    return cast(State, json.loads(row[0]))


def records(service: OperationalService, collection: str) -> list[Document]:
    return cast(list[Document], service.state()[collection])


def record(service: OperationalService, collection: str, identifier: str) -> Document:
    return next(row for row in records(service, collection) if row["id"] == identifier)


def domain(state: State) -> Document:
    # Auditoría/revisión pueden avanzar ante rechazo; los efectos operativos no.
    document = cast(Document, state)
    return {key: copy.deepcopy(document[key]) for key in COLLECTIONS} | {
        "reservations": cast(JSON, copy.deepcopy(state["reservations"])),
    }


def check_invariants(before: State, after: State) -> None:
    require(after["revision"] >= before["revision"], "revision_regressed")
    require(set(before["incidents"]) <= set(after["incidents"]), "incident_lost")
    expected: dict[str, str] = {}
    for assignment in after["assignments"].values():
        actor = after["actors"][assignment["actor_id"]]
        incident = after["incidents"][assignment["incident_id"]]
        if assignment["status"] in ACTIVE:
            require(assignment["role"] in actor["roles"], "active_role_mismatch")
            require(assignment["zone"] == incident["zone"], "active_destination_mismatch")
            for key in ("actor:" + actor["id"], "task:" + assignment["task_id"]):
                require(key not in expected, "exclusive_reservation_duplicated")
                expected[key] = assignment["id"]
        if assignment["id"] not in before["assignments"]:
            require(actor["availability"] == "available", "new_assignment_unavailable")
        if assignment["status"] == "offered":
            require(assignment["eta_min"] is None, "eta_without_acceptance")
        if assignment["status"] == "en_route":
            eta = assignment["eta_min"]
            require(type(eta) is int and 0 <= eta <= 240, "eta_invalid")
    require(after["reservations"] == expected, "reservations_not_bidirectional")
    previous = cast(Document, before)
    current = cast(Document, after)
    for collection in COLLECTIONS:
        old_rows = cast(dict[str, Document], previous[collection])
        new_rows = cast(dict[str, Document], current[collection])
        for identifier, old in old_rows.items():
            require(identifier in new_rows, "entity_lost:" + collection)
            new = new_rows[identifier]
            require(cast(int, new["version"]) >= cast(int, old["version"]), "version_regressed:" + collection)
            if old != new:
                require(cast(int, new["version"]) > cast(int, old["version"]), "changed_without_version:" + collection)
    for delivery in after["deliveries"].values():
        if delivery["purpose"] in GRAVE:
            require(delivery["payload"].get("human_approved") is True, "grave_without_approval")
            require(any(a["status"] == "approved" and a["decided_by"]
                        and a["incident_id"] == delivery["incident_id"]
                        and any(x["kind"] == delivery["purpose"] for x in a["actions"])
                        for a in after["approvals"].values()), "grave_without_human_record")
    for identifier, delivery in before["deliveries"].items():
        if delivery["channel"] in {"phone", "happyrobot"} and delivery["status"] == "uncertain":
            current_delivery = after["deliveries"][identifier]
            require(current_delivery["attempts"] == delivery["attempts"] and current_delivery["status"] == "uncertain",
                    "uncertain_call_retried")


def register_command(identifier: str, role: str = "medico", channel: str = "web") -> Document:
    return {"kind": "register_actor", "actor_id": identifier, "name": "Equipo sintético " + identifier,
            "roles": [role], "channel": channel, "address": "synthetic-" + identifier,
            "availability": "available", "zone": "front_pit"}


def report_command(identifier: str, text: str = TEXTS[0], zone: str | None = "front_pit") -> Document:
    return {"command_id": identifier, "kind": "report", "text": text, "zone": zone}


class Scenario:
    """Traduce recetas en comandos reales y comprueba efectos, no decisiones copiadas."""

    def __init__(self, path: Path, clock: Clock | None = None) -> None:
        self.path = path
        self.clock = clock or Clock()
        self.service = open_service(path, self.clock)
        self.trace: list[Document] = []
        self.saved: dict[str, Document] = {}
        self.counts: Counter[str] = Counter()

    def close(self) -> None:
        self.service.close()

    def choose(self, collection: str, event: Document, statuses: set[str] | None = None) -> Document | None:
        rows = records(self.service, collection)
        if statuses is not None:
            rows = [row for row in rows if row["status"] in statuses]
        if not rows:
            return None
        return rows[int(str(event.get("pick", 0))) % len(rows)]

    def step(self, event: Document) -> Document:
        before = persisted(self.path)
        op = str(event["op"])
        entry: Document = {"event": event, "time": self.clock.now}
        self.trace.append(entry)  # También se conserva el evento que falla.
        result: Document = {}
        expected = str(event.get("expect", "ok"))
        command: Document | None = None
        scope = "operator"
        if op == "expire":
            self.clock.now += int(str(event.get("seconds", 121)))
            result = self.service.reconcile()
        elif op in {"drain", "uncertain"}:
            worker = DeliveryWorker(self.service, external=False)
            lost = 0
            for delivery in self.service.claim("synthetic-worker", limit=100):
                if op == "uncertain" and delivery["channel"] in {"phone", "happyrobot"}:
                    require(self.service.settle(str(delivery["id"]), str(delivery["lease_token"]),
                                               "uncertain", detail="synthetic_lost_response"), "lost_response_not_persisted")
                    lost += 1
                else:
                    worker._deliver(delivery)
            result = {"simulated_lost_responses": lost}
        elif op == "reopen":
            self.service.close()
            self.service = open_service(self.path, self.clock)
            self.service.recover_inbox()
        else:
            command, scope = self.command(event)
            entry["command"] = command
            try:
                result = self.service.execute(command, scope=scope)
                require(expected != "reject", "invalid_command_accepted:" + op)
            except OperationalError as exc:
                result = {"error": exc.code, "status": exc.status}
                require(expected in {"reject", "either"} and exc.status < 500,
                        "unexpected_rejection:" + op + ":" + exc.code)
                require(domain(before) == domain(persisted(self.path)), "rejected_command_changed_domain")
                self.counts["rejected"] += 1
            else:
                self.counts["accepted"] += 1
                if command["kind"] == "report" and not result.get("duplicate"):
                    after_report = persisted(self.path)
                    require(len(after_report["incidents"]) == len(before["incidents"]) + 1,
                            "distinct_victims_merged")
                if op == "replay":
                    require(result.get("duplicate") is True, "replay_not_duplicate")
                    require(before == persisted(self.path), "replay_changed_state")
                if op in {"accept", "eta", "arrive", "locate", "complete"}:
                    target = {"accept": "accepted", "eta": "en_route", "arrive": "arrived",
                              "locate": "located", "complete": "completed"}[op]
                    assignment = record(self.service, "assignments", str(command["assignment_id"]))
                    require(assignment["status"] == target, "transition_conflated:" + op)
                if op == "report":
                    self.saved[str(event["id"])] = command
        after = persisted(self.path)
        if op == "collision":
            require(domain(before) == domain(after), "collision_not_rolled_back")
        check_invariants(before, after)
        entry.update(result=result, revision=after["revision"])
        self.counts[op] += 1
        if command:
            self.counts["command:" + str(command["kind"])] += 1
        return result

    def command(self, event: Document) -> tuple[Document, str]:
        op = str(event["op"])
        cid = str(event["id"])
        command: Document = {"command_id": cid, "kind": op}
        scope = "operator"
        if op == "register":
            command.update(register_command(str(event["actor"]), str(event.get("role", "medico")),
                                            str(event.get("channel", "web"))))
        elif op == "report":
            command.update(report_command(cid, str(event.get("text", TEXTS[0])), cast(str | None, event.get("zone", "front_pit"))))
        elif op in {"replay", "collision"}:
            source = self.saved.get(str(event.get("source", "victim-one")), report_command("victim-one"))
            command = dict(source)
            if op == "collision":
                command["text"] = "Otro contenido incompatible"
        elif op == "availability":
            actor = self.choose("actors", event) or {"id": "missing-actor", "version": 1}
            command.update(actor_id=actor["id"], expected_version=actor["version"],
                           availability=event.get("availability", "available"))
        elif op in {"update", "offer", "propose", "stale"}:
            incident = self.choose("incidents", event, {"open", "waiting", "offered", "assigned", "in_progress"}) or {
                "id": "missing-incident", "version": 1, "zone": "front_pit"}
            command.update(incident_id=incident["id"], expected_version=incident["version"])
            if op in {"update", "stale"}:
                command.update(kind="update", text=event.get("text", "Persona consciente, necesita evaluación"),
                               zone=event.get("zone", incident["zone"]), confirmed=event.get("confirmed", True))
                if op == "stale":
                    command["expected_version"] = cast(int, incident["version"]) + 1
            elif op == "offer":
                command.update(actor_id=event.get("actor", "medic-a"), role=event.get("role", "medico"))
            else:
                command.update(actions=[{"kind": "stop_show", "actor_id": "coordinator"}],
                               requiere_persona=False, reason="Ensayo de autorización humana, simulado")
        elif op in {"decide", "forbidden_decide"}:
            approval = self.choose("approvals", event, {"pending"}) or {
                "id": "missing-approval", "version": 1, "content_hash": "0" * 64}
            command.update(kind="decide", approval_id=approval["id"], expected_version=approval["version"],
                           approved=True, content_hash=approval["content_hash"])
            if op == "forbidden_decide":
                scope = "proposal"
        else:
            statuses = {"followup": {"declined", "expired"},
                        "accept": {"offered"}, "eta": {"accepted", "en_route"},
                        "arrive": {"accepted", "en_route"}, "locate": {"arrived"}, "complete": {"located"},
                        "decline": {"offered", "accepted", "en_route"}}
            assignment = self.choose("assignments", event, statuses.get(op, set(ACTIVE))) or {
                "id": "missing-assignment", "version": 1, "zone": "front_pit"}
            command.update(assignment_id=assignment["id"], expected_version=assignment["version"])
            if op in {"eta", "bad_eta"}:
                command.update(kind="eta", eta_min=event.get("eta", 4), destination_confirmed=True,
                               destination_zone_id=assignment["zone"])
                if op == "bad_eta":
                    command["eta_min"] = event.get("eta", -1)
                    command["destination_confirmed"] = False
            elif op in {"decline", "followup"}:
                command["reason"] = ("Imprevisto sintético: equipo no puede continuar" if op == "decline"
                                     else "Operador confirma seguimiento y disponibilidad en simulación")
        return command, scope


def generate(seed: int, events: int = 100) -> list[Document]:
    rng = random.Random(seed)
    prefix: list[Document] = [
        {"op": "register", "actor": "medic-a"},
        {"op": "register", "actor": "medic-b"},
        {"op": "register", "actor": "coordinator", "role": "organizador"},
        {"op": "register", "actor": "police", "role": "policia", "channel": "phone"},
        {"op": "report", "id": "first-victim"},
        {"op": "bad_eta", "expect": "reject"},
        {"op": "accept"}, {"op": "eta", "eta": 0}, {"op": "arrive"},
        {"op": "locate"}, {"op": "complete"},
        {"op": "report", "id": "victim-one"}, {"op": "report", "id": "victim-two"},
        {"op": "replay"}, {"op": "collision", "expect": "reject"},
        {"op": "stale", "expect": "reject"},
        {"op": "propose"}, {"op": "forbidden_decide", "expect": "reject"}, {"op": "decide"},
        {"op": "decline"}, {"op": "availability", "expect": "either"},
        {"op": "offer", "role": "bomberos", "expect": "reject"},
        {"op": "update", "expect": "either", "text": "Confirmo: persona consciente con mareo"},
        {"op": "expire"}, {"op": "drain"}, {"op": "reopen"},
    ]
    choices = ("report", "report", "update", "availability", "offer", "accept", "decline", "eta",
               "arrive", "locate", "complete", "bad_eta", "stale", "propose", "decide",
               "forbidden_decide", "expire", "drain", "uncertain", "followup", "reopen", "replay", "collision")
    result: list[Document] = []
    for index in range(events):
        if index < len(prefix):
            event = dict(prefix[index])
        else:
            op = rng.choice(choices)
            event = {"op": op, "pick": rng.randrange(100), "expect": "either"}
            if op == "report":
                event.update(text=rng.choice(TEXTS), zone=rng.choice(["front_pit", "gate_a", "gate_b", None, "invalid-zone"]))
            elif op == "availability":
                event["availability"] = rng.choice(["available", "unavailable", "unknown", "invalid"])
            elif op == "update":
                event.update(text=rng.choice(TEXTS), zone=rng.choice(["gate_a", "front_pit", None]))
            elif op == "eta":
                event["eta"] = rng.choice([0, 4, 240])
            elif op == "bad_eta":
                event["eta"] = rng.choice([-1, 241, "four", True])
            if op in {"bad_eta", "stale", "forbidden_decide", "collision"}:
                event["expect"] = "reject"
        event.setdefault("id", f"seed-{seed}-event-{index}")
        result.append(event)
    return result


def replay(path: Path, events: list[Document]) -> tuple[list[Document], Document, str | None]:
    scenario = Scenario(path)
    failure: str | None = None
    try:
        for event in events:
            scenario.step(event)
    except (AssertionError, OperationalError, sqlite3.Error, LookupError, ValueError, TypeError, RuntimeError) as exc:
        failure = exc.code if isinstance(exc, (InvariantFailure, OperationalError)) else type(exc).__name__
        scenario.trace[-1]["failure"] = failure
    finally:
        scenario.close()
    return scenario.trace, cast(Document, dict(scenario.counts)), failure


def minimize(events: list[Document], failure: str) -> tuple[list[Document], int]:
    """ddmin y eliminación unitaria: 1-mínimo, no promesa de mínimo global."""
    attempts = 0

    def reproduces(candidate: list[Document]) -> bool:
        nonlocal attempts
        attempts += 1
        with tempfile.TemporaryDirectory(prefix="mando-reduce-") as directory:
            return replay(Path(directory) / "operations.sqlite", candidate)[2] == failure

    current = list(events)
    width = max(1, len(current) // 2)
    while width:
        index = 0
        while index < len(current):
            candidate = current[:index] + current[index + width:]
            if candidate and reproduces(candidate):
                current = candidate
                index = 0
            else:
                index += width
        width //= 2
    for index, event in enumerate(current):
        simpler = {**event, "pick": 0}
        if "text" in simpler:
            simpler["text"] = "Persona desmayada"
        candidate = current[:index] + [simpler] + current[index + 1:]
        if candidate != current and reproduces(candidate):
            current = candidate
    index = 0
    while index < len(current):
        candidate = current[:index] + current[index + 1:]
        if candidate and reproduces(candidate):
            current, index = candidate, 0
        else:
            index += 1
    return current, attempts


def fingerprint() -> Document:
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True, check=True).stdout != ""
    digest = hashlib.sha256()
    for path in sorted((ROOT / "motor").rglob("*.py")):
        if ".venv" not in path.parts:
            digest.update(str(path.relative_to(ROOT)).encode())
            digest.update(path.read_bytes())
    return {"sha": sha, "dirty": dirty, "python_sources_sha256": digest.hexdigest()}


def fresh_output(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == ROOT or ROOT in resolved.parents:
        raise ValueError("Los artefactos deben quedar fuera del repositorio")
    # No se abre ni sustituye una DB existente, incluso si el operador apunta a producción.
    resolved.mkdir(mode=0o700, parents=False, exist_ok=False)
    return resolved


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def run_batch(output: Path, *, seed: int = 1701, seeds: int = 200, events: int = 100,
              split: str = "development") -> Document:
    if seeds < 1 or events < 1 or seed < 0 or split not in {"development", "evaluation"}:
        raise ValueError("Configuración inválida")
    # Paridad separa conjuntos para cualquier número de semillas, no solo el lote por defecto.
    selected = [2 * (seed + index) + int(split == "evaluation") for index in range(seeds)]
    started = time.monotonic()
    initial = fingerprint()
    failures: list[JSON] = []
    totals: Counter[str] = Counter()
    rows: list[JSON] = []
    with offline():
        for current in selected:
            scenario_started = time.monotonic()
            sequence = generate(current, events)
            directory = output / f"seed-{current}"
            directory.mkdir()
            trace, counts, failure = replay(directory / "operations.sqlite", sequence)
            totals.update(cast(dict[str, int], counts))
            row: Document = {"seed": current, "events_planned": events, "events_executed": len(trace),
                             "duration_seconds": time.monotonic() - scenario_started,
                             "counts": counts, "failure": failure}
            rows.append(row)
            if failure:
                write_json(directory / "trace.json", trace)
                reduced, attempts = minimize(sequence[:len(trace)], failure)
                write_json(directory / "minimal.json", {"failure": failure, "events": reduced,
                           "reduction": "1-minimal deletion + field simplification", "attempts": attempts})
                failures.append({"seed": current, "failure": failure, "trace": str(directory / "trace.json"),
                                 "minimal": str(directory / "minimal.json")})
    final = fingerprint()
    stable = initial == final
    manifest: Document = {
        "simulation": True, "providers": "simulated; socket and httpx blocked", "N": seeds,
        "events_planned": seeds * events, "events_executed": sum(int(str(row["events_executed"])) for row in cast(list[Document], rows)),
        "seed": seed, "seeds": cast(JSON, selected), "config": {"events_per_seed": events, "split": split,
        "clock_start": 1000, "festival": FESTIVAL, "resources": 4}, "source_start": initial, "source_end": final,
        "source_stable": stable, "duration_seconds": time.monotonic() - started, "failures": failures,
        "counts": cast(JSON, dict(totals)), "scenarios": rows, "ok": not failures and stable,
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=1701)
    parser.add_argument("--seeds", type=int, default=200)
    parser.add_argument("--events", type=int, default=100)
    parser.add_argument("--split", choices=("development", "evaluation"), default="development")
    parser.add_argument("--output", type=Path, required=True, help="Directorio NUEVO, fuera del repo")
    options = parser.parse_args(argv)
    try:
        output = fresh_output(options.output)
        manifest = run_batch(output, seed=options.seed, seeds=options.seeds, events=options.events, split=options.split)
    except (OSError, ValueError) as exc:
        print(f"Precondición rechazada: {type(exc).__name__}")
        return 2
    print(f"SIMULACIÓN N={manifest['N']}, eventos={manifest['events_executed']}; ok={manifest['ok']}; {output / 'manifest.json'}")
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
