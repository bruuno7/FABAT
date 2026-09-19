"""Integración API/SSE en memoria: no abre sockets ni llama a servicios externos."""
import json
import os
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from motor.server.app import create_app


class CentroIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'TELEGRAM_MODE':'off'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.app = create_app('demo-1', threaded=False, local_params=False, playbook='seed')
        self.s = self.app.state.session
        self.c = TestClient(self.app)
        self.addCleanup(self.s.close)
        self.addCleanup(self.app.state.chat.stop)

    def test_route_and_state_sse_share_forecasts(self):
        self.assertEqual(self.c.get('/centro').status_code, 200)
        state = self.c.get('/api/state').json()
        self.assertEqual(state['forecasts'], [])
        self.assertEqual(state['event_name'], 'Festival Abierto')
        raw = self.c.get('/api/stream?limit=1').text
        streamed = json.loads(next(line[6:] for line in raw.splitlines() if line.startswith('data: ')))
        self.assertEqual(streamed['forecasts'], state['forecasts'])
        self.assertIn('href="/centro"', self.c.get('/').text)

    def test_voice_health_recovers_on_simulator_clock(self):
        self.s.world.inject({'kind':'comms_down','channel':'voice','n':3})
        self.s._rebuild()
        health = self.c.get('/api/state').json()['service_health']['comms_down']
        self.assertEqual(health['voice'], self.s.world.t + 3)
        for _ in range(3):
            self.s.tick()
        state = self.c.get('/api/state').json()
        self.assertLessEqual(state['service_health']['comms_down'].get('voice', 0), state['t'])

    def test_key_moment_restarts_forecast_worker(self):
        self.app.state.threaded = True
        response = self.c.post('/api/control', json={'cmd': 'key_moment'})
        self.assertEqual(response.status_code, 200)
        new = self.app.state.session
        try:
            self.assertIsNotNone(new._forecast)
            self.assertTrue(new._forecast.thread.is_alive())
            self.assertEqual(new.world.t, 7)
            self.assertFalse(new.running)
        finally:
            new.close()
            if new._forecast is not None:
                new._forecast.thread.join(2)

    def test_background_prediction_published_and_worker_closes(self):
        from motor.server.forecast import ForecastService
        self.s.world.flags[self.s.world.L.idx['water_n']]['water_l'] = 1
        self.s._forecast = ForecastService(self.s)
        worker = self.s._forecast
        try:
            deadline = time.monotonic() + 2
            while not self.s.state().get('forecasts') and time.monotonic() < deadline:
                time.sleep(.01)
            state = self.c.get('/api/state').json()
            self.assertTrue(any(p['metric']=='water_l' for p in state['forecasts']))
            self.assertIsNone(state['engine_error'])
            streamed = self.c.get('/api/stream?limit=1').text
            self.assertIn('water_l', streamed)
        finally:
            self.s.close()
            worker.thread.join(2)
        self.assertFalse(worker.thread.is_alive())

    def test_failed_forecast_is_empty_logged_and_clock_survives(self):
        from motor.server.forecast import ForecastService
        with patch('motor.server.forecast.forecast', side_effect=ValueError('private detail')):
            self.s._forecast = ForecastService(self.s)
            worker = self.s._forecast
            try:
                deadline = time.monotonic() + 2
                while not any(e['kind']=='forecast_error' for e in self.s.server_log) and time.monotonic()<deadline:
                    time.sleep(.01)
                self.assertTrue(any(e['kind']=='forecast_error' for e in self.s.state()['log']))
                self.assertEqual(self.s.state()['forecasts'], [])
                self.assertTrue(worker.thread.is_alive())
                self.s.tick()
                self.assertEqual(self.s.world.t, 1)
                self.assertIsNone(self.s.state()['engine_error'])
            finally:
                self.s.close(); worker.thread.join(2)
