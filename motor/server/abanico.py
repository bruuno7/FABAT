"""Enjambre en abanico: el backend lanza los especialistas de HappyRobot en paralelo."""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx

from . import cerebro, cerebro_tools, equipo, enjambre
from .comms_happyrobot import public_base

PAPELES = equipo.PAPELES
OLA1 = ("triaje", "prioridad", "recursos", "avisos", "vigia")
NUCLEO = ("triaje", "prioridad", "recursos")
ENV_KEY = {
    "triaje": "HR_AGENTE_TRIAJE",
    "prioridad": "HR_AGENTE_PRIORIDAD",
    "recursos": "HR_AGENTE_RECURSOS",
    "avisos": "HR_AGENTE_AVISOS",
    "vigia": "HR_AGENTE_VIGIA",
    "critico": "HR_AGENTE_CRITICO",
}
_NODO_OK = ("devolver resultado", "entregar_resultado", "resultado validado")
_LISTO = {"completed", "succeeded", "success", "ok", "done"}
_SIGUE = {"running", "queued", "pending", "in_progress", "in-progress"}
_GRAVE = {"evacuate", "stop_show", "request_external", "evacuar", "parar", "ayuda_externa"}


def timeout_s() -> float:
    try:
        return max(0.2, float(os.environ.get("MANDO_ABANICO_TIMEOUT_S") or "45"))
    except (TypeError, ValueError):
        return 45.0


def poll_s() -> float:
    try:
        return max(0.02, float(os.environ.get("MANDO_ABANICO_POLL_S") or "2"))
    except (TypeError, ValueError):
        return 2.0


def workflow_id(papel: str) -> str:
    return (os.environ.get(ENV_KEY.get(papel) or "") or "").strip()


def api_base() -> str:
    return (os.environ.get("HR_API_BASE") or "").rstrip("/")


def api_key() -> str:
    return (os.environ.get("HR_API_KEY") or "").strip()


def callback_url() -> str:
    return (os.environ.get("MANDO_PUBLIC_URL") or public_base() or "").rstrip("/")


def callback_token() -> str:
    return (os.environ.get("HR_SECRET") or os.environ.get("MANDO_HR_TOKEN") or "").strip()


def plataforma_lista() -> bool:
    return bool(api_base() and api_key() and any(workflow_id(p) for p in OLA1))


def hook(session: Any) -> None:
    if getattr(session, "_abanico_hooked", False):
        return
    session._abanico_hooked = True
    session._abanico_stop = threading.Event()
    session._abanico_threads: list[threading.Thread] = []
    session._abanico_started: set[str] = set()
    session._abanico_report_ids: set[str] = set()
    session._abanico_aviso_text: dict[str, dict[str, Any]] = {}
    session._abanico_allow_reglas: set[str] = set()
    session._abanico_prop: dict[str, dict[str, str]] = {}
    orig_close = session.close
    orig_report = session.report

    def close() -> None:
        session._abanico_stop.set()
        orig_close()
        for t in list(session._abanico_threads):
            if t.is_alive() and t is not threading.current_thread():
                t.join(timeout=2)

    def report(*args: Any, **kwargs: Any) -> Any:
        out = orig_report(*args, **kwargs)
        try:
            rid = str((out or {}).get("report_id") or "")
            if rid:
                session._abanico_report_ids.add(rid)
                texto = kwargs.get("text") or (args[1] if len(args) > 1 else "")
                session._abanico_aviso_text[rid] = {
                    "texto": str(texto or "")[:400],
                    "zona": kwargs.get("zone") or (args[2] if len(args) > 2 else None),
                }
        except Exception:
            pass
        return out

    session.close = close
    session.report = report


def lanzar_si_aviso(session: Any) -> None:
    if cerebro.mode() != "abanico":
        return
    hook(session)
    ids = getattr(session, "_abanico_report_ids", set())
    if not ids:
        return
    for inc in list(getattr(session.agent, "live", []) or []):
        if inc.id in session._abanico_started:
            continue
        recs = set(inc.reports or [])
        if not (recs & ids):
            continue
        arrancar(session, inc.id)


