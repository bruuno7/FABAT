"""Herramientas HTTP del agente cerebro: /hr/tools/… (POST JSON, token de callbacks)."""
from __future__ import annotations

import json
import re
import secrets
from typing import Any

from fastapi import HTTPException, Request

from motor.contracts import (ALWAYS_APPROVE, Action, ActionKind, ActionStatus, Autonomy, Channel, Family,
                             Incident, Report)
from motor.mando.lexicon import spec_for
from motor.mando.parser import HeuristicParser
from motor.mando.rehearsal import Rehearsal
from motor.mando.triage import IncidentMeta

from . import forecast as forecast_mod
from . import privacy, recibo, whatif
from . import equipo
from .cerebro import ORIGEN_AGENTE, ORIGEN_BARANDILLA, attach, mark_decided, mode
from .comms_happyrobot import NEVER_DIAL, allowed_numbers, normalize_number
from .hr_routing import WORKFLOW_NAMES, slot_for_role
from .telegram_bot import match_zone

_PHONE = re.compile(r"(?<![\w])\+?\d(?:[\s().-]*\d){8,14}(?!\w)")
_GRAVE_KIND = {ActionKind.EVACUATE, ActionKind.STOP_SHOW, ActionKind.REQUEST_EXTERNAL}
_KIND = {str(k): k for k in ActionKind}
_KIND.update({"evacuar": ActionKind.EVACUATE, "parar": ActionKind.STOP_SHOW,
              "ayuda_externa": ActionKind.REQUEST_EXTERNAL, "desviar": ActionKind.REROUTE,
              "despachar": ActionKind.DISPATCH, "avisar": ActionKind.NOTIFY})
_ZONA_ALIAS = {"foso": "front_pit", "pit": "front_pit", "foso de escenario": "front_pit"}


def _invoke(fn, *args, **kwargs):
    try:
        return _safe(fn(*args, **kwargs))
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except (TypeError, OverflowError):
        raise HTTPException(422, "entrada de tipo incorrecto")


def mount(app: Any, get_session: Any, check_token: Any, operator: Any) -> None:
    @app.post("/hr/tools/contexto")
    async def hr_contexto(request: Request) -> dict[str, Any]:
        check_token(request)
        return _invoke(contexto, get_session(), await _body(request))

    @app.post("/hr/tools/ensayar")
    async def hr_ensayar(request: Request) -> dict[str, Any]:
        check_token(request)
        return _invoke(ensayar, get_session(), await _body(request))

    @app.post("/hr/tools/decidir")
    async def hr_decidir(request: Request) -> dict[str, Any]:
        check_token(request)
        return _invoke(decidir, get_session(), await _body(request))

    @app.post("/hr/tools/cambio")
    async def hr_cambio(request: Request) -> dict[str, Any]:
        check_token(request)
        return _invoke(cambio, get_session(), await _body(request))

    @app.post("/hr/tools/memoria/guardar")
    async def hr_mem_guardar(request: Request) -> dict[str, Any]:
        check_token(request)
        return _invoke(memoria_guardar, get_session(), await _body(request))

    @app.post("/hr/tools/memoria/buscar")
    async def hr_mem_buscar(request: Request) -> dict[str, Any]:
        check_token(request)
        return _invoke(memoria_buscar, get_session(), await _body(request))

    @app.post("/hr/tools/memoria/lecciones")
    async def hr_mem_lecciones(request: Request) -> dict[str, Any]:
        check_token(request)
        body = await _body(request)
        accion = str(body.get("accion") or "listar").strip().lower()
        if accion in ("aprobar", "rechazar", "revocar"):
            operator(request)
        return _invoke(memoria_lecciones, get_session(), body, by=str(body.get("by") or "")[:40])

    @app.post("/api/memoria/lecciones")
    async def api_mem_lecciones(request: Request) -> dict[str, Any]:
        operator(request)
        body = await _body(request)
        if "accion" not in body:
            body = dict(body, accion="aprobar" if body.get("approve") else "rechazar")
        return _invoke(memoria_lecciones, get_session(), body, by=str(body.get("by") or "operador")[:40])

    @app.get("/api/agentes/{incident_id}")
    def api_agentes(incident_id: str) -> dict[str, Any]:
        st = get_session().state()
        rec = (st.get("agentes") or {}).get(incident_id)
        if rec is None:
            raise HTTPException(404, "sin datos de agentes para ese incidente")
        return _safe({"ok": True, "incident_id": incident_id, **rec})

    from . import adaptativo, enjambre, observar

    def _tool(path: str, fn: Any, *, need_operator: bool = False):
        async def _h(request: Request) -> dict[str, Any]:
            check_token(request)
            if need_operator:
                operator(request)
            return _invoke(fn, get_session(), await _body(request))
        _h.__name__ = path.replace("/", "_").strip("_")
        app.add_api_route(path, _h, methods=["POST"])
        return _h

    _tool("/hr/tools/pizarra/publicar", enjambre.publicar)
    _tool("/hr/tools/pizarra/leer", enjambre.leer)
    _tool("/hr/tools/zona", observar.zona)
    _tool("/hr/tools/recurso", observar.recurso)
    _tool("/hr/tools/rutas", observar.rutas)
    _tool("/hr/tools/staff", observar.staff)
    _tool("/hr/tools/previsiones", observar.previsiones)
    _tool("/hr/tools/incidentes_parecidos", observar.incidentes_parecidos)
    _tool("/hr/tools/protocolo", observar.protocolo)
    _tool("/hr/tools/confianza", observar.confianza_tool)
    _tool("/hr/tools/acciones_posibles", observar.acciones_posibles)
    _tool("/hr/tools/comparar_opciones", observar.comparar_opciones)
    _tool("/hr/tools/analizar_situacion", observar.analizar_situacion)
    _tool("/hr/tools/resultado", observar.resultado)

    @app.post("/hr/tools/prompt/proponer")
    async def hr_prompt_prop(request: Request) -> dict[str, Any]:
        check_token(request)
        return _invoke(adaptativo.proponer_prompt, get_session(), await _body(request))

    @app.post("/hr/tools/prompt/listar")
    async def hr_prompt_list(request: Request) -> dict[str, Any]:
        check_token(request)
        body = await _body(request)
        led = getattr(get_session(), "ledger", None)
        rows = led.prompt_listar(str(body.get("agente") or "")) if led is not None else []
        return _safe({"ok": True, "versiones": rows, "texto": f"{len(rows)} versiones"})

    @app.post("/hr/tools/prompt/comparar")
    async def hr_prompt_cmp(request: Request) -> dict[str, Any]:
        check_token(request)
        return _invoke(adaptativo.comparar_prompts, get_session(), await _body(request))

    @app.post("/api/prompt/versiones")
    async def api_prompt_ver(request: Request) -> dict[str, Any]:
        operator(request)
        body = await _body(request)
        return _invoke(adaptativo.decidir_prompt, get_session(), body, by=str(body.get("by") or "operador")[:40])

    @app.get("/api/adaptacion")
    def api_adaptacion() -> dict[str, Any]:
        return _safe(adaptativo.snapshot(get_session()))


