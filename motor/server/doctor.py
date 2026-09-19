"""Diagnóstico de configuración y sondas de solo lectura; nunca lanza llamadas.

`--sin-red` examina únicamente configuración y ficheros. Ningún informe demuestra por sí
solo una llamada real: hacen falta un run y su callback observados.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from . import hr_config
from .comms_happyrobot import NEVER_DIAL, normalize_number

RAIZ = Path(__file__).resolve().parent
OK, WARN, MISSING = "OK   ", "AVISO", "FALTA"
IMPRESCINDIBLE, NECESARIO, OPCIONAL = "imprescindible", "necesario", "opcional"


@dataclass
class Comprobacion:
    clave: str
    estado: str
    consecuencia: str
    nivel: str = NECESARIO
    detalle: str = ""
    grupo: str = ""


@dataclass
class Diagnostico:
    comprobaciones: list[Comprobacion] = field(default_factory=list)
    modo: str = "simulada"
    criterios_en_riesgo: list[str] = field(default_factory=list)

    def anadir(self, c: Comprobacion) -> None:
        self.comprobaciones.append(c)

    def del_nivel(self, nivel: str) -> list[Comprobacion]:
        return [c for c in self.comprobaciones if c.nivel == nivel and c.estado != "ok"]

    def faltan_imprescindibles(self) -> list[Comprobacion]:
        return self.del_nivel(IMPRESCINDIBLE)

    def to_dict(self) -> dict[str, Any]:
        return {"modo": self.modo, "criterios_en_riesgo": self.criterios_en_riesgo,
                "comprobaciones": [vars(c).copy() for c in self.comprobaciones]}


def _url_segura(url: str) -> str:
    """No mostrar userinfo, fragmentos o parámetros que pueden contener credenciales."""
    try:
        p = urlsplit(url)
        host = p.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        if p.port:
            host += f":{p.port}"
        return urlunsplit((p.scheme, host, p.path, "", ""))
    except ValueError:
        return "URL no válida"


def _local(url: str) -> bool:
    try:
        return urlsplit(url).hostname in (None, "localhost", "127.0.0.1", "::1", "0.0.0.0")
    except ValueError:
        return True


def _get(url: str, method: str = "GET", timeout: float = 6.0, **kw: Any) -> tuple[int | None, str]:
    try:
        r = httpx.request(method, url, timeout=timeout, follow_redirects=False, **kw)
        return r.status_code, ""
    except (httpx.HTTPError, ValueError) as ex:
        return None, type(ex).__name__


def _numeros_de(datos: dict[str, Any]) -> list[str]:
    numeros = []
    for grupo in ("resources", "roles"):
        contenido = datos.get(grupo)
        if not isinstance(contenido, dict):
            continue
        for valor in contenido.values():
            if isinstance(valor, str):
                numeros.append(valor)
            elif isinstance(valor, dict):
                numeros.extend(str(valor[c]) for c in ("to_number", "number", "phone", "telefono") if valor.get(c))
    allowed = datos.get("allowed_numbers", [])
    if isinstance(allowed, str):
        numeros.extend(allowed.split(","))
    elif isinstance(allowed, list):
        numeros.extend(str(v) for v in allowed)
    return numeros


def _emergencia(numero: str) -> bool:
    n = normalize_number(numero)
    return n in NEVER_DIAL or n.lstrip("+") in NEVER_DIAL


def diagnosticar(sondear_red: bool = True, env: dict[str, str] | None = None) -> Diagnostico:
    e = dict(os.environ if env is None else env)
    d = Diagnostico()

    def add(clave: str, estado: str, consecuencia: str, nivel: str = NECESARIO,
            detalle: str = "", grupo: str = "plataforma") -> None:
        d.anadir(Comprobacion(clave, estado, consecuencia, nivel, detalle, grupo))

    # .env en la raíz FABAT (cargado por __main__ con python-dotenv; aquí solo informamos).
    env_file = RAIZ.parent.parent / ".env"
    if env_file.is_file():
        try:
            keys = [ln.split("=", 1)[0].strip() for ln in env_file.read_text(encoding="utf-8").splitlines()
                    if ln.strip() and not ln.lstrip().startswith("#") and "=" in ln]
            present = sum(1 for k in keys if e.get(k))
            add(".env", "ok",
                f"encontrado: {len(keys)} claves en fichero, {present} visibles en el proceso",
                OPCIONAL, grupo="ficheros", detalle=str(env_file))
        except OSError as ex:
            add(".env", "aviso", f"existe pero no se pudo leer: {ex}", OPCIONAL, grupo="ficheros")
    else:
        add(".env", "aviso",
            "no hay .env en la raíz FABAT: MANDO_VOICE_MODE/HR_* usan defaults del código",
            OPCIONAL, grupo="ficheros", detalle=str(env_file))

    voice_mode = e.get("MANDO_VOICE_MODE", "web_call").strip()
    phone = voice_mode == "phone"
    launch = e.get("HR_LAUNCH_MODE", "hook")
    api = hr_config.api_base(e)
    wf, urls = hr_config.workflow_ids(e), hr_config.workflow_urls(e)
    if voice_mode not in ("web_call", "phone"):
        add("MANDO_VOICE_MODE", "falta", f"valor «{voice_mode}» no reconocido: usa web_call o phone", NECESARIO)
    else:
        add("MANDO_VOICE_MODE", "ok", "despacho por teléfono" if phone else "despacho por llamada web", OPCIONAL)
    add("HR_ENV", "ok", "entorno resuelto", OPCIONAL, hr_config.environment(e))
    add("HR_PLATFORM_BASE", "ok", "plataforma resuelta", OPCIONAL, _url_segura(hr_config.platform_base(e)))
    try:
        host = urlsplit(api).hostname or ""
    except ValueError:
        host = ""
    cluster_incorrecto = host.endswith("happyrobot.ai") and host != "platform.eu.happyrobot.ai"
    add("HR_API_BASE", "aviso" if cluster_incorrecto else "ok",
        "clúster distinto de EU: una clave EU puede responder 401 o 404; comprueba el clúster antes de cambiar la clave"
        if cluster_incorrecto else "base API configurada; esto no verifica credenciales",
        IMPRESCINDIBLE if cluster_incorrecto else NECESARIO, _url_segura(api))
    clave = e.get("HR_API_KEY", "")
    add("HR_API_KEY", "ok" if clave else "falta", "clave configurada; autenticación pendiente de verificar" if clave else
        "sin clave no se pueden pedir tokens web ni leer runs: el sello puede quedar `real: false`",
        IMPRESCINDIBLE if not phone or launch == "runs" else OPCIONAL, "definida" if clave else "")
    secret = e.get("HR_SECRET") or e.get("MANDO_HR_TOKEN") or ""
    add("HR_SECRET", "ok" if secret else "falta", "firma callbacks con X-Mando-Token" if secret else
        "sin secreto los endpoints /hr/* responden 503 y se pierde el resultado", IMPRESCINDIBLE)
    if secret and len(secret) < 16:
        add("HR_SECRET longitud", "aviso", "usa al menos 16 caracteres", NECESARIO)
    add("HR_WORKFLOW_WEBCALL", "ok" if wf.get("webcall") else "falta",
        "workflow configurado" if wf.get("webcall") else "sin workflow no se abre la llamada web",
        OPCIONAL if phone else IMPRESCINDIBLE)
    add("HR_LAUNCH_MODE", "ok", "lanzamiento por API runs" if launch == "runs" else "lanzamiento por hook", OPCIONAL)
    if phone and launch == "runs":
        add("HR_WORKFLOW_DISPATCH", "ok" if wf.get("dispatch") else "falta",
            "workflow configurado" if wf.get("dispatch") else "sin id no se puede crear el run de despacho", IMPRESCINDIBLE)
    hook = urls.get("dispatch", "")
    add("HR_HOOK_DISPATCH", "ok" if hook else "falta", "URL configurada; publicación pendiente de verificar" if hook else
        "sin Incoming hook no se lanza despacho telefónico por hook", IMPRESCINDIBLE if phone and launch != "runs" else OPCIONAL)
    for name, url in urls.items():
        add(f"URL {name}", "ok" if url else "degradado", "URL resuelta; no prueba publicación del workflow" if url else
            "sin URL resuelta", OPCIONAL, _url_segura(url) if url else "")

    public = (e.get("MANDO_PUBLIC_URL") or e.get("MANDO_CALLBACK_URL") or "").rstrip("/")
    callback_key = "MANDO_PUBLIC_URL" if e.get("MANDO_PUBLIC_URL") or not e.get("MANDO_CALLBACK_URL") else "MANDO_CALLBACK_URL"
    public_ok = bool(public) and not _local(public) and public.startswith("https://")
    add(callback_key, "ok" if public_ok else ("aviso" if public else "falta"),
        "callback configurado; alcance pendiente de verificar" if public_ok else
        "la plataforma no puede llamar a 127.0.0.1; hace falta una URL pública HTTPS para recibir callbacks",
        IMPRESCINDIBLE, _url_segura(public) if public else "")
    for name in ("MANDO_OPERATOR_TOKEN", "MANDO_MCP_TOKEN"):
        add(name, "ok" if e.get(name) else "falta", "configurado" if e.get(name) else
            ("sin token las operaciones remotas quedan bloqueadas" if name == "MANDO_OPERATOR_TOKEN" else "sin token /mcp responde 503"),
            IMPRESCINDIBLE if public and not _local(public) else OPCIONAL, grupo="operación")
    if secret and secret == e.get("MANDO_MCP_TOKEN"):
        add("MANDO_MCP_TOKEN separación", "aviso", "usa un secreto distinto de HR_SECRET", grupo="operación")

    path = Path(e.get("MANDO_CONTACTS") or RAIZ / "contacts.local.json")
    try:
        contacts = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(contacts, dict) or any(not isinstance(contacts.get(g, {}), dict) for g in ("resources", "roles")):
            raise ValueError("estructura")
    except (OSError, ValueError):
        contacts = {}
    danger = any(_emergencia(n) for n in _numeros_de(contacts))
    has_contacts = any(value for g in ("resources", "roles") for value in contacts.get(g, {}).values())
    add("contacts.local.json", "falta" if danger or not has_contacts else "ok",
        "contiene números bloqueados por NEVER_DIAL: retirar emergencias antes de la demo" if danger else
        ("contactos presentes; no se muestran números" if has_contacts else "sin contactos utilizables todo lo contesta SimComms"),
        IMPRESCINDIBLE, grupo="ficheros")
    allowed = {normalize_number(n) for n in e.get("MANDO_ALLOWED_NUMBERS", "").split(",") if n.strip()}
    bad = any(_emergencia(n) or not re.fullmatch(r"\+[1-9]\d{7,14}", n) for n in allowed)
    add("MANDO_ALLOWED_NUMBERS", "falta" if bad or not allowed else "ok",
        "lista contiene teléfonos inválidos o emergencias: se bloquean" if bad else
        (f"{len(allowed)} número(s) autorizados" if allowed else "lista vacía: no se marca ningún teléfono; la llamada web no la necesita"),
        IMPRESCINDIBLE if bad or phone else OPCIONAL, grupo="ficheros")
    if phone and has_contacts:
        routed = [normalize_number(v.get("to_number", "") if isinstance(v, dict) else v)
                  for g in ("resources", "roles") for v in contacts.get(g, {}).values()]
        if not any(n in allowed and not _emergencia(n) and re.fullmatch(r"\+[1-9]\d{7,14}", n) for n in routed):
            add("contactos telefónicos", "falta", "ningún to_number utilizable está autorizado: el despacho cae a SimComms",
                IMPRESCINDIBLE, grupo="ficheros")
        elif any(n and n not in allowed for n in routed):
            add("contactos telefónicos", "aviso", "hay contactos fuera de la lista blanca; no se les llamará", grupo="ficheros")
    if not phone:
        livekit = RAIZ / "static/vendor/livekit-client.umd.min.js"
        add("static/vendor/livekit-client.umd.min.js", "ok" if livekit.is_file() else "falta",
            "librería presente; audio pendiente de verificar" if livekit.is_file() else
            "sin LiveKit no abre el audio; copiar livekit-client.umd.js de https://unpkg.com/livekit-client@2.22.3/dist/livekit-client.umd.js",
            IMPRESCINDIBLE, grupo="ficheros")
    playbook = RAIZ.parent / "harness/out/playbook.learned.json"
    try:
        lessons = len(json.loads(playbook.read_text(encoding="utf-8"))["lessons"])
    except (OSError, ValueError, KeyError, TypeError):
        lessons = None
    add("harness/out/playbook.learned.json", "ok" if lessons is not None else "degradado",
        f"manual aprendido con {lessons} lecciones" if lessons is not None else
        "sin manual aprendido válido, --playbook auto usa el de siembra", OPCIONAL, grupo="ficheros")

    # Ledger SQLite: auditoría durable; si no escribe, la demo sigue (degradado).
    try:
        from .ledger import open_ledger
        led = open_ledger()
        st = led.stats()
        led.close()
        if st.get("enabled"):
            add("ledger.sqlite", "ok",
                f"auditoría local: {st.get('episodes', 0)} episodios, {st.get('events', 0)} eventos"
                + (f" ({st['path']})" if st.get("path") else ""),
                OPCIONAL, grupo="ficheros", detalle=str(st.get("path") or ""))
        else:
            add("ledger.sqlite", "degradado",
                "no escribible; las llamadas no se auditan en disco (demo sigue)",
                OPCIONAL, grupo="ficheros", detalle=str(st.get("warning") or ""))
    except Exception as ex:
        add("ledger.sqlite", "degradado", f"ledger no disponible: {type(ex).__name__}", OPCIONAL, grupo="ficheros")

    # LLM cascada (Helmcode / AI Gateway): solo si hay clave y MANDO_LLM=1; no gasta cuota en doctor.
    try:
        from . import llm_parser_factory
        st = llm_parser_factory.status_for_doctor()
        ok_cfg, detail = llm_parser_factory.llm_configured()
        if ok_cfg:
            add("MANDO_LLM / Helmcode", "ok",
                f"cascada lista vía {st['gateway']}: {st['model']}", OPCIONAL, grupo="plataforma",
                detalle=st["base"])
        elif st["key_set"] == "yes":
            add("MANDO_LLM / Helmcode", "aviso",
                "clave presente pero MANDO_LLM≠1: demo usa solo heurístico (no gasta tokens)",
                OPCIONAL, grupo="plataforma", detalle=detail)
        else:
            add("MANDO_LLM / Helmcode", "degradado",
                "sin AGENTES_LLM_KEY: avisos libres solo con reglas; confirma crédito Helmcode",
                OPCIONAL, grupo="plataforma", detalle=detail)
    except Exception as ex:
        add("MANDO_LLM / Helmcode", "degradado", f"factory LLM: {type(ex).__name__}", OPCIONAL, grupo="plataforma")

    for name, why in (("HR_HOOK_INTAKE", "sin intake remoto se entienden avisos en local"),
                      ("HR_WEBCALL_PUBLIC_URL", "sin enlace público para avisar por voz"),
                      ("HR_INTAKE_EMAIL", "sin dirección de avisos por email"), ("HR_SMS_NUMBER", "sin canal SMS")):
        value = urls.get("intake") if name == "HR_HOOK_INTAKE" else e.get(name)
        add(name, "ok" if value else "degradado", "configurado" if value else why, OPCIONAL)

    mode = e.get("TELEGRAM_MODE", "poll")
    token = e.get("TELEGRAM_BOT_TOKEN", "").strip()
    add("TELEGRAM_MODE", "ok" if mode in ("poll", "send_only", "off") else "falta",
        {"poll": "recepción por polling", "send_only": "solo envía; no recibe mensajes", "off": "Telegram desactivado"}.get(mode, "modo inválido"),
        IMPRESCINDIBLE, grupo="operación")
    if public_ok and mode == "poll":
        add("TELEGRAM_MODE espejo", "aviso",
            "con túnel público y puente Vercel el bot Python no debe hacer poll: usa send_only u off",
            NECESARIO, grupo="operación")
    cors = [x.strip() for x in e.get("MANDO_CORS_ORIGINS", "").replace(";", ",").split(",") if x.strip()]
    if public_ok and not cors:
        add("MANDO_CORS_ORIGINS", "aviso",
            "vacío: otra interfaz en otro origen no podrá llamar a la API; define orígenes HTTPS si hace falta",
            OPCIONAL, grupo="operación")
    if mode != "off":
        valid = bool(token) and (bool(e.get("TELEGRAM_API_BASE")) or bool(re.fullmatch(r"\d{5,}:[\w-]{20,}", token)))
        tg_text = "configurado; identidad pendiente de verificar" if valid else "sin token válido el bot no arranca"
        tg_state = "ok" if valid else "falta"
        if valid and sondear_red:
            base = (e.get("TELEGRAM_API_BASE") or "https://api.telegram.org").rstrip("/")
            try:
                data = httpx.post(f"{base}/bot{token}/getMe", timeout=8).json()
                username = str((data.get("result") or {}).get("username", ""))
                tg_state = "ok" if data.get("ok") else "falta"
                tg_text = f"getMe → @{username}" if data.get("ok") and re.fullmatch(r"[A-Za-z0-9_]+", username) else "Telegram responde" if data.get("ok") else "Telegram rechaza el token"
                info = httpx.post(f"{base}/bot{token}/getWebhookInfo", timeout=8).json()
                if info.get("ok"):
                    active = bool((info.get("result") or {}).get("url"))
                    add("TELEGRAM_WEBHOOK", "aviso" if active and mode == "poll" else "ok",
                        "webhook activo con poll: Telegram rechaza getUpdates; resuelve el modo antes de arrancar" if active and mode == "poll" else
                        "sin conflicto entre webhook y modo configurado", NECESARIO, grupo="red")
                else:
                    add("TELEGRAM_WEBHOOK", "aviso", "getWebhookInfo no verificó el webhook", grupo="red")
            except (httpx.HTTPError, ValueError, AttributeError, TypeError) as ex:
                tg_state, tg_text = "falta", f"no se pudo verificar Telegram ({type(ex).__name__})"
        add("TELEGRAM_BOT_TOKEN", tg_state, tg_text, IMPRESCINDIBLE, grupo="operación")

    if sondear_red:
        if public_ok:
            code, err = _get(public + "/api/state")
            add("alcance callback", "ok" if code == 200 else "falta",
                f"GET /api/state: {code or err}; no verifica la entrega de un callback", IMPRESCINDIBLE, grupo="red")
        if hook and phone and launch != "runs":
            code, err = _get(hook, "HEAD")
            state = "ok" if code is not None and code < 500 and code not in (401, 403, 404) else "aviso"
            # Sustituye el estado de configuración para conservar checks() del doctor original.
            row = next(c for c in d.comprobaciones if c.clave == "HR_HOOK_DISPATCH")
            row.estado = state
            row.consecuencia = f"HEAD: {code or err}; no verifica publicación ni lanza llamadas"
            if code in (401, 403):
                row.consecuencia += "; Enhanced Security puede exigir HR_API_KEY"
        if clave or e.get("HR_API_BASE"):
            code, err = _get(api + "/runs?limit=1", headers={"Authorization": f"Bearer {clave}"} if clave else {})
            if code in (401, 403):
                add("plataforma EU", "falta" if clave else "aviso",
                    "la clave es rechazada: comprueba clúster y permisos; este código no demuestra cuál falla" if clave else
                    "la plataforma responde sin autenticar: falta HR_API_KEY; el 401 no demuestra que el clúster sea correcto",
                    IMPRESCINDIBLE if clave else OPCIONAL, grupo="red")
            else:
                add("plataforma EU", "ok" if code is not None and 200 <= code < 300 else "aviso",
                    f"GET runs: {code or err}; no demuestra una llamada real", NECESARIO, grupo="red")
    else:
        add("verificación de red", "degradado", "sin red: solo configuración, sin verificar credenciales ni llamadas", OPCIONAL, grupo="red")

    blocked = {c.clave for c in d.faltan_imprescindibles()}
    d.modo = "simulada" if blocked else "configurada"
    if blocked & {"HR_API_KEY", "HR_WORKFLOW_WEBCALL", "HR_HOOK_DISPATCH", "HR_WORKFLOW_DISPATCH"}:
        d.criterios_en_riesgo.extend(["1 · un run real en la plataforma queda en riesgo", "2 · el sello `real: true` puede quedar `real: false`"])
    for c in d.faltan_imprescindibles():
        if c.clave not in {"HR_API_KEY", "HR_WORKFLOW_WEBCALL", "HR_HOOK_DISPATCH", "HR_WORKFLOW_DISPATCH"}:
            d.criterios_en_riesgo.append(c.consecuencia)
    return d


def checks(env: dict[str, str] | None = None) -> list[tuple[str, str, str]]:
    return [(OK if c.estado == "ok" else MISSING if c.nivel == IMPRESCINDIBLE else WARN,
             c.clave, " · ".join(filter(None, (c.detalle, c.consecuencia)))) for c in diagnosticar(env=env).comprobaciones]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m motor.server doctor", description="Diagnóstico de solo lectura")
    ap.add_argument("--sin-red", action="store_true", help="no realizar ninguna petición de red")
    ap.add_argument("--json", metavar="FICHERO", help="guardar el informe en el fichero indicado")
    args = ap.parse_args([] if argv is None else argv)
    d = diagnosticar(sondear_red=not args.sin_red)
    if args.json:
        Path(args.json).write_text(json.dumps(d.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print("MANDO · doctor — configuración y consecuencias\n")
    for c in d.comprobaciones:
        level = OK if c.estado == "ok" else MISSING if c.nivel == IMPRESCINDIBLE else WARN
        print(f"  [{level}] {c.clave:<28} {' · '.join(filter(None, (c.detalle, c.consecuencia)))}")
    missing = d.faltan_imprescindibles()
    print("\n" + ("FALTA: " + ", ".join(c.clave for c in missing) if missing else "Configuración completa; una llamada real y su callback siguen pendientes de verificar."))
    print(f"MODO DE LA DEMO: {d.modo.upper()}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
