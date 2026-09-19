"""Equipo de agentes: votos parciales, composición, conflictos y cambios."""
from __future__ import annotations

import json
import re
import time
from typing import Any

PAPELES = ("triaje", "prioridad", "recursos", "avisos", "vigia", "critico")
AGENTES = PAPELES + ("equipo",)
AGENTES_OK = AGENTES + ("rapido",)
TIPOS_CAMBIO = ("rechazo", "silencio", "dato_nuevo", "sensor", "prevision", "golpe")
_CAMBIO_ALIAS = {
    "dato nuevo": "dato_nuevo", "dato_nuevo": "dato_nuevo",
    "previsión": "prevision", "previsiones": "prevision", "prevision": "prevision",
    "golpe del jurado": "golpe",
}
_CERRADOS = {"resolved", "false_alarm", "failed"}
_REVISION_TOKEN = {"confirma", "corrige", "confirmar", "corregir", "aprobar", "confirm"}
_CONFIRMA = {"confirma", "confirmar", "confirm", "aprobar", "aprueba", "ok", "acuerdo"}
_CORRIGE = {"corrige", "corregir", "correct", "objecion"}


def _sin_acento(raw: Any) -> str:
    return (str(raw or "").strip().lower()
            .replace("á", "a").replace("é", "e").replace("í", "i")
            .replace("ó", "o").replace("ú", "u").replace("ü", "u"))


_PAPEL_CANON = {
    "triaje": "triaje", "prioridad": "prioridad",
    "recurso": "recursos", "recursos": "recursos",
    "aviso": "avisos", "avisos": "avisos",
    "vigia": "vigia", "critico": "critico", "critica": "critico",
}
_LABEL_RE = re.compile(
    r"(?i)(?:\*\*|__)?(triaje|prioridad|recursos?|avisos?|vig[ií]a|cr[ií]tic[oa])(?:\*\*|__)?\s*[:.\-–—]\s*"
)
_RECURSO_ID_RE = re.compile(r"^[a-z]{2,8}_\d+$")


def _canon_papel(raw: Any) -> str:
    return _PAPEL_CANON.get(_sin_acento(raw), "")


def _es_numero(v: Any) -> bool:
    return isinstance(v, (int, float)) and type(v) is not bool


def parse_agente(raw: Any) -> str:
    name = str(raw or "equipo").strip().lower()
    if name not in AGENTES_OK:
        raise ValueError("agente debe ser triaje | prioridad | recursos | avisos | vigia | critico | equipo | rapido")
    return name


def parse_fase(raw: Any, agente: str = "") -> str | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return "rapida" if agente == "rapido" else None
    name = _sin_acento(raw)
    if name in ("rapida", "fast"):
        return "rapida"
    if name == "revision":
        return "revision"
    raise ValueError("fase debe ser rapida o revision")


def parse_veredicto(body: dict[str, Any]) -> str | None:
    raw = body.get("veredicto")
    if raw is None and isinstance(body.get("revision"), str):
        cand = _sin_acento(body["revision"])
        if cand in _REVISION_TOKEN:
            raw = cand
    if raw is None:
        cr = body.get("critico")
        if isinstance(cr, dict):
            raw = cr.get("veredicto") or cr.get("verdict") or cr.get("resultado")
        elif isinstance(cr, str) and cr.strip():
            raw = cr
    if raw is None:
        return None
    t = _sin_acento(raw)
    if t in _CONFIRMA:
        return "confirma"
    if t in _CORRIGE:
        return "corrige"
    if "confirm" in t or "aprob" in t:
        return "confirma"
    if "corrig" in t or "correct" in t:
        return "corrige"
    return None


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
        "fases": {}, "velocidad": None, "plan_cambio": None,
    })
    return box


def _linea_papel(raw: Any) -> dict[str, Any] | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        return {"razonamiento": raw[:400]}
    if isinstance(raw, dict):
        texto = (raw.get("razonamiento") or raw.get("porque") or raw.get("texto")
                 or raw.get("veredicto") or raw.get("linea") or "")
        if not texto:
            skip = {"agente", "papel", "confianza", "supuestos", "hora", "valor",
                    "prioridad", "priority"}
            bits = [str(v) for k, v in raw.items() if k not in skip and v not in (None, "", [], {})]
            texto = "; ".join(bits)[:400]
        if not str(texto).strip():
            return None
        conf = raw.get("confianza") if _es_numero(raw.get("confianza")) else None
        sup = raw.get("supuestos") if isinstance(raw.get("supuestos"), list) else []
        return {"razonamiento": str(texto)[:400], "confianza": conf,
                "supuestos": [str(x)[:200] for x in sup[:8]]}
    return {"razonamiento": str(raw)[:400]}


def _mezclar_papeles(out: dict[str, dict[str, Any]], extra: dict[str, dict[str, Any]]) -> None:
    for name, row in extra.items():
        if name in PAPELES and name not in out and row:
            out[name] = row


