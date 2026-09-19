"""Sandbox 'Contexto del remitente' de fa-entrada-tg: ¿quién escribe y sobre qué incidente?
input_data: chat_json (fa:chat:<chat>), seats_json, chat_id, now
Salida: sender_kind (asistente|equipo), role, incident_id ('none' si no hay), chat_kind, pregunta_pendiente,
        pregunta_de, assignment_id, resumen_remitente (texto para el LLM)
"""
# --- COMMON ---
chat = as_obj(input_data.get('chat_json'), {})
seats = as_obj(input_data.get('seats_json'), {})
chat_id = s(input_data.get('chat_id'), 40)
now = s(input_data.get('now'), 40)
role = role_of_chat(seats, chat_id)
kind = s(chat.get('kind'), 40)
caducado = expired(chat.get('last_at') or chat.get('asked_at'), now)

incident_id, assignment_id, pregunta, pregunta_de = '', '', '', ''
if kind == 'staff_disponibilidad':
    pass
elif kind in ('asistente_activo', 'asistente_pregunta') and not caducado:
    incident_id = s(chat.get('incident_id'), 60)
    pregunta = s(chat.get('pregunta'), 200)
    pregunta_de = s(chat.get('pregunta_de'), 40)
elif kind == 'staff_activo' and not caducado:
    incident_id = s(chat.get('incident_id'), 60)
    assignment_id = s(chat.get('assignment_id'), 80)
if role and not incident_id and kind != 'staff_disponibilidad':
    incident_id = s(seats.get(role, {}).get('incident_id'), 60)

sender_kind = 'equipo' if role else 'asistente'
if sender_kind == 'equipo':
    resumen = f"El remitente es un miembro del EQUIPO con el puesto {SEAT_ES.get(role, role)}"
    resumen += f", asignado ahora al incidente {incident_id}." if incident_id else ", sin ningún incidente asignado ahora."
else:
    resumen = 'El remitente es un ASISTENTE del festival'
    resumen += f" con un incidente abierto ({incident_id})." if incident_id else ' sin ningún incidente abierto.'
    if pregunta:
        resumen += f" Se le hizo esta pregunta y está pendiente de respuesta: «{pregunta}»."
output = {'sender_kind': sender_kind, 'role': role, 'incident_id': incident_id or 'none', 'chat_kind': kind,
          'pregunta_pendiente': pregunta, 'pregunta_de': pregunta_de, 'assignment_id': assignment_id,
          'has_incident': 'true' if incident_id else 'false', 'resumen_remitente': resumen}
