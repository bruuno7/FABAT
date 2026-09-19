"""Previsión del gemelo, sin órdenes nuevas ni acceso a eventos futuros.

Las rutas vigiladas son ambulancia -> puestos médicos y salida sanitaria. EVITADO
significa umbral no observado en la ventana e intervención pertinente registrada;
la asociación al plan es temporal, no una prueba causal ni una cifra de precisión.
"""
from __future__ import annotations

import copy
import threading
import time
from collections import deque
from typing import Any

CRITICAL = ('medical', 'ambulance', 'security')


def measurements(world) -> dict[str, dict]:
    """Medidas observables; mismas definiciones para predicción y evaluación."""
    obs = world.observe()
    out = {}
    def put(metric, target, value, threshold, severity, zone=None, resource=None):
        key = f'{metric}:{target}:{threshold:g}'
        out[key] = dict(id=key, zone=zone, resource=resource, metric=metric,
                        current=value, threshold=threshold, severity=severity)
    for z in obs.zones.values():
        for threshold in (4.0, 5.0):
            put('density', z.id, z.density, threshold,
                'critico' if threshold == 5 else 'atencion', zone=z.id)
        if 'water_l' in z.flags:
            put('water_l', z.id, float(z.flags['water_l']), 0, 'atencion', zone=z.id)
    for kind in CRITICAL:
        members = [r for r in obs.resources.values() if str(r.kind) == kind]
        if members:
            put('free_units', kind, sum(str(r.status) == 'available' for r in members),
                0, 'critico', resource=kind)
    destinations = [z.id for z in obs.zones.values() if z.kind == 'medical' or z.id == 'exit_transport']
    for r in obs.resources.values():
        if str(r.kind) != 'ambulance' or str(r.status) == 'offline':
            continue
        for dest in destinations:
            # Use the actual simulator routing rule, not an invented density cutoff.
            blocked = world.travel_time(r.zone, dest, r.id) is None
            put('route_blocked', f'{r.id}>{dest}', int(blocked), 1, 'critico', zone=dest, resource=r.id)
    return out


def crossed(m: dict) -> bool:
    return m['current'] <= m['threshold'] if m['metric'] in ('water_l', 'free_units') else m['current'] >= m['threshold']


def forecast(world, horizon=15) -> list[dict]:
    """Función pura determinista. Primer cruce futuro por métrica/objetivo/umbral.

    Id estable mientras persiste el mismo riesgo; el tracker añade el episodio.
    horizon se acota a 60 minutos para impedir un coste accidental ilimitado.
    """
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= 60:
        raise ValueError('horizon debe ser un entero entre 1 y 60')
    initial = measurements(world)
    eligible = {key for key, m in initial.items() if not crossed(m)}
    twin = world.twin()
    predictions = []
    for eta in range(1, horizon + 1):
        twin.step()
        for key, m in measurements(twin).items():
            if key in eligible and crossed(m):
                predictions.append(dict(initial[key], predicted=m['current'], eta_min=eta,
                                        label='previsión del gemelo'))
                eligible.remove(key)
    return sorted(predictions, key=lambda p: (p['severity'] != 'critico', p['eta_min'], p['id']))