def desglosar_texto(texto: str) -> dict[str, dict[str, Any]]:
    """Parte un bloque «Triaje: … Prioridad: …» en una línea por papel."""
    raw = str(texto or "").strip()
    if not raw:
        return {}
    matches = list(_LABEL_RE.finditer(raw))
    if not matches:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for i, m in enumerate(matches):
        key = _canon_papel(m.group(1))
        if key not in PAPELES:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        chunk = raw[m.end():end].strip().strip(";,").strip()
        row = _linea_papel(chunk)
        if row:
            out[key] = row
    return out


def _menciona_seis(texto: str) -> bool:
    t = _sin_acento(texto)
    return all(tok in t for tok in ("triaje", "prioridad", "recurso", "aviso", "vigia", "critico"))


def _absorber_textos(out: dict[str, dict[str, Any]], textos: list[str]) -> None:
    unlabeled: list[str] = []
    for s in textos:
        parsed = desglosar_texto(s)
        if parsed:
            _mezclar_papeles(out, parsed)
        elif str(s).strip():
            unlabeled.append(str(s).strip())
    if not unlabeled:
        return
    parsed = desglosar_texto("\n".join(unlabeled))
    if parsed:
        _mezclar_papeles(out, parsed)
        return
    missing = [p for p in PAPELES if p not in out]
    for name, s in zip(missing, unlabeled):
        row = _linea_papel(s)
        if row:
            out[name] = row


def extraer_por_papel(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}

    def put(name: str, raw: Any) -> None:
        key = _canon_papel(name) or str(name or "").strip().lower()
        if key not in PAPELES:
            return
        row = _linea_papel(raw)
        if row:
            out[key] = row

    raw = body.get("por_papel")
    if isinstance(raw, str) and raw.strip()[:1] in "{[":
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, (dict, list)):
                raw = parsed
        except ValueError:
            pass
    if isinstance(raw, dict):
        for name, val in raw.items():
            put(name, val)
    elif isinstance(raw, list):
        leftover: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                etiqueta = str(item.get("agente") or item.get("papel") or "")
                if _canon_papel(etiqueta) in PAPELES:
                    put(etiqueta, item)
                else:
                    texto = (item.get("razonamiento") or item.get("porque")
                             or item.get("texto") or item.get("linea") or "")
                    parsed = desglosar_texto(str(texto))
                    if parsed:
                        _mezclar_papeles(out, parsed)
                    elif str(texto).strip():
                        leftover.append(str(texto).strip())
            elif isinstance(item, str):
                leftover.append(item)
        _absorber_textos(out, leftover)
    elif isinstance(raw, str):
        _mezclar_papeles(out, desglosar_texto(raw))
    for name in PAPELES:
        if name in out:
            continue
        v = body.get(name)
        if name == "prioridad" and _es_numero(v):
            continue
        if name in ("recursos", "avisos") and isinstance(v, list):
            continue
        put(name, v)
    for item in body.get("especialistas") or []:
        if isinstance(item, dict):
            put(str(item.get("agente") or item.get("papel") or ""), item)
    if len(out) < len(PAPELES):
        blob = " ".join(str(body.get(k) or "") for k in
                        ("porque", "why", "razonamiento", "recomendacion"))
        if _menciona_seis(blob):
            _mezclar_papeles(out, desglosar_texto(blob))
    return out


def peel_decision_fields(body: dict[str, Any]) -> dict[str, Any]:
    out = dict(body)
    p = out.get("prioridad")
    if isinstance(p, dict):
        valor = p.get("valor")
        if valor is None:
            for k in ("prioridad", "priority"):
                if _es_numero(p.get(k)):
                    valor = p.get(k)
                    break
        out["prioridad"] = valor
    rec = out.get("recursos")
    if isinstance(rec, str):
        tok = rec.strip().lower()
        if _RECURSO_ID_RE.fullmatch(tok):
            out["recursos"] = [tok]
        else:
            out.pop("recursos", None)
    return out


def stamp_aviso(session: Any, incident_id: str, body: dict[str, Any]) -> float:
    box = card(session, incident_id)
    if "aviso_at" in box:
        return float(box["aviso_at"])
    raw = body.get("aviso_at", body.get("t_aviso"))
    ts: float | None = None
    if raw is not None:
        try:
            ts = float(raw)
            if ts > 1e12:
                ts /= 1000.0
        except (TypeError, ValueError):
            ts = None
    box["aviso_at"] = time.time() if ts is None else ts
    return float(box["aviso_at"])


def latencia_s(session: Any, incident_id: str, body: dict[str, Any]) -> int:
    t0 = stamp_aviso(session, incident_id, body)
    return int(max(0, round(time.time() - t0)))


