"""Día 1 → lecciones → día 2. Demo de 1 minuto con cerebro falso.

python3 -m motor.evals aprende --demo
"""
from __future__ import annotations

from typing import Any, Callable

from motor.server import cerebro_tools
from motor.server.aprende import proponer as proponer_lecciones

from .equipo import correr_uno, session_eval
from .escenarios_diversos import por_id


def dia(escenarios: list[dict[str, Any]], *, fake: bool = True,
        client: Callable[[str], str] | None = None, etiqueta: str = "") -> dict[str, Any]:
    corridas = [correr_uno(esc, fake=fake, client=client) for esc in escenarios]
    return {"n": len(corridas), "corridas": corridas, "etiqueta": etiqueta, "fake": fake}


def proponer_y_aplicar(d1: dict[str, Any], *, aprobar: tuple[str, ...] = ("incendio",),
                       rechazar: tuple[str, ...] = ("voluntario",), by: str = "test") -> dict[str, Any]:
    propuestas = proponer_lecciones(d1.get("corridas") or [])
    s = session_eval()
    aprobadas: list[str] = []
    rechazadas: list[str] = []
    try:
        for p in propuestas:
            cerebro_tools.memoria_lecciones(s, {
                "accion": "proponer", "id": p["id"], "texto": p["texto"],
                "evidencia": p.get("evidencia") or {}, "tipo": p.get("tipo") or "",
                "zona": p.get("zona") or "", "para_agente": p.get("para_agente") or p.get("agente") or "",
                "aplica": p.get("aplica") or "",
            }, by=by)
            blob = (p.get("texto") or "").lower()
            if any(k in blob for k in rechazar):
                cerebro_tools.memoria_lecciones(s, {"accion": "rechazar", "id": p["id"]}, by=by)
                rechazadas.append(p["id"])
            elif not aprobar or any(k in blob for k in aprobar):
                cerebro_tools.memoria_lecciones(s, {"accion": "aprobar", "id": p["id"]}, by=by)
                aprobadas.append(p["id"])
    finally:
        s.close()
    return {"propuestas": propuestas, "aprobadas": aprobadas, "rechazadas": rechazadas}


def revocar(session: Any, lesson_id: str, *, by: str = "test") -> dict[str, Any]:
    return cerebro_tools.memoria_lecciones(session, {"accion": "revocar", "id": lesson_id}, by=by)


def _fmt_recs(recs: list[str]) -> str:
    return "[" + ", ".join(recs) + "]" if recs else "[]"


def demo() -> dict[str, Any]:
    """Fallo día 1 → lección con evidencia → aprobada → día 2 distinta y mejor."""
    from .equipo import isolate_eval_db
    isolate_eval_db()
    esc = por_id("d-incendio-restauracion")
    d1 = dia([esc], fake=True, etiqueta="dia1")
    rec1 = d1["corridas"][0]["recursos_agente"]
    ep_ids = [e.get("id") for e in d1["corridas"][0].get("episodios") or [] if e.get("id")]
    print("DÍA 1  escenario d-incendio-restauracion")
    print(f"  fallo: recursos={_fmt_recs(rec1)}  (técnico sin seguridad en incendio de restauración)")
    print(f"  episodios: {ep_ids}  N={d1['n']}")
    props = proponer_y_aplicar(d1, aprobar=("incendio", "técnico", "tecnico"), rechazar=("voluntario",), by="demo")
    print("LECCIÓN")
    if not props["propuestas"]:
        print("  (el agente de aprendizaje no propuso nada; eso se dice)")
    for p in props["propuestas"]:
        estado = "APROBADA" if p["id"] in props["aprobadas"] else (
            "RECHAZADA" if p["id"] in props["rechazadas"] else "propuesta")
        ev = p.get("evidencia") or {}
        print(f"  {p['id']}  {p['texto']}")
        print(f"  evidencia: ids={ev.get('ids')} n={ev.get('n')}  aplica: {p.get('aplica')} → {p.get('agente')}")
        print(f"  {estado} por test/demo")
    d2 = dia([esc], fake=True, etiqueta="dia2")
    rec2 = d2["corridas"][0]["recursos_agente"]
    cambio = set(rec1) != set(rec2)
    mejor = any(r.startswith("sec") for r in rec2) and any(r.startswith("tech") for r in rec2)
    print("DÍA 2  misma situación")
    print(f"  recursos={_fmt_recs(rec2)}  distinta={'sí' if cambio else 'no'}  mejor={'sí' if mejor else 'no'}")
    print(f"N_dia1={d1['n']} N_dia2={d2['n']}  cambio_observable={'sí' if cambio else 'no'}")
    if not cambio or not mejor:
        print("  AVISO: no mejoró o no cambió. No se maquilla.")
    md = (
        f"- Día 1 (N={d1['n']}): recursos `{rec1}` — fallo: técnico sin seguridad.\n"
        f"- Lección: {props['propuestas'][0]['texto'] if props['propuestas'] else '(ninguna)'} "
        f"(evidencia n={(props['propuestas'][0].get('evidencia') or {}).get('n') if props['propuestas'] else 0}).\n"
        f"- Día 2 (N={d2['n']}): recursos `{rec2}` — "
        f"{'cambia y cubre técnico+seguridad' if mejor else 'no mejora'}."
    )
    return {
        "n_dia1": d1["n"], "n_dia2": d2["n"], "cambio": cambio, "mejora": mejor,
        "rec1": rec1, "rec2": rec2, "propuestas": props["propuestas"],
        "aprobadas": props["aprobadas"], "markdown": md,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="motor.evals aprende")
    p.add_argument("--demo", action="store_true", help="1 minuto: día 1 → lección → día 2")
    args = p.parse_args(argv)
    if args.demo:
        demo()
        return 0
    p.print_help()
    return 2
