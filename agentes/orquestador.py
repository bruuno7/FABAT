"""El orquestador: encadena los cuatro agentes y deja una traza que se puede enseñar.

El encadenado es **fijo**, no decidido por un modelo: analizar → construir prompt → implementar →
revisar. Es la misma decisión que en el motor: los nodos de conversación llevan modelo, los nodos
de decisión no. Un orquestador con modelo dentro es más vistoso y menos auditable, y aquí lo que
se puntúa es poder explicar por qué pasó cada cosa.

Escribir en disco es un paso aparte y **nunca automático**: solo ocurre si el veredicto lo permite
y si quien llama lo pide. Un veredicto de `PIDE_APROBACION` no se aplica solo, igual que una
evacuación no se ejecuta sola.
"""
from __future__ import annotations

import time
from pathlib import Path

from .analizador import AnalizadorDeContexto
from .arquitecto import ArquitectoDePrompts
from .contratos import (
    ContextPack,
    Encargo,
    Parche,
    PromptSpec,
    Proveedor,
    Revision,
    Traza,
    Veredicto,
)
from .implementador import Implementador
from .proveedores import ProveedorSeco
from .revisor import RevisorDeCodigo


class Resultado:
    """Lo que devuelve una pasada completa."""

    def __init__(
        self,
        contexto: ContextPack,
        prompt: PromptSpec,
        parche: Parche,
        revision: Revision,
        traza: Traza,
    ) -> None:
        self.contexto = contexto
        self.prompt = prompt
        self.parche = parche
        self.revision = revision
        self.traza = traza

    @property
    def aplicable(self) -> bool:
        return self.revision.veredicto in (Veredicto.ACEPTA, Veredicto.ACEPTA_CON_AVISOS)

    def to_dict(self) -> dict:
        return {
            "contexto": {
                "huella": self.contexto.generado_con,
                "modulos": len(self.contexto.modulos),
                "reglas": len(self.contexto.reglas),
            },
            "prompt": self.prompt.to_dict(),
            "parche": self.parche.to_dict(),
            "revision": self.revision.to_dict(),
            "traza": self.traza.to_dict(),
        }


class Orquestador:
    def __init__(self, raiz: str | Path = ".", proveedor: Proveedor | None = None) -> None:
        self.raiz = Path(raiz).resolve()
        self.proveedor = proveedor or ProveedorSeco()
        self._contexto: ContextPack | None = None

    def contexto(self, refrescar: bool = False) -> ContextPack:
        if self._contexto is None or refrescar:
            self._contexto = AnalizadorDeContexto(self.raiz).analizar()
        return self._contexto

    # ------------------------------------------------------------------ pasada completa

    def ejecutar(self, encargo: Encargo) -> Resultado:
        traza = Traza(encargo=f"{encargo.huella()} · {encargo.objetivo[:80]}")

        t0 = time.monotonic()
        contexto = self.contexto()
        traza.anotar(
            "context-analyzer",
            str(self.raiz),
            f"{len(contexto.modulos)} módulos, {len(contexto.reglas)} reglas, huella {contexto.generado_con}",
            int((time.monotonic() - t0) * 1000),
            contexto.avisos,
        )

        t0 = time.monotonic()
        prompt = ArquitectoDePrompts(contexto).construir(encargo)
        traza.anotar(
            "prompt-architect",
            f"acción {encargo.accion}, {len(encargo.ficheros_permitidos)} ficheros en la valla",
            f"{prompt.caracteres} caracteres, bloques: {', '.join(prompt.piezas)}",
            int((time.monotonic() - t0) * 1000),
            [f"recortado por presupuesto: {b}" for b in prompt.recortado],
        )

        t0 = time.monotonic()
        parche = Implementador(self.proveedor).implementar(prompt, encargo)
        traza.anotar(
            "implementer",
            f"proveedor {self.proveedor.nombre}",
            f"{len(parche.ficheros)} fichero(s), {parche.lineas()} líneas · {parche.resumen[:120]}",
            int((time.monotonic() - t0) * 1000),
        )

        t0 = time.monotonic()
        revision = RevisorDeCodigo(encargo).revisar_parche(parche)
        traza.anotar(
            "code-reviewer",
            f"{len(parche.ficheros)} fichero(s)",
            f"{revision.veredicto} · {len(revision.avisos)} aviso(s)",
            int((time.monotonic() - t0) * 1000),
            [str(a) for a in revision.avisos],
        )
        traza.veredicto = revision.veredicto

        return Resultado(contexto, prompt, parche, revision, traza)

    # ------------------------------------------------------------------ escritura

    def aplicar(self, resultado: Resultado, forzar: bool = False) -> list[str]:
        """Escribe los ficheros propuestos. Devuelve las rutas escritas.

        No escribe nada si el veredicto no lo permite, salvo que alguien pase `forzar=True`, que es
        la forma de dejar constancia de que **una persona** ha decidido saltarse el revisor.
        """
        if not resultado.aplicable and not forzar:
            return []
        escritos: list[str] = []
        for f in resultado.parche.ficheros:
            destino = (self.raiz / f.ruta).resolve()
            if not str(destino).startswith(str(self.raiz)):
                continue  # ruta que se sale del repositorio: no se escribe ni forzando
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(f.contenido, encoding="utf-8")
            escritos.append(f.ruta)
        return escritos


def ejecutar(encargo: Encargo, raiz: str | Path = ".", proveedor: Proveedor | None = None) -> Resultado:
    return Orquestador(raiz, proveedor).ejecutar(encargo)