def arrancar(session: Any, incident_id: str, aviso: dict[str, Any] | None = None) -> None:
    hook(session)
    iid = str(incident_id or "").strip()
    if not iid or iid in session._abanico_started:
        return
    session._abanico_started.add(iid)
    aviso = dict(aviso or aviso_de(session, iid), incident_id=iid)
    try:
        ctx = cerebro_tools.contexto(session, aviso)
    except Exception:
        ctx = {"aviso": aviso}
    entrada = {"aviso": aviso, "contexto": ctx, "incident_id": iid, "tipo": "entrada"}
    payload = {
        "entrada_json": json.dumps(entrada, ensure_ascii=False, default=str)[:12000],
        "callback_url": callback_url(),
        "callback_token": callback_token(),
    }
    _init_box(session, iid, lanzados=list(OLA1), fuente="plataforma")
    t = threading.Thread(target=_correr, args=(session, iid, aviso, payload),
                         name=f"abanico-{iid}", daemon=True)
    session._abanico_threads.append(t)
    t.start()


def aviso_de(session: Any, iid: str) -> dict[str, Any]:
    inc = session.agent.incidents.get(iid)
    zona = getattr(inc, "zone", None) if inc is not None else None
    tipo = str(getattr(inc, "type", None) or "")[:40] if inc is not None else ""
    texto = ""
    for rid in list(getattr(inc, "reports", None) or []):
        hint = getattr(session, "_abanico_aviso_text", {}).get(rid) or {}
        texto = str(hint.get("texto") or texto)
        zona = zona or hint.get("zona")
    return {"incident_id": iid, "zona": zona, "texto": texto[:400], "tipo": tipo}


def extraer_voto(blob: Any) -> dict[str, Any] | None:
    if isinstance(blob, str):
        text = blob.strip()
        if text.startswith("{"):
            try:
                blob = json.loads(text)
            except json.JSONDecodeError:
                return None
        else:
            return None
    if not isinstance(blob, dict):
        return None
    if _parece_voto(blob):
        return blob
    for key in ("payload_json", "output", "data", "result", "resultado", "json", "vote"):
        inner = blob.get(key)
        if isinstance(inner, str) and inner.strip().startswith("{"):
            try:
                inner = json.loads(inner)
            except json.JSONDecodeError:
                continue
        if isinstance(inner, dict):
            found = extraer_voto(inner)
            if found:
                return found
        if isinstance(inner, list):
            for item in inner:
                found = extraer_voto(item)
                if found:
                    return found
    return None


def voto_desde(papel: str, raw: dict[str, Any], iid: str) -> dict[str, Any]:
    d = dict(raw)
    d["agente"] = papel
    d["incident_id"] = iid
    if not str(d.get("porque") or "").strip():
        d["porque"] = str(d.get("razonamiento") or d.get("recomendacion") or f"voto de {papel}")[:400]
    d["supuestos"] = _planos(d.get("supuestos"))
    d["vigilar"] = _planos(d.get("vigilar"))
    if papel == "prioridad" and not _es_num(d.get("prioridad")):
        cola = d.get("cola")
        if isinstance(cola, list) and cola and isinstance(cola[0], dict) and _es_num(cola[0].get("prioridad")):
            d["prioridad"] = cola[0]["prioridad"]
    if papel == "recursos" and not d.get("recursos"):
        recs = []
        for a in d.get("asignaciones") or []:
            if isinstance(a, str) and a.strip():
                recs.append(a.strip())
            elif isinstance(a, dict):
                rid = str(a.get("id") or a.get("recurso") or a.get("resource") or "").strip()
                if rid:
                    recs.append(rid)
        d["recursos"] = recs
    if papel == "avisos" and not d.get("avisar"):
        d["avisar"] = d.get("avisos") if isinstance(d.get("avisos"), list) else []
    if papel == "critico":
        ver = str(d.get("veredicto") or d.get("verdict") or "").upper()
        d["veredicto"] = d.get("veredicto") or d.get("verdict")
        if "ESCALAR" in ver:
            d["requiere_persona"] = True
    return d


