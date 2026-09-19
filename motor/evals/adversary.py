"""Suite 4 — Adversarial Agent del MUNDO (Caos), no de la conversación."""
from __future__ import annotations

from typing import Any

from motor.caos import Chaos

from .common import EvalResult, fail_ex, median_or_none, select_cases, simulate


def run(rapido: bool = False) -> list[EvalResult]:
    n = 2 if rapido else 8
    budgets = (1,) if rapido else (1, 3, 5)
    lookahead = 6 if rapido else 10
    cases = select_cases(n=n, scan=40 if rapido else 80)
    out: list[EvalResult] = []
    for budget in budgets:
        mando_rows = []
        base_rows = []
        for c in cases:
            seed = int(c.get("seed", 0))
            mando_rows.append(simulate(c, seed, agent_name="mando",
                                       chaos=Chaos(budget=budget, lookahead=lookahead)))
            base_rows.append(simulate(c, seed, agent_name="baseline",
                                      chaos=Chaos(budget=budget, lookahead=lookahead)))
        out.append(_compare(budget, mando_rows, base_rows))
    return out


def _crit(row: dict[str, Any]) -> int:
    return int(row["metrics"].get("critical_failed") or 0)


def _recovered(row: dict[str, Any]) -> bool:
    if not row.get("strikes"):
        return False
    if row.get("strike_to_plan"):
        return True
    return bool(row.get("replan_delays")) or int(row["metrics"].get("replans") or 0) > 0


def _compare(budget: int, mando: list[dict[str, Any]], baseline: list[dict[str, Any]]) -> EvalResult:
    n = len(mando)
    struck = [r for r in mando if r.get("strikes")]
    recovered = [r for r in struck if _recovered(r)]
    delays = [d for r in mando for d in (r.get("strike_to_plan") or r.get("replan_delays") or [])]
    crit_m = sum(_crit(r) for r in mando)
    crit_b = sum(_crit(r) for r in baseline)
    fails = []
    # no es un umbral de «ganar»: se informa. Un fallo duro: Caos tumba el reloj (excepción ya no llega aquí).
    # Marcamos fallo si Mando, con el mismo caso y semilla, deja MÁS críticos que la lista fija.
    worse = 0
    for m, b in zip(mando, baseline):
        if _crit(m) > _crit(b):
            worse += 1
            fails.append(fail_ex(m["seed"], m["case_id"],
                                 f"Mando críticos={_crit(m)} > lista fija {_crit(b)} con presupuesto {budget}"))
    extra = {
        "presupuesto": budget,
        "n": n,
        "casos_con_golpe": len(struck),
        "tasa_recuperacion_mando": round(len(recovered) / len(struck), 3) if struck else None,
        "mediana_min_plan_nuevo": median_or_none(delays),
        "criticos_fallidos_mando": crit_m,
        "criticos_fallidos_lista_fija": crit_b,
        "golpes_medios_mando": round(sum(len(r.get("strikes") or []) for r in mando) / n, 2) if n else 0,
        "lista_fija_sin_planes": True,
        "nota_lista_fija": "Baseline.snapshot()['plans'] es []: no escribe supuestos ni plan nuevo.",
    }
    notes = (
        f"Simulación. Adversary del MUNDO (Caos, lookahead corto), no Adversarial Agent de conversación de HappyRobot. "
        f"Recuperación = plan nuevo tras golpe. N={n} casos × presupuesto {budget}. "
        f"Mando críticos={crit_m} · lista fija={crit_b}."
    )
    # el eval «aprueba» si no empeora vs lista fija en ningún caso; la tasa se reporta igual
    return EvalResult(
        id=f"ADV-caos-b{budget}",
        suite="adversario",
        description=f"Caos presupuesto {budget}: recuperación, minutos hasta plan nuevo, críticos vs lista fija.",
        n=n, passed=n - worse, failures=fails, extra=extra, notes=notes,
    )
