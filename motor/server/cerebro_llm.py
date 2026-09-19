"""Cerebro local: el EQUIPO de agentes (mismos papeles que HappyRobot) sin la plataforma.

Usa el cliente de `llm_parser_factory` (Helmcode / Cloudflare, `MANDO_LLM=1`) o un cerebro
falso determinista para tests. Prompts: `motor/happyrobot/equipo/*.md`.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from . import cerebro_tools, llm_parser_factory
from . import equipo
from . import adaptativo, enjambre
from .cerebro import ORIGEN_AGENTE, ORIGEN_LLM_LOCAL

PROMPT_PATH = Path(__file__).resolve().parent.parent / "happyrobot" / "cerebro" / "PROMPT-CEREBRO.md"
EQUIPO_DIR = Path(__file__).resolve().parent.parent / "happyrobot" / "equipo"
_PARALELO = ("prioridad", "recursos", "avisos", "vigia")


def load_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return "Eres el cerebro de MANDO. Devuelve solo JSON de decisión válido."


def load_agent_prompt(agente: str, session: Any = None) -> str:
    path = EQUIPO_DIR / f"{agente}.md"
    try:
        fallback = path.read_text(encoding="utf-8")
    except OSError:
        fallback = load_prompt()
    if session is not None:
        return adaptativo.load_prompt(session, agente, fallback)
    return fallback


def parse_decision_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("el modelo no devolvió JSON")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("el JSON no es un objeto")
    if isinstance(data.get("decision"), dict) and not (data.get("porque") or data.get("why") or data.get("razonamiento")):
        data = dict(data["decision"])
    if not (data.get("porque") or data.get("why")):
        data["porque"] = data.get("razonamiento") or data.get("recomendacion") or ""
    return cerebro_tools.validate_decision(data)


def _plain(text: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _aviso_blob(ctx: dict[str, Any]) -> str:
    av = ctx.get("aviso") or {}
    return _plain(" ".join(str(x or "") for x in (
        av.get("texto"), av.get("tipo"), av.get("zona"),
        json.dumps(ctx.get("incidentes") or [], ensure_ascii=False),
    )))


def _lecciones_blob(ctx: dict[str, Any]) -> str:
    rows = ((ctx.get("memoria") or {}).get("lecciones_aprobadas") or [])
    return _plain(" ".join(str(r.get("texto") or "") for r in rows if isinstance(r, dict)))


def _mas_cercano(ctx: dict[str, Any], kinds: tuple[str, ...]) -> str | None:
    best, best_eta = None, 10 ** 9
    for kind in kinds:
        for row in (ctx.get("recursos_libres") or {}).get(kind) or []:
            if not isinstance(row, dict) or not row.get("id"):
                continue
            eta = row.get("eta_min")
            eta_f = 99.0 if eta is None else float(eta)
            if eta_f < best_eta:
                best, best_eta = str(row["id"]), eta_f
    return best


def fake_brain(ctx: dict[str, Any]) -> dict[str, Any]:
    """Determinista: riesgo vital → primer médico libre; si no, no mueve recursos graves."""
    joint, _ = equipo.compose(list(fake_team(ctx).values()))
    joint.setdefault("avisar", [])
    joint.setdefault("requiere_persona", False)
    return joint


def fake_team(ctx: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Un voto por papel. Determinista; aplica lecciones APROBADAS del contexto."""
    av = ctx.get("aviso") or {}
    blob = _aviso_blob(ctx)
    lessons = _lecciones_blob(ctx)
    tipo = str(av.get("tipo") or "")
    zona = av.get("zona")
    texto = str(av.get("texto") or "")[:400]
    abiertos = list(ctx.get("incidentes") or [])
    vital = any(i.get("vital") for i in abiertos) or any(
        w in blob for w in ("no respira", "parada", "cardiac", "rcp", "cpr", "anafil", "wont wake", "not breathing")
    )
    fuego = tipo == "small_fire" or any(w in blob for w in ("incendio", "llamas", "humo", "fuego", "huele a gas"))
    silencio = any(w in blob for w in ("no contesta", "silencio", "60 segundo"))
    rumor = "rumor" in blob or "bulo" in blob
    grave_txt = any(w in blob for w in ("evacuar", "desaloj", "parar el", "ayuda externa"))
    iid = (next((i for i in abiertos if i.get("vital")), abiertos[0]) if abiertos else {}).get("id") or "nuevo"

    recs: list[str] = []
    prio = 4.0
    rp = bool(grave_txt and not vital)
    acciones: list[dict[str, Any]] = []
    avisar: list[dict[str, Any]] = []
    porque = "Recomiendo vigilar: no hay rama vital. Alternativa: mover medios sin hecho."

    if vital:
        prio = 10
        rid = _mas_cercano(ctx, ("medical", "ambulance"))
        recs = [rid] if rid else []
        porque = ("Recomiendo despachar el médico más cercano ya: riesgo vital. "
                  "Alternativa: esperar más datos; inaceptable.")
        avisar = [{"rol": "sanitario", "canal": "voz", "mensaje": "Acude; riesgo vital."}]
    elif fuego:
        prio = 8
        tech, sec = _mas_cercano(ctx, ("tech",)), _mas_cercano(ctx, ("security",))
        recs = [tech] if tech else []
        porque = ("Recomiendo mandar técnico al fuego. "
                  "Alternativa: evacuar sin persona; no.")
        if "seguridad" in lessons and ("tecnico" in lessons or "tecnico" in lessons):
            recs = [x for x in (tech, sec) if x]
            porque = ("Recomiendo técnico y seguridad a la vez: incendio en restauración. "
                      "Alternativa: solo técnico; deja el perímetro vacío.")
        avisar = [{"rol": "jefe_zona", "canal": "telegram", "mensaje": "Fuego; perímetro y técnico."}]
        rp = True
    elif silencio:
        prio = 6
        if "60" in lessons and "reasign" in lessons:
            rid = _mas_cercano(ctx, ("security", "medical", "volunteer"))
            recs = [rid] if rid else []
            porque = ("Recomiendo reasignar ya: el staff no contesta en 60 s. "
                      "Alternativa: seguir esperando; pierde el minuto.")
        else:
            recs = []
            porque = ("Recomiendo esperar al equipo que no contesta. "
                      "Alternativa: reasignar a otro libre.")
    else:
        kinds: tuple[str, ...] = ()
        if any(w in blob for w in ("pelea", "acoso", "mochila", "puerta", "densidad", "avalancha", "aplast", "grada")):
            kinds, prio = ("security",), 7
        elif any(w in blob for w in ("desmay", "mare", "vomit", "alergi", "intoxic", "tobillo", "heat")):
            kinds, prio = ("medical",), 6
        elif any(w in blob for w in ("luz", "apag", "valla", "gas", "estructura", "viento")):
            kinds, prio = ("tech", "security"), 7
        elif any(w in blob for w in ("agua", "cisterna")):
            kinds, prio = ("logistics", "volunteer"), 7
        elif any(w in blob for w in ("nin", "menor", "child", "nina")):
            kinds, prio = ("security", "volunteer"), 7
        for k in kinds:
            rid = _mas_cercano(ctx, (k,))
            if rid and rid not in recs:
                recs.append(rid)
        porque = (f"Recomiendo {', '.join(recs) or 'no despachar urgente'} según gravedad y medios que quedan. "
                  "Alternativa: invertir el orden de la cola.")
        if rumor:
            rp = True
            porque = ("Recomiendo no evacuar: es un rumor, no un hecho. "
                      "Alternativa: desalojar el recinto; irreversible sin persona.")

    rec_txt = ", ".join(recs) if recs else "nadie"
    base = {
        "incident_id": iid, "zona": zona, "tipo": tipo, "texto": texto,
        "confianza": 0.8 if vital else 0.55, "supuestos": ["El recinto sigue como en el contexto."],
    }
    return {
        "triaje": {**base, "agente": "triaje", "fusionar_con": None,
                   "porque": ("Recomiendo tratarlo como aviso nuevo: no hay ID de duplicado. "
                              "Alternativa: fusionar a ciegas.")[:400],
                   "confianza": 0.7},
        "prioridad": {**base, "agente": "prioridad", "prioridad": prio,
                      "porque": porque[:400],
                      "vigilar": ["rechazo o silencio del equipo", "un segundo incidente más grave"]},
        "recursos": {**base, "agente": "recursos", "recursos": recs,
                     "porque": (f"Recomiendo {rec_txt} (más cercano de lo que queda). "
                                "Alternativa: el siguiente del mismo tipo.")[:400],
                     "confianza": 0.75 if recs else 0.45},
        "avisos": {**base, "agente": "avisos", "avisar": avisar,
                   "porque": ("Recomiendo avisar a quien actúa y dejar esperando lo leve. "
                              "Alternativa: megafonía general.")[:400]},
        "vigia": {**base, "agente": "vigia",
                  "supuestos": ["El equipo acepta en 3 min", "La zona sigue accesible"],
                  "vigilar": ["llegada del equipo", "silencio >60 s", "segundo incidente grave"],
                  "porque": (f"Recomiendo tirar el plan si rechazan, no contestan en 60 s o entra algo más grave en {zona or 'la zona'}. "
                             f"Pizarra {len(ctx.get('pizarra') or [])} msgs. Alternativa: seguir el plan ciego.")[:400]},
        "critico": {**base, "agente": "critico", "requiere_persona": rp, "acciones": acciones,
                    "porque": ("Recomiendo tarjeta de persona para lo irreversible; lo vital ya va. "
                               "Alternativa: ejecutar evacuar/parar/ayuda externa a solas.")[:400],
                    "confianza": 0.8},
    }


