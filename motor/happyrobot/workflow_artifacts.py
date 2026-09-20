import json
from uuid import UUID

from .sandbox import build_nodes, plate


EVENTS = {"post": "01926f2b-2973-7ebf-ada1-e984251e27ec", "python": "019dde7b-3500-7a3c-8f5e-1c2d4e6a8b9c"}


def ref(pid, field):
    return "{{%s.%s}}" % (str(UUID(pid)), field)


def raw_ref(pid, field):
    return "{{$var:%s.%s}}" % (str(UUID(pid)), field)


def post_config(path, scope, body):
    return {"url": plate.plate("{{use_case_variables.STATE_API_URL}}/hr/state" + path),
            "authType": "none", "contentType": "application/json", "webhookSchemaVersion": 2,
            "ignore5XX": True, "headers": [
                {"key": "x-hr-state-secret", "value": plate.plate("{{use_case_variables.HR_STATE_%s_SECRET}}" % scope.upper())},
                {"key": "x-vercel-protection-bypass", "value": plate.plate("{{use_case_variables.VERCEL_AUTOMATION_BYPASS_SECRET}}")},
            ], "body": {"schemaVersion": 2, "contentType": "application/json", "raw": body}}


def python_config(artifact, trigger, bindings=None):
    config = json.loads(build_nodes.updates(artifact, TRIGGER_PID=trigger))["configuration"]
    if bindings is not None:
        config["input_data"] = [{"key": key, "value": plate.plate(value, "p")} for key, value in bindings.items()]
    return config


def status_body(trigger):
    return json.dumps({"id": raw_ref(trigger, "event_id")})


def body_nodes(trigger):
    initial = {"event_id": ref(trigger, "event_id"), "state_status": "unconfigured", "status_code": "0",
               "event_json": "{}", "snapshot_json": "{}"}
    return [
        {"type": "loop", "name": "Reintentos CAS", "parent_node_id": trigger, "iterate_for": 3, "execute_in_parallel": False},
        {"type": "action", "name": "Leer contexto", "event_id": EVENTS["post"], "parent_node_index": 0,
         "configuration": post_config("/operations/context", "read", status_body(trigger))},
        {"type": "action", "name": "Calcular transición", "event_id": EVENTS["python"], "parent_node_index": 1,
         "configuration": python_config("fa_snapshot", trigger, initial)},
        {"type": "action", "name": "Confirmar transición", "event_id": EVENTS["post"], "parent_node_index": 2,
         "configuration": post_config("/inbox/status", "commit", status_body(trigger))},
        {"type": "path", "name": "¿Reintentar conflicto?", "parent_node_index": 3},
    ]


def final_nodes(trigger, loop_end):
    initial = {"event_id": ref(trigger, "event_id"), "status_json": "{}", "status_code": "0"}
    return [
        {"type": "action", "name": "Leer estado final", "event_id": EVENTS["post"], "parent_node_id": loop_end,
         "configuration": post_config("/inbox/status", "commit", status_body(trigger))},
        {"type": "action", "name": "Cerrar intento", "event_id": EVENTS["python"], "parent_node_index": 0,
         "configuration": python_config("fa_finish", trigger, initial)},
        {"type": "action", "name": "Registrar resultado", "event_id": EVENTS["post"], "parent_node_index": 1,
         "configuration": post_config("/inbox/status", "commit", status_body(trigger))},
        {"type": "action", "name": "Leer cierre del intento", "event_id": EVENTS["post"], "parent_node_index": 2,
         "configuration": post_config("/inbox/status", "commit", status_body(trigger))},
        {"type": "action", "name": "Resultado operación", "event_id": EVENTS["python"], "parent_node_index": 3,
         "configuration": python_config("fa_result", trigger, initial)},
    ]


def bindings(nodes, trigger):
    pid = lambda name: nodes[name]["persistent_id"]
    context = pid("Leer contexto")
    calculated = pid("Calcular transición")
    status = pid("Leer estado final")
    finish = pid("Cerrar intento")
    result = pid("Leer cierre del intento")
    return {
        "Calcular transición": {"configuration": python_config("fa_snapshot", trigger, {
            "event_id": ref(trigger, "event_id"), "state_status": ref(context, "status"),
            "event_json": ref(context, "event_json"), "snapshot_json": ref(context, "snapshot_json"),
            "status_code": ref(context, "api_status_code"),
        })},
        "Confirmar transición": {"configuration": post_config(ref(calculated, "path"), "commit", raw_ref(calculated, "body_json"))},
        "Cerrar intento": {"configuration": python_config("fa_finish", trigger, {
            "event_id": ref(trigger, "event_id"), "status_json": ref(status, "result_json"), "status_code": ref(status, "api_status_code"),
        })},
        "Registrar resultado": {"configuration": post_config(ref(finish, "path"), "commit", raw_ref(finish, "body_json"))},
        "Resultado operación": {"configuration": python_config("fa_result", trigger, {
            "event_id": ref(trigger, "event_id"), "status_json": ref(result, "result_json"), "status_code": ref(result, "api_status_code"),
        })},
    }


