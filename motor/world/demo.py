"""Corre un caso con un agente trivial y pinta la ocupación de las puertas minuto a minuto.

    python3 -m motor.world.demo                      # sin desvío
    python3 -m motor.world.demo --reroute 6          # desvía gate_b -> gate_a en el minuto 6
    python3 -m motor.world.demo --bench 200          # tiempo medio por ejecución

El agente trivial hace trampa (lee `truth_incident` de los avisos): solo sirve para probar el mundo.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from motor.contracts import Action, ActionKind, ResourceStatus

from . import SimComms, World


def trivial_agent(world: World, obs, seen: set[str], n: list[int]) -> list[Action]:
    """Al incidente de cada aviso nuevo le manda el recurso libre más cercano de cada tipo que necesita."""
    actions = []
    taken: set[str] = set()
    for rep in obs.new_reports:
        inc = world.incidents.get(rep.truth_incident or "")
        if inc is None or inc.id in seen or inc.zone is None:
            continue
        seen.add(inc.id)
        for need, count in inc.needs.items():
            free = [r for r in obs.resources.values()
                    if r.status == ResourceStatus.AVAILABLE and r.kind.value == need and r.id not in taken]
            free.sort(key=lambda r: (world.travel_time(r.zone, inc.zone, r.id) or 999, r.id))
            for r in free[:count]:
                taken.add(r.id)
                n[0] += 1
                actions.append(Action(f"a{n[0]}", ActionKind.DISPATCH, obs.t, incident=inc.id, resource=r.id,
                                      zone=inc.zone, why="recurso libre más cercano"))
    return actions


def run(case: dict, seed: int, reroute_at: int | None = None, verbose: bool = True) -> dict:
    world = World.from_case(case, seed)
    SimComms(world, seed)
    seen: set[str] = set()
    n = [0]
    if verbose:
        print(f"{'t':>3} {'hora':>5} {'gate_a':>7} {'d_a':>5} {'gate_b':>7} {'d_b':>5}  novedades")
    while not world.done():
        obs = world.observe()
        actions = trivial_agent(world, obs, seen, n)
        if reroute_at is not None and obs.t == reroute_at:
            actions.append(Action("reroute-1", ActionKind.REROUTE, obs.t, zone="gate_b",
                                  params={"to": "gate_a", "fraction": 0.7}, why="Puerta B saturada"))
        for a in actions:
            world.apply(a)
        if verbose:
            za, zb = obs.zones["gate_a"], obs.zones["gate_b"]
            news = [f"[{r.channel}] {r.text[:70]}" for r in obs.new_reports]
            news += [f"{a.kind} {a.resource or a.zone} -> {a.status} {a.params.get('error', '')}" for a in actions]
            print(f"{obs.t:>3} {obs.clock['hhmm']:>5} {za.occupancy:>7} {za.density:>5.2f} {zb.occupancy:>7} "
                  f"{zb.density:>5.2f}  {' | '.join(news)}")
        world.step()
    return world.truth()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=str(Path(__file__).parent / "demo_case.json"))
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--reroute", type=int, default=None, help="minuto en que se desvía gate_b -> gate_a")
    ap.add_argument("--bench", type=int, default=0, help="repite N veces sin pintar y da el tiempo medio")
    args = ap.parse_args()
    case = json.loads(Path(args.case).read_text(encoding="utf-8"))
    seed = case.get("seed", 0) if args.seed is None else args.seed
    if args.bench:
        run(case, seed, args.reroute, verbose=False)
        t0 = time.perf_counter()
        for _ in range(args.bench):
            run(case, seed, args.reroute, verbose=False)
        print(f"{(time.perf_counter() - t0) / args.bench * 1000:.2f} ms por ejecución (N={args.bench})")
        return
    truth = run(case, seed, args.reroute)
    print("\nIncidentes verdaderos:")
    for iid, inc in truth["incidents"].items():
        print(f"  {iid:<6} {inc['type']:<20} {inc['zone']:<10} sev {inc['severity']}  {inc['status']:<12} "
              f"abierto {inc['t_open']}  atendido {inc['t_first_attention']}  resuelto {inc['t_resolved']}  "
              f"fallido {inc['t_failed']}")
    pk = truth["peak_density"]
    print("Picos de densidad:", ", ".join(f"{z} {pk[z]['density']:.2f}/m² (t={pk[z]['t']})" for z in ("gate_a", "gate_b", "front_pit")))
    print("Población:", truth["population"])


if __name__ == "__main__":
    main()
