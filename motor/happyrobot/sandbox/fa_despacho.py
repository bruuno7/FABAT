"""Sandbox 'Elegir efectivo' de fa-despacho-tg (v6). Ejecuta el MODO decidido en fa-entrada-tg.
input_data: seats_json, inc_json, mode, hito, incident_id, role, minutes, texto, tipo, zona, gravedad, prioridad,
            alias_informante, reporter_chat_id (= chat del remitente), correlation_id, summary, rol, roles_orden,
            pregunta, instruccion_staff, reenvio, to_chat, chat_json (estado actual del chat remitente), now
Salida: dispatched/payload_json (msg al puesto), has_reporter/reporter_json, has_extra/extra_json, has_extra2/extra2_json,
        incident_id/incident_json, seats_key/seats_json, chat_key/chat_json (remitente), chat2_key/chat2_json (otro chat)
"""
# --- COMMON ---
seats = as_obj(input_data.get('seats_json'), {})
inc = as_obj(input_data.get('inc_json'), {})
now = s(input_data.get('now'), 40)
mode = s(input_data.get('mode'), 30) or 'new'
hito = s(input_data.get('hito'), 20)
texto = s(input_data.get('texto')) or s(input_data.get('summary'))
reenvio = s(input_data.get('reenvio')) or texto
tipo_in = (s(input_data.get('tipo'), 40) or 'otro').lower()
tipo = TIPO.get(tipo_in, 'otro')
zona = s(input_data.get('zona'), 60)
if zona.lower() in ('desconocido', 'desconocida', 'null', 'none'):
    zona = ''
grav = gravedad(input_data.get('gravedad'), input_data.get('prioridad'))
try:
    prioridad = int(float(input_data.get('prioridad') or 5))
except (TypeError, ValueError):
    prioridad = 5
correlation = s(input_data.get('correlation_id'), 120)
sender = s(input_data.get('reporter_chat_id'), 40)
sender_role = s(input_data.get('role'), 30) or role_of_chat(seats, sender)
rol_pedido = s(input_data.get('rol'), 30).lower() or None
roles = roles_list(input_data.get('roles_orden'))
pregunta = s(input_data.get('pregunta'), 200)
instr_staff = s(input_data.get('instruccion_staff'), 300)
to_chat = s(input_data.get('to_chat'), 40)
chat_in = s(input_data.get('chat_json'), 2000)
if inc.get('estado') == 'cerrado' and mode in ('answer_info', 'answer_to_staff', 'close'):
    mode = 'new'  # sobre un incidente cerrado, cualquier novedad es un aviso nuevo

out = {'mode': mode, 'incident_id': inc.get('id') or s(input_data.get('incident_id'), 60) or 'none', 'dispatched': 'false',
       'reason': '', 'assignment_id': '', 'rol': '', 'alias': '', 'chat_id': '', 'payload_json': '',
       'has_reporter': 'false', 'reporter_json': '', 'has_extra': 'false', 'extra_json': '', 'has_extra2': 'false', 'extra2_json': '',
       'write_seats': 'false', 'seats_json': dumps(seats),
       'chat_key': f'fa:chat:{sender}' if sender else 'fa:chat:none', 'chat_json': chat_in,
       'chat2_key': 'fa:chat:none', 'chat2_json': '', 'seats_claimed': sum(1 for r in SEATS if seats.get(r))}
msgs = []  # cola de mensajes → reporter_json, extra_json, extra2_json


def say(chat, text, **kw):
    if chat:
        m = send(chat, text)
        m.update(kw)
        msgs.append(m)


def set_chat(key_chat, value, second=False):
    k, v = ('chat2_key', 'chat2_json') if second else ('chat_key', 'chat_json')
    out[k] = f'fa:chat:{key_chat}' if key_chat else 'fa:chat:none'
    out[v] = value


def touch_seats():
    out.update(write_seats='true', seats_json=dumps(seats))


def libera_puestos():
    for a in inc.get('assignments', []):
        row = seats.get(a.get('rol'), {})
        if row.get('incident_id') == inc.get('id'):
            row.pop('incident_id', None)
            touch_seats()


def dispatch():
    pick = next_seat(seats, inc, now, rol_pedido)
    if pick is None:
        out['reason'] = 'no_staff'
        org = seats.get('organizador')
        if org and org.get('chat_id'):
            out.update(dispatched='true', chat_id=org['chat_id'], rol='organizador', alias=org.get('alias') or 'organizador',
                       payload_json=dumps(send(org['chat_id'], f"SIMULACIÓN · Aviso sin nadie disponible: {inc['tipo']} en {inc.get('zona') or 'zona no indicada'} "
                                                                f"({inc['gravedad']}). {inc['texto'][:200]}\n\nNo hay puesto libre para cubrirlo: decide tú.")))
        say(inc.get('reporter_chat_id'), 'Ahora mismo no hay ningún equipo libre para tu aviso; lo he pasado al organizador para que decida. Te aviso en cuanto haya novedades.')
        return None
    a = create_assignment(inc, pick, now)
    seats[pick['rol']]['incident_id'] = inc['id']
    touch_seats()
    out.update(dispatched='true', assignment_id=a['id'], rol=a['rol'], alias=a['alias'], chat_id=a['chat_id'], payload_json=dumps(offer_message(a, inc)))
    return a


rep = inc.get('reporter_chat_id', '')
quien = ROL_SUJETO.get(sender_role, 'El equipo')

if mode == 'answer_availability':
    try:
        minutes = int(float(input_data.get('minutes')))
    except (TypeError, ValueError):
        minutes = -1
    if sender_role in seats and minutes >= 0:
        n = parse_iso(now)
        seats[sender_role]['busy_until'] = (n + timedelta(minutes=minutes)).isoformat(timespec='seconds') if (n and minutes > 0) else ''
        touch_seats()
        set_chat(sender, chat_state('staff_activo', role=sender_role, incident_id=seats[sender_role].get('incident_id'), last_at=now)
                 if seats[sender_role].get('incident_id') else '')
    out['incident_json'] = ''
