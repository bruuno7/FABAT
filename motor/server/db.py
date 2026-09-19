"""Fachada del historial: el esquema y el escritor viven en ``memoria_db``."""
from __future__ import annotations

from .memoria_db import (  # noqa: F401
    DEFAULT_PATH,
    SCHEMA_VERSION,
    History,
    Recorder,
    configured_path,
)
