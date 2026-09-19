"""Confianza aprendida por agente y familia: media bayesiana, sin inventar si N < 3."""
from __future__ import annotations

from typing import Any

from . import equipo

PRIOR_A = 1.0
PRIOR_B = 1.0
N_MIN = 3
ALTA = 0.7
BAJA = 0.45
SIN_EVIDENCIA = "sin evidencia"

_HIT = {
    "acepto", "aceptó", "accept", "accepted", "llego", "llegó", "evitado", "evitó",
    "acierto", "ok", "1", "true",
}
_MISS = {
    "rechazo", "rechazó", "reject", "rejected", "silencio", "no_answer", "cumplido", "cumplió",
    "fallo", "0", "false",
}

REGLA_PESO = (
    "Si dos propuestas compiten y ambos agentes tienen N≥3, gana la de mayor puntuación "
    "bayesiana (prior débil α=β=1, media (α+aciertos)/(α+β+N)). Si N<3 se declara "
    "«sin evidencia» y no se usa como peso: el conflicto se conserva o se espera revisión. "
    "Las barandillas no se pesan: lo grave sigue exigiendo persona y lo vital no espera."
)


def _led(session: Any):
    return getattr(session, "ledger", None)


def puntuacion(aciertos: float, n: int) -> tuple[float, str]:
    n = max(0, int(n))
    score = (PRIOR_A + float(aciertos)) / (PRIOR_A + PRIOR_B + n)
    if n < N_MIN:
        return round(score, 3), SIN_EVIDENCIA
    return round(score, 3), "ok"


def fila(agente: str, familia: str, aciertos: float = 0, n: int = 0,
         tendencia: str = "") -> dict[str, Any]:
    score, etiqueta = puntuacion(aciertos, n)
    return {
        "agente": agente, "familia": familia or "todas", "puntuacion": score,
        "n": int(n), "aciertos": float(aciertos), "etiqueta": etiqueta, "tendencia": tendencia or "estable",
        "sin_evidencia": etiqueta == SIN_EVIDENCIA,
    }


def resumen(session: Any, *, familia: str = "") -> list[dict[str, Any]]:
    led = _led(session)
    by: dict[str, dict[str, Any]] = {}
    if led is not None:
        for row in led.confianza_todas():
            if familia and row["familia"] not in (familia, "", "todas"):
                continue
            by.setdefault(row["agente"], fila(row["agente"], row["familia"], row["aciertos"],
                                              row["n"], row.get("tendencia") or ""))
            # si hay varias familias, prioriza la pedida; si no, agrega
    for name in equipo.AGENTES:
        by.setdefault(name, fila(name, familia or "todas"))
    return [by[name] for name in equipo.AGENTES if name in by] + [
        v for k, v in by.items() if k not in equipo.AGENTES]


def de(session: Any, agente: str, familia: str = "") -> dict[str, Any]:
    led = _led(session)
    fam = familia or "todas"
    if led is not None:
        row = led.confianza_get(agente, fam)
        if row:
            return fila(row[0], row[1], row[2], row[3], row[5] or "")
        # media de todas las familias de ese agente
        rows = led.confianza_get(agente, "")
        if isinstance(rows, list) and rows:
            aciertos = sum(r[2] for r in rows)
            n = sum(r[3] for r in rows)
            return fila(agente, fam, aciertos, n)
    cache = getattr(session, "_confianza", {}).get((agente, fam))
    if cache:
        return dict(cache)
    return fila(agente, fam)


def aplicar(session: Any, agente: str, familia: str, resultado: Any) -> dict[str, Any]:
    """Actualiza con un resultado observado. No inventa: N cuenta 1."""
    hit = _es_acierto(resultado)
    if hit is None:
        raise ValueError("resultado no reconocible (aceptó, rechazó, silencio, llegó, evitó, cumplió)")
    fam = (familia or "todas")[:40]
    ag = str(agente or "equipo")[:40]
    prev = de(session, ag, fam)
    n = int(prev["n"]) + 1
    prev_ac = float(prev.get("aciertos") or 0)
    aciertos = prev_ac + (1.0 if hit else 0.0)
    score, etiqueta = puntuacion(aciertos, n)
    old = prev["puntuacion"]
    tendencia = "sube" if score > old + 0.01 else ("baja" if score < old - 0.01 else "estable")
    out = fila(ag, fam, aciertos, n, tendencia)
    out["etiqueta"] = etiqueta
    out["sin_evidencia"] = etiqueta == SIN_EVIDENCIA
    box = getattr(session, "_confianza", None)
    if box is None:
        session._confianza = {}
        box = session._confianza
    box[(ag, fam)] = out
    led = _led(session)
    if led is not None:
        led.confianza_put(ag, fam, aciertos, n, score, tendencia)
    return out


def pesos_para(session: Any, votes: list[dict[str, Any]], familia: str = "") -> dict[str, dict[str, Any]]:
    out = {}
    for vote in votes:
        ag = str(vote.get("agente") or "equipo")
        fam = str(vote.get("tipo") or familia or "")
        out[ag] = de(session, ag, fam)
    return out


def elige(a: dict[str, Any], b: dict[str, Any]) -> str | None:
    """Quién gana un empate. None si no hay evidencia suficiente en ambos."""
    if a.get("sin_evidencia") or b.get("sin_evidencia"):
        return None
    if a.get("n", 0) < N_MIN or b.get("n", 0) < N_MIN:
        return None
    if float(a["puntuacion"]) == float(b["puntuacion"]):
        return None
    return a["agente"] if float(a["puntuacion"]) > float(b["puntuacion"]) else b["agente"]


def autonomia(session: Any, agente: str, familia: str = "") -> dict[str, Any]:
    row = de(session, agente, familia)
    if row["n"] < N_MIN:
        modo = "sin_evidencia"
    elif row["puntuacion"] >= ALTA:
        modo = "directo"
    elif row["puntuacion"] <= BAJA:
        modo = "revision"
    else:
        modo = "par"
    return {
        **row, "autonomia": modo,
        "umbrales": {"n_min": N_MIN, "alta": ALTA, "baja": BAJA, "prior": {"a": PRIOR_A, "b": PRIOR_B}},
        "exige_revision": modo == "revision",
        "ejecuta_directo": modo == "directo",
    }


def _es_acierto(resultado: Any) -> bool | None:
    if isinstance(resultado, bool):
        return resultado
    if isinstance(resultado, (int, float)) and type(resultado) is not bool:
        return bool(resultado)
    if isinstance(resultado, dict):
        if "acierto" in resultado:
            return bool(resultado["acierto"])
        resultado = resultado.get("resultado") or resultado.get("texto") or ""
    raw = str(resultado or "").strip().lower()
    if raw in _HIT:
        return True
    if raw in _MISS:
        return False
    if "acept" in raw or "evit" in raw or "lleg" in raw:
        return True
    if "rechaz" in raw or "silenc" in raw or "cumpl" in raw:
        return False
    return None
