"""ASGI operator authentication and bounded public intake, without buffering SSE.

Install with ``app.add_middleware(SecurityGuard)`` and use ``require_operator``
for conditional operator actions. Tokens never belong in URLs or browser storage.
"""
from collections import OrderedDict
import hashlib
import hmac
from http.cookies import CookieError, SimpleCookie
import json
import math
import os
import posixpath
import time
from urllib.parse import urlsplit

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

COOKIE_NAME = 'mando_operator'
COOKIE_TTL = 8 * 60 * 60
BODY_MAX = 8192
MAX_CLIENTS = 4096


def _public():
    return bool(os.environ.get('MANDO_PUBLIC_URL', '').strip())


def _signature(value, token):
    return hmac.new(token.encode(), ('mando-operator-cookie-v1:' + value).encode(), hashlib.sha256).hexdigest()


def _auth_status(scope):
    request = Request(scope)
    if not _public() and request.client and request.client.host in ('127.0.0.1', '::1', 'localhost', 'testclient'):
        return 0
    token = os.environ.get('MANDO_OPERATOR_TOKEN', '')
    if not token:
        return 503 if _public() else 403
    header = request.headers.get('x-mando-operator')
    if header is not None:
        return 0 if hmac.compare_digest(header.encode(), token.encode()) else 403
    try:
        cookies = SimpleCookie(request.headers.get('cookie', ''))
        cookie = cookies.get(COOKIE_NAME)
        if cookie is None:
            return 401
        issued, signature = cookie.value.split('.', 1)
        age = time.time() - int(issued)
        if 0 <= age < COOKIE_TTL and hmac.compare_digest(signature, _signature(issued, token)):
            return 0
    except (CookieError, ValueError, TypeError):
        pass
    return 403


def verify_operator(scope):
    """Whether this ASGI connection has operator authority (never query/forwarded headers)."""
    return _auth_status(scope) == 0


def operator_authenticated(request):
    return verify_operator(request.scope)


def require_operator(request):
    """Raise 401 missing credential, 403 bad credential, or 503 unconfigured token."""
    status = _auth_status(request.scope)
    if status:
        raise HTTPException(status, 'Acceso de operador requerido' if status != 503 else 'Token de operador sin configurar')


LOGIN_HTML = '''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Acceso de operador</title><main><h1>Acceso de operador</h1>
<form id="login"><label>Token de operador <input id="token" type="password" autocomplete="current-password" required></label>
<button>Entrar</button></form><p id="status" role="status"></p></main><script>
document.getElementById('login').addEventListener('submit',async e=>{e.preventDefault();
const input=document.getElementById('token');const token=input.value;input.value='';
try {const r=await fetch('/api/operator/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});
if(r.ok) location.replace('/');else document.getElementById('status').textContent='No se ha autorizado el acceso.';}
catch {document.getElementById('status').textContent='No se ha podido conectar.';}});
</script></html>'''


def _positive_env(name, default):
    try:
        value = int(os.environ.get(name, str(default)))
        return value if value > 0 else default
    except ValueError:
        return default


