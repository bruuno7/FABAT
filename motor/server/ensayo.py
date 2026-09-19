"""Guion auditable, N=1, sin pantalla, red ni aprobaciones humanas ficticias.

Se usa el caso y su semilla originales, el playbook de partida y ningún ajuste
local. El operador simulado pertenece exclusivamente a este comando explícito.
"""
from __future__ import annotations

import argparse
import copy
import json
from typing import Any

from .app import Session, load_case


MILESTONES = (
    "avisos_fusionados", "despacho_aceptado", "supuesto_roto", "plan_nuevo",
    "tarjeta_decision", "aprobacion_operador_simulado", "informe",
)
METRICS = (
    "critical_failed", "critical_total", "incidents_total", "incidents_resolved",
    "merges", "replans", "assumptions_broken", "calls_total", "calls_failed",
    "calls_recovered", "unsafe_actions", "unsafe_blocked", "approvals_requested",
    "agent_errors", "minutes_over_5", "fronts_peak", "peak_density",
)


def _scheduled_blow(case: dict[str, Any]) -> dict[str, Any] | None:
    return next((e for e in sorted(case.get("events", []), key=lambda e: e.get("t", 0))
                 if e.get("kind") == "world" and e.get("effect", {}).get("kind") == "resource_offline"
                 and e.get("t", 0) > 0), None)


def prepare_key_moment(session: Session) -> dict[str, Any]:
    """Avanza una sesión nueva de simulación hasta antes del golpe del caso.

    World.step dispara los eventos al entrar en su minuto: en demo-1 se para
    en t=7, antes del resource_offline de t=8. No duplica el golpe ni aprueba.
    El llamador debe crear la sesión con playbook='seed', local_params=False.
    """
    if session.comms_mode != "sim" or session.comms.mode != "sim":
        raise ValueError("El momento clave exige comunicaciones simuladas")
    if session.world.t != 0 or session.running or session._thread is not None:
        raise ValueError("El momento clave exige una sesión nueva, pausada y sin hilo")
    if session.auto_approve_min is not None or session.replay is not None:
        raise ValueError("El momento clave no permite autoaprobaciones ni replays")
    if session.playbook_choice != "seed" or getattr(session.agent, "params", None) is not None:
        raise ValueError("El momento clave exige playbook seed y parámetros locales desactivados")
    blow = _scheduled_blow(session.case)
    if blow is None or blow["t"] > session.case.get("duration_min", 0):
        raise ValueError("El caso no contiene un golpe de recurso preparable")
    # Los routers de una app viva no deben mandar las preguntas del guion fuera.
    session.comms.external_ask = None
    while session.world.t < blow["t"] - 1:
        session.tick()
    return {"t": session.world.t, "scheduled_t": blow["t"], "effect": copy.deepcopy(blow["effect"])}


def run_ensayo(case_id: str = "demo-1") -> dict[str, Any]:
    case = load_case(case_id)
    session = Session(case, seed=case.get("seed", 0), comms_mode="sim", threaded=False,
                      playbook="seed", local_params=False)
    session.comms.external_ask = None
    milestones = {key: {"ok": False, "evidence": None} for key in MILESTONES}
    blow = _scheduled_blow(case)
    broken_plan = None
    card_ids: set[str] = set()

    def record(key: str, evidence: dict[str, Any]) -> None:
        if not milestones[key]["ok"]:
            milestones[key] = {"ok": True, "evidence": copy.deepcopy(evidence)}

    try:
        while not session.world.done():
            session.tick()
            st = session.state()
            for action in st["actions"]:
                if action["kind"] == "merge" and action["status"] == "done":
                    reports = action.get("params", {}).get("reports", [])
                    if len(reports) >= 2:
                        record("avisos_fusionados", {"t": st["t"], "action": action["id"], "reports": reports})
            for call in st["calls"]["calls"]:
                if call["kind"] == "dispatch" and call["result"] == "accept" and not call["real"]:
                    record("despacho_aceptado", {k: call[k] for k in ("action_id", "resource", "t", "t_end", "result")})
            for entry in st["log"]:
                check = entry.get("data", {}).get("check", {})
                if (blow and entry["kind"] == "assumption_broken" and entry["t"] >= blow["t"]
                        and check.get("kind") == "resource_status_is"
                        and check.get("resource") == blow["effect"]["resource"]):
                    broken_plan = broken_plan or entry["data"]["plan"]
                    record("supuesto_roto", {"t": entry["t"], "plan": entry["data"]["plan"],
                                             "assumption": entry["ref"], "effect": blow["effect"]})
            for plan in st["plans"]:
                if broken_plan and plan.get("supersedes") == broken_plan:
                    record("plan_nuevo", {"t": st["t"], "plan": plan["id"], "supersedes": broken_plan})
            for action in st["approvals"]:
                card = action.get("card")
                if card and action["kind"] == "request_external":
                    card_ids.add(action["id"])
                    record("tarjeta_decision", {"t": st["t"], "action": action["id"], "card": card})
                # Gesto explícito del operador del ensayo, después del golpe.
                if st["t"] >= (blow["t"] + 1 if blow else 1):
                    approved = session.approve(action["id"], True, "EVACUAR · ensayo simulado N=1",
                                               by="operador-simulado")
                    if approved and action["id"] in card_ids:
                        record("aprobacion_operador_simulado", {"t": st["t"], "action": action["id"],
                                                               "by": "operador-simulado"})
        report = session.informe()
        # Proyección explícita: nunca exporta ids de sesión aleatorios ni latencias reales.
        informe = {"t": report["t"], "done": report["session"]["done"],
                   "metrics": {key: report["metrics"][key] for key in METRICS},
                   "approvals": report["approvals"], "truth_incidents": report["truth_incidents"]}
        if informe["done"] and report["session"]["case"] == case["id"]:
            record("informe", {"t": report["t"], "incidents": len(report["truth_incidents"]), "N": 1})
        missing = [key for key, value in milestones.items() if not value["ok"]]
        healthy = (session.engine_error is None and report["metrics"]["agent_errors"] == 0
                   and report["metrics"]["unsafe_actions"] == 0
                   and session.comms.stats["real_sent"] == 0)
        return {"ok": not missing and healthy, "case": case["id"], "seed": session.seed, "N": 1,
                "mode": "sim", "playbook": "seed", "local_params": False,
                "milestones": milestones, "missing": missing, "informe": informe}
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ensayo determinista del guion; simulación N=1")
    parser.add_argument("--case", default="demo-1")
    args = parser.parse_args(argv)
    try:
        result = run_ensayo(args.case)
    except (KeyError, ValueError) as exc:
        result = {"ok": False, "N": 1, "error": type(exc).__name__, "missing": list(MILESTONES)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
