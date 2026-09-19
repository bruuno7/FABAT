"""Audita las demás acciones HTTP del puesto sin guardar cuerpos ni credenciales."""
from .multi import identity
from starlette.exceptions import HTTPException
from starlette.requests import Request

# Estas acciones ya tienen eventos semánticos más detallados en Operators.
DETAILED = ('/api/approve', '/api/whatif/order', '/api/operators/', '/api/incidents/', '/api/personal/', '/api/external-notice')
PUBLIC = ('/api/operator/login', '/api/report', '/api/chat', '/api/webcall/')


class OperatorAudit:
    def __init__(self, app, get_session):
        self.app, self.get_session = app, get_session

    async def __call__(self, scope, receive, send):
        path = scope.get('path','')
        if (scope['type'] != 'http' or scope.get('method') in ('GET','HEAD','OPTIONS')
                or not path.startswith('/api/') or path.startswith(DETAILED + PUBLIC)):
            return await self.app(scope, receive, send)
        try:
            who = identity(Request(scope))
        except HTTPException:
            who = None
        status = 500
        async def capture(message):
            nonlocal status
            if message['type']=='http.response.start':
                status = message['status']
            await send(message)
        await self.app(scope, receive, capture)
        if who and 200 <= status < 300:
            s = self.get_session()
            with s.lock:
                s.operators.event(who, 'acción del puesto: ' + path)
                s._rebuild()