class SecurityGuard:
    """Per-process IP rate budget; only intake bodies are buffered (at most 8 KiB).

    MANDO_PUBLIC_RATE_MAX defaults to 30 mutations/window; page GETs get twice
    that budget. MANDO_PUBLIC_RATE_WINDOW_S defaults to 60 seconds. At capacity,
    new clients are refused until an existing window expires, avoiding eviction
    as a way to reset an attacker's budget. Forwarded headers are never trusted.
    """
    def __init__(self, app):
        self.app = app
        self.rate_max = _positive_env('MANDO_PUBLIC_RATE_MAX', 30)
        self.window = _positive_env('MANDO_PUBLIC_RATE_WINDOW_S', 60)
        self.clients = OrderedDict()

    def _rate(self, scope, page):
        now = time.monotonic()
        while self.clients and next(iter(self.clients.values()))[0] + self.window <= now:
            self.clients.popitem(last=False)
        ip = (scope.get('client') or ('unknown', 0))[0]
        key = (ip, page)
        if key not in self.clients:
            if len(self.clients) >= MAX_CLIENTS:
                return self.window
            self.clients[key] = [now, 0]
        entry = self.clients[key]
        maximum = self.rate_max * (2 if page else 1)
        if entry[1] >= maximum:
            return max(1, math.ceil(entry[0] + self.window - now))
        entry[1] += 1
        return 0

    @staticmethod
    async def _deny(scope, receive, send, status, message, headers=None):
        await JSONResponse({'ok': False, 'error': message}, status_code=status,
                           headers={'Cache-Control': 'no-store', **(headers or {})})(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path = '/' + posixpath.normpath(scope.get('path', '/')).lstrip('/')
        method = scope.get('method', 'GET')
        mutation = method not in ('GET', 'HEAD', 'OPTIONS')
        login = path == '/api/operator/login' and method == 'POST'
        public_intake = path in ('/api/chat', '/api/report', '/api/strike') or (
            path.startswith('/api/report/') and path.endswith('/answer'))
        headers = Request(scope).headers
        chat_token = os.environ.get('HR_CHAT_TOKEN', '')
        if path == '/hr/events' and chat_token and hmac.compare_digest(
                (headers.get('x-mando-token') or headers.get('x-hr-secret') or '').encode(), chat_token.encode()):
            public_intake = True
        # Webcall IDs are existing capability links; they retain their own access policy.
        public_call = path.startswith('/api/webcall/') and path.endswith(('/answer', '/mock_answer'))
        operator_action = mutation and path.startswith('/api/') and not (public_intake or public_call or login)
        operator_page = _public() and path in ('/', '/static/index.html')
        if operator_action or operator_page:
            status = _auth_status(scope)
            if status:
                if operator_page:
                    return await HTMLResponse(LOGIN_HTML, status_code=status, headers={'Cache-Control': 'no-store'})(scope, receive, send)
                return await self._deny(scope, receive, send, status, 'Acceso de operador requerido; entra en /acceso')
        page = path in ('/asistente', '/static/asistente.html', '/acceso') and method in ('GET', 'HEAD')
        if page or (mutation and public_intake) or login:
            retry = self._rate(scope, page)
            if retry:
                return await self._deny(scope, receive, send, 429, 'Demasiadas peticiones', {'Retry-After': str(retry)})
        if path == '/acceso' and method in ('GET', 'HEAD'):
            return await HTMLResponse(LOGIN_HTML, headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})(scope, receive, send)
        if not ((mutation and public_intake) or login):
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            if message['type'] != 'http.request':
                continue
            part = message.get('body', b'')
            if len(body) + len(part) > BODY_MAX:
                return await self._deny(scope, receive, send, 413, 'Cuerpo demasiado grande')
            body.extend(part)
            if not message.get('more_body', False):
                break
        try:
            data = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            data = None
        if isinstance(data, dict) and len(str(data.get('text') or '')) > 400:
            return await self._deny(scope, receive, send, 413, 'Texto demasiado largo (máximo 400 caracteres)')
        if login:
            return await self._login(scope, receive, send, data)
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()

        await self.app(scope, replay, send)

    async def _login(self, scope, receive, send, data):
        request = Request(scope)
        origin = request.headers.get('origin')
        if origin:
            actual = urlsplit(origin)
            allowed = urlsplit(os.environ.get('MANDO_PUBLIC_URL') or str(request.base_url))
            if (actual.scheme, actual.netloc) != (allowed.scheme, allowed.netloc):
                return await self._deny(scope, receive, send, 403, 'Origen no autorizado')
        expected = os.environ.get('MANDO_OPERATOR_TOKEN', '')
        if not expected:
            return await self._deny(scope, receive, send, 503, 'Token de operador sin configurar')
        got = data.get('token') if isinstance(data, dict) else None
        if not isinstance(got, str) or not hmac.compare_digest(got.encode(), expected.encode()):
            return await self._deny(scope, receive, send, 403, 'Token incorrecto')
        issued = str(int(time.time()))
        response = JSONResponse({'ok': True}, headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})
        secure = scope.get('scheme') == 'https' or os.environ.get('MANDO_PUBLIC_URL', '').startswith('https://')
        response.set_cookie(COOKIE_NAME, issued + '.' + _signature(issued, expected), max_age=COOKIE_TTL,
                            httponly=True, secure=secure, samesite='strict', path='/')
        await response(scope, receive, send)
