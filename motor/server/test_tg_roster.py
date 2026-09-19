"""Directorio rol↔chat_id y cerrojo primer-acc-gana del despacho por Telegram.

    uv run --project motor/server python -m unittest motor.server.test_tg_roster -v
"""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from motor.server.app import create_app

SECRET = 'hr-test'


class TelegramRosterTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'MANDO_PUBLIC_URL': 'https://test.invalid', 'MANDO_OPERATORS': '',
                                           'MANDO_OPERATOR_TOKEN': 'operator-test',
                                           'TELEGRAM_MODE': 'off', 'MANDO_DB': 'off'})
        self.env.start()
        self.app = create_app('demo-gates', threaded=False, secret=SECRET, playbook='seed', local_params=False)
        self.s = self.app.state.session
        self.c = TestClient(self.app)
        self.hr = {'X-Mando-Token': SECRET}

    def tearDown(self):
        self.s.close()
        self.app.state.session.close()
        self.app.state.tg_roster.close()
        self.app.state.chat.stop()
        self.env.stop()

    def post(self, path, payload, expect=200):
        r = self.c.post(path, json=payload, headers=self.hr)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json() if r.status_code < 400 else r

    def test_claim_release_and_chat_id_stays_private(self):
        out = self.post('/hr/tg/roster', {'action': 'claim', 'role': 'medico',
                                          'chat_id': '1001', 'alias': 'Marta'})
        self.assertTrue(out['ok'])
        self.assertEqual(out['claimed'], 1)
        seats = {s['rol']: s for s in self.c.get('/hr/tg/roster', headers=self.hr).json()['seats']}
        self.assertEqual(seats['medico']['chat_id'], '1001')
        taken = self.post('/hr/tg/roster', {'action': 'claim', 'role': 'medico',
                                            'chat_id': '1002', 'alias': 'Iván'})
        self.assertFalse(taken['ok'])
        self.assertEqual(taken['reason'], 'taken')
        state = json.dumps(self.c.get('/api/state').json(), ensure_ascii=False)
        self.assertNotIn('1001', state)
        self.assertNotIn('chat_id', state)
        self.post('/hr/tg/roster', {'action': 'release', 'chat_id': '1001'})
        seats = {s['rol']: s for s in self.c.get('/hr/tg/roster', headers=self.hr).json()['seats']}
        self.assertFalse(seats['medico']['claimed'])

    def test_dispatch_sends_buttons_to_claimed_seat(self):
        self.post('/hr/tg/roster', {'action': 'claim', 'role': 'medico',
                                    'chat_id': '2002', 'alias': 'Marta'})
        out = self.post('/hr/tg/dispatch', {
            'texto': 'Una persona se ha desplomado junto a la valla (simulación)',
            'tipo': 'medica', 'zona': 'front_pit', 'severity': 5,
            'correlation_id': 'tg-200-1',
        })
        self.assertTrue(out['dispatched'])
        self.assertEqual(out['rol'], 'medico')
        self.assertEqual(out['chat_id'], '2002')
        self.assertEqual(out['outbound']['event'], 'telegram_send')
        keys = {btn['callback_data'][:3] for row in out['outbound']['reply_markup']['inline_keyboard']
                for btn in row}
        self.assertEqual(keys, {'acc', 'dec'})
        espejo = self.c.get('/api/state').json()['telegram']
        self.assertEqual(espejo['asignaciones'][0]['estado'], 'pending')
        self.assertEqual(espejo['asignaciones'][0]['alias'], 'Marta')
        self.assertNotIn('chat_id', json.dumps(espejo))

    def test_first_acc_wins_and_second_is_covered(self):
        self.post('/hr/tg/roster', {'action': 'claim', 'role': 'policia',
                                    'chat_id': '31', 'alias': 'Nadia'})
        self.post('/hr/tg/roster', {'action': 'claim', 'role': 'bomberos',
                                    'chat_id': '32', 'alias': 'Luis'})
        first = self.post('/hr/tg/dispatch', {
            'texto': 'Pelea en el acceso A (simulación)', 'tipo': 'agresion',
            'zona': 'gate_a', 'severity': 3, 'id': 'tg-pelea',
        })
        self.assertEqual(first['rol'], 'policia')
        acc = self.post('/hr/tg/staff-response', {
            'kind': 'acc', 'assignment_id': first['assignment_id'],
            'chat_id': '31', 'alias': 'Nadia',
        })
        self.assertEqual(acc['estado'], 'accepted')
        self.assertIn('ETA', acc['outbound']['text'])
        # Un segundo acc del mismo rol (otro chat no debería tener el botón, pero el cerrojo cubre).
        self.app.state.tg_roster._db().execute(
            """INSERT INTO tg_assignments(id, incident_id, rol, alias, chat_id, estado, intento,
               correlation_id, created_at, updated_at)
               VALUES('asg-rival','tg-pelea','policia','Bruno','99','pending',2,'','t','t')""")
        self.app.state.tg_roster._db().commit()
        covered = self.post('/hr/tg/staff-response', {
            'kind': 'acc', 'assignment_id': 'asg-rival',
            'chat_id': '99', 'alias': 'Bruno',
        })
        self.assertEqual(covered['estado'], 'covered')
        estados = [a['estado'] for a in self.c.get('/api/state').json()['telegram']['asignaciones']
                   if a['rol'] == 'policia']
        self.assertIn('accepted', estados)
        self.assertIn('covered', estados)

    def test_decline_reasigns_next_seat(self):
        self.post('/hr/tg/roster', {'action': 'claim', 'role': 'policia',
                                    'chat_id': '41', 'alias': 'Iván'})
        self.post('/hr/tg/roster', {'action': 'claim', 'role': 'bomberos',
                                    'chat_id': '42', 'alias': 'Luis'})
        first = self.post('/hr/tg/dispatch', {
            'texto': 'Humo en restauración (simulación)', 'tipo': 'incendio',
            'zona': 'food_court', 'severity': 4, 'id': 'tg-humo',
        })
        self.assertEqual(first['rol'], 'bomberos')
        dec = self.post('/hr/tg/staff-response', {
            'kind': 'dec', 'assignment_id': first['assignment_id'],
            'chat_id': '42', 'alias': 'Luis',
        })
        self.assertEqual(dec['estado'], 'declined')
        self.assertEqual(dec['next']['rol'], 'policia')
        self.assertEqual(dec['next_outbound']['chat_id'], '41')
        eta = self.post('/hr/tg/staff-response', {
            'kind': 'eta', 'assignment_id': dec['next']['assignment_id'],
            'chat_id': '41', 'callback_data': f"eta|{dec['next']['assignment_id']}|5",
            'alias': 'Iván',
        })
        self.assertEqual(eta['eta_min'], 5)
        loc = self.post('/hr/tg/staff-response', {
            'kind': 'loc', 'assignment_id': dec['next']['assignment_id'],
            'chat_id': '41', 'callback_data': f"loc|{dec['next']['assignment_id']}|gate_a",
            'alias': 'Iván',
        })
        self.assertEqual(loc['from_zone'], 'gate_a')
        row = next(a for a in self.c.get('/api/state').json()['telegram']['asignaciones']
                   if a['alias'] == 'Iván' and a['estado'] == 'accepted')
        self.assertEqual((row['eta_min'], row['desde_zona']), (5, 'gate_a'))

    def test_roster_requires_secret(self):
        self.assertEqual(self.c.get('/hr/tg/roster').status_code, 401)
        self.assertEqual(self.c.post('/hr/tg/dispatch', json={'texto': 'x'}).status_code, 401)


if __name__ == '__main__':
    unittest.main()