def record_papeles(session: Any, incident_id: str, papeles: dict[str, dict[str, Any]]) -> None:
    if not papeles:
        return
    box = card(session, incident_id)
    clock = (session.world.observe().clock or {}).get("hhmm") or time.strftime("%H:%M")
    for name, row in papeles.items():
        if name not in PAPELES:
            continue
        box["agentes"][name] = {
            "agente": name,
            "razonamiento": str(row.get("razonamiento") or "")[:240],
            "confianza": row.get("confianza"),
            "supuestos": list(row.get("supuestos") or [])[:8],
            "hora": clock,
        }


def record_fase(session: Any, incident_id: str, fase: str, *, s: int, agente: str = "",
                porque: str = "", veredicto: str | None = None, tardia: bool = False) -> dict[str, Any]:
    box = card(session, incident_id)
    fases = box.setdefault("fases", {})
    row: dict[str, Any] = {"s": s, "agente": agente, "hora": time.strftime("%H:%M"),
                           "porque": str(porque or "")[:400]}
    if veredicto:
        row["veredicto"] = veredicto
    if tardia:
        row["tardia"] = True
    fases[fase] = row
    rev = fases.get("revision") or {}
    box["velocidad"] = {
        "rapida_s": (fases.get("rapida") or {}).get("s"),
        "revision_s": rev.get("s"),
        "revision": rev.get("veredicto") or "pendiente",
    }
    return box["velocidad"]


def revision_tardia(session: Any, incident_id: str) -> str | None:
    inc = session.agent.incidents.get(incident_id)
    if inc is None:
        return "incidente desconocido"
    if str(inc.status) in _CERRADOS:
        return "incidente cerrado"
    box = getattr(session, "_equipo", {}).get(incident_id) or {}
    vel = box.get("velocidad") or {}
    if vel.get("revision") == "corrige":
        return "ya corregido"
    return None


def record_vote(session: Any, incident_id: str, decision: dict[str, Any]) -> None:
    agente = parse_agente(decision.get("agente"))
    if agente == "rapido":
        return
    box = card(session, incident_id)
    clock = (session.world.observe().clock or {}).get("hhmm") or ""
    row = {
        "razonamiento": str(decision.get("porque") or "")[:240],
        "confianza": decision.get("confianza"),
        "supuestos": list(decision.get("supuestos") or [])[:8],
        "hora": clock or time.strftime("%H:%M"),
        "agente": agente,
    }
    if _es_numero(decision.get("s")):
        row["s"] = int(decision["s"])
    box["agentes"][agente] = row
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
        ab_lat = {x.get("papel"): x.get("s") for x in ((box.get("abanico") or {}).get("llegados") or [])
                  if isinstance(x, dict) and x.get("papel")}
        for name, row in (box.get("agentes") or {}).items():
            if reserved:
                agentes[name] = {
                    "agente": name, "razonamiento": None, "supuestos": [],
                    "confianza": row.get("confianza"), "hora": row.get("hora"), "s": row.get("s"),
                    "categoria": inc.get("family") or inc.get("type"), "zona": inc.get("zone"),
                }
            else:
                agentes[name] = {k: row.get(k) for k in ("agente", "razonamiento", "confianza", "supuestos", "hora", "s")}
            if agentes[name].get("s") is None and name in ab_lat:
                agentes[name]["s"] = ab_lat[name]
        rec: dict[str, Any] = {
            "agentes": agentes,
            "ejecutado": [] if reserved else list(box.get("ejecutado") or []),
            "bloqueado": [] if reserved else list(box.get("bloqueado") or []),
            "espera_persona": [] if reserved else list(box.get("espera_persona") or []),
            "conflicto": None if reserved else box.get("conflicto"),
        }
        ab = box.get("abanico")
        if isinstance(ab, dict):
            rec["abanico"] = {
                "lanzados": list(ab.get("lanzados") or []),
                "llegados": list(ab.get("llegados") or []),
                "timeouts": list(ab.get("timeouts") or []),
                "primera_decision_s": ab.get("primera_decision_s"),
                "final_s": ab.get("final_s"),
                "fuente": ab.get("fuente"),
            }
        vel = box.get("velocidad")
        if vel:
            rec["velocidad"] = {
                "rapida_s": vel.get("rapida_s"),
                "revision_s": vel.get("revision_s"),
                "revision": vel.get("revision") or "pendiente",
            }
        fases = box.get("fases") or {}
        if fases:
            keys = ("s", "agente", "hora", "veredicto", "tardia")
            if not reserved:
                keys = ("s", "agente", "hora", "porque", "veredicto", "tardia")
            rec["fases"] = {fname: {k: row.get(k) for k in keys} for fname, row in fases.items()}
        cambio = box.get("plan_cambio")
        if cambio:
            if reserved:
                rec["plan_cambio"] = {k: cambio.get(k) for k in ("viejo_id", "nuevo_id")}
            else:
                rec["plan_cambio"] = dict(cambio)
        out[iid] = rec
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