def _un_agente(agente: str, ctx: dict[str, Any], client: Callable[[str], str] | None,
               fake: bool, session: Any = None) -> tuple[str, dict[str, Any], bool]:
    if fake or client is None:
        return agente, fake_team(ctx)[agente], False
    lecciones = ((ctx.get("memoria") or {}).get("lecciones_aprobadas") or [])
    prompt = (load_agent_prompt(agente, session) + "\n\n# CONTEXTO (JSON)\n"
              + json.dumps(ctx, ensure_ascii=False, default=str)[:5000]
              + "\n\n# LECCIONES APROBADAS (obligatorias si aplican)\n"
              + json.dumps(lecciones, ensure_ascii=False, default=str)[:1500]
              + "\n\n# PIZARRA\n" + json.dumps(ctx.get("pizarra") or [], ensure_ascii=False)[:1500]
              + "\n\nDevuelve SOLO el JSON de tu voto, con \"agente\":\"" + agente
              + "\" y un «porque» que sea la recomendación al operador (qué, porqué, alternativa).")
    last = None
    for _ in range(2):
        raw = client(prompt if last is None else prompt + "\nEl JSON anterior no validó: " + str(last)[:200]
                     + "\nCorrígelo. Solo JSON.")
        try:
            data = parse_decision_json(raw)
            data["agente"] = agente
            return agente, data, False
        except (ValueError, json.JSONDecodeError, KeyError) as exc:
            last = exc
    vote = fake_team(ctx)[agente]
    vote["_fallback"] = True
    return agente, vote, True


