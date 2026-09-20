import argparse
import asyncio
import json
import logging
import os
import re
from pathlib import Path

from dotenv import dotenv_values
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[2]
SERVER = "https://mcp.platform.eu.happyrobot.ai/workflows/mcp"
MANIFEST = Path(__file__).with_name("workflows-v2.json")
SECRET_KEYS = ("HR_STATE_INGRESS_SECRET", "HR_STATE_READ_SECRET", "HR_STATE_COMMIT_SECRET",
               "HR_STATE_DELIVERY_SECRET", "VERCEL_AUTOMATION_BYPASS_SECRET")


def text(result):
    return "\n".join(item.text for item in result.content if item.type == "text")


def parse_nodes(details):
    nodes = []
    for block in details.split("\n### ")[1:]:
        heading = re.match(r"(.+) \(([^)]+)\)", block)
        node_id = re.search(r"- Node ID: ([0-9a-f-]{36})", block)
        persistent = re.search(r"- Persistent ID: ([0-9a-f-]{36})", block)
        parent = re.search(r"- Parent ID: ([0-9a-f-]{36})", block)
        if heading and node_id and persistent:
            nodes.append({"name": heading[1], "type": heading[2], "id": node_id[1],
                          "persistent_id": persistent[1], "parent_id": parent[1] if parent else None})
    return nodes


async def install_operations(session, workflow):
    from . import workflow_artifacts as artifacts

    async def call(tool, arguments):
        result = await session.call_tool(tool, arguments)
        if result.isError:
            raise RuntimeError("workflow_operation_failed:" + tool)
        return text(result)

    async def inventory():
        details = await call("get_workflow_details", {"workflow_id": workflow, "include_nodes": True})
        if "- Published: true" in details or "- Live: true" in details:
            raise RuntimeError("fork_published_version_first")
        section = details.split("## Latest Version", 1)[1]
        version = re.search(r"- ID: ([0-9a-f-]{36})", section)[1]
        return version, parse_nodes(details)

    version, nodes = await inventory()
    trigger = next(node for node in nodes if node["parent_id"] is None)
    if not any(node["name"] == "Reintentos CAS" for node in nodes):
        await call("update_workflow_nodes", {"version_id": version, "action": "add",
                   "nodes": json.dumps(artifacts.body_nodes(trigger["persistent_id"]), ensure_ascii=False)})
        await call("fix_broken_vars", {"version_id": version, "dry_run": True})
        version, nodes = await inventory()
    loop = next(node for node in nodes if node["name"] == "Reintentos CAS")
    ends = [node for node in nodes if node["type"] == "loop_end"]
    if len(ends) != 1:
        print(json.dumps({"nodes": nodes}, ensure_ascii=False))
        raise RuntimeError("loop_end_not_identified")
    if not any(node["name"] == "Leer estado final" for node in nodes):
        await call("update_workflow_nodes", {"version_id": version, "action": "add",
                   "nodes": json.dumps(artifacts.final_nodes(trigger["persistent_id"], ends[0]["id"]), ensure_ascii=False)})
        await call("fix_broken_vars", {"version_id": version, "dry_run": True})
        version, nodes = await inventory()
    if not any(node["name"] == "Leer cierre del intento" for node in nodes):
        parent = next(node for node in nodes if node["name"] == "Registrar resultado")
        await call("update_workflow_nodes", {"version_id": version, "action": "add", "nodes": json.dumps([
            {"type": "action", "name": "Leer cierre del intento", "event_id": artifacts.EVENTS["post"], "parent_node_id": parent["id"],
             "configuration": artifacts.post_config("/inbox/status", "commit", artifacts.status_body(trigger["persistent_id"]))},
        ])})
        await call("fix_broken_vars", {"version_id": version, "dry_run": True})
        version, nodes = await inventory()
    by_name = {node["name"]: node for node in nodes}
    for name, updates in artifacts.bindings(by_name, trigger["persistent_id"]).items():
        node = by_name[name]
        await call("get_node_details", {"version_id": version, "node_id": node["id"]})
        await call("update_workflow_nodes", {"version_id": version, "action": "update", "node_id": node["id"], "updates": json.dumps(updates)})
    path = by_name["¿Reintentar conflicto?"]
    primary = [node for node in nodes if node["parent_id"] == path["id"] and node["type"] == "condition" and "fallback" not in node["name"].lower()]
    if len(primary) != 1:
        print(json.dumps({"nodes": nodes}, ensure_ascii=False))
        raise RuntimeError("condition_not_identified")
    condition = primary[0]
    await call("get_node_details", {"version_id": version, "node_id": condition["id"]})
    await call("update_workflow_nodes", {"version_id": version, "action": "update", "node_id": condition["id"], "updates": json.dumps({
        "type_of_condition": "conditional", "conditions": [{"ors": [{"ands": [{
            "field": {"group_id": by_name["Confirmar transición"]["persistent_id"], "variable_id": "status"},
            "condition": "text_not_equals", "value": [{"type": "paragraph", "children": [{"text": "conflict"}]}],
        }]}]}],
    })})
    if not any(node["name"] == "Salir del intento" for node in nodes):
        await call("update_workflow_nodes", {"version_id": version, "action": "add", "nodes": json.dumps([
            {"type": "loop_break", "name": "Salir del intento", "parent_node_id": condition["id"]},
        ])})
    await call("fix_broken_vars", {"version_id": version, "dry_run": True})
    version, nodes = await inventory()
    print(json.dumps({"workflow_id": workflow, "version_id": version, "nodes": nodes}, ensure_ascii=False))


