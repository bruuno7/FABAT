"""Sandbox 'Directorio de puestos' de fa-rol-tg. Sustituye a MANDO /hr/tg/roster.
input_data: seats_json, action (claim|release|list), role, chat_id, alias, now
Salida: ok, action, role, alias, reason, seats_json, resumen, reply_text, chat_id, claimed, total
"""
# --- COMMON ---
seats = as_obj(input_data.get('seats_json'), {})
action = (s(input_data.get('action'), 10).lower() or 'claim')
role = s(input_data.get('role'), 30).lower().replace('médico', 'medico').replace('policía', 'policia')
chat_id = s(input_data.get('chat_id'), 40)
alias = s(input_data.get('alias'), 40) or 'staff'
now = s(input_data.get('now'), 40)

out = {'ok': 'true', 'action': action, 'role': role, 'alias': alias, 'reason': '', 'chat_id': chat_id}
if action == 'claim':
    if role not in SEATS:
        out.update(ok='false', reason='puesto_desconocido',
                   reply_text='Puesto desconocido. Puestos: ' + ', '.join(SEATS) + '.')
    elif not chat_id:
        out.update(ok='false', reason='falta_chat_id', reply_text='Falta chat_id.')
    else:
        holder = seats.get(role)
        if holder and holder.get('chat_id') != chat_id:
            out.update(ok='false', reason='taken',
                       reply_text=f"El puesto {SEAT_ES[role]} ya lo tiene {holder.get('alias') or 'otra persona'} (simulación).")
        else:
            for r, row in list(seats.items()):
                if row.get('chat_id') == chat_id and r != role:
                    del seats[r]
            seats[role] = {'chat_id': chat_id, 'alias': alias, 'claimed_at': now}
            out['reply_text'] = f"Puesto {SEAT_ES[role]} asignado a {alias} (simulación). Recibirás los avisos de ese puesto aquí."
elif action == 'release':
    prev = next((r for r, row in seats.items() if row.get('chat_id') == chat_id), None)
    if prev:
        del seats[prev]
        out['reply_text'] = f"Dejas el puesto {SEAT_ES[prev]} (simulación)."
    else:
        out['reply_text'] = 'No tenías ningún puesto. /rol para tomar uno.'
else:
    out['action'] = 'list'
    out['reply_text'] = ''

lines = [f"{'●' if seats.get(r) else '○'} {SEAT_ES[r]}: {seats[r]['alias'] if seats.get(r) else 'libre'}" for r in SEATS]
out['resumen'] = 'Puestos (simulación)\n' + '\n'.join(lines)
if action == 'list' or not out['reply_text']:
    out['reply_text'] = out['resumen']
elif out['ok'] == 'true':
    out['reply_text'] += '\n\n' + out['resumen']
out['claimed'] = sum(1 for r in SEATS if seats.get(r))
out['total'] = len(SEATS)
out['seats_json'] = dumps(seats)
out['has_reply'] = 'true' if chat_id else 'false'
out['reply_json'] = dumps({'event': 'telegram_send', 'chat_id': chat_id, 'text': out['reply_text']}) if chat_id else ''
output = out