def sync_agent(session: Any) -> None:
    agent = session.agent
    obs = session.world.observe()
    agent.t = session.world.t
    agent.zones, agent.resources = obs.zones, obs.resources
    agent.weather, agent.clock = obs.weather, obs.clock
    if not getattr(session, "_cerebro_seen", None):
        attach(session)


def contexto(session: Any, aviso: dict[str, Any] | None = None) -> dict[str, Any]:
    sync_agent(session)
    aviso = aviso or {}
    _opt_str(aviso, "tipo", 40)
    _opt_str(aviso, "zona", 40)
    _opt_str(aviso, "texto", 400)
    st = session.state()
    zone_names = {z["id"]: z["name"] for z in st.get("zones", [])}
    zona = _zona(aviso.get("zona") or "", zone_names)
    t = int(st.get("t") or 0)
    abiertos = []
    for i in st.get("incidents", []):
        if i.get("status") in ("resolved", "false_alarm", "failed"):
            continue
        abiertos.append({
            "id": i.get("id"), "que": i.get("label") or i.get("type"), "zona": i.get("zone"),
            "gravedad": i.get("severity"), "prioridad": i.get("priority"), "estado": i.get("status"),
            "recursos": list(i.get("assigned") or []), "minutos_abierto": max(0, t - int(i.get("t_open") or t)),
            "origen": i.get("origin") or "", "vital": bool(i.get("life_threat")),
        })
    tipo_aviso = str(aviso.get("tipo") or "").strip()
    relevant = _zonas_relevantes(st, zona, abiertos)
    zonas = []
    for z in st.get("zones", []):
        if z["id"] not in relevant:
            continue
        zonas.append({
            "id": z["id"], "nombre": z.get("name"), "densidad": z.get("density"),
            "tendencia": z.get("delta"), "estado": z.get("state"),
            "bloqueos": [k for k, v in (z.get("flags") or {}).items() if v in (True, "blocked") or k == "blocked" and v],
        })
    destino = zona or (abiertos[0]["zona"] if abiertos else None)
    libres, ocupados = _recursos_por_tipo(session, destino)
    previsiones = []
    try:
        raw = st.get("forecasts") or []
        if not raw:
            raw = [{"eta_min": p.get("eta_min"), "que": p.get("label") or p.get("metric"),
                    "zona": p.get("zone"), "umbral": p.get("threshold"), "gravedad": p.get("severity")}
                   for p in forecast_mod.forecast(session.world, horizon=15)[:8]]
        for p in raw[:8]:
            if isinstance(p, dict):
                previsiones.append({
                    "id": p.get("id"), "que": p.get("que") or p.get("label") or p.get("metric"),
                    "zona": p.get("zona") or p.get("zone"),
                    "cuenta_atras_min": p.get("cuenta_atras_min") or p.get("eta_min") or (
                        (p.get("due_t") - t) if p.get("due_t") is not None else None),
                    "estado": p.get("status") or p.get("gravedad"),
                })
    except (TypeError, ValueError):
        previsiones = []
    pendientes = []
    for a in st.get("approvals") or []:
        pendientes.append({
            "id": a.get("id"), "que": a.get("kind"), "zona": a.get("zone"),
            "cargo": (a.get("card") or {}).get("role"), "porque": a.get("why"),
        })
    led = getattr(session, "ledger", None)
    lecciones = []
    agente_ctx = str(aviso.get("agente") or "").strip().lower()
    if led is not None:
        if agente_ctx:
            lecciones = led.list_lecciones(estado="aprobada", tipo=tipo_aviso, zona=zona or "",
                                           para_agente=agente_ctx, limit=8)
        else:
            lecciones = led.list_lecciones(estado="aprobada", tipo=tipo_aviso, zona=zona or "", limit=8)
    parecidos = []
    if led is not None:
        parecidos = led.search_cerebro(tipo=tipo_aviso, zona=zona or "", limit=3)
        if len(parecidos) < 3 and (tipo_aviso or zona):
            extra = led.search_cerebro(texto=tipo_aviso or zona or "", limit=3)
            seen = {p["id"] for p in parecidos}
            for p in extra:
                if p["id"] not in seen:
                    parecidos.append(p)
                if len(parecidos) >= 3:
                    break
    from . import confianza as conf_mod
    texto = ["Contexto para decidir. Cifras de simulación."]
    texto.append(f"{len(abiertos)} incidentes abiertos. {sum(len(v) for v in libres.values())} recursos libres.")
    if pendientes:
        texto.append(f"{len(pendientes)} decisiones pendientes de persona.")
    return {
        "ok": True, "texto": " ".join(texto), "minuto": t,
        "aviso": {"tipo": tipo_aviso or None, "zona": zona},
        "incidentes": abiertos[:20], "recursos_libres": libres, "recursos_ocupados": ocupados,
        "zonas": zonas, "previsiones": previsiones, "decisiones_pendientes": pendientes,
        "memoria": {"lecciones_aprobadas": lecciones, "casos_parecidos": parecidos[:3]},
        "cerebro": mode(),
        "confianza_agentes": conf_mod.resumen(session, familia=tipo_aviso),
        "regla_peso": conf_mod.REGLA_PESO,
    }


