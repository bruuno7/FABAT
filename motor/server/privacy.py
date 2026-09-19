"""Proyección pública única: conserva la estructura y elimina datos reservados y teléfonos."""
import re
from ipaddress import ip_address
from typing import Any

from motor.mando.parser import HeuristicParser

PHONE = re.compile(r"(?<![\w])\+?\d(?:[\s().-]*\d){8,14}(?!\w)")


def _phone(match: re.Match) -> str:
    text = match.group()
    try:
        ip_address(text)
        return text
    except ValueError:
        return "(teléfono oculto)"


def scrub(value: Any) -> Any:
    if isinstance(value, str):
        return PHONE.sub(_phone, value)
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k not in
                ("phone", "to_number", "from_number", "contact", "callback_token", "reply_to")}
    return value


def sensitive(report: Any, zones: dict) -> bool:
    try:
        return bool(HeuristicParser().parse(report, zones).get("reserved"))
    except Exception:
        return True  # hasta poder clasificarlo, no se publica texto entrante


def private_reports(reports: list, meta: dict, zones: dict) -> set[str]:
    hidden = {r.id for r in reports if meta.get(r.id, {}).get("reserved") or sensitive(r, zones)}
    # La reserva se comparte entre el aviso raíz y todas sus actualizaciones, incluso si llega más tarde.
    changed = True
    while changed:
        before = set(hidden)
        truth = {r.truth_incident for r in reports if r.id in hidden and r.truth_incident}
        for r in reports:
            parent = meta.get(r.id, {}).get("update_of")
            if r.id in hidden or parent in hidden or (r.truth_incident and r.truth_incident in truth):
                hidden.add(r.id)
                if parent:
                    hidden.add(parent)
        changed = hidden != before
    return hidden


def project(state: dict, reports: list, meta: dict, zones: dict) -> dict:
    hidden_reports = private_reports(reports, meta, zones)
    hidden = set(hidden_reports)
    hidden.update(r.truth_incident for r in reports if r.id in hidden_reports and r.truth_incident)
    hidden.update(meta[r].get("truth") for r in hidden_reports if meta.get(r, {}).get("truth"))
    for inc in state.get("incidents", []):
        if inc.get("reserved") or hidden_reports.intersection(inc.get("reports", [])):
            hidden.add(inc["id"])
    for key in ("actions", "plans"):
        for item in state.get(key, []):
            if item.get("incident") in hidden or hidden_reports.intersection((item.get("params") or {}).get("reports", [])):
                hidden.add(item["id"])
    resources = {a.get("resource") for a in state.get("actions", []) if a.get("id") in hidden}
    refs = ("id", "ref", "incident", "incident_id", "action", "action_id", "report", "report_id", "plan", "task")
    safe = {"id", "ref", "incident", "incident_id", "action_id", "report_id", "plan", "t", "t_end", "t_open", "status",
            "kind", "channel", "via", "result", "real", "reserved", "reports", "priority", "severity", "version",
            "understood", "origin", "outcome", "n", "number", "broken", "new_plans", "locked_test", "attribution", "src", "holds", "life_threat", "autonomy", "can_take", "waiting_pickup"}

    def walk(value: Any, inherited: bool = False) -> Any:
        if isinstance(value, list):
            return [walk(v, inherited) for v in value]
        if not isinstance(value, dict):
            return scrub(value)
        data = value.get("data") if isinstance(value.get("data"), dict) else {}
        private = inherited or any(isinstance(value.get(k), str) and value[k] in hidden for k in refs)
        private = private or any(isinstance(data.get(k), str) and data[k] in hidden for k in refs)
        effect = value.get("effect") or data.get("effect") or {}
        incident = effect.get("incident") if isinstance(effect, dict) else None
        private = private or (isinstance(incident, dict) and incident.get("id") in hidden)
        private = private or (value.get("id") in resources and "task" in value and "status" in value)
        out = {}
        for key, val in value.items():
            if private and key not in safe:
                if key in ("label", "text", "objective", "title"):
                    out[key] = ("Incidente reservado · entendido por HappyRobot" if key == "text" and data.get("understood") == "happyrobot" else "Incidente reservado")
                elif isinstance(val, list):
                    out[key] = []
                elif isinstance(val, dict):
                    out[key] = {}
                else:
                    out[key] = None
            else:
                out[key] = walk(val, (private or key in hidden) if isinstance(val, (dict, list)) else False)
        if private and "reserved" in value:
            out["reserved"] = True
        return scrub(out)
    return walk(state)
