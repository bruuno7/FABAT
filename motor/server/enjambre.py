"""Pizarra del enjambre: mensajes entre agentes, revisión entre pares, vista pública."""
from __future__ import annotations

import os
import secrets
import time
from typing import Any

from . import confianza, equipo, privacy

TIPOS = ("observacion", "propuesta", "decision", "revision", "objecion",
         "correccion", "pregunta", "respuesta")
GRAVEDADES = ("alta", "media", "baja")
REVISIONES = ("revision", "objecion", "correccion")
AGENTES_PIZARRA = equipo.AGENTES + ("aprendizaje", "todos")


def timeout_objecion_s() -> float:
    try:
        return max(0.0, float(os.environ.get("MANDO_ENJAMBRE_OBJECION_S") or "45"))
    except (TypeError, ValueError):
        return 45.0


def parse_tipo(raw: Any) -> str:
    name = str(raw or "").strip().lower()
    if name not in TIPOS:
        raise ValueError("tipo: observacion|propuesta|decision|revision|objecion|correccion|pregunta|respuesta")
    return name


def parse_de(raw: Any) -> str:
    name = str(raw or "").strip().lower()
    if name not in AGENTES_PIZARRA or name == "todos":
        raise ValueError("de debe ser un agente del equipo")
    return name


def parse_para(raw: Any) -> str:
    name = str(raw or "todos").strip().lower() or "todos"
    if name not in AGENTES_PIZARRA:
        raise ValueError("para debe ser un agente o «todos»")
    return name


def _box(session: Any) -> dict[str, Any]:
    box = getattr(session, "_enjambre", None)
    if box is None:
        session._enjambre = {"mensajes": [], "modo": None, "modo_porque": "", "modo_historial": []}
        box = session._enjambre
    return box


def _reservados(session: Any) -> set[str]:
    try:
        st = session.state()
    except Exception:
        return set()
    return {str(i.get("id")) for i in (st.get("incidents") or []) if i.get("reserved")}


