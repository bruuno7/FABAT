"""Genera los JSON de `updates` (configuration completa) para update_workflow_nodes, con el código de cada Sandbox
y sus input_data. Uso: python3 build_nodes.py <sandbox> > /tmp/u.json
Recorta funciones no usadas para que el payload sea pequeño y valida ejecutando el código con input vacío."""
import json, re, sys
from uuid import UUID

if __package__:
    from . import plate
else:
    import plate

T_ENT = '01a0b846-7d26-7213-b716-20c90765a016'   # trigger fa-entrada-tg
E = '01a0b8d6-cfa8-7d99-a896-185306754ca4'       # Identify Explicit Data
D = '01a0b916-38b0-7d5c-a2e2-d382bd6976ad'       # Decidir coordinación
S = '01a0b916-38c4-7281-9d7b-05ee11d6c3de'       # Serializar
CH = '01a0ba63-3b0d-7955-972c-e4f08643e4e0'      # Leer estado del chat (entrada)
T_DES = '0de63eba-a8cc-4a63-a239-012f0de3ed67'   # trigger fa-despacho-tg
SEATS_D, INC_D = '01a0b9ee-d895-7da9-8734-a460a8f65880', '01a0b9ee-d8a3-73b5-8979-6670e7f90410'
ELEGIR = '01a0b9f1-87db-7f6e-801a-f9aadc926dd7'
T_RES = 'c9fa7ced-e107-473c-81cb-850957b4774f'   # trigger fa-respuesta-tg
P_RES, INC_R, SEATS_R = '01a0b9f5-be83-7500-bc5d-45f7344722c7', '01a0b9f5-f39d-7f9d-ab81-67b0961575ff', '01a0b9f5-f3aa-741d-abe1-071888f8b769'
APLICAR = '01a0b9f7-0c40-7995-b26d-735e5da1e040'
# Los siguientes se rellenan tras crear los nodos nuevos en la plataforma (persistent IDs):
CTX = 'CTX_PID'      # Sandbox Contexto (entrada)
INC_E = 'INC_E_PID'  # Leer incidente activo (entrada)


def slim(code):
    code = re.sub(r'^"""[\s\S]*?"""\n', '', code)
    code = re.sub(r'"""Bloque[\s\S]*?"""\n', '', code)
    body = code.split('\n')
    # elimina funciones de nivel superior que no se usan
    for _ in range(3):
        defs = re.findall(r'^def (\w+)\(', code, flags=re.M)
        for fn in defs:
            uses = len(re.findall(r'\b%s\b' % fn, code))
            if uses == 1:
                code = re.sub(r'^def %s\([\s\S]*?(?=^\S)' % fn, '', code, flags=re.M)
    return re.sub(r'\n{3,}', '\n\n', code).strip() + '\n'


def dual(group, key):
    """Trigger llamado por workflow (raíz) o por webhook (data.*): los dos."""
    return '{{%s.data.%s}}{{%s.%s}}' % (group, key, group, key)


