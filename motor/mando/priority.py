"""El número de prioridad: quién recibe el recurso escaso.

    prioridad = min(10, gravedad × f_plazo × f_densidad × f_vulnerable × f_tendencia × f_confianza) + ajuste_manual

    gravedad      1..10, la del incidente
    f_plazo       0,6 + 0,6·u          u = 1 − minutos_restantes/30, acotado a [0,1]; sin plazo u = 0,5 → ×0,90
    f_densidad    1 + k·d              d = (densidad − 2)/(7 − 2) acotado a [0,1]; k = 0,3 en aglomeraciones, 0,1 en el resto
                                       (2/m² planificación · 5/m² límite de pie · ~7/m² aplastamiento)
    f_vulnerable  1 · 1,1 · 1,2        zona PMR y/o menores
    f_tendencia   1 + 0,1·s            s = variación de densidad por minuto / 0,2, acotado a [−1,1]
    f_confianza   0,5 + 0,5·confianza  en riesgo vital la confianza nunca cuenta menos de 0,8
    ajuste_manual suma de los `priority_boost` de las lecciones aplicables, acotada a ±2

Suelo: un riesgo vital (posible parada, persona inconsciente) nunca baja de 9,0. Resultado en [0, 10].
Desempate a igual número: más gravedad, menos plazo, id más antiguo.
"""
from __future__ import annotations

from ..contracts import Family, Incident, Zone

HORIZON_MIN = 30
D_PLAN, D_LIMIT, D_CRUSH = 2.0, 5.0, 7.0
LIFE_FLOOR = 9.0
BOOST_MAX = 2.0


def compute(inc: Incident, zone: Zone | None, t: int, trend: float = 0.0, *, life_threat: bool = False,
            minors: bool = False, boost: float = 0.0) -> tuple[float, tuple]:
    """Devuelve (prioridad, factores). Los factores se guardan para explicar sin recalcular."""
    if inc.deadline is None:
        remaining, u = None, 0.5
    else:
        remaining = inc.deadline - t
        u = 1.0 - remaining / HORIZON_MIN
        u = 0.0 if u < 0.0 else 1.0 if u > 1.0 else u
    f_u = 0.6 + 0.6 * u

    dens = zone.occupancy / zone.area_m2 if zone is not None and zone.area_m2 else 0.0
    d = (dens - D_PLAN) / (D_CRUSH - D_PLAN)
    d = 0.0 if d < 0.0 else 1.0 if d > 1.0 else d
    f_d = 1.0 + (0.3 if inc.family == Family.CROWD else 0.1) * d

    f_v = 1.0 + (0.1 if zone is not None and zone.kind == "pmr" else 0.0) + (0.1 if minors else 0.0)

    s = trend / 0.2
    s = -1.0 if s < -1.0 else 1.0 if s > 1.0 else s
    f_t = 1.0 + 0.1 * s

    conf = inc.confidence
    if life_threat and conf < 0.8:
        conf = 0.8
    f_c = 0.5 + 0.5 * conf

    p = inc.severity * f_u * f_d * f_v * f_t * f_c
    if p > 10.0:
        p = 10.0
    boost = -BOOST_MAX if boost < -BOOST_MAX else BOOST_MAX if boost > BOOST_MAX else boost
    p += boost
    if life_threat and p < LIFE_FLOOR:
        p = LIFE_FLOOR
    p = 0.0 if p < 0.0 else 10.0 if p > 10.0 else p
    return round(p, 2), (inc.severity, remaining, f_u, dens, f_d, f_v, s, f_t, conf, f_c, boost, life_threat)


def _es(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def explain(priority: float, factors: tuple) -> str:
    """Una línea: «prioridad 8,7 = gravedad 7 × plazo 10 min (×1,00) × densidad 5,8/m² (×1,23)»."""
    if not factors:
        return f"prioridad {_es(priority)}"
    sev, remaining, f_u, dens, f_d, f_v, s, f_t, conf, f_c, boost, life = factors
    parts = [f"gravedad {sev}"]
    if remaining is None:
        parts.append(f"sin plazo (×{_es(f_u, 2)})")
    elif remaining <= 0:
        parts.append(f"plazo vencido (×{_es(f_u, 2)})")
    else:
        parts.append(f"plazo {remaining} min (×{_es(f_u, 2)})")
    if f_d > 1.005:
        parts.append(f"densidad {_es(dens)}/m² (×{_es(f_d, 2)})")
    if f_v > 1.0:
        parts.append(f"vulnerables (×{_es(f_v, 2)})")
    if abs(f_t - 1.0) > 0.005:
        parts.append(f"densidad {'sube' if s > 0 else 'baja'} (×{_es(f_t, 2)})")
    if f_c < 0.995:
        parts.append(f"confianza {round(conf * 100)} % (×{_es(f_c, 2)})")
    text = f"prioridad {_es(priority)} = " + " × ".join(parts)
    if boost:
        text += f" {'+' if boost > 0 else '−'} {_es(abs(boost))} del manual"
    if life and priority == LIFE_FLOOR:
        text += " · suelo 9,0 por riesgo vital"
    return text


def sort_key(inc: Incident) -> tuple:
    return (-inc.priority, -inc.severity, inc.deadline if inc.deadline is not None else 10 ** 6, inc.id)