def razonar_equipo(ctx: dict[str, Any], *, client: Callable[[str], str] | None = None,
                   fake: bool = False, session: Any = None,
                   solo: list[str] | None = None) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Triaje primero; el resto en paralelo; el crítico al final. El vigía solo relanza afectados."""
    fake = fake or client is None
    votes: dict[str, dict[str, Any]] = {}
    fallbacks: list[str] = []
    paralelos = list(_PARALELO)
    if session is not None and solo is None:
        act = adaptativo.especialistas_activos(
            session, familia=str((ctx.get("aviso") or {}).get("tipo") or ""))
        permitidos = set(act.get("activar") or [])
        paralelos = [n for n in paralelos if n in permitidos]
    if solo is not None:
        names = [n for n in solo if n != "critico"]
        if "triaje" in names:
            _, votes["triaje"], fb = _un_agente("triaje", ctx, client, fake, session)
            if fb:
                fallbacks.append("triaje")
            names = [n for n in names if n != "triaje"]
        ctx_rest = dict(ctx, voto_triaje=votes.get("triaje"))
        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = [pool.submit(_un_agente, name, ctx_rest, client, fake, session) for name in names]
            for fut in as_completed(futs):
                name, vote, fb = fut.result()
                votes[name] = vote
                if fb:
                    fallbacks.append(name)
        if "critico" in (solo or []):
            _, votes["critico"], fb = _un_agente("critico", dict(ctx_rest, votos_previos=dict(votes)),
                                                 client, fake, session)
            if fb:
                fallbacks.append("critico")
        return votes, fallbacks
    _, votes["triaje"], fb = _un_agente("triaje", ctx, client, fake, session)
    if fb:
        fallbacks.append("triaje")
    ctx_rest = dict(ctx, voto_triaje=votes["triaje"])
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(_un_agente, name, ctx_rest, client, fake, session) for name in paralelos]
        for fut in as_completed(futs):
            name, vote, fb = fut.result()
            votes[name] = vote
            if fb:
                fallbacks.append(name)
    _, votes["critico"], fb = _un_agente("critico", dict(ctx_rest, votos_previos=dict(votes)),
                                         client, fake, session)
    if fb:
        fallbacks.append("critico")
    return votes, fallbacks


def razonar(ctx: dict[str, Any], *, client: Callable[[str], str] | None = None,
            fake: bool = False) -> dict[str, Any]:
    if fake or client is None:
        joint, _ = equipo.compose(list(fake_team(ctx).values()))
        return cerebro_tools.validate_decision(joint)
    prompt = (load_prompt() + "\n\n# CONTEXTO (JSON)\n" + json.dumps(ctx, ensure_ascii=False, default=str)[:6000]
              + "\n\nDevuelve SOLO el JSON de decisión.")
    last = None
    for _ in range(2):
        raw = client(prompt if last is None else prompt + "\nEl JSON anterior no validó: " + str(last)[:200]
                     + "\nCorrígelo. Solo JSON.")
        try:
            return parse_decision_json(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            last = exc
    raise ValueError(f"JSON de decisión inválido tras reintento: {last}")


def cycle(session: Any, aviso: dict[str, Any] | None = None, *, client: Callable[[str], str] | None = None,
          fake: bool = False) -> dict[str, Any]:
    t0 = time.monotonic()
    ctx = cerebro_tools.contexto(session, aviso or {})
    if aviso:
        ctx = dict(ctx)
        av = dict(ctx.get("aviso") or {})
        av["texto"] = str(aviso.get("texto") or "")[:400]
        if aviso.get("tipo") and not av.get("tipo"):
            av["tipo"] = aviso.get("tipo")
        ctx["aviso"] = av
    try:
        piz = enjambre.leer(session, {
            "agente": str((aviso or {}).get("agente") or "prioridad"),
            "incidente": str((aviso or {}).get("incident_id") or ""),
        })
        ctx.setdefault("pizarra", piz.get("mensajes") or [])
        ctx.setdefault("memoria", {})
        have = list(ctx["memoria"].get("lecciones_aprobadas") or [])
        seen = {x.get("id") for x in have if isinstance(x, dict)}
        for x in piz.get("lecciones") or []:
            if isinstance(x, dict) and x.get("id") not in seen:
                have.append(x)
        ctx["memoria"]["lecciones_aprobadas"] = have
    except ValueError:
        ctx.setdefault("pizarra", [])
    t_ctx = time.monotonic()
    fake = fake or client is None
    solo = None
    if str((aviso or {}).get("tipo") or "") == "cambio" or (aviso or {}).get("cambio"):
        afectados = cerebro_tools.cambio(session, aviso or {})
        ctx["cambio"] = afectados
        solo = ["vigia", "prioridad", "recursos", "avisos", "critico"]
        relanzar = []
        for row in afectados.get("afectados") or []:
            relanzar.extend(["prioridad", "recursos"])
        if relanzar:
            solo = ["vigia"] + list(dict.fromkeys(relanzar)) + ["critico"]
        else:
            solo = ["vigia"]
    votos, fallbacks = razonar_equipo(ctx, client=client, fake=fake, session=session, solo=solo)
    iid = str((aviso or {}).get("incident_id") or "")
    if not iid or iid.lower() == "nuevo":
        iid = str((ctx.get("incidentes") or [{}])[0].get("id") or "nuevo")
    try:
        enjambre.revisar_dependencias(session, votos, iid)
    except ValueError:
        pass
    from . import confianza as conf_mod
    pesos = conf_mod.pesos_para(session, list(votos.values()))
    decision, conflictos = equipo.compose(list(votos.values()), pesos=pesos)
    t_think = time.monotonic()
    if conflictos:
        out = {"ok": False, "conflicto": conflictos, "texto": "conflicto entre agentes; no se ejecuta",
               "aceptadas": [], "bloqueadas": []}
    else:
        out = cerebro_tools.decidir(session, dict(decision, agente="equipo"))
    t_end = time.monotonic()
    tiempos = {"contexto_s": round(t_ctx - t0, 3), "razonar_s": round(t_think - t_ctx, 3),
               "decidir_s": round(t_end - t_think, 3), "total_s": round(t_end - t0, 3)}
    visto = {
        "aviso": ctx.get("aviso"),
        "incidentes": ctx.get("incidentes"),
        "recursos_libres": {k: [x.get("id") for x in (v or []) if isinstance(x, dict)]
                            for k, v in (ctx.get("recursos_libres") or {}).items()},
        "lecciones_aprobadas": [
            x.get("id") or x.get("texto") for x in ((ctx.get("memoria") or {}).get("lecciones_aprobadas") or [])
        ],
    }
    episodios = []
    sid = str(getattr(session, "session_id", "") or "")[:8]
    for name, vote in votos.items():
        eid = f"ce-{sid}-{name}-{secrets_token()}"
        payload = {
            "id": eid, "agente": name,
            "tipo": (aviso or {}).get("tipo") or "",
            "zona": (aviso or {}).get("zona") or (ctx.get("aviso") or {}).get("zona"),
            "entrada": dict(aviso or {}, visto=visto),
            "contexto": {**{k: ctx[k] for k in ("incidentes", "recursos_libres", "previsiones", "memoria") if k in ctx},
                         "aviso": ctx.get("aviso"), "visto": visto},
            "razonamiento": vote.get("porque"),
            "decision": {k: v for k, v in vote.items() if k != "_fallback"},
            "supuestos": vote.get("supuestos"),
            "confianza": vote.get("confianza"),
            "acciones": out.get("aceptadas") if name == "critico" else vote.get("recursos") or vote.get("acciones"),
            "resultado": {"texto": out.get("texto"), "incident_id": out.get("incident_id"),
                          "aceptadas": out.get("aceptadas"), "bloqueadas": out.get("bloqueadas"),
                          "ok": out.get("ok"), "fallback": name in fallbacks},
            "tiempos": tiempos,
        }
        saved = cerebro_tools.memoria_guardar(session, payload)
        payload["id"] = saved.get("id") or eid
        payload["ok"] = bool(saved.get("ok", True))
        episodios.append(payload)
    return {"ok": bool(out.get("ok")), "origen": ORIGEN_LLM_LOCAL if not fake else ORIGEN_AGENTE,
            "contexto": ctx, "decision": decision,
            "votos": votos, "conflicto": conflictos, "resultado": out, "episodio": episodios[-1] if episodios else {},
            "episodios": episodios, "tiempos": tiempos, "fake": fake, "fallbacks": fallbacks}


def secrets_token() -> str:
    import secrets
    return secrets.token_hex(2)


def main(argv: list[str] | None = None) -> int:
    from .app import Session, load_case
    ap = argparse.ArgumentParser(prog="motor.server cerebro",
                                 description="Ciclo local contexto → razonar → decidir (sin HappyRobot)")
    ap.add_argument("--case", default="demo-1")
    ap.add_argument("--fake", action="store_true", help="cerebro determinista, sin red")
    ap.add_argument("--ticks", type=int, default=1, help="minutos simulados antes de razonar")
    args = ap.parse_args(argv)
    session = Session(load_case(args.case), threaded=False, playbook="seed", local_params=False)
    try:
        for _ in range(max(0, args.ticks)):
            session.tick()
        client = None if args.fake else llm_parser_factory.make_client()
        fake = args.fake or client is None
        aviso = {"texto": "ciclo local del cerebro", "zona": "front_pit"}
        out = cycle(session, aviso, client=client, fake=fake)
        print(json.dumps({"ok": out["ok"], "fake": out["fake"], "episodio": out["episodio"],
                          "incident_id": (out["resultado"] or {}).get("incident_id"),
                          "aceptadas": (out["resultado"] or {}).get("aceptadas"),
                          "bloqueadas": (out["resultado"] or {}).get("bloqueadas"),
                          "tiempos": out["tiempos"]}, ensure_ascii=False, indent=2))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
