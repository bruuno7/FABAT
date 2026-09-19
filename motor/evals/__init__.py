"""Orquesta las seis suites y escribe el informe."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from . import adversary, comprehension, conversation, notifications, platform, safety
from .common import EvalResult
from .report import write


def run(*, rapido: bool = False, out_dir: Path | None = None) -> dict[str, Any]:
    t0 = time.perf_counter()
    evals: list[EvalResult] = []
    evals += safety.run(rapido=rapido)
    evals += comprehension.run(rapido=rapido)
    evals += conversation.run(rapido=rapido)
    evals += adversary.run(rapido=rapido)
    evals += notifications.run(rapido=rapido)
    evals += platform.run(rapido=rapido)
    wall = time.perf_counter() - t0
    paths = write(evals, rapido=rapido, wall_s=wall, out_dir=out_dir)
    payload = paths.pop("payload")
    return {"evals": evals, "wall_s": wall, "paths": paths, "payload": payload}


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Audits & Tests de MANDO (simulación).")
    p.add_argument("--rapido", action="store_true", help="pasada de menos de 60 s")
    p.add_argument("--out", type=Path, default=None, help="directorio de salida (por defecto motor/evals/out)")
    args = p.parse_args(argv)
    result = run(rapido=args.rapido, out_dir=args.out)
    payload = result["payload"]
    print(f"simulación · {'rápido' if args.rapido else 'completo'} · {payload['wall_s']} s")
    print(f"evals {payload['n_evals']} · N total {payload['suma_n']} · "
          f"aprobados {payload['suma_aprobados']} · fallos {payload['suma_fallos']}")
    print("lo que falla hoy:")
    fails = payload["lo_que_falla_hoy"]
    if not fails:
        print("  (ningún eval local con fallos en esta pasada)")
    else:
        for f in fails:
            print(f"  {f['id']}: {f['fallos']}/{f['n']}  {f['ejemplo'].get('detalle', '')[:120]}")
    print(result["paths"]["informe"])
    print(result["paths"]["resultados"])
    return 0
