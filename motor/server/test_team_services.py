"""Servicios de fase A, comprobables antes de integrar rutas."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from motor.contracts import Action, ActionKind, ActionStatus, Autonomy
from motor.server.app import Session, load_case
from motor.server.multi import Operators
from motor.server.personal import FieldStaff
from fastapi import HTTPException


class TeamServicesTest(unittest.TestCase):
    def setUp(self):
        self.s=Session(load_case('demo-1'), threaded=False, playbook='seed',local_params=False)
        self.s.operators=Operators(self.s)
        self.s.staff=FieldStaff(self.s)
        self.a=dict(id='m', name='Marta',role='sanitario')
        self.b=dict(id='l', name='Luis',role='seguridad')

    def tearDown(self):
        self.s.close()

    def test_atomic_decision(self):
        self.s.agent.actions['test']=Action('test',ActionKind.STOP_SHOW,0,autonomy=Autonomy.APPROVE,status=ActionStatus.AWAITING_APPROVAL)
        self.s._rebuild()
        def go(who):
            try:
                self.s.operators.decide('test',True,'',who)
                return 200
            except HTTPException as e:
                return e.status_code
        with patch.dict(os.environ,{'MANDO_TWO_PERSON':'0'}), ThreadPoolExecutor(2) as ex:
            self.assertEqual(sorted(ex.map(go,[self.a,self.b])),[200,409])

    def test_token_and_status(self):
        token=self.s.staff.issue('med_1','sanitario')
        self.assertEqual(self.s.staff.verify(token)['unit_id'],'med_1')
        with self.assertRaises(HTTPException):self.s.staff.verify(token,'amb_1')
        self.s.staff.status({'unit_id':'med_1','status':'on_scene','zone':'general'},token)
        self.assertEqual(str(self.s.world.observe().resources['med_1'].status),'busy')

    def test_correction_vote_cannot_approve_different_order(self):
        self.s.agent.actions['test']=Action('test',ActionKind.STOP_SHOW,0,autonomy=Autonomy.APPROVE,status=ActionStatus.AWAITING_APPROVAL)
        self.s._rebuild()
        with patch.dict(os.environ,{'MANDO_TWO_PERSON':'1'}):
            self.s.operators.correction({'kind':'stop_show'},'alternativa',self.a,target='test')
            with self.assertRaises(HTTPException):self.s.operators.decide('test',True,'',self.b)
        self.assertEqual(self.s.agent.actions['test'].status,ActionStatus.AWAITING_APPROVAL)

    def test_invalid_prepared_approval_does_not_consume_vote(self):
        self.s.agent.actions['test']=Action('test',ActionKind.EVACUATE,0,autonomy=Autonomy.APPROVE,
            status=ActionStatus.AWAITING_APPROVAL,params={'prepared':True})
        self.s._rebuild()
        with patch.dict(os.environ,{'MANDO_TWO_PERSON':'0'}):
            with self.assertRaises(HTTPException):self.s.operators.decide('test',True,'',self.a)
            out=self.s.operators.decide('test',True,'EVACUAR zona general',self.a)
        self.assertTrue(out['ok'])

    def test_cancelled_original_cannot_be_corrected_by_second_signature(self):
        self.s.agent.actions['test']=Action('test',ActionKind.STOP_SHOW,0,autonomy=Autonomy.APPROVE,status=ActionStatus.AWAITING_APPROVAL)
        self.s._rebuild()
        with patch.dict(os.environ,{'MANDO_TWO_PERSON':'1'}):
            self.s.operators.correction({'kind':'stop_show'},'',self.a,target='test')
            self.s.agent.actions['test'].status=ActionStatus.CANCELLED
            self.s._rebuild()
            with self.assertRaises(HTTPException):self.s.operators.correction({'kind':'stop_show'},'',self.b,target='test')
        self.assertFalse(self.s.world.show_stopped)

    def test_staff_arrival_and_release_close_existing_incident(self):
        from motor.contracts import Report, Channel, Observation
        # Sin sucesos del caso: un aviso y el mismo ciclo de contrato que usa Session.
        self.s.report('radio', 'Una persona mareada por calor', 'general', source='med_1', preset='heat')
        self.s.tick()
        self.s.tick()
        inc=next(i for i in self.s.agent.incidents.values() if i.zone=='general')
        unit=inc.assigned[0]
        token=self.s.staff.issue(unit,'sanitario')
        self.s.staff.status({'unit_id':unit,'status':'on_scene','zone':'general'},token)
        actions=self.s.agent.tick(self.s.staff.observation(self.s.world.observe()))
        for a in actions:
            if str(a.autonomy)!='approve':self.s.world.apply(a)
        self.assertTrue(self.s.agent.meta[inc.id].seen_on_scene)
        self.assertGreaterEqual(inc.confidence,.9)
        self.s.staff.status({'unit_id':unit,'status':'free'},token)
        self.s.agent.tick(self.s.staff.observation(self.s.world.observe()))
        self.assertEqual(str(inc.status),'resolved')

    def test_veto_finishes_pending_two_person_decision(self):
        self.s.agent.actions['test']=Action('test',ActionKind.STOP_SHOW,0,autonomy=Autonomy.APPROVE,status=ActionStatus.AWAITING_APPROVAL)
        self.s._rebuild()
        with patch.dict(os.environ,{'MANDO_TWO_PERSON':'1'}):
            self.assertTrue(self.s.operators.decide('test',True,'',self.a)['pending'])
            self.assertTrue(self.s.operators.decide('test',False,'No es necesario',self.b)['ok'])
            with self.assertRaises(HTTPException):self.s.operators.decide('test',True,'',self.a)
        self.assertEqual(self.s.agent.actions['test'].status,ActionStatus.REJECTED)

    def test_false_alarm_uses_site_confirmation(self):
        self.s.report('radio', 'Una persona mareada por calor', 'general', source='med_1', preset='heat')
        self.s.tick();self.s.tick()
        inc=next(i for i in self.s.agent.incidents.values() if i.zone=='general')
        unit=inc.assigned[0]
        token=self.s.staff.issue(unit,'sanitario')
        self.s.staff.status({'unit_id':unit,'status':'false_alarm','zone':'general'},token)
        self.s.agent.tick(self.s.staff.observation(self.s.world.observe()))
        self.assertIn(str(inc.status),('false_alarm','resolved'))
        self.assertTrue(any('quien está en el sitio' in e['text'] for e in self.s.agent.snapshot()['log']))
