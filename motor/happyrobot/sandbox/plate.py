"""Genera nodos en formato Plate (para update_workflow_nodes action=add, que no transforma plantillas)."""
import json, pathlib, re, sys

HERE = pathlib.Path(__file__).parent
COMMON = (HERE / 'fa_common.py').read_text()
CRED = '01a0b9e1-c4b5-754f-9540-3e71561caa4e'
EV = {'redis_r': '019d4a7a-f3e9-77f8-be5c-9b08b5fc6908', 'redis_w': '019d4a7a-f3e9-7d3c-88ab-ab76f0de0c5f',
      'py': '019dde7b-3500-7a3c-8f5e-1c2d4e6a8b9c', 'post': '01926f2b-2973-7ebf-ada1-e984251e27ec'}
REDIS_CRED = {'credentialId': CRED, 'credential': {'type': 'static', 'static': {'id': CRED, 'name': 'fabat-redis'}}}
VAR = re.compile(r'\{\{([^.}]+)\.([^}]+)\}\}')


def plate(text, ptype='paragraph'):
    """'abc {{g.v}} def' → [{type, children:[text, variable, text]}]"""
    children, pos = [], 0
    for m in VAR.finditer(text):
        children.append({'text': text[pos:m.start()]})
        children.append({'type': 'variable', 'children': [{'text': ''}], 'group_id': m.group(1), 'variable_id': m.group(2)})
        pos = m.end()
    children.append({'text': text[pos:]})
    return [{'type': ptype, 'children': children}]


def code(name):
    return (HERE / f'{name}.py').read_text().replace('# --- COMMON ---', COMMON)


def py(name, label, inputs, parent):
    return {'type': 'action', 'event_id': EV['py'], 'name': label, 'parent_node_id': parent,
            'configuration': {'code': code(name), 'execution_profile': 'standard',
                              'input_data': [{'key': k, 'value': plate(v, 'p')} for k, v in inputs.items()]}}


def rread(label, key, parent):
    return {'type': 'action', 'event_id': EV['redis_r'], 'name': label, 'parent_node_id': parent,
            'configuration': {**REDIS_CRED, 'key': plate(key)}}


def rwrite(label, key, value, parent):
    return {'type': 'action', 'event_id': EV['redis_w'], 'name': label, 'parent_node_id': parent,
            'configuration': {**REDIS_CRED, 'key': plate(key), 'value': plate(value)}}


def post_puente(label, raw_var, parent_key, parent):
    return {'type': 'action', 'event_id': EV['post'], 'name': label, parent_key: parent,
            'configuration': {'url': plate('{{use_case_variables.PUENTE_URL}}/hr/events'), 'authType': 'none',
                              'contentType': 'application/json', 'webhookSchemaVersion': 2, 'ignore5XX': True,
                              'headers': [{'key': 'x-hr-secret', 'value': plate('{{use_case_variables.HR_SECRET}}')}],
                              'body': {'schemaVersion': 2, 'contentType': 'application/json', 'raw': raw_var}}}


def path_with(label, cond_label, group, var, text, then_label, raw_var, parent):
    return [{'type': 'path', 'name': label, 'parent_node_id': parent},
            {'type': 'condition', 'name': cond_label, 'type_of_condition': 'conditional', 'parent_node_index': 0, 'order': 0,
             'conditions': [{'ors': [{'ands': [{'field': {'group_id': group, 'variable_id': var}, 'condition': 'text_equals',
                                                'value': [{'type': 'paragraph', 'children': [{'text': text}]}]}]}]}]},
            post_puente(then_label, raw_var, 'parent_node_index', 1)]


if __name__ == '__main__':
    fn, args = sys.argv[1], sys.argv[2:]
    out = globals()[fn](*args)
    print(json.dumps(out if isinstance(out, list) else [out], ensure_ascii=False))
