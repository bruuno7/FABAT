"""Concurrencia real entre personas; todo local, sin llamadas externas."""
from concurrent.futures import ThreadPoolExecutor
import os
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from motor.contracts import Action, ActionKind, ActionStatus, Autonomy
from motor.server.app import create_app


class MultiTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'MANDO_PUBLIC_URL': 'https://test.invalid',
            'MANDO_OPERATOR_TOKEN': 'legacy-test', 'MANDO_OPERATORS': 'Marta:sanitario:marta-test,Luis:seguridad:luis-test',
            'MANDO_PUBLIC_RATE_MAX': '', 'MANDO_TWO_PERSON': '0', 'TELEGRAM_MODE': 'off'})
        self.env.start()
        self.app = create_app('demo-1', threaded=False, secret='hr-test', local_params=False)
        self.s = self.app.state.session
        self.c = TestClient(self.app, base_url="https://test.invalid")
        self.marta = {'X-Mando-Operator': 'marta-test'}
        self.luis = {'X-Mando-Operator': 'luis-test'}

    def tearDown(self):
        self.s.close()
        self.app.state.session.close()
        self.app.state.chat.stop()
        self.env.stop()

    def pending(self, aid='test-decision', kind=ActionKind.STOP_SHOW):
        a = Action(aid, kind, self.s.world.t, autonomy=Autonomy.APPROVE,
                   status=ActionStatus.AWAITING_APPROVAL, why='prueba de decisión humana')
        self.s.agent.actions[aid] = a
        self.s._rebuild()
        return aid

    def test_two_operators_race_one_wins(self):
        aid = self.pending()
        barrier = threading.Barrier(2)
        def decide(headers):
            barrier.wait()
            return self.c.post('/api/approve', headers=headers, json={'action_id': aid, 'ok': True, 'by': 'suplantado'})
        with ThreadPoolExecutor(2) as pool:
            replies = list(pool.map(decide, [self.marta, self.luis]))
        self.assertEqual(sorted(r.status_code for r in replies), [200, 409])
        loser = next(r for r in replies if r.status_code == 409)
        self.assertIn('ya lo decidió', loser.text)
        self.assertNotEqual(self.s.approvals[aid]['by'], 'suplantado')
        audit = self.c.get('/api/informe', headers=self.marta).json()
        self.assertTrue(audit['operator_audit'])
        self.assertTrue(audit['operator_latency'])

    def test_two_person_distinct_and_no_early_execution(self):
        with patch.dict(os.environ, {'MANDO_TWO_PERSON': '1'}):
            aid = self.pending()
            first = self.c.post('/api/approve', headers=self.marta, json={'action_id': aid, 'ok': True})
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json()['votes'], 1)
            self.assertNotIn(aid, self.s.approvals)
            self.assertEqual(self.s.agent.actions[aid].status, ActionStatus.AWAITING_APPROVAL)
            duplicate = self.c.post('/api/approve', headers=self.marta, json={'action_id': aid, 'ok': True})
            self.assertEqual(duplicate.status_code, 409)
            second = self.c.post('/api/approve', headers=self.luis, json={'action_id': aid, 'ok': True})
            self.assertEqual(second.status_code, 200, second.text)
            self.assertTrue(self.s.approvals[aid]['ok'])
            self.assertEqual(len(self.s.approvals[aid]['operators']), 2)

    def test_presence_claim_notes_sse(self):
        self.s.report('radio', 'Una persona mareada por calor', 'general', source='med_1')
        self.s.tick()
        self.s.tick()
        iid = next(iter(self.s.agent.incidents))
        r = self.c.post('/api/operators/presence', headers=self.marta, json={'incident': iid})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.c.post(f'/api/incidents/{iid}/claim', headers=self.marta, json={'claim': True})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.c.post(f'/api/incidents/{iid}/note', headers=self.luis, json={'text': '@sanitario mira ' + iid})
        self.assertEqual(r.status_code, 200, r.text)
        stream = self.c.get('/api/stream?limit=1', headers=self.marta).text
        self.assertIn('Marta', stream)
        self.assertIn('@sanitario', stream)
        self.assertIn('sanitario', stream)
        r = self.c.post(f'/api/incidents/{iid}/claim', headers=self.marta, json={'claim': False})
        self.assertEqual(r.status_code, 200)

    def test_operator_login_cookie_and_legacy(self):
        r = self.c.post('/api/operator/login', json={'token': 'marta-test'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.cookies)
        self.assertEqual(self.c.get('/api/operators/me').json()['operator']['name'], 'Marta')
        self.assertEqual(self.c.get('/api/operators/me', headers={'X-Mando-Operator':'legacy-test'}).json()['operator']['id'], 'operador-1')

    def test_untrusted_identity_is_rejected(self):
        self.assertEqual(self.c.post('/api/operators/presence', json={'name':'Marta'}).status_code, 401)
        self.assertEqual(self.c.post('/api/operator/login', json={'token':'bad'}).status_code, 403)

    def test_chat_50_sessions_four_turns_clock(self):
        start = threading.Barrier(51)
        stop = threading.Event()
        ticks = []
        def clock():
            start.wait()
            while not stop.is_set():
                before = time.monotonic()
                self.s.tick()
                ticks.append(time.monotonic() - before)
                stop.wait(.02)
        def chat(n):
            start.wait()
            sid = None
            ids = set()
            for text in ['Hay una persona mareada por calor en general', 'Sí', 'Respira normalmente', 'Solo una persona']:
                r = self.c.post('/api/chat', json={'text':text, 'session_id':sid, 'zone_hint':'general'})
                self.assertEqual(r.status_code, 200, r.text)
                out = r.json()
                if sid:
                    self.assertEqual(out['session_id'], sid)
                sid = out['session_id']
                ids.update(out['reports'])
            return sid, ids
        thread = threading.Thread(target=clock)
        thread.start()
        try:
            with ThreadPoolExecutor(50) as pool:
                results = list(pool.map(chat, range(50)))
        finally:
            stop.set()
            thread.join(10)
        self.assertEqual(len({sid for sid, _ in results}), 50)
        self.assertTrue(all(ids for _, ids in results))
        self.assertEqual(sum(len(ids) for _, ids in results), len(set().union(*(ids for _, ids in results))))
        self.assertTrue(ticks)
        maximum = max(ticks)
        print(f'\nCHAT LOAD N=50 × 4; ticks={len(ticks)}; tick max={maximum:.4f}s', flush=True)
        self.assertLess(maximum, 1.0, 'un tick no debe perder un segundo bajo esta carga local')
        self.assertEqual(self.c.get('/api/chat/c-inventado/events').status_code, 404)
        self.assertEqual(self.c.get('/api/report/j-001').status_code, 404)

    def test_chat_capability_never_appears_in_shared_state(self):
        out = self.c.post('/api/chat', json={'text': 'Una persona mareada por calor en general'}).json()
        sid = out['session_id']
        self.s.refresh.flush()
        self.assertNotIn(sid, self.c.get('/api/state').text)
        self.assertNotIn(sid, self.c.get('/api/state', headers=self.marta).text)
        self.assertNotIn(sid, str(out['state']))
        # A visible intake ID does not grant access to the private conversation.
        guess = self.c.post('/api/chat', json={'session_id': out['state']['session'], 'text': 'Hola'}).json()
        self.assertNotEqual(guess['session_id'], sid)

    def test_public_middleware_preserves_auth_errors(self):
        self.assertEqual(self.c.post('/api/control', json={'cmd': 'step'}).status_code, 401)
        self.assertNotEqual(self.c.post('/api/strike', json={'preset': 'no_answer'}).status_code, 500)