async def call_tool(session, tool, arguments):
    result = await session.call_tool(tool, arguments)
    if result.isError:
        raise RuntimeError("workflow_operation_failed:" + tool)
    return text(result)


async def workflow_snapshot(session, workflow):
    details = await call_tool(session, "get_workflow_details", {"workflow_id": workflow, "include_nodes": True})
    if "- Published: true" in details or "- Live: true" in details:
        raise RuntimeError("fork_published_version_first")
    version = re.search(r"- ID: ([0-9a-f-]{36})", details.split("## Latest Version", 1)[1])[1]
    return version, parse_nodes(details)


async def add_sequential(session, workflow, nodes):
    """Añade una cadena lineal de nodos de uno en uno, colgando cada uno del anterior.

    Un lote con el código completo de cada Sandbox supera el límite del endpoint
    («Payload Too Large»), así que no se pueden enviar juntos. Es idempotente: si el
    primer nodo ya existe, no vuelve a añadir nada."""
    version, current = await workflow_snapshot(session, workflow)
    if nodes[0]["name"] in {node["name"] for node in current}:
        return version, current
    parent = next(node["persistent_id"] for node in current if node["parent_id"] is None)
    for node in nodes:
        name = node["name"]
        payload = {key: value for key, value in node.items() if key not in ("parent_node_index", "parent_node_id")}
        payload["parent_node_id"] = parent
        await call_tool(session, "update_workflow_nodes", {"version_id": version, "action": "add",
                                                          "nodes": json.dumps([payload], ensure_ascii=False)})
        version, current = await workflow_snapshot(session, workflow)
        parent = next(item["persistent_id"] for item in current if item["name"] == name)
    return version, current


async def bind_nodes(session, version, nodes, bindings):
    by_name = {node["name"]: node for node in nodes}
    for name, updates in bindings.items():
        node = by_name[name]
        await call_tool(session, "get_node_details", {"version_id": version, "node_id": node["id"]})
        await call_tool(session, "update_workflow_nodes", {"version_id": version, "action": "update",
                                                          "node_id": node["id"], "updates": json.dumps(updates)})
    return by_name


async def install_coordinador(session, workflow):
    """Monta la cadena del coordinador, incluido el paso del modelo, sobre un workflow
    ya creado con trigger de webhook. No crea el workflow ni lo publica."""
    from . import workflow_artifacts as artifacts
    version, current = await workflow_snapshot(session, workflow)
    trigger = next(node for node in current if node["parent_id"] is None)
    version, current = await add_sequential(session, workflow, artifacts.coordinator_chain(trigger["persistent_id"]))
    await bind_nodes(session, version, current, artifacts.coordinator_chain_bindings(
        {node["name"]: node for node in current}, trigger["persistent_id"]))
    await call_tool(session, "fix_broken_vars", {"version_id": version, "dry_run": True})
    print(json.dumps({"workflow_id": workflow, "version_id": version,
                      "nodes": [node["name"] for node in current]}, ensure_ascii=False))


