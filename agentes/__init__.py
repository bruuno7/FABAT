"""Sistema multiagente de FABAT: analizador de contexto, arquitecto de prompts, implementador y
revisor de código.

Solo biblioteca estándar. Se ejecuta desde la raíz del repositorio, como todo lo demás:

    python -m agentes doctor
    python -m agentes analizar
    python -m agentes pipeline --objetivo "…" --ficheros a.py,b.py --prueba "python -m unittest …"
"""
from __future__ import annotations

from .analizador import AnalizadorDeContexto, analizar
from .arquitecto import ArquitectoDePrompts
from .contratos import (
    Accion,
    Aviso,
    ContextPack,
    Encargo,
    Parche,
    PromptSpec,
    Revision,
    Severidad,
    Veredicto,
)
from .happyrobot import ClienteHappyRobot
from .implementador import Implementador
from .orquestador import Orquestador, Resultado, ejecutar
from .revisor import RevisorDeCodigo, revisar_parche, revisar_ruta

__all__ = [
    "Accion",
    "AnalizadorDeContexto",
    "ArquitectoDePrompts",
    "Aviso",
    "ClienteHappyRobot",
    "ContextPack",
    "Encargo",
    "Implementador",
    "Orquestador",
    "Parche",
    "PromptSpec",
    "Resultado",
    "RevisorDeCodigo",
    "Revision",
    "Severidad",
    "Veredicto",
    "analizar",
    "ejecutar",
    "revisar_parche",
    "revisar_ruta",
]
