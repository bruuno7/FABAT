"""Agente 3 — **Implementer**. Pide el código al proveedor y convierte la respuesta en un `Parche`.

Es el único agente que necesita un modelo, y por eso es el único que puede gastar. No construye su
cliente: se le inyecta uno, igual que en `motor/`. Con el proveedor seco (el de por defecto) no
llama a nadie y devuelve el **encargo listo para pegar** en una sesión de Claude Code, que es el
flujo real del equipo: una suscripción, una operadora y encargos escritos.

Lo que no hace, a propósito: **no escribe en disco**. Devuelve ficheros propuestos y se los pasa al
revisor. Escribir es una decisión aparte, del orquestador, y solo después de un veredicto.
"""
from __future__ import annotations

import re

from .contratos import (
    Encargo,
    FicheroPropuesto,
    ModoProveedor,
    Parche,
    PromptSpec,
    Proveedor,
)

# ```fichero:ruta/al/fichero.py …contenido… ```
BLOQUE = re.compile(
    r"^```(?:fichero|file)[:=]\s*(?P<ruta>[^\s`\n]+)[^\n]*\n(?P<cuerpo>.*?)^```",
    re.MULTILINE | re.DOTALL,
)
# Respaldo: un bloque de código normal precedido por una ruta en la línea anterior.
BLOQUE_SUELTO = re.compile(
    r"^[^\n`]*?`(?P<ruta>[\w./\-]+\.(?:py|md|json|toml|txt|sh))`[^\n]*\n+```[\w]*\n(?P<cuerpo>.*?)^```",
    re.MULTILINE | re.DOTALL,
)


class Implementador:
    nombre = "implementer"

    def __init__(self, proveedor: Proveedor, max_tokens: int = 8000) -> None:
        self.proveedor = proveedor
        self.max_tokens = max_tokens

    def implementar(self, prompt: PromptSpec, encargo: Encargo) -> Parche:
        respuesta = self.proveedor.completar(prompt.sistema, prompt.usuario, self.max_tokens)

        if not respuesta.ok:
            return Parche(
                resumen=f"el proveedor «{self.proveedor.nombre}» no respondió: {respuesta.error}",
                proveedor=self.proveedor.modo,
                encargo_para_humano=_encargo_pegable(prompt, encargo, motivo=respuesta.error),
                crudo="",
            )

        if self.proveedor.modo is ModoProveedor.SECO:
            return Parche(
                resumen=(
                    "modo seco: no se ha llamado a ningún modelo. El encargo queda listo para "
                    "pegarlo en una sesión de Claude Code."
                ),
                proveedor=ModoProveedor.SECO,
                modelo="(ninguno)",
                encargo_para_humano=respuesta.texto,
                crudo=respuesta.texto,
            )

        ficheros = extraer_ficheros(respuesta.texto)
        permitidos = {f.replace("\\", "/") for f in encargo.ficheros_permitidos}
        resumen = _resumir(respuesta.texto, ficheros)
        if not ficheros:
            resumen = "el modelo respondió pero no devolvió ningún bloque `fichero:`. " + resumen

        for f in ficheros:
            f.modo = "reemplazar" if f.ruta in permitidos else "crear"

        return Parche(
            ficheros=ficheros,
            resumen=resumen,
            proveedor=respuesta.proveedor,
            modelo=respuesta.modelo,
            crudo=respuesta.texto,
        )


def extraer_ficheros(texto: str) -> list[FicheroPropuesto]:
    """Saca los bloques de fichero de la respuesta. Tolerante con el formato, estricto con la ruta."""
    encontrados: dict[str, str] = {}
    for patron in (BLOQUE, BLOQUE_SUELTO):
        for m in patron.finditer(texto):
            ruta = m.group("ruta").strip().strip("`").replace("\\", "/")
            cuerpo = m.group("cuerpo")
            if ruta and ruta not in encontrados:
                encontrados[ruta] = cuerpo
    return [FicheroPropuesto(ruta=r, contenido=c) for r, c in encontrados.items()]


def _resumir(texto: str, ficheros: list[FicheroPropuesto]) -> str:
    """La primera frase de prosa que haya fuera de los bloques de código."""
    sin_codigo = re.sub(r"^```.*?^```", "", texto, flags=re.MULTILINE | re.DOTALL).strip()
    primera = next((l.strip() for l in sin_codigo.splitlines() if len(l.strip()) > 30), "")
    cuantos = f"{len(ficheros)} fichero(s)" if ficheros else "sin ficheros"
    return f"{cuantos}. {primera[:300]}" if primera else cuantos


def _encargo_pegable(prompt: PromptSpec, encargo: Encargo, motivo: str = "") -> str:
    cabecera = [
        f"# Encargo {encargo.huella()} — para pegar a mano",
        "",
    ]
    if motivo:
        cabecera += [
            f"> No se pudo usar el proveedor automático: {motivo}",
            "> El encargo sigue siendo válido: se pega tal cual en una sesión de Claude Code.",
            "",
        ]
    cabecera += [
        "## Bloque de SISTEMA",
        "",
        prompt.sistema,
        "",
        "## Bloque de ENCARGO",
        "",
        prompt.usuario,
    ]
    return "\n".join(cabecera)
