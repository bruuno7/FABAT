"""Regresiones de la revisión independiente: público, operador y concurrencia."""
import os
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from motor.server.app import create_app


class PublicDemoTest(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {
            'MANDO_PUBLIC_URL': 'https://demo.invalid',
            'MANDO_OPERATOR_TOKEN': 'test-operator',
            'TELEGRAM_MODE': 'off', 'HR_HOOK_INTAKE': '',
            'MANDO_PUBLIC_RATE_MAX': '1000',
        })
        env.start()
        self.addCleanup(env.stop)
        self.app = create_app('demo-1', threaded=False, playbook='seed', local_params=False)
        self.s = self.app.state.session
        self.c = TestClient(self.app, raise_server_exceptions=False)
        self.op = {'X-Mando-Operator': 'test-operator'}
        self.addCleanup(self.s.close)
        self.addCleanup(self.app.state.chat.stop)
        self.addCleanup(lambda: self.app.state.duel and self.app.state.duel.close())

    def test_01_public_strikes_are_presets_with_budget(self):
        before = self.s.world.truth()
        for payload in (
            {'effect': {'kind': 'zone_inflow', 'zone': 'front_pit', 'per_min': 5000, 'n': 180}},
            {'preset': 'no_answer', 'n': 180},
            {'preset': 'no_answer', 'resource': 'amb_1'},
            {'preset': 'no_answer', 'channel': 'voice'},
        ):
            with self.subTest(payload=payload):
                self.assertIn(self.c.post('/api/strike', json=payload).status_code, (401, 403))
                self.assertEqual(self.s.world.truth(), before)
        for _ in range(3):
            self.assertEqual(self.c.post('/api/strike', json={'preset': 'no_answer'}).status_code, 200)
        self.assertEqual(self.c.post('/api/strike', json={'preset': 'no_answer'}).status_code, 429)
        self.assertEqual(self.c.post('/api/strike', headers=self.op, json={
            'origin': 'chaos', 'effect': {'kind': 'weather', 'rain': True}}).status_code, 200)

    def test_02_report_capability_is_required_and_not_in_state(self):
        out = self.c.post('/api/report', json={'text': 'algo ocurre'}).json()
        ref = out['report_id']
        self.assertNotEqual(ref, 'j-001')
        self.assertEqual(out['report_refs'], {ref: 'j-001'})
        self.assertNotIn(ref, self.c.get('/api/state').text)
        self.assertEqual(self.c.get('/api/report/j-001').status_code, 404)
        self.assertEqual(self.c.post('/api/report/j-001/answer', json={'text': 'falso'}).status_code, 404)
        self.assertEqual(self.c.get('/api/report/' + ref).status_code, 200)
        self.assertEqual(self.c.get('/api/report/' + ref).json()['report_id'], ref)
        self.assertEqual(self.c.post('/api/report/' + ref + '/answer', json={'text': 'aquí'}).status_code, 409)
        self.assertEqual(self.c.get('/api/report/j-001', headers=self.op).status_code, 200)

    def test_02_owner_can_answer_and_reset_invalidates_capability(self):
        from motor.contracts import Action, ActionKind
        ref = self.c.post('/api/report', json={'text': 'algo ocurre'}).json()['report_id']
        self.c.get('/api/report/' + ref)
        self.s.comms.send(Action('question', ActionKind.ASK, 0,
                                params={'reports': ['j-001'], 'message': '¿Dónde?'}))
        self.assertEqual(self.c.get('/api/report/' + ref).json()['ask']['question'], '¿Dónde?')
        self.assertEqual(self.c.post('/api/report/' + ref + '/answer', json={'text': 'En restauración'}).status_code, 200)
        self.assertEqual(self.s.comms.poll(0)[0]['result'], 'answer')
        self.assertEqual(self.c.post('/api/session', headers=self.op, json={'case_id': 'demo-1'}).status_code, 200)
        self.addCleanup(self.app.state.session.close)
        self.assertEqual(self.c.get('/api/report/' + ref).status_code, 404)

    def test_02_reserved_status_is_neutral_before_and_after_tick(self):
        ref = self.c.post('/api/report', json={'text': 'Una menor perdida en los baños', 'zone': 'toilets'}).json()['report_id']
        for _ in range(2):
            status = self.c.get('/api/report/' + ref).json()
            self.assertIsNone(status.get('safety'))
            self.assertIsNone(status.get('ask'))
            self.s.tick()

    def test_02_chat_report_refs_allow_only_own_status(self):
        with patch('motor.server.chat.load_intake', return_value=None):
            out = self.c.post('/api/chat', json={'text': 'humo en restauración'}).json()
        self.assertTrue(out['report_id'])
        self.assertNotEqual(out['report_id'], 'j-001')
        self.assertEqual(self.c.get('/api/report/' + out['report_id']).status_code, 200)
        self.assertEqual(out['reports'], [out['report_id']])
        self.assertEqual(out['report_refs'], {out['report_id']: 'j-001'})

    def test_01_gate_selector_only_accepts_the_three_predefined_gates(self):
        for gate in ('gate_a', 'gate_b', 'gate_c'):
            response = self.c.post('/api/strike', json={'preset': 'close_gate', 'zone': gate})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['strike']['effect']['zone'], gate)
        self.assertIn(self.c.post('/api/strike', json={'preset': 'close_gate', 'zone': 'front_pit'}).status_code, (401, 403))
        self.assertIn(self.c.post('/api/strike', json={'preset': 'food_blackout', 'zone': 'gate_a'}).status_code, (401, 403))

    def test_03_web_cannot_write_or_read_telegram_conversation(self):
        hub = self.app.state.chat
        with patch('motor.server.chat.load_intake', return_value=None):
            out = hub.turn('tg-telegram:1', 'algo ocurre', channel='telegram')
        hub._event(hub.chats[out['session_id']], 'ask', 'pregunta privada')
        before = len(self.s.world.reports)
        self.assertEqual(self.c.post('/api/chat', json={
            'session_id': 'tg-telegram:1', 'text': 'mensaje inyectado'}).status_code, 403)
        self.assertEqual(len(self.s.world.reports), before)
        self.assertEqual(self.c.get('/api/chat/tg-telegram:1/events?limit=1').status_code, 403)
        self.assertEqual(self.c.post('/api/chat', json={'session_id': 'tg-nueva', 'text': 'crear'}).status_code, 403)

    def webcall(self):
        from motor.contracts import Action, ActionKind
        comms = self.s.comms
        comms.mode = 'happyrobot'
        comms.voice_mode = 'web_call'
        comms.api_base = 'https://example.invalid'
        comms.workflows['webcall'] = 'test-workflow'
        comms.contacts = {'resources': {'med_1': {'web_call': True}}, 'roles': {}}
        action = Action('web-probe', ActionKind.DISPATCH, 0, resource='med_1', zone='food')
        with patch.dict(os.environ, {'HR_API_KEY': 'only-test'}):
            comms.send(action, self.s.world.resources['med_1'])
        return comms, next(iter(comms.webcalls))

    def test_04_concurrent_pickup_launches_only_one_call(self):
        comms, call_id = self.webcall()
        entered, release = threading.Event(), threading.Event()
        launches = []
        def api(*args):
            launches.append(args)
            entered.set()
            release.wait(2)
            return {'url': 'mock://livekit', 'token': 'test-token'}
        def answer():
            try:
                return comms.answer_webcall(call_id)
            except RuntimeError:
                return None
        with patch.object(comms, '_api', side_effect=api), ThreadPoolExecutor(2) as pool:
            first = pool.submit(answer)
            self.assertTrue(entered.wait(2))
            second = pool.submit(answer)
            try:
                second_result = second.result(timeout=3)
            finally:
                release.set()
            self.assertIsNone(second_result)
            self.assertEqual(first.result()['token'], 'test-token')
            self.assertIsNone(answer())
        self.assertEqual(len(launches), 1)

    def test_05_webcall_allows_scanning_and_conversation_then_expires(self):
        with patch('motor.server.comms_happyrobot.time.monotonic', return_value=100):
            comms, call_id = self.webcall()
        with patch('motor.server.comms_happyrobot.time.monotonic', return_value=130):
            comms.sweep()
            self.assertFalse(comms.calls['web-probe']['fell_back'])
            with patch.object(comms, '_api', return_value={'token': 'test-token'}):
                comms.answer_webcall(call_id)
        with patch('motor.server.comms_happyrobot.time.monotonic', return_value=160):
            comms.sweep()
            self.assertFalse(comms.calls['web-probe']['fell_back'])
        with patch('motor.server.comms_happyrobot.time.monotonic', return_value=176):
            comms.sweep()
            self.assertTrue(comms.calls['web-probe']['fell_back'])

    def test_05_unanswered_webcall_expires_after_pickup_window(self):
        with patch('motor.server.comms_happyrobot.time.monotonic', return_value=100):
            comms, _ = self.webcall()
        with patch('motor.server.comms_happyrobot.time.monotonic', return_value=174):
            comms.sweep()
            self.assertFalse(comms.calls['web-probe']['fell_back'])
        with patch('motor.server.comms_happyrobot.time.monotonic', return_value=176):
            comms.sweep()
            self.assertTrue(comms.calls['web-probe']['fell_back'])

    def test_06_chaos_rollouts_require_operator(self):
        self.assertEqual(self.c.get('/api/chaos/suggest').status_code, 401)
        result = self.c.get('/api/chaos/suggest', headers=self.op)
        self.assertEqual(result.status_code, 200)
        self.assertIsInstance(result.json()['suggestions'], list)
        self.assertEqual(self.c.get('/caos', headers=self.op).status_code, 200)

    def test_07_duel_gets_cannot_change_baseline_or_reset_time(self):
        self.assertEqual(self.c.post('/api/duel/session', headers=self.op, json={'baseline': 'reroute'}).status_code, 200)
        duel = self.app.state.duel
        duel.tick()
        for path in ('/api/duel/state?baseline=fixed', '/duelo?baseline=fixed'):
            with self.subTest(path=path):
                self.assertEqual(self.c.get(path).status_code, 200)
                self.assertIs(self.app.state.duel, duel)
                self.assertEqual(duel.right.world.t, 1)
        self.assertEqual(self.c.post('/api/duel/session', json={'baseline': 'fixed'}).status_code, 401)
        self.assertEqual(self.c.post('/api/duel/session', headers=self.op, json={'baseline': 'fixed'}).status_code, 200)
        self.assertEqual(self.app.state.duel.baseline, 'fixed')

    def test_08_proxy_budget_is_per_phone_only_when_proxy_is_trusted(self):
        from motor.server.test_security import make_app
        for public, peer in (('https://demo.invalid', '192.0.2.1'), ('', '127.0.0.1'), ('', '::1')):
            for header in ('CF-Connecting-IP', 'X-Forwarded-For'):
                with self.subTest(public=public, peer=peer, header=header), patch.dict(os.environ, {
                    'MANDO_PUBLIC_URL': public, 'MANDO_PUBLIC_RATE_MAX': '1'}):
                    c = TestClient(make_app(), client=(peer, 1))
                    for ip in ('198.51.100.1', '198.51.100.2'):
                        value = ip + ', 127.0.0.1' if header == 'X-Forwarded-For' else ip
                        self.assertEqual(c.post('/api/chat', json={'text': 'hola'}, headers={header: value}).status_code, 200)
                    self.assertEqual(c.post('/api/chat', json={'text': 'otra'}, headers={header: value}).status_code, 429)
        with patch.dict(os.environ, {'MANDO_PUBLIC_URL': '', 'MANDO_PUBLIC_RATE_MAX': '1'}):
            c = TestClient(make_app(), client=('192.0.2.1', 1))
            self.assertEqual(c.post('/api/chat', json={}, headers={'CF-Connecting-IP': '198.51.100.1'}).status_code, 200)
            self.assertEqual(c.post('/api/chat', json={}, headers={'CF-Connecting-IP': '198.51.100.2', 'X-Forwarded-For': '198.51.100.3'}).status_code, 429)

    def test_09_slow_intake_does_not_block_other_telegram_chats(self):
        from motor.server.telegram_bot import TelegramBot
        bot = TelegramBot('test-token', get_session=lambda: self.s,
                          submit_report=self.app.state.submit_report, submit_strike=None, strike_presets={})
        bot.mode, bot.status = 'poll', 'on'
        bot.chat_hub = self.app.state.chat
        slow, release, fast = threading.Event(), threading.Event(), threading.Event()
        delivered = []
        def understand(text, *args):
            if text == 'lento':
                slow.set()
                release.wait(3)
            return None
        updates = [{'update_id': 1, 'message': {'chat': {'id': 1}, 'text': 'lento'}},
                   {'update_id': 2, 'message': {'chat': {'id': 2}, 'text': 'humo en restauración'}}]
        def api(method, payload=None, **kwargs):
            if method == 'getUpdates':
                if updates:
                    batch = list(updates)
                    updates.clear()
                    return batch
                bot._stop.wait(.02)
                return []
            if method == 'sendMessage':
                delivered.append(payload)
                if payload['chat_id'] == 2:
                    fast.set()
            return {}
        with patch.object(bot, '_call', side_effect=api), patch.object(bot.chat_hub, 'understand', side_effect=understand):
            thread = threading.Thread(target=bot._poll_loop)
            thread.start()
            try:
                self.assertTrue(slow.wait(2))
                self.assertTrue(fast.wait(1), 'el segundo chat debe recibir respuesta mientras el primero espera')
                self.assertFalse(release.is_set())
            finally:
                release.set()
                bot.stop()
                thread.join(3)
        self.assertTrue(any(m['chat_id'] == 2 for m in delivered))

    def test_10_malformed_public_fields_are_422_and_clock_and_sse_survive(self):
        for path, fields in (('/api/report', ('zone', 'preset')),
                             ('/api/chat', ('zone_hint', 'preset')),
                             ('/api/strike', ('preset',))):
            for field in fields:
                for value in ([], {}, 7, True):
                    with self.subTest(path=path, field=field, value=value):
                        payload = {'text': 'humo', field: value}
                        self.assertEqual(self.c.post(path, json=payload).status_code, 422)
        self.assertEqual(len(self.s.world.reports), 0)
        self.s.tick()
        self.assertEqual(self.s.world.t, 1)
        response = self.c.get('/api/stream?limit=1')
        self.assertEqual(response.status_code, 200)
        self.assertIn('event: state', response.text)
