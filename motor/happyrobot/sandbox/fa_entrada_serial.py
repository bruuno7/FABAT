"""Sandbox 'Serializar propuesta JSON' de fa-entrada-tg (v9). Traduce la decisión del LLM (relacion) + contexto del
remitente a un MODO ejecutable por fa-despacho-tg y compone la respuesta inmediata al remitente.
input_data: chat_json, chat_id, alias, correlation_id, run_id, original_text, zone_hint, channel,
            sender_kind, role, ctx_incident_id, chat_kind, pregunta_pendiente, pregunta_de, inc_json,
            incident_type, location, description, severity, triage,
            relacion, mensaje_reenvio, roles_orden, pregunta_asistente, instruccion_asistente, instruccion_staff
Salida: payload_json (agent_reply), has_reply, mode, hito, incident_id, role, minutes, roles_orden_json, pregunta,
        instruccion_staff, zona, tipo, severity, texto, reporter_chat_id, alias, reenvio, to_chat, chat_json
"""
# --- COMMON ---
chat_id = s(input_data.get('chat_id'), 40)
texto = s(input_data.get('original_text'), 400)
inc = as_obj(input_data.get('inc_json'), {})
sender = s(input_data.get('sender_kind'), 20) or 'asistente'
role = s(input_data.get('role'), 30)
ctx_inc = s(input_data.get('ctx_incident_id'), 60)
ctx_inc = '' if ctx_inc == 'none' else ctx_inc
inc_abierto = bool(ctx_inc and inc.get('id') and inc.get('estado', 'abierto') != 'cerrado')
chat_kind = s(input_data.get('chat_kind'), 40)
pregunta_pend = s(input_data.get('pregunta_pendiente'), 200)
pregunta_de = s(input_data.get('pregunta_de'), 40)
relacion = s(input_data.get('relacion'), 40).lower()
reenvio = s(input_data.get('mensaje_reenvio'), 400) or texto
tipo = (s(input_data.get('incident_type'), 40) or 'otro').lower()
zona = s(input_data.get('location') or input_data.get('zone_hint'), 60)
if zona.lower() in ('desconocido', 'desconocida', 'no indicada', 'null', 'none'):
    zona = ''
try:
    sev = max(1, min(5, int(float(input_data.get('severity') or 3))))
except (TypeError, ValueError):
    sev = 3
roles = roles_list(input_data.get('roles_orden'))


def clean(v, n=300):
    v = s(v, n)
    return '' if v.lower() in ('null', 'none', 'ninguna', 'ninguno', 'no', '-') else v


pregunta = clean(input_data.get('pregunta_asistente'), 200)
instr_asist = clean(input_data.get('instruccion_asistente'))
instr_staff = clean(input_data.get('instruccion_staff'))
quien_rol = ROL_SUJETO.get(role, 'El equipo')

# ---- relación → modo ----
if not relacion:
    relacion = 'actualizacion' if inc_abierto else 'nuevo'
mode, hito, minutes = 'new', '', None
if chat_kind == 'staff_disponibilidad':
    mode = 'answer_availability'
elif sender == 'equipo':
    if relacion.startswith('estado_') and inc_abierto:
        mode, hito = 'staff_status', relacion[7:]
    elif relacion == 'cierre' and inc_abierto:
        mode, hito = 'staff_status', 'finalizado'
    elif relacion == 'pregunta_al_asistente' and inc_abierto:
        mode = 'staff_question'
    elif relacion in ('actualizacion', 'respuesta_a_pregunta') and inc_abierto:
        mode = 'staff_note'
    elif relacion == 'nuevo':
        mode = 'new'
    else:
        mode = 'chat'
else:
    if pregunta_de and relacion in ('respuesta_a_pregunta', 'actualizacion', 'charla') and inc_abierto:
        mode = 'answer_to_staff'
    elif relacion == 'cierre' and inc_abierto:
        mode = 'close'
    elif relacion in ('actualizacion', 'respuesta_a_pregunta', 'pregunta_al_equipo', 'charla') and inc_abierto:
        mode = 'answer_info'
    elif relacion == 'charla':
        mode = 'chat'
    else:
        mode = 'new'

# ---- respuesta inmediata al remitente ----
TIPO_ES = {'medica': 'una emergencia médica', 'incendio': 'un incendio', 'seguridad': 'un problema de seguridad',
           'agresion': 'una agresión', 'aglomeracion': 'una aglomeración', 'clima': 'una incidencia meteorológica',
           'infraestructura': 'una incidencia en las instalaciones', 'falta_recursos': 'una falta de recursos', 'otro': 'tu aviso'}