INPUTS = {
    'fa_contexto': {'chat_json': '{{%s.value}}' % CH, 'seats_json': '{{SEATS_E_PID.value}}', 'chat_id': '{{%s.data.reporter.chat_id}}' % T_ENT, 'now': '{{time.now_iso}}'},
    'fa_entrada_serial': {
        'chat_json': '{{%s.value}}' % CH, 'chat_id': '{{%s.data.reporter.chat_id}}' % T_ENT, 'alias': '{{%s.data.reporter.display_name}}' % T_ENT,
        'correlation_id': '{{%s.data.correlation_id}}' % T_ENT, 'run_id': '{{current.run_id}}', 'original_text': '{{%s.data.text}}' % T_ENT,
        'zone_hint': '{{%s.data.location_hint}}' % T_ENT, 'channel': '{{%s.data.channel}}' % T_ENT,
        'sender_kind': '{{%s.sender_kind}}' % CTX, 'role': '{{%s.role}}' % CTX, 'ctx_incident_id': '{{%s.incident_id}}' % CTX, 'chat_kind': '{{%s.chat_kind}}' % CTX,
        'pregunta_pendiente': '{{%s.pregunta_pendiente}}' % CTX, 'pregunta_de': '{{%s.pregunta_de}}' % CTX, 'inc_json': '{{%s.value}}' % INC_E,
        'incident_type': '{{%s.response.incident_type}}' % E, 'location': '{{%s.response.location}}' % E, 'description': '{{%s.response.description}}' % E,
        'severity': '{{%s.response.severity}}' % E, 'triage': '{{%s.response.triage_color}}' % E,
        'relacion': '{{%s.response.relacion}}' % D, 'mensaje_reenvio': '{{%s.response.mensaje_reenvio}}' % D, 'roles_orden': '{{%s.response.roles_orden}}' % D,
        'pregunta_asistente': '{{%s.response.pregunta_asistente}}' % D, 'instruccion_asistente': '{{%s.response.instruccion_asistente}}' % D,
        'instruccion_staff': '{{%s.response.instruccion_staff}}' % D},
    'fa_despacho': {'seats_json': '{{%s.value}}' % SEATS_D, 'inc_json': '{{%s.value}}' % INC_D,
                    **{k: dual(T_DES, k) for k in ['mode', 'hito', 'incident_id', 'role', 'minutes', 'texto', 'tipo', 'zona', 'gravedad', 'prioridad',
                                                    'alias_informante', 'reporter_chat_id', 'correlation_id', 'summary', 'rol', 'roles_orden', 'pregunta',
                                                    'instruccion_staff', 'reenvio', 'to_chat', 'chat_json']},
                    'now': '{{time.now_iso}}'},
    'fa_respuesta': {'inc_json': '{{%s.value}}' % INC_R, 'seats_json': '{{%s.value}}' % SEATS_R, 'kind': '{{%s.kind}}' % P_RES,
                     'callback_data': '{{%s.data.callback_data}}' % T_RES, 'assignment_id': '{{%s.assignment_id}}' % P_RES,
                     'chat_id': '{{%s.data.chat_id}}' % T_RES, 'alias': '{{%s.data.reporter.display_name}}' % T_RES, 'now': '{{time.now_iso}}'},
}


def updates(name, **override):
    if name in ('fa_operaciones', 'fa_consumidor', 'fa_snapshot', 'fa_finish', 'fa_result'):
        raw = override.get('TRIGGER_PID')
        if not isinstance(raw, str) or not raw:
            raise ValueError('TRIGGER_PID must be a persistent UUID')
        trigger = str(UUID(raw))
        source = (plate.HERE / 'fa_operaciones.py').read_text()
        keys = ('event_json', 'snapshot_json')
        entry = 'run_input'
        if name != 'fa_operaciones':
            source += '\n' + (plate.HERE / 'fa_consumidor.py').read_text()
            entry, keys = {
                'fa_consumidor': ('consumer_input', ('event_id', 'state_json', 'response_json', 'status_code')),
                'fa_snapshot': ('snapshot_input', ('event_id', 'state_status', 'event_json', 'snapshot_json', 'status_code')),
                'fa_finish': ('finish_input', ('event_id', 'status_json', 'status_code')),
                'fa_result': ('result_input', ('event_id', 'status_json', 'status_code')),
            }[name]
        code = source + '\noutput = %s(input_data)\n' % entry
        compile(code, name, 'exec')
        return json.dumps({'configuration': {
            'code': code, 'execution_profile': 'standard',
            'input_data': [{'key': key, 'value': plate.plate('{{%s.%s}}' % (trigger, key), 'p')}
                           for key in keys],
        }})
    inputs = dict(INPUTS[name])
    for k, v in override.items():
        for ik in inputs:
            inputs[ik] = inputs[ik].replace(k, v)
    n = plate.py(name, name, inputs, 'x')
    code = slim(n['configuration']['code'])
    ns = {'input_data': {}}
    exec(code, ns)
    assert 'output' in ns
    n['configuration']['code'] = code
    return json.dumps({'configuration': n['configuration']})


if __name__ == '__main__':
    name = sys.argv[1]
    over = dict(a.split('=') for a in sys.argv[2:])
    print(updates(name, **over))