elif mode == 'chat':
    out['incident_json'] = ''
elif mode in ('answer_info', 'answer_to_staff', 'close') and inc.get('id'):
    inc['last_at'] = now
    inc.setdefault('actualizaciones', []).append({'t': now, 'de': 'asistente', 'texto': texto})
    if zona and not inc.get('zona'):
        inc['zona'] = zona
    if mode == 'close':
        inc['estado'] = 'cerrado'
        inc['cerrado_por'] = 'asistente'
        for a in activos(inc):
            say(a['chat_id'], f"El asistente informa de que el aviso en {inc.get('zona') or 'la zona indicada'} está resuelto: «{reenvio[:200]}». Incidencia cerrada.")
        libera_puestos()
        set_chat(sender, '')
    elif mode == 'answer_to_staff':
        say(to_chat, f"Respuesta del asistente a tu pregunta: «{reenvio[:300]}»")
        set_chat(sender, chat_state('asistente_activo', incident_id=inc['id'], last_at=now))
    else:
        act = activos(inc)
        if act:
            say(act[-1]['chat_id'], f"Dato nuevo del asistente sobre el aviso en {inc.get('zona') or 'zona sin confirmar'}: «{reenvio[:250]}»")
        else:
            a = dispatch()
            if a:
                say(rep, f"Gracias. Estoy avisando {A_QUIEN.get(a['rol'], a['rol'])}. Te confirmo en cuanto esté en camino.")
        set_chat(sender, chat_state('asistente_activo', incident_id=inc['id'], last_at=now))
    out['incident_json'] = dumps(inc)
elif mode in ('staff_question', 'staff_note', 'staff_status') and inc.get('id'):
    inc['last_at'] = now
    if mode == 'staff_question':
        inc.setdefault('preguntas', []).append({'t': now, 'de': sender_role, 'texto': reenvio})
        say(rep, f"{quien} pregunta: «{reenvio[:300]}». Responde aquí y se lo paso.")
        set_chat(rep, chat_state('asistente_activo', incident_id=inc['id'], pregunta=reenvio[:200], pregunta_de=sender, last_at=now), second=True)
    elif mode == 'staff_note':
        inc.setdefault('actualizaciones', []).append({'t': now, 'de': sender_role, 'texto': reenvio})
        say(rep, f"{quien} informa: «{reenvio[:300]}»")
    else:
        mine = next((a for a in reversed(inc.get('assignments', [])) if a.get('chat_id') == sender), None) or (activos(inc) or [None])[-1]
        if mine is not None:
            mine.setdefault('hitos', {})[hito] = now
            mine['updated_at'] = now
        zona_txt = inc.get('zona') or 'la zona indicada'
        plural = sender_role in PLURAL
        if hito == 'llegado':
            say(rep, f"{quien} {'han' if plural else 'ha'} llegado a {zona_txt}.")
        elif hito == 'localizado':
            say(rep, f"{quien} ya {'han' if plural else 'ha'} localizado la incidencia y {'están' if plural else 'está'} actuando.")
        elif hito == 'finalizado':
            inc['estado'] = 'cerrado'
            inc['cerrado_por'] = sender_role
            if mine is not None:
                mine['estado'] = 'done'
            say(rep, f"{quien} {'dan' if plural else 'da'} por finalizada la asistencia. Incidencia cerrada. Gracias por avisar; si vuelve a pasar algo, escríbeme.")
            libera_puestos()
            set_chat(rep, '', second=True)
            set_chat(sender, '')
    if mode != 'staff_status' or hito != 'finalizado':
        set_chat(sender, chat_state('staff_activo', role=sender_role, incident_id=inc['id'], last_at=now))
    out['incident_json'] = dumps(inc)
else:  # new
    iid = s(input_data.get('incident_id'), 60) or ('tg-' + correlation)[:60] or 'tg-sin-id'
    if iid == 'none':
        iid = ('tg-' + correlation)[:60]
    if not inc.get('id') or inc.get('estado') == 'cerrado':
        inc = {'id': iid, 'estado': 'abierto', 'texto': texto, 'tipo': tipo, 'tipo_in': tipo_in, 'zona': zona, 'gravedad': grav, 'prioridad': prioridad,
               'alias_informante': s(input_data.get('alias_informante'), 40) or 'Asistente', 'correlation_id': correlation,
               'created_at': now, 'last_at': now, 'assignments': [], 'reporter_chat_id': sender, 'roles_orden': roles, 'instruccion_staff': instr_staff}
    else:
        if roles:
            inc['roles_orden'] = roles
        inc['last_at'] = now
    out['incident_id'] = inc['id']
    if not texto:
        out['reason'] = 'sin_texto'
    else:
        a = dispatch()
        if a:
            set_chat(a['chat_id'], chat_state('staff_activo', role=a['rol'], incident_id=inc['id'], assignment_id=a['id'], last_at=now), second=True)
    set_chat(sender, chat_state('asistente_activo', incident_id=inc['id'], pregunta=pregunta, last_at=now))
    out['incident_json'] = dumps(inc)

for i, key in enumerate(('reporter', 'extra', 'extra2')):
    if i < len(msgs):
        out.update({f'has_{key}': 'true', f'{key}_json': dumps(msgs[i])})
out['incident_key'] = f"fa:inc:{out['incident_id']}" if out.get('incident_json') else 'fa:inc:none'
out['seats_key'] = 'fa:seats' if out['write_seats'] == 'true' else 'fa:scratch:seats'
output = out
