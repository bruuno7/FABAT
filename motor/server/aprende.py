"""Agente de aprendizaje local: propone lecciones concretas a partir de episodios reales.

No publica en la plataforma. Una persona (o el test) aprueba / rechaza / revoca.
"""
from __future__ import annotations

import hashlib
import unicodedata
from typing import Any


def _plain(text: str) -> str:
    t = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _ids_recurso(raw: Any) -> list[str]:
    out: list[str] = []
    for item in raw or []:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict):
            rid = str(item.get("id") or item.get("recurso") or "").strip()
            if rid:
                out.append(rid)
    return out


def _kinds(ids: list[str]) -> set[str]:
    kinds = set()
    for rid in ids:
        if rid.startswith("tech"):
            kinds.add("tech")
        elif rid.startswith("sec"):
            kinds.add("security")
        elif rid.startswith("med"):
            kinds.add("medical")
        elif rid.startswith("amb"):
            kinds.add("ambulance")
        elif rid.startswith("log"):
            kinds.add("logistics")
        elif rid.startswith("vol"):
            kinds.add("volunteer")
    return kinds


def _episodio_ids(corrida: dict[str, Any]) -> list[str]:
    ids = []
    for ep in corrida.get("episodios") or corrida.get("episodios_completos") or []:
        if isinstance(ep, dict) and ep.get("id"):
            ids.append(str(ep["id"]))
        elif isinstance(ep, dict) and isinstance(ep.get("ok"), bool) and ep.get("id"):
            ids.append(str(ep["id"]))
    ciclo = corrida.get("ciclo") or {}
    for ep in ciclo.get("episodios") or []:
        if isinstance(ep, dict) and ep.get("id") and ep["id"] not in ids:
            ids.append(str(ep["id"]))
    if not ids:
        ids = [str(corrida.get("id") or corrida.get("escenario", {}).get("id") or "sin-id")]
    return ids[:12]


def _lid(texto: str) -> str:
    h = hashlib.sha1(texto.encode("utf-8")).hexdigest()[:8]
    return f"L-{h}"


def proponer(corridas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """De fallos reales del día → lecciones con evidencia (ids y N) y a qué aplica."""
    buckets: dict[str, dict[str, Any]] = {}

    def add(clave: str, texto: str, *, agente: str, tipo: str, zona: str, corrida: dict, aplica: str) -> None:
        ids = _episodio_ids(corrida)
        row = buckets.setdefault(clave, {
            "id": _lid(clave), "texto": texto, "agente": agente, "para_agente": agente,
            "tipo": tipo, "zona": zona, "aplica": aplica,
            "evidencia": {"ids": [], "n": 0, "agente": agente, "aplica": aplica},
        })
        for i in ids:
            if i not in row["evidencia"]["ids"]:
                row["evidencia"]["ids"].append(i)
        row["evidencia"]["n"] = len(row["evidencia"]["ids"])
        row["tipo"] = row["tipo"] or tipo
        row["zona"] = row["zona"] or zona

    for c in corridas:
        esc = c.get("escenario") or {}
        blob = _plain(" ".join(str(x or "") for x in (
            esc.get("texto"), esc.get("tipo"), esc.get("titulo"), " ".join(esc.get("tags") or []),
        )))
        recs = _ids_recurso(c.get("recursos_agente") or ((c.get("ciclo") or {}).get("votos") or {}).get("recursos", {}).get("recursos"))
        kinds = _kinds(recs)
        tipo = str(esc.get("tipo") or "")
        zona = str(esc.get("zona") or "")
        fuego = tipo == "small_fire" or "incendio" in blob or "llamas" in blob
        if fuego and "tech" in kinds and "security" not in kinds:
            add("incendio-rest",
                "En incendios de restauración, mandar técnico + seguridad a la vez",
                agente="recursos", tipo=tipo or "small_fire", zona=zona or "food",
                corrida=c, aplica="incendios de restauración / small_fire")
        if any(t in (esc.get("tags") or []) for t in ("silencio",)) or "no contesta" in blob:
            if "security" not in kinds and "medical" not in kinds:
                add("silencio-60",
                    "Si el staff no contesta en 60 s, reasignar sin esperar",
                    agente="recursos", tipo=tipo or "team_no_answer", zona=zona,
                    corrida=c, aplica="silencio de staff >60 s")
        if esc.get("vital") and not (kinds & {"medical", "ambulance"}):
            add("vital-minuto",
                "Riesgo vital: despachar el equipo más cercano en el primer minuto",
                agente="prioridad", tipo=tipo, zona=zona, corrida=c, aplica="riesgo vital")
        if "rumor" in blob or "bulo" in blob:
            add("rumor-no-evacua",
                "Un rumor no es un hecho: no evacuar ni parar sin persona",
                agente="critico", tipo=tipo or "rumor_panic", zona=zona, corrida=c,
                aplica="rumores / desalojos pedidos en el texto")

    return list(buckets.values())
