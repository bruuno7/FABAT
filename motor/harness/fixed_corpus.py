"""Explicit simulation corpus, with no file-dependent demo fallback.

python -m motor.harness.fixed_corpus --n 30 --seed 1 --run-seed 100
python -m motor.harness.fixed_corpus --n 30 --run-seed 100 --demo-clones
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from motor.cases.generator import build_case
from motor.cases.validate import validate_case
from motor.harness.metrics import aggregate
from motor.harness.runner import AgentFactory, assert_same_cases, case_signature, code_fingerprint, run_many


def build_corpus(n: int, seed: int = 1, run_seed: int = 100, *, demo_clones: bool = False) -> list[dict]:
    if n < 1:
        raise ValueError("requested N must be positive")
    if demo_clones:
        demo = json.loads((Path(__file__).resolve().parents[1] / "world" / "demo_case.json").read_text())
        cases = [dict(demo, id=f"demo-{i}", seed=run_seed + i) for i in range(n)]
    else:
        cases = [dict(build_case(i, seed, "train"), seed=run_seed + i) for i in range(n)]
        for case in cases:
            errors = validate_case(case)
            if errors:
                raise ValueError(f"{case['id']}: {errors}")
    return cases


def manifest(cases: list[dict], requested_n: int, seed: int, demo_clones: bool) -> dict:
    if len(cases) != requested_n:
        raise ValueError(f"requested N={requested_n}, generated N={len(cases)}")
    return {
        "simulation": True, "requested_n": requested_n, "generated_n": len(cases),
        "corpus": "explicit_demo_clones" if demo_clones else "generated_train",
        "generator_seed": None if demo_clones else seed,
        "run_seeds": [case["seed"] for case in cases],
        "case_ids": [case["id"] for case in cases],
        "case_fingerprint": case_signature(cases), "code_fingerprint": code_fingerprint(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--run-seed", type=int, default=100)
    parser.add_argument("--demo-clones", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--agents", nargs="+", choices=("baseline", "mando"), default=["baseline"])
    args = parser.parse_args()
    cases = build_corpus(args.n, args.seed, args.run_seed, demo_clones=args.demo_clones)
    report = manifest(cases, args.n, args.seed, args.demo_clones)
    arms = {
        f"{agent}/{chaos}": run_many(cases, AgentFactory(agent), workers=args.workers, chaos=chaos)
        for agent in args.agents for chaos in ("none", "random", "smart")
    }
    assert_same_cases(arms, cases)
    if code_fingerprint() != report["code_fingerprint"]:
        raise RuntimeError("code changed while running the simulation")
    report["summary"] = {name: aggregate(rows) for name, rows in arms.items()}
    report["results"] = arms
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if any(row["metrics"]["run_error"] for rows in arms.values() for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
