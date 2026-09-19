"""Rutas nuevas de personal y coordinación. install no altera las rutas existentes."""
import asyncio
import io

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from . import multi
from .personal import ROLES, external_notice


def install(app, get_session, base_url):
    async def body(request):
        try:
            value = await request.json()
        except ValueError:
            raise HTTPException(400, 'JSON inválido')
        if not isinstance(value, dict):
            raise HTTPException(422, 'Se esperaba un objeto')
        return value

    @app.get('/personal', include_in_schema=False)
    def page():
        return HTMLResponse(
            '<!doctype html><meta charset="utf-8"><title>MANDO</title>'
            '<p>Pantalla archivada. <a href="/">Sala de control</a>.</p>',
            headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})

    @app.get('/api/personal/catalog')
    def catalog():
        s = get_session()
        return dict(units=[dict(id=r.id,name=r.name,kind=str(r.kind)) for r in s.world.resources.values()], roles=ROLES)

    @app.post('/api/personal/links')
    async def links(request: Request):
        who = multi.identity(request)
        d = await body(request)
        s = get_session()
        with s.lock:
            result = s.staff.links(d.get('unit_id'), d.get('role'), base_url())
            s.operators.event(who, 'genera enlace del personal', d.get('unit_id'))
            s._rebuild()
        return JSONResponse(result, headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})

    @app.post('/api/personal/qr')
    async def qr(request: Request):
        multi.identity(request)
        d = await body(request)
        s = get_session()
        import segno
        link = s.staff.links(d.get('unit_id'), d.get('role'), base_url())
        buf = io.BytesIO()
        segno.make(link['url'], error='m').save(buf, kind='svg', scale=5, border=2, xmldecl=False)
        return Response(buf.getvalue(), media_type='image/svg+xml', headers={'Cache-Control':'no-store'})

    @app.get('/api/personal/me')
    def me(request: Request):
        s = get_session()
        who = s.staff.verify(request.headers.get('x-mando-unit',''))
        return JSONResponse(s.staff.orders(who), headers={'Cache-Control':'no-store'})

    @app.post('/api/personal/status')
    async def status(request: Request):
        d = await body(request)
        s = get_session()
        return await asyncio.to_thread(s.staff.status, d, request.headers.get('x-mando-unit',''))

    @app.post('/api/personal/order/{aid}')
    async def answer(aid: str, request: Request):
        d = await body(request)
        s = get_session()
        who = s.staff.verify(request.headers.get('x-mando-unit',''))
        return s.staff.answer(who, aid, d.get('result'), d.get('reason',''))

    @app.get('/api/operators/me')
    def operator_me(request: Request):
        return dict(operator=multi.identity(request), local=multi.local_mode(request.scope), roles=multi.ROLES)

    @app.post('/api/operators/local')
    async def local(request: Request):
        if not multi.local_mode(request.scope):
            raise HTTPException(403, 'El selector de identidad solo está disponible en local sin tokens')
        d = await body(request)
        cookie = multi.local_cookie(d.get('name'), d.get('role'))
        response = JSONResponse({'ok':True})
        response.set_cookie(multi.LOCAL_COOKIE, cookie, httponly=True, samesite='strict', max_age=28800, path='/')
        return response

    @app.post('/api/operators/presence')
    async def presence(request: Request):
        who = multi.identity(request)
        d = await body(request)
        iid = d.get('incident')
        if iid is not None and not isinstance(iid, str):
            raise HTTPException(422, 'Incidente inválido')
        return get_session().operators.heartbeat(who, iid)

    @app.post('/api/incidents/{iid}/claim')
    async def claim(iid: str, request: Request):
        who = multi.identity(request)
        d = await body(request)
        if type(d.get('claim')) is not bool:
            raise HTTPException(422, 'claim debe ser booleano')
        return get_session().operators.claim(iid, who, d['claim'])

    @app.post('/api/incidents/{iid}/note')
    async def note(iid: str, request: Request):
        who = multi.identity(request)
        d = await body(request)
        return get_session().operators.note(iid, who, d.get('text'))

    @app.post('/api/external-notice')
    async def external(request: Request):
        who = multi.identity(request)
        d = await body(request)
        s = get_session()
        out = external_notice(s, dict(d, type='external_notice'))
        with s.lock:
            s.operators.event(who, 'registra aviso de servicios externos', out['report_id'])
            s._rebuild()
        return out
