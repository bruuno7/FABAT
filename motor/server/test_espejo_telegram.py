"""Espejo del despacho por Telegram: entrada por /hr/events, estado de la Sala y validación estricta.

    uv run --project motor/server python -m unittest motor.server.test_espejo_telegram -v
"""
import json
import os
import re
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from motor.server import telegram_espejo
from motor.server.app import create_app

SECRET = 'hr-test'
PHONE = re.compile(r'\+?\d[\d\s().-]{8,}')


class EspejoTelegramTest(unittest.TestCase):
    def setUp(self):
        # MANDO_PUBLIC_URL: también en localhost hace falta credencial para operar (si no, el TestClient
        # entraría como operador por venir de 127.0.0.1 y la prueba del 403 no probaría nada).
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

    # ------------------------------------------------------------------ utilidades
    def send(self, event, expect=200):
        r = self.c.post('/hr/events', json=event, headers=self.hr)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json() if r.status_code < 400 else r

    def espejo(self):
        return self.c.get('/api/state').json()['telegram_despacho']

    def aviso(self, iid='tg-1', **kw):
        event = dict({'type': 'tg_incident', 'schema': 'mando.hr.v1', 'event_id': iid + '-0', 'id': iid,
                      'texto': 'Una persona se ha desplomado y no responde, junto a la valla',
                      'tipo': 'medica', 'zona': 'front_pit', 'gravedad': 'vital', 'prioridad': 9,
                      'requiere_aprobacion': True, 'alias_informante': 'Asistente',
                      'recursos_requeridos': [{'rol': 'medico', 'cantidad': 1}]}, **kw)
        return self.send(event)

    # ------------------------------------------------------------------ los tres tipos entran y se ven
    def test_tg_incident_entra_por_el_contrato_normal(self):
        out = self.aviso()
        self.assertTrue(out['ok'])
        rid = out['report_id']
        state = self.c.get('/api/state').json()
        report = next(r for r in state['reports'] if r['id'] == rid)
        self.assertEqual(report['via'], 'telegram')
        self.assertEqual(report['source'], 'HappyRobot · Telegram')
        self.assertEqual(report['understood'], 'happyrobot')
        item = state['telegram_despacho']['incidentes'][0]
        self.assertEqual((item['id'], item['gravedad'], item['prioridad']), ('tg-1', 'vital', 9))
        self.assertEqual(item['recursos_requeridos'], [{'rol': 'medico', 'cantidad': 1}])
        self.assertTrue(item['requiere_aprobacion'])

    def test_el_aviso_se_fusiona_como_cualquier_otro(self):
        rid = self.aviso()['report_id']
        self.c.post('/api/control', json={'cmd': 'step', 'n': 3}, headers=self.op)
        state = self.c.get('/api/state').json()
        incident = next((i for i in state['incidents'] if rid in (i.get('reports') or [])), None)
        self.assertIsNotNone(incident, 'el aviso de Telegram tiene que acabar en un incidente de Mando')
        self.assertEqual(incident['zone'], 'front_pit')

    def test_tg_assignment_se_ve_con_los_rotulos_del_diseno(self):
        self.aviso()
        self.send({'type': 'tg_assignment', 'event_id': 'a1', 'incident_id': 'tg-1', 'rol': 'medico',
                   'estado': 'pending', 'alias': 'Marta', 'intento': 1, 'timeout_s': 40})
        self.assertEqual(self.espejo()['incidentes'][0]['resumen'], 'Telegram → médico: pendiente 40 s')
        self.send({'type': 'tg_assignment', 'event_id': 'a2', 'incident_id': 'tg-1', 'rol': 'medico',
                   'estado': 'accepted', 'alias': 'Marta', 'eta_min': 3, 'from_zone': 'gate_a', 'intento': 1})
        item = self.espejo()['incidentes'][0]
        self.assertEqual(item['resumen'], 'ACUDE Marta · 3 min · desde Puerta A (norte)')
        self.assertEqual(item['clase'], 'acepta')
        self.assertEqual(item['asignaciones'][0]['from_zone'], 'gate_a')

    def test_tg_assignment_rechazo_y_cubierto(self):
        self.aviso()
        self.send({'type': 'tg_assignment', 'event_id': 'a1', 'incident_id': 'tg-1', 'rol': 'medico',
                   'estado': 'declined', 'alias': 'Iván', 'intento': 1})
        self.assertEqual(self.espejo()['incidentes'][0]['resumen'], 'No puede → reasignando (intento 2)')
        self.send({'type': 'tg_assignment', 'event_id': 'a2', 'incident_id': 'tg-1', 'rol': 'medico',
                   'estado': 'covered', 'alias': 'Nadia', 'intento': 2})
        self.assertEqual(self.espejo()['incidentes'][0]['resumen'], 'Cubierto')

    def test_tg_approval(self):
        self.aviso()
        self.send({'type': 'tg_approval', 'event_id': 'ap1', 'incident_id': 'tg-1', 'decision': 'apr',
                   'por': 'organizador', 'nota': 'adelante'})
        approval = self.espejo()['incidentes'][0]['aprobacion']
        self.assertEqual((approval['decision'], approval['por'], approval['etiqueta']),
                         ('apr', 'organizador', 'aprobada'))

    def test_staff_por_telegram_como_grupo_aparte(self):
        self.aviso()
        for n, (alias, estado) in enumerate([('Marta', 'accepted'), ('Iván', 'declined'), ('Nadia', 'declined')]):
            self.send({'type': 'tg_assignment', 'event_id': f's{n}', 'incident_id': 'tg-1', 'rol': 'medico',
                       'estado': estado, 'alias': alias, 'intento': 1})
        staff = self.espejo()['staff']
        self.assertEqual((staff['total'], staff['libres'], staff['atendiendo']), (3, 2, 1))
        self.assertEqual(staff['titulo'], 'Staff por Telegram')

    def test_chat_con_los_mensajes(self):
        self.aviso()
        self.send({'type': 'tg_assignment', 'event_id': 'a1', 'incident_id': 'tg-1', 'rol': 'medico',
                   'estado': 'accepted', 'alias': 'Marta', 'eta_min': 2, 'intento': 1})
        mensajes = self.espejo()['mensajes']
        self.assertEqual(mensajes[0]['de'], 'informante')
        self.assertIn('desplomado', mensajes[0]['texto'])
        self.assertEqual(mensajes[-1]['nombre'], 'Marta')

    # ------------------------------------------------------------------ secuencia completa
    def test_secuencia_completa_hasta_la_escalada_por_voz(self):
        for event in telegram_espejo.secuencia_demo(self.s):
            self.send(event)
        espejo = self.espejo()
        self.assertEqual(len(espejo['escaladas']), 1)
        escalada = espejo['escaladas'][0]
        self.assertEqual(escalada['rol'], 'seguridad')
        self.assertEqual(escalada['workflow'], 'mando-despacho-seguridad')
        self.assertEqual(escalada['intentos'], telegram_espejo.INTENTOS_MAX)
        item = espejo['incidentes'][0]
        self.assertEqual(item['clase'], 'escalada')
        self.assertIn('llamada por voz', item['resumen'])
        # la parte que SÍ aceptó sigue contada: una escalada no borra a quien va de camino
        self.assertTrue(any(a['estado'] == 'accepted' for a in item['asignaciones']))
        self.assertGreaterEqual(len(item['cronologia']), 9)

    def test_demo_de_operador(self):
        self.assertEqual(self.c.post('/api/espejo/demo', json={}).status_code, 401)
        out = self.c.post('/api/espejo/demo', json={'zone': 'front_pit'}, headers=self.op).json()
        self.assertTrue(out['ok'])
        self.assertEqual(len(out['escaladas']), 1)
        self.assertEqual(self.espejo()['incidentes'][0]['escalada']['workflow'], 'mando-despacho-seguridad')

    # ------------------------------------------------------------------ validación estricta
    def test_tipo_desconocido_es_422(self):
        self.send({'type': 'tg_cualquier_cosa', 'id': 'x'}, expect=422)

    def test_campos_desconocidos_y_valores_fuera_de_vocabulario(self):
        self.aviso()
        malos = [
            {'type': 'tg_incident', 'id': 'tg-2', 'texto': 'x', 'tipo': 'inventado'},
            {'type': 'tg_incident', 'id': 'tg-2', 'texto': 'x', 'gravedad': 'catastrofica'},
            {'type': 'tg_incident', 'id': 'tg-2', 'texto': 'x', 'zona': 'zona_que_no_existe'},
            {'type': 'tg_incident', 'id': 'tg-2', 'texto': 'x', 'prioridad': 99},
            {'type': 'tg_incident', 'id': 'tg-2', 'texto': 'x', 'requiere_aprobacion': 'true'},
            {'type': 'tg_incident', 'id': 'tg-2', 'texto': 'x', 'recursos_requeridos': [{'rol': 'astronauta'}]},
            {'type': 'tg_incident', 'id': 'tg-2', 'texto': 'x', 'recursos_requeridos': [{'rol': 'medico', 'cantidad': 0}]},
            {'type': 'tg_incident', 'id': 'tg-2'},
            {'type': 'tg_assignment', 'incident_id': 'tg-1', 'rol': 'medico', 'estado': 'quizas'},
            {'type': 'tg_assignment', 'incident_id': 'tg-1', 'rol': 'astronauta', 'estado': 'pending'},
            {'type': 'tg_assignment', 'incident_id': 'tg-1', 'rol': 'medico', 'estado': 'accepted', 'eta_min': 9999},
            {'type': 'tg_assignment', 'incident_id': 'tg-1', 'rol': 'medico', 'estado': 'accepted', 'from_zone': 'marte'},
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
        self.send({'type': 'tg_assignment', 'incident_id': 'tg-1', 'rol': 'medico', 'estado': 'pending',
                   'alias': '987654321'}, expect=422)
        self.send({'type': 'tg_incident', 'id': 'tg-9', 'texto': 'x', 'telefono': '+34600111222'}, expect=422)

    def test_sin_chat_id_ni_telefono_en_el_estado(self):
        for event in telegram_espejo.secuencia_demo(self.s):
            self.send(event)
        state = self.c.get('/api/state').json()
        self.assertNotIn('chat_id', json.dumps(state, ensure_ascii=False))
        # El espejo entero, campo a campo: ni un identificador de Telegram ni nada con pinta de teléfono.
        espejo = json.dumps(state['telegram_despacho'], ensure_ascii=False)
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
        self.assertEqual(len(state['telegram_despacho']['incidentes'][0]['asignaciones']), 0)

    def test_idempotencia_por_event_id(self):
        self.aviso()
        event = {'type': 'tg_assignment', 'event_id': 'repetido', 'incident_id': 'tg-1', 'rol': 'medico',
                 'estado': 'accepted', 'alias': 'Marta', 'eta_min': 4, 'intento': 1}
        self.send(event)
        self.assertTrue(self.send(event)['duplicate'])
        self.assertEqual(len(self.espejo()['incidentes'][0]['asignaciones']), 1)

    def test_token_de_webhooks(self):
        self.assertEqual(self.c.post('/hr/events', json={'type': 'tg_incident'}).status_code, 401)
        self.assertEqual(self.c.post('/hr/events', json={'type': 'tg_incident'},
                                     headers={'X-Mando-Token': 'otro'}).status_code, 401)

    def test_el_token_del_widget_no_sirve_para_el_espejo(self):
        with patch.dict(os.environ, {'HR_CHAT_TOKEN': 'token-widget'}):
            r = self.c.post('/hr/events', json={'type': 'tg_incident', 'id': 'x', 'texto': 'y'},
                            headers={'X-Mando-Token': 'token-widget'})
        self.assertEqual(r.status_code, 403, r.text)


if __name__ == '__main__':
    unittest.main()
