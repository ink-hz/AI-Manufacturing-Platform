"""Inert host boundary probes; these tests never contact MES."""
import asyncio
import importlib
from threading import get_ident
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

BASE = '/api/v1/manufacturing/mes'
ADMIN = {'user_id': 'admin-1', 'configuration_admin': True, 'read_only': False}
SECRET = 'password=private-token; http://private/internal'


class Service:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.thread = None

    def _call(self, name, *args):
        self.calls.append((name, *args))
        self.thread = get_ident()
        if self.failure:
            raise self.failure
        return {'operation': name}

    def status(self): return self._call('status')
    def interfaces(self): return self._call('interfaces')
    def diagnose(self, actor_id): return self._call('diagnose', actor_id)
    def query(self, interface, filters, page, page_size, actor_id):
        return self._call('query', interface, filters, page, page_size, actor_id)


def build(service, authorize):
    try:
        module = importlib.import_module('manufacturing_platform.mes_access.api')
    except ModuleNotFoundError:
        pytest.fail('MES access router implementation is missing')
    return module.build_mes_access_router(service=service, authorize=authorize)


def install(identity=None, *, authorize=None):
    service, calls = Service(), []
    def default(request, *, write):
        calls.append((request.method, write))
        return ADMIN.copy() if identity is None else identity
    app = FastAPI()
    app.include_router(build(service, authorize or default))
    return TestClient(app), service, calls, app


def private(response):
    assert response.headers['cache-control'] == 'private, no-store'
    assert SECRET not in response.text
    assert 'set-cookie' not in response.headers
    return response


def test_constructor_is_lazy():
    class Untouchable:
        def __getattr__(self, name): raise AssertionError('service touched')
    assert build(Untouchable(), lambda request, write: ADMIN).prefix == BASE


@pytest.mark.parametrize('method,path,body,expected', [
    ('GET', '/status', None, ('status',)),
    ('GET', '/interfaces', None, ('interfaces',)),
    ('POST', '/diagnostics/login', b'', ('diagnose', 'admin-1')),
    ('POST', '/diagnostics/login', b'{}', ('diagnose', 'admin-1')),
    ('POST', '/interfaces/order_materials/query', b'{}', ('query', 'order_materials', {}, 1, 1, 'admin-1')),
    ('POST', '/interfaces/order_materials/query', b'{"filters":{"shopOrder":"WO-1"},"page":2,"page_size":3}', ('query', 'order_materials', {'shopOrder': 'WO-1'}, 2, 3, 'admin-1')),
])
def test_fixed_routes(method, path, body, expected):
    client, service, calls, _ = install()
    assert private(client.request(method, BASE + path, content=body)).status_code == 200
    assert service.calls == [expected]
    assert calls == [(method, method == 'POST')]


@pytest.mark.parametrize('identity', [{}, {**ADMIN, 'configuration_admin': False},
    {**ADMIN, 'configuration_admin': 1}, {**ADMIN, 'read_only': 'false'},
    {**ADMIN, 'user_id': ''}, {**ADMIN, 'user_id': None}, {**ADMIN, 'user_id': True}])
def test_admin_identity_required(identity):
    client, service, _, _ = install(identity)
    assert private(client.get(BASE + '/status')).status_code == 403
    assert not service.calls


@pytest.mark.parametrize('method,path', [('POST', '/diagnostics/login'),
    ('POST', '/interfaces/order_materials/query'), ('BREW', '/status'),
    ('POST', '/config'), ('GET', ''), ('GET', '/status')])
def test_auth_before_body_and_service(method, path):
    _, service, calls, app = install({**ADMIN, 'configuration_admin': False})
    outgoing = []
    async def receive(): raise AssertionError('body read before authorization')
    async def send(message): outgoing.append(message)
    scope = {'type':'http', 'asgi':{'version':'3.0'}, 'http_version':'1.1',
        'method':method, 'scheme':'http', 'path':BASE + path,
        'raw_path':(BASE + path).encode(), 'query_string':b'', 'root_path':'',
        'headers':[(b'content-type', b'application/json')],
        'client':('127.0.0.1',1), 'server':('testserver',80)}
    asyncio.run(app(scope, receive, send))
    start = next(m for m in outgoing if m['type'] == 'http.response.start')
    assert start['status'] == 403
    assert (b'cache-control', b'private, no-store') in start['headers']
    assert len(calls) == 1
    assert not service.calls


@pytest.mark.parametrize('status', [401, 403, 500])
def test_host_auth_and_csrf_failures_are_redacted(status):
    def authorize(request, *, write):
        assert write
        raise HTTPException(status, SECRET, headers={'Set-Cookie': SECRET})
    client, service, _, _ = install(authorize=authorize)
    assert private(client.post(BASE + '/diagnostics/login', content=b'bad')).status_code == (status if status in {401,403} else 503)
    assert not service.calls


@pytest.mark.parametrize('method,path,body', [('GET','/status',None), ('GET','/interfaces',None),
    ('POST','/diagnostics/login',None), ('POST','/interfaces/order_materials/query',b'{}')])
