"""Agente 1 — **Context Analyzer**. Extrae del repositorio lo que los demás agentes necesitan saber.

Es completamente determinista: no llama a ningún modelo. Lee ficheros, los recorre con `ast` y
arma un `ContextPack`. Dos razones para que sea así, y las dos importan:

1. Un modelo que «resume el repositorio» inventa módulos que no existen. Un `ast.parse` no.
2. Es gratis y tarda menos de un segundo, así que se puede correr antes de cada encargo sin pensar
   en la cuota, que es el recurso escaso de este fin de semana.

La huella del `ContextPack` sale del contenido, no de la hora: el mismo repositorio da la misma
huella, y eso permite saber si un prompt se generó con el código de antes o el de después.
"""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

from .contratos import ContextPack, Modulo, Regla, Severidad
from .reglas import CATALOGO as REGLAS_PROYECTO

IGNORAR_DIR = {
    ".git", "__pycache__", ".venv", "node_modules", ".pytest_cache", ".ruff_cache",
    "out",           # motor/harness/out: 48 MB de artefactos y cuatro copias del repositorio
    "material",      # documentación con código de acceso: no se lee ni se resume
    ".cursor",
}
EXTENSIONES_TEXTO = {".py", ".md", ".json", ".txt", ".toml", ".sh", ".mjs", ".js", ".css", ".html"}

# Módulos que no son de la biblioteca estándar y delatan una dependencia externa.
NO_STDLIB = {
    "fastapi", "starlette", "uvicorn", "httpx", "requests", "pydantic", "numpy", "pandas",
    "anthropic", "openai", "scipy", "matplotlib", "yaml", "dotenv",
}


