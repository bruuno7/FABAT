"""Security boundaries exercised without sockets, external APIs or real credentials."""
import asyncio
import json
import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from motor.server.security import SecurityGuard, require_operator

TOKEN = 'only-a-test-operator-token'


def make_app():
    app = FastAPI()

    @app.api_route('/{path:path}', methods=['GET', 'HEAD', 'POST', 'PUT', 'DELETE'])
    async def endpoint(request: Request, path: str):
        if path == 'conditional':
            require_operator(request)
        if path == 'api/stream':
            async def events():
                yield 'data: first\n\n'
                yield 'data: second\n\n'
            return StreamingResponse(events(), media_type='text/event-stream')
        raw = await request.body()
        return {'ok': True, 'body': raw.decode()}

    app.add_middleware(SecurityGuard)
    return app


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'MANDO_PUBLIC_URL': 'https://example.invalid',
            'MANDO_OPERATOR_TOKEN': TOKEN, 'MANDO_MCP_TOKEN': 'test-mcp-token',
            'MANDO_PUBLIC_RATE_MAX': '30', 'MANDO_PUBLIC_RATE_WINDOW_S': '60'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.app = make_app()
        self.client = TestClient(self.app, client=('127.0.0.1', 1234), base_url='https://example.invalid')

    def test_public_loopback_has_no_operator_bypass(self):
        for path in ('/', '/static/sala.html', '/api/approve', '/api/control', '/api/whatif/order',
                     '/api/session', '/api/memoria/decide', '/api/regression/run', '/api/duel/control'):
            with self.subTest(path=path):
                response = self.client.request('GET' if path in ('/', '/static/sala.html') else 'POST', path)
                self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.get('/?token=' + TOKEN).status_code, 401)
        self.assertEqual(self.client.get('/', headers={'X-Mando-Operator': 'wrong'}).status_code, 403)
        self.assertEqual(self.client.get('/', headers={'X-Mando-Operator': TOKEN}).status_code, 200)

    def test_unconfigured_operator_fails_closed(self):
        os.environ['MANDO_OPERATOR_TOKEN'] = ''
        self.assertEqual(self.client.get('/').status_code, 503)
        self.assertEqual(self.client.post('/api/operator/login', json={'token': TOKEN}).status_code, 503)

    def test_local_bypass_disappears_in_public_mode(self):
        os.environ['MANDO_PUBLIC_URL'] = ''
        self.assertEqual(self.client.post('/api/control').status_code, 200)
        other = TestClient(self.app, client=('192.0.2.1', 80))
        self.assertEqual(other.post('/api/control').status_code, 401)
        self.assertEqual(other.get('/conditional', headers={'X-Mando-Operator': TOKEN}).status_code, 200)

    def test_login_cookie_is_signed_expiring_and_not_the_secret(self):
        self.assertEqual(self.client.get('/acceso').status_code, 200)
        response = self.client.post('/api/operator/login', json={'token': TOKEN})
        self.assertEqual(response.status_code, 200)
        cookie = response.headers['set-cookie']
        self.assertNotIn(TOKEN, cookie)
        for flag in ('HttpOnly', 'SameSite=strict', 'Secure', 'Max-Age=28800'):
            self.assertIn(flag, cookie)
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.post('/api/approve').status_code, 200)
        self.assertEqual(self.client.get('/conditional').status_code, 200)
        signed_cookie = cookie.split(';', 1)[0]
        with patch('motor.server.security.time.time', return_value=9999999999):
            self.assertEqual(self.client.get('/', headers={'Cookie': signed_cookie}).status_code, 403)
        os.environ['MANDO_OPERATOR_TOKEN'] = 'rotated-test-token'
        self.assertEqual(self.client.get('/', headers={'Cookie': signed_cookie}).status_code, 403)

    def test_cookie_tampering_and_cross_origin_login_are_rejected(self):
        self.client.cookies.set('mando_operator', '1.invalid')
        self.assertEqual(self.client.get('/').status_code, 403)
        self.assertEqual(self.client.post('/api/operator/login', json={'token': 'wrong'}).status_code, 403)
        self.assertEqual(self.client.post('/api/operator/login', json={'token': TOKEN},
            headers={'Origin': 'https://other.invalid'}).status_code, 403)

    def test_mcp_always_needs_its_token_even_locally(self):
        from motor.server.mcp_server import TokenGuard
        self.client = TestClient(TokenGuard(make_app()), client=('127.0.0.1', 1))
        os.environ['MANDO_PUBLIC_URL'] = ''
        self.assertEqual(self.client.post('/mcp').status_code, 401)
        self.assertEqual(self.client.post('/mcp', headers={'X-Mando-Token': 'test-mcp-token'}).status_code, 200)
        self.assertEqual(self.client.post('/mcp', headers={'Authorization': 'Bearer test-mcp-token'}).status_code, 200)
        os.environ['MANDO_MCP_TOKEN'] = ''
        self.assertEqual(self.client.post('/mcp').status_code, 503)

    def test_rate_budget_is_by_connection_ip_across_routes(self):
        os.environ['MANDO_PUBLIC_URL'] = ''  # sin proxy configurado ni peer loopback
        os.environ['MANDO_PUBLIC_RATE_MAX'] = '2'
        c = TestClient(make_app(), client=('192.0.2.3', 1))
        self.assertEqual(c.post('/api/chat', json={'text': 'hola', 'client_id': 'a'}).status_code, 200)
        self.assertEqual(c.post('/api/report', json={'text': 'hola', 'client_id': 'b'}).status_code, 200)
        r = c.post('/api/strike', json={'client_id': 'c'}, headers={'X-Forwarded-For': '198.51.100.3'})
        self.assertEqual(r.status_code, 429)
        self.assertIn('retry-after', r.headers)

    def test_page_budget_is_separate_and_window_expires(self):
        os.environ['MANDO_PUBLIC_RATE_MAX'] = '1'
        app = make_app()
        c = TestClient(app, client=('192.0.2.4', 1))
        with patch('motor.server.security.time.monotonic', return_value=100):
            self.assertEqual(c.get('/asistente').status_code, 200)
            self.assertEqual(c.get('/asistente').status_code, 200)
            self.assertEqual(c.get('/asistente').status_code, 429)
            self.assertEqual(c.post('/api/chat', json={'text': 'hola'}).status_code, 200)
        with patch('motor.server.security.time.monotonic', return_value=161):
            self.assertEqual(c.get('/asistente').status_code, 200)

    def test_text_and_real_body_size_limits_and_small_body_replayed(self):
        for path in ('/api/chat', '/api/report', '/api/strike', '/api/report/r-1/answer'):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path, json={'text': 'x' * 401}).status_code, 413)
                self.assertEqual(self.client.post(path, content=b'x' * 8193).status_code, 413)
        raw = json.dumps({'text': 'x' * 400}).encode()
        self.assertEqual(self.client.post('/api/chat', content=raw).json()['body'], raw.decode())
        self.assertEqual(self.client.post('/api/chat', content=(part for part in (b'x' * 4096, b'x' * 4097))).status_code, 413)

    def test_fragmented_body_ignores_forged_content_length(self):
        async def run(chunks):
            messages = iter({'type': 'http.request', 'body': chunk, 'more_body': i < len(chunks) - 1}
                            for i, chunk in enumerate(chunks))
            sent = []
            async def receive():
                return next(messages)
            async def send(message):
                sent.append(message)
            async def downstream(scope, receive, send):
                self.fail('Oversized input reached application')
            scope = {'type': 'http', 'method': 'POST', 'path': '/api/chat',
                     'headers': [(b'content-length', b'1')], 'client': ('192.0.2.8', 1)}
            await SecurityGuard(downstream)(scope, receive, send)
            return sent[0]['status']
        self.assertEqual(asyncio.run(run([b'x' * 4096, b'x' * 4097])), 413)

    def test_full_client_storage_refuses_new_ips_without_resetting_old_budgets(self):
        with patch('motor.server.security.MAX_CLIENTS', 2):
            os.environ['MANDO_PUBLIC_RATE_MAX'] = '1'
            app = make_app()
            c1 = TestClient(app, client=('192.0.2.10', 1))
            c2 = TestClient(app, client=('192.0.2.11', 1))
            c3 = TestClient(app, client=('192.0.2.12', 1))
            with patch('motor.server.security.time.monotonic', return_value=100):
                self.assertEqual(c1.post('/api/chat', json={'text': 'a'}).status_code, 200)
                self.assertEqual(c2.post('/api/chat', json={'text': 'b'}).status_code, 200)
                self.assertEqual(c3.post('/api/chat', json={'text': 'c'}).status_code, 429)
                self.assertEqual(c1.post('/api/chat', json={'text': 'd'}).status_code, 429)
            with patch('motor.server.security.time.monotonic', return_value=161):
                self.assertEqual(c3.post('/api/chat', json={'text': 'e'}).status_code, 200)

    def test_sse_and_disconnect_are_preserved(self):
        self.assertEqual(self.client.get('/api/stream').text, 'data: first\n\ndata: second\n\n')
        async def disconnected():
            sent = []
            async def receive():
                return {'type': 'http.disconnect'}
            async def send(message):
                sent.append(message)
            scope = {'type': 'http', 'method': 'POST', 'path': '/api/chat', 'headers': [], 'client': ('192.0.2.8', 1)}
            await self.app(scope, receive, send)
            return sent
        self.assertEqual(asyncio.run(disconnected()), [])


if __name__ == '__main__':
    unittest.main()
