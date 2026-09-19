"""Enrutado por oficio y decisiones de voz: solo mocks, nunca comunicaciones reales."""
import os
import unittest
from unittest.mock import patch

from motor.contracts import Action, ActionKind, Resource, ResourceKind


class RoutingTest(unittest.TestCase):
    def test_each_resource_and_action(self):
        from .hr_routing import workflow_slot
        for kind, expected in ((ResourceKind.MEDICAL, 'sanitario'), (ResourceKind.AMBULANCE, 'sanitario'),
                               (ResourceKind.SECURITY, 'seguridad'), (ResourceKind.TECH, 'tecnico'),
                               (ResourceKind.LOGISTICS, 'logistica'), (ResourceKind.VOLUNTEER, 'relevo')):
            for action_kind in (ActionKind.DISPATCH, ActionKind.RECALL, ActionKind.NOTIFY):
                with self.subTest(kind=kind, action=action_kind):
                    resource = Resource('unit', kind, 'Unidad de prueba', 'gate_b')
                    action = Action('a', action_kind, 0, resource='unit')
                    self.assertEqual(workflow_slot(action, resource), expected)
        for kind, params, expected in ((ActionKind.RESUPPLY, {'to': 'proveedor'}, 'logistica'),
                                      (ActionKind.REQUEST_EXTERNAL, {}, 'externos'),
                                      (ActionKind.BROADCAST, {}, 'difusion'),
                                      (ActionKind.NOTIFY, {'to': 'director', 'decision_for': 'pending'}, 'director'),
                                      (ActionKind.NOTIFY, {'to': 'suplente', 'decision_for': 'pending'}, 'director'),
                                      (ActionKind.NOTIFY, {'to': 'reserva'}, 'relevo')):
            self.assertEqual(workflow_slot(Action('a', kind, 0, params=params), None), expected)

    def test_unconfigured_specialists_are_opt_in(self):
        from . import hr_config
        with patch.dict(os.environ, {}, clear=True):
            for slot in ('sanitario', 'seguridad', 'tecnico', 'logistica', 'director', 'externos', 'difusion', 'relevo'):
                self.assertEqual(hr_config.workflow_ids()[slot], '')
                self.assertEqual(hr_config.workflow_urls()[slot], '')

    def test_explicit_environment_url_wins(self):
        from . import hr_config
        with patch.dict(os.environ, {'HR_WORKFLOW_SANITARIO': 'test-specialist',
                'HR_HOOK_SANITARIO': 'https://unused.invalid/general',
                'HR_HOOK_SANITARIO_DEVELOPMENT': 'http://127.0.0.1:1/medical'}, clear=True):
            self.assertEqual(hr_config.workflow_ids()['sanitario'], 'test-specialist')
            self.assertEqual(hr_config.workflow_urls()['sanitario'], 'http://127.0.0.1:1/medical')


