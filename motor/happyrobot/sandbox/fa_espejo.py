"""Sandbox 'Espejo a MANDO': cuelga el espejo de solo lectura en el mensaje ya construido.

HappyRobot decide; MANDO y la Sala sólo reflejan. Este nodo NO crea ofertas, no reserva
capacidad ni elige a nadie: copia el estado ya decidido (aviso + asignaciones) dentro del
mensaje que va al puente, que lo reenvía a `POST /api/operations/happyrobot`.

Entrada: payload_json (mensaje del Sandbox anterior), inc_json (incidente con `id` y
`assignments`). Salida: payload_json con la lista `mirror` y has_mirror.

Es autocontenido a propósito (no usa el bloque común de fa_common.py): son ~1,5 KB de helpers
y así el nodo de la plataforma se revisa y se reenvía sin arrastrar todo el bloque. Si cambia
`ESTADO_ESPEJO`, `tg_incident_event` o `tg_assignment_event`, actualizar los dos sitios.
"""
import json

ESTADO_ESPEJO = {'pending': 'pending', 'accepted': 'accepted', 'covered': 'covered',
                 'declined': 'declined', 'done': 'finalizado', 'timeout': 'timeout'}


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


def dumps(o):
    return json.dumps(o, ensure_ascii=True, separators=(',', ':'))


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
    events = [e for e in events if e]
    if isinstance(msg, dict) and events:
        msg = dict(msg)
        msg['mirror'] = events
    return msg


msg = as_obj(input_data.get('payload_json'), {})
inc = as_obj(input_data.get('inc_json'), {})
events = []
if isinstance(inc, dict) and inc.get('id'):
    events = [tg_incident_event(inc)] + [tg_assignment_event(inc, a) for a in inc.get('assignments', [])[-8:]]
if isinstance(msg, dict) and msg:
    salida = dumps(attach_mirror(msg, events))
else:
    salida = s(input_data.get('payload_json'), 200000)
output = {'payload_json': salida, 'has_mirror': 'true' if events else 'false'}