def ensayar(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    sync_agent(session)
    raw = body.get("opciones") or body.get("opcion")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not 1 <= len(raw) <= 5:
        raise ValueError("hace falta «opciones»: entre una y cinco alternativas en texto")
    minutes = body.get("minutes") or body.get("minutos") or 12
    if type(minutes) is bool or type(minutes) not in (int, float) or not 10 <= float(minutes) <= 15:
        minutes = 12
    minutes = int(minutes)
    zone_names = {z["id"]: z["name"] for z in session.festival["zones"]}
    resultados = []
    for item in raw:
        texto = item if isinstance(item, str) else str((item or {}).get("texto") or (item or {}).get("opcion") or "")
        if not texto or len(texto) > 240:
            raise ValueError("cada opción debe ser texto de como mucho 240 caracteres")
        try:
            parsed = parse_opcion(texto, zone_names, session.world.observe().resources)
            resultados.append(_ensayar_una(session, parsed, minutes, zone_names))
        except ValueError as exc:
            resultados.append({"texto": texto, "kind": "no_ensayable", "N": 0, "numeros": {},
                               "supuestos": [str(exc)]})
    return {
        "ok": True,
        "texto": "Ensayo en el gemelo: estado de ahora, sin futuro. No cambia el recinto.",
        "minutos": minutes, "opciones": resultados,
        "supuestos": ["El gemelo copia el estado de ahora y no conoce el guion futuro.",
                      "Horizonte 10–15 min; más allá sobreestima."],
    }


def decidir(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    from . import adaptativo, confianza as conf_mod, enjambre
    sync_agent(session)
    if isinstance(body.get("decision"), dict) and not (body.get("porque") or body.get("why")):
        body = dict(body["decision"])
    agente = equipo.parse_agente(body.get("agente"))
    d = validate_decision(body)
    d["agente"] = agente
    key = _vote_key(session, d)
    if key:
        equipo.store_raw(session, key, d)
        equipo.record_vote(session, key, d)
        votos = equipo.votes_of(session, key)
        pesos = conf_mod.pesos_para(session, votos, familia=str(d.get("tipo") or ""))
        joint, conflicts = equipo.compose(votos, pesos=pesos)
        session._equipo_pesos = getattr(session, "_equipo_pesos", {})
        session._equipo_pesos[key] = joint.get("_pesos") or []
        if conflicts:
            equipo.record_result(session, key, {}, conflicto=conflicts)
            with session.lock:
                session._rebuild()
            return {
                "ok": False, "texto": "conflicto entre agentes; no se ejecuta",
                "conflicto": conflicts, "incident_id": key,
                "aceptadas": [], "bloqueadas": [], "origen": ORIGEN_AGENTE,
            }
        if not (joint.get("porque") or "").strip():
            with session.lock:
                session._rebuild()
            return {
                "ok": True, "texto": "voto registrado; falta porque para ejecutar",
                "incident_id": key, "pendiente": True, "aceptadas": [], "bloqueadas": [],
            }
        d = dict(joint)
        d["agente"] = agente
        vital_now = False
        meta = session.agent.meta.get(key)
        vital_now = bool(meta and meta.life_threat)
        if (not vital_now) and adaptativo.exige_revision(session, agente, str(d.get("tipo") or "")) and agente != "equipo":
            with session.lock:
                session._rebuild()
            return {
                "ok": False, "texto": "confianza baja con N suficiente: pasa por revisión de un par",
                "pendiente_revision": True, "incident_id": key, "aceptadas": [], "bloqueadas": [],
            }
    vital = False
    iid_probe = key or d.get("incident_id")
    if iid_probe and iid_probe in getattr(session.agent, "incidents", {}):
        meta = session.agent.meta.get(iid_probe)
        vital = bool(meta and meta.life_threat)
    blocked = enjambre.gate_decidir(session, dict(d, incident_id=iid_probe or d.get("incident_id")), vital=vital)
    if blocked:
        if blocked.get("escalada") and iid_probe and iid_probe in session.agent.incidents:
            _escalar_objeciones(session, session.agent.incidents[iid_probe], blocked.get("objeciones") or [])
        with session.lock:
            session._rebuild()
        blocked["incident_id"] = iid_probe
        blocked["origen"] = ORIGEN_AGENTE
        return blocked
    out = _aplicar_decision(session, d)
    real_id = out["incident_id"]
    if not key:
        stored = dict(d, agente=agente)
        equipo.store_raw(session, real_id, stored)
        equipo.record_vote(session, real_id, stored)
    equipo.record_result(session, real_id, out)
    with session.lock:
        session._rebuild()
    return out


def _escalar_objeciones(session: Any, inc: Any, objeciones: list) -> None:
    texto = "Objeciones altas sin resolver: " + "; ".join(
        f"{o.get('de')}: {o.get('texto')}" for o in objeciones[:4])
    a = session.agent._emit(ActionKind.NOTIFY, inc, texto[:200], channel=Channel.OPERATOR,
                            params={"origen": ORIGEN_AGENTE, "decision_card": True,
                                    "objeciones": objeciones[:8]},
                            status=ActionStatus.AWAITING_APPROVAL)
    a.params["origen"] = ORIGEN_AGENTE


def cambio(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    from . import confianza as conf_mod
    sync_agent(session)
    out = equipo.cambio(session, body)
    tipo = str(body.get("tipo") or "")
    ag = str(body.get("agente") or "recursos")
    fam = str(body.get("familia") or body.get("tipo_incidente") or "")
    if tipo in ("rechazo", "silencio") and body.get("agente"):
        try:
            conf_mod.aplicar(session, ag, fam or "todas", "rechazo" if tipo == "rechazo" else "silencio")
        except ValueError:
            pass
    return out


def _vote_key(session: Any, d: dict[str, Any]) -> str | None:
    agent = session.agent
    iid = d.get("incident_id") or ""
    fuse = d.get("fusionar_con") or ""
    if fuse and fuse in agent.incidents:
        return fuse
    if iid and iid.lower() != "nuevo" and iid in agent.incidents:
        return iid
    return None


def _aplicar_decision(session: Any, d: dict[str, Any]) -> dict[str, Any]:
    agent = session.agent
    aceptadas: list[dict[str, Any]] = []
    bloqueadas: list[dict[str, Any]] = []
    inc, creado = _ensure_incident(session, d)
    if d.get("prioridad") is not None:
        inc.priority = float(d["prioridad"])
    meta = agent.meta[inc.id]
    meta.origin = ORIGEN_AGENTE
    meta.dirty = None
    porque = d["porque"]
    if d.get("fusionar_con") and d["fusionar_con"] != inc.id and d["fusionar_con"] in agent.incidents:
        other = agent.incidents[d["fusionar_con"]]
        for rid in other.reports:
            if rid not in inc.reports:
                inc.reports.append(rid)
        other.notes.append(f"fusionado en {inc.id} por agente HR")
        aceptadas.append({"que": "fusionar", "con": other.id})

    for act in d.get("acciones") or []:
        _aplicar_accion(session, inc, act, porque, aceptadas, bloqueadas)
    for rec in d.get("recursos") or []:
        _aplicar_recurso(session, inc, rec, porque, aceptadas, bloqueadas)
    for aviso in d.get("avisar") or []:
        _aplicar_aviso(session, inc, aviso, aceptadas, bloqueadas)

    if d.get("requiere_persona") and not any(x.get("tarjeta") for x in aceptadas):
        bloqueadas.append({"que": "requiere_persona", "motivo": "marcado para una persona; no se ejecuta solo"})

    if meta.life_threat and not any(x.get("kind") == "dispatch" and x.get("ok") for x in aceptadas):
        rid = _primer_libre(session, ("medical", "ambulance"))
        if rid:
            _aplicar_recurso(session, inc, rid, "barandilla: riesgo vital, despacho inmediato",
                             aceptadas, bloqueadas, origen=ORIGEN_BARANDILLA)
        else:
            bloqueadas.append({"que": "despacho vital", "motivo": "no hay médico ni ambulancia libre"})

    ids = [x["action_id"] for x in aceptadas if x.get("action_id")]
    mark_decided(session, inc.id, ids)
    session.log("action", f"DECISIÓN {ORIGEN_AGENTE}: {porque}", inc.id,
                origen=ORIGEN_AGENTE, confianza=d.get("confianza"), supuesto=d.get("supuestos"))
    with session.lock:
        session._rebuild()
    session._wake.set()
    texto = (f"Aceptadas {len(aceptadas)}, bloqueadas {len(bloqueadas)}."
             + (f" Porque: {porque}" if porque else ""))
    return {
        "ok": True, "texto": texto, "incident_id": inc.id, "nuevo": creado,
        "origen": ORIGEN_AGENTE, "aceptadas": aceptadas, "bloqueadas": bloqueadas,
        "confianza": d.get("confianza"), "requiere_persona": bool(d.get("requiere_persona")),
    }


def memoria_guardar(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    led = getattr(session, "ledger", None)
    eid = str(body.get("id") or f"ce-{session.session_id[:8]}-{secrets.token_hex(3)}")
    if led is None:
        return {"ok": False, "texto": "ledger no disponible", "id": eid}
    clock = (session.world.observe().clock or {}).get("hhmm") or ""
    led.save_cerebro_episode(
        session.session_id, eid,
        tipo=str(body.get("tipo") or "")[:40],
        zona=str(body.get("zona") or "")[:40],
        franja=str(body.get("franja") or clock)[:20],
        entrada=body.get("entrada") if isinstance(body.get("entrada"), dict) else {"aviso": body.get("aviso")},
        contexto=body.get("contexto") if isinstance(body.get("contexto"), dict) else None,
        razonamiento=str(body.get("razonamiento") or "")[:800],
        decision=body.get("decision") if isinstance(body.get("decision"), dict) else None,
        acciones=body.get("acciones") if isinstance(body.get("acciones"), list) else None,
        respuestas=body.get("respuestas") if isinstance(body.get("respuestas"), dict) else None,
        resultado=body.get("resultado") if isinstance(body.get("resultado"), dict) else {"texto": str(body.get("resultado") or "")[:200]},
        tiempos=body.get("tiempos") if isinstance(body.get("tiempos"), dict) else {"t": session.world.t},
        agente=equipo.parse_agente(body.get("agente")),
        confianza=body.get("confianza") if isinstance(body.get("confianza"), (int, float)) and type(body.get("confianza")) is not bool else None,
        supuestos=body.get("supuestos") if isinstance(body.get("supuestos"), list) else None,
    )
    return {"ok": True, "id": eid, "texto": "episodio guardado en el ledger"}


def memoria_buscar(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    led = getattr(session, "ledger", None)
    if led is None:
        return {"ok": False, "casos": [], "texto": "ledger no disponible"}
    casos = led.search_cerebro(tipo=str(body.get("tipo") or ""), zona=str(body.get("zona") or ""),
                               franja=str(body.get("franja") or ""), texto=str(body.get("texto") or ""),
                               limit=int(body.get("limit") or 8))
    return {"ok": True, "texto": f"{len(casos)} casos", "casos": casos}


def memoria_lecciones(session: Any, body: dict[str, Any], *, by: str = "") -> dict[str, Any]:
    led = getattr(session, "ledger", None)
    if led is None:
        return {"ok": False, "texto": "ledger no disponible"}
    accion = str(body.get("accion") or "listar").strip().lower()
    if accion == "listar":
        estado = body.get("estado")
        para = str(body.get("para_agente") or body.get("agente") or "")
        rows = led.list_lecciones(estado=str(estado) if estado else None,
                                  tipo=str(body.get("tipo") or ""), zona=str(body.get("zona") or ""),
                                  para_agente=para or None)
        return {"ok": True, "lecciones": rows, "texto": f"{len(rows)} lecciones"}
    if accion == "proponer":
        texto = str(body.get("texto") or "").strip()
        if not texto or len(texto) > 400:
            raise ValueError("hace falta «texto» de la lección (máx. 400)")
        evidencia = body.get("evidencia") if isinstance(body.get("evidencia"), dict) else {}
        ids = evidencia.get("ids") or body.get("ids") or []
        if not isinstance(ids, list) or not ids:
            raise ValueError("una propuesta lleva evidencia: ids de episodios y N")
        n = evidencia.get("n") or body.get("n") or len(ids)
        if type(n) is bool or type(n) not in (int, float) or n < 1:
            raise ValueError("evidencia.n debe ser un entero ≥ 1")
        lid = str(body.get("id") or f"L-{secrets.token_hex(3)}")
        evidencia = dict(evidencia)
        evidencia["ids"] = [str(x)[:40] for x in ids[:20]]
        evidencia["n"] = int(n)
        if body.get("aplica"):
            evidencia["aplica"] = body.get("aplica")
        if body.get("agente") or body.get("para_agente"):
            evidencia["agente"] = str(body.get("agente") or body.get("para_agente"))[:40]
        out = led.upsert_leccion(lid, texto, evidencia=evidencia, estado="propuesta",
                                 tipo=str(body.get("tipo") or "")[:40],
                                 zona=str(body.get("zona") or "")[:40], by=by, n=int(n),
                                 para_agente=str(body.get("para_agente") or body.get("agente") or "")[:40])
        out["texto"] = "propuesta registrada; una persona tiene que aprobarla"
        return out
    if accion in ("aprobar", "rechazar", "revocar"):
        lid = str(body.get("id") or "")
        if not lid:
            raise ValueError("hace falta el id de la lección")
        out = led.decide_leccion(lid, accion == "aprobar", by=by, revocar=(accion == "revocar"))
        if out is None:
            raise HTTPException(404, "Esa lección no existe")
        return out
    raise ValueError("accion debe ser listar, proponer, aprobar, rechazar o revocar")


def validate_decision(body: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("se esperaba un objeto JSON")
    porque = body.get("porque") or body.get("why") or body.get("razonamiento") or body.get("recomendacion")
    if isinstance(porque, str) and len(porque) > 400:
        porque = porque[:400]
    if not isinstance(porque, str) or not porque.strip():
        raise ValueError("hace falta «porque»: texto de como mucho 400 caracteres")
    prio = body.get("prioridad", body.get("priority"))
    if prio is not None:
        if type(prio) is bool or type(prio) not in (int, float) or not 0 <= float(prio) <= 10:
            raise ValueError("prioridad debe ser un número entre 0 y 10")
        prio = float(prio)
    conf = body.get("confianza", body.get("confidence"))
    if conf is not None:
        if type(conf) is bool or type(conf) not in (int, float) or not 0 <= float(conf) <= 1:
            raise ValueError("confianza debe ser un número entre 0 y 1")
        conf = float(conf)
    rp = body.get("requiere_persona")
    if rp is not None and type(rp) is not bool:
        raise ValueError("requiere_persona debe ser un booleano JSON")
    avisar = body.get("avisar") or []
    if not isinstance(avisar, list) or len(avisar) > 8:
        raise ValueError("avisar debe ser una lista corta")
    for a in avisar:
        if not isinstance(a, dict):
            raise ValueError("cada aviso es {rol|recurso, canal, mensaje}")
        if a.get("mensaje") is not None and (not isinstance(a["mensaje"], str) or len(a["mensaje"]) > 240):
            raise ValueError("mensaje de aviso demasiado largo")
    recursos = body.get("recursos") or []
    if not isinstance(recursos, list) or len(recursos) > 8:
        raise ValueError("recursos debe ser una lista corta")
    supuestos = body.get("supuestos") or []
    vigilar = body.get("vigilar") or []
    for name, seq in (("supuestos", supuestos), ("vigilar", vigilar)):
        if not isinstance(seq, list) or len(seq) > 8:
            raise ValueError(f"{name} debe ser una lista corta de textos")
        for x in seq:
            if not isinstance(x, str) or len(x) > 200:
                raise ValueError(f"cada ítem de {name} es texto corto")
    acciones = body.get("acciones") or []
    if not isinstance(acciones, list) or len(acciones) > 8:
        raise ValueError("acciones debe ser una lista corta")
    for a in acciones:
        if not isinstance(a, dict) or not isinstance(a.get("kind") or a.get("tipo") or "", str):
            raise ValueError("cada acción es {kind, ...}")
    iid = body.get("incident_id") or body.get("incidente")
    if iid is not None and not isinstance(iid, str):
        raise ValueError("incident_id debe ser texto")
    fuse = body.get("fusionar_con")
    if fuse is not None and not isinstance(fuse, str):
        raise ValueError("fusionar_con debe ser texto")
    return {
        "incident_id": (iid or "").strip(), "fusionar_con": (fuse or "").strip(),
        "prioridad": prio, "porque": porque.strip(), "avisar": avisar, "recursos": recursos,
        "supuestos": supuestos, "vigilar": vigilar, "confianza": conf,
        "requiere_persona": bool(rp), "acciones": acciones,
        "texto": str(body.get("texto") or "")[:400], "zona": body.get("zona") or body.get("zone"),
        "tipo": str(body.get("tipo") or "")[:40],
        "agente": str(body.get("agente") or "equipo")[:40],
    }


def parse_opcion(texto: str, zone_names: dict[str, str], resources: dict[str, Any]) -> dict[str, Any]:
    raw = texto.strip()
    t = _plain(raw)
    out: dict[str, Any] = {"texto": raw, "kind": None}
    if "desvi" in t or "reroute" in t:
        out["kind"] = "reroute"
        m = re.search(r"(puerta|gate)\s*([abc])", t)
        origen = f"gate_{m.group(2)}" if m else match_zone(raw, zone_names)
        dests = []
        for m in re.finditer(r"\b([abc])\b", t.split("→")[-1] if "→" in raw else t.split("->")[-1] if "->" in t else t):
            zid = f"gate_{m.group(1)}"
            if zid in zone_names and zid != origen:
                dests.append(zid)
        if not dests:
            for tok in re.split(r"[→>,y/]| y ", raw):
                z = match_zone(tok, zone_names)
                if z and z != origen:
                    dests.append(z)
        out["zone"] = origen if origen in zone_names else None
        out["destinos"] = list(dict.fromkeys(dests))
        return out
    if any(w in t for w in ("mandar", "enviar", "despach", "acude")):
        out["kind"] = "dispatch"
        out["resource"] = _alias_recurso(t, resources)
        out["zone"] = _zona_opcion(raw, t, zone_names)
        return out
    if "evac" in t:
        out["kind"] = "evacuate"
        out["zone"] = _zona_opcion(raw, t, zone_names)
        return out
    if "parar" in t or "stop" in t:
        out["kind"] = "stop_show"
        return out
    raise ValueError(f"no supe interpretar la opción: {raw}")


# ---- internos --------------------------------------------------------------

async def _body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "JSON inválido")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise HTTPException(400, "Se esperaba un objeto JSON")
    raw = data.get("payload_json")
    if isinstance(raw, str) and raw.strip():
        try:
            inner = json.loads(raw)
        except ValueError:
            raise HTTPException(400, "payload_json no es un JSON válido")
        if isinstance(inner, dict):
            data = inner
    return data


def _safe(obj: Any) -> Any:
    return privacy.scrub(obj)


def _plain(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def _opt_str(d: dict, key: str, n: int) -> None:
    if key in d and d[key] is not None and (not isinstance(d[key], str) or len(d[key]) > n):
        raise ValueError(f"{key} debe ser texto de {n} caracteres como mucho")


def _zona_opcion(raw: str, plain: str, names: dict[str, str]) -> str | None:
    for alias, zid in _ZONA_ALIAS.items():
        if alias in plain and zid in names:
            return zid
    return match_zone(raw, names)


def _zona(raw: str, names: dict[str, str]) -> str | None:
    if not raw:
        return None
    if raw in names:
        return raw
    return _zona_opcion(raw, _plain(raw), names)


def _zonas_relevantes(st: dict, zona: str | None, abiertos: list) -> set[str]:
    ids = {zona} if zona else set()
    ids.update(i.get("zona") for i in abiertos if i.get("zona"))
    ids.update(z["id"] for z in st.get("zones", []) if z.get("kind") in ("gate", "stage_front") or (z.get("density") or 0) >= 4)
    ids.discard(None)
    if not ids:
        ids = {z["id"] for z in st.get("zones", [])[:6]}
    return ids


def _recursos_por_tipo(session: Any, destino: str | None) -> tuple[dict, dict]:
    obs = session.world.observe()
    libres: dict[str, list] = {}
    ocupados: dict[str, list] = {}
    for r in obs.resources.values():
        kind = str(r.kind)
        eta = None
        if destino:
            eta = session.world.travel_time(r.zone, destino, r.id)
        row = {"id": r.id, "nombre": r.name, "zona": r.zone, "eta_min": eta, "estado": str(r.status)}
        if str(r.status) == "available":
            libres.setdefault(kind, []).append(row)
        else:
            ocupados.setdefault(kind, []).append(row)
    for bucket in (libres, ocupados):
        for kind, rows in bucket.items():
            rows.sort(key=lambda r: (r.get("eta_min") is None, r.get("eta_min") if r.get("eta_min") is not None else 99))
    return libres, ocupados


def _ensayar_una(session: Any, parsed: dict, minutes: int, zone_names: dict[str, str]) -> dict[str, Any]:
    kind = parsed.get("kind")
    if kind == "reroute":
        dests = parsed.get("destinos") or []
        zone = parsed.get("zone")
        if not zone or not dests:
            raise ValueError("desvío: hace falta origen y destino de la lista de zonas")
        ramas = []
        for dest in dests[:2]:
            d = {"kind": "reroute", "zone": zone, "to": dest, "fraction": 0.5 if len(dests) > 1 else 1.0,
                 "minutes": minutes}
            ramas.append(whatif.rehearse(session.world, d, zone_names))
        nums = []
        for r in ramas:
            alt = r.get("alternative") or {}
            nums.append({"hacia": (r.get("action") or {}).get("to"), "pico": alt.get("peak_density"),
                         "min_sobre_4": alt.get("minutes_over_4"), "veredicto": r.get("verdict")})
        return {"texto": parsed["texto"], "kind": "reroute", "N": 1, "numeros": nums,
                "supuestos": [r.get("note") for r in ramas]}
    if kind == "dispatch":
        rid, zone = parsed.get("resource"), parsed.get("zone")
        if not rid:
            raise ValueError("no reconozco el recurso de esa opción")
        if not zone:
            raise ValueError("no reconozco la zona de esa opción")
        a = Action(id="ENS-1", kind=ActionKind.DISPATCH, t=session.world.t, resource=rid, zone=zone,
                   status=ActionStatus.EXECUTING, params={})
        reh = Rehearsal(lambda: session.world.twin(), horizon=minutes)
        out = reh.run(parsed["texto"], [a], watch=[zone], horizon=minutes, resources=[rid])
        if out is None:
            return {"texto": parsed["texto"], "kind": "dispatch", "numeros": {}, "supuestos": ["gemelo no disponible"]}
        rec = None
        try:
            rec = recibo.calculate(session.world, a, accepted=False, minutes=min(15, minutes))
        except Exception:
            rec = None
        return {"texto": parsed["texto"], "kind": "dispatch", "resource": rid, "zona": zone, "N": 1,
                "numeros": {"pico": round(out.worst, 2), "llegada": out.arrival,
                            "min_sobre_4": sum(out.over4.values())},
                "recibo": {"veredicto": (rec or {}).get("verdict"), "texto": (rec or {}).get("text"),
                           "N": (rec or {}).get("N", 1)} if rec else None,
                "supuestos": ["El gemelo copia el estado de ahora y no conoce el guion futuro.",
                              f"Horizonte {minutes} min; más allá sobreestima."]}
    if kind == "stop_show":
        d = {"kind": kind, "zone": parsed.get("zone"), "minutes": minutes}
        r = whatif.rehearse(session.world, d, zone_names)
        alt = r.get("alternative") or {}
        return {"texto": parsed["texto"], "kind": kind, "N": 1,
                "numeros": {"pico": alt.get("peak_density"), "min_sobre_4": alt.get("minutes_over_4"),
                            "veredicto": r.get("verdict")},
                "supuestos": [r.get("note")]}
    if kind == "evacuate":
        return {"texto": parsed["texto"], "kind": kind, "N": 1, "numeros": {},
                "supuestos": ["Evacuar no se ensaya como AUTO: siempre es tarjeta de una persona."]}
    raise ValueError("opción no ensayable")


def _alias_recurso(texto: str, resources: dict[str, Any]) -> str | None:
    t = _plain(texto)
    for rid in resources:
        if rid in t or _plain(getattr(resources[rid], "name", "")) in t:
            return rid
    m = re.search(r"\b([msatlv]|med|sec|amb|tech|log|vol)[\s_-]?(\d+)\b", t)
    if not m:
        return None
    prefix = {"m": "med", "s": "sec", "a": "amb", "t": "tech", "l": "log", "v": "vol"}.get(m.group(1), m.group(1))
    cand = f"{prefix}_{m.group(2)}"
    return cand if cand in resources else None


def _ensure_incident(session: Any, d: dict[str, Any]) -> tuple[Any, bool]:
    agent = session.agent
    iid = d.get("incident_id") or ""
    fuse = d.get("fusionar_con") or ""
    if fuse and fuse in agent.incidents:
        return agent.incidents[fuse], False
    if iid and iid.lower() != "nuevo" and iid in agent.incidents:
        return agent.incidents[iid], False
    if iid and iid.lower() != "nuevo" and iid not in agent.incidents:
        raise ValueError(f"incidente desconocido: {iid}")
    zone_names = {z["id"]: z["name"] for z in session.festival["zones"]}
    zona = _zona(str(d.get("zona") or ""), zone_names)
    texto = d.get("texto") or d.get("porque") or "aviso del agente"
    obs_zones = session.world.observe().zones
    rep = Report(f"hr-{secrets.token_hex(3)}", session.world.t, Channel.OPERATOR, texto,
                 source="agente HR", zone_hint=zona)
    p = HeuristicParser().parse(rep, obs_zones)
    spec = spec_for(p["type"], p["family"])
    nid = agent.new_id("M")
    inc = Incident(id=nid, family=Family(p["family"]), type=p["type"], zone=p["zone"] or zona,
                   severity=max(1, int(p["severity"] or 5)), t_open=session.world.t,
                   deadline=(session.world.t + spec.deadline) if spec.deadline else None,
                   needs=dict(p.get("needs") or {}), reports=[], confidence=float(p.get("confidence") or 0.7))
    meta = IncidentMeta(group=spec.group, origin=ORIGEN_AGENTE,
                        life_threat=bool(p.get("life_threat", spec.life_threat)),
                        reserved=bool(p.get("reserved", spec.reserved)), last_report_t=session.world.t)
    agent.incidents[nid] = inc
    agent.meta[nid] = meta
    if inc not in agent.live:
        agent.live.append(inc)
    return inc, True


def _aplicar_recurso(session: Any, inc: Any, rec: Any, porque: str, aceptadas: list, bloqueadas: list,
                     origen: str = ORIGEN_AGENTE) -> None:
    rid = rec if isinstance(rec, str) else str((rec or {}).get("id") or (rec or {}).get("recurso") or "")
    zona = None
    if isinstance(rec, dict):
        zona = rec.get("zona") or rec.get("zone")
    _dispatch(session, inc, rid, zona, porque, aceptadas, bloqueadas, origen)


def _dispatch(session: Any, inc: Any, rid: str, zona: str | None, porque: str,
              aceptadas: list, bloqueadas: list, origen: str) -> None:
    agent = session.agent
    obs = session.world.observe()
    rid = (rid or "").strip()
    alias = _alias_recurso(rid, obs.resources) if rid not in obs.resources else rid
    rid = alias or rid
    r = obs.resources.get(rid)
    if r is None:
        bloqueadas.append({"que": "recurso", "id": rid, "motivo": "recurso inexistente"})
        return
    if str(r.status) != "available" or rid in getattr(agent, "assign", {}):
        bloqueadas.append({"que": "recurso", "id": rid, "motivo": "recurso ocupado"})
        return
    dest = zona or inc.zone
    if dest and dest not in {z["id"] for z in session.festival["zones"]}:
        bloqueadas.append({"que": "recurso", "id": rid, "motivo": "destino fuera de la lista blanca de zonas"})
        return
    eta = session.world.travel_time(r.zone, dest, rid) if dest else None
    agent.assign[rid] = (inc.id, str(r.kind))
    if rid not in inc.assigned:
        inc.assigned.append(rid)
    a = agent._emit(ActionKind.DISPATCH, inc, porque, resource=rid, zone=dest, channel=Channel.VOICE,
                    params={"need": str(r.kind), "eta": eta or 0, "origen": origen, "message": porque[:160]})
    a.params["origen"] = origen
    _apply_auto(session, a)
    aceptadas.append({"ok": True, "kind": "dispatch", "action_id": a.id, "recurso": rid, "zona": dest,
                      "eta_min": eta, "origen": origen})


def _aplicar_accion(session: Any, inc: Any, act: dict, porque: str, aceptadas: list, bloqueadas: list) -> None:
    kind_s = str(act.get("kind") or act.get("tipo") or "").strip().lower()
    kind = _KIND.get(kind_s)
    if kind is None:
        bloqueadas.append({"que": kind_s, "motivo": "tipo de acción desconocido"})
        return
    zone_ids = {z["id"] for z in session.festival["zones"]}
    zona = act.get("zone") or act.get("zona") or inc.zone
    if zona and zona not in zone_ids and kind != ActionKind.STOP_SHOW:
        bloqueadas.append({"que": kind_s, "motivo": "destino fuera de la lista blanca de zonas"})
        return
    dest = act.get("to") or act.get("hacia")
    if dest and dest not in zone_ids:
        bloqueadas.append({"que": kind_s, "motivo": "destino fuera de la lista blanca de zonas"})
        return
    params = {k: v for k, v in act.items() if k not in ("kind", "tipo", "zone", "zona")}
    params["origen"] = ORIGEN_AGENTE
    if kind in _GRAVE_KIND:
        a = session.agent._emit(kind, inc, porque, zone=None if kind == ActionKind.STOP_SHOW else zona,
                                params=params)
        a.params["origen"] = ORIGEN_AGENTE
        aceptadas.append({"ok": True, "kind": kind_s, "action_id": a.id, "tarjeta": True,
                          "status": str(a.status), "motivo": "evacuar / parar / ayuda externa → persona",
                          "origen": ORIGEN_AGENTE})
        return
    if kind == ActionKind.DISPATCH:
        _dispatch(session, inc, str(act.get("resource") or ""), zona, porque, aceptadas, bloqueadas, ORIGEN_AGENTE)
        return
    a = session.agent._emit(kind, inc, porque, zone=zona, resource=act.get("resource"),
                            channel=Channel.OPERATOR if kind not in (ActionKind.NOTIFY, ActionKind.ASK) else Channel.VOICE,
                            params=params)
    a.params["origen"] = ORIGEN_AGENTE
    _apply_auto(session, a)
    aceptadas.append({"ok": True, "kind": kind_s, "action_id": a.id, "status": str(a.status), "origen": ORIGEN_AGENTE})


def _aplicar_aviso(session: Any, inc: Any, aviso: dict, aceptadas: list, bloqueadas: list) -> None:
    rol = str(aviso.get("rol") or aviso.get("recurso") or aviso.get("to") or "").strip()
    destino = str(aviso.get("destino") or "").strip()
    mensaje = str(aviso.get("mensaje") or "")[:240]
    canal = str(aviso.get("canal") or "voz").strip().lower()
    probe = destino or rol
    if _PHONE.search(probe) or probe.lstrip("+").isdigit():
        number = normalize_number(probe)
        if number in NEVER_DIAL or number.lstrip("+") in NEVER_DIAL:
            bloqueadas.append({"que": "avisar", "motivo": "destino fuera de la lista blanca (emergencias)"})
            return
        allow = allowed_numbers()
        if not allow or number not in allow:
            bloqueadas.append({"que": "avisar", "motivo": "destino fuera de la lista blanca"})
            return
    slot = slot_for_role(rol)
    if not slot and rol and rol not in session.world.observe().resources and rol not in WORKFLOW_NAMES:
        if not destino:
            bloqueadas.append({"que": "avisar", "rol": rol, "motivo": "destino fuera de la lista blanca"})
            return
    params = {"to": rol or slot, "message": mensaje, "origen": ORIGEN_AGENTE, "canal": canal}
    a = session.agent._emit(ActionKind.NOTIFY, inc, mensaje or "aviso del agente",
                            resource=rol if rol in session.world.observe().resources else None,
                            channel=Channel.VOICE, params=params)
    a.params["origen"] = ORIGEN_AGENTE
    _apply_auto(session, a)
    aceptadas.append({"ok": True, "kind": "notify", "action_id": a.id, "rol": rol, "canal": canal,
                      "origen": ORIGEN_AGENTE})


def _apply_auto(session: Any, a: Action) -> None:
    if a.status == ActionStatus.AWAITING_APPROVAL or a.kind in ALWAYS_APPROVE:
        return
    if str(a.autonomy) == str(Autonomy.APPROVE):
        return
    try:
        session.receipts.capture(session.world, a, human=False)
        session.world.apply(a)
    except Exception:
        pass


def _primer_libre(session: Any, kinds: tuple[str, ...]) -> str | None:
    obs = session.world.observe()
    assigned = getattr(session.agent, "assign", {})
    for kind in kinds:
        for r in obs.resources.values():
            if str(r.kind) == kind and str(r.status) == "available" and r.id not in assigned:
                return r.id
    return None
