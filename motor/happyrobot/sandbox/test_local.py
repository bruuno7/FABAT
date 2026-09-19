"""Simula el motor de Sandbox de HappyRobot: exec del código con input_data, recoge `output`. Redis simulado con un dict.
Encadena fa-entrada-tg (contexto → serial) y fa-despacho-tg igual que la plataforma; el LLM se simula con `relacion`."""
import json, pathlib

HERE = pathlib.Path(__file__).parent
COMMON = (HERE / 'fa_common.py').read_text()


def build(name):
    return (HERE / f'{name}.py').read_text().replace('# --- COMMON ---', COMMON)


def run(name, **input_data):
    ns = {'input_data': {k: ('' if v is None else v) for k, v in input_data.items()}}
    exec(build(name), ns)
    out = ns['output']
    assert all(isinstance(v, (str, int, float)) for v in out.values()), f'salida no plana: {out}'
    return out


redis = {}
NOW = '2026-09-19T14:00:00Z'
sent = []  # (chat_id, text) — todo lo que saldría por Telegram


def deliver(out, *keys):
    for k in keys:
        if out.get(f'has_{k}') == 'true' or (k in ('payload', 'outbound', 'next') and out.get(f'{k}_json')):
            m = json.loads(out[f'{k}_json'])
            sent.append((m['chat_id'], m['text']))


def writes(out):
    """Aplica las escrituras Redis que haría el workflow."""
    if out.get('incident_json') and out.get('incident_id') not in ('', 'none'):
        redis[f"fa:inc:{out['incident_id']}"] = out['incident_json']
    if out.get('seats_key') == 'fa:seats':
        redis['fa:seats'] = out['seats_json']
    for k in ('chat', 'chat2'):
        key = out.get(f'{k}_key')
        if key and key != 'fa:chat:none':
            redis[key] = out[f'{k}_json']


def entrada(chat_id, text, relacion, corr, alias='X', tipo='otro', location='', severity='3', roles='[]', pregunta='', instr_a='', instr_s='', reenvio=''):
    """fa-entrada-tg: Leer chat → Leer puestos → Contexto → Leer incidente → (LLM simulado) → Serial → Despacho."""
    ctx = run('fa_contexto', chat_json=redis.get(f'fa:chat:{chat_id}', ''), seats_json=redis['fa:seats'], chat_id=chat_id, now=NOW)
    inc_json = redis.get(f"fa:inc:{ctx['incident_id']}", '')
    o = run('fa_entrada_serial', chat_json=redis.get(f'fa:chat:{chat_id}', ''), chat_id=chat_id, alias=alias, correlation_id=corr, run_id='r',
            original_text=text, zone_hint='', channel='telegram', sender_kind=ctx['sender_kind'], role=ctx['role'],
            ctx_incident_id=ctx['incident_id'], chat_kind=ctx['chat_kind'], pregunta_pendiente=ctx['pregunta_pendiente'],
            pregunta_de=ctx['pregunta_de'], inc_json=inc_json, incident_type=tipo, location=location, description=text,
            severity=severity, triage='', relacion=relacion, mensaje_reenvio=reenvio, roles_orden=roles,
            pregunta_asistente=pregunta, instruccion_asistente=instr_a, instruccion_staff=instr_s)
    sent.append((chat_id, json.loads(o['payload_json'])['reply_text']))
    d = run('fa_despacho', seats_json=redis['fa:seats'], inc_json=redis.get(f"fa:inc:{o['incident_id']}", ''), mode=o['mode'], hito=o['hito'],
            incident_id=o['incident_id'], role=o['role'], minutes=o['minutes'], texto=o['texto'], tipo=o['tipo'], zona=o['zona'],
            gravedad='', prioridad=o['severity'], alias_informante=o['alias'], reporter_chat_id=o['reporter_chat_id'], correlation_id=corr,
            summary='', rol='', roles_orden=o['roles_orden_json'], pregunta=o['pregunta'], instruccion_staff=o['instruccion_staff'],
            reenvio=o['reenvio'], to_chat=o['to_chat'], chat_json=o['chat_json'], now=NOW)
    deliver(d, 'payload', 'reporter', 'extra', 'extra2')
    writes(d)
    return o, d


def boton(chat_id, cbd, alias='X'):
    aid = cbd.split('|')[1]
    iid = aid.split('~')[0]
    o = run('fa_respuesta', inc_json=redis.get(f'fa:inc:{iid}', ''), seats_json=redis['fa:seats'], kind='', callback_data=cbd,
            assignment_id='', chat_id=chat_id, alias=alias, now=NOW)
    deliver(o, 'outbound', 'next', 'reporter')
    writes(o)
    return o


