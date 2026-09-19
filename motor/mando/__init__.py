"""Mando: el agente que coordina incidentes. API pública en README.md."""
from .mando import Mando
from .parser import CascadeParser, HeuristicParser, LLMParser, Parser
from .playbook import Playbook
from .report import report

__all__ = ["Mando", "Playbook", "Parser", "HeuristicParser", "LLMParser", "CascadeParser", "report"]
