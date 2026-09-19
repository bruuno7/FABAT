"""Rutas de solo lectura del historial persistente."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response

from .db import History
from .security import require_operator


def install(app: FastAPI, history: History, static: Path,
            operator: Callable[[Request], None] = require_operator) -> None:
    def ready(request: Request) -> History:
        operator(request)
        if not history.enabled:
            raise HTTPException(503, "Historial desactivado con MANDO_DB=off")
        return history

    def unavailable(exc: BaseException) -> HTTPException:
        return HTTPException(503, f"Historial no disponible: {type(exc).__name__}")

    @app.get("/historial", include_in_schema=False)
    def historial_page(request: Request) -> FileResponse:
        ready(request)
        return FileResponse(static / "historial.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/historial/escenas")
    def scenes(request: Request) -> dict:
        try:
            return {"items": ready(request).scenes()}
        except (sqlite3.Error, RuntimeError) as exc:
            raise unavailable(exc)

    @app.get("/api/historial/incidentes")
    def incidents(request: Request, escena: str | None = None, estado: str | None = None,
                  familia: str | None = None, zona: str | None = None,
                  desde: int | None = None, hasta: int | None = None, q: str | None = None,
                  pagina: int = 1, tamano: int = 50) -> dict:
        try:
            return ready(request).incidents(scene=escena, status=estado, family=familia, zone=zona,
                                            since=desde, until=hasta, q=q, page=pagina, size=tamano)
        except (sqlite3.Error, RuntimeError, ValueError) as exc:
            raise unavailable(exc)

    @app.get("/api/historial/incidente/{incident_id}")
    def incident(incident_id: str, request: Request, escena: str | None = None) -> dict:
        try:
            return ready(request).incident(escena, incident_id)
        except KeyError:
            raise HTTPException(404, "Incidente no encontrado")
        except (sqlite3.Error, RuntimeError) as exc:
            raise unavailable(exc)

    @app.get("/api/historial/decisiones")
    def decisions(request: Request, escena: str | None = None) -> dict:
        try:
            return {"items": ready(request).decisions(escena)}
        except (sqlite3.Error, RuntimeError) as exc:
            raise unavailable(exc)

    @app.get("/api/historial/recursos")
    def resources(request: Request, escena: str | None = None) -> dict:
        try:
            return {"items": ready(request).resources(escena)}
        except (sqlite3.Error, RuntimeError) as exc:
            raise unavailable(exc)

    @app.get("/api/historial/servicios")
    def services(request: Request, escena: str | None = None) -> dict:
        try:
            return {"items": ready(request).services(escena)}
        except (sqlite3.Error, RuntimeError) as exc:
            raise unavailable(exc)

    @app.get("/api/historial/resumen")
    def summary(request: Request, escena: str | None = None) -> dict:
        try:
            return ready(request).summary(escena)
        except (sqlite3.Error, RuntimeError) as exc:
            raise unavailable(exc)

    @app.get("/api/historial/export.json")
    def export_json(request: Request, escena: str) -> Response:
        try:
            content = ready(request).export_json(escena)
        except KeyError:
            raise HTTPException(404, "Escena no encontrada")
        except (sqlite3.Error, RuntimeError) as exc:
            raise unavailable(exc)
        return Response(content, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="mando-{escena}.json"'})

    @app.get("/api/historial/export.csv")
    def export_csv(request: Request, escena: str) -> Response:
        try:
            content = ready(request).export_csv(escena)
        except KeyError:
            raise HTTPException(404, "Escena no encontrada")
        except (sqlite3.Error, RuntimeError) as exc:
            raise unavailable(exc)
        return Response(content, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="mando-{escena}.csv"'})
