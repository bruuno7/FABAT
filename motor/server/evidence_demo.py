"""Ejemplos auditables demo-1, N visible. Solo simulación; no red, git ni hackspain.

python -m motor.server.evidence_demo --n 200 --seed 1 --out /tmp/evidence-demo.json
"""
import argparse
import json
from pathlib import Path
from .app import Session, load_case
from .evidence_runtime import evidence
from .simulacro import SimulacroService


def run(n=200, seed=1):
    session = Session(load_case('demo-1'), threaded=False, playbook='seed', local_params=False)
    drill = SimulacroService()
    try:
        while session.world.t < 7:
            session.tick()
        drill.start(session, n=n, seed=seed)
        while not session.world.done():
            session.tick()
            for action in session.state()['approvals']:
                if session.world.t >= 9:
                    session.approve(action['id'], True, 'EVACUAR · ensayo simulado N=1', by='operador-simulado')
        session.receipts.wait()
        drill.join(60)
        report = evidence(session)
        report.pop('session_id', None)
        sim = drill.status()
        sim.pop('session_id', None)
        return {'case': 'demo-1', 'N_sessions': 1, 'snapshot_t': 7, **report, 'simulacro': sim}
    finally:
        drill.close()
        session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--n', type=int, choices=(50, 200, 500), default=200)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    result = run(args.n, args.seed)
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    if args.out:
        args.out.write_text(text + '\n', encoding='utf-8')
    sim = result['simulacro']
    print(json.dumps({'case': result['case'], 'recibos': result['recibos'], 'coordinacion': result['coordinacion'],
                      'simulacro': {k: sim.get(k) for k in ('N', 'requested_N', 'failures', 'errors', 'elapsed_s', 'cpu_s', 'weaknesses', 'code')}},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