def ciclo_local(session: Any, aviso: dict[str, Any], **kwargs: Any) -> dict[str, Any] | None:
    from . import llm_parser_factory
    from .cerebro_llm import cycle
    client = llm_parser_factory.make_client()
    if client is None:
        return None
    try:
        return cycle(session, aviso, client=client, fake=False)
    except Exception:
        return None


def lanzar_run(wid: str, payload: dict[str, Any], http: httpx.Client | None = None) -> str:
    client = http or httpx.Client(timeout=8.0)
    own = http is None
    try:
        resp = client.post(
            f"{api_base()}/workflows/{wid}/runs",
            json={"environment": os.environ.get("HR_ENV") or "development", "payload": payload},
            headers={"Authorization": f"Bearer {api_key()}"},
            timeout=8.0,
        )
        if resp.status_code >= 300:
            raise RuntimeError(f"HTTP {resp.status_code}")
        data = resp.json() if resp.content else {}
        queued = data.get("queued_run_ids") if isinstance(data, dict) else None
        rid = data.get("run_id") or (queued[0] if isinstance(queued, list) and queued else "")
        if not rid:
            raise RuntimeError("sin run_id")
        return str(rid)
    finally:
        if own:
            client.close()


def leer_run(run_id: str, http: httpx.Client | None = None) -> dict[str, Any] | None:
    client = http or httpx.Client(timeout=6.0)
    own = http is None
    headers = {"Authorization": f"Bearer {api_key()}"}
    base = api_base()
    try:
        try:
            resp = client.get(f"{base}/runs/{run_id}", headers=headers, timeout=6.0)
        except httpx.HTTPError:
            return None
        body = resp.json() if resp.content and resp.status_code < 300 else {}
        status = str(body.get("status") or "").lower()
        if status not in _SIGUE:
            vote = extraer_voto(body)
            if vote:
                return vote
        try:
            nodes = client.get(f"{base}/runs/{run_id}/nodes", headers=headers, timeout=6.0)
            data = (nodes.json() or {}).get("data") if nodes.status_code < 300 and nodes.content else []
        except httpx.HTTPError:
            data = []
        if not isinstance(data, list):
            data = []
        node = _elegir_nodo(data)
        if node and node.get("output_id"):
            try:
                out = client.get(f"{base}/runs/{run_id}/outputs/{node['output_id']}",
                                 headers=headers, timeout=6.0)
                if out.status_code < 300 and out.content:
                    vote = extraer_voto(out.json())
                    if vote:
                        return vote
            except httpx.HTTPError:
                pass
            vote = extraer_voto(node)
            if vote:
                return vote
        return None
    finally:
        if own:
            client.close()


def _correr(session: Any, iid: str, aviso: dict[str, Any], payload: dict[str, Any]) -> None:
    t0 = time.monotonic()
    votes: dict[str, dict[str, Any]] = {}
    run_ids: dict[str, str] = {}
    if not plataforma_lista() or _stopped(session):
        _fallback(session, iid, aviso, t0)
        return
    with httpx.Client(timeout=8.0) as http:
        with ThreadPoolExecutor(max_workers=5) as pool:
            futs = {}
            for papel in OLA1:
                wid = workflow_id(papel)
                if not wid:
                    continue
                futs[pool.submit(_safe_lanzar, wid, payload, http)] = papel
            for fut in as_completed(futs):
                papel = futs[fut]
                rid = fut.result()
                if rid:
                    run_ids[papel] = rid
        if not run_ids:
            _fallback(session, iid, aviso, t0)
            return
        decided = False
        critico_on = False
        timeouts: list[str] = []
        deadline = t0 + timeout_s()
        while not _stopped(session) and time.monotonic() < deadline:
            _recolectar(session, iid, run_ids, votes, t0, http)
            if not decided and all(p in votes for p in NUCLEO):
                _componer_y_ejecutar(session, iid, votes, t0)
                decided = True
            if decided and not critico_on:
                critico_on = _lanzar_critico(session, iid, aviso, payload, votes, run_ids, http)
            if critico_on:
                _recolectar(session, iid, run_ids, votes, t0, http)
                if "critico" in votes:
                    _tratar_critico(session, iid, aviso, payload, votes, run_ids, t0, http)
            _marcar_timeouts(session, iid, run_ids, votes, timeouts, t0, deadline)
            if _enjambre_completo(votes, timeouts, critico_on):
                break
            time.sleep(poll_s())
        _marcar_timeouts(session, iid, run_ids, votes, timeouts, t0, time.monotonic())
        if not decided:
            if all(p in votes for p in NUCLEO):
                _componer_y_ejecutar(session, iid, votes, t0)
                decided = True
            else:
                _fallback(session, iid, aviso, t0)
                return
        if decided and not critico_on:
            _lanzar_critico(session, iid, aviso, payload, votes, run_ids, http)
            fin = time.monotonic() + min(8.0, timeout_s())
            while not _stopped(session) and time.monotonic() < fin and "critico" not in votes:
                _recolectar(session, iid, run_ids, votes, t0, http)
                time.sleep(poll_s())
            if "critico" in votes:
                _tratar_critico(session, iid, aviso, payload, votes, run_ids, t0, http)
        _cerrar(session, iid, t0, "plataforma")