class AnalizadorDeContexto:
    """Recorre el repositorio y devuelve un `ContextPack`."""

    nombre = "context-analyzer"

    def __init__(self, raiz: str | Path) -> None:
        self.raiz = Path(raiz).resolve()
        if not self.raiz.is_dir():
            raise NotADirectoryError(f"no existe la raíz {self.raiz}")

    # ------------------------------------------------------------------ recorrido

    def _ficheros(self) -> list[Path]:
        salida: list[Path] = []
        for p in self.raiz.rglob("*"):
            if not p.is_file():
                continue
            if any(parte in IGNORAR_DIR for parte in p.relative_to(self.raiz).parts):
                continue
            if p.suffix in EXTENSIONES_TEXTO:
                salida.append(p)
        return sorted(salida)

    def _rel(self, p: Path) -> str:
        return p.relative_to(self.raiz).as_posix()

    @staticmethod
    def _leer(p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return ""

    # ------------------------------------------------------------------ módulos

    def _analizar_modulos(self, ficheros: list[Path], avisos: list[str]) -> list[Modulo]:
        """Un módulo es cualquier carpeta con `__init__.py`, más `agentes/` y la raíz."""
        paquetes: dict[str, Modulo] = {}
        for p in ficheros:
            if p.name != "__init__.py":
                continue
            ruta = self._rel(p.parent)
            paquetes[ruta] = Modulo(ruta=ruta)

        for p in ficheros:
            if p.suffix != ".py":
                continue
            rel = self._rel(p)
            duenno = max((r for r in paquetes if rel.startswith(r + "/")), key=len, default="")
            if not duenno:
                continue
            m = paquetes[duenno]
            texto = self._leer(p)
            m.ficheros += 1
            m.lineas += texto.count("\n") + 1
            if p.name.startswith("test_"):
                m.tests.append(rel)
            try:
                arbol = ast.parse(texto, filename=rel)
            except SyntaxError as e:
                avisos.append(f"{rel}: no se puede leer con ast ({e.msg} en la línea {e.lineno})")
                continue
            # Solo el nivel superior del fichero propio del paquete, no de los subpaquetes, y sin
            # los tests: en `motor/world` las clases `TestLoQueSea` se comían la lista y el
            # implementador acababa viendo los tests en vez de la API con la que tiene que trabajar.
            if p.parent == (self.raiz / duenno) and not p.name.startswith("test_"):
                for nodo in arbol.body:
                    if isinstance(nodo, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not nodo.name.startswith("_"):
                            m.publico.append(f"{p.stem}.{nodo.name}")
            for nodo in ast.walk(arbol):
                raiz_mod = ""
                if isinstance(nodo, ast.Import):
                    raiz_mod = nodo.names[0].name.split(".")[0]
                elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
                    raiz_mod = nodo.module.split(".")[0]
                if raiz_mod in NO_STDLIB and raiz_mod not in m.importa_externo:
                    m.importa_externo.append(raiz_mod)
                    m.solo_stdlib = False

        for m in paquetes.values():
            m.publico.sort()
            m.importa_externo.sort()
        return [paquetes[k] for k in sorted(paquetes)]

    # ------------------------------------------------------------------ dueños

    def _duenos(self, avisos: list[str]) -> dict[str, str]:
        """La tabla «Quién es dueño de qué» de `AGENTS.md`, leída de verdad, no supuesta."""
        agents = self.raiz / "AGENTS.md"
        if not agents.exists():
            avisos.append("no hay AGENTS.md: nadie es dueño de nada y eso se va a notar en un conflicto")
            return {}
        duenos: dict[str, str] = {}
        for linea in self._leer(agents).splitlines():
            if not linea.startswith("|") or linea.count("|") < 3:
                continue
            celdas = [c.strip() for c in linea.strip("|").split("|")]
            if len(celdas) < 2 or celdas[0].startswith("-") or celdas[0] in ("Carpeta", "Fichero"):
                continue
            persona = celdas[1]
            for ruta in re.findall(r"`([^`]+)`", celdas[0]):
                if "/" in ruta or ruta.endswith(".md"):
                    duenos[ruta.strip().rstrip("/")] = persona
        return duenos

    # ------------------------------------------------------------------ documentos, reglas, hitos

    def _documentos(self, ficheros: list[Path]) -> dict[str, str]:
        """Para cada documento de nivel superior, su primera línea con contenido. Es el índice que
        permite al arquitecto decidir qué leer sin cargarlo todo."""
        docs: dict[str, str] = {}
        for p in ficheros:
            rel = self._rel(p)
            if p.suffix != ".md" or rel.count("/") > 1:
                continue
            for linea in self._leer(p).splitlines():
                limpia = linea.strip().lstrip("#").strip()
                if limpia:
                    docs[rel] = limpia[:160]
                    break
        return docs

    def _hitos(self) -> list[str]:
        """Las guillotinas con hora, de MVP.md. Un agente que no sabe qué hora es propone
        refactorizaciones de tres horas a las dos de la mañana."""
        mvp = self.raiz / "MVP.md"
        if not mvp.exists():
            return []
        hitos: list[str] = []
        for linea in self._leer(mvp).splitlines():
            m = re.match(r"\|\s*\*\*(F\d[^|*]*)\*\*\s*\|\s*([^|]+)\|\s*([^|]+)\|", linea)
            if m:
                hitos.append(f"{m.group(1).strip()} · {m.group(2).strip()} · {m.group(3).strip()}")
        return hitos

    def _reglas(self, avisos: list[str]) -> list[Regla]:
        """Las del catálogo, más las que estén escritas en las reglas de Cursor.

        Se mira también en la carpeta padre: en esta máquina el repositorio vive dentro del espacio
        de trabajo, y `.cursor/rules` está un nivel por encima.
        """
        reglas = list(REGLAS_PROYECTO)
        carpeta = next(
            (c for c in (self.raiz / ".cursor" / "rules", self.raiz.parent / ".cursor" / "rules") if c.is_dir()),
            None,
        )
        if carpeta is None:
            avisos.append("no hay .cursor/rules ni aquí ni en la carpeta padre: el catálogo va solo con las reglas del código")
            return reglas
        for p in sorted(carpeta.glob("*.mdc")):
            texto = self._leer(p)
            for linea in texto.splitlines():
                if linea.strip().startswith("description:"):
                    reglas.append(
                        Regla(
                            clave=f"cursor:{p.stem}",
                            texto=linea.split(":", 1)[1].strip(),
                            fuente=f".cursor/rules/{p.name}",
                            severidad=Severidad.AVISO,
                        )
                    )
                    break
        return reglas

    def _convenciones(self, modulos: list[Modulo]) -> list[str]:
        conv = [
            "Todo se ejecuta desde la raíz del repositorio.",
            "Español en los comentarios y la documentación; inglés en los identificadores del motor.",
            "Dataclasses con `to_dict()`, y `from __future__ import annotations` en cada fichero.",
        ]
        nucleo = [m for m in modulos if m.ruta.startswith("motor/") and m.ruta != "motor/server"]
        if nucleo and all(m.solo_stdlib for m in nucleo):
            conv.append("El núcleo usa **solo biblioteca estándar**: comprobado, ningún import externo.")
        externos = sorted({d for m in modulos for d in m.importa_externo})
        if externos:
            conv.append(f"Dependencias externas, solo en el servidor: {', '.join(externos)}.")
        con_tests = [m for m in modulos if m.tests]
        if con_tests:
            conv.append(
                "Cada módulo lleva su `test_*.py`: "
                + ", ".join(f"{m.ruta} ({len(m.tests)})" for m in con_tests)
                + "."
            )
        return conv

    # ------------------------------------------------------------------ entrada principal

    def analizar(self) -> ContextPack:
        avisos: list[str] = []
        ficheros = self._ficheros()
        modulos = self._analizar_modulos(ficheros, avisos)
        duenos = self._duenos(avisos)

        for m in modulos:
            m.dueno = duenos.get(m.ruta, duenos.get(m.ruta.split("/")[0], m.dueno))

        # La huella sale del contenido, nunca del reloj: así dos análisis del mismo código coinciden.
        h = hashlib.sha256()
        for p in ficheros:
            h.update(self._rel(p).encode("utf-8"))
            h.update(str(p.stat().st_size).encode("utf-8"))

        return ContextPack(
            raiz=str(self.raiz),
            generado_con=h.hexdigest()[:12],
            modulos=modulos,
            reglas=self._reglas(avisos),
            duenos=duenos,
            convenciones=self._convenciones(modulos),
            hitos=self._hitos(),
            documentos=self._documentos(ficheros),
            avisos=avisos,
        )


def analizar(raiz: str | Path = ".") -> ContextPack:
    return AnalizadorDeContexto(raiz).analizar()
