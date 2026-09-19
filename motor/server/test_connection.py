"""Conexión real por configuración, probada sin servicios externos."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from .test_server import SECRET, Served, free_port, wait_for
from .mock_telegram import TOKEN, create_mock_telegram
from .mock_happyrobot import create_mock
import httpx


def _ledger_env(extra: dict | None = None) -> dict:
    """Ruta de ledger temporal: evita escribir en motor/server/data/ con clear=True."""
    env = dict(extra or {})
    if "MANDO_LEDGER_PATH" not in env:
        env["MANDO_LEDGER_PATH"] = str(Path(tempfile.mkdtemp()) / "ledger.sqlite")
    return env


class ConfigurationTest(unittest.TestCase):
    def test_ask_waits_for_person_text_in_final_callback(self):
        from .app import Session, load_case
        from motor.contracts import Action, ActionKind
        with patch.dict(os.environ, _ledger_env({'MANDO_VOICE_MODE': 'web_call', 'HR_API_KEY': 'fake'}), clear=True):
            s = Session(load_case('demo-1'), threaded=False, comms_mode='happyrobot')
            self.addCleanup(s.close)
            r = next(iter(s.world.resources.values()))
            s.comms.contacts = {'resources': {r.id: {'title': 'Responsable'}}, 'roles': {}}
            a = Action('ask-real', ActionKind.ASK, s.world.t, resource=r.id, zone='gate_b', params={'message': '¿Dónde está?'})
            s.comms.send(a, r)
            wire = s.comms.wire_payload(a.id)['action_id']
            s.comms.on_event({'type': 'dispatch_progress', 'action_id': wire, 'result': 'accept'})
            self.assertEqual(s.comms.poll(s.world.t), [], 'Aceptar escuchar no responde a la pregunta')
            s.comms.on_event({'type': 'dispatch_result', 'action_id': wire, 'result': 'accept',
                             'transcript': 'assistant: ¿Dónde?\nuser: Está en la puerta C'})
            reply = s.comms.poll(s.world.t)[0]
            self.assertEqual(reply['result'], 'answer')
            self.assertEqual(reply['text'], 'Está en la puerta C')
            self.assertEqual(reply['data'], {})

    def test_real_slugs_and_environment_urls(self):
        from . import hr_config
        with patch.dict(os.environ, {}, clear=True):
            urls = hr_config.workflow_urls()
            self.assertEqual(urls['dispatch'], 'https://platform.eu.happyrobot.ai/hooks/development/slug-despacho-telefono')
            self.assertEqual(urls['voice'], 'https://platform.eu.happyrobot.ai/deployments/development/slug-ingesta-voz')
            self.assertEqual(hr_config.workflow_ids()['chat'], 'slug-asistente-chat')
        with patch.dict(os.environ, {'HR_ENV': 'production', 'HR_PLATFORM_BASE': 'https://example.invalid',
                                    'HR_HOOK_INTAKE': 'http://localhost/custom'}, clear=True):
            urls = hr_config.workflow_urls()
            self.assertEqual(urls['webcall'], 'https://example.invalid/deployments/slug-despacho-webcall')
            self.assertEqual(urls['intake'], 'http://localhost/custom')

    def test_dispatch_ask_notify_use_real_trigger_shape_in_both_modes(self):
        from .app import Session, load_case
        from motor.contracts import Action, ActionKind
        from .comms_happyrobot import DISPATCH_PARAMS
        for mode in ('phone', 'web_call'):
            with self.subTest(mode=mode), patch.dict(os.environ, _ledger_env({
                'MANDO_VOICE_MODE': mode, 'HR_API_KEY': 'fake-key', 'HR_SECRET': SECRET,
                'HR_HOOK_DISPATCH': 'http://127.0.0.1:1/hook', 'MANDO_ALLOWED_NUMBERS': '+34600000002',
                # ASK/NOTIFY reales solo si se piden: por defecto en phone solo despacho (evita Runs basura).
                'MANDO_HR_PHONE_KINDS': 'dispatch,ask,notify',
                'MANDO_HR_MAX_INFLIGHT': '3'}), clear=True):
                s = Session(load_case('demo-1'), threaded=False, comms_mode='happyrobot')
                self.addCleanup(s.close)
                r = next(iter(s.world.resources.values()))
                s.comms.contacts = {'resources': {r.id: {'to_number': '+34600000002', 'title': 'Responsable'}}, 'roles': {}}
                with patch.object(s.comms, '_post'):
                    for kind in (ActionKind.DISPATCH, ActionKind.ASK, ActionKind.NOTIFY):
                        a = Action('test-' + str(kind), kind, s.world.t, resource=r.id, zone='gate_b',
                                   params={'message': 'Confirma la puerta B'})
                        s.comms.send(a, r)
                        self.assertTrue(s.comms.calls[a.id]['real'])
                        wire = s.comms.wire_payload(a.id)
                        self.assertEqual(set(wire), set(DISPATCH_PARAMS) - ({'to_number'} if mode == 'web_call' else set()))
                        if kind != ActionKind.DISPATCH:
                            self.assertEqual(wire['order_text'], 'Confirma la puerta B')
                        self.assertTrue(wire['callback_url'].endswith('/hr/events'))

    def test_phone_mode_only_dispatch_is_real_by_default_and_caps_inflight(self):
        from .app import Session, load_case
        from motor.contracts import Action, ActionKind
        with patch.dict(os.environ, _ledger_env({
            'MANDO_VOICE_MODE': 'phone', 'HR_API_KEY': 'fake-key', 'HR_SECRET': SECRET,
            'HR_HOOK_DISPATCH': 'http://127.0.0.1:1/hook', 'MANDO_ALLOWED_NUMBERS': '+34600000002',
            'MANDO_HR_MAX_INFLIGHT': '1'}), clear=True):
            s = Session(load_case('demo-1'), threaded=False, comms_mode='happyrobot')
            self.addCleanup(s.close)
            r = next(iter(s.world.resources.values()))
            s.comms.contacts = {'resources': {r.id: {'to_number': '+34600000002', 'title': 'Responsable'}}, 'roles': {}}
            with patch.object(s.comms, '_post') as post:
                ask = Action('ask-1', ActionKind.ASK, s.world.t, resource=r.id, zone='gate_b',
                             params={'message': '¿Confirmas?'})
                s.comms.send(ask, r)
                self.assertFalse(s.comms.calls[ask.id]['real'], 'ASK no debe marcar en phone por defecto')
                self.assertEqual(post.call_count, 0)
                d1 = Action('d1', ActionKind.DISPATCH, s.world.t, resource=r.id, zone='gate_b',
                            params={'message': 'Ve a B'})
                s.comms.send(d1, r)
                self.assertTrue(s.comms.calls[d1.id]['real'])
                self.assertEqual(post.call_count, 1)
                d2 = Action('d2', ActionKind.DISPATCH, s.world.t, resource=r.id, zone='gate_b',
                            params={'message': 'Ve a C'})
                s.comms.send(d2, r)
                self.assertFalse(s.comms.calls[d2.id]['real'], 'segundo despacho cae a sim con max_inflight=1')
                self.assertEqual(post.call_count, 1)


class TelegramBridgeTest(unittest.TestCase):
    def test_send_only_webhook_continues_poll_chat_without_getupdates(self):
        from .app import create_app
        fake, port = create_mock_telegram(), free_port()
        with patch.dict(os.environ, _ledger_env({'TELEGRAM_BOT_TOKEN': TOKEN, 'TELEGRAM_MODE': 'send_only',
                                    'TELEGRAM_API_BASE': f'http://127.0.0.1:{port}', 'HR_HOOK_INTAKE': ''}), clear=True), Served(fake, port):
            app = create_app(threaded=False, secret=SECRET)
            self.addCleanup(app.state.session.close)
            with TestClient(app) as client:
                bot = app.state.telegram
                self.assertTrue(wait_for(lambda: bot.status == 'on'))
                bot._handle({'message': {'chat': {'id': 42}, 'text': 'Hay una persona mareada en puerta B'}})
                chat = next(iter(app.state.chat.chats.values()))
                sid = chat['id']
                out = client.post('/hr/events', headers={'X-Mando-Token': SECRET}, json={
                    'type': 'public_report', 'channel': 'telegram', 'reply_to': '42', 'event_id': 'bridge-1',
                    'report': {'text': 'Sí, está despierta'}})
                self.assertEqual(out.status_code, 200, out.text)
                self.assertEqual(list(app.state.chat.chats), [sid])
                self.assertTrue(wait_for(lambda: len(fake.state.sent) >= 2))
                self.assertTrue(all(m['chat_id'] == 42 for m in fake.state.sent))
                duplicate = client.post('/hr/events', headers={'X-Mando-Token': SECRET}, json={
                    'type': 'public_report', 'channel': 'telegram', 'reply_to': '42', 'event_id': 'bridge-1',
                    'text': 'Sí'})
                self.assertTrue(duplicate.json()['duplicate'])
                self.assertNotIn('getUpdates', [m for m, _ in fake.state.calls])
                with patch.dict(os.environ, {'HR_CHAT_TOKEN': 'public-widget'}):
                    denied = client.post('/hr/events', headers={'X-Mando-Token': 'public-widget'}, json={
                        'type': 'public_report', 'channel': 'telegram', 'reply_to': '999', 'text': '/estado'})
                    self.assertEqual(denied.status_code, 403)
                structured = client.post('/hr/events', headers={'X-Mando-Token': SECRET}, json={
                    'type': 'public_report', 'channel': 'telegram', 'reply_to': '43', 'event_id': 'private-tg',
                    'report_ref': 'tg-private-ref', 'report': {'text': 'Hay una persona mareada', 'zone_hint': 'gate_c', 'lang': 'en'},
                    'extracted': {'sensitive': 'true', 'location': 'gate_c'}})
                self.assertEqual(structured.status_code, 200)
                self.assertIn('tg-private-ref', app.state.session.report_refs)
                self.assertTrue(app.state.session._report_meta[structured.json()['report_id']]['reserved'])

    def test_off_does_not_create_consumer(self):
        from .telegram_bot import start_from_env
        with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': TOKEN, 'TELEGRAM_MODE': 'off'}):
            self.assertIsNone(start_from_env())


class IntakePathsTest(unittest.TestCase):
    def test_every_free_text_turn_uses_text_workflow_and_tracks_result(self):
        from .app import create_app
        port, hr_port, tg_port = free_port(), free_port(), free_port()
        hr, tg = create_mock(delay_s=0.01, secret=SECRET), create_mock_telegram()
        with patch.dict(os.environ, _ledger_env({'HR_HOOK_INTAKE': f'http://127.0.0.1:{hr_port}/hooks/ingesta-texto',
                'MANDO_CALLBACK_URL': f'http://127.0.0.1:{port}', 'HR_SECRET': SECRET, 'HR_INTAKE_TIMEOUT_S': '1',
                'TELEGRAM_MODE': 'send_only', 'TELEGRAM_BOT_TOKEN': TOKEN, 'TELEGRAM_API_BASE': f'http://127.0.0.1:{tg_port}'}), clear=True), Served(hr, hr_port), Served(tg, tg_port):
            app = create_app(threaded=False, secret=SECRET, port=port)
            self.addCleanup(app.state.session.close)
            with Served(app, port):
                with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=5) as c:
                    c.post('/api/chat', json={'text': 'hola'})
                    c.post('/hr/events', headers={'X-Mando-Token': SECRET}, json={
                        'type': 'public_report', 'channel': 'telegram', 'reply_to': '42', 'event_id': 'tg-hi', 'text': 'hola'})
                    c.post('/api/report', json={'text': 'Una persona mareada en puerta B'})
                    self.assertEqual(len(hr.state.received), 3)
                    self.assertEqual({x['payload']['channel'] for x in hr.state.received}, {'web', 'telegram'})
                    status = c.get('/api/state').json()['happyrobot']['intake']
                    self.assertTrue(status['last_request'])
                    self.assertTrue(status['last_event'])
