"""`python -m motor.server doctor`: dice en claro qué falta para salir con el bot y la plataforma REALES.

Solo lee variables de entorno y hace peticiones que no lanzan nada: `getMe` a Telegram, GET a `MANDO_PUBLIC_URL` y
HEAD/GET al hook de HappyRobot (nunca POST: un POST lanzaría una llamada). No escribe nada y nunca imprime un secreto.
"""
from __future__ import annotations

import os
import re
from typing import Any

import httpx

from .comms_happyrobot import CONTACTS_PATH, NEVER_DIAL, allowed_numbers, load_contacts, normalize_number, shared_secret

OK, WARN, MISSING = "OK   ", "AVISO", "FALTA"


def _mask(v: str) -> str:
    return f"({len(v)} caracteres)" if v else "(vacío)"


def _get(url: str, method: str = "GET", timeout: float = 6.0, **kw: Any) -> tuple[int | None, str]:
    try:
        r = httpx.request(method, url, timeout=timeout, follow_redirects=True, **kw)
        return r.status_code, ""
    except httpx.HTTPError as e:
        return None, type(e).__name__


def checks(env: dict[str, str] | None = None) -> list[tuple[str, str, str]]:
    e = dict(os.environ if env is None else env)
    out: list[tuple[str, str, str]] = []
    add = lambda level, name, text: out.append((level, name, text))  # noqa: E731

    # --- secreto de los webhooks
    secret = e.get("HR_SECRET") or e.get("MANDO_HR_TOKEN") or ""
    if not secret:
        add(MISSING, "HR_SECRET", "sin secreto, /hr/* responde 503 y HappyRobot no puede devolver nada. export HR_SECRET=$(openssl rand -hex 16)")
    elif len(secret) < 16:
        add(WARN, "HR_SECRET", f"muy corto {_mask(secret)}: usa al menos 16 caracteres")
    else:
        add(OK, "HR_SECRET", f"configurado {_mask(secret)}; viaja como callback_token y vuelve en la cabecera X-Mando-Token")

    # --- URL pública: base de callback_url y del QR
    public = (e.get("MANDO_PUBLIC_URL") or "").rstrip("/")
    if not public:
        add(MISSING, "MANDO_PUBLIC_URL", "sin URL pública la plataforma no puede devolver resultados (callback_url) y el QR usa la IP local. "
            "El túnel lo abre una PERSONA: cloudflared tunnel --url http://127.0.0.1:8000")
    elif not public.startswith("https://"):
        add(WARN, "MANDO_PUBLIC_URL", f"{public} no es https: la plataforma y el micrófono del navegador lo exigen")
    else:
        code, err = _get(public + "/api/state")
        if code == 200:
            add(OK, "MANDO_PUBLIC_URL", f"{public} responde desde fuera (GET /api/state → 200). callback_url = {public}/hr/events")
        else:
            add(MISSING, "MANDO_PUBLIC_URL", f"{public} no responde ({code or err}). ¿Está arrancado el servidor y vivo el túnel?")

    # --- lista blanca y contactos
    allowed = allowed_numbers() if env is None else {normalize_number(x) for x in e.get("MANDO_ALLOWED_NUMBERS", "").split(",") if x.strip()}
    contacts = load_contacts()
    numbers = {rid: normalize_number(v.get("to_number") if isinstance(v, dict) else v) for rid, v in contacts["resources"].items()}
    numbers = {k: v for k, v in numbers.items() if v}
    if not allowed:
        add(MISSING, "MANDO_ALLOWED_NUMBERS", "lista blanca vacía: NO se marca a nadie (todo sigue en simulación). export MANDO_ALLOWED_NUMBERS=+34…,+34…")
    else:
        bad = [n for n in allowed if n in NEVER_DIAL or n.lstrip("+") in NEVER_DIAL or not re.fullmatch(r"\+[1-9]\d{7,14}", n)]
        outside = [rid for rid, n in numbers.items() if n not in allowed]
        if bad:
            add(MISSING, "MANDO_ALLOWED_NUMBERS", f"{len(bad)} número(s) no válidos o de emergencias: nunca se marcarán. Formato E.164 (+34600111222)")
        else:
            add(OK, "MANDO_ALLOWED_NUMBERS", f"{len(allowed)} número(s) autorizados")
        if outside:
            add(WARN, "contacts.local.json", f"recursos con teléfono FUERA de la lista blanca (no se les llamará): {', '.join(sorted(outside))}")
    if not contacts["resources"]:
        add(WARN, "contacts.local.json", f"sin contactos reales en {CONTACTS_PATH.name}: todas las llamadas se simulan. cp contacts.example.json contacts.local.json")
    else:
        add(OK, "contacts.local.json", f"{len(contacts['resources'])} recurso(s) con contacto real: {', '.join(sorted(contacts['resources']))}")

    # --- HappyRobot: hook de despacho (sin lanzar nada) y API
    mode = "phone" if e.get("MANDO_VOICE_MODE", "web_call") == "phone" else "web_call"
    add(OK, "MANDO_VOICE_MODE", f"{mode}: " + ("las órdenes salen por TELÉFONO (hook HR_HOOK_DISPATCH)" if mode == "phone"
                                               else "las órdenes salen por LLAMADA WEB. Para teléfono real: export MANDO_VOICE_MODE=phone"))
    hook = e.get("HR_HOOK_DISPATCH") or ""
    if not hook:
        add(MISSING if mode == "phone" else WARN, "HR_HOOK_DISPATCH", "sin la URL del «Incoming hook» de mando-despacho-telefono no sale ninguna llamada")
    else:
        code, err = _get(hook, "HEAD")
        if code is None or code >= 500:
            code, err = _get(hook, "GET")
        host = re.sub(r"^(https?://[^/]+).*", r"\1", hook)
        if code is None:
            add(MISSING, "HR_HOOK_DISPATCH", f"{host} no es alcanzable ({err}). No se ha lanzado ninguna llamada")
        elif code in (401, 403):
            add(WARN, "HR_HOOK_DISPATCH", f"{host} contesta {code}: el trigger pide autenticación (Enhanced Security) → hace falta HR_API_KEY")
        else:
            add(OK, "HR_HOOK_DISPATCH", f"{host} alcanzable (HTTP {code} a HEAD/GET; no se ha lanzado ninguna llamada). "
                "OJO: el workflow tiene que estar PUBLICADO, no en borrador")
    for name, why in (("HR_API_BASE", "https://platform.eu.happyrobot.ai/api/v2 (llamada web, Signals, escucha y transcripción en vivo)"),
                      ("HR_API_KEY", "Bearer de la API; nunca en el repo"), ("HR_WORKFLOW_WEBCALL", "slug de mando-despacho-webcall (cq1s1v3ay7yg)")):
        add(OK if e.get(name) else (MISSING if mode == "web_call" else WARN), name, ("configurada" if e.get(name) else f"sin configurar: {why}"))
    for name, why in (("HR_HOOK_INTAKE", "entendimiento delegado de avisos de texto: sin él se entienden en local"),
                      ("HR_WEBCALL_PUBLIC_URL", "botón «Avisar por voz» de /jurado y /asistente"),
                      ("HR_INTAKE_EMAIL", "dirección de email de avisos que se enseña al público"), ("HR_SMS_NUMBER", "número para avisos por SMS")):
        add(OK if e.get(name) else WARN, name, "configurada" if e.get(name) else f"opcional, sin configurar: {why}")

    # --- Telegram
    token = (e.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        add(MISSING, "TELEGRAM_BOT_TOKEN", "sin token el bot no arranca (el servidor sí). Créalo con @BotFather → /newbot y export TELEGRAM_BOT_TOKEN=…")
    elif not re.fullmatch(r"\d{5,}:[\w-]{20,}", token) and not e.get("TELEGRAM_API_BASE"):
        add(MISSING, "TELEGRAM_BOT_TOKEN", "no tiene forma de token de BotFather (123456789:AA…)")
    else:
        base = (e.get("TELEGRAM_API_BASE") or "https://api.telegram.org").rstrip("/")
        try:
            r = httpx.post(f"{base}/bot{token}/getMe", timeout=8)
            data = r.json()
            if data.get("ok"):
                add(OK, "TELEGRAM_BOT_TOKEN", f"getMe → @{data['result'].get('username')} (enlace para el público: https://t.me/{data['result'].get('username')})")
            else:
                add(MISSING, "TELEGRAM_BOT_TOKEN", f"Telegram lo rechaza: {data.get('error_code')} {data.get('description')}")
        except (httpx.HTTPError, ValueError) as ex:
            add(MISSING, "TELEGRAM_BOT_TOKEN", f"no se pudo hablar con Telegram ({type(ex).__name__}). ¿Hay salida a internet?")

    # --- resto
    for name, why, level in (("MANDO_MCP_TOKEN", "sin él /mcp responde 503 (servidor MCP apagado)", WARN),
                             ("MANDO_OPERATOR_TOKEN", "sin él solo se puede operar desde esta máquina", WARN)):
        add(OK if e.get(name) else level, name, f"configurado {_mask(e[name])}" if e.get(name) else why)
    if shared_secret() and e.get("MANDO_MCP_TOKEN") and shared_secret() == e.get("MANDO_MCP_TOKEN"):
        add(WARN, "MANDO_MCP_TOKEN", "es igual que HR_SECRET: usa secretos distintos")
    return out


def main() -> int:
    rows = checks()
    print("MANDO · doctor — qué falta para salir con el bot y la plataforma reales\n")
    for level, name, text in rows:
        print(f"  [{level}] {name:<24} {text}")
    missing = [n for level, n, _ in rows if level == MISSING]
    print("\n" + (f"FALTA: {', '.join(dict.fromkeys(missing))}" if missing else "Todo lo imprescindible está. Avisos arriba, si los hay."))
    print("Arranque real:  uv run --project motor/server python -m motor.server --case demo-1 --comms happyrobot --lan")
    return 1 if missing else 0
