import json
from pathlib import Path
from uuid import UUID

from .sandbox import build_nodes, plate


EVENTS = {"post": "01926f2b-2973-7ebf-ada1-e984251e27ec", "python": "019dde7b-3500-7a3c-8f5e-1c2d4e6a8b9c"}

# Descubiertos con list_integrations/get_node_config_schema (solo lectura). El Cron es el
# root del workflow de recuperación; el bucle solo se usa si el grafo llega a necesitarlo.
CRON_TRIGGER = "0192fff4-4da6-7712-a139-53c87250339f"
LOOP_EVENT = "8d8ec06c-4d69-4f40-9f9d-1e1f7a1e6d7c"
CRON_MAX = 8
# Campo del nodo POST /outbox/recover que devuelve las entregas del tick. Es lo único del
# grafo del Cron que debe confirmarse contra el nodo desplegado antes de instalarlo.
RECOVER_RESULTS_FIELD = "results"
INBOX_ITEMS_FIELD = "items"


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


COORDINATOR_LLM_NAME = "Coordinar con el modelo"
COORDINATOR_LLM_EVENT = "01926f30-36a3-7394-8f73-eeead5d7f948"  # Extract (prompt + input + json_schema)
LLM_CONTEXT_FIELD = "context_json"   # salida de «Preparar contexto público»
# Salida del nodo Extract. La plataforma expone el resultado del esquema bajo `response`;
# si un run real lo publica con otro nombre, se cambia aquí y el grafo no se toca.
LLM_PROPOSAL_FIELD = "response"

# Orden lineal del coordinador: cada nodo cuelga del anterior, así que se pueden añadir
# de uno en uno (el código de cada Sandbox no cabe en un solo payload).
COORDINATOR_CHAIN = (COORDINATOR_NAMES[0], COORDINATOR_NAMES[1], COORDINATOR_LLM_NAME,
                     COORDINATOR_NAMES[2], COORDINATOR_NAMES[3], COORDINATOR_NAMES[4],
                     COORDINATOR_NAMES[5], COORDINATOR_NAMES[6], COORDINATOR_NAMES[7])


def coordinator_prompt():
    return json.loads(Path(__file__).with_name("coordinator-prompt.json").read_text(encoding="utf-8"))


def coordinator_llm_config(input_ref="{}"):
    prompt = coordinator_prompt()
    return {"prompt": prompt["prompt"], "input": input_ref, "json_schema": json.dumps(prompt["schema"])}


def coordinator_chain(trigger):
    """Cadena lineal completa del coordinador, incluido el paso del modelo."""
    initial = {"event_id": ref(trigger, "event_id"), "state_status": "unconfigured", "status_code": "0",
               "event_json": "{}", "snapshot_json": "{}", "proposal_json": "{}"}
    return [
        {"type": "action", "name": COORDINATOR_CHAIN[0], "event_id": EVENTS["post"],
         "configuration": post_config("/coordinator/context", "read", status_body(trigger))},
        {"type": "action", "name": COORDINATOR_CHAIN[1], "event_id": EVENTS["python"],
         "configuration": python_config("fa_coordinador_contexto", trigger, initial)},
        {"type": "action", "name": COORDINATOR_CHAIN[2], "event_id": COORDINATOR_LLM_EVENT,
         "configuration": coordinator_llm_config()},
        {"type": "action", "name": COORDINATOR_CHAIN[3], "event_id": EVENTS["python"],
         "configuration": python_config("fa_coordinador_entidades", trigger, initial)},
        {"type": "action", "name": COORDINATOR_CHAIN[4], "event_id": EVENTS["post"],
         "configuration": post_config("/coordinator/context", "read", status_body(trigger))},
        {"type": "action", "name": COORDINATOR_CHAIN[5], "event_id": EVENTS["python"],
         "configuration": python_config("fa_coordinador", trigger, initial)},
        {"type": "action", "name": COORDINATOR_CHAIN[6], "event_id": EVENTS["post"],
         "configuration": post_config("/coordinator/context", "commit", status_body(trigger))},
        {"type": "action", "name": COORDINATOR_CHAIN[7], "event_id": EVENTS["post"],
         "configuration": post_config("/inbox/status", "commit", status_body(trigger))},
        {"type": "action", "name": COORDINATOR_CHAIN[8], "event_id": EVENTS["python"],
         "configuration": python_config("fa_result", trigger, initial)},
    ]


