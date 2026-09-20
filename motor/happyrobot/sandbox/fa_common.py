"""Bloque común (se pega al principio de cada Sandbox). Sin red, sin imports fuera de stdlib."""
import json, re
from datetime import datetime, timedelta

SEATS = ('medico', 'staff_entradas', 'organizador', 'bomberos', 'policia')
SEAT_ES = {'medico': 'médico', 'staff_entradas': 'staff entradas', 'organizador': 'organizador',
           'bomberos': 'bomberos', 'policia': 'policía'}
ROL_SUJETO = {'medico': 'El equipo médico', 'staff_entradas': 'El staff de accesos', 'organizador': 'El organizador',
              'bomberos': 'Los bomberos', 'policia': 'La policía'}
A_QUIEN = {'medico': 'al equipo médico', 'staff_entradas': 'al staff de accesos', 'organizador': 'al organizador',
           'bomberos': 'a los bomberos', 'policia': 'a la policía'}
PLURAL = {'bomberos'}
ROLE_PREFERENCE = {
    'medica': ('medico', 'staff_entradas'), 'incendio': ('bomberos', 'policia', 'organizador'),
    'seguridad': ('policia', 'bomberos', 'organizador'), 'agresion': ('policia', 'medico', 'organizador'),
    'aglomeracion': ('staff_entradas', 'policia', 'organizador'), 'infraestructura': ('staff_entradas', 'organizador'),
    'falta_recursos': ('staff_entradas', 'organizador'), 'clima': ('organizador', 'staff_entradas'),
    'menor': ('staff_entradas', 'medico', 'organizador'), 'otro': ('organizador', 'staff_entradas', 'policia'),
}
TIPO = {'medica': 'medica', 'aglomeracion': 'aglomeracion', 'seguridad': 'seguridad', 'agresion': 'seguridad',
        'incendio': 'incendio', 'clima': 'clima', 'infraestructura': 'infraestructura', 'infra': 'infraestructura',
        'falta_recursos': 'infraestructura', 'menor': 'menor', 'otro': 'otro'}
GRAVEDAD = {5: 'vital', 4: 'emergencia', 3: 'urgente', 2: 'leve', 1: 'sin_clasificar'}
DISCLAIMER = 'Esto es una simulación de hackathon, no un servicio de emergencias.'
HITOS = (('llegado', 'He llegado', 'lle'), ('localizado', 'Localizado', 'enc'), ('finalizado', 'Finalizado', 'fin'))
ACTIVO_MIN = 45  # minutos que un incidente sigue "abierto" para el chat


def s(v, maximo=400):
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        v = str(int(v) if float(v).is_integer() else v)
    return str(v).strip()[:maximo]


def as_obj(v, default):
    if isinstance(v, (dict, list)):
        return v
    t = s(v, 200000)
    if not t:
        return default
    try:
        p = json.loads(t)
        return p if isinstance(p, type(default)) else default
    except Exception:
        return default


def roles_list(v):
    raw = as_obj(v, []) if not isinstance(v, list) else v
    if not raw:
        raw = [x.strip() for x in s(v, 400).replace(';', ',').replace('[', '').replace(']', '').replace('"', '').split(',')]
    out = []
    for r in raw:
        r = s(r, 30).lower().replace('médico', 'medico').replace('policía', 'policia').replace('staff de entradas', 'staff_entradas')
        if r in SEATS and r not in out:
            out.append(r)
    return out


def gravedad(raw, sev):
    r = s(raw, 20).lower()
    if r in GRAVEDAD.values():
        return r
    try:
        n = int(float(sev))
    except (TypeError, ValueError):
        n = 3
    return GRAVEDAD.get(max(1, min(5, n)), 'urgente')


def parse_iso(t):
    try:
        return datetime.fromisoformat(s(t, 40).replace('Z', '+00:00'))
    except Exception:
        return None


def is_busy(row, now):
    bu, n = parse_iso(row.get('busy_until')), parse_iso(now)
    return bool(bu and n and bu > n)


def expired(last_at, now, minutes=ACTIVO_MIN):
    a, n = parse_iso(last_at), parse_iso(now)
    return bool(a and n and n - a > timedelta(minutes=minutes))


def role_of_chat(seats, chat_id):
    return next((r for r, row in seats.items() if chat_id and row.get('chat_id') == chat_id), '')


def cb(kind, aid, extra=''):
    parts = [kind, aid] + ([extra] if extra else [])
    return '|'.join(parts)[:64]


def next_seat(seats, inc, now, rol_pedido=None):
    declined = {a['chat_id'] for a in inc.get('assignments', []) if a.get('estado') == 'declined'}
    covered = {a['rol'] for a in inc.get('assignments', []) if a.get('estado') in ('accepted', 'covered', 'pending')}
    order = [rol_pedido] if rol_pedido in SEATS else (list(inc.get('roles_orden') or []) or list(ROLE_PREFERENCE.get(inc.get('tipo_in') or inc.get('tipo'), ROLE_PREFERENCE['otro'])))
    for role in SEATS:
        if role not in order:
            order.append(role)  # último recurso: cualquier puesto reclamado
    for role in order:
        if role in covered:
            continue
        row = seats.get(role)
        if not row or not row.get('chat_id') or row['chat_id'] in declined or is_busy(row, now):
            continue
        return {'rol': role, 'chat_id': row['chat_id'], 'alias': row.get('alias') or SEAT_ES[role]}
    return None