async def install_communications(session, workflow, schedule=None):
    """Monta el tick de recuperación sobre un workflow ya creado con trigger Cron.

    No crea el workflow: eso lo decide la persona autorizada. El Cron se configura al
    crear el trigger según el esquema de la plataforma; si se pasa `--schedule` aquí,
    se reescribe esa configuración."""
    from . import workflow_artifacts as artifacts

    if schedule is not None:
        artifacts.cron_config(schedule)
    version, current = await workflow_snapshot(session, workflow)
    trigger = next(node for node in current if node["parent_id"] is None)
    version, current = await add_sequential(session, workflow, artifacts.communication_nodes(trigger["persistent_id"]))
    await bind_nodes(session, version, current, artifacts.communication_bindings(
        {node["name"]: node for node in current}, trigger["persistent_id"]))
    if schedule is not None:
        block = re.search(r"```json\s*(.*?)\s*```", await call_tool(
            session, "get_node_details", {"version_id": version, "node_id": trigger["id"]}), re.S)
        if not block:
            raise RuntimeError("trigger_configuration_unavailable")
        configuration = json.loads(block[1])
        configuration.update(artifacts.cron_config(schedule))
        await call_tool(session, "update_workflow_nodes", {"version_id": version, "action": "update",
                                                          "node_id": trigger["id"],
                                                          "updates": json.dumps({"configuration": configuration})})
    await call_tool(session, "fix_broken_vars", {"version_id": version, "dry_run": True})
    print(json.dumps({"workflow_id": workflow, "version_id": version, "schedule": schedule,
                      "nodes": [node["name"] for node in current]}, ensure_ascii=False))