def publicar(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    de = parse_de(body.get("de") or body.get("agente"))
    para = parse_para(body.get("para"))
    tipo = parse_tipo(body.get("tipo"))
    texto = str(body.get("texto") or "").strip()
    if not texto or len(texto) > 400:
        raise ValueError("hace falta «texto» de como mucho 400 caracteres")
    incidente = str(body.get("incidente") or body.get("incident_id") or "").strip()[:40]
    enlaza = str(body.get("enlaza") or body.get("sobre") or "").strip()[:40]
    if tipo in REVISIONES and not enlaza:
        raise ValueError("una revisión, objeción o corrección enlaza la propuesta de otro agente")
    grav = str(body.get("gravedad") or ("alta" if tipo == "objecion" else "")).strip().lower()
    if grav and grav not in GRAVEDADES:
        raise ValueError("gravedad: alta|media|baja")
    if tipo == "objecion" and not grav:
        grav = "alta"
    conf = body.get("confianza")
    if conf is not None:
        if type(conf) is bool or type(conf) not in (int, float) or not 0 <= float(conf) <= 1:
            raise ValueError("confianza debe ser un número entre 0 y 1")
        conf = float(conf)
    datos = body.get("datos") if isinstance(body.get("datos"), dict) else {}
    if incidente in _reservados(session):
        texto, datos = "(reservado)", {}
    mid = str(body.get("id") or f"P-{secrets.token_hex(3)}")
    ts = body.get("_ts")
    ts_unix = float(ts) if isinstance(ts, (int, float)) and type(ts) is not bool else time.time()
    msg = {
        "id": mid, "ts": ts_unix, "de": de, "para": para, "incidente": incidente or None,
        "tipo": tipo, "texto": texto, "datos": datos, "confianza": conf,
        "enlaza": enlaza or None, "gravedad": grav or None, "resuelta": False,
    }
    _box(session)["mensajes"].append(msg)
    led = getattr(session, "ledger", None)
    if led is not None:
        led.save_pizarra(mid, de=de, para=para, incidente=incidente, tipo=tipo, texto=texto,
                         datos=datos, confianza=conf, enlaza=enlaza, gravedad=grav,
                         session_id=getattr(session, "session_id", ""), ts_unix=ts_unix)
    return {"ok": True, "id": mid, "texto": f"{tipo} de {de} para {para}", **msg}


def leer(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    agente = str(body.get("agente") or body.get("para") or "").strip().lower()
    if agente and agente not in AGENTES_PIZARRA:
        raise ValueError("agente desconocido")
    incidente = str(body.get("incidente") or body.get("incident_id") or "").strip()
    n = body.get("n") or body.get("limit") or 12
    if type(n) is bool or type(n) not in (int, float):
        n = 12
    n = max(1, min(50, int(n)))
    hidden = _reservados(session)
    led = getattr(session, "ledger", None)
    rows = []
    if led is not None:
        rows = led.leer_pizarra(incidente=incidente, para=agente, limit=80)
    if not rows:
        rows = list(_box(session)["mensajes"])
        if incidente:
            rows = [m for m in rows if not m.get("incidente") or m.get("incidente") == incidente]
        rows = sorted(rows, key=lambda m: -float(m.get("ts") or 0))
    out = []
    for m in rows:
        if m.get("incidente") in hidden:
            continue
        dest = str(m.get("para") or "").lower()
        if agente and agente != "todos" and dest not in (agente, "todos", ""):
            # lo dirigido a él primero, pero también ve propuestas del incidente
            if m.get("tipo") not in ("propuesta", "decision", "observacion", "revision",
                                     "objecion", "correccion", "pregunta", "respuesta"):
                continue
        out.append(privacy.scrub(dict(m)))
    if agente and agente != "todos":
        def _rank(m: dict[str, Any]) -> int:
            dest = str(m.get("para") or "").lower()
            if dest == agente:
                return 0
            if dest in ("todos", ""):
                return 1
            return 2
        out.sort(key=lambda m: (_rank(m), -float(m.get("ts") or 0)))
    lecciones = []
    if led is not None and agente:
        lecciones = led.list_lecciones(estado="aprobada", para_agente=agente, limit=8)
    elif led is not None:
        lecciones = [x for x in led.list_lecciones(estado="aprobada", limit=8)
                     if not x.get("para_agente")]
    return {
        "ok": True, "texto": f"{min(n, len(out))} mensajes para {agente or 'todos'}",
        "mensajes": out[:n], "lecciones": lecciones,
        "confianza": confianza.de(session, agente or "equipo") if agente else None,
    }


def objeciones_abiertas(session: Any, incidente: str, *, gravedad: str = "alta") -> list[dict[str, Any]]:
    led = getattr(session, "ledger", None)
    rows = led.leer_pizarra(incidente=incidente, limit=80) if led is not None else list(_box(session)["mensajes"])
    now = time.time()
    to = timeout_objecion_s()
    out = []
    for m in rows:
        if m.get("tipo") != "objecion":
            continue
        if m.get("resuelta"):
            continue
        if incidente and m.get("incidente") not in (None, "", incidente):
            continue
        grav = str(m.get("gravedad") or "media")
        if gravedad and grav != gravedad:
            continue
        age = now - float(m.get("ts") or now)
        out.append(dict(m, edad_s=round(age, 1), vence=(age >= to)))
    return out


def resolver(session: Any, mid: str) -> None:
    for m in _box(session)["mensajes"]:
        if m.get("id") == mid:
            m["resuelta"] = True
    led = getattr(session, "ledger", None)
    if led is not None:
        led.resolver_pizarra(mid)


def gate_decidir(session: Any, d: dict[str, Any], *, vital: bool) -> dict[str, Any] | None:
    """Si hay objeciones altas abiertas, no ejecuta (salvo lo vital). Escala si vencen."""
    iid = str(d.get("incident_id") or "")
    if not iid or iid.lower() == "nuevo":
        return None
    altas = objeciones_abiertas(session, iid, gravedad="alta")
    if not altas:
        return None
    if vital:
        return None
    vencidas = [o for o in altas if o.get("vence")]
    lista = [{"id": o.get("id"), "de": o.get("de"), "texto": o.get("texto"),
              "sobre": o.get("enlaza"), "edad_s": o.get("edad_s")} for o in altas]
    if vencidas:
        return {
            "ok": False, "texto": "resolver primero; objeciones altas sin resolver: se escala a una persona",
            "resolver_primero": True, "escalada": True, "objeciones": lista,
            "aceptadas": [], "bloqueadas": [], "requiere_persona": True,
        }
    return {
        "ok": False, "texto": "resolver primero",
        "resolver_primero": True, "escalada": False, "objeciones": lista,
        "aceptadas": [], "bloqueadas": [],
    }


def aristas(mensajes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str], int] = {}
    for m in mensajes:
        de, para = str(m.get("de") or ""), str(m.get("para") or "todos")
        if not de:
            continue
        counts[(de, para)] = counts.get((de, para), 0) + 1
    return [{"de": a, "para": b, "n": n} for (a, b), n in sorted(counts.items())]


def public_view(session: Any, state: dict[str, Any]) -> dict[str, Any]:
    hidden = {i["id"] for i in (state.get("incidents") or []) if i.get("reserved")}
    led = getattr(session, "ledger", None)
    msgs = led.leer_pizarra(limit=80) if led is not None else list(_box(session)["mensajes"])
    msgs = [m for m in msgs if m.get("incidente") not in hidden]
    msgs = sorted(msgs, key=lambda m: float(m.get("ts") or 0))
    msgs = privacy.scrub(msgs[-50:])
    confs = {row["agente"]: row for row in confianza.resumen(session)}
    last: dict[str, dict[str, Any]] = {}
    for m in msgs:
        last[str(m.get("de") or "")] = m
    agentes = []
    lecciones_por = {}
    if led is not None:
        for ag in equipo.AGENTES:
            lecciones_por[ag] = [x["id"] for x in led.list_lecciones(estado="aprobada", para_agente=ag, limit=8)]
    box = _box(session)
    for ag in equipo.AGENTES:
        row = confs.get(ag) or confianza.fila(ag, "todas")
        ult = last.get(ag) or {}
        agentes.append({
            "id": ag, "estado": "activo" if ult else "en_espera",
            "ultimo_mensaje": ult.get("texto") if ult else None,
            "confianza": row.get("puntuacion"), "n": row.get("n"),
            "tendencia": row.get("tendencia") or "estable",
            "etiqueta": row.get("etiqueta"),
            "lecciones_activas": lecciones_por.get(ag) or [],
        })
    modo = box.get("modo") or "calma"
    return {
        "modo": {"id": modo, "porque": box.get("modo_porque") or ""},
        "agentes": agentes,
        "mensajes": msgs[-50:],
        "aristas": aristas(msgs),
        "cadena": getattr(session, "_cerebro_cadena", None) or "plataforma",
        "degradado": bool(getattr(session, "_cerebro_degradado", False)),
    }


def marcar_modo(session: Any, modo: str, porque: str) -> dict[str, Any]:
    box = _box(session)
    prev = box.get("modo")
    box["modo"] = modo
    box["modo_porque"] = porque
    if prev != modo:
        box["modo_historial"].append({"modo": modo, "porque": porque, "ts": time.time(), "t": getattr(session.world, "t", 0)})
        led = getattr(session, "ledger", None)
        if led is not None:
            led.adaptacion_append(f"modo-{secrets.token_hex(3)}", clase="modo", valor=modo,
                                  porque=porque, session_id=getattr(session, "session_id", ""))
        try:
            publicar(session, {"de": "vigia", "para": "todos", "tipo": "observacion",
                               "texto": f"modo {modo}: {porque}", "datos": {"modo": modo}})
        except ValueError:
            pass
    return {"modo": modo, "porque": porque, "cambio": prev != modo}


def revisar_dependencias(session: Any, votos: dict[str, dict[str, Any]], incidente: str) -> None:
    """Cada especialista revisa al que depende de él. El crítico revisa el plan."""
    pares = (("recursos", "prioridad"), ("avisos", "recursos"), ("vigia", "equipo"), ("critico", "equipo"))
    ids = {}
    for name, vote in votos.items():
        out = publicar(session, {
            "de": name, "para": "todos", "tipo": "propuesta", "incidente": incidente,
            "texto": str(vote.get("porque") or "")[:400] or f"propuesta de {name}",
            "datos": {"prioridad": vote.get("prioridad"), "recursos": vote.get("recursos"),
                      "acciones": vote.get("acciones")},
            "confianza": vote.get("confianza"),
        })
        ids[name] = out["id"]
    for revisor, objetivo in pares:
        if revisor not in votos or objetivo not in ids:
            continue
        publicar(session, {
            "de": revisor, "para": objetivo, "tipo": "revision", "incidente": incidente,
            "enlaza": ids[objetivo],
            "texto": f"{revisor} revisa a {objetivo}: {str(votos[revisor].get('porque') or 'sin objeción')[:200]}",
            "confianza": votos[revisor].get("confianza"), "gravedad": "baja",
        })
    crit = votos.get("critico") or {}
    veredicto = str(crit.get("veredicto") or "").upper()
    if veredicto in ("CORREGIR", "ESCALAR A PERSONA") or crit.get("correcciones"):
        publicar(session, {
            "de": "critico", "para": "recursos", "tipo": "correccion" if veredicto == "CORREGIR" else "objecion",
            "incidente": incidente, "enlaza": ids.get("recursos") or ids.get("prioridad") or "",
            "texto": str(crit.get("porque") or veredicto or "el crítico objeta")[:400],
            "gravedad": "alta" if veredicto != "CORREGIR" else "media",
        })