def test_async_authorize_and_off_loop_service(method, path, body):
    loop_threads = []
    async def authorize(request, *, write):
        await asyncio.sleep(0)
        loop_threads.append(get_ident())
        return ADMIN.copy()
    client, service, _, _ = install(authorize=authorize)
    assert private(client.request(method, BASE + path, content=body)).status_code == 200
    assert service.thread != loop_threads[0]


def test_uuid_actor_and_read_only_admin():
    actor = UUID('00000000-0000-0000-0000-000000000123')
    client, service, _, _ = install({**ADMIN, 'user_id': actor})
    assert private(client.post(BASE + '/diagnostics/login')).status_code == 200
    assert service.calls == [('diagnose', str(actor))]
    client, service, _, _ = install({**ADMIN, 'read_only': True})
    assert private(client.post(BASE + '/diagnostics/login', content=b'bad')).status_code == 403
    assert not service.calls
    assert private(client.get(BASE + '/status')).status_code == 200


@pytest.mark.parametrize('body', [b'', b'null', b'[]', b'true', b'1', b'{', b'\xff',
    b'{"password":"private-token"}', b'{"filters":null}', b'{"filters":[]}',
    b'{"filters":{"shopOrder":true}}', b'{"filters":{"url":"private-token"}}',
    b'{"page":true}', b'{"page":1.0}', b'{"page":"1"}', b'{"page":0}',
    b'{"page":1000001}', b'{"page_size":0}', b'{"page_size":6}',
    b'{"page_size":null}', b'{"page":1,"page":2}',
    b'{"filters":{"shopOrder":"A","shopOrder":"B"}}', b' ' * 4097 + b'{}'])
def test_query_body_strict_before_service(body):
    client, service, _, _ = install()
    assert private(client.post(BASE + '/interfaces/order_materials/query', content=body)).status_code == 422
    assert not service.calls


@pytest.mark.parametrize('method,path,body', [('GET','/status',b'{}'),
    ('POST','/diagnostics/login',b'{"x":1}'), ('POST','/diagnostics/login',b'null'),
    ('POST','/diagnostics/login',b' ' * 4097)])
def test_other_routes_reject_body_arguments(method, path, body):
    client, service, _, _ = install()
    assert private(client.request(method, BASE + path, content=body)).status_code == 422
    assert not service.calls


@pytest.mark.parametrize('method,path', [('GET','/status'), ('GET','/interfaces'),
    ('POST','/diagnostics/login'), ('POST','/interfaces/order_materials/query')])
def test_url_query_rejected(method, path):
    client, service, _, _ = install()
    assert private(client.request(method, BASE + path + '?password=private-token', content=b'{}')).status_code == 422
    assert not service.calls


@pytest.mark.parametrize('method,path,status', [('PUT','/status',405), ('TRACE','/status',405),
    ('BREW','/status',405), ('HEAD','/status',405), ('OPTIONS','/status',405),
    ('GET','/diagnostics/login',405), ('GET','/interfaces/order_materials/query',405),
    ('POST','/config',404), ('GET','/status/',404), ('GET','',404), ('GET','/',404),
    ('POST','/interfaces/arbitrary/query',404), ('POST','/interfaces/order_materials/query/extra',404)])
def test_unknown_routes_and_methods_protected(method, path, status):
    client, service, calls, _ = install()
    assert private(client.request(method, BASE + path, content=b'{}')).status_code == status
    assert calls == [(method, method not in {'GET','HEAD','OPTIONS'})]
    assert not service.calls


@pytest.mark.parametrize('failure,expected', [(RuntimeError(SECRET), {'code':'MES_UNAVAILABLE'})])
def test_service_errors_redacted(failure, expected):
    client, service, _, _ = install()
    service.failure = failure
    response = private(client.get(BASE + '/status'))
    assert response.status_code == 503
    assert response.json() == expected


def test_mes_error_only_safe_code_and_status():
    from manufacturing_platform.mes_access.errors import MesAccessError
    client, service, _, _ = install()
    service.failure = MesAccessError('MES_TIMEOUT', 504)
    service.failure.args = (SECRET,)
    response = private(client.get(BASE + '/status'))
    assert response.status_code == 504
    assert response.json() == {'code':'MES_TIMEOUT'}


def test_streamed_body_limit_applies_before_service():
    _, service, _, app = install()
    outgoing, chunks = [], iter([b' ' * 2048, b' ' * 2048, b'{}'])
    async def receive():
        chunk = next(chunks)
        return {'type':'http.request', 'body':chunk, 'more_body':chunk != b'{}'}
    async def send(message): outgoing.append(message)
    path = BASE + '/interfaces/order_materials/query'
    scope = {'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST',
        'scheme':'http','path':path,'raw_path':path.encode(),'query_string':b'','root_path':'',
        'headers':[],'client':('127.0.0.1',1),'server':('testserver',80)}
    asyncio.run(app(scope, receive, send))
    start = next(message for message in outgoing if message['type'] == 'http.response.start')
    assert start['status'] == 422
    assert (b'cache-control',b'private, no-store') in start['headers']
    assert not service.calls