def _safe_lanzar(wid: str, payload: dict[str, Any], http: httpx.Client | None = None) -> str | None:
    try:
        return lanzar_run(wid, payload, http)
    except (RuntimeError, httpx.HTTPError, ValueError, TypeError):
        return None


def _recolectar(session: Any, iid: str, run_ids: dict[str, str],
                votes: dict[str, dict[str, Any]], t0: float,
                http: httpx.Client | None = None) -> None:
    for papel, rid in list(run_ids.items()):
        if papel in votes:
            continue
        raw = leer_run(rid, http)
        if not raw:
            continue
        vote = voto_desde(papel, raw, iid)
        votes[papel] = vote
        _llegada(session, iid, papel, vote, int(round(time.monotonic() - t0)))


def _lanzar_critico(session: Any, iid: str, aviso: dict[str, Any], payload: dict[str, Any],
                    votes: dict[str, dict[str, Any]], run_ids: dict[str, str],
                    http: httpx.Client | None = None) -> bool:
    wid = workflow_id("critico")
    if not wid:
        return False
    extra = dict(payload)
    entrada = {
        "aviso": aviso, "incident_id": iid, "tipo": "revision",
        "decision": {k: v for k, v in votes.items() if k != "critico"},
    }
    extra["entrada_json"] = json.dumps(entrada, ensure_ascii=False, default=str)[:12000]
    rid = _safe_lanzar(wid, extra, http)
    if not rid:
        return False
    run_ids["critico"] = rid
    box = _ab(session, iid)
    lanz = list(box.get("lanzados") or [])
    if "critico" not in lanz:
        lanz.append("critico")
        box["lanzados"] = lanz
        _rebuild(session)
    return True


def _tratar_critico(session: Any, iid: str, aviso: dict[str, Any], payload: dict[str, Any],
                    votes: dict[str, dict[str, Any]], run_ids: dict[str, str], t0: float,
                    http: httpx.Client | None = None) -> None:
    cr = votes.get("critico") or {}
    if cr.get("_tratado"):
        return
    cr["_tratado"] = True
    ver = str(cr.get("veredicto") or "").upper()
    acciones = [a for a in (cr.get("acciones") or []) if isinstance(a, dict)]
    grave = any(str(a.get("kind") or a.get("tipo") or "").lower() in _GRAVE for a in acciones)
    objeta = grave or cr.get("requiere_persona") is True or "CORREG" in ver or "ESCALAR" in ver or "OBJE" in ver
    if not objeta:
        return
    if grave or "ESCALAR" in ver or cr.get("requiere_persona"):
        body = {
            "agente": "critico", "incident_id": iid,
            "porque": str(cr.get("porque") or "objeción alta: una persona decide lo grave")[:400],
            "requiere_persona": True,
            "acciones": [a for a in acciones if str(a.get("kind") or a.get("tipo") or "").lower() in _GRAVE],
            "prioridad": cr.get("prioridad"),
            "zona": aviso.get("zona"),
        }
        try:
            d = cerebro_tools.validate_decision(body)
            d["agente"] = "critico"
            out = cerebro_tools._aplicar_decision(session, d)
            equipo.record_result(session, iid, out)
        except (ValueError, TypeError) as exc:
            session.log("cerebro", f"abanico: crítico no pudo escalar ({type(exc).__name__})", iid)
    afectados = []
    for item in cr.get("correcciones") or []:
        if isinstance(item, dict):
            name = item.get("agente") or item.get("papel")
        else:
            name = item
        name = str(name or "").strip().lower()
        if name in OLA1 and name not in afectados:
            afectados.append(name)
    if "vigia" not in afectados:
        afectados.append("vigia")
    extra = dict(payload)
    extra["entrada_json"] = json.dumps(
        {"aviso": aviso, "incident_id": iid, "tipo": "cambio", "relanzar": afectados,
         "objecion": cr.get("porque")},
        ensure_ascii=False, default=str)[:8000]
    for papel in afectados:
        wid = workflow_id(papel)
        if not wid:
            continue
        rid = _safe_lanzar(wid, extra, http)
        if rid:
            run_ids[papel] = rid
            votes.pop(papel, None)
    enlaza = (getattr(session, "_abanico_prop", {}).get(iid) or {}).get("recursos") or "decision"
    try:
        enjambre.publicar(session, {
            "de": "critico", "para": "recursos", "incidente": iid,
            "tipo": "objecion", "gravedad": "alta", "enlaza": enlaza,
            "texto": str(cr.get("porque") or "objeción alta del crítico")[:400],
        })
    except ValueError:
        pass


