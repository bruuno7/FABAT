"""Sandbox 'Localizar incidente' de fa-respuesta-tg: del callback_data saca assignment_id → incident_id.
input_data: callback_data, assignment_id, kind
Salida: incident_id, assignment_id, kind, extra
"""
def s(v, maximo=120):
    return '' if v is None else str(v).strip()[:maximo]


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
iid = aid.split('~')[0] if aid else ''
output = {'incident_id': iid, 'assignment_id': aid, 'kind': kind, 'extra': extra}
