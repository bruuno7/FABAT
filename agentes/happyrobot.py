"""Cliente de la API de HappyRobot (clúster EU) y sonda de diagnóstico.

Comprobado el 19-sep-2026 a la 01:55 desde este repositorio, **sin clave**:

    GET https://platform.eu.happyrobot.ai/api/v2/runs   →  HTTP 401 {"error":"missing bearer token"}

Eso confirma dos cosas que hasta ahora eran suposiciones del expediente: la URL base es correcta y
la autenticación es **Bearer**, no cabecera propia ni parámetro. Lo que no se ha podido comprobar es
ninguna respuesta con datos, porque no hay `HR_API_KEY` en el entorno de esta máquina.

Trampa número uno de la plataforma, documentada en `motor/happyrobot/DOCS_CONFIRMADO.md`: el clúster.
Todo va a `platform.eu.…`; contra el de por defecto (`us`) la misma clave responde 401 o 404.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

BASE_EU = "https://platform.eu.happyrobot.ai/api/v2"
MCP_WORKFLOWS = "https://mcp.platform.eu.happyrobot.ai/workflows/mcp"
TIEMPO_ESPERA = 30


@dataclass
class RespuestaHR:
    codigo: int
    cuerpo: Any = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.codigo < 300

    @property
    def sin_credencial(self) -> bool:
        return self.codigo in (401, 403)

    def to_dict(self) -> dict[str, Any]:
        return {"codigo": self.codigo, "ok": self.ok, "error": self.error}


class ClienteHappyRobot:
    """Cliente mínimo y honesto: solo los caminos que el MVP necesita.

    La clave se lee del entorno y **nunca se imprime**, ni siquiera recortada.
    """

    def __init__(self, clave: str | None = None, base: str | None = None) -> None:
        # Mismas variables que `motor/server/comms_happyrobot.py`, para no tener dos convenciones:
        # `HR_API_BASE` y `HR_API_KEY`. La diferencia es que aquí `HR_API_BASE` tiene valor por
        # defecto, y es el de EU, que es el que hay que usar.
        self.base = (base or os.environ.get("HR_API_BASE") or BASE_EU).rstrip("/")
        self._clave = clave or os.environ.get("HR_API_KEY", "")

    # ------------------------------------------------------------------ transporte

    @property
    def tiene_clave(self) -> bool:
        return bool(self._clave)

    def _cabeceras(self) -> dict[str, str]:
        cab = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._clave:
            cab["Authorization"] = f"Bearer {self._clave}"
        return cab

    def _llamar(self, metodo: str, ruta: str, cuerpo: dict | None = None) -> RespuestaHR:
        url = ruta if ruta.startswith("http") else f"{self.base}{ruta}"
        datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
        req = urllib.request.Request(url, data=datos, headers=self._cabeceras(), method=metodo)
        try:
            with urllib.request.urlopen(req, timeout=TIEMPO_ESPERA) as r:
                bruto = r.read().decode("utf-8", "replace")
                try:
                    return RespuestaHR(r.status, json.loads(bruto))
                except json.JSONDecodeError:
                    return RespuestaHR(r.status, bruto)
        except urllib.error.HTTPError as e:
            bruto = e.read().decode("utf-8", "replace")
            try:
                return RespuestaHR(e.code, json.loads(bruto), error=bruto[:200])
            except json.JSONDecodeError:
                return RespuestaHR(e.code, bruto, error=bruto[:200])
        except Exception as e:
            return RespuestaHR(0, None, f"{type(e).__name__}: {e}")

    # ------------------------------------------------------------------ caminos del MVP

    def runs(self, limite: int = 10) -> RespuestaHR:
        """Las ejecuciones. Es la prueba de que una llamada existió: el criterio 1 del MVP."""
        return self._llamar("GET", f"/runs?limit={limite}")

    def sesiones(self, run_id: str) -> RespuestaHR:
        """`GET /runs/{id}/sessions` — de aquí sale el `session_id` que necesita Signals."""
        return self._llamar("GET", f"/runs/{run_id}/sessions")

    def publicar_signal(self, session_id: str, nombre: str, datos: dict | None = None) -> RespuestaHR:
        """Cambiar la orden en mitad de una llamada viva. El agente necesita tener activado
        *Start agent response on signal* o el aviso llega y no se dice en voz alta."""
        return self._llamar(
            "POST",
            "/signals",
            {"channel": f"session.{session_id}", "name": nombre, "data": datos or {}},
        )

    def workflows(self) -> RespuestaHR:
        return self._llamar("GET", "/workflows")

    # ------------------------------------------------------------------ diagnóstico

    def diagnostico(self) -> dict[str, Any]:
        """Sonda los caminos que importan y explica qué significa cada respuesta.

        Se puede ejecutar **sin clave**: en ese caso sirve para confirmar que la plataforma está
        viva y que la URL base es la buena, que no es poco a las dos de la mañana.
        """
        pruebas = [
            ("runs", "GET", "/runs?limit=1"),
            ("workflows", "GET", "/workflows"),
            ("mcp-workflows", "GET", MCP_WORKFLOWS),
        ]
        resultado: dict[str, Any] = {
            "base": self.base,
            "clave_presente": self.tiene_clave,
            "cluster": "eu" if ".eu." in self.base else "NO ES EU",
            "pruebas": [],
            "lectura": "",
        }
        if ".eu." not in self.base:
            resultado["aviso_cluster"] = (
                f"`HR_API_BASE` apunta a {self.base}, que no es el clúster EU. Es el fallo número uno "
                "documentado: con el clúster equivocado la misma clave responde 401 o 404."
            )
        alcanzable = False
        autorizado = False
        for nombre, metodo, ruta in pruebas:
            r = self._llamar(metodo, ruta)
            if r.codigo:
                alcanzable = True
            if r.ok:
                autorizado = True
            resultado["pruebas"].append(
                {"nombre": nombre, "ruta": ruta, "codigo": r.codigo, "ok": r.ok, "detalle": (r.error or "")[:120]}
            )

        if not alcanzable:
            resultado["lectura"] = (
                "No hay red hacia la plataforma. Antes de tocar nada, comprobar la wifi de la sede: "
                "es la causa más frecuente y la más rápida de descartar."
            )
        elif autorizado:
            resultado["lectura"] = "Clave válida: se puede leer la plataforma."
        elif not self.tiene_clave:
            resultado["lectura"] = (
                "La plataforma responde y la URL base es correcta, pero **no hay HR_API_KEY en el entorno**. "
                "Exportarla antes de usar nada de esto: `export HR_API_KEY=…` (nunca en el repositorio)."
            )
        else:
            resultado["lectura"] = (
                "Hay clave y la plataforma responde, pero la rechaza. Las dos causas de siempre: la clave es "
                "del clúster equivocado (esto apunta a `platform.eu.…`) o su rol no llega para leer."
            )
        return resultado


def sonda_sin_clave() -> dict[str, Any]:
    """Atajo para el `doctor`: diagnóstico con lo que haya en el entorno."""
    return ClienteHappyRobot().diagnostico()