def _componer_y_ejecutar(session: Any, iid: str, votes: dict[str, dict[str, Any]], t0: float) -> None:
    from . import confianza as conf_mod
    lista = [votes[p] for p in PAPELES if p in votes]
    pesos = conf_mod.pesos_para(session, lista)
    joint, _conflicts = equipo.compose(lista, pesos=pesos)
    if not str(joint.get("porque") or "").strip():
        joint["porque"] = next((v.get("porque") for v in lista if v.get("porque")), "composición del abanico")
    joint["agente"] = "equipo"
    joint["incident_id"] = iid
    try:
        cerebro_tools.decidir(session, joint)
    except (ValueError, TypeError) as exc:
        session.log("cerebro", f"abanico: decidir falló ({type(exc).__name__})", iid)
        return
    box = _ab(session, iid)
    if box.get("primera_decision_s") is None:
        box["primera_decision_s"] = int(max(0, round(time.monotonic() - t0)))
        box["fuente"] = box.get("fuente") or "plataforma"
        cerebro.mark_decided(session, iid)
        _rebuild(session)


def _llegada(session: Any, iid: str, papel: str, vote: dict[str, Any], s: int) -> None:
    vote = dict(vote, agente=papel, incident_id=iid, s=s)
    equipo.store_raw(session, iid, vote)
    equipo.record_vote(session, iid, vote)
    ab = _ab(session, iid)
    llegados = list(ab.get("llegados") or [])
    if not any(x.get("papel") == papel for x in llegados):
        llegados.append({"papel": papel, "s": s})
        ab["llegados"] = llegados
    try:
        pub = enjambre.publicar(session, {
            "de": papel, "para": "todos", "incidente": iid, "tipo": "propuesta",
            "texto": str(vote.get("porque") or papel)[:400],
            "confianza": vote.get("confianza") if isinstance(vote.get("confianza"), (int, float)) else None,
        })
        session._abanico_prop.setdefault(iid, {})[papel] = str(pub.get("id") or "")
    except ValueError:
        pass
    _rebuild(session)


def _fallback(session: Any, iid: str, aviso: dict[str, Any], t0: float) -> None:
    out = None
    try:
        out = ciclo_local(session, dict(aviso or {}, incident_id=iid))
    except Exception:
        out = None
    if out and out.get("ok"):
        for name, vote in (out.get("votos") or {}).items():
            if name in PAPELES:
                s = int(max(0, round(time.monotonic() - t0)))
                _llegada(session, iid, name, voto_desde(name, vote, iid), s)
        box = _ab(session, iid)
        box["fuente"] = "local"
        box["primera_decision_s"] = box.get("primera_decision_s")
        if box["primera_decision_s"] is None:
            box["primera_decision_s"] = int(max(0, round(time.monotonic() - t0)))
        cerebro.mark_decided(session, iid)
        session._cerebro_cadena = "llm_local"
        _cerrar(session, iid, t0, "local")
        return
    session._cerebro_degradado = True
    session._cerebro_cadena = "reglas"
    session._abanico_allow_reglas.add(iid)
    session.log("cerebro", f"{cerebro.ETIQUETA_DEGRADADO}: abanico sin plataforma ni LLM local", iid)
    wake = getattr(session, "_wake", None)
    if wake is not None:
        wake.set()
    box = _ab(session, iid)
    box["fuente"] = "reglas"
    box["primera_decision_s"] = box.get("primera_decision_s") or int(max(0, round(time.monotonic() - t0)))
    _cerrar(session, iid, t0, "reglas")


