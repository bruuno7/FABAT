"""Regresiones del informe H1–H8, sin conexiones a servicios externos."""
import json
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from motor.server.app import create_app


class HardeningTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(threaded=False, secret="test-secret")
        self.s = self.app.state.session
        self.c = TestClient(self.app)
        self.addCleanup(self.s.close)
        self.addCleanup(self.app.state.chat.stop)

    def test_h1_invalid_effects_do_not_mutate_world(self):
        effects = [
            {"kind": "weather", "temp_c": ""},
            {"kind": "weather", "wind_kmh": -1},
            {"kind": "weather", "wind_kmh": 10 ** 400},
            {"kind": "comms_down", "channel": []},
            {"kind": "weather", "rain": "false"},
            {"kind": "zone_flag", "zone": "food", "flag": "water_l", "value": "bad"},
            {"kind": "zone_flag", "zone": "food", "flag": "power", "value": False, "flow_factor": "bad"},
            {"kind": "resource_offline", "resource": "amb_1", "n": []},
            {"kind": "zone_inflow", "zone": "gate_a", "per_min": 1e99},
            {"kind": "zone_state", "zone": "absent", "state": "closed"},
            {"kind": "transport_cut", "factor": -1},
            {"kind": "incident", "incident": {"severity": "bad"}},
        ]
        before = self.s.world.truth()
        for effect in effects:
            with self.subTest(effect=effect):
                response = self.c.post("/api/strike", json={"effect": effect})
                self.assertIn(response.status_code, (400, 422), response.text)
                self.assertEqual(self.s.world.truth(), before)
        self.s.tick()
        self.assertEqual(self.s.world.t, 1)

    def test_h1_clock_survives_tick_exception(self):
        reached = threading.Event()
        def broken():
            reached.set()
            raise RuntimeError("fallo de prueba")
        with patch.object(self.s.world, "step", broken):
            self.s.running = True
            thread = threading.Thread(target=self.s._loop, daemon=True)
            thread.start()
            self.assertTrue(reached.wait(2))
            time.sleep(.05)
            try:
                self.assertTrue(thread.is_alive())
                self.assertFalse(self.s.running)
                self.assertTrue(self.s.state().get("engine_error"))
            finally:
                self.s.close()
                thread.join(2)

    def test_h2_reserved_projection_before_tick_and_after_calls(self):
        self.c.post('/api/report', json={"text": "Una menor perdida en los baños. MARCADOR_PRIVADO +34600000999", "zone": "toilets"})
        for _ in range(3):
            raw = self.c.get('/api/state').text
            self.assertNotIn('MARCADOR_PRIVADO', raw)
            self.assertNotIn('600000999', raw)
            self.assertNotIn('MARCADOR_PRIVADO', self.c.get('/api/stream?limit=1').text)
            state = self.s.state()
            reserved = {i['id'] for i in state['incidents'] if i.get('reserved')}
            for call in state['calls']['calls']:
                if call.get('incident') in reserved:
                    self.assertIsNone(call.get('zone'))
            self.s.tick()
        self.s.log('action', 'Llámame al +34 600 000 999', data={'phone': '+34600000999'})
        self.s._rebuild()
        self.assertNotIn('600 000 999', self.s.state_json())
        self.assertNotIn('600000999', self.s.state_json())

    def test_h3_boolean_fields_are_strict(self):
        for path, payload in [('/api/approve', {'action_id': 'missing', 'ok': 'false'}),
                              ('/api/session', {'autoplay': 'false'}),
                              ('/api/duel/session', {'autoplay': 'false'}),
                              ('/api/memoria/decide', {'id': 'x', 'approve': 'false'}),
                              ('/api/call/x/token', {'takeover': 'false'})]:
            with self.subTest(path=path):
                self.assertEqual(self.c.post(path, json=payload).status_code, 422)
        self.assertFalse(self.s.approvals)

    def flight(self, aid='probe'):
        from motor.contracts import Action, ActionKind
        action = Action(aid, ActionKind.DISPATCH, 0, resource='sec_1', zone='gate_b')
        c = self.s.comms
        c.calls[aid] = {'action_id': aid, 'stage': 'llamando', 'zone': 'gate_b', 'resource': 'sec_1'}
        c._inflight[aid] = {'action': action, 'resource': self.s.world.resources['sec_1'],
                            'started': time.monotonic(), 'deadline': time.monotonic() + 60}
        return c

    def test_h4_invalid_callback_can_be_retried(self):
        c = self.flight()
        payload = {'message': 'dispatch_result', 'action_id': 'probe', 'event_id': 'bad', 'result': 'accept', 'data': 'bad'}
        response = TestClient(self.app, raise_server_exceptions=False).post('/hr/events', json=payload, headers={'X-Mando-Token': 'test-secret'})
        self.assertEqual(response.status_code, 422)
        self.assertIn('probe', c._inflight)
        self.assertNotIn('probe', c._closed)
        self.assertNotIn('bad', c._seen_events)
        payload['data'] = {}
        self.assertEqual(self.c.post('/hr/events', json=payload, headers={'X-Mando-Token': 'test-secret'}).json()['result'], 'accept')
        self.assertEqual(len(c.poll(0)), 1)

    def test_h4_report_validates_before_idempotency(self):
        for kind in ('message', 'type'):
            payload = {kind: 'public_report', 'event_id': kind, 'report': 'bad'}
            r = TestClient(self.app, raise_server_exceptions=False).post('/hr/events', json=payload, headers={'X-Mando-Token': 'test-secret'})
            self.assertEqual(r.status_code, 422)
            self.assertNotIn(kind, self.s.comms._seen_events)

    def test_h5_timeout_and_confirmation_finish_only_once(self):
        c = self.flight()
        entered, resume = threading.Event(), threading.Event()
        original = c._result_item
        def delayed(*args, **kwargs):
            entered.set()
            self.assertTrue(resume.wait(2))
            return original(*args, **kwargs)
        with patch.object(c, '_result_item', delayed):
            worker = threading.Thread(target=c._early_result, args=('probe', {'early_result': 'reject'}))
            worker.start()
            self.assertTrue(entered.wait(2))
            c._inflight['probe']['deadline'] = 0
            c.sweep()
            resume.set()
            worker.join(2)
        results = c.poll(20)
        self.assertEqual(len(results), 1, results)

    def test_h6_unknown_run_cannot_bind_current_action(self):
        c = self.flight('A-0001')
        out = c.on_event({'type': 'dispatch_result', 'action_id': 'A-0001', 'session_id': 'old',
                          'hr_run_id': 'old-run', 'result': 'reject'})
        self.assertTrue(out.get('stale'), out)
        self.assertNotIn('old-run', c._run_to_action)
        self.assertIn('A-0001', c._inflight)
        self.assertEqual(c.poll(0), [])

    def test_h6_outbound_ids_differ_between_sessions(self):
        from motor.server.comms_happyrobot import HappyRobotComms
        c = self.flight()
        d = HappyRobotComms(self.s.world, self.s.sim, session_id='different')
        for comms in (c, d):
            comms.payloads['probe'] = {'message': 'dispatch_request', 'action_id': 'probe'}
        self.assertNotEqual(c.wire_payload('probe')['action_id'], d.wire_payload('probe')['action_id'])

    def test_h7_callback_publishes_while_paused(self):
        self.flight()
        self.s._rebuild()
        version, tick = self.s.version, self.s.world.t
        self.c.post('/hr/events', json={'message': 'progress', 'action_id': 'probe', 'stage': 'call_answered'},
                    headers={'X-Mando-Token': 'test-secret'})
        self.assertGreater(self.s.version, version)
        self.assertEqual(self.s.world.t, tick)
        self.assertEqual(self.s.state()['calls']['calls'][0]['stage'], 'ha descolgado')

    def test_h8_rollout_rehearses_its_clone(self):
        from motor.caos.chaos import rollout
        from motor.mando import Mando
        from motor.world import SimComms, World
        from motor.server.app import load_case
        world = World.from_case(load_case('demo-gates'), 7)
        consulted = []
        original = World.twin
        def traced(w):
            consulted.append((w.t, w.observe().zones['gate_b'].state))
            return original(w)
        agent = Mando(comms=SimComms(world, 7), twin=lambda: world.twin())
        before = world.truth()
        with patch.object(World, 'twin', traced):
            rollout(world, agent, 10, {'kind': 'zone_state', 'zone': 'gate_b', 'state': 'closed'})
        self.assertTrue(consulted)
        self.assertTrue(all(t > 0 and state == 'closed' for t, state in consulted), consulted)
        self.assertEqual(world.truth(), before)

    def test_real_person_asks_exclude_staff_and_never_simulate_answer(self):
        from motor.contracts import Action, ActionKind
        with patch('motor.server.chat.load_intake', return_value=None):
            out = self.app.state.chat.turn(None, 'Hay algo raro', zone_hint='food')
        rid = out['report_id']
        staff = Action('staff', ActionKind.ASK, 0, params={'purpose': 'sitrep', 'to': 'sec_1', 'reports': [rid], 'message': '¿Qué os encontráis?'})
        self.assertEqual(self.app.state.chat.route_ask(self.s, staff), '')

    def test_real_person_timeout_never_simulates_answer(self):
        from motor.contracts import Action, ActionKind
        with patch('motor.server.chat.load_intake', return_value=None):
            out = self.app.state.chat.turn(None, 'Hay algo raro', zone_hint='food')
        rid = out['report_id']
        ask = Action('person', ActionKind.ASK, 0, params={'purpose': 'detail', 'reports': [rid], 'message': '¿Qué pasa?'})
        self.s.comms.send(ask)
        self.assertEqual(self.s.comms.poll(100), [])
        self.s.comms._inflight['person']['deadline'] = 0
        self.s.comms.sweep()
        results = self.s.comms.poll(100)
        self.assertEqual([r['result'] for r in results], ['no_answer'])
        self.assertNotIn('aquí no pasa nada', json.dumps(results, ensure_ascii=False))

    def test_real_person_disconnected_still_waits_real_deadline(self):
        from motor.contracts import Action, ActionKind
        rid = self.s.report('whatsapp', 'algo ocurre', source='asistente', via='web')['report_id']
        ask = Action('person', ActionKind.ASK, 0, params={'reports': [rid], 'message': '¿Dónde?'})
        self.s.comms.send(ask)
        self.assertIn('person', self.s.comms._inflight)
        self.assertEqual(self.s.comms.poll(100), [])

    def test_chat_uses_real_intake_and_app_contract(self):
        from motor.intake import IntakeSession
        first = self.c.post('/api/chat', json={'text': 'A person collapsed and is not responding', 'zone_hint': 'gate_b',
                                              'lang': 'en', 'source': 'Alex', 'client_id': 'person-1', 'preset': 'collapse'}).json()
        self.assertFalse(first['degraded'])
        self.assertIsInstance(self.app.state.chat.chats[first['session_id']]['intake'], IntakeSession)
        self.assertIsInstance(first['state']['slots'], list)
        self.assertTrue(all({'id', 'label', 'value', 'confidence'} <= set(x) for x in first['state']['slots']))
        self.assertEqual(first['quick_replies'], ['Yes', 'No', "I don't know"])
        self.assertEqual(set(first['instruction']) & {'id', 'title', 'steps', 'metronome'}, {'id', 'title', 'steps', 'metronome'})
        rep = next(r for r in self.s.world.reports if r.id == first['report_id'])
        self.assertEqual(rep.source, 'Alex')
        self.assertNotIn('¿', first['say'])
        self.assertEqual(self.app.state.chat.chats[first['session_id']]['client_id'], 'person-1')

    def test_chat_degraded_english_and_instruction_shape(self):
        with patch('motor.server.chat.load_intake', return_value=None):
            out = self.c.post('/api/chat', json={'text': 'There is smoke', 'lang': 'en', 'preset': 'smoke', 'source': 'Sam'}).json()
        self.assertIn('control', out['say'])
        self.assertIsInstance(out['state']['slots'], list)
        self.assertIn('quick_replies', out)

    def test_strikes_have_person_budget_and_stable_consequences(self):
        for _ in range(3):
            out = self.c.post('/api/strike', json={'preset': 'storm', 'client_id': 'alice'}).json()
        self.assertEqual(out['left'], 0)
        strike = out['strike']
        self.assertIn('id', strike)
        self.assertTrue({'broken', 'new_plans', 'locked_test'} <= set(strike))
        self.assertEqual(self.c.get('/api/jury?client_id=alice').json()['left'], 0)
        self.assertEqual(self.c.get('/api/jury?client_id=bob').json()['left'], 3)
        self.assertEqual(self.c.post('/api/strike', json={'preset': 'storm', 'client_id': 'bob'}).status_code, 429)
        self.assertEqual(self.s.state()['scoreboard']['left'], 0)
        with patch('motor.server.regression_live.lock', return_value={'n': 99, 'author': 'Alice'}):
            self.s.strikes[-1]['outcome'] = 'failed'
            self.s.lock_as_test('Alice')
        self.assertEqual(self.s.strikes[-1]['locked_test'], 99)

    def test_duel_reroute_default_and_labels_use_real_figures(self):
        from motor.baseline import BaselineReroute
        self.c.get('/duelo?baseline=reroute')
        st = self.c.get('/api/duel/state').json()
        self.assertIsInstance(self.app.state.duel.left.agent, BaselineReroute)
        self.assertEqual(st['session']['baseline'], 'reroute')
        for side in ('left', 'right'):
            self.assertIn('peak_zone', st[side])
            self.assertIn('reroutes', st[side])
            self.assertEqual(st[side]['n'], 1)
        self.assertEqual(self.c.get('/duelo?baseline=unknown').status_code, 200)
        self.assertEqual(self.c.get('/api/duel/state').json()['session']['baseline'], 'reroute')
        self.assertEqual(self.c.post('/api/duel/session', json={'baseline': 'unknown'}).status_code, 422)
        self.app.state.duel.close()

    def test_memory_real_observations_and_paired_comparison(self):
        out = self.c.get('/api/memoria').json()
        self.assertTrue(out['observations'])
        self.assertTrue(out['comparison']['rows'])
        rows = out['comparison']['rows']
        self.assertTrue(any(r.get('split') == 'heldout' for r in rows))
        self.assertTrue(all(r.get('n') is not None and r.get('ci') is not None for r in rows))
        self.assertIn('initial', out['comparison']['params'])

    def test_memory_decision_uses_tuning_and_next_session_loads_it(self):
        from pathlib import Path
        from motor.server import memoria
        decision = Path('motor/server/test-decisions.local.json')
        approved = Path('motor/server/test-approved.local.json')
        self.addCleanup(lambda: decision.unlink(missing_ok=True))
        self.addCleanup(lambda: approved.unlink(missing_ok=True))
        with patch.object(memoria, 'DECISIONS_PATH', decision), patch.object(memoria, 'LOCAL_APPROVED_PATH', approved, create=True):
            response = self.c.post('/api/memoria/decide', json={'id': 'C-01', 'approve': True, 'by': 'Ana'}).json()
            self.assertTrue(response['applied_to_mando'])
            self.assertEqual(json.loads(approved.read_text())['values']['resupply_lead_min']['water_n'], 32)
            self.c.post('/api/session', json={})
            self.assertEqual(self.app.state.session.agent.params.lead('water_n'), (32, True))
            self.app.state.session.close()
            self.c.post('/api/memoria/decide', json={'id': 'C-01', 'approve': False, 'by': 'Ana'})
            self.assertNotIn('water_n', json.loads(approved.read_text())['values'].get('resupply_lead_min', {}))

    def test_h2_server_log_adapter_and_resource_references_are_masked(self):
        rid = self.s.report('whatsapp', 'Una menor perdida MARCADOR_PRIVADO', 'toilets')['report_id']
        self.assertNotIn('MARCADOR_PRIVADO', json.dumps(self.s.server_log))
        self.s.tick()
        self.s.tick()
        inc = next(i for i in self.s.agent.snapshot()['incidents'] if rid in i['reports'])
        for call in self.s.comms.calls.values():
            if call.get('incident') == inc['id']:
                self.s.comms._say(call['action_id'], 'user', 'MARCADOR_PRIVADO en toilets +34600000999')
        self.assertNotIn('MARCADOR_PRIVADO', json.dumps(self.s.comms.view()))
        self.s._rebuild()
        for action in self.s.state()['actions']:
            if action.get('incident') == inc['id']:
                self.assertIsNone(action.get('zone'))
        self.assertNotIn('MARCADOR_PRIVADO', json.dumps(self.s.informe()))

    def test_real_report_does_not_expire_by_simulated_minutes(self):
        rid = self.s.report('whatsapp', 'Creo que hay algo raro', source='asistente', via='web')['report_id']
        for _ in range(14):
            self.s.tick()
        inc = next(i for i in self.s.agent.incidents.values() if rid in i.reports)
        self.assertNotEqual(str(inc.status), 'false_alarm')
        self.assertTrue(any(f.get('external') for f in self.s.comms._inflight.values()))

    def test_all_chaos_effects_are_accepted_without_corrupting_world(self):
        from motor.caos.chaos import catalogue
        from motor.server.validation import strike_effect
        self.s.world.t = 85
        effects = [c['effect'] for c in catalogue(self.s.world, self.s.agent.snapshot())]
        effects.append({"kind": "transport_cut", "n": 30})
        self.assertTrue(effects)
        for effect in effects:
            with self.subTest(effect=effect):
                w = self.s.world.clone()
                valid = strike_effect(effect, w)
                w.inject(valid)
                w.step()

    def test_cpr_instruction_enables_metronome(self):
        from motor.server.chat import instruction_view
        self.assertTrue(instruction_view({'id': 'cpr_hands_only', 'steps': ['texto del protocolo']}, 'es')['metronome'])

    def test_telegram_renders_instruction_steps_as_text(self):
        from motor.server.telegram_bot import TelegramBot
        from types import SimpleNamespace
        sent = []
        bot = TelegramBot.__new__(TelegramBot)
        bot.chat_hub = SimpleNamespace(available=True, turn=lambda *a, **kw: {
            'reports': [], 'say': 'Recibido', 'instruction': {'id': 'safe', 'title': 'Ahora', 'steps': ['Paso uno.', 'Paso dos.'], 'metronome': False}})
        bot.stats = {'reports': 0}
        bot.send = lambda cid, text: sent.append(text)
        bot._report(1, {'alias': 'telegram:1', 'zone': None, 'wristband': None, 'reports': []}, 'aviso')
        self.assertIn('Paso uno.\nPaso dos.', sent[-1])
        self.assertNotIn("'steps'", sent[-1])

    def test_h2_report_export_hides_reserved_truth_location(self):
        self.s.report('whatsapp', 'Una menor perdida MARCADOR_PRIVADO', 'toilets')
        out = self.s.informe()
        self.assertIsNone(out['truth_incidents']['jx1']['zone'])

    def test_h6_platform_callback_without_run_requires_issued_id(self):
        c = self.flight()
        out = c.on_event({'type': 'dispatch_result', 'action_id': 'probe', 'session_id': 'hr-old',
                          'result': 'reject', 'event_id': 'old'})
        self.assertTrue(out.get('stale'), out)
        self.assertIn('probe', c._inflight)
        self.assertNotIn('old', c._seen_events)

    def test_h4_nested_answer_validates_before_consuming_event(self):
        c = self.flight()
        for data in ({'exists': 'false'}, {'exists': True, 'severity': 'bad'}, {'zone': []},
                     {'needs': {'medical': 'bad'}}, {'deadline': {}}, {'family': []}):
            with self.subTest(data=data):
                ev = {'message': 'clarify_result', 'action_id': 'probe', 'event_id': 'bad-answer',
                      'result': 'answer', 'data': data}
                response = self.c.post('/hr/events', json=ev, headers={'X-Mando-Token': 'test-secret'})
                self.assertEqual(response.status_code, 422)
                self.assertIn('probe', c._inflight)
                self.assertNotIn('bad-answer', c._seen_events)
        ev['data'] = {'exists': True, 'severity': 5}
        self.assertEqual(self.c.post('/hr/events', json=ev, headers={'X-Mando-Token': 'test-secret'}).json()['result'], 'answer')

    def test_h2_final_classification_masks_existing_report(self):
        ev = {'type': 'public_report', 'report_ref': 'private-ref', 'partial': True,
              'text': 'Necesito ayuda MARCADOR_FINAL', 'zone_hint': 'toilets'}
        headers = {'X-Mando-Token': 'test-secret'}
        self.assertEqual(self.c.post('/hr/events', json=ev, headers=headers).status_code, 200)
        ev.update(partial=False, extracted={'sensitive': True})
        self.assertEqual(self.c.post('/hr/events', json=ev, headers=headers).status_code, 200)
        self.assertNotIn('MARCADOR_FINAL', self.c.get('/api/state').text)

    def test_h2_test_mode_never_logs_private_report_text(self):
        for kind in ('message', 'type'):
            ev = {kind: 'public_report', 'mode': 'test', 'event_id': kind,
                  'text': 'Una menor perdida MARCADOR_TEST', 'report': {'text': 'Una menor perdida MARCADOR_TEST'}}
            self.assertEqual(self.c.post('/hr/events', json=ev, headers={'X-Mando-Token': 'test-secret'}).status_code, 200)
            self.s._rebuild()
            self.assertNotIn('MARCADOR_TEST', self.c.get('/api/state').text)

    def test_h2_strike_and_follow_endpoint_hide_reserved_payload(self):
        effect = {'kind': 'incident', 'incident': {'id': 'private-strike', 'family': 'aggression',
                  'type': 'missing_child', 'zone': 'toilets', 'severity': 7},
                  'reports': [{'text': 'Una menor perdida MARCADOR_GOLPE', 'zone_hint': 'toilets'}]}
        self.c.post('/api/strike', json={'preset': 'storm', 'client_id': 'alice'})
        response = self.c.post('/api/strike', json={'effect': effect, 'label': 'MARCADOR_GOLPE', 'client_id': 'bob'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['left'], 2)
        self.assertEqual(response.json()['global_left'], 1)
        self.assertNotIn('MARCADOR_GOLPE', response.text)
        self.assertNotIn('MARCADOR_GOLPE', self.s.state_json())
        follow = self.c.get(response.json()['follow'])
        self.assertNotIn('MARCADOR_GOLPE', follow.text)
        self.assertTrue({'id', 'broken', 'new_plans', 'locked_test'} <= set(follow.json()))

    def test_chat_intake_has_unique_id_and_resets_with_world(self):
        hub = self.app.state.chat
        a = hub.turn(None, 'Necesito ayuda', lang='es')
        b = hub.turn(None, 'Necesito ayuda', lang='es')
        ai, bi = hub.chats[a['session_id']]['intake'], hub.chats[b['session_id']]['intake']
        self.assertNotEqual(ai.session_id, bi.session_id)
        self.c.post('/api/session', json={})
        hub._sync()
        self.assertNotIn(a['session_id'], hub.chats, 'reiniciar elimina la conversación anterior completa')
        self.assertFalse(hub.chats)
        self.app.state.session.close()

    def test_duel_invalid_baseline_keeps_existing_session(self):
        self.c.get('/api/duel/state')
        old = self.app.state.duel
        response = TestClient(self.app, raise_server_exceptions=False).post('/api/duel/session', json={'baseline': 'bad'})
        self.assertEqual(response.status_code, 422)
        self.assertIs(self.app.state.duel, old)
        old.close()

    def test_phone_redaction_preserves_network_links(self):
        from motor.server.privacy import scrub
        self.assertEqual(scrub('http://192.168.100.8:8000/asistente'), 'http://192.168.100.8:8000/asistente')
        self.assertNotIn('600000999', scrub('+34600000999'))

    def test_h1_agent_failure_marks_engine_error_without_private_exception(self):
        with patch.object(self.s.agent, 'tick', side_effect=ValueError('MARCADOR_EXCEPCION')):
            self.s.tick()
        self.assertEqual(self.s.state()['engine_error']['type'], 'ValueError')
        self.assertEqual(self.s.agent_errors, 1)
        self.assertNotIn('MARCADOR_EXCEPCION', self.s.state_json())

    def test_h4_top_level_needs_validates_before_closing(self):
        c = self.flight()
        ev = {'message': 'clarify_result', 'action_id': 'probe', 'event_id': 'bad-needs',
              'result': 'answer', 'data': {'exists': True}, 'needs': {'medical': 'bad'}}
        response = self.c.post('/hr/events', json=ev, headers={'X-Mando-Token': 'test-secret'})
        self.assertEqual(response.status_code, 422)
        self.assertIn('probe', c._inflight)
        self.assertNotIn('bad-needs', c._seen_events)
        ev['needs'] = {'medical': 1}
        self.assertEqual(self.c.post('/hr/events', json=ev, headers={'X-Mando-Token': 'test-secret'}).json()['result'], 'answer')

    def test_h2_updates_inherit_and_propagate_reservation(self):
        root = self.s.report('whatsapp', 'Una menor perdida en los baños', 'toilets')['report_id']
        update = self.s.report('whatsapp', 'Lleva una chaqueta MARCADOR_ACTUALIZACION', 'toilets', update_of=root)['report_id']
        self.assertNotIn('MARCADOR_ACTUALIZACION', self.s.state_json())
        self.assertTrue(self.s._report_meta[update]['reserved'])
        root = self.s.report('whatsapp', 'Necesito ayuda', 'toilets')['report_id']
        update = self.s.report('whatsapp', 'Una chaqueta MARCADOR_FINAL_TARDIO', 'toilets', update_of=root)['report_id']
        self.s._report_meta[root]['reserved'] = True
        self.s._rebuild()
        self.assertTrue(self.s._report_meta[update]['reserved'])
        self.assertNotIn('MARCADOR_FINAL_TARDIO', self.s.state_json())
        self.assertNotIn('MARCADOR_FINAL_TARDIO', json.dumps(self.s.server_log))
