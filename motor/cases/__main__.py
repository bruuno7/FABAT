"""CLI de casos. Se ejecuta desde la raíz del proyecto:

    python3 -m motor.cases generate --n 5000 --seed 1 --out motor/cases/data/train.jsonl --split train
    python3 -m motor.cases stats motor/cases/data/train.jsonl
    python3 -m motor.cases show motor/cases/data/demo.jsonl c-d000009
    python3 -m motor.cases space
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from typing import Any

from .generator import FAMILY_ORDER, iter_cases, iter_load_cases, max_concurrent, signature, space_size, true_incidents
from .taxonomy import PERTURBATIONS, TAXONOMY, ZONES, combo_universe
from .validate import validate_case


def _load(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _reports(case: dict[str, Any]):
    for ev in case["events"]:
        yield from ev.get("reports") or (ev.get("effect") or {}).get("reports") or []


def cmd_generate(args: argparse.Namespace) -> int:
    t0 = time.perf_counter()
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    n = bad = 0
    with open(args.out, "w", encoding="utf-8") as fh:
        if args.split == "load":  # --n es el total: se reparte a partes iguales entre las cargas 5, 6, 7 y 8
            source = iter_load_cases(seed=args.seed, per_level=max(1, args.n // 4))
        else:
            source = iter_cases(seed=args.seed, split=args.split, n=None if args.split == "demo" else args.n)
        for case in source:
            errors = validate_case(case)
            if errors:
                bad += 1
                print(f"INVÁLIDO {case.get('id')}: {errors[:3]}", file=sys.stderr)
                continue
            fh.write(json.dumps(case, ensure_ascii=False, separators=(",", ":")) + "\n")
            n += 1
    print(f"{n} casos válidos escritos en {args.out} ({args.split}, semilla {args.seed}) en {time.perf_counter() - t0:.2f} s; "
          f"{bad} inválidos descartados")
    return 1 if bad else 0


def _table(title: str, counter: Counter, total: int, order: list[str] | None = None, limit: int | None = None) -> None:
    print(f"\n{title}")
    keys = order if order else [k for k, _ in counter.most_common()]
    for k in keys[:limit]:
        if counter.get(k):
            print(f"  {str(k):<32}{counter[k]:>7}  {100 * counter[k] / total:5.1f} %")
    if limit and len(keys) > limit:
        print(f"  ... y {len(keys) - limit} más")


def cmd_stats(args: argparse.Namespace) -> int:
    cases = _load(args.file)
    n = len(cases)
    if not n:
        print("fichero vacío")
        return 1
    splits = Counter(c["split"] for c in cases)
    print(f"{args.file}: N = {n} casos · particiones {dict(splits)} · firmas estructurales distintas: "
          f"{len({signature(c) for c in cases})}")
    incidents = [i for c in cases for i in true_incidents(c)]
    reports = [r for c in cases for r in _reports(c)]
    print(f"incidentes verdaderos: {len(incidents)} ({len(incidents) / n:.2f} por caso; "
          f"{sum(i['conditional'] for i in incidents)} condicionales por encadenamiento) · avisos: {len(reports)}")

    _table("Casos por familia (un caso cuenta en todas las suyas)", Counter(f for c in cases for f in c["families"]), n, FAMILY_ORDER)
    type_counts = Counter(t for c in cases for t in c["meta"]["types"])
    _table("Casos por tipo", type_counts, n, limit=None if args.all else 15)
    missing = [t for t in TAXONOMY if t not in type_counts]
    print(f"  tipos de la taxonomía presentes: {len(TAXONOMY) - len(missing)} de {len(TAXONOMY)}"
          + (f" · ausentes: {', '.join(missing)}" if missing else ""))
    _table("Dificultad (calculada)", Counter(c["difficulty"] for c in cases), n, [1, 2, 3, 4, 5])
    _table("Avisos por canal", Counter(r["channel"] for r in reports), len(reports))
    _table("Avisos por idioma", Counter(r["lang"] for r in reports), len(reports))
    _table("Calidad de la información", Counter(c["meta"]["info_quality"] for c in cases), n)
    _table("Estado de los recursos", Counter(c["meta"]["resource_state"] for c in cases), n)
    _table("Fase", Counter(c["meta"]["phase"] for c in cases), n)
    _table("Meteorología", Counter(c["meta"]["weather"] for c in cases), n)
    _table("Incidentes verdaderos seguros por caso", Counter(sum(1 for i in true_incidents(c) if not i["conditional"]) for c in cases), n, list(range(1, 10)))
    _table("Máximo de incidentes activos A LA VEZ por caso (de apertura a plazo)", Counter(max_concurrent(c) for c in cases), n, list(range(1, 10)))
    loads = [c for c in cases if c["meta"].get("load")]
    if loads:
        print(f"\nCarga simultánea: {len(loads)} casos")
        print(f"  {'carga':<8}{'casos':>7}{'train':>7}{'heldout':>9}{'sin sorpresa':>14}{'incidente':>11}{'golpe world':>13}{'familias (media)':>18}")
        for level in sorted({c["meta"]["load"] for c in loads}):
            g = [c for c in loads if c["meta"]["load"] == level]
            kinds = Counter(str(c["meta"].get("surprise_kind")) for c in g)
            print(f"  {level:<8}{len(g):>7}{sum(c['split'] == 'train' for c in g):>7}{sum(c['split'] == 'heldout' for c in g):>9}"
                  f"{kinds['None']:>14}{kinds['incident']:>11}{kinds['world']:>13}"
                  f"{sum(c['meta'].get('distinct_families', 0) for c in g) / len(g):>18.1f}")
        _table("Recurso escaso (un caso cuenta en todos los suyos)", Counter(k for c in loads for k in c["meta"].get("scarce_kinds", [])), len(loads))
    chains = Counter(" → ".join(link) for c in cases for link in c["meta"]["chain"])
    print(f"\nEncadenamientos: {sum(1 for c in cases if c['meta']['chain'])} casos, {len(chains)} eslabones distintos")
    for k, v in chains.most_common(None if args.all else 8):
        print(f"  {k:<58}{v:>6}")

    # Cobertura de combinaciones familia × tipo × perturbación.
    seen = {tuple(x) for c in cases for x in c["meta"]["combos"]}
    print(f"\nCobertura de combinaciones (familia × tipo × perturbación): {len(seen)} distintas")
    for split in splits:
        if split == "demo":
            continue
        universe = combo_universe(split)
        own = {tuple(x) for c in cases if c["split"] == split for x in c["meta"]["combos"]}
        print(f"  universo de {split}: {len(universe)} · cubiertas por sus casos: {len(own & universe)} ({100 * len(own & universe) / len(universe):.1f} %)"
              f" · fuera de su universo: {len(own - universe)}")
    short = {p: p.replace("resource_", "r_").replace("zone_", "z_")[:9] for p in PERTURBATIONS}
    print("\n  casos por familia (del incidente) × perturbación")
    print("  " + f"{'':<12}" + "".join(f"{short[p]:>10}" for p in PERTURBATIONS))
    grid = Counter((f, p) for c in cases for f, p in {(x[0], x[2]) for x in c["meta"]["combos"]})
    for f in FAMILY_ORDER:
        if any(grid.get((f, p)) for p in PERTURBATIONS):
            print("  " + f"{f:<12}" + "".join(f"{grid.get((f, p), 0):>10}" for p in PERTURBATIONS))
    pairs = Counter(frozenset((a, b)) for c in cases for a in c["families"] for b in c["families"] if a < b)
    print(f"\n  parejas de familias que coinciden en algún caso: {len(pairs)} de {len(FAMILY_ORDER) * (len(FAMILY_ORDER) - 1) // 2}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    case = next((c for c in _load(args.file) if c["id"] == args.id), None)
    if case is None:
        print(f"no existe el caso {args.id} en {args.file}", file=sys.stderr)
        return 1
    m = case.get("meta", {})
    print(f"{case['id']} · {case['split']} · día {case['day']} {case['start_hhmm']} · {case['duration_min']} min · "
          f"dificultad {case['difficulty']}/5 ({m.get('difficulty_points')} puntos)")
    if m.get("title"):
        print(f"«{m['title']}»\n{m.get('story', '')}")
    print(f"familias: {', '.join(case['families'])}")
    print(f"fase {m.get('phase')} · meteo {m.get('weather')} · información {m.get('info_quality')} · recursos {m.get('resource_state')} · "
          f"perturbaciones {', '.join(m.get('perturbations', []))}")
    if m.get("chain"):
        print("encadenamientos: " + "; ".join(" → ".join(link) for link in m["chain"]))
    ini = case["initial"]
    w = ini.get("weather", {})
    print(f"\nESTADO INICIAL  {w.get('temp_c')} °C, viento {w.get('wind_kmh')} km/h, lluvia {'sí' if w.get('rain') else 'no'}, alerta {w.get('alert') or 'ninguna'}"
          f" · fuera de servicio: {', '.join(ini.get('resources_offline', [])) or 'nadie'}"
          + (f" · fin de turno: {ini['shift_ends']}" if ini.get("shift_ends") else ""))
    dense = sorted(((occ / ZONES[z]["area_m2"], z, occ) for z, occ in ini.get("occupancy", {}).items()), reverse=True)[:4]
    print("  zonas más densas: " + " · ".join(f"{z} {occ} pers. ({d:.1f} p/m²)" for d, z, occ in dense))

    print("\nLÍNEA DE TIEMPO")
    for ev in case["events"]:
        cond = f"  [solo si {ev['cond']['unless_resolved']} no se resuelve]" if "cond" in ev else ""
        body = ev.get("incident") or (ev.get("effect") or {}).get("incident")
        if body:
            via = " (inyectado como efecto world)" if ev["kind"] == "world" else ""
            print(f"  t={ev['t']:>3}  INCIDENTE {body['id']} {body['type']} [{body['family']}] en {body['zone']} · severidad {body['severity']} · "
                  f"plazo t={body['deadline']} · necesita {body['needs']}{via}{cond}")
        elif ev["kind"] == "world":
            eff = dict(ev["effect"])
            print(f"  t={ev['t']:>3}  MUNDO {eff.pop('kind')} {eff}{cond}")
        else:
            print(f"  t={ev['t']:>3}  AVISOS SIN INCIDENTE NUEVO ({ev.get('tag', '?')} → {ev.get('ref', '?')})")
        for r in ev.get("reports") or (ev.get("effect") or {}).get("reports") or []:
            print(f"         [{r['channel']}/{r['lang']}] {r['source']}: {r['text']}")
    exp = case["expected"]
    if exp.get("priority"):
        print("\nPRIORIDAD ESPERADA  " + "  >  ".join(" = ".join(tier) for tier in exp["priority_tiers"])
              + f"   · puede esperar: {', '.join(exp['may_wait']) or 'nadie'}")
    if m.get("load"):
        print(f"CARGA {m['load']} frentes en t={m['window'][0]}–{m['window'][1]} · activos a la vez: {m['max_concurrent']} · "
              f"escasea: {', '.join(m['scarce_kinds'])} (demanda {m['demand']}, hay {m['supply']}) · "
              f"sorpresa: {m.get('surprise_kind') or 'no'}" + (f" en t={m['surprise_t']}" if m.get("surprise_t") is not None else ""))
    print("\nDEBE")
    for rule in case["expected"]["must"]:
        print(f"  + {rule}")
    print("NO DEBE")
    for rule in case["expected"]["must_not"]:
        print(f"  - {rule}")
    return 0


def cmd_check_world(args: argparse.Namespace) -> int:
    """Corre cada caso en `motor.world.World` sin agente y comprueba que no lanza, que ningún efecto es
    rechazado y que el reloj del simulador da la fase que el caso declara."""
    from motor.world import World  # solo aquí: el resto de `motor.cases` no depende del simulador

    cases = _load(args.file)
    problems: list[str] = []
    t0 = time.perf_counter()
    for case in cases:
        try:
            world = World.from_case(case)
            phase0 = world.observe().clock.get("show_phase")
            while not world.done():
                world.step()
            truth = world.truth()
        except Exception as exc:  # noqa: BLE001 - se quiere el recuento completo, no parar en el primero
            problems.append(f"{case['id']}: excepción {type(exc).__name__}: {exc}")
            continue
        for log in truth.get("injected", []):
            if log.get("error"):
                problems.append(f"{case['id']}: efecto rechazado {log['error']}: {log.get('effect')}")
        if phase0 != case["meta"]["phase"]:
            problems.append(f"{case['id']}: el simulador da fase {phase0!r} y el caso declara {case['meta']['phase']!r}")
        expected_ids = {i["id"] for i in true_incidents(case) if not i["conditional"]}
        missing = expected_ids - set(truth.get("incidents", {}))
        if missing:
            problems.append(f"{case['id']}: incidentes que el simulador no abrió: {sorted(missing)}")
    for line in problems[:20]:
        print("  " + line)
    print(f"{args.file}: {len(cases)} casos corridos en motor.world.World en {time.perf_counter() - t0:.1f} s · "
          f"{len(problems)} problemas")
    return 1 if problems else 0


def cmd_space(args: argparse.Namespace) -> int:
    for split in ("train", "heldout"):
        s = space_size(split)
        total = f"{s['total']:,}".replace(",", ".")
        print(f"{split}: {s['types']} tipos · conjuntos de tipos compatibles por tamaño {s['type_sets_by_size']} · "
              f"casos estructurales por tamaño {s['cases_by_size']} · TOTAL (cota inferior) {total}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m motor.cases", description="Taxonomía y generador de casos del Festival Abierto")
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="genera casos, los valida y los escribe en JSONL")
    g.add_argument("--n", type=int, default=1000)
    g.add_argument("--seed", type=int, default=1)
    g.add_argument("--split", choices=("train", "heldout", "demo", "load"), default="train")
    g.add_argument("--out", required=True)
    g.set_defaults(fn=cmd_generate)
    s = sub.add_parser("stats", help="recuentos y cobertura de un fichero de casos")
    s.add_argument("file")
    s.add_argument("--all", action="store_true", help="lista completa de tipos y encadenamientos")
    s.set_defaults(fn=cmd_stats)
    w = sub.add_parser("show", help="imprime un caso legible")
    w.add_argument("file")
    w.add_argument("id")
    w.set_defaults(fn=cmd_show)
    c = sub.add_parser("check-world", help="corre los casos en motor.world.World: sin excepciones ni efectos rechazados")
    c.add_argument("file")
    c.set_defaults(fn=cmd_check_world)
    p = sub.add_parser("space", help="tamaño del espacio de casos (cota inferior)")
    p.set_defaults(fn=cmd_space)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