def _cerrar(session: Any, iid: str, t0: float, fuente: str) -> None:
    box = _ab(session, iid)
    box["fuente"] = fuente
    box["final_s"] = int(max(0, round(time.monotonic() - t0)))
    _rebuild(session)


def _marcar_timeouts(session: Any, iid: str, run_ids: dict[str, str], votes: dict[str, dict[str, Any]],
                     timeouts: list[str], t0: float, deadline: float) -> None:
    if time.monotonic() < deadline:
        return
    for papel in list(run_ids):
        if papel not in votes and papel not in timeouts:
            timeouts.append(papel)
    box = _ab(session, iid)
    if timeouts and box.get("timeouts") != timeouts:
        box["timeouts"] = list(timeouts)
        _rebuild(session)


def _enjambre_completo(votes: dict[str, dict[str, Any]], timeouts: list[str], critico_on: bool) -> bool:
    need = set(OLA1)
    if critico_on:
        need.add("critico")
    return need <= (set(votes) | set(timeouts))


def _init_box(session: Any, iid: str, *, lanzados: list[str], fuente: str) -> dict[str, Any]:
    box = equipo.card(session, iid)
    ab = box.setdefault("abanico", {})
    ab.setdefault("lanzados", list(lanzados))
    ab.setdefault("llegados", [])
    ab.setdefault("timeouts", [])
    ab.setdefault("primera_decision_s", None)
    ab.setdefault("final_s", None)
    ab["fuente"] = fuente
    _rebuild(session)
    return ab


def _ab(session: Any, iid: str) -> dict[str, Any]:
    return equipo.card(session, iid).setdefault("abanico", {
        "lanzados": [], "llegados": [], "timeouts": [],
        "primera_decision_s": None, "final_s": None, "fuente": "plataforma",
    })


def _rebuild(session: Any) -> None:
    try:
        with session.lock:
            session._rebuild()
    except Exception:
        pass


def _stopped(session: Any) -> bool:
    ev = getattr(session, "_abanico_stop", None)
    if ev is not None and ev.is_set():
        return True
    stop = getattr(session, "_stop", None)
    return bool(stop is not None and stop.is_set())


def _parece_voto(d: dict[str, Any]) -> bool:
    if d.get("agente") or d.get("razonamiento") or d.get("porque"):
        return True
    return bool(d.get("veredicto") or d.get("prioridad") is not None or d.get("recursos") or d.get("asignaciones"))


def _elegir_nodo(nodes: list[Any]) -> dict[str, Any] | None:
    named = []
    ready = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        label = " ".join(str(n.get(k) or "") for k in ("name", "title", "label", "tool", "type")).lower()
        if any(tok in label for tok in _NODO_OK) or str(n.get("is_response_node") or "").lower() in ("1", "true"):
            named.append(n)
        if str(n.get("status") or "").lower() in _LISTO and n.get("output_id"):
            ready.append(n)
    for n in named + ready + [n for n in nodes if isinstance(n, dict)]:
        if n.get("output_id") or extraer_voto(n):
            return n
    return named[0] if named else (ready[-1] if ready else None)


def _planos(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out = []
    for x in raw[:8]:
        if isinstance(x, str) and x.strip():
            out.append(x.strip()[:200])
        elif isinstance(x, dict):
            t = str(x.get("hecho") or x.get("text") or x.get("texto") or "")[:200]
            if t:
                out.append(t)
    return out


def _es_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and type(v) is not bool

