"""Sistema agéntico adaptativo: modo, autonomía, ritmo, activación y prompts versionados."""
from __future__ import annotations

import secrets
from typing import Any

from . import confianza, enjambre, equipo, privacy

UMBRALES = confianza.autonomia  # reexporta el cálculo


def elegir_modo(senales: dict[str, Any]) -> dict[str, Any]:
    if senales.get("riesgo_vital_multiple") or (
            senales.get("recurso_critico_agotado") and senales.get("riesgo_vital")):
        modo, porque = "crisis", "recurso crítico agotado o riesgo vital múltiple: reasignar, escalar antes, avisar más arriba"
    elif senales.get("recurso_critico_agotado") or (senales.get("riesgo_vital") and senales.get("varios_incidentes")):
        modo, porque = "crisis", "medios críticos o vital concurrente: reasignar y escalar antes"
    elif senales.get("varios_incidentes"):
        modo, porque = "carga", "varios incidentes a la vez: priorizar y reservar"
    else:
        modo, porque = "calma", "un incidente y medios de sobra: resolver bien y ahorrar recursos"
    return {"id": modo, "porque": porque}


def aplicar_modo(session: Any, modo: dict[str, Any], senales: dict[str, Any] | None = None) -> dict[str, Any]:
    out = enjambre.marcar_modo(session, modo["id"], modo["porque"])
    session._enjambre_volatil = bool((senales or {}).get("volatil"))
    return out


def ritmo_vigia(session: Any) -> dict[str, Any]:
    modo = (_box(session).get("modo") or "calma")
    volatil = bool(getattr(session, "_enjambre_volatil", False))
    base = {"calma": 5, "carga": 2, "crisis": 1}.get(modo, 5)
    if volatil:
        base = max(1, base - 2) if modo != "crisis" else 1
    return {
        "modo": modo, "cada_min": base, "volatil": volatil,
        "texto": f"el vigía reevalúa cada {base} min ({'volátil' if volatil else modo})",
    }


def especialistas_activos(session: Any, *, familia: str = "", modo: str | None = None) -> dict[str, Any]:
    modo = modo or (_box(session).get("modo") or "calma")
    todos = [a for a in equipo.AGENTES if a != "equipo"]
    if modo == "crisis":
        return {"modo": modo, "activar": todos, "saltar": [],
                "porque": "en crisis se activan todos los especialistas"}
    saltar = []
    activar = []
    led = getattr(session, "ledger", None)
    fam = familia or "todas"
    for name in todos:
        if name in ("triaje", "critico", "vigia"):
            activar.append(name)
            continue
        n, cambios = (0, 0)
        if led is not None:
            n, cambios = led.aporte_get(name, fam)
        if modo == "calma" and n >= confianza.N_MIN and cambios == 0:
            saltar.append({"agente": name, "n": n, "cambios": cambios})
        else:
            activar.append(name)
    return {
        "modo": modo, "activar": activar, "saltar": saltar,
        "porque": ("en calma se saltan especialistas que nunca cambian la decisión (N≥3, 0 cambios)"
                   if saltar else "aún no hay evidencia para saltar a nadie"),
    }


def registrar_aporte(session: Any, agente: str, familia: str, *, cambio: bool) -> None:
    led = getattr(session, "ledger", None)
    fam = familia or "todas"
    n, cambios = (0, 0)
    if led is not None:
        n, cambios = led.aporte_get(agente, fam)
        led.aporte_put(agente, fam, n + 1, cambios + (1 if cambio else 0))
    box = getattr(session, "_aporte", None)
    if box is None:
        session._aporte = {}
        box = session._aporte
    prev = box.get((agente, fam), (0, 0))
    box[(agente, fam)] = (prev[0] + 1, prev[1] + (1 if cambio else 0))


def autonomia_por_agente(session: Any, familia: str = "") -> list[dict[str, Any]]:
    return [confianza.autonomia(session, ag, familia) for ag in equipo.AGENTES]


def exige_revision(session: Any, agente: str, familia: str = "") -> bool:
    return bool(confianza.autonomia(session, agente, familia)["exige_revision"])


def load_prompt(session: Any, agente: str, fallback: str) -> str:
    led = getattr(session, "ledger", None)
    if led is None:
        return fallback
    row = led.prompt_activo(agente)
    if row and row.get("estado") == "aprobada" and row.get("cuerpo"):
        return str(row["cuerpo"])
    return fallback