def create_assignment(inc, pick, now):
    n = len(inc.setdefault('assignments', [])) + 1
    aid = f"{inc['id']}~{n}"
    intento = 1 + sum(1 for a in inc['assignments'] if a.get('rol') == pick['rol'])
    a = {'id': aid, 'rol': pick['rol'], 'alias': pick['alias'], 'chat_id': pick['chat_id'], 'estado': 'pending',
         'intento': intento, 'eta_min': None, 'from_zone': None, 'motivo': '', 'hitos': {}, 'created_at': now, 'updated_at': now}
    inc['assignments'].append(a)
    return a


def activos(inc):
    return [a for a in inc.get('assignments', []) if a.get('estado') in ('pending', 'accepted')]


# --- Espejo para la interfaz (solo lectura) ---------------------------------
# La decisión la toma HappyRobot; la Sala sólo pinta esto y sus botones quedan
# para el override humano. El puente reenvía la lista `mirror` a MANDO.
ESTADO_ESPEJO = {'pending': 'pending', 'accepted': 'accepted', 'covered': 'covered',
                 'declined': 'declined', 'done': 'finalizado', 'timeout': 'timeout'}


def tg_incident_event(inc):
    return {'type': 'tg_incident', 'id': s(inc.get('id'), 60), 'texto': s(inc.get('texto'), 400),
            'tipo': s(inc.get('tipo') or 'otro', 40), 'zona': s(inc.get('zona'), 60) or '',
            'gravedad': s(inc.get('gravedad') or 'sin_clasificar', 20),
            'alias_informante': s(inc.get('alias_informante'), 40), 'recursos_requeridos': []}


def tg_assignment_event(inc, a):
    try:
        intento = min(20, max(1, int(a.get('intento') or 1)))
    except (TypeError, ValueError):
        intento = 1
    return {'type': 'tg_assignment', 'incident_id': s(inc.get('id'), 60), 'rol': s(a.get('rol'), 30),
            'estado': ESTADO_ESPEJO.get(s(a.get('estado'), 20), 'pending'), 'alias': s(a.get('alias'), 40),
            'eta_min': a.get('eta_min'), 'from_zone': s(a.get('from_zone'), 60) or '',
            'intento': intento, 'motivo': s(a.get('motivo'), 200) or ''}


def attach_mirror(msg, events):
    """Cuelga el espejo en un mensaje ya construido; el puente lo reenvía a MANDO."""
    events = [e for e in events if e]
    if isinstance(msg, dict) and events:
        msg = dict(msg)
        msg['mirror'] = events
    return msg


def offer_message(a, inc):
    rol = SEAT_ES.get(a['rol'], a['rol'])
    zona = inc.get('zona') or 'zona no indicada'
    extra = f"\nQué hacer: {inc['instruccion_staff'][:200]}" if inc.get('instruccion_staff') else ''
    body = (f"SIMULACIÓN · {rol}\nUrgencia: {inc.get('gravedad')} · {zona}\n{inc.get('texto', '')[:280]}{extra}\n\n"
            f"¿Puedes acudir? {DISCLAIMER}")
    return attach_mirror({'event': 'telegram_send', 'chat_id': a['chat_id'], 'text': body, 'correlation_id': a['id'],
            'reply_markup': {'inline_keyboard': [[
                {'text': 'Acepto', 'callback_data': cb('acc', a['id'])},
                {'text': 'No puedo', 'callback_data': cb('dec', a['id'])}]]}},
            [tg_incident_event(inc), tg_assignment_event(inc, a)])


def eta_loc_message(a):
    aid = a['id']
    return {'event': 'telegram_send', 'chat_id': a['chat_id'],
            'text': 'Anotado. ¿Cuánto tardas y desde dónde sales? (simulación)',
            'correlation_id': aid,
            'reply_markup': {'inline_keyboard': [
                [{'text': 'ETA 2 min', 'callback_data': cb('eta', aid, '2')},
                 {'text': 'ETA 5 min', 'callback_data': cb('eta', aid, '5')},
                 {'text': 'ETA 10 min', 'callback_data': cb('eta', aid, '10')}],
                [{'text': 'Foso', 'callback_data': cb('loc', aid, 'front_pit')},
                 {'text': 'Acceso A', 'callback_data': cb('loc', aid, 'gate_a')},
                 {'text': 'Escenario', 'callback_data': cb('loc', aid, 'main_stage')}]]}}


def progress_keyboard(a):
    hitos = a.get('hitos') or {}
    row = [{'text': label, 'callback_data': cb(k, a['id'])} for h, label, k in HITOS if not hitos.get(h)]
    return {'inline_keyboard': [row]} if row else None


def progress_message(a, text):
    m = {'event': 'telegram_send', 'chat_id': a['chat_id'], 'text': text, 'correlation_id': a['id']}
    kb = progress_keyboard(a)
    if kb:
        m['reply_markup'] = kb
    return m


def dumps(o):
    return json.dumps(o, ensure_ascii=True, separators=(',', ':'))


def send(chat, text):
    return {'event': 'telegram_send', 'chat_id': chat, 'text': text}


def reporter_msg(inc, text):
    chat = inc.get('reporter_chat_id')
    return send(chat, text) if chat else None


def chat_state(kind, **kw):
    d = {'kind': kind}
    d.update({k: v for k, v in kw.items() if v not in (None, '')})
    return dumps(d)


def parse_minutes(text):
    t = s(text, 200).lower()
    if re.search(r'\b(ahora|ya|libre|disponible|puedo)\b', t) and not re.search(r'\d', t):
        return 0
    if 'media hora' in t:
        return 30
    if re.search(r'\b(una|1)\s*hora', t):
        return 60
    m = re.search(r'(\d+)\s*(h|hora)', t)
    if m:
        return int(m.group(1)) * 60
    m = re.search(r'(\d+)', t)
    return int(m.group(1)) if m else None
