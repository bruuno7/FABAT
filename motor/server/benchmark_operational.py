"""Synthetic SQLite contention, duplicate intake and restart benchmark."""

from __future__ import annotations

import argparse
import json
import random
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

from motor.world import load_festival

from .operational import ACTIVE
from .operational_service import OperationalService
from .operational_types import Document


def run(count: int, seed: int, workers: int) -> Document:
    rng = random.Random(seed)
    reports = [
        rng.choice(
            ("Persona desmayada", "Ola de calor con mareos", "Aglomeración peligrosa")
        )
        for _ in range(count)
    ]
    festival = cast(Document, load_festival())
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "load.sqlite"
        stores = [OperationalService(path, festival) for _ in range(workers)]
        try:
            for index in range(min(count, 20)):
                stores[0].execute(
                    {
                        "command_id": f"actor-{index}",
                        "kind": "register_actor",
                        "actor_id": f"worker-{index}",
                        "name": f"Synthetic {index}",
                        "roles": ["medico", "policia"],
                        "channel": "web",
                        "availability": "available",
                        "zone": "front_pit",
                    }
                )

            def submit(lane: int) -> list[float]:
                durations = []
                store = stores[lane]
                for index in range(lane, count, workers):
                    update: Document = {
                        "update_id": index,
                        "message": {
                            "from": {"id": 10000 + index},
                            "message_id": index,
                            "text": reports[index] + " en escenario 1",
                        },
                    }
                    started = time.perf_counter()
                    first = store.receive_telegram(update)
                    repeated = store.receive_telegram(update)
                    assert not first["duplicate"] and repeated["duplicate"]
                    durations.append((time.perf_counter() - started) * 1000)
                return durations

            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=workers) as pool:
                durations = [
                    value
                    for batch in pool.map(submit, range(workers))
                    for value in batch
                ]
            elapsed = time.perf_counter() - started
            before = stores[0].state()
        finally:
            for store in stores:
                store.close()
        reopened = OperationalService(path, festival)
        try:
            state = reopened.state()
            incidents = cast(list[Document], state["incidents"])
            assignments = cast(list[Document], state["assignments"])
            active = [a for a in assignments if a["status"] in ACTIVE]
            assert len(incidents) == count
            assert len({a["actor_id"] for a in active}) == len(active)
            assert len({a["task_id"] for a in active}) == len(active)
            assert before["revision"] == state["revision"]
        finally:
            reopened.close()
    ordered = sorted(durations)
    return {
        "simulation": True,
        "N": count,
        "seed": seed,
        "workers": workers,
        "seconds": round(elapsed, 3),
        "intake_pairs_per_second": round(count / elapsed, 2),
        "pair_latency_p50_ms": round(statistics.median(ordered), 2),
        "pair_latency_p95_ms": round(ordered[int((count - 1) * 0.95)], 2),
        "pair_latency_max_ms": round(max(ordered), 2),
        "incidents_after_restart": len(incidents),
        "duplicates_suppressed": count,
        "lost_incidents": 0,
        "double_reservations": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=120)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.n <= 10000 or not 1 <= args.workers <= 32:
        parser.error("n must be 1..10000; workers must be 1..32")
    print(json.dumps(run(args.n, args.seed, args.workers), indent=2))


if __name__ == "__main__":
    main()
