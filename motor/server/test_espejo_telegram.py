"""Espejo del despacho por Telegram: entrada por /hr/events, contrato S.telegram y validación estricta.

    uv run --project motor/server python -m unittest motor.server.test_espejo_telegram -v
"""
import json
import os
import re
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from motor.server import espejo_telegram
from motor.server.app import create_app

SECRET = 'hr-test'
PHONE = re.compile(r'\+?\d[\d\s().-]{8,}')


class EspejoTelegramTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'MANDO_PUBLIC_URL': 'https://test.invalid', 'MANDO_OPERATORS': '',
                                           'MANDO_OPERATOR_TOKEN': 'operator-test',
                                           'TELEGRAM_MODE': 'off', 'MANDO_DB': 'off'})
        self.env.start()
        self.app = create_app('demo-gates', threaded=False, secret=SECRET, playbook='seed', local_params=False)
        self.s = self.app.state.session
        self.c = TestClient(self.app)
        self.hr = {'X-Mando-Token': SECRET}
        self.op = {'X-Mando-Operator': 'operator-test'}

    def tearDown(self):
        self.s.close()
        self.app.state.session.close()
        self.app.state.chat.stop()
        self.env.stop()

    def send(self, event, expect=200):
        r = self.c.post('/hr/events', json=event, headers=self.hr)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json() if r.status_code < 400 else r

    def espejo(self):
        return self.c.get('/api/state').json()['telegram']

    def aviso(self, iid='tg-1', **kw):
        event = dict({'type': 'tg_incident', 'schema': 'mando.hr.v1', 'event_id': iid + '-0', 'id': iid,
                      'texto': 'Una persona se ha desplomado y no responde, junto a la valla',
                      'tipo': 'medica', 'zona': 'front_pit', 'gravedad': 'vital', 'prioridad': 9,
                      'requiere_aprobacion': True, 'alias_informante': 'Asistente',
                      'recursos_requeridos': [{'rol': 'medico', 'cantidad': 1}]}, **kw)
        return self.send(event)

    def test_tg_incident_entra_por_el_contrato_normal(self):
        out = self.aviso()
        self.assertTrue(out['ok'])
        rid = out['report_id']
        state = self.c.get('/api/state').json()
        report = next(r for r in state['reports'] if r['id'] == rid)
        self.assertEqual(report['via'], 'telegram')
        self.assertEqual(report['source'], 'HappyRobot · Telegram')
        self.assertEqual(report['understood'], 'happyrobot')
        tg = state['telegram']
        self.assertIsNotNone(tg)
        self.assertEqual(tg['asignaciones'], [])
        self.assertEqual(tg['escaladas'], [])

    def test_el_aviso_se_fusiona_como_cualquier_otro(self):
        rid = self.aviso()['report_id']
        self.c.post('/api/control', json={'cmd': 'step', 'n': 3}, headers=self.op)
        state = self.c.get('/api/state').json()
        incident = next((i for i in state['incidents'] if rid in (i.get('reports') or [])), None)
        self.assertIsNotNone(incident, 'el aviso de Telegram tiene que acabar en un incidente de Mando')
        self.assertEqual(incident['zone'], 'front_pit')

    def test_tg_assignment_se_ve_en_el_contrato(self):
        self.aviso()
        self.send({'type': 'tg_assignment', 'event_id': 'a1', 'incident_id': 'tg-1', 'rol': 'medico',
                   'estado': 'pending', 'alias': 'Marta', 'intento': 1})
        row = self.espejo()['asignaciones'][0]
        self.assertEqual((row['incident_id'], row['rol'], row['estado'], row['alias'], row['intento']),
                         ('tg-1', 'medico', 'pending', 'Marta', 1))
        self.send({'type': 'tg_assignment', 'event_id': 'a2', 'incident_id': 'tg-1', 'rol': 'medico',
                   'estado': 'accepted', 'alias': 'Marta', 'eta_min': 3, 'from_zone': 'gate_a', 'intento': 1})
        row = self.espejo()['asignaciones'][-1]
        self.assertEqual((row['estado'], row['eta_min'], row['desde_zona']), ('accepted', 3, 'gate_a'))

    def test_tg_staff(self):
        self.aviso()
        self.send({'type': 'tg_staff', 'event_id': 'st1', 'disponibles': 4, 'total': 5})
        self.assertEqual(self.espejo()['staff'], {'disponibles': 4, 'total': 5})

    def test_tg_assignment_rechazo_y_cubierto(self):
        self.aviso()
        self.send({'type': 'tg_assignment', 'event_id': 'a1', 'incident_id': 'tg-1', 'rol': 'medico',
                   'estado': 'declined', 'alias': 'Iván', 'intento': 1})
        self.send({'type': 'tg_assignment', 'event_id': 'a2', 'incident_id': 'tg-1', 'rol': 'medico',
                   'estado': 'covered', 'alias': 'Nadia', 'intento': 2})
        estados = [a['estado'] for a in self.espejo()['asignaciones']]
        self.assertEqual(estados, ['declined', 'covered'])

    def test_tg_approval_solo_log_si_no_hay_tarjeta(self):
        self.aviso()
        self.send({'type': 'tg_approval', 'event_id': 'ap1', 'incident_id': 'tg-1', 'decision': 'apr',
                   'por': 'organizador', 'nota': 'adelante'})
        self.assertEqual(self.c.get('/api/state').json()['approvals'], [])
        logs = [e['text'] for e in self.c.get('/api/state').json()['log'] if e.get('kind') == 'espejo_telegram']
        self.assertTrue(any('organizador por Telegram' in t and 'APRUEBA' in t for t in logs))

    def _app_demo1(self):
        self.s.close()
        self.app.state.session.close()
        self.app.state.chat.stop()
        self.app = create_app('demo-1', threaded=False, secret=SECRET, playbook='seed', local_params=False)
        self.s = self.app.state.session
        self.c = TestClient(self.app)

    def test_tg_approval_marca_tarjeta_sin_ejecutar(self):
        self._app_demo1()
        self.c.post('/api/control', json={'cmd': 'step', 'n': 14}, headers=self.op)
        state = self.c.get('/api/state').json()
        pending = state['approvals']
        self.assertTrue(pending)
        inc = next(i for i in state['incidents'] if i['id'] == pending[0]['incident'])
        rid = inc['reports'][0]
        iid = 'tg-link'
        self.send({'type': 'tg_incident', 'schema': 'mando.hr.v1', 'event_id': iid + '-0', 'id': iid,
                   'texto': 'Aviso enlazado para prueba de aprobación', 'tipo': 'medica', 'zona': 'front_pit'})
        self.s.tg_mirror.incidentes[iid]['report_id'] = rid
        aid = pending[0]['id']
        self.send({'type': 'tg_approval', 'event_id': 'ap-link', 'incident_id': iid, 'decision': 'vet',
                   'por': 'organizador', 'nota': 'espera'})
        after = self.c.get('/api/state').json()
        marked = next(a for a in after['approvals'] if a['id'] == aid)
        self.assertEqual(marked['telegram_decision']['text'],
                         'Decidido en Telegram por el organizador: VETA')
        self.assertIn(aid, [a['id'] for a in after['approvals']])

    def test_tg_approval_ejecuta_con_trust(self):
        self._app_demo1()
        with patch.dict(os.environ, {'MANDO_TRUST_TG_APPROVAL': '1'}):
            self.c.post('/api/control', json={'cmd': 'step', 'n': 14}, headers=self.op)
            state = self.c.get('/api/state').json()
            pending = state['approvals']
            inc = next(i for i in state['incidents'] if i['id'] == pending[0]['incident'])
            rid, aid = inc['reports'][0], pending[0]['id']
            iid = 'tg-trust'
            self.send({'type': 'tg_incident', 'schema': 'mando.hr.v1', 'event_id': iid + '-0', 'id': iid,
                       'texto': 'Aviso para ejecutar aprobación', 'tipo': 'medica'})
            self.s.tg_mirror.incidentes[iid]['report_id'] = rid
            self.send({'type': 'tg_approval', 'event_id': 'ap-trust', 'incident_id': iid, 'decision': 'apr',
                       'por': 'organizador'})
        after = self.c.get('/api/state').json()
        self.assertNotIn(aid, [a['id'] for a in after['approvals']])

    def test_secuencia_completa_hasta_la_escalada_por_voz(self):
        for event in espejo_telegram.secuencia_demo(self.s):
            self.send(event)
        tg = self.espejo()
        self.assertEqual(len(tg['escaladas']), 1)
        escalada = tg['escaladas'][0]
        self.assertEqual(escalada['rol'], 'seguridad')
        self.assertEqual(escalada['workflow_voz'], 'mando-despacho-seguridad')
        self.assertIn('Telegram', escalada['motivo'])
        self.assertTrue(any(a['estado'] == 'accepted' for a in tg['asignaciones']))

    def test_demo_de_operador(self):
        self.assertEqual(self.c.post('/api/demo/telegram', json={}).status_code, 401)
        out = self.c.post('/api/demo/telegram', json={'zone': 'front_pit'}, headers=self.op).json()
        self.assertTrue(out['ok'])
        self.assertEqual(len(out['escaladas']), 1)
        self.assertEqual(out['telegram']['escaladas'][0]['workflow_voz'], 'mando-despacho-seguridad')

    def test_tipo_desconocido_es_422(self):
        self.send({'type': 'tg_cualquier_cosa', 'id': 'x'}, expect=422)

    def test_zona_desconocida_no_rechaza_el_evento(self):
        out = self.aviso(iid='tg-z', zona='zona_que_no_existe')
        self.assertTrue(out['ok'])
        item = self.s.tg_mirror.incidentes['tg-z']
        self.assertIsNone(item['zona'])

    def test_alias_de_zona_en_espanol(self):
        out = self.aviso(iid='tg-alias', zona='escenario')
        self.assertEqual(self.s.tg_mirror.incidentes['tg-alias']['zona'], 'front_pit')

    def test_enteros_y_booleanos_como_cadena(self):
        self.aviso(iid='tg-str', prioridad='8', requiere_aprobacion='true',
                   recursos_requeridos=[{'rol': 'medico', 'cantidad': '2'}])
        item = self.s.tg_mirror.incidentes['tg-str']
        self.assertEqual((item['prioridad'], item['requiere_aprobacion']), (8, True))
        self.send({'type': 'tg_assignment', 'event_id': 'str-a', 'incident_id': 'tg-str', 'rol': 'medico',
                   'estado': 'accepted', 'alias': 'Marta', 'eta_min': '3', 'from_zone': 'puerta b', 'intento': '1'})
        row = self.espejo()['asignaciones'][-1]
        self.assertEqual((row['eta_min'], row['desde_zona'], row['intento']), (3, 'gate_b', 1))
        self.send({'type': 'tg_staff', 'event_id': 'str-s', 'disponibles': '4', 'total': '5'})
        self.assertEqual(self.espejo()['staff'], {'disponibles': 4, 'total': 5})

    def test_coercion_estricta_rechaza_valores_ambiguos(self):
        self.aviso()
        malos = [
            {'type': 'tg_incident', 'id': 'tg-2', 'texto': 'x', 'tipo': 'inventado'},
            {'type': 'tg_incident', 'id': 'tg-2', 'texto': 'x', 'gravedad': 'catastrofica'},
            {'type': 'tg_incident', 'id': 'tg-2', 'texto': 'x', 'prioridad': 99},
            {'type': 'tg_incident', 'id': 'tg-2', 'texto': 'x', 'prioridad': 'ocho'},
            {'type': 'tg_incident', 'id': 'tg-2', 'texto': 'x', 'requiere_aprobacion': 'quizas'},
            {'type': 'tg_incident', 'id': 'tg-2', 'texto': 'x', 'recursos_requeridos': [{'rol': 'astronauta'}]},
            {'type': 'tg_incident', 'id': 'tg-2', 'texto': 'x', 'recursos_requeridos': [{'rol': 'medico', 'cantidad': 0}]},
            {'type': 'tg_incident', 'id': 'tg-2'},
            {'type': 'tg_assignment', 'incident_id': 'tg-1', 'rol': 'medico', 'estado': 'quizas'},
            {'type': 'tg_assignment', 'incident_id': 'tg-1', 'rol': 'astronauta', 'estado': 'pending'},
            {'type': 'tg_assignment', 'incident_id': 'tg-1', 'rol': 'medico', 'estado': 'accepted', 'eta_min': 9999},
            {'type': 'tg_staff', 'disponibles': 6, 'total': 5},
            {'type': 'tg_approval', 'incident_id': 'tg-1', 'decision': 'quizas', 'por': 'organizador'},
            {'type': 'tg_approval', 'incident_id': 'tg-1', 'decision': 'apr', 'por': 'Marta'},
        ]
        for event in malos:
            self.send(event, expect=422)

    def test_ni_chat_id_ni_telefono_entran(self):
        self.aviso()
        self.send({'type': 'tg_assignment', 'incident_id': 'tg-1', 'rol': 'medico', 'estado': 'pending',
                   'chat_id': 123456789}, expect=422)
        self.send({'type': 'tg_assignment', 'incident_id': 'tg-1', 'rol': 'medico', 'estado': 'pending',
                   'alias': '+34600111222'}, expect=422)
        self.send({'type': 'tg_incident', 'id': 'tg-9', 'texto': 'x', 'telefono': '+34600111222'}, expect=422)

    def test_sin_chat_id_ni_telefono_en_el_estado(self):
        for event in espejo_telegram.secuencia_demo(self.s):
            self.send(event)
        state = self.c.get('/api/state').json()
        self.assertNotIn('chat_id', json.dumps(state, ensure_ascii=False))
        espejo = json.dumps(state['telegram'], ensure_ascii=False)
        self.assertIsNone(PHONE.search(espejo), 'no puede salir nada con pinta de teléfono en el espejo')
        for palabra in ('chat_id', 'telefono', 'teléfono', 'phone', 'message_id'):
            self.assertNotIn(palabra, espejo)

    def test_una_asignacion_de_un_aviso_que_no_existe(self):
        self.send({'type': 'tg_assignment', 'incident_id': 'no-existe', 'rol': 'medico', 'estado': 'pending'},
                  expect=404)

    def test_la_validacion_no_tumba_el_reloj(self):
        self.aviso()
        antes = self.c.get('/api/state').json()['t']
        for _ in range(5):
            self.send({'type': 'tg_assignment', 'incident_id': 'tg-1', 'rol': 'medico', 'estado': 'nada'}, expect=422)
        self.assertEqual(self.c.post('/api/control', json={'cmd': 'step', 'n': 2}, headers=self.op).status_code, 200)
        state = self.c.get('/api/state').json()
        self.assertEqual(state['t'], antes + 2)
        self.assertIsNone(state['engine_error'])
        self.assertEqual(self.espejo()['asignaciones'], [])

    def test_idempotencia_por_event_id(self):
        self.aviso()
        event = {'type': 'tg_assignment', 'event_id': 'repetido', 'incident_id': 'tg-1', 'rol': 'medico',
                 'estado': 'accepted', 'alias': 'Marta', 'eta_min': 4, 'intento': 1}
        self.send(event)
        self.assertTrue(self.send(event)['duplicate'])
        self.assertEqual(len(self.espejo()['asignaciones']), 1)

    def test_primer_acc_gana_en_el_espejo(self):
        self.aviso()
        self.send({'type': 'tg_assignment', 'event_id': 'a1', 'incident_id': 'tg-1', 'rol': 'medico',
                   'estado': 'accepted', 'alias': 'Marta', 'intento': 1})
        out = self.send({'type': 'tg_assignment', 'event_id': 'a2', 'incident_id': 'tg-1', 'rol': 'medico',
                         'estado': 'accepted', 'alias': 'Bruno', 'intento': 2})
        self.assertEqual(out['estado'], 'covered')
        estados = {(a['alias'], a['estado']) for a in self.espejo()['asignaciones']}
        self.assertEqual(estados, {('Marta', 'accepted'), ('Bruno', 'covered')})

    def test_puestos_del_bot_en_el_espejo(self):
        self.send({'type': 'tg_incident', 'schema': 'mando.hr.v1', 'event_id': 'tg-b-0', 'id': 'tg-b',
                   'texto': 'Humo en restauración, simulación', 'tipo': 'incendio', 'zona': 'front_pit',
                   'gravedad': 'urgente', 'recursos_requeridos': [{'rol': 'bomberos', 'cantidad': 1}]})
        self.send({'type': 'tg_assignment', 'event_id': 'tg-b-1', 'incident_id': 'tg-b',
                   'rol': 'bomberos', 'estado': 'pending', 'alias': 'Luis', 'intento': 1})
        self.assertEqual(self.espejo()['asignaciones'][0]['rol'], 'bomberos')

    def test_token_de_webhooks(self):
        self.assertEqual(self.c.post('/hr/events', json={'type': 'tg_incident'}).status_code, 401)
        self.assertEqual(self.c.post('/hr/events', json={'type': 'tg_incident'},
                                     headers={'X-Mando-Token': 'otro'}).status_code, 401)

    def test_el_token_del_widget_no_sirve_para_el_espejo(self):
        with patch.dict(os.environ, {'HR_CHAT_TOKEN': 'token-widget'}):
            r = self.c.post('/hr/events', json={'type': 'tg_incident', 'id': 'x', 'texto': 'y'},
                            headers={'X-Mando-Token': 'token-widget'})
        self.assertEqual(r.status_code, 403, r.text)

    def test_espejo_ausente_sin_eventos(self):
        tg = self.c.get('/api/state').json()['telegram']
        self.assertNotIn('asignaciones', tg, 'sin espejo no debe publicar el contrato de despacho')


if __name__ == '__main__':
    unittest.main()
