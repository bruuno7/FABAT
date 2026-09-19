"""Clientes de modelo. Solo biblioteca estándar (`urllib`), con tiempo de espera siempre puesto.

Reglas de este fichero, que no se negocian:

- **Ninguna clave se imprime, ni entera ni en un error.** Solo se dice si está o no está.
- **Ningún agente construye un cliente por su cuenta**: se le inyecta uno. Igual que en `motor/`.
- **El modo por defecto es `seco`**: sin red y sin gasto. Salir de ahí es una decisión explícita,
  porque gastar cuota o dinero es de una persona, no del agente (`AGENTS.md`).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .contratos import ModoProveedor, Respuesta

TIEMPO_ESPERA = 60


def _pedir(url: str, cabeceras: dict[str, str], cuerpo: dict, tiempo: int = TIEMPO_ESPERA) -> tuple[int, dict | str]:
    """POST de JSON. Devuelve (código, cuerpo). Nunca lanza por un error HTTP ni deja escapar la clave."""
    datos = json.dumps(cuerpo).encode("utf-8")
    req = urllib.request.Request(url, data=datos, headers=cabeceras, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=tiempo) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, f"HTTP {e.code}"
    except Exception as e:  # red caída, DNS, tiempo agotado
        return 0, f"{type(e).__name__}: {e}"


def _mensaje_error(codigo: int, cuerpo: dict | str) -> str:
    if isinstance(cuerpo, dict):
        err = cuerpo.get("error")
        if isinstance(err, dict):
            return f"HTTP {codigo}: {err.get('message') or err.get('type') or err}"
        if err:
            return f"HTTP {codigo}: {err}"
        return f"HTTP {codigo}: {json.dumps(cuerpo)[:200]}"
    return f"HTTP {codigo}: {cuerpo}"


# ------------------------------------------------------------------------------------------- seco


class ProveedorSeco:
    """Sin red y sin gasto. No inventa código: devuelve el encargo listo para que una persona lo
    pegue en su sesión de Claude Code.

    No es un apaño para cuando falla la red: es el modo **previsto** del equipo. Hay una sola
    suscripción y una sola operadora (MVP.md §2.4), así que lo que de verdad hace falta a escala es
    el encargo bien escrito, no otra tubería que gaste cuota.
    """

    nombre = "seco"
    modo = ModoProveedor.SECO

    def disponible(self) -> tuple[bool, str]:
        return True, "siempre disponible: no usa red"

    def completar(self, sistema: str, usuario: str, max_tokens: int = 4000) -> Respuesta:
        texto = (
            "<!-- ENCARGO GENERADO EN MODO SECO -->\n"
            "No se ha llamado a ningún modelo. Abajo está el prompt completo, listo para pegar en\n"
            "una sesión de Claude Code con `/model sonnet`. Pega primero el bloque de SISTEMA y\n"
            "luego el de ENCARGO, en el mismo turno y sin nada más.\n\n"
            "================================ SISTEMA ================================\n"
            f"{sistema}\n\n"
            "================================ ENCARGO ================================\n"
            f"{usuario}\n"
        )
        return Respuesta(texto=texto, modelo="(ninguno)", proveedor=ModoProveedor.SECO)


# -------------------------------------------------------------------------------------- anthropic


class ProveedorAnthropic:
    """API de Anthropic. **Gasta dinero de verdad** (créditos de Console, no la suscripción Max).

    Por eso nunca se elige solo: hay que pedirlo con `--proveedor anthropic`.
    """

    nombre = "anthropic"
    modo = ModoProveedor.ANTHROPIC
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, modelo: str = "claude-sonnet-4-20250514", clave: str | None = None) -> None:
        self.modelo = modelo
        self._clave = clave or os.environ.get("ANTHROPIC_API_KEY", "")

    def disponible(self) -> tuple[bool, str]:
        if not self._clave:
            return False, "falta ANTHROPIC_API_KEY en el entorno"
        codigo, cuerpo = _pedir(
            self.URL,
            {"x-api-key": self._clave, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            {"model": "claude-3-5-haiku-20241022", "max_tokens": 4, "messages": [{"role": "user", "content": "ok"}]},
            tiempo=20,
        )
        if codigo == 200:
            return True, f"clave válida, modelo {self.modelo}"
        return False, _mensaje_error(codigo, cuerpo)

    def completar(self, sistema: str, usuario: str, max_tokens: int = 4000) -> Respuesta:
        if not self._clave:
            return Respuesta("", proveedor=self.modo, error="falta ANTHROPIC_API_KEY")
        codigo, cuerpo = _pedir(
            self.URL,
            {"x-api-key": self._clave, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            {
                "model": self.modelo,
                "max_tokens": max_tokens,
                "system": sistema,
                "messages": [{"role": "user", "content": usuario}],
            },
        )
        if codigo != 200 or not isinstance(cuerpo, dict):
            return Respuesta("", self.modelo, self.modo, error=_mensaje_error(codigo, cuerpo))
        trozos = [b.get("text", "") for b in cuerpo.get("content", []) if b.get("type") == "text"]
        uso = cuerpo.get("usage", {})
        return Respuesta(
            texto="".join(trozos),
            modelo=cuerpo.get("model", self.modelo),
            proveedor=self.modo,
            tokens_entrada=uso.get("input_tokens", 0),
            tokens_salida=uso.get("output_tokens", 0),
        )


# ------------------------------------------------------------------------------- compatible OpenAI


class ProveedorOpenAICompat:
    """Cualquier API con forma de OpenAI: Helmcode, Cloudflare AI Gateway, OpenRouter.

    Se configura con dos variables, `AGENTES_LLM_BASE` y `AGENTES_LLM_KEY`, para no atar el código
    a un proveedor. El modelo por defecto es el de Helmcode del expediente.
    """

    nombre = "openai_compat"
    modo = ModoProveedor.OPENAI_COMPAT

    def __init__(self, base: str | None = None, modelo: str | None = None, clave: str | None = None) -> None:
        self.base = (base or os.environ.get("AGENTES_LLM_BASE") or "https://api.helmcode.com/v1").rstrip("/")
        self.modelo = modelo or os.environ.get("AGENTES_LLM_MODEL") or "deepseek-v4-flash"
        self._clave = clave or os.environ.get("AGENTES_LLM_KEY") or os.environ.get("HELMCODE_API_KEY", "")

    def disponible(self) -> tuple[bool, str]:
        if not self._clave:
            return False, f"falta AGENTES_LLM_KEY para {self.base}"
        codigo, cuerpo = _pedir(
            f"{self.base}/chat/completions",
            {"Authorization": f"Bearer {self._clave}", "Content-Type": "application/json"},
            {"model": self.modelo, "max_tokens": 4, "messages": [{"role": "user", "content": "ok"}]},
            tiempo=20,
        )
        if codigo == 200:
            return True, f"{self.base} responde con {self.modelo}"
        return False, _mensaje_error(codigo, cuerpo)

    def completar(self, sistema: str, usuario: str, max_tokens: int = 4000) -> Respuesta:
        if not self._clave:
            return Respuesta("", proveedor=self.modo, error="falta AGENTES_LLM_KEY")
        codigo, cuerpo = _pedir(
            f"{self.base}/chat/completions",
            {"Authorization": f"Bearer {self._clave}", "Content-Type": "application/json"},
            {
                "model": self.modelo,
                "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
            },
        )
        if codigo != 200 or not isinstance(cuerpo, dict):
            return Respuesta("", self.modelo, self.modo, error=_mensaje_error(codigo, cuerpo))
        opciones = cuerpo.get("choices") or [{}]
        uso = cuerpo.get("usage", {})
        return Respuesta(
            texto=(opciones[0].get("message") or {}).get("content", ""),
            modelo=cuerpo.get("model", self.modelo),
            proveedor=self.modo,
            tokens_entrada=uso.get("prompt_tokens", 0),
            tokens_salida=uso.get("completion_tokens", 0),
        )


# ---------------------------------------------------------------------------------------- fábrica


CATALOGO: dict[str, type] = {
    "seco": ProveedorSeco,
    "anthropic": ProveedorAnthropic,
    "openai_compat": ProveedorOpenAICompat,
}


def construir(nombre: str = "seco", **kwargs):
    """Devuelve un proveedor por nombre. Por defecto, el que no gasta nada."""
    clase = CATALOGO.get(nombre)
    if clase is None:
        raise ValueError(f"proveedor desconocido: {nombre!r}. Hay: {', '.join(CATALOGO)}")
    return clase(**kwargs)


def diagnostico() -> list[tuple[str, bool, str]]:
    """Prueba los tres proveedores y dice cuál se puede usar. No imprime ninguna clave."""
    salida: list[tuple[str, bool, str]] = []
    for nombre in CATALOGO:
        try:
            ok, detalle = construir(nombre).disponible()
        except Exception as e:  # un proveedor roto no tumba el diagnóstico de los demás
            ok, detalle = False, f"{type(e).__name__}: {e}"
        salida.append((nombre, ok, detalle))
    return salida