COORDINATOR_NAMES = ("Leer contexto", "Preparar contexto público", "Cargar entidades necesarias",
                     "Leer contexto ampliado", "Componer transición", "Confirmar transición",
                     "Leer estado final", "Registrar resultado")


def coordinator_nodes(trigger, llm):
    """Cadena del workflow fa-coordinador: contexto → contexto público → LLM → entidades → contexto
    ampliado → composición → commit → resultado.

    El nodo que llama al modelo ya existe en la plataforma: se referencia por su persistent ID y no se
    recrea aquí. Se asume colocado justo después de «Preparar contexto público», de modo que el LLM
    recibe el contexto sin contactos y el Sandbox de operaciones sigue validando toda transición."""
    llm = str(UUID(llm))
    initial = {"event_id": ref(trigger, "event_id"), "state_status": "unconfigured", "status_code": "0",
               "event_json": "{}", "snapshot_json": "{}", "proposal_json": "{}"}
    return [
        {"type": "action", "name": "Leer contexto", "event_id": EVENTS["post"], "parent_node_id": trigger,
         "configuration": post_config("/coordinator/context", "read", status_body(trigger))},
        {"type": "action", "name": "Preparar contexto público", "event_id": EVENTS["python"], "parent_node_index": 0,
         "configuration": python_config("fa_coordinador_contexto", trigger, initial)},
        {"type": "action", "name": "Cargar entidades necesarias", "event_id": EVENTS["python"], "parent_node_id": llm,
         "configuration": python_config("fa_coordinador_entidades", trigger, initial)},
        {"type": "action", "name": "Leer contexto ampliado", "event_id": EVENTS["post"], "parent_node_index": 2,
         "configuration": post_config("/coordinator/context", "read", status_body(trigger))},
        {"type": "action", "name": "Componer transición", "event_id": EVENTS["python"], "parent_node_index": 3,
         "configuration": python_config("fa_coordinador", trigger, initial)},
        {"type": "action", "name": "Confirmar transición", "event_id": EVENTS["post"], "parent_node_index": 4,
         "configuration": post_config("/coordinator/context", "commit", status_body(trigger))},
        {"type": "action", "name": "Leer estado final", "event_id": EVENTS["post"], "parent_node_index": 5,
         "configuration": post_config("/inbox/status", "commit", status_body(trigger))},
        {"type": "action", "name": "Registrar resultado", "event_id": EVENTS["python"], "parent_node_index": 6,
         "configuration": python_config("fa_result", trigger, initial)},
    ]


def coordinator_bindings(nodes, trigger, llm, proposal_field="proposal_json"):
    """Enlaza los nodos ya creados con IDs persistentes reales. `proposal_field` es el nombre con el
    que el nodo del LLM publica su propuesta: se declara explícitamente para no inventarlo."""
    llm = str(UUID(llm))
    pid = lambda name: nodes[name]["persistent_id"]
    read, entities = pid("Leer contexto"), pid("Cargar entidades necesarias")
    extended, compose, final = pid("Leer contexto ampliado"), pid("Componer transición"), pid("Leer estado final")
    proposal = ref(llm, proposal_field)
    return {
        "Preparar contexto público": {"configuration": python_config("fa_coordinador_contexto", trigger, {
            "event_json": ref(read, "event_json"), "snapshot_json": ref(read, "snapshot_json"),
            "state_status": ref(read, "status"), "status_code": ref(read, "api_status_code"),
        })},
        "Cargar entidades necesarias": {"configuration": python_config("fa_coordinador_entidades", trigger, {
            "event_json": ref(read, "event_json"), "proposal_json": proposal, "event_id": ref(trigger, "event_id"),
        })},
        "Leer contexto ampliado": {"configuration": post_config("/coordinator/context", "read", raw_ref(entities, "body_json"))},
        "Componer transición": {"configuration": python_config("fa_coordinador", trigger, {
            "event_id": ref(trigger, "event_id"), "state_status": ref(extended, "status"),
            "status_code": ref(extended, "api_status_code"), "event_json": ref(extended, "event_json"),
            "snapshot_json": ref(extended, "snapshot_json"), "proposal_json": proposal,
        })},
        "Confirmar transición": {"configuration": post_config(ref(compose, "path"), "commit", raw_ref(compose, "body_json"))},
        "Registrar resultado": {"configuration": python_config("fa_result", trigger, {
            "event_id": ref(trigger, "event_id"), "status_json": ref(final, "result_json"),
            "status_code": ref(final, "api_status_code"),
        })},
    }
