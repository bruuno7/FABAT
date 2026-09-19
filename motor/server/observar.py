"""Herramientas pequeñas del enjambre: observar, abrir opciones, comparar, elegir rama."""
from __future__ import annotations

from typing import Any

from motor.contracts import ActionKind

from . import confianza, enjambre, forecast as forecast_mod, privacy
from .cerebro import mode as cerebro_mode


def zona(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    from .cerebro_tools import _zona, sync_agent
    sync_agent(session)
    st = session.state()
    names = {z["id"]: z["name"] for z in st.get("zones", [])}
    zid = _zona(str(body.get("zona") or body.get("id") or ""), names)
    if not zid:
        raise ValueError("hace falta una zona de la lista blanca")
    z = next((x for x in st["zones"] if x["id"] == zid), None)
    if z is None:
        raise ValueError("zona desconocida")
    flags = z.get("flags") or {}
    bloqueos = [k for k, v in flags.items() if v in (True, "blocked") or (k == "blocked" and v)]
    accesos = []
    layout = getattr(session.world, "L", None)
    if layout is not None and zid in layout.idx:
        i = layout.idx[zid]
        for v, _m in layout.adj[i]:
            accesos.append(layout.ids[v])
    incs = [{"id": i.get("id"), "que": i.get("label") or i.get("type"), "prioridad": i.get("priority")}
            for i in st.get("incidents") or [] if i.get("zone") == zid
            and i.get("status") not in ("resolved", "false_alarm", "failed") and not i.get("reserved")]
    return {
        "ok": True, "texto": f"{z.get('name')}: densidad {z.get('density')} tendencia {z.get('delta')}",
        "id": zid, "nombre": z.get("name"), "densidad": z.get("density"), "tendencia": z.get("delta"),
        "estado": z.get("state"), "accesos": accesos, "bloqueos": bloqueos, "incidentes": incs,
    }


def recurso(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    from .cerebro_tools import _alias_recurso, _zona, sync_agent
    sync_agent(session)
    obs = session.world.observe()
    rid = str(body.get("recurso") or body.get("id") or "").strip()
    rid = _alias_recurso(rid, obs.resources) or rid
    r = obs.resources.get(rid)
    if r is None:
        raise ValueError("recurso desconocido")
    names = {z["id"]: z["name"] for z in session.state().get("zones", [])}
    dest = _zona(str(body.get("zona") or ""), names)
    eta = session.world.travel_time(r.zone, dest, rid) if dest else None
    asign = (getattr(session.agent, "assign", {}) or {}).get(rid)
    carga = sum(1 for a in session.state().get("actions") or []
                if a.get("resource") == rid and a.get("kind") == "dispatch")
    return {
        "ok": True, "texto": f"{r.name} en {r.zone} ({r.status})",
        "id": rid, "nombre": r.name, "zona": r.zone, "hace": str(r.task or r.status),
        "estado": str(r.status), "eta_min": eta, "asignado_a": asign[0] if asign else None,
        "carga_dia": carga,
    }


def rutas(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    from .cerebro_tools import _zona, sync_agent
    sync_agent(session)
    names = {z["id"]: z["name"] for z in session.state().get("zones", [])}
    origen = _zona(str(body.get("de") or body.get("origen") or ""), names)
    dest = _zona(str(body.get("a") or body.get("hasta") or body.get("zona") or ""), names)
    if not origen or not dest:
        raise ValueError("hacen falta dos zonas (de, a)")
    rid = str(body.get("recurso") or "") or None
    principal = session.world.travel_time(origen, dest, rid)
    alts = []
    for zid in names:
        if zid in (origen, dest):
            continue
        t1 = session.world.travel_time(origen, zid, rid)
        t2 = session.world.travel_time(zid, dest, rid)
        if t1 is None or t2 is None:
            continue
        alts.append({"via": zid, "eta_min": t1 + t2, "tramos": [t1, t2]})
    alts.sort(key=lambda x: x["eta_min"])
    bloqueos = []
    for z in session.state().get("zones") or []:
        flags = z.get("flags") or {}
        if z.get("state") in ("closed", "restricted") or any(
                v in (True, "blocked") or (k == "blocked" and v) for k, v in flags.items()):
            bloqueos.append(z["id"])
    return {
        "ok": True,
        "texto": ("sin ruta" if principal is None else f"{origen} → {dest} en {principal} min"),
        "de": origen, "a": dest, "eta_min": principal,
        "bloqueada": principal is None, "bloqueos": bloqueos,
        "alternativas": alts[:4],
    }


def staff(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    from .cerebro_tools import sync_agent
    sync_agent(session)
    st = session.state()
    rol = str(body.get("rol") or body.get("kind") or "").strip().lower()
    por_rol: dict[str, list] = {}
    for r in st.get("resources") or []:
        kind = str(r.get("kind") or "")
        if rol and kind != rol and rol not in str(r.get("name") or "").lower():
            continue
        por_rol.setdefault(kind, []).append({
            "id": r.get("id"), "nombre": r.get("name"), "zona": r.get("zone"),
            "estado": r.get("status"),
        })
    tg = st.get("telegram") or {}
    espejo = None
    if isinstance(tg, dict):
        espejo = {"staff": tg.get("staff"), "asignaciones": (tg.get("asignaciones") or [])[:8]}
    return {
        "ok": True, "texto": f"{sum(len(v) for v in por_rol.values())} personas por rol",
        "por_rol": por_rol, "telegram": espejo,
    }


def previsiones(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    from .cerebro_tools import sync_agent
    sync_agent(session)
    horizontes = body.get("minutos") or body.get("horizontes") or (5, 10, 15)
    if isinstance(horizontes, (int, float)) and type(horizontes) is not bool:
        horizontes = [int(horizontes)]
    out = {}
    for h in (5, 10, 15):
        if int(h) not in {int(x) for x in horizontes} and horizontes not in ((5, 10, 15), [5, 10, 15]):
            continue
        try:
            raw = forecast_mod.forecast(session.world, horizon=int(h))[:6]
        except (TypeError, ValueError):
            raw = []
        out[str(int(h))] = [{"que": p.get("label") or p.get("metric"), "zona": p.get("zone"),
                             "eta_min": p.get("eta_min"), "estado": p.get("severity")}
                            for p in raw]
    if not out:
        for h in (5, 10, 15):
            try:
                raw = forecast_mod.forecast(session.world, horizon=h)[:6]
            except (TypeError, ValueError):
                raw = []
            out[str(h)] = [{"que": p.get("label") or p.get("metric"), "zona": p.get("zone"),
                            "eta_min": p.get("eta_min"), "estado": p.get("severity")}
                           for p in raw]
    n = sum(len(v) for v in out.values())
    return {"ok": True, "texto": f"{n} previsiones del gemelo (simulación)", "por_minuto": out}


def incidentes_parecidos(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    led = getattr(session, "ledger", None)
    if led is None:
        return {"ok": False, "casos": [], "texto": "ledger no disponible"}
    casos = led.search_cerebro(tipo=str(body.get("tipo") or ""), zona=str(body.get("zona") or ""),
                               texto=str(body.get("texto") or ""), limit=int(body.get("limit") or 5))
    return {"ok": True, "texto": f"{len(casos)} episodios parecidos", "casos": [
        {"id": c.get("id"), "tipo": c.get("tipo"), "zona": c.get("zona"),
         "que_se_hizo": c.get("que_se_hizo"), "como_acabo": c.get("como_acabo"),
         "agente": c.get("agente")} for c in casos]}


def protocolo(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    from motor.protocolos import load
    tipo = str(body.get("tipo") or body.get("id") or "").strip().lower()
    texto = str(body.get("texto") or "").lower()
    familia = str(body.get("familia") or "").strip().lower()
    data = load()
    found = None
    for p in data.get("protocols") or []:
        if p.get("id") == tipo or (familia and p.get("family") == familia and not tipo):
            found = p
            break
        triggers = (p.get("triggers") or {}).get("es") or []
        blob = f"{tipo} {texto}"
        if any(str(tr).lower() in blob for tr in triggers):
            found = p
            break
    if found is None:
        return {"ok": False, "texto": "sin protocolo para ese tipo", "id": None}
    label = (found.get("label") or {}).get("es") or found.get("id")
    slots = []
    for s in (found.get("slots") or [])[:4]:
        q = s.get("es") or (s.get("ask") or {}).get("es") if isinstance(s, dict) else None
        if isinstance(s, dict):
            q = s.get("es") or ((s.get("ask") or {}).get("es") if isinstance(s.get("ask"), dict) else s.get("ask"))
            slots.append({"id": s.get("id"), "pregunta": q})
    aviso = (data.get("disclaimer") or {}).get("es") or ""
    return {
        "ok": True, "id": found.get("id"), "familia": found.get("family"), "etiqueta": label,
        "texto": f"{label}. Simulación; no sustituye al 112.",
        "instruccion": aviso[:280], "preguntas": slots,
        "despachar_en cuanto": found.get("dispatch_as_soon_as") or [],
        "sensible": bool(found.get("sensitive")),
    }


def confianza_tool(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    familia = str(body.get("familia") or body.get("tipo") or "")
    rows = confianza.resumen(session, familia=familia)
    return {"ok": True, "texto": "confianza por agente (sin evidencia si N<3)", "agentes": rows,
            "regla": confianza.REGLA_PESO}


def acciones_posibles(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    from .cerebro_tools import _zona, sync_agent
    sync_agent(session)
    st = session.state()
    iid = str(body.get("incidente") or body.get("incident_id") or "").strip()
    inc = next((i for i in st.get("incidents") or [] if i.get("id") == iid), None)
    names = {z["id"]: z["name"] for z in st.get("zones", [])}
    zona_id = (inc or {}).get("zone") or _zona(str(body.get("zona") or ""), names)
    opciones: list[dict[str, Any]] = []

    def add(kind: str, texto: str, *, persona: bool = False, coste: str = "bajo",
            tiempo: str = "minutos", riesgo: str = "bajo", requisitos: str = "", extra: dict | None = None):
        row = {"id": kind if not extra else f"{kind}:{extra.get('recurso') or extra.get('hacia') or len(opciones)}",
               "kind": kind, "texto": texto, "exige_persona": persona, "coste": coste,
               "tiempo": tiempo, "riesgo": riesgo, "requisitos": requisitos or "ninguno"}
        if extra:
            row.update(extra)
        opciones.append(row)

    obs = session.world.observe()
    assigned = set((inc or {}).get("assigned") or [])
    dest = zona_id
    for r in obs.resources.values():
        if str(r.status) != "available" or r.id in assigned:
            continue
        eta = session.world.travel_time(r.zone, dest, r.id) if dest else None
        add("dispatch", f"Despachar {r.name} a {dest or 'la zona'}", coste="medio",
            tiempo=f"{eta} min" if eta is not None else "ETA desconocida",
            requisitos=f"{r.id} libre", extra={"recurso": r.id, "eta_min": eta, "zona": dest})
        if len([o for o in opciones if o["kind"] == "dispatch"]) >= 3:
            break
    otros = [i for i in st.get("incidents") or []
             if i.get("id") != iid and i.get("status") not in ("resolved", "false_alarm", "failed")
             and i.get("assigned") and not i.get("reserved")]
    if otros:
        donor = otros[0]
        rid = (donor.get("assigned") or [None])[0]
        add("recall", f"Reasignar {rid} desde {donor.get('id')} (ese incidente espera)",
            coste="alto", riesgo="medio", requisitos="otro incidente con recurso",
            extra={"recurso": rid, "retirado_de": donor.get("id"), "deja_esperando": donor.get("id")})
    add("split", "Dividir un recurso (uno se queda, otro atiende)", coste="alto",
        riesgo="medio", requisitos="recurso ya asignado con margen")
    add("preposition", f"Preposicionar un equipo cerca de {dest or 'la zona'}", coste="bajo",
        tiempo="minutos", requisitos="recurso libre")
    add("notify_staff", "Pedir apoyo al staff por Telegram (botones)", coste="bajo",
        requisitos="espejo Telegram o bot")
    add("voice", "Llamar por voz a un oficio de la lista blanca", coste="medio",
        requisitos="MANDO_ALLOWED_NUMBERS")
    add("ask", "Preguntar UNA cosa al informante", coste="bajo", tiempo="segundos",
        requisitos="canal abierto; no retrasa lo vital")
    add("zone_lead", "Avisar al jefe de zona", coste="bajo")
    add("broadcast", "Megafonía / difusión general", persona=True, coste="alto", riesgo="alto",
        requisitos="persona: mensaje público")
    add("reroute", "Desviar flujo entre puertas", coste="medio", riesgo="medio",
        requisitos="ensayar en el gemelo")
    add("set_zone", "Abrir o cerrar un acceso", persona=bool(zona_id), coste="alto", riesgo="alto",
        requisitos="cerrar con presión detrás exige persona")
    add("resupply", "Reponer suministros (agua, barreras)", coste="bajo")
    add("watch", "Vigilar sin actuar", coste="nulo", riesgo="si empeora, se pierde tiempo")
    add("escalate", "Escalar a una persona del centro", persona=True, coste="bajo")
    add("request_external", "Pedir ayuda externa (112 simulado)", persona=True, coste="máximo",
        riesgo="alto", requisitos="SIEMPRE persona")
    add("stop_show", "Parar el espectáculo", persona=True, coste="máximo", riesgo="alto",
        requisitos="SIEMPRE persona")
    add("evacuate", "Evacuar la zona", persona=True, coste="máximo", riesgo="alto",
        requisitos="SIEMPRE persona")
    # mínimo 6 cuando existan: el catálogo amplio ya las tiene
    return {
        "ok": True, "incident_id": iid or None, "zona": zona_id,
        "texto": f"{len(opciones)} opciones con los medios que quedan. Elige el agente.",
        "opciones": opciones, "n": len(opciones),
    }


def comparar_opciones(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    from . import cerebro_tools
    raw = body.get("opciones") or []
    if not isinstance(raw, list) or not 1 <= len(raw) <= 5:
        raise ValueError("hace falta «opciones»: entre 1 y 5")
    criterios = body.get("criterios") or (
        "vidas_en_riesgo", "tiempo_hasta_atencion", "densidad_max_prevista",
        "recursos_que_quedan", "reversibilidad")
    ensayos = None
    try:
        ensayos = cerebro_tools.ensayar(session, {"opciones": [
            o if isinstance(o, str) else (o.get("texto") or o.get("id") or "") for o in raw],
            "minutos": body.get("minutos") or 12})
    except ValueError:
        ensayos = None
    tabla = []
    for i, item in enumerate(raw):
        if isinstance(item, str):
            item = {"texto": item}
        nums = {}
        if ensayos and i < len(ensayos.get("opciones") or []):
            nums = (ensayos["opciones"][i] or {}).get("numeros") or {}
        pico = None
        if isinstance(nums, list) and nums:
            pico = max((n.get("pico") or 0) for n in nums if isinstance(n, dict))
        elif isinstance(nums, dict):
            pico = nums.get("pico")
        persona = bool(item.get("exige_persona")) or str(item.get("kind") or "") in (
            "evacuate", "stop_show", "request_external", "broadcast")
        eta = item.get("eta_min")
        row = {
            "opcion": item.get("texto") or item.get("id") or str(i),
            "kind": item.get("kind"),
            "vidas_en_riesgo": "alta" if persona or (pico or 0) >= 5 else ("media" if (pico or 0) >= 4 else "baja"),
            "tiempo_hasta_atencion": eta,
            "densidad_max_prevista": pico,
            "recursos_que_quedan": "reserva" if item.get("kind") in ("watch", "preposition") else "gasta",
            "reversibilidad": "baja" if persona or item.get("kind") in ("evacuate", "stop_show", "set_zone") else "alta",
            "exige_persona": persona,
        }
        tabla.append({k: row[k] for k in ["opcion", "kind", *criterios, "exige_persona"] if k in row or k == "opcion"})
    return {
        "ok": True, "texto": "Tabla comparativa. No elige: elige el agente.",
        "criterios": list(criterios), "tabla": tabla, "elige": "agente",
    }


def analizar_situacion(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    from .cerebro_tools import sync_agent
    from . import adaptativo
    sync_agent(session)
    st = session.state()
    closed = {"resolved", "false_alarm", "failed"}
    abiertos = [i for i in st.get("incidents") or [] if i.get("status") not in closed]
    vitales = [i for i in abiertos if i.get("life_threat") or (i.get("priority") or 0) >= 9]
    sin_zona = [i for i in abiertos if not i.get("zone")]
    criticos = [r for r in st.get("resources") or []
                if str(r.get("kind")) in ("medical", "ambulance", "security")]
    libres_c = [r for r in criticos if r.get("status") == "available"]
    planes_rotos = [p for p in st.get("plans") or [] if p.get("invalidated_by") or not p.get("live")]
    conflictos = []
    for box in (st.get("agentes") or {}).values():
        if isinstance(box, dict) and box.get("conflicto"):
            conflictos.extend(box["conflicto"] if isinstance(box["conflicto"], list) else [box["conflicto"]])
    obj = []
    iid = str(body.get("incidente") or body.get("incident_id") or "")
    if iid:
        obj = enjambre.objeciones_abiertas(session, iid, gravedad="alta")
    previs = st.get("forecasts") or []
    cerca = [p for p in previs if (p.get("eta_min") or p.get("cuenta_atras_min") or 99) <= 5]
    log = st.get("log") or []
    t = int(st.get("t") or 0)
    cambios = sum(1 for e in log[-20:] if int(e.get("t") or 0) >= t - 1)
    senales = {
        "riesgo_vital": bool(vitales),
        "riesgo_vital_multiple": len(vitales) >= 2,
        "varios_incidentes": len(abiertos) >= 2,
        "contradicciones": bool(conflictos or obj),
        "falta_ubicacion": bool(sin_zona),
        "recurso_critico_agotado": bool(criticos) and not libres_c,
        "plan_vigente_roto": bool(planes_rotos),
        "sistema_degradado": bool(getattr(session, "_cerebro_degradado", False)),
        "volatil": cambios >= 3 or bool(cerca),
        "n_abiertos": len(abiertos), "n_vitales": len(vitales), "cambios_por_minuto": cambios,
    }
    modo = adaptativo.elegir_modo(senales)
    adaptativo.aplicar_modo(session, modo, senales)
    return {
        "ok": True, "texto": f"señales → modo {modo['id']}. El coordinador elige rama.",
        "senales": senales, "modo": modo,
        "rama": "la elige el agente coordinador y la publica en la pizarra con su porqué",
    }


def resultado(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    ag = str(body.get("agente") or "").strip()
    if not ag:
        raise ValueError("hace falta el agente")
    fam = str(body.get("familia") or body.get("tipo") or "todas")
    out = confianza.aplicar(session, ag, fam, body.get("resultado") if "resultado" in body else body.get("acierto"))
    if body.get("cambio_decision"):
        from . import adaptativo
        adaptativo.registrar_aporte(session, ag, fam, cambio=True)
    return {"ok": True, "texto": f"{ag}/{fam}: N={out['n']} {out['etiqueta']}", **out}
