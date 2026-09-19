"""Personal autenticado, partes e integración con el bucle Mando."""
import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from motor.server.app import create_app


class PersonalTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'MANDO_PUBLIC_URL':'https://test.invalid', 'MANDO_OPERATOR_TOKEN':'operator-test',
                                          'MANDO_OPERATORS':'', 'TELEGRAM_MODE':'off'})
        self.env.start()
        self.app = create_app('demo-1', threaded=False, secret='hr-test', playbook='seed', local_params=False)
        self.s = self.app.state.session
        self.c = TestClient(self.app)
        self.op = {'X-Mando-Operator':'operator-test'}

    def tearDown(self):
        self.s.close()
        self.app.state.session.close()
        self.app.state.chat.stop()
        self.env.stop()

    def credential(self, unit='med_1'):
        r = self.c.post('/api/personal/links', headers=self.op, json={'unit_id':unit, 'role':'sanitario'})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()['token']

    def test_invalid_unit_token(self):
        r = self.c.post('/api/personal/status', headers={'X-Mando-Unit':'bad'}, json={'unit_id':'med_1','status':'on_scene'})
        self.assertEqual(r.status_code, 403, r.text)

    def test_status_and_scene_expiry(self):
        token = self.credential()
        headers = {'X-Mando-Unit':token}
        r = self.c.post('/api/personal/status', headers=headers, json={'unit_id':'med_1','status':'on_scene','zone':'general'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(str(self.s.world.observe().resources['med_1'].status), 'busy')
        self.assertEqual(self.s.world.reports[-1].source, 'med_1')
        self.assertEqual(str(self.s.world.reports[-1].channel), 'radio')
        self.assertEqual(self.c.post('/api/personal/status', headers=headers, json={'unit_id':'amb_1','status':'free'}).status_code, 403)
        self.c.post('/api/control', headers=self.op, json={'cmd':'reset'})
        self.assertEqual(self.c.get('/api/personal/me', headers=headers).status_code, 403)

    def test_blocked_route_breaks_assumption_new_plan(self):
        from motor.server.ensayo import prepare_key_moment
        prepare_key_moment(self.s)
        token = self.credential('amb_1')
        before = {p['id'] for p in self.s.state()['plans']}
        r = self.c.post('/api/personal/status', headers={'X-Mando-Unit':token},
                        json={'unit_id':'amb_1','status':'route_blocked','zone':'corridor_s'})
        self.assertEqual(r.status_code, 200, r.text)
        self.s.tick()
        logs = self.s.state()['log']
        self.assertTrue(any(e['kind']=='assumption_broken' for e in logs))
        self.assertTrue(any(p['id'] not in before and p.get('supersedes') for p in self.s.state()['plans']))
        self.assertTrue(any(e['kind']=='staff_status' for e in logs))

    def test_staff_webhook_strict_idempotent(self):
        token = self.credential()
        ev = {'type':'staff_status','event_id':'staff-1','unit_id':'med_1','unit_token':token,
              'status':'on_scene','zone':'general','needs_support':False,'free_text':''}
        headers = {'X-Mando-Token':'hr-test'}
        r = self.c.post('/hr/events', headers=headers, json=dict(ev, needs_support='false'))
        self.assertEqual(r.status_code, 422, r.text)
        r = self.c.post('/hr/events', headers=headers, json=ev)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()['ok'])
        count = len(self.s.world.reports)
        self.assertTrue(self.c.post('/hr/events', headers=headers, json=ev).json()['duplicate'])
        self.assertEqual(count, len(self.s.world.reports))
        self.assertEqual(self.c.post('/hr/events', headers={'X-Mando-Token':'bad'}, json=ev).status_code, 401)

    def test_external_notice(self):
        r = self.c.post('/hr/events', headers={'X-Mando-Token':'hr-test'}, json={
            'type':'external_notice','event_id':'external-1','source':'112','text':'Ambulancia externa en acceso A','zone':'gate_a'})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.s.world.reports[-1].source, '112')

    def test_page_and_own_orders_only(self):
        self.assertEqual(self.c.get('/personal').status_code, 200)
        token = self.credential()
        r = self.c.get('/api/personal/me', headers={'X-Mando-Unit':token})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['unit']['id'], 'med_1')
        self.assertNotIn('contact', r.text)
        self.assertTrue(all(a['resource']=='med_1' for a in r.json()['orders']))

    def test_own_order_accept_reject_and_phone_redaction(self):
        from motor.contracts import Action, ActionKind, ActionStatus
        token = self.credential()
        other = self.credential('med_2')
        a = Action('field-order', ActionKind.DISPATCH, self.s.world.t, resource='med_1',
                   status=ActionStatus.EXECUTING, why='Llamar +999 123 456 789')
        self.s.agent.actions[a.id] = a
        own = {'X-Mando-Unit': token}
        reply = self.c.get('/api/personal/me', headers=own)
        self.assertNotIn('+999 123 456 789', reply.text)
        self.assertEqual(len(reply.json()['orders']), 1)
        path = '/api/personal/order/' + a.id
        self.assertEqual(self.c.post(path, headers={'X-Mando-Unit': other}, json={'result':'accept'}).status_code, 403)
        self.assertEqual(self.c.post(path, headers=own, json={'result':'reject'}).status_code, 422)
        self.assertEqual(self.c.post(path, headers=own, json={'result':'accept'}).status_code, 200)
        self.assertEqual(self.c.post(path, headers=own, json={'result':'accept'}).status_code, 409)

    def test_public_and_staff_sources_merge_with_more_confidence(self):
        text = 'Una persona mareada por calor en general'
        self.s.report('web', text, 'general', source='publico-uno')
        self.s.report('web', text, 'general', source='publico-dos')
        self.s.tick()
        self.s.tick()
        before = next(iter(self.s.agent.incidents.values())).confidence
        token = self.credential()
        r = self.c.post('/api/personal/status', headers={'X-Mando-Unit':token}, json={
            'unit_id':'med_1','status':'new_notice','zone':'general','free_text':text})
        self.assertEqual(r.status_code, 200, r.text)
        self.s.tick()
        self.s.tick()
        incident = next(i for i in self.s.state()['incidents'] if r.json()['report_id'] in i['reports'])
        self.assertEqual(incident['sources'], {'público':2, 'equipo médico':1})
        self.assertGreater(incident['confidence'], before)
