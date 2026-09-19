"""Taxonomía de crisis y generador combinatorio de casos del «Festival Abierto».

API pública:
    from motor.cases import generate, iter_cases, validate_case, TAXONOMY
"""
from .generator import generate, iter_cases, space_size  # noqa: F401
from .taxonomy import TAXONOMY  # noqa: F401
from .validate import validate_case, validate_file  # noqa: F401