def last_to(chat):
    return next(t for c, t in reversed(sent) if c == chat)


# 1. roles
for role, chat, alias in [('medico', '111', 'Lucía'), ('policia', '222', 'Marc'), ('organizador', '333', 'Bruno')]:
    o = run('fa_rol', seats_json=redis.get('fa:seats', ''), action='claim', role=role, chat_id=chat, alias=alias, now=NOW)
    assert o['ok'] == 'true', o
    redis['fa:seats'] = o['seats_json']
o = run('fa_rol', seats_json=redis['fa:seats'], action='claim', role='medico', chat_id='999', alias='Intruso', now=NOW)
assert o['reason'] == 'taken'
print('1 roster OK')

# 2. (a) aviso médico con pregunta de zona → respuesta = actualización (aunque el LLM diga 'nuevo' por despiste, la pregunta manda)
o, d = entrada('555', 'Una persona se ha desmayado', 'nuevo', 'tg-555-1', tipo='medica', severity='4', roles='["medico","staff_entradas"]',
               pregunta='¿En qué zona estás?', instr_a='No la muevas.', instr_s='Llevar botiquín y DEA.')
assert o['mode'] == 'new' and d['rol'] == 'medico' and d['chat_id'] == '111', (o, d)
assert json.loads(redis['fa:chat:555'])['kind'] == 'asistente_activo' and json.loads(redis['fa:chat:111'])['kind'] == 'staff_activo'
assert json.loads(redis['fa:seats'])['medico']['incident_id'] == 'tg-555-1'
o, d = entrada('555', 'En el foso, delante del escenario', 'respuesta_a_pregunta', 'tg-555-2', location='foso')
assert o['mode'] == 'answer_info' and d['has_reporter'] == 'true', (o, d)
assert json.loads(redis['fa:inc:tg-555-1'])['zona'] == 'foso'
assert 'Dato nuevo' in last_to('111')
print('2 pregunta zona → actualización OK:', last_to('111')[:60])

# 3. (b) sin pregunta previa, el asistente añade info → actualización, no incidente nuevo
o, d = entrada('555', 'Ahora respira pero no responde', 'actualizacion', 'tg-555-3')
assert o['mode'] == 'answer_info' and o['incident_id'] == 'tg-555-1', o
assert 'fa:inc:tg-555-3' not in redis
print('3 añadido sin pregunta → actualización OK')

# 4. (c) el médico acepta, pregunta al asistente, el asistente responde → llega al médico
o = boton('111', 'acc|tg-555-1~1', alias='Lucía')
assert o['estado'] == 'accepted' and 'va hacia foso' in last_to('555')
o = boton('111', 'eta|tg-555-1~1|5', alias='Lucía')
assert 'He llegado' in o['outbound_json'] and 'llega en unos 5' in last_to('555')
o, d = entrada('111', '¿Se sabe si está consciente? ¿Hay más heridos?', 'pregunta_al_asistente', 'tg-111-1', reenvio='¿Está consciente? ¿Hay más heridos?')
assert o['mode'] == 'staff_question' and d['has_reporter'] == 'true', (o, d)
assert 'El equipo médico pregunta' in last_to('555')
st = json.loads(redis['fa:chat:555'])
assert st['pregunta_de'] == '111' and st['incident_id'] == 'tg-555-1', st
o, d = entrada('555', 'Sí, está consciente y solo es ella', 'respuesta_a_pregunta', 'tg-555-4', reenvio='Está consciente y solo es ella')
assert o['mode'] == 'answer_to_staff', o
assert 'Respuesta del asistente' in last_to('111') and 'consciente' in last_to('111')
assert 'pregunta_de' not in json.loads(redis['fa:chat:555'])
print('4 pregunta equipo ↔ respuesta asistente OK:', last_to('111')[:70])

# 5. (d) botones llegado / localizado / finalizado → asistente informado; finalizado cierra
o = boton('111', 'lle|tg-555-1~1', alias='Lucía')
assert o['estado'] == 'llegado' and 'ha llegado a foso' in last_to('555') and 'Localizado' in o['outbound_json'] and 'He llegado' not in o['outbound_json']
o = boton('111', 'enc|tg-555-1~1', alias='Lucía')
assert 'localizado' in last_to('555')
o = boton('111', 'fin|tg-555-1~1', alias='Lucía')
assert o['estado'] == 'cerrado' and 'finalizada' in last_to('555') and json.loads(redis['fa:inc:tg-555-1'])['estado'] == 'cerrado'
assert 'incident_id' not in json.loads(redis['fa:seats'])['medico'] and redis['fa:chat:111'] == '' and redis['fa:chat:555'] == ''
o = boton('111', 'lle|tg-555-1~1', alias='Lucía')
assert o['estado'] == 'cerrado'  # botón tardío sobre incidente cerrado
print('5 llegado/localizado/finalizado OK')

