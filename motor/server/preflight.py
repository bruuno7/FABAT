"""Ensayo operativo seguro: SIMULACIÓN, sin .env, llamadas, mensajes ni DB de producción.

python -m motor.server.preflight --seed 1701 --output /tmp/resqval-ensayo-nuevo
Reutiliza OperationalService y el generador; no arranca UI ni un segundo planificador.
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import cast

from .operational_scenarios import (
    InvariantFailure,
    Scenario,
    fingerprint,
    fresh_output,
    offline,
    persisted,
    records,
    require,
    run_batch,
    write_json,
)
from .operational_types import JSON, Document


def plan(scenario: Scenario) -> Document:
    return {"assignments": cast(JSON, records(scenario.service, "assignments")),
            "incidents": cast(JSON, records(scenario.service, "incidents")),
            "revision": scenario.service.state()["revision"]}


def demonstrate(output: Path, seed: int) -> Document:
    """Ensayo con rechazo real en la autoridad, aprobación y reapertura de SQLite."""
    scenario = Scenario(output / "demo.sqlite")
    counter = 0

    def step(op: str, **fields: JSON) -> Document:
        nonlocal counter
        counter += 1
        return scenario.step({"id": f"demo-{seed}-{counter}", "op": op, **fields})

    try:
        for actor, role in (("medic-a", "medico"), ("medic-b", "medico"), ("coordinator", "organizador")):
            step("register", actor=actor, role=role)
        zone = random.Random(seed).choice(["front_pit", "gate_a"])
        step("report", id="victim-one", text="Persona desmayada", zone=zone)
        before = plan(scenario)
        original = records(scenario.service, "assignments")[0]
        step("decline")
        after = plan(scenario)
        assignments = records(scenario.service, "assignments")
        replacement = next(row for row in assignments if row["status"] == "offered")
        declined = next(row for row in assignments if row["id"] == original["id"])
        require(declined["status"] == "declined", "demo_decline_missing")
        require(replacement["actor_id"] != original["actor_id"], "demo_no_alternative")
        require(bool(declined.get("reason")), "demo_reason_missing")
        step("replay")
        step("collision", expect="reject")
        step("propose")
        step("forbidden_decide", expect="reject")
        require(not any(row["purpose"] == "stop_show" for row in records(scenario.service, "deliveries")),
                "demo_unauthorized_effect")
        step("decide")
        require(len([row for row in records(scenario.service, "deliveries") if row["purpose"] == "stop_show"]) == 1,
                "demo_approval_effect_missing")
        for operation in ("accept", "eta", "arrive", "locate", "complete"):
            step(operation)
        step("drain")
        persisted_before = persisted(scenario.path)
        step("reopen")
        require(persisted_before == persisted(scenario.path), "demo_restart_changed_state")
        step("replay")
        result: Document = {
            "simulation": True, "N": 1, "seed": seed, "events": counter,
            "plan_before": before, "unexpected_event": {"kind": "decline", "actor_id": original["actor_id"]},
            "plan_after": after, "reason": declined["reason"],
            "next_action": {"kind": "offer", "actor_id": replacement["actor_id"], "zone": replacement["zone"]},
            "evidence": {"idempotent_replay": True, "collision_rolled_back": True,
                         "workflow_cannot_approve": True, "human_approval_effects": 1,
                         "transitions_distinct": True, "persisted_after_reopen": True},
            "final_plan": plan(scenario), "ok": True,
        }
        write_json(output / "demo.json", result)
        return result
    finally:
        write_json(output / "demo-trace.json", scenario.trace)
        scenario.close()


def run_preflight(output: Path, seed: int = 1701) -> Document:
    started = time.monotonic()
    initial = fingerprint()
    errors: list[JSON] = []
    demo: Document = {}
    batch: Document = {}
    with offline():
        try:
            demo = demonstrate(output, seed)
        except (AssertionError, ValueError, OSError, sqlite3.Error, LookupError, RuntimeError, TypeError) as exc:
            # El código, no repr(exc): ningún valor de configuración ambiental se publica.
            errors.append(exc.code if isinstance(exc, InvariantFailure) else type(exc).__name__)
        try:
            batch_output = output / "scenarios"
            batch_output.mkdir()
            batch = run_batch(batch_output, seed=seed, seeds=3, events=30)
        except (AssertionError, ValueError, OSError, sqlite3.Error, LookupError, RuntimeError, TypeError) as exc:
            errors.append(exc.code if isinstance(exc, InvariantFailure) else type(exc).__name__)
    final = fingerprint()
    result: Document = {"simulation": True, "seed": seed, "N_demo": 1, "N_scenarios": 3,
                        "source_start": initial, "source_end": final, "source_stable": initial == final,
                        "duration_seconds": time.monotonic() - started, "errors": errors,
                        "demo": demo, "scenarios": batch,
                        "ok": not errors and demo.get("ok") is True and batch.get("ok") is True and initial == final,
                        "scope": "Ensayo local, no certifica UI, HTTP, plataforma ni emergencias reales"}
    write_json(output / "preflight.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=1701)
    parser.add_argument("--output", type=Path, help="Directorio NUEVO fuera del repositorio; por defecto temporal aislado")
    options = parser.parse_args(argv)
    try:
        if options.seed < 0:
            raise ValueError("La semilla debe ser no negativa")
        output = fresh_output(options.output) if options.output else Path(tempfile.mkdtemp(prefix="resqval-preflight-"))
        result = run_preflight(output, options.seed)
    except (OSError, ValueError) as exc:
        print(f"Precondición rechazada: {type(exc).__name__}")
        return 2
    print("SIMULACIÓN N=1 demo + N=3 escenarios × 30 eventos; proveedores simulados, red bloqueada.")
    demo = cast(Document, result["demo"])
    if demo:
        change = cast(Document, demo["unexpected_event"])
        action = cast(Document, demo["next_action"])
        print(f"Plan anterior: {change['actor_id']} ofrecido; imprevisto: rechazo.")
        print(f"Plan posterior: {action['actor_id']} hacia {action['zone']}. Razón: {demo['reason']}")
        print("Evidencias: replay sin duplicados, aprobación humana, etapas distintas y persistencia tras reapertura.")
    print(f"ok={result['ok']}; evidencia: {output / 'preflight.json'}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
