"""Equipo de agentes: votos parciales, composición, conflictos y cambios."""
from __future__ import annotations

import json
import time
from typing import Any

AGENTES = ("triaje", "prioridad", "recursos", "avisos", "vigia", "critico", "equipo")
TIPOS_CAMBIO = ("rechazo", "silencio", "dato_nuevo", "sensor", "prevision", "golpe")
_CAMBIO_ALIAS = {
    "dato nuevo": "dato_nuevo", "dato_nuevo": "dato_nuevo",
    "previsión": "prevision", "previsiones": "prevision", "prevision": "prevision",
    "golpe del jurado": "golpe",
}


def parse_agente(raw: Any) -> str:
    name = str(raw or "equipo").strip().lower()
    if name not in AGENTES:
        raise ValueError("agente debe ser triaje | prioridad | recursos | avisos | vigia | critico | equipo")
    return name


def parse_cambio(raw: Any) -> str:
    name = str(raw or "").strip().lower().replace(" ", "_")
    name = _CAMBIO_ALIAS.get(name, name)
    if name not in TIPOS_CAMBIO:
        raise ValueError("tipo de cambio: rechazo, silencio, dato_nuevo, sensor, prevision o golpe")
    return name


def _canon(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and type(value) is not bool:
        return round(float(value), 4)
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return value


def _recurso_id(item: Any) -> tuple[str, str | None]:
    if isinstance(item, str):
        return item.strip(), None
    if isinstance(item, dict):
        rid = str(item.get("id") or item.get("recurso") or "").strip()
        zona = item.get("zona") or item.get("zone")
        return rid, str(zona) if zona else None
    return "", None


def compose(votes: list[dict[str, Any]], pesos: dict[str, dict[str, Any]] | None = None
            ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Junta votos. Si dos agentes fijan el mismo escalar a valores distintos, hay conflicto
    salvo que ambos tengan N≥3 y se pueda desempatar por confianza aprendida."""
    joint: dict[str, Any] = {
        "avisar": [], "recursos": [], "acciones": [], "supuestos": [], "vigilar": [],
        "porque": "", "incident_id": "", "fusionar_con": "", "requiere_persona": False,
    }
    owners: dict[str, tuple[str, Any, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    pesos_aplicados: list[dict[str, Any]] = []

    def scalar(field: str, agente: str, value: Any) -> None:
        if value in (None, "", []):
            return
        key = _canon(value)
        if field in owners and owners[field][1] != key:
            if pesos:
                from . import confianza as conf_mod
                a = pesos.get(owners[field][0]) or {}
                b = pesos.get(agente) or {}
                ganador = conf_mod.elige({**a, "agente": owners[field][0]}, {**b, "agente": agente})
                if ganador == agente:
                    pesos_aplicados.append({"campo": field, "ganador": agente, "perdedor": owners[field][0],
                                            "valores": [owners[field][2], value]})
                    owners[field] = (agente, key, value)
                    joint[field] = value
                    return
                if ganador == owners[field][0]:
                    pesos_aplicados.append({"campo": field, "ganador": owners[field][0], "perdedor": agente,
                                            "valores": [owners[field][2], value]})
                    return
            conflicts.append({
                "campo": field,
                "agentes": [owners[field][0], agente],
                "valores": [owners[field][2], value],
            })
            return
        owners[field] = (agente, key, value)
        joint[field] = value

    rec_owner: dict[str, tuple[str, str | None]] = {}
    seen_avisar: set[str] = set()
    seen_acc: dict[tuple[str, str], tuple[str, Any]] = {}

    for vote in votes:
        ag = str(vote.get("agente") or "equipo")
        iid = vote.get("incident_id")
        if iid and str(iid).lower() != "nuevo":
            scalar("incident_id", ag, str(iid).strip())
        scalar("prioridad", ag, vote.get("prioridad"))
        fuse = vote.get("fusionar_con")
        if fuse:
            scalar("fusionar_con", ag, fuse)
        if vote.get("requiere_persona") is True:
            scalar("requiere_persona", ag, True)
        if vote.get("zona"):
            scalar("zona", ag, vote.get("zona"))
        if vote.get("tipo"):
            if not joint.get("tipo"):
                joint["tipo"] = vote["tipo"]
        if vote.get("texto") and not joint.get("texto"):
            joint["texto"] = vote["texto"]
        if vote.get("porque"):
            joint["porque"] = vote["porque"]
        conf = vote.get("confianza")
        if isinstance(conf, (int, float)) and type(conf) is not bool:
            joint["confianza"] = min(float(joint["confianza"]), float(conf)) if "confianza" in joint else float(conf)
        for item in vote.get("supuestos") or []:
            if item not in joint["supuestos"]:
                joint["supuestos"].append(item)
        for item in vote.get("vigilar") or []:
            if item not in joint["vigilar"]:
                joint["vigilar"].append(item)
        for rec in vote.get("recursos") or []:
            rid, zona = _recurso_id(rec)
            if not rid:
                continue
            prev = rec_owner.get(rid)
            if prev and prev[1] and zona and prev[1] != zona:
                conflicts.append({"campo": "recursos", "agentes": [prev[0], ag],
                                  "valores": [{rid: prev[1]}, {rid: zona}]})
                continue
            rec_owner[rid] = (ag, zona or (prev[1] if prev else None))
            if rec not in joint["recursos"] and rid not in { _recurso_id(x)[0] for x in joint["recursos"] }:
                joint["recursos"].append(rec)
        for av in vote.get("avisar") or []:
            mark = _canon(av)
            if mark not in seen_avisar:
                seen_avisar.add(mark)
                joint["avisar"].append(av)
        for act in vote.get("acciones") or []:
            if not isinstance(act, dict):
                continue
            kind = str(act.get("kind") or act.get("tipo") or "")
            zone = str(act.get("zone") or act.get("zona") or "")
            dest = act.get("to") or act.get("hacia")
            key = (kind, zone)
            prev = seen_acc.get(key)
            if prev and prev[1] != _canon(dest) and kind in ("reroute", "evacuate", "stop_show"):
                conflicts.append({"campo": "acciones", "agentes": [prev[0], ag],
                                  "valores": [prev[1], dest]})
                continue
            if kind == "evacuate" and any(str(a.get("kind")) == "reroute" and str(a.get("zone") or a.get("zona") or "") == zone
                                          for a in joint["acciones"]):
                conflicts.append({"campo": "acciones", "agentes": [ag], "valores": ["evacuate vs reroute"]})
                continue
            seen_acc[key] = (ag, _canon(dest))
            joint["acciones"].append(act)
    if pesos_aplicados:
        joint["_pesos"] = pesos_aplicados
    return joint, conflicts


def card(session: Any, incident_id: str) -> dict[str, Any]:
    box = getattr(session, "_equipo", {}).setdefault(incident_id, {
        "agentes": {}, "ejecutado": [], "bloqueado": [], "espera_persona": [], "conflicto": None,
    })
    return box


def record_vote(session: Any, incident_id: str, decision: dict[str, Any]) -> None:
    agente = parse_agente(decision.get("agente"))
    box = card(session, incident_id)
    clock = (session.world.observe().clock or {}).get("hhmm") or ""
    box["agentes"][agente] = {
        "razonamiento": str(decision.get("porque") or "")[:240],
        "confianza": decision.get("confianza"),
        "supuestos": list(decision.get("supuestos") or [])[:8],
        "hora": clock or time.strftime("%H:%M"),
        "agente": agente,
    }
    box["conflicto"] = None


def record_result(session: Any, incident_id: str, out: dict[str, Any],
                  conflicto: list | None = None) -> None:
    box = card(session, incident_id)
    if conflicto:
        box["conflicto"] = conflicto
        return
    aceptadas = list(out.get("aceptadas") or [])
    bloqueadas = list(out.get("bloqueadas") or [])
    box["ejecutado"] = aceptadas
    box["bloqueado"] = bloqueadas
    box["espera_persona"] = [a for a in aceptadas if a.get("tarjeta") or a.get("status") == "awaiting_approval"]
    box["conflicto"] = None


def votes_of(session: Any, incident_id: str) -> list[dict[str, Any]]:
    box = getattr(session, "_equipo", {}).get(incident_id) or {}
    out = []
    for name, row in (box.get("agentes") or {}).items():
        blob = dict(row)
        # the raw decision is kept aside on session._equipo_raw
        raw = getattr(session, "_equipo_raw", {}).get((incident_id, name))
        if raw:
            out.append(dict(raw, agente=name))
        else:
            out.append({"agente": name, "porque": blob.get("razonamiento"),
                        "confianza": blob.get("confianza"), "supuestos": blob.get("supuestos")})
    return out


def store_raw(session: Any, incident_id: str, decision: dict[str, Any]) -> None:
    raw = getattr(session, "_equipo_raw", None)
    if raw is None:
        session._equipo_raw = {}
        raw = session._equipo_raw
    raw[(incident_id, parse_agente(decision.get("agente")))] = dict(decision)


def public_view(session: Any, state: dict[str, Any]) -> dict[str, Any]:
    hidden = {i["id"] for i in state.get("incidents") or [] if i.get("reserved")}
    by_inc = {i["id"]: i for i in state.get("incidents") or []}
    out: dict[str, Any] = {}
    for iid, box in (getattr(session, "_equipo", {}) or {}).items():
        agentes = {}
        reserved = iid in hidden
        inc = by_inc.get(iid) or {}
        for name, row in (box.get("agentes") or {}).items():
            if reserved:
                agentes[name] = {
                    "agente": name, "razonamiento": None, "supuestos": [],
                    "confianza": row.get("confianza"), "hora": row.get("hora"),
                    "categoria": inc.get("family") or inc.get("type"), "zona": inc.get("zone"),
                }
            else:
                agentes[name] = {k: row.get(k) for k in ("agente", "razonamiento", "confianza", "supuestos", "hora")}
        out[iid] = {
            "agentes": agentes,
            "ejecutado": [] if reserved else list(box.get("ejecutado") or []),
            "bloqueado": [] if reserved else list(box.get("bloqueado") or []),
            "espera_persona": [] if reserved else list(box.get("espera_persona") or []),
            "conflicto": None if reserved else box.get("conflicto"),
        }
    return out


def cambio(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    tipo = parse_cambio(body.get("tipo"))
    iid = str(body.get("incident_id") or body.get("incidente") or "").strip()
    zona = str(body.get("zona") or body.get("zone") or "").strip()
    recurso = str(body.get("recurso") or body.get("resource") or "").strip()
    st = session.state()
    afectados: list[dict[str, Any]] = []
    closed = {"resolved", "false_alarm", "failed"}
    for inc in st.get("incidents") or []:
        if inc.get("status") in closed:
            continue
        assigned = list(inc.get("assigned") or [])
        hit = bool(iid and inc.get("id") == iid)
        hit = hit or bool(zona and inc.get("zone") == zona)
        hit = hit or bool(recurso and recurso in assigned)
        hit = hit or (tipo == "golpe" and not iid and not zona and not recurso)
        if not hit:
            continue
        planes = []
        for plan in st.get("plans") or []:
            if plan.get("incident") != inc.get("id"):
                continue
            planes.append({
                "id": plan.get("id"), "objetivo": plan.get("objective"),
                "version": plan.get("version"), "porque": plan.get("why"),
                "supuestos": [a.get("text") for a in (plan.get("assumptions") or []) if isinstance(a, dict)],
            })
        box = (getattr(session, "_equipo", {}) or {}).get(inc["id"]) or {}
        vigilar = []
        for row in (box.get("agentes") or {}).values():
            vigilar.extend(row.get("supuestos") or [])
        afectados.append({
            "incident_id": inc.get("id"), "zona": inc.get("zone"),
            "prioridad": inc.get("priority"), "planes": planes,
            "recursos": assigned, "vigilar": vigilar[:8],
        })
    if iid and not any(a["incident_id"] == iid for a in afectados):
        afectados.append({"incident_id": iid, "zona": zona or None, "planes": [], "recursos": [], "vigilar": []})
    return {
        "ok": True, "tipo": tipo, "afectados": afectados,
        "texto": f"{len(afectados)} incidentes afectados por {tipo}",
    }
