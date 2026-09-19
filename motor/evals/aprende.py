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


def aprender_banco(escenarios: list[dict[str, Any]], *, fake: bool = True,
                   client: Callable[[str], str] | None = None, by: str = "eval") -> dict[str, Any]:
    """Día 1 del banco → lecciones con evidencia → persona (test) aprueba → mismo banco día 2."""
    from .equipo import evaluar

    d1 = dia(escenarios, fake=fake, client=client, etiqueta="dia1")
    s1 = evaluar(d1["corridas"], fake=bool(fake or client is None), client=None, juez=False)
    props = proponer_y_aplicar(
        d1,
        aprobar=("incendio", "técnico", "tecnico", "60", "reasign", "vital", "rumor", "minuto"),
        rechazar=("voluntario",),
        by=by,
    )
    d2 = dia(escenarios, fake=fake, client=client, etiqueta="dia2")
    s2 = evaluar(d2["corridas"], fake=bool(fake or client is None), client=None, juez=False)
    cambios: list[dict[str, Any]] = []
    no_repiten: list[str] = []
    regresiones: list[str] = []
    for a, b in zip(d1["corridas"], d2["corridas"]):
        eid = a["id"]
        rec_a, rec_b = list(a.get("recursos_agente") or []), list(b.get("recursos_agente") or [])
        prio_a, prio_b = a.get("prioridad"), b.get("prioridad")
        if rec_a != rec_b or prio_a != prio_b:
            cambios.append({"id": eid, "rec1": rec_a, "rec2": rec_b, "prio1": prio_a, "prio2": prio_b})
        r1, r2 = score_pair(s1, eid), score_pair(s2, eid)
        if r1 and not r2:
            regresiones.append(eid)
        if (not r1) and r2:
            no_repiten.append(eid)
    mejora_recurso = s2["recurso_ok"] > s1["recurso_ok"]
    mejora_prio = s2["prioridad_ok"] > s1["prioridad_ok"]
    mejora = bool(cambios) and (mejora_recurso or mejora_prio or no_repiten) and not (
        s2["recurso_ok"] < s1["recurso_ok"] or s2["prioridad_ok"] < s1["prioridad_ok"]
    )
    empeora = s2["recurso_ok"] < s1["recurso_ok"] or s2["prioridad_ok"] < s1["prioridad_ok"] or bool(regresiones)
    md_lines = [
        f"Banco N={s1['n']} (mismos escenarios). "
        f"Día 1 recurso {s1['recurso_ok']}/{s1['n']} prioridad {s1['prioridad_ok']}/{s1['n']}; "
        f"día 2 recurso {s2['recurso_ok']}/{s2['n']} prioridad {s2['prioridad_ok']}/{s2['n']}.",
        f"Decisiones distintas: {len(cambios)}/{s1['n']}. "
        f"Errores que no se repiten: {len(no_repiten)}/{s1['n']}. "
        f"Regresiones: {len(regresiones)}/{s1['n']}.",
        f"Lecciones propuestas {len(props['propuestas'])} · aprobadas {len(props['aprobadas'])} · "
        f"rechazadas {len(props['rechazadas'])}.",
    ]
    if empeora or not mejora:
        md_lines.append("**No mejora o empeora en alguna métrica: se dice, no se maquilla.**")
    for p in props["propuestas"]:
        ev = p.get("evidencia") or {}
        estado = "APROBADA" if p["id"] in props["aprobadas"] else (
            "RECHAZADA" if p["id"] in props["rechazadas"] else "propuesta")
        md_lines.append(
            f"- `{p['id']}` {estado}: {p['texto']} "
            f"(evidencia n={ev.get('n')} ids={ev.get('ids')}; aplica {p.get('aplica')} → {p.get('agente')})"
        )
    for c in cambios[:8]:
        md_lines.append(f"- cambio `{c['id']}`: recursos {c['rec1']} → {c['rec2']}")
    return {
        "n": s1["n"], "n_dia1": d1["n"], "n_dia2": d2["n"],
        "dia1": {"recurso_ok": s1["recurso_ok"], "prioridad_ok": s1["prioridad_ok"],
                 "barandillas_ok": s1["barandillas_ok"], "json_ok": s1["json_ok"],
                 "latencia_mediana_s": s1["latencia_mediana_s"]},
        "dia2": {"recurso_ok": s2["recurso_ok"], "prioridad_ok": s2["prioridad_ok"],
                 "barandillas_ok": s2["barandillas_ok"], "json_ok": s2["json_ok"],
                 "latencia_mediana_s": s2["latencia_mediana_s"]},
        "propuestas": props["propuestas"], "aprobadas": props["aprobadas"],
        "rechazadas": props["rechazadas"], "cambios": cambios,
        "no_repiten": no_repiten, "regresiones": regresiones,
        "cambio": bool(cambios), "mejora": mejora and not empeora, "empeora": empeora,
        "markdown": "\n".join(md_lines),
    }


def score_pair(summary: dict[str, Any], eid: str) -> bool:
    for f in summary.get("filas") or []:
        if f.get("id") == eid:
            return bool(f["barandillas"]["ok"] and f["prioridad"]["ok"] and f["recurso"]["cercano_o_tipo"])
    return False


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
