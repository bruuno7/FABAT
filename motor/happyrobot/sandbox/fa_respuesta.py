"""Sandbox 'Aplicar respuesta' de fa-respuesta-tg (v5): botones del personal.
kinds: acc (acepto) · dec (no puedo) · eta|min · loc|zona · lle (he llegado) · enc (localizado) · fin (finalizado) · apr/vet
input_data: inc_json, seats_json, kind, callback_data, assignment_id, chat_id, alias, now
Salida: estado, has_outbound/outbound_json (al puesto), has_next/next_json (siguiente puesto u organizador),
        has_reporter/reporter_json (al asistente), incident_json, seats_key/seats_json, chat_key/chat_json (puesto),
        chat2_key/chat2_json (asistente), error
"""
# --- COMMON ---
inc = as_obj(input_data.get('inc_json'), {})
seats = as_obj(input_data.get('seats_json'), {})
now = s(input_data.get('now'), 40)
kind = s(input_data.get('kind'), 16).lower()
aid = s(input_data.get('assignment_id'), 80)
extra = ''
cbd = s(input_data.get('callback_data'), 64)
if cbd:
    parts = cbd.replace(':', '|').split('|')
    kind = (parts[0] or kind).lower()[:16]
    if len(parts) > 1 and not aid:
        aid = parts[1]
    if len(parts) > 2:
        extra = parts[2]
chat_id = s(input_data.get('chat_id'), 40)
alias = s(input_data.get('alias'), 40)

out = {'estado': 'error', 'incident_id': inc.get('id', ''), 'assignment_id': aid, 'rol': '', 'alias': alias,
       'has_outbound': 'false', 'outbound_json': '', 'has_next': 'false', 'next_json': '',
       'has_reporter': 'false', 'reporter_json': '', 'error': '', 'write_seats': 'false', 'seats_json': dumps(seats),
       'chat_key': 'fa:chat:none', 'chat_json': '',
       'chat2_key': 'fa:chat:none', 'chat2_json': ''}


def tell_reporter(text):
    chat = inc.get('reporter_chat_id')
    if chat:
        out.update(has_reporter='true', reporter_json=dumps(send(chat, text)))


def touch_seats():
    out.update(write_seats='true', seats_json=dumps(seats))


fila = next((a for a in inc.get('assignments', []) if a.get('id') == aid), None)
if not inc.get('id'):
    out['error'] = 'incidente_no_encontrado'
elif fila is None:
    out['error'] = 'asignacion_no_encontrada'
elif chat_id and fila.get('chat_id') != chat_id:
    out['error'] = 'boton_de_otro_chat'
elif inc.get('estado') == 'cerrado' and kind not in ('apr', 'vet'):
    out.update(estado='cerrado', has_outbound='true', outbound_json=dumps(send(fila['chat_id'], 'Este incidente ya está cerrado. Gracias.')))