def coordinator_chain_bindings(nodes, trigger):
    """Enlaza la cadena con persistent IDs reales. El contexto público llega al modelo como
    `input`, y la propuesta del modelo entra en el núcleo como `proposal_json`."""
    pid = lambda name: nodes[name]["persistent_id"]
    read, prepared = pid(COORDINATOR_CHAIN[0]), pid(COORDINATOR_CHAIN[1])
    entities, extended = pid(COORDINATOR_CHAIN[3]), pid(COORDINATOR_CHAIN[4])
    compose, final = pid(COORDINATOR_CHAIN[5]), pid(COORDINATOR_CHAIN[7])
    proposal = ref(pid(COORDINATOR_CHAIN[2]), LLM_PROPOSAL_FIELD)
    return {
        COORDINATOR_CHAIN[1]: {"configuration": python_config("fa_coordinador_contexto", trigger, {
            "event_json": ref(read, "event_json"), "snapshot_json": ref(read, "snapshot_json"),
            "state_status": ref(read, "status"), "status_code": ref(read, "api_status_code")})},
        COORDINATOR_CHAIN[2]: {"configuration": coordinator_llm_config(ref(prepared, LLM_CONTEXT_FIELD))},
        COORDINATOR_CHAIN[3]: {"configuration": python_config("fa_coordinador_entidades", trigger, {
            "event_json": ref(read, "event_json"), "proposal_json": proposal, "event_id": ref(trigger, "event_id")})},
        COORDINATOR_CHAIN[4]: {"configuration": post_config("/coordinator/context", "read", raw_ref(entities, "body_json"))},
        COORDINATOR_CHAIN[5]: {"configuration": python_config("fa_coordinador", trigger, {
            "event_id": ref(trigger, "event_id"), "state_status": ref(extended, "status"),
            "status_code": ref(extended, "api_status_code"), "event_json": ref(extended, "event_json"),
            "snapshot_json": ref(extended, "snapshot_json"), "proposal_json": proposal})},
        COORDINATOR_CHAIN[6]: {"configuration": post_config(ref(compose, "path"), "commit", raw_ref(compose, "body_json"))},
        COORDINATOR_CHAIN[8]: {"configuration": python_config("fa_result", trigger, {
            "event_id": ref(trigger, "event_id"), "status_json": ref(final, "result_json"),
            "status_code": ref(final, "api_status_code")})},
    }


COMMUNICATION_NAMES = ("Acotar tick de recuperación", "Recuperar entregas", "Resumir entregas",
                       "Leer inbox pendiente", "Planificar reenvío")


def cron_config(expression, timezone="Europe/Madrid"):
    """Configuración del trigger Cron tal y como la declara la plataforma
    (`{cron: {expression, timezone}}`). Se valida aquí para no publicar un Cron
    que la plataforma vaya a rechazar o que dispare cada minuto por error."""
    if not isinstance(expression, str) or len(expression.split()) != 5:
        raise ValueError("cron expression must have five fields")
    if not isinstance(timezone, str) or "/" not in timezone:
        raise ValueError("cron timezone must be an IANA name")
    return {"cron": {"expression": expression, "timezone": timezone}}


def communication_nodes(trigger, limit=CRON_MAX):
    """Grafo del tick de recuperación: un solo POST acotado al puente, el resumen,
    y la lectura del inbox pendiente. Sin bucle: el puente ya reclama un lease por
    mensaje, así que repetir el tick no reenvía ni duplica."""
    if type(limit) is not int or not 1 <= limit <= 16:
        raise ValueError("invalid_recovery_limit")
    return [
        {"type": "action", "name": COMMUNICATION_NAMES[0], "event_id": EVENTS["python"], "parent_node_id": trigger,
         "configuration": python_config("fa_comunicaciones_recover", trigger, {"limit": str(limit)})},
        {"type": "action", "name": COMMUNICATION_NAMES[1], "event_id": EVENTS["post"], "parent_node_index": 0,
         "configuration": post_config("/outbox/recover", "delivery", json.dumps({"limit": limit}))},
        {"type": "action", "name": COMMUNICATION_NAMES[2], "event_id": EVENTS["python"], "parent_node_index": 1,
         "configuration": python_config("fa_comunicaciones_resumen", trigger, {"results_json": "[]"})},
        {"type": "action", "name": COMMUNICATION_NAMES[3], "event_id": EVENTS["post"], "parent_node_index": 2,
         "configuration": post_config("/inbox/batch", "read", json.dumps({}))},
        {"type": "action", "name": COMMUNICATION_NAMES[4], "event_id": EVENTS["python"], "parent_node_index": 3,
         "configuration": python_config("fa_comunicaciones_inbox", trigger, {"items_json": "[]"})},
    ]


def communication_bindings(nodes, trigger):
    """Enlaza el grafo con los persistent IDs reales. `RECOVER_RESULTS_FIELD` e
    `INBOX_ITEMS_FIELD` son los nombres que publica cada nodo POST; si la versión
    desplegada los expone con otro nombre, se cambia aquí y el grafo sigue igual."""
    pid = lambda name: nodes[name]["persistent_id"]
    recovered, inbox = pid(COMMUNICATION_NAMES[1]), pid(COMMUNICATION_NAMES[3])
    return {
        COMMUNICATION_NAMES[1]: {"configuration": post_config(
            ref(pid(COMMUNICATION_NAMES[0]), "path"), "delivery", raw_ref(pid(COMMUNICATION_NAMES[0]), "body_json"))},
        COMMUNICATION_NAMES[2]: {"configuration": python_config("fa_comunicaciones_resumen", trigger, {
            "results_json": raw_ref(recovered, RECOVER_RESULTS_FIELD)})},
        COMMUNICATION_NAMES[4]: {"configuration": python_config("fa_comunicaciones_inbox", trigger, {
            "items_json": raw_ref(inbox, INBOX_ITEMS_FIELD)})},
    }
