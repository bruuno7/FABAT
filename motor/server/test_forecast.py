"""Regresión de previsiones: el futuro del caso nunca entra en el gemelo."""
import copy
import time
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from motor.world import World
from motor.server.forecast import forecast, ForecastTracker, ForecastService, measurements


def world():
    return World.from_case({'id': 'forecast-test', 'seed': 73, 'duration_min': 90,
                           'initial': {'spontaneous': False}, 'events': []})


class ForecastTests(unittest.TestCase):
    def test_deterministic_and_no_mutation(self):
        w = world()
        w.flags[w.L.idx['water_n']]['water_l'] = 1
        before = copy.deepcopy(w.__dict__)
        a = forecast(w)
        self.assertTrue(any(p['metric'] == 'water_l' for p in a))
        self.assertEqual(a, forecast(w))
        self.assertEqual(w.rng.getstate(), before['rng'].getstate())
        for key in ('t', 'occ', 'flags', 'action_log', 'events', 'inflows', 'reports'):
            self.assertEqual(getattr(w, key), before[key])

    def test_no_future_leak(self):
        a = world()
        b = world()
        b.events = [{'t': 1, 'kind': 'zone_inflow', 'zone': 'gate_a', 'rate': 9000}]
        self.assertEqual(forecast(a), forecast(b))

    def test_lifecycle_and_deadline_not_sliding(self):
        w = world()
        w.flags[w.L.idx['water_n']]['water_l'] = 1
        tr = ForecastTracker()
        tr.update(w)
        p = next(x for x in tr.view(w.t) if x['metric'] == 'water_l')
        deadline = p['due_t']
        w.step()
        tr.update(w)
        q = next(x for x in tr.view(w.t) if x['id'] == p['id'])
        self.assertEqual(q['status'], 'CUMPLIDO')
        self.assertEqual(q['due_t'], deadline)

    def test_avoided_requires_intervention_and_deadline(self):
        for intervention, expected in (([], 'NO_CUMPLIDO'),
                                       ([{'id': 'P1', 't': 1, 'zone': 'water_n', 'metric': 'water_l'}], 'EVITADO')):
            w = world()
            tr = ForecastTracker()
            prediction = {'id': 'water_l:water_n:0', 'zone': 'water_n', 'resource': None,
                          'metric': 'water_l', 'current': 1, 'predicted': 0, 'threshold': 0,
                          'eta_min': 3, 'severity': 'atencion'}
            tr.ingest([prediction], 0)
            w.t = 1
            tr.observe(w, intervention)
            self.assertEqual(tr.view(1)[0]['status'], 'PREVISTO')
            w.t = 15
            tr.observe(w, intervention)
            self.assertEqual(tr.view(15)[0]['status'], expected)

    def test_both_density_thresholds_are_separate_stable_risks(self):
        w = world()
        w.inject({'kind': 'zone_inflow', 'zone': 'gate_a', 'per_min': 1000})
        predictions = [p for p in forecast(w) if p['zone']=='gate_a' and p['metric']=='density']
        self.assertEqual({p['threshold'] for p in predictions}, {4, 5})
        self.assertEqual({p['id'] for p in predictions}, {'density:gate_a:4', 'density:gate_a:5'})
        self.assertTrue(all(p['current'] < p['threshold'] <= p['predicted'] for p in predictions))
        tracker = ForecastTracker()
        tracker.ingest(predictions, w.t)
        for _ in range(15):
            w.step()
            tracker.observe(w)
        observed = tracker.view(w.t)
        self.assertEqual({p['threshold'] for p in observed}, {4, 5})
        self.assertTrue(all(p['status'] == 'CUMPLIDO' for p in observed))

    def test_resource_exhaustion(self):
        w = world()
        for r in w.resources.values():
            if str(r.kind) == 'ambulance':
                r.shift_ends = 2
        self.assertTrue(any(p['metric'] == 'free_units' and p['resource'] == 'ambulance'
                            and p['eta_min'] == 2 for p in forecast(w)))

    def test_frequency_and_cost(self):
        w = world()
        tr = ForecastTracker()
        with patch('motor.server.forecast.forecast', wraps=forecast) as fn:
            tr.update(w)
            for _ in range(2):
                w.step(); tr.update(w)
            self.assertEqual(fn.call_count, 1)
            w.step(); tr.update(w)
            self.assertEqual(fn.call_count, 2)
        self.assertGreaterEqual(tr.last_ms, 0)
        tr.record_cost(151)
        self.assertGreater(tr.interval, 3)
        start = time.perf_counter()
        forecast(w)
        self.assertLess(time.perf_counter() - start, 1.0)  # margen para CI; umbral adaptativo = 150 ms

    def test_worker_does_not_hold_clock_lock_while_forecasting(self):
        w = world()
        entered, release, rebuilt = threading.Event(), threading.Event(), threading.Event()
        s = SimpleNamespace(world=w, lock=threading.RLock(), state=lambda: {},
                            log=lambda *a: None, _rebuild=rebuilt.set)
        def slow(_):
            entered.set()
            release.wait(2)
            return []
        with patch('motor.server.forecast.forecast', slow):
            service = ForecastService(s)
            try:
                self.assertTrue(entered.wait(2))
                self.assertTrue(s.lock.acquire(timeout=.05))
                s.lock.release()
                release.set()
                self.assertTrue(rebuilt.wait(2))
            finally:
                release.set(); service.close(); service.thread.join(2)
        self.assertFalse(service.thread.is_alive())

    def test_worker_failure_is_visible_and_survives(self):
        w = world()
        rebuilt = threading.Event()
        logs = []
        s = SimpleNamespace(world=w, lock=threading.RLock(), state=lambda: {},
                            log=lambda *a: logs.append(a), _rebuild=rebuilt.set)
        with patch('motor.server.forecast.forecast', side_effect=ValueError('private detail')):
            service = ForecastService(s)
            try:
                self.assertTrue(rebuilt.wait(2))
                self.assertTrue(service.thread.is_alive())
                self.assertEqual(service.view(), [])
                self.assertIn('forecast_error', logs[0])
                self.assertNotIn('private detail', str(logs))
            finally:
                service.close(); service.thread.join(2)

    def test_late_crossing_is_not_prematurely_avoided(self):
        w = world()
        tr = ForecastTracker()
        p = {'id':'water_l:water_n:0','zone':'water_n','resource':None,'metric':'water_l',
             'current':1,'predicted':0,'threshold':0,'eta_min':1,'severity':'atencion'}
        tr.ingest([p], 0)
        w.t = 1
        tr.observe(w)
        self.assertEqual(tr.view(1)[0]['status'], 'PREVISTO')
        w.t = 2
        w.flags[w.L.idx['water_n']]['water_l'] = 0
        tr.observe(w)
        self.assertEqual(tr.view(2)[0]['status'], 'CUMPLIDO')

    def test_observation_gap_never_counts_as_avoided(self):
        w = world()
        tr = ForecastTracker()
        p = {'id':'water_l:water_n:0','zone':'water_n','resource':None,'metric':'water_l',
             'current':1,'predicted':0,'threshold':0,'eta_min':3,'severity':'atencion'}
        tr.ingest([p], 0)
        w.t = 1
        tr.observe(w, [{'id':'P1','t':1,'zone':'water_n','metric':'water_l'}])
        tr.record_gap(2)
        w.t = 15
        tr.observe(w)
        self.assertEqual(tr.view(15)[0]['status'], 'NO_VERIFICABLE')

    def test_execution_time_not_plan_creation_time(self):
        from motor.server.forecast import interventions
        w = world()
        observed = {}
        state = {'t':5,'plans':[{'id':'P1','t':0,'steps':[{'id':'A1','kind':'resupply','zone':'water_n','status':'executing'}]}]}
        self.assertEqual(interventions(state, observed)[0]['t'], 5)
        state['t'] = 9
        self.assertEqual(interventions(state, observed)[0]['t'], 5)

    def test_already_over_threshold_is_not_future(self):
        w = world()
        w.flags[w.L.idx['water_n']]['water_l'] = 0
        self.assertFalse(any(p['zone'] == 'water_n' and p['metric'] == 'water_l' for p in forecast(w)))


if __name__ == '__main__':
    unittest.main()