else:
    alias = alias or fila.get('alias') or ''
    rol = fila['rol']
    out['rol'] = rol
    out['alias'] = alias
    fila['updated_at'] = now
    inc['last_at'] = now
    quien = ROL_SUJETO.get(rol, rol)
    zona = inc.get('zona') or 'tu posición'
    plural = rol in PLURAL
    out['chat_key'] = f"fa:chat:{fila['chat_id']}"
    out['chat_json'] = chat_state('staff_activo', role=rol, incident_id=inc['id'], assignment_id=aid, last_at=now)
    if kind == 'acc':
        winner = next((a for a in inc['assignments'] if a.get('rol') == rol and a.get('estado') == 'accepted' and a.get('id') != aid), None)
        if winner:
            fila.update(estado='covered', alias=alias)
            out.update(estado='covered', has_outbound='true', outbound_json=dumps(send(fila['chat_id'], f"Este aviso ya lo cubre {winner.get('alias')} (simulación). Gracias.")))
        else:
            fila.update(estado='accepted', alias=alias)
            out['estado'] = 'accepted'
            if rol in seats:
                seats[rol]['incident_id'] = inc['id']
                touch_seats()
            if fila.get('eta_min') is None:
                out.update(has_outbound='true', outbound_json=dumps(eta_loc_message(fila)))
            tell_reporter(f"{quien} ({alias or 'en servicio'}) ya {'van' if plural else 'va'} hacia {zona}. En un momento te digo cuánto tarda.")
    elif kind == 'dec':
        fila.update(estado='declined', alias=alias, motivo='no puede acudir')
        if seats.get(rol, {}).get('incident_id') == inc['id']:
            seats[rol].pop('incident_id', None)
            touch_seats()
        pick = next_seat(seats, inc, now)
        out.update(estado='declined', has_outbound='true',
                   outbound_json=dumps(send(fila['chat_id'], 'Anotado, busco a otro. ¿Cuándo volverás a estar disponible? Responde con los minutos (p. ej. «en 10 min») o «ahora».')),
                   chat_json=chat_state('staff_disponibilidad', role=rol, incident_id=inc['id'], asked_at=now))
        if pick:
            nxt = create_assignment(inc, pick, now)
            seats[pick['rol']]['incident_id'] = inc['id']
            touch_seats()
            out.update(has_next='true', next_json=dumps(offer_message(nxt, inc)),
                       chat2_key=f"fa:chat:{nxt['chat_id']}",
                       chat2_json=chat_state('staff_activo', role=nxt['rol'], incident_id=inc['id'], assignment_id=nxt['id'], last_at=now))
            tell_reporter(f"{quien} no puede acudir ahora; estoy avisando {A_QUIEN.get(nxt['rol'], nxt['rol'])}.")
        else:
            tell_reporter(f"{quien} no puede acudir y no queda nadie más libre; lo he escalado al organizador.")
            org = seats.get('organizador')
            if org and org.get('chat_id') and org['chat_id'] != fila['chat_id']:
                out.update(has_next='true', next_json=dumps(send(org['chat_id'], f"SIMULACIÓN · Nadie puede cubrir {inc.get('tipo')} en {inc.get('zona') or 'zona no indicada'} ({inc.get('gravedad')}). Decide tú: refuerzo externo o reasignar.")))
    elif kind == 'eta':
        try:
            eta = int(extra)
        except ValueError:
            eta = -1
        if 0 <= eta <= 240:
            fila.update(eta_min=eta, estado='accepted')
            out.update(estado='accepted', has_outbound='true',
                       outbound_json=dumps(progress_message(fila, f'ETA {eta} min anotada (simulación). Cuando avances, márcalo aquí:')))
            tell_reporter(f"{quien} {'llegan' if plural else 'llega'} en unos {eta} minutos a {zona}. Quédate donde estás si es seguro.")
        else:
            out['error'] = 'eta_invalida'
    elif kind == 'loc':
        if extra:
            fila.update(from_zone=extra, estado='accepted')
            out.update(estado='accepted', has_outbound='true', outbound_json=dumps(progress_message(fila, f'Posición «{extra}» anotada (simulación).')))
        else:
            out['error'] = 'zona_vacia'
    elif kind in ('lle', 'enc', 'fin'):
        hito = {'lle': 'llegado', 'enc': 'localizado', 'fin': 'finalizado'}[kind]
        fila.setdefault('hitos', {})[hito] = now
        zona_txt = inc.get('zona') or 'la zona indicada'
        if kind == 'lle':
            out.update(estado='llegado', has_outbound='true', outbound_json=dumps(progress_message(fila, 'Llegada anotada. Aviso al asistente.')))
            tell_reporter(f"{quien} {'han' if plural else 'ha'} llegado a {zona_txt}.")
        elif kind == 'enc':
            out.update(estado='localizado', has_outbound='true', outbound_json=dumps(progress_message(fila, 'Incidencia localizada. Aviso al asistente.')))
            tell_reporter(f"{quien} ya {'han' if plural else 'ha'} localizado la incidencia y {'están' if plural else 'está'} actuando.")
        else:
            fila['estado'] = 'done'
            inc['estado'] = 'cerrado'
            inc['cerrado_por'] = rol
            for a in inc.get('assignments', []):
                if seats.get(a.get('rol'), {}).get('incident_id') == inc['id']:
                    seats[a['rol']].pop('incident_id', None)
                    touch_seats()
            out.update(estado='cerrado', has_outbound='true',
                       outbound_json=dumps(send(fila['chat_id'], 'Asistencia finalizada e incidencia cerrada. Gracias. Quedas libre para el siguiente aviso.')),
                       chat_json='', chat2_key=f"fa:chat:{inc.get('reporter_chat_id') or 'none'}", chat2_json='')
            tell_reporter(f"{quien} {'dan' if plural else 'da'} por finalizada la asistencia. Incidencia cerrada. Gracias por avisar; si vuelve a pasar algo, escríbeme.")
    elif kind in ('apr', 'vet'):
        inc['decision'] = {'kind': kind, 'por': alias or 'organizador', 'at': now}
        out.update(estado='approval', has_outbound='true', outbound_json=dumps(send(fila['chat_id'], ('Aprobado' if kind == 'apr' else 'Vetado') + ' (simulación). Registrado.')))
    else:
        out['error'] = f'kind_desconocido:{kind}'

out['incident_json'] = dumps(inc) if inc.get('id') else ''
out['seats_key'] = 'fa:seats' if out['write_seats'] == 'true' else 'fa:scratch:seats'
output = out