def proponer_prompt(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    from .cerebro_llm import load_agent_prompt
    agente = str(body.get("agente") or "").strip().lower()
    if agente not in equipo.AGENTES and agente != "aprendizaje":
        raise ValueError("agente desconocido")
    cuerpo = str(body.get("cuerpo") or body.get("prompt") or "")
    if not cuerpo or len(cuerpo) > 20000:
        raise ValueError("hace falta el cuerpo del prompt")
    actual = load_agent_prompt(agente)
    diff = str(body.get("diff") or _diff(actual, cuerpo))
    evidencia = body.get("evidencia") if isinstance(body.get("evidencia"), dict) else {}
    n = evidencia.get("n") or body.get("n") or 0
    if type(n) is bool or type(n) not in (int, float) or n < 1:
        raise ValueError("una propuesta de prompt lleva evidencia N ≥ 1")
    pid = str(body.get("id") or f"PV-{secrets.token_hex(3)}")
    led = getattr(session, "ledger", None)
    if led is None:
        return {"ok": False, "texto": "ledger no disponible"}
    out = led.prompt_proponer(pid, agente, cuerpo, diff=diff[:4000], evidencia=evidencia, n=int(n))
    out["texto"] = "propuesta registrada; una persona tiene que aprobarla"
    return out


def decidir_prompt(session: Any, body: dict[str, Any], *, by: str = "") -> dict[str, Any]:
    led = getattr(session, "ledger", None)
    if led is None:
        return {"ok": False, "texto": "ledger no disponible"}
    accion = str(body.get("accion") or "").strip().lower()
    if accion == "revertir":
        ag = str(body.get("agente") or "")
        out = led.prompt_revertir(ag, by=by)
        if out is None:
            raise ValueError("no hay versión activa que revertir")
        return out
    pid = str(body.get("id") or "")
    if not pid:
        raise ValueError("hace falta el id de la versión")
    if accion == "aprobar":
        out = led.prompt_decidir(pid, aprobar=True, by=by, activar=True)
    elif accion == "rechazar":
        out = led.prompt_decidir(pid, aprobar=False, by=by, activar=False)
    else:
        raise ValueError("accion: aprobar, rechazar o revertir")
    if out is None:
        raise ValueError("esa versión no existe")
    return out


def comparar_prompts(session: Any, body: dict[str, Any]) -> dict[str, Any]:
    """Compara dos versiones en los mismos escenarios (demo de motor/evals si existe)."""
    agente = str(body.get("agente") or "")
    led = getattr(session, "ledger", None)
    versiones = led.prompt_listar(agente) if led is not None else []
    escenarios: list[str] = []
    n = 0
    try:
        from motor.evals.common import load_demo
        demo = load_demo()[:5]
        escenarios = [str(c.get("id") or i) for i, c in enumerate(demo)]
        n = len(escenarios)
    except Exception:
        escenarios, n = ["ctx-vital", "ctx-crowd"], 2
    return {
        "ok": True, "agente": agente, "n": n, "escenarios": escenarios,
        "versiones": versiones, "texto": f"mismos {n} escenarios; N declarado. No se usa versión no aprobada.",
        "fuente": "motor/evals (demo.jsonl) si existe",
    }


def snapshot(session: Any) -> dict[str, Any]:
    box = _box(session)
    modo = {"id": box.get("modo") or "calma", "porque": box.get("modo_porque") or ""}
    led = getattr(session, "ledger", None)
    hist = box.get("modo_historial") or []
    if led is not None and not hist:
        hist = led.adaptacion_list(clase="modo", limit=20)
    act = especialistas_activos(session)
    return privacy.scrub({
        "ok": True,
        "modo": modo,
        "historial_modo": hist[-20:],
        "autonomia": autonomia_por_agente(session),
        "umbrales": {"n_min": confianza.N_MIN, "alta": confianza.ALTA, "baja": confianza.BAJA},
        "ritmo_vigia": ritmo_vigia(session),
        "especialistas": act,
        "lecciones": (led.list_lecciones(estado="aprobada", limit=20) if led is not None else []),
        "prompts": (led.prompt_listar() if led is not None else []),
        "cadena": getattr(session, "_cerebro_cadena", None) or "plataforma",
        "degradado": bool(getattr(session, "_cerebro_degradado", False)),
        "etiqueta_degradado": "modo degradado: reglas" if getattr(session, "_cerebro_degradado", False) else None,
    })


def _box(session: Any) -> dict[str, Any]:
    return enjambre._box(session)


def _diff(old: str, new: str) -> str:
    old_l, new_l = old.splitlines(), new.splitlines()
    lines = []
    n = max(len(old_l), len(new_l))
    for i in range(min(n, 80)):
        a = old_l[i] if i < len(old_l) else ""
        b = new_l[i] if i < len(new_l) else ""
        if a != b:
            if a:
                lines.append(f"- {a[:160]}")
            if b:
                lines.append(f"+ {b[:160]}")
    return "\n".join(lines) or "(sin diferencias de línea)"