class TransportTest(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from .comms_happyrobot import HappyRobotComms
        self.env = patch.dict(os.environ, {'HR_HOOK_DISPATCH': 'http://127.0.0.1:1/generic',
            'HR_HOOK_SANITARIO': 'http://127.0.0.1:1/medical', 'MANDO_VOICE_MODE': 'phone',
            'MANDO_ALLOWED_NUMBERS': '+99900000000', 'HR_RETRIES': '0', 'HR_SECRET': 'fixture'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.r = Resource('medical-fixture', ResourceKind.MEDICAL, 'Equipo ficticio', 'gate_b')
        self.a = Action('routing-fixture', ActionKind.DISPATCH, 0, resource=self.r.id, zone='gate_b')
        self.c = HappyRobotComms(SimpleNamespace(t=0), Mock(), session_id='fixture', mode='happyrobot',
            contacts={'resources': {self.r.id: {'to_number': '+99900000000'}}, 'roles': {}})
        self.addCleanup(self.c.close)

    def test_specific_and_missing_configuration(self):
        self.assertEqual(self.c._real_route(self.a, self.r)[0], 'http://127.0.0.1:1/medical')
        self.c.hooks['sanitario'] = ''
        self.c.workflows['sanitario'] = ''
        self.assertEqual(self.c._real_route(self.a, self.r)[0], 'http://127.0.0.1:1/generic')

    def test_role_contacts_choose_specialist_without_resource(self):
        for role, slot in (('sanitario', 'sanitario'), ('ambulance', 'sanitario'),
                           ('seguridad', 'seguridad'), ('jefe_sector', 'seguridad'),
                           ('tech', 'tecnico'), ('logistics', 'logistica')):
            with self.subTest(role=role):
                self.c.contacts['roles'][role] = {'to_number': '+99900000000'}
                self.c.hooks[slot] = 'http://127.0.0.1:1/' + slot
                a = Action('role-' + role, ActionKind.NOTIFY, 0, params={'to': role})
                route = self.c._real_route(a, None)
                self.assertEqual(route[0], 'http://127.0.0.1:1/' + slot)
                self.assertEqual(route[1]['workflow'], slot)

    def test_public_notification_never_uses_voice_or_broadcast_approval(self):
        self.c.contacts['roles']['public'] = {'to_number': '+99900000000'}
        self.c.hooks['difusion'] = 'http://127.0.0.1:1/text'
        for mode in ('phone', 'web_call'):
            with self.subTest(mode=mode), patch.dict(os.environ, {'HR_API_KEY': 'fixture'}):
                self.c.voice_mode = mode
                a = Action('public-notify', ActionKind.NOTIFY, 0, params={'to': 'public'})
                self.assertIsNone(self.c._real_route(a, None))

    def test_failed_specific_falls_back_to_generic_without_losing_order(self):
        import httpx
        with patch('motor.server.comms_happyrobot.threading.Thread'):
            self.c.send(self.a, self.r)
        with patch('motor.server.comms_happyrobot.httpx.post', side_effect=[
                httpx.Response(503), httpx.Response(200, json={'run_id': 'generic-run'})]) as post:
            self.c._post(self.a.id, 'http://127.0.0.1:1/medical', self.c.wire_payload(self.a.id))
        self.assertEqual([x.args[0] for x in post.call_args_list],
                         ['http://127.0.0.1:1/medical', 'http://127.0.0.1:1/generic'])
        self.assertEqual(post.call_args_list[0].kwargs['json']['order_text'],
                         post.call_args_list[1].kwargs['json']['order_text'])
        self.assertEqual(self.c.calls[self.a.id]['workflow'], 'dispatch')
        self.assertEqual(self.c.calls[self.a.id]['workflow_history'], ['sanitario', 'dispatch'])
        self.c.sim.send.assert_not_called()

    def test_outcome_contract_is_normalized(self):
        from .comms_happyrobot import normalize_platform_event
        for outcome, result in [('accepted', 'accept'), ('rejected', 'reject'), ('no_answer', 'no_answer')]:
            self.assertEqual(normalize_platform_event({'type': 'dispatch_result', 'outcome': outcome})['result'], result)


class DecisionTest(unittest.TestCase):
    def setUp(self):
        from .app import Session, load_case
        from motor.contracts import ActionStatus, Autonomy
        self.env = patch.dict(os.environ, {'TELEGRAM_MODE': 'off'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.s = Session(load_case('demo-1'), threaded=False)
        self.addCleanup(self.s.close)
        self.action = Action('phone-pending', ActionKind.STOP_SHOW, 0,
                             autonomy=Autonomy.APPROVE, status=ActionStatus.AWAITING_APPROVAL)
        self.s.agent.actions[self.action.id] = self.action
        self.s._rebuild()
        self.s.comms._wire_to_action['issued:decision'] = 'call-decision'
        self.s.comms.calls['call-decision'] = {'decision_for': self.action.id, 'decision_role': 'director'}

    def event(self, decision='approve', **kw):
        return dict(type='decision', action_id='issued:decision', decision=decision, by_role='director', note='Confirmo', **kw)

    def test_phone_approve_and_duplicate(self):
        from .hr_routing import apply_decision
        out = apply_decision(self.s, self.event())
        self.assertTrue(out['ok'])
        self.assertTrue(self.s.approvals[self.action.id]['ok'])
        self.assertIn('por teléfono: director', self.s.approvals[self.action.id]['by'])
        self.assertTrue(apply_decision(self.s, self.event())['duplicate'])

    def test_phone_veto(self):
        from .hr_routing import apply_decision
        self.assertTrue(apply_decision(self.s, self.event('veto'))['ok'])
        self.assertFalse(self.s.approvals[self.action.id]['ok'])

    def test_doubt_never_approves(self):
        from .hr_routing import apply_decision
        for value in ('quizá', 'yes', '', 'unclear', True, None):
            self.assertFalse(apply_decision(self.s, self.event(value))['ok'])
        self.assertNotIn(self.action.id, self.s.approvals)

    def test_wrong_role_or_unissued_id_denied(self):
        from fastapi import HTTPException
        from .hr_routing import apply_decision
        for key, value in (('by_role', 'sanitario'), ('action_id', self.action.id)):
            ev = self.event()
            ev[key] = value
            with self.assertRaises(HTTPException) as err:
                apply_decision(self.s, ev)
            self.assertEqual(err.exception.status_code, 403)
        self.assertNotIn(self.action.id, self.s.approvals)

    def test_test_event_does_not_approve(self):
        from .hr_routing import apply_decision
        self.assertTrue(apply_decision(self.s, self.event(mode='test'))['test'])
        self.assertNotIn(self.action.id, self.s.approvals)


class DiffusionTest(unittest.TestCase):
    def test_delivery_requires_matching_approval_and_counts_real_ack(self):
        from types import SimpleNamespace
        import threading
        from unittest.mock import Mock
        from .hr_text_delivery import deliver_text
        c = SimpleNamespace(_wire_to_action={'wire': 'broadcast'}, payloads={'broadcast': {
            'message_text': 'Camine hacia la salida indicada.', 'audience': 'test', 'approved_by': 'Ana'}},
            contacts={'audiences': {'test': {'telegram': [1001, 1002]}}},
            workflow_status=Mock(), text_receipts={})
        s = SimpleNamespace(lock=threading.RLock(), comms=c, _approval_record=lambda aid: {'by': 'Ana'}, _rebuild=Mock())
        bot = Mock(mode='send_only')
        bot._call.side_effect = [{'message_id': 1}, RuntimeError('fallo simulado')]
        ev = dict(type='text_delivery_request', action_id='wire', approved_by='Ana', audience='test',
                  message_text='Camine hacia la salida indicada.')
        out = deliver_text(s, ev, bot)
        self.assertEqual((out['delivered'], out['failed']), (1, 1))
        self.assertEqual(deliver_text(s, ev, bot), out)
        self.assertEqual(bot._call.call_count, 2)

    def test_no_approval_or_changed_text_never_sends(self):
        from types import SimpleNamespace
        import threading
        from unittest.mock import Mock
        from fastapi import HTTPException
        from .hr_text_delivery import deliver_text
        c = SimpleNamespace(_wire_to_action={'wire': 'a'}, payloads={'a': {
            'message_text': 'Texto aprobado', 'audience': 'test', 'approved_by': 'Ana'}},
            contacts={'audiences': {'test': {'telegram': [1001]}}}, text_receipts={})
        s = SimpleNamespace(lock=threading.RLock(), comms=c, _approval_record=lambda aid: None)
        bot = Mock()
        with self.assertRaises(HTTPException):
            deliver_text(s, dict(action_id='wire', message_text='Texto cambiado', audience='test', approved_by=''), bot)
        bot._call.assert_not_called()
