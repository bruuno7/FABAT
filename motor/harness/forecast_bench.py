"""Evaluación de previsiones sobre heldout nuevo, sin agente y sin intervenir.

Una predicción por métrica/objetivo/umbral en cada ventana de 15 min (no se
cuentan las revisiones). Emparejamiento uno a uno con el primer cruce posterior
real dentro de la ventana. Se conservan los eventos futuros del mundo verdadero;
World.twin() los desconoce. IC 95 % por bootstrap de casos, no de ticks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
from pathlib import Path

from motor.cases import iter_cases
from motor.server.forecast import forecast, measurements, crossed
from motor.world import World


def evaluate_case(case, horizon=15, cadence=3):
    w = World.from_case(case)
    previous = measurements(w)
    predictions, events = [], []
    locked_until = {}
    censored = 0
    while not w.done():
        if w.t % cadence == 0:
            for p in forecast(w, horizon):
                if locked_until.get(p['id'], -1) > w.t:
                    continue
                if w.t + horizon > w.duration:
                    censored += 1
                    locked_until[p['id']] = w.t + horizon
                    continue
                predictions.append(dict(p, issued_t=w.t, end_t=w.t+horizon, matched_t=None))
                locked_until[p['id']] = w.t + horizon
        w.step()
        current = measurements(w)
        for key, m in current.items():
            if key in previous and not crossed(previous[key]) and crossed(m):
                events.append(dict(key=key, metric=m['metric'], t=w.t))
        previous = current
    # Both lists are chronological. Each crossing and prediction can count once.
    for event in events:
        match = next((p for p in predictions if p['id']==event['key'] and p['matched_t'] is None
                      and p['issued_t'] < event['t'] <= p['end_t']), None)
        if match is not None:
            match['matched_t'] = event['t']
    hits = [p for p in predictions if p['matched_t'] is not None]
    return {'case_id':case['id'], 'seed':case.get('seed'), 'predicted':len(predictions),
            'crossings':len(events), 'hits':len(hits), 'censored':censored,
            'leads':[p['matched_t']-p['issued_t'] for p in hits],
            'eta_absolute_errors':[abs(p['matched_t']-p['issued_t']-p['eta_min']) for p in hits],
            'by_metric':{m:{'predicted':sum(p['metric']==m for p in predictions),
                            'hits':sum(p['metric']==m for p in hits),
                            'crossings':sum(e['metric']==m for e in events)}
                         for m in ('density','water_l','route_blocked','free_units')}}


def aggregate(rows):
    predicted=sum(r['predicted'] for r in rows)
    crossings=sum(r['crossings'] for r in rows)
    hits=sum(r['hits'] for r in rows)
    lead=[v for r in rows for v in r['leads']]
    return {'precision': hits/predicted if predicted else None,
            'recall': hits/crossings if crossings else None,
            'median_lead_min':statistics.median(lead) if lead else None}


def summarize(rows, seed=20260919, bootstrap=2000):
    point=aggregate(rows)
    rng=random.Random(seed)
    samples={k:[] for k in point}
    for _ in range(bootstrap):
        result=aggregate([rows[rng.randrange(len(rows))] for _ in rows])
        for k,v in result.items():
            if v is not None:
                samples[k].append(v)
    metrics={}
    for k,values in samples.items():
        values.sort()
        metrics[k]={'value':point[k], 'ci95':[values[int(.025*(len(values)-1))],values[int(.975*(len(values)-1))]] if values else None}
    return {'n':len(rows), 'predictions':sum(r['predicted'] for r in rows),
            'actual_crossings':sum(r['crossings'] for r in rows), 'matched':sum(r['hits'] for r in rows),
            'censored_predictions':sum(r['censored'] for r in rows), 'metrics':metrics,
            'interval':'bootstrap por casos; percentiles 2,5 y 97,5; 2000 réplicas',
            'protocol':'Cruces ascendentes densidad ≥4 y ≥5, ruta sanitaria bloqueada; descendentes agua/unidades libres ≤0. '
                       'Cada umbral es un evento distinto. Predicciones cada 3 ticks; ventana 15 min; '
                       'una previsión por clave y ventana, un cruce por acierto. Precisión: cruce dentro de ventana, '
                       'no exactitud del minuto anunciado. Antelación: cruce real menos primera emisión. '
                       'Predicciones sin 15 min completos de seguimiento censuradas; todos los cruces reales cuentan en exhaustividad.',
            'limits':'Simulación: el gemelo conoce la dinámica del simulador. No valida sensores ni predicción de campo. '
                     'No conoce sucesos futuros ni incidentes espontáneos. Brazo sin agente y sin intervenciones. '
                     'No mide EVITADO ni demuestra que una intervención evitó un daño.',
            'by_metric':{m:{k:sum(r.get('by_metric',{}).get(m,{}).get(k,0) for r in rows)
                            for k in ('predicted','hits','crossings')}
                         for m in ('density','water_l','route_blocked','free_units')},
            'cases':rows}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--n',type=int,default=200)
    parser.add_argument('--seed',type=int,default=20260919)
    parser.add_argument('--offset',type=int,default=700000)
    parser.add_argument('--out',type=Path,default=Path('motor/harness/out/forecast.json'))
    args=parser.parse_args(argv)
    if args.n<1:
        parser.error('--n debe ser positivo')
    cases=list(iter_cases(seed=args.seed,split='heldout',start=args.offset,n=args.n))
    rows=[evaluate_case(c) for c in cases]
    result=summarize(rows,args.seed)
    result.update(split='heldout',seed=args.seed,offset=args.offset,horizon_min=15,cadence_ticks=3,
                  cases_sha256=hashlib.sha256(json.dumps(cases,sort_keys=True).encode()).hexdigest(),
                  code_sha256={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in
                               ('motor/world/world.py','motor/server/forecast.py','motor/harness/forecast_bench.py')})
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='cases'},ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