URG = {5: 'máxima urgencia', 4: 'urgencia alta', 3: 'urgencia media', 2: 'urgencia baja', 1: 'urgencia baja'}
zona_inc = inc.get('zona') or zona
if mode == 'new':
    quien = ' y '.join(A_QUIEN[r] for r in roles[:2]) if roles else 'al equipo que corresponde'
    partes = [f"He registrado {TIPO_ES.get(tipo, 'tu aviso')}{(' en ' + zona) if zona else ''} con {URG.get(sev, 'urgencia media')}."]
    if instr_asist:
        partes.append(instr_asist)
    partes.append(f"Estoy avisando ahora mismo {quien}." if roles else 'Estoy avisando al organizador para que decida a quién mandar.')
    partes.append(pregunta or 'Te confirmo en cuanto alguien esté en camino y cuánto tarda.')
    reply = ' '.join(partes)
elif mode == 'answer_availability':
    minutes = parse_minutes(texto)
    reply = ('No he entendido cuándo estarás disponible. Dime los minutos, por ejemplo «en 10 min» o «ahora».' if minutes is None
             else 'Perfecto, te marco como disponible. Te avisaré con el siguiente incidente.' if minutes == 0
             else f'Anotado: no disponible durante {minutes} min. Hasta entonces no te asignaré incidentes.')
elif mode == 'answer_to_staff':
    reply = 'Gracias, se lo paso ahora mismo al equipo.'
elif mode == 'answer_info':
    reply = ('Gracias, se lo traslado al equipo que va hacia allí.' if activos(inc) else 'Gracias, lo anoto en el aviso.')
elif mode == 'close':
    reply = 'Perfecto, doy por cerrado el aviso y se lo comunico al equipo. Si vuelve a pasar algo, escríbeme.'
elif mode == 'staff_question':
    reply = 'Se lo pregunto al asistente que dio el aviso y te paso su respuesta en cuanto conteste.'
elif mode == 'staff_note':
    reply = 'Anotado en el incidente; se lo comunico al asistente.'
elif mode == 'staff_status':
    reply = {'llegado': 'Anotado: has llegado. Aviso al asistente.', 'localizado': 'Anotado: incidencia localizada. Aviso al asistente.',
             'finalizado': 'Anotado: asistencia finalizada. Cierro el incidente y aviso al asistente. Gracias.'}.get(hito, 'Anotado.')
else:  # chat
    reply = ('Aquí estoy. Cuando te asigne un aviso te llegará con botones; si necesitas algo del asistente, pregúntamelo y se lo traslado.'
             if sender == 'equipo' else
             'Hola. Cuéntame qué ocurre y dónde (por ejemplo «una persona se ha desmayado junto al escenario») y aviso al equipo.')

payload = {'event': 'agent_reply', 'correlation_id': s(input_data.get('correlation_id') or input_data.get('run_id'), 120),
           'channel': s(input_data.get('channel'), 20) or 'telegram', 'chat_id': chat_id, 'reply_text': reply,
           'hr_run_id': s(input_data.get('run_id'), 80), 'mode': mode,
           'report': {'channel': 'telegram', 'text': texto, 'zone_hint': s(input_data.get('zone_hint'), 60), 'source': 'telegram_bridge', 'lang': 'es'},
           'extract': {'incident_type': tipo, 'sector': zona or 'desconocido', 'severity': sev,
                       'triage_color': s(input_data.get('triage'), 20) or 'desconocido', 'summary': s(input_data.get('description'), 300)}}
incident_out = ctx_inc if mode not in ('new', 'chat', 'answer_availability') else ('none' if mode != 'new' else s(input_data.get('correlation_id'), 60))
output = {'payload_json': dumps(payload), 'has_reply': 'true' if (chat_id and reply) else 'false', 'mode': mode, 'hito': hito,
          'relacion': relacion, 'incident_id': incident_out, 'role': role, 'minutes': -1 if minutes is None else minutes,
          'roles_orden_json': dumps(roles), 'pregunta': pregunta, 'instruccion_staff': instr_staff, 'zona': zona, 'tipo': tipo,
          'severity': sev, 'texto': texto, 'reporter_chat_id': chat_id, 'alias': s(input_data.get('alias'), 40),
          'reenvio': reenvio, 'to_chat': pregunta_de, 'chat_json': s(input_data.get('chat_json'), 2000)}