async def main(args):
    params = StdioServerParameters(command="npm", args=["exec", "--yes", "--package=mcp-remote@0.13.5", "--",
                                  "mcp-remote", SERVER, "--silent"], cwd=ROOT)
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            if args.command == "describe":
                tool = tools[args.tool]
                if args.field:
                    print(tool.inputSchema["properties"][args.field]["description"])
                else:
                    print(tool.description)
                    print(json.dumps(tool.inputSchema, ensure_ascii=False, indent=2))
                return
            if args.command == "info":
                result = await session.call_tool("get_connection_info", {})
                if result.isError:
                    raise RuntimeError("connection_failed")
                print(text(result))
                return
            manifest = json.loads(MANIFEST.read_text())
            allowed = {entry["id"] for entry in manifest["workflows"].values()}
            if args.workflow not in allowed:
                raise ValueError("workflow_not_in_manifest")
            if args.command == "install-operations":
                await install_operations(session, args.workflow)
                return
            if args.command == "install-comunicaciones":
                await install_communications(session, args.workflow, args.schedule)
                return
            if args.command == "install-coordinador":
                await install_coordinador(session, args.workflow)
                return
            if args.command == "probe-operations":
                from .probe_workflows import probe_operations
                entry = next(entry for entry in manifest["workflows"].values() if entry["id"] == args.workflow)
                await probe_operations(session, entry, manifest)
                return
            if args.command == "test-operations":
                entry = next(entry for entry in manifest["workflows"].values() if entry["id"] == args.workflow)
                result = await session.call_tool("get_workflow_details", {"workflow_id": args.workflow, "version_id": entry["version_id"], "include_nodes": True})
                details = text(result)
                if result.isError or "- Published: true" in details or "- Live: true" in details:
                    raise RuntimeError("test_requires_draft")
                nodes = {node["name"]: node for node in parse_nodes(details)}
                trigger = nodes["Procesar evento v2"]
                current = await session.call_tool("get_node_details", {"version_id": entry["version_id"], "node_id": trigger["id"]})
                block = re.search(r"```json\s*(.*?)\s*```", text(current), re.S)
                if current.isError or not block:
                    raise RuntimeError("trigger_configuration_unavailable")
                config = json.loads(block[1])
                if config.get("enhanced_security") and not config.get("api_key"):
                    key = dotenv_values(ROOT / "puente" / ".env.test").get("HR_STATE_INGRESS_SECRET")
                    if not key:
                        raise ValueError("missing_ingress_secret")
                    config.update(auth_type="api_key", api_key=key)
                    changed = await session.call_tool("update_workflow_nodes", {"version_id": entry["version_id"], "action": "update",
                        "node_id": trigger["id"], "updates": json.dumps({"configuration": config})})
                    if changed.isError:
                        raise RuntimeError("trigger_authentication_configuration_failed")
                for name in ("Procesar evento v2", "Leer contexto", "Calcular transición", "Confirmar transición", "Leer estado final", "Cerrar intento", "Registrar resultado", "Leer cierre del intento", "Resultado operación"):
                    result = await session.call_tool("test_workflow", {"action": "test_node", "version_id": entry["version_id"], "node_id": nodes[name]["id"], "environment": "development"})
                    output = text(result)
                    failed = bool(result.isError or re.search(r'^\s*"error"\s*:', output, re.M))
                    status = re.search(r'"status":\s*"([a-z_]+)"', output)
                    print(json.dumps({"node": name, "failed": failed, "status": status[1] if status else None}, ensure_ascii=False))
                    if failed:
                        raise RuntimeError("node_test_failed")
                return
            if args.command == "variables":
                values = dotenv_values(ROOT / "puente" / ".env.test")
                result = await session.call_tool("manage_variables", {"workflow_id": args.workflow, "action": "list"})
                safe = text(result)
                for key in SECRET_KEYS:
                    value = values.get(key)
                    if not value:
                        raise ValueError("missing_redaction_value")
                    safe = safe.replace(value, "[redacted]")
                print(safe)
                return
            if args.command == "sync-vars":
                values = dotenv_values(ROOT / "puente" / ".env.test")
                if any(not values.get(key) for key in SECRET_KEYS):
                    raise ValueError("missing_local_configuration")
                result = await session.call_tool("manage_variables", {"workflow_id": args.workflow, "action": "list"})
                if result.isError:
                    raise RuntimeError("variable_inventory_failed")
                existing = text(result)
                items = {"STATE_API_URL": manifest["preview_url"], **{key: values[key] for key in SECRET_KEYS}}
                for key, value in items.items():
                    if re.search(r"\b" + re.escape(key) + r"\b", existing):
                        print(json.dumps({"key": key, "status": "already_present"}))
                        continue
                    result = await session.call_tool("manage_variables", {"workflow_id": args.workflow, "action": "create",
                        "key": key, "value_production": "", "value_staging": "", "value_development": value,
                        "is_hidden_in_ui": key in SECRET_KEYS})
                    if result.isError:
                        print(json.dumps({"key": key, "status": "failed"}))
                        raise RuntimeError("variable_creation_failed")
                    print(json.dumps({"key": key, "status": "created", "environment": "development"}))


def describe_error(error, depth=0):
    """Aplana un ExceptionGroup anidado hasta la causa real, sin volcar payloads."""
    if isinstance(error, BaseExceptionGroup) and depth < 8:
        described = []
        for item in error.exceptions:
            described.extend(describe_error(item, depth + 1))
        return described
    described = ["%s: %s" % (type(error).__name__, str(error)[:400])]
    cause = error.__cause__ or error.__context__
    if cause is not None and cause is not error:
        described.append("caused by %s: %s" % (type(cause).__name__, str(cause)[:400]))
    return described


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("info", "describe", "sync-vars", "variables", "install-operations", "install-coordinador", "install-comunicaciones", "test-operations", "probe-operations"))
    parser.add_argument("--workflow")
    parser.add_argument("--schedule")
    parser.add_argument("--tool")
    parser.add_argument("--field")
    logging.disable(logging.CRITICAL)
    try:
        asyncio.run(main(parser.parse_args()))
    except Exception as exc:
        output = {"ok": False, "error_type": type(exc).__name__}
        if os.environ.get("FABAT_ADMIN_DEBUG") == "1":
            output["detail"] = describe_error(exc)
        print(json.dumps(output))
        raise SystemExit(1) from None
