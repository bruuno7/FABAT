"""Instala entradas de personal, servicios externos y espejo de Telegram en el mock local de HappyRobot."""
from fastapi import Request
import httpx


async def _post(app, data, event):
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(data['callback_url'], headers={'X-Mando-Token': data['callback_token']}, json=event)
    # El mock no guarda el secreto del enlace ni de callbacks.
    app.state.posted.append({k: v for k, v in event.items() if k != 'unit_token'})
    return dict(status=response.status_code, reply=response.json())


def install(app):
    @app.post('/mock/staff-status')
    @app.post('/mock/external-notice')
    async def staff_status(request: Request):
        data = await request.json()
        event = dict(data.get('event') or {})
        event['type'] = 'staff_status' if request.url.path.endswith('staff-status') else 'external_notice'
        return await _post(app, data, event)

    @app.post('/mock/tg-incident')
    @app.post('/mock/tg-assignment')
    @app.post('/mock/tg-approval')
    async def tg_event(request: Request):
        """Los tres tipos del espejo de Telegram, uno a uno: `{callback_url, callback_token, event}`.
        El `type` lo pone la ruta, para que una prueba no pueda equivocarse de tipo sin darse cuenta."""
        data = await request.json()
        event = dict(data.get('event') or {})
        event['type'] = 'tg_' + request.url.path.rsplit('/tg-', 1)[1].replace('-', '_')
        return await _post(app, data, event)

    @app.post('/mock/tg-secuencia')
    async def tg_secuencia(request: Request):
        """La secuencia entera del despacho, tal y como la mandaría HappyRobot: `{callback_url,
        callback_token, events:[...]}`. Sirve para probar el espejo sin plataforma ni bot."""
        data = await request.json()
        salidas = []
        for event in data.get('events') or []:
            salidas.append(await _post(app, data, dict(event)))
        return dict(ok=True, n=len(salidas), results=salidas)