# 6. (g) tras el cierre, el asistente escribe otra cosa → incidente NUEVO
o, d = entrada('555', 'Hay una pelea en el acceso A', 'nuevo', 'tg-555-5', tipo='seguridad', location='acceso A', roles='["policia"]')
assert o['mode'] == 'new' and d['rol'] == 'policia' and d['incident_id'] == 'tg-555-5', (o, d)
print('6 tras cierre → nuevo OK')

# 7. (e) el policía informa por texto que ha llegado y luego que ha terminado → asistente informado y cierre
o = boton('222', 'acc|tg-555-5~1', alias='Marc')
o, d = entrada('222', 'ya estoy aquí en el acceso A', 'estado_llegado', 'tg-222-1')
assert o['mode'] == 'staff_status' and o['hito'] == 'llegado' and 'ha llegado' in last_to('555'), (o, d)
o, d = entrada('222', 'listo, ya está todo tranquilo, nos vamos', 'estado_finalizado', 'tg-222-2')
assert o['hito'] == 'finalizado' and json.loads(redis['fa:inc:tg-555-5'])['estado'] == 'cerrado' and 'finalizada' in last_to('555')
assert 'incident_id' not in json.loads(redis['fa:seats'])['policia']
print('7 estados por texto OK')

# 8. (f) el asistente dice que está resuelto → cierre e informe al equipo activo
o, d = entrada('777', 'Alguien ha vomitado en la barra 2', 'nuevo', 'tg-777-1', tipo='menor', location='barra 2', roles='["staff_entradas","medico"]')
assert d['rol'] == 'medico', d  # staff_entradas no reclamado → siguiente
o = boton('111', 'acc|tg-777-1~1', alias='Lucía')
o, d = entrada('777', 'Ya no hace falta, se ha recuperado y se ha ido con sus amigos', 'cierre', 'tg-777-2', reenvio='se ha recuperado y se ha ido')
assert o['mode'] == 'close' and json.loads(redis['fa:inc:tg-777-1'])['estado'] == 'cerrado', o
assert 'resuelto' in last_to('111') and redis['fa:chat:777'] == ''
print('8 cierre por el asistente OK')

# 9. (h) un puesto escribe sin incidente activo → charla, no se crea incidente
n = len([k for k in redis if k.startswith('fa:inc:')])
o, d = entrada('222', 'hola, ¿todo bien?', 'charla', 'tg-222-3')
assert o['mode'] == 'chat' and len([k for k in redis if k.startswith('fa:inc:')]) == n, o
print('9 charla del equipo sin incidente OK')

# 10. disponibilidad tras "No puedo" y cerrojo primer-acepta-gana
o, d = entrada('888', 'Humo en los baños', 'nuevo', 'tg-888-1', tipo='incendio', location='baños', severity='5', roles='["bomberos","policia"]')
assert d['rol'] == 'policia'  # bomberos no reclamado
o = boton('222', 'dec|tg-888-1~1', alias='Marc')
assert 'disponible' in o['outbound_json'] and json.loads(redis['fa:chat:222'])['kind'] == 'staff_disponibilidad'
assert o['has_next'] == 'true'  # siguiente: organizador o médico
o, d = entrada('222', 'en 15 min', 'charla', 'tg-222-4')
assert o['mode'] == 'answer_availability' and o['minutes'] == 15 and json.loads(redis['fa:seats'])['policia']['busy_until'].startswith('2026-09-19T14:15')
nxt = json.loads(redis['fa:inc:tg-888-1'])['assignments'][-1]
o = boton(nxt['chat_id'], f"acc|{nxt['id']}")
assert o['estado'] == 'accepted'
print('10 disponibilidad + siguiente OK')

# 11. incidente caducado (>45 min) → nuevo
redis['fa:chat:555'] = json.dumps({'kind': 'asistente_activo', 'incident_id': 'tg-555-5', 'last_at': '2026-09-19T12:00:00Z'})
ctx = run('fa_contexto', chat_json=redis['fa:chat:555'], seats_json=redis['fa:seats'], chat_id='555', now=NOW)
assert ctx['incident_id'] == 'none'
print('11 caducidad OK')

print('\nTODO OK —', len(sent), 'mensajes simulados')