class ForecastTracker:
    """Plazos inmutables; observación cada tick, ensayo como máximo cada tres.

    El reloj de pared solo regula frecuencia: no afecta al resultado de forecast.
    Historial acotado (256 avisos, 64 observaciones) y generación sin solapamiento.
    """
    def __init__(self):
        self.items: dict[str, dict] = {}
        self.history = deque(maxlen=64)
        self.gaps = deque(maxlen=64)
        self.last_t = -10**9
        self.interval = 3
        self.last_ms = 0.0
        self.runs = 0

    def due(self, t):
        return t - self.last_t >= self.interval

    def record_cost(self, ms):
        self.last_ms = round(ms, 3)
        self.runs += 1
        if ms > 150:
            self.interval = min(24, self.interval * 2)

    def ingest(self, predictions, origin):
        for p in predictions:
            key = p['id']
            active = next((x for x in reversed(list(self.items.values()))
                           if x['key'] == key and x['status'] == 'PREVISTO'), None)
            if active:
                continue
            # No duplicates during the original horizon after an early crossing.
            if any(x['key'] == key and x['until_t'] > origin for x in self.items.values()):
                continue
            uid = f'{key}@{origin}'
            self.items[uid] = dict(p, id=uid, key=key, issued_t=origin, due_t=origin + p['eta_min'],
                                   until_t=origin + 15, status='PREVISTO', intervention=None,
                                   incomplete=any(origin < t <= origin + 15 for t in self.gaps))
        for t, values, interventions in self.history:
            self._resolve(t, values, interventions)
        while len(self.items) > 256:
            del self.items[next(iter(self.items))]

    def _resolve(self, t, values, interventions):
        for p in self.items.values():
            if p['status'] != 'PREVISTO' or t <= p['issued_t']:
                continue
            for action in interventions:
                if (p['issued_t'] < action.get('t', -1) <= t
                        and action.get('metric') == p['metric']
                        and ((p['zone'] and action.get('zone') == p['zone'])
                             or (p['metric'] == 'free_units' and action.get('resource') == p['resource']))):
                    p['intervention'] = dict(action)
            m = values.get(p['key'])
            if m is None:
                p['incomplete'] = True
            if t <= p['until_t'] and m is not None and crossed(m):
                p.update(status='CUMPLIDO', resolved_t=t, actual=m['current'])
            elif t >= p['until_t']:
                p.update(status='NO_VERIFICABLE' if p.get('incomplete') else 'EVITADO' if p['intervention'] else 'NO_CUMPLIDO', resolved_t=t,
                         attribution='temporal' if p['intervention'] else None)

    def record_gap(self, t):
        if t not in self.gaps:
            self.gaps.append(t)
        for p in self.items.values():
            if p['issued_t'] < t <= p['until_t']:
                p['incomplete'] = True

    def observe(self, world, interventions=()):
        values = measurements(world)
        frame = (world.t, values, list(interventions))
        if self.history and self.history[-1][0] == world.t:
            self.history[-1] = frame
        else:
            self.history.append(frame)
        self._resolve(*frame)

    def update(self, world, interventions=()):
        self.observe(world, interventions)
        if self.due(world.t):
            self.last_t = world.t
            start = time.perf_counter()
            self.ingest(forecast(world), world.t)
            self.record_cost((time.perf_counter() - start) * 1000)
        return self.view(world.t)

    def view(self, t):
        return [dict(copy.deepcopy(p), eta_min=max(0, p['due_t'] - t)) for p in self.items.values()]


def interventions(state, first_execution):
    """Solo pasos efectivamente ejecutados; no atribuir mérito a un plan propuesto."""
    result = []
    for p in state.get('plans', []):
        for a in p.get('steps', []):
            if a.get('status') not in ('executing', 'done'):
                continue
            action_id = a.get('id')
            if not action_id:
                continue
            executed_t = first_execution.setdefault(action_id, state.get('t', 0))
            kind = a.get('kind')
            metrics = {'reroute': ('density', 'route_blocked'), 'set_zone': ('density', 'route_blocked'),
                       'stop_show': ('density', 'route_blocked'), 'evacuate': ('density', 'route_blocked'),
                       'resupply': ('water_l',)}.get(kind, ())
            for metric in metrics:
                targets = [a.get('zone')] if a.get('zone') else [z['id'] for z in state.get('zones', [])]
                for zone in targets:
                    result.append({'id': p['id'], 't': executed_t, 'zone': zone, 'metric': metric})
    return result


class ForecastService:
    """Un trabajador por sesión; solo la copia del mundo necesita el cerrojo del reloj."""
    def __init__(self, session):
        self.session = session
        self.tracker = ForecastTracker()
        self.stop = threading.Event()
        self.error = None
        self.first_execution = {}
        self.thread = threading.Thread(target=self._loop, name='mando-forecast', daemon=True)
        self.thread.start()

    def observe(self):
        try:
            self.tracker.observe(self.session.world, interventions(self.session.state(), self.first_execution))
        except Exception as exc:
            self.tracker.record_gap(self.session.world.t)
            self._fail(exc)

    def view(self):
        return [] if self.error else self.tracker.view(self.session.world.t)

    def _fail(self, exc):
        name = type(exc).__name__
        if self.error != name:
            self.session.log('forecast_error', 'Previsión del gemelo no disponible: ' + name)
        self.error = name

    def _loop(self):
        while not self.stop.wait(.05):
            s = self.session
            try:
                with s.lock:
                    if not self.tracker.due(s.world.t):
                        continue
                    self.tracker.last_t = origin = s.world.t
                    start = time.perf_counter()
                    twin = s.world.twin()
                predictions = forecast(twin)
                elapsed = (time.perf_counter() - start) * 1000
                with s.lock:
                    if self.stop.is_set():
                        return
                    self.tracker.ingest(predictions, origin)
                    self.tracker.record_cost(elapsed)
                    self.error = None
                    s._rebuild()  # publica la misma instantánea en API y SSE, también en pausa
            except Exception as exc:
                with s.lock:
                    self._fail(exc)
                    s._rebuild()

    def close(self):
        self.stop.set()
