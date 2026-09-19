"""Rutas de lectura y simulacro: montar después de registrar las rutas principales."""
from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from .security import require_operator
from .evidence_runtime import evidence
from .simulacro import SimulacroService


def register(app, session, static):
    service = SimulacroService()
    app.state.simulacro = service

    @app.get('/simulacro', include_in_schema=False)
    def page():
        return FileResponse(static / 'simulacro.html', headers={'Cache-Control': 'no-store'})

    @app.get('/api/evidence')
    def read_evidence(call_minutes: float = 3, message_minutes: float = 1, report_minutes: float = 1):
        try:
            return evidence(session(), call_minutes=call_minutes, message_minutes=message_minutes, report_minutes=report_minutes)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post('/api/simulacro/start')
    async def start(request: Request):
        require_operator(request)
        try:
            data = await request.json()
        except ValueError as exc:
            raise HTTPException(400, 'JSON inválido') from exc
        if not isinstance(data, dict):
            raise HTTPException(422, 'Se esperaba un objeto JSON')
        try:
            return service.start(session(), n=data.get('n', 200), seed=data.get('seed', 1))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post('/api/simulacro/cancel')
    def cancel(request: Request):
        require_operator(request)
        return service.cancel()

    @app.get('/api/simulacro/status')
    def status():
        return service.status()
