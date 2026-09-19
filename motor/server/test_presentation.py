"""Regresiones de recuperación y fallos externos durante la presentación."""
import json
import os
import threading
import asyncio
import time
import httpx
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from .app import create_app
from .test_server import SECRET
from .presentation import demo, channels


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': '', 'HR_HOOK_INTAKE': '', 'MANDO_PUBLIC_URL': ''}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.app = create_app('demo-1', threaded=False, secret=SECRET)
        self.client = TestClient(self.app)
        self.addCleanup(self.app.state.chat.stop)
        self.addCleanup(lambda: self.app.state.session.close())

    def test_reset_clears_calls_chats_and_strike_budget(self):
        self.client.post('/api/chat', json={'text': 'Una persona mareada en puerta B'})
        self.client.post('/api/strike', json={'preset': 'block_ambulance', 'client_id': 'jury'})
        old = self.app.state.session
        old.comms._inflight['fake-flight'] = {}
        old.comms.webcalls['old-link'] = {'action_id': 'fake-flight'}
        out = self.client.post('/api/control', json={'cmd': 'reset'})
        self.assertEqual(out.status_code, 200)
        self.assertEqual(old.comms._inflight, {})
        self.assertEqual(old.comms.webcalls, {})
        self.assertEqual(self.app.state.chat.chats, {})
        self.assertEqual(self.app.state.session.jury_left('jury'), 3)
        self.assertEqual(self.app.state.session.world.t, 0)

    def test_demo_runs_doctor_and_starts_paused_reproducible_case(self):
        with patch('motor.server.presentation.doctor.main') as check, patch('uvicorn.run') as serve, patch('builtins.print'):
            demo(['--case', 'demo-1', '--port', '8799'])
        check.assert_called_once_with(['--sin-red'])
        started = serve.call_args.args[0]
        self.addCleanup(started.state.chat.stop)
        self.addCleanup(started.state.session.close)
        self.assertEqual(started.state.session.world.t, 0)
        self.assertFalse(started.state.session.running)
        self.assertFalse(started.state.session.local_params)
        self.assertEqual(started.state.session.comms_mode, 'sim')

    def test_telegram_send_failure_is_visible(self):
        from unittest.mock import Mock
        telegram = Mock()
        telegram.view.return_value = {'status': 'on', 'error': 'sendMessage: ReadTimeout'}
        status = channels(self.app.state.session, telegram)
        self.assertEqual(status['telegram'], 'sin conexión')
        self.assertIn('Telegram sin conexión', status['banner'])

    def test_telegram_connection_retries_are_bounded(self):
        from .telegram_bot import TelegramBot
        bot = TelegramBot('fake', get_session=lambda: self.app.state.session,
                          submit_report=lambda **kw: {}, submit_strike=lambda **kw: {}, strike_presets={})
        self.addCleanup(bot.stop)
        with patch.object(bot, '_call', side_effect=httpx.ConnectError('offline')) as call, patch.object(bot._stop, 'wait'):
            bot._poll_loop()
        self.assertEqual(call.call_count, 5)
        self.assertEqual(bot.status, 'error')

    def test_sse_announces_reset_even_when_versions_match(self):
        endpoint = next(r.endpoint for r in self.app.routes if getattr(r, 'path', '') == '/api/stream')
        async def scenario():
            response = await endpoint(limit=2)
            first = await anext(response.body_iterator)
            old_version = self.app.state.session.version
            self.client.post('/api/control', json={'cmd': 'reset'})
            self.app.state.session.version = old_version
            second = await asyncio.wait_for(anext(response.body_iterator), 0.5)
            self.assertNotEqual(first, second)
            await response.body_iterator.aclose()
        asyncio.run(scenario())

    def test_report_waiting_for_network_cannot_enter_new_scene(self):
        started, release = threading.Event(), threading.Event()
        def slow(**kwargs):
            started.set()
            release.wait(2)
            return None, 'timeout'
        results = []
        with patch.dict(os.environ, {'HR_HOOK_INTAKE': 'http://127.0.0.1:1/mock'}), patch.object(self.app.state.intake, 'understand', side_effect=slow):
            t = threading.Thread(target=lambda: results.append(self.app.state.submit_report('whatsapp', 'hay humo en comida')))
            t.start()
            self.assertTrue(started.wait(1))
            self.client.post('/api/control', json={'cmd': 'reset'})
            release.set()
            t.join(2)
        self.assertFalse(t.is_alive())
        self.assertTrue(results[0].get('stale'))
        self.assertFalse(self.app.state.session._report_meta)

    def test_intake_failure_after_reset_does_not_submit_to_new_scene(self):
        started, release = threading.Event(), threading.Event()
        hub = self.app.state.chat
        turn = hub.turn(None, 'hola')
        c = hub.chats[turn['session_id']]
        def receive(text):
            started.set()
            release.wait(2)
            raise RuntimeError('mock intake failed')
        with patch.object(c['intake'], 'receive', side_effect=receive):
            worker = threading.Thread(target=lambda: hub.turn(c['id'], 'Una persona mareada en puerta B'))
            worker.start()
            self.assertTrue(started.wait(1))
            self.client.post('/api/control', json={'cmd': 'reset'})
            release.set()
            worker.join(2)
        self.assertFalse(self.app.state.session._report_meta)

    def test_tokens_do_not_enter_state_stream_or_logs(self):
        token = 'not-a-real-secret-mando-test'
        with patch.dict(os.environ, {'HR_API_KEY': token}):
            self.app.state.session.log('test', 'error ' + token, token=token)
            self.client.post('/api/report', json={'text': 'Una persona mareada en puerta B ' + token + ' +34600000002'})
            state = self.client.get('/api/state').text
            stream = self.client.get('/api/stream?limit=1').text
            logs = json.dumps(self.app.state.session.server_log)
        for output in (state, stream, logs):
            self.assertNotIn(token, output)
            self.assertNotIn('+34600000002', output)

    def test_key_moment_is_deterministic_paused_and_recovers_budget(self):
        states = []
        for _ in range(2):
            response = self.client.post('/api/control', json={'cmd': 'key_moment'})
            self.assertEqual(response.status_code, 200, response.text)
            s = self.app.state.session
            self.assertEqual(s.world.t, 7)
            self.assertEqual(s.jury_left(), 3)
            self.assertFalse(s.running)
            self.assertEqual(s.comms_mode, 'sim')
            states.append(s.world.observe().to_dict() if hasattr(s.world.observe(), 'to_dict') else s.world.truth())
        self.assertEqual(states[0], states[1])

    def test_slow_platform_does_not_freeze_state_or_sse(self):
        def slow(*args):
            time.sleep(0.6)
            raise httpx.ReadTimeout('mock network timeout')
        async def scenario():
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url='http://localhost', timeout=2) as c:
                request = asyncio.create_task(c.post('/api/call/fake/token', json={}))
                await asyncio.sleep(0.03)
                state = await c.get('/api/state')
                stream = await c.get('/api/stream?limit=1')
                self.assertFalse(request.done(), 'la petición externa bloqueó el bucle HTTP')
                self.assertEqual(state.status_code, 200)
                self.assertIn('event: state', stream.text)
                self.assertEqual((await request).status_code, 502)
        with patch.object(self.app.state.session.comms, 'takeover_token', side_effect=slow):
            asyncio.run(scenario())

    def test_public_operator_requires_token_even_on_loopback(self):
        with patch.dict(os.environ, {'MANDO_PUBLIC_URL': 'https://demo.invalid', 'MANDO_OPERATOR_TOKEN': 'operator-test',
                                    'MANDO_MCP_TOKEN': 'mcp-test'}):
            for path, body in [('/api/approve', {}), ('/api/control', {'cmd': 'step'}), ('/api/whatif/order', {})]:
                self.assertEqual(self.client.post(path, json=body).status_code, 401)
            self.assertEqual(self.client.get('/').status_code, 401)
            self.assertEqual(self.client.post('/mcp', json={}).status_code, 401)
            self.assertEqual(self.client.get('/', headers={'X-Mando-Operator': 'operator-test'}).status_code, 200)
            self.assertEqual(self.client.post('/api/control', json={'cmd': 'step'}, headers={'X-Mando-Operator': 'operator-test'}).status_code, 200)

    def test_public_size_limits_use_actual_body(self):
        for path in ('/api/chat', '/api/report', '/api/strike'):
            self.assertEqual(self.client.post(path, json={'text': 'x' * 401}).status_code, 413)
            self.assertEqual(self.client.post(path, content=b'x' * 9000).status_code, 413)
