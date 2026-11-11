from dataclasses import replace
import json
from urllib.parse import parse_qs
import pytest
from .conftest import implementation, SECRET

SITE = 'a'*32
LOGIN = ('<form method="post" action="j_spring_security_check">'
         '<input type="hidden" name="loginMode" value="default"></form>'
         '<ul id="siteID"><li value="'+SITE+'">1000</li></ul>').encode()
HOME = b'<title>I-Factory</title>/core/home/home/show_subMenu.jsp'


class Wire:
    def __init__(self, responses=None):
        self.calls=[]
        self.responses=list(responses or [
            (200, [('Content-Type','text/html'),('Set-Cookie','JSESSIONID=before; Path=/; HttpOnly')], LOGIN),
            (302, [('Location','/'),('Set-Cookie','JSESSIONID=after; Path=/; HttpOnly')], b''),
            (200, [('Content-Type','text/html')], HOME),
        ])
    def __call__(self, method, path, body, headers):
        self.calls.append((method,path,body,headers))
        return self.responses.pop(0)


def client(config, wire):
    return implementation('mes_access.transport').SessionTransport(config, requester=wire)


def test_login_uses_site_and_verifies_protected_home(config):
    wire=Wire();c=client(config,wire)
    summary=c.login()
    assert summary['authentication_verified'] is True and summary['site_code']=='1000'
    assert [x[1] for x in wire.calls]==['/login.jsp','/j_spring_security_check','/']
    body=parse_qs(wire.calls[1][2].decode())
    assert body=={'username':['test-user'],'password':[SECRET],'loginMode':['default'],'siteId':[SITE]}
    assert wire.calls[1][3]['Cookie']=='JSESSIONID=before'
    assert wire.calls[2][3]['Cookie']=='JSESSIONID=after'
    assert 'after' not in json.dumps(summary) and SECRET not in repr(c)
    c.close()
    assert c.authenticated is False


@pytest.mark.parametrize('status,location', [
    (302,'http://evil.test/'),(302,'//evil.test/'),(302,'/login.jsp?error=passwordError'),
    (200,''),(303,'/'),(302,'/orbbec/wms/save.action'),
])
def test_login_denials_never_follow_redirect(config,status,location):
    wire=Wire([(200,[],LOGIN),(status,[('Location',location)],b'')])
    with pytest.raises(Exception) as caught:client(config,wire).login()
    assert caught.value.code in {'MES_AUTHENTICATION_FAILED','MES_REDIRECT_BLOCKED'}
    assert len(wire.calls)==2 and SECRET not in str(caught.value)


def test_cookie_without_authenticated_home_is_not_success(config):
    wire=Wire();wire.responses[-1]=(200,[],b'<title>login</title>')
    with pytest.raises(Exception) as caught:client(config,wire).login()
    assert caught.value.code=='MES_AUTHENTICATION_FAILED'


@pytest.mark.parametrize('payload', [b'no form', LOGIN.replace(b'1000',b'2000'), LOGIN.replace(b'j_spring_security_check',b'other')])
def test_changed_login_contract_does_not_submit_password(config,payload):
    wire=Wire([(200,[],payload)])
    with pytest.raises(Exception) as caught:client(config,wire).login()
    assert caught.value.code=='MES_LOGIN_CONTRACT_CHANGED'
    assert len(wire.calls)==1


def test_disabled_configuration_never_opens_connection(config):
    wire=Wire()
    with pytest.raises(Exception) as caught:client(replace(config,enabled=False),wire).login()
    assert caught.value.code=='MES_DISABLED' and not wire.calls


@pytest.mark.parametrize('exception,code',[(TimeoutError(SECRET),'MES_TIMEOUT'),(OSError(SECRET),'MES_CONNECTION_FAILED')])
def test_network_failure_is_redacted_without_retry(config,exception,code):
    calls=[]
    def fail(*args):calls.append(args);raise exception
    with pytest.raises(Exception) as caught:client(config,fail).login()
    assert caught.value.code==code and len(calls)==1
    assert SECRET not in str(caught.value)


def test_response_size_limit_applies_to_login(config):
    wire=Wire([(200,[],b'x'*(config.max_response_bytes+1))])
    with pytest.raises(Exception) as caught:client(config,wire).login()
    assert caught.value.code=='MES_RESPONSE_TOO_LARGE'


def test_foreign_domain_cookie_is_rejected(config):
    wire=Wire([(200,[('Set-Cookie','JSESSIONID=stolen; Domain=evil.test; Path=/')],LOGIN)])
    with pytest.raises(Exception) as caught:client(config,wire).login()
    assert caught.value.code=='MES_INVALID_COOKIE'


@pytest.mark.parametrize('headers', [[], [('Location', '')], [('Location', '   ')]])
def test_missing_success_location_is_rejected_before_home(config, headers):
    wire = Wire([(200, [], LOGIN),
                 (302, headers + [('Set-Cookie', 'JSESSIONID=after; Path=/')], b''),
                 (200, [], HOME)])
    with pytest.raises(Exception) as caught:
        client(config, wire).login()
    assert caught.value.code == 'MES_AUTHENTICATION_FAILED'
    assert len(wire.calls) == 2


# Native-path tests use real HTTPConnection/socket parsing; only DNS and the
# final socket destination are redirected to an offline loopback fixture.
import contextlib
import http.client
import socket
import ssl
import threading
import time


@contextlib.contextmanager
def native_server(monkeypatch, scripts):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    listener.settimeout(0.05)
    stopped = threading.Event()
    requests, connections, destinations = [], [], []
    original_connect = socket.create_connection

    def connect(address, timeout=None, source_address=None):
        destinations.append(address)
        return original_connect(listener.getsockname(), timeout, source_address)

    monkeypatch.setattr(socket, 'create_connection', connect)

    def serve():
        for script in scripts:
            while not stopped.is_set():
                try:
                    conn, _ = listener.accept()
                    break
                except socket.timeout:
                    continue
                except OSError:
                    return
            else:
                return
            connections.append(conn)
            with conn:
                conn.settimeout(3)
                data = b''
                try:
                    while b'\r\n\r\n' not in data:
                        part = conn.recv(4096)
                        if not part:
                            return
                        data += part
                    requests.append(data)
                    script(conn, stopped)
                except (OSError, ValueError):
                    pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield requests, destinations
    finally:
        stopped.set()
        listener.close()
        for conn in connections:
            with contextlib.suppress(OSError):
                conn.shutdown(socket.SHUT_RDWR)
            conn.close()
        thread.join(1)


def reply(payload=b'ok', extra=b''):
    def send(conn, stopped):
        conn.sendall(b'HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: ' +
                     str(len(payload)).encode() + b'\r\n' + extra + b'\r\n' + payload)
    return send


def native_client(config, **kwargs):
    return implementation('mes_access.transport').SessionTransport(config, **kwargs)


def test_native_resolution_peer_reconnect_host_and_cookie_isolation(config, monkeypatch):
    resolutions, factories = [], []
    def resolve(host, port, **kwargs):
        resolutions.append((host, port))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (peer, port))
                for peer in ['127.0.0.1', '127.0.0.2']]
    def factory(origin, peer, settings):
        factories.append((origin.hostname, peer, settings))
        return http.client.HTTPConnection(origin.hostname, timeout=settings.connect_timeout_seconds)
    with native_server(monkeypatch, [reply(extra=b'Set-Cookie: JSESSIONID=one; Path=/\r\n'),
                                     reply(), reply()]) as (requests, destinations):
        first = native_client(config, resolver=resolve, connection_factory=factory)
        second = native_client(config, resolver=resolve, connection_factory=factory)
        try:
            assert first._request('GET', '/')[2] == b'ok'
            assert first._request('GET', '/')[2] == b'ok'
            assert second._request('GET', '/')[2] == b'ok'
            assert resolutions == [('mes.orbbec.com', 80)] * 2
            assert destinations == [('127.0.0.1', 80)] * 3
            assert all(b'Host: mes.orbbec.com\r\n' in request for request in requests)
            assert b'Cookie:' not in requests[0] and b'Cookie: JSESSIONID=one' in requests[1]
            assert b'Cookie:' not in requests[2]
            assert [(host, peer) for host, peer, _ in factories] == [('mes.orbbec.com', '127.0.0.1')] * 2
        finally:
            first.close()
            second.close()


@pytest.mark.parametrize('phase', ['headers', 'body'])
def test_native_total_deadline_stops_trickled_response_without_retry(config, monkeypatch, phase):
    config = replace(config, connect_timeout_seconds=1, read_timeout_seconds=1)
    closed = threading.Event()
    def trickle(conn, stopped):
        if phase == 'body':
            conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 20\r\n\r\n')
        else:
            conn.sendall(b'HTTP/1.1 200 OK\r\nX-Slow: ')
        for _ in range(20):
            if stopped.wait(0.2):
                return
            try:
                conn.sendall(b'x')
            except OSError:
                closed.set()
                return
        conn.sendall(b'\r\nContent-Length: 0\r\n\r\n')
    with native_server(monkeypatch, [trickle]) as (requests, destinations):
        c = native_client(config, resolver=lambda *a, **k: [(2, 1, 6, '', ('127.0.0.1', 80))])
        start = time.monotonic()
        with pytest.raises(Exception) as caught:
            c._request('GET', '/')
        elapsed = time.monotonic() - start
        assert caught.value.code == 'MES_TIMEOUT'
        assert 1.5 <= elapsed < 2.7
        assert len(requests) == len(destinations) == 1
        assert c._connection is None and c._cookie is None
        assert closed.wait(0.8)


def test_native_dns_deadline_returns_without_late_connection_or_retry(config):
    config = replace(config, connect_timeout_seconds=1, read_timeout_seconds=1)
    release, finished = threading.Event(), threading.Event()
    resolutions, connections = [], []
    def resolve(*args, **kwargs):
        resolutions.append(args)
        release.wait(3)
        finished.set()
        return [(2, 1, 6, '', ('127.0.0.1', 80))]
    def factory(*args):
        connections.append(args)
        raise AssertionError('expired DNS must not connect')
    c = native_client(config, resolver=resolve, connection_factory=factory)
    start = time.monotonic()
    try:
        with pytest.raises(Exception) as caught:
            c._request('GET', '/')
        assert caught.value.code == 'MES_TIMEOUT'
        assert time.monotonic() - start < 1.7
        assert len(resolutions) == 1 and not connections
    finally:
        release.set()
        assert finished.wait(1)
    assert c._peer is None and c._connection is None and not connections


@pytest.mark.parametrize('response,code', [
    (b'HTTP/1.1 200 OK\r\nContent-Length: 999999\r\n\r\n', 'MES_RESPONSE_TOO_LARGE'),
    (b'HTTP/1.1 200 OK\r\nContent-Length: bad\r\n\r\n', 'MES_RESPONSE_TOO_LARGE'),
    (b'HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: 0\r\n\r\n', 'MES_UNSUPPORTED_ENCODING'),
    (b'HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n' + b'x' * 1025, 'MES_RESPONSE_TOO_LARGE'),
    (b'not HTTP\r\n\r\n', 'MES_TRANSPORT_ERROR'),
])
def test_native_resource_failures_close_without_retry(config, monkeypatch, response, code):
    def send(conn, stopped):
        conn.sendall(response)
    with native_server(monkeypatch, [send]) as (requests, destinations):
        c = native_client(replace(config, max_response_bytes=1024),
                          resolver=lambda *a, **k: [(2, 1, 6, '', ('127.0.0.1', 80))])
        with pytest.raises(Exception) as caught:
            c._request('GET', '/')
        assert caught.value.code == code
        assert c._connection is None
        assert len(requests) == len(destinations) == 1


def test_native_connection_failure_is_not_retried(config):
    attempts = []
    class BrokenConnection:
        sock = None
        def connect(self):
            attempts.append('connect')
            raise OSError(SECRET)
        def close(self):
            attempts.append('close')
    c = native_client(config, resolver=lambda *a, **k: [(2, 1, 6, '', ('127.0.0.1', 80))],
                      connection_factory=lambda *a: BrokenConnection())
    with pytest.raises(Exception) as caught:
        c._request('GET', '/')
    assert caught.value.code == 'MES_CONNECTION_FAILED'
    assert SECRET not in str(caught.value)
    assert attempts.count('connect') == 1 and attempts.count('close') >= 1


def test_native_https_reconnect_preserves_sni_and_certificate_policy(config, monkeypatch):
    names, factories = [], []
    context = ssl.create_default_context()
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    # Keep the real HTTPSConnection path; replace only TLS wrapping so the
    # offline HTTP fixture can observe the exact certificate/SNI identity.
    def wrap(sock, *, server_hostname):
        names.append(server_hostname)
        return sock
    monkeypatch.setattr(context, 'wrap_socket', wrap)
    def factory(origin, peer, settings):
        factories.append(peer)
        return http.client.HTTPSConnection(origin.hostname, context=context)
    with native_server(monkeypatch, [reply(), reply()]) as (requests, destinations):
        c = native_client(replace(config, base_url='https://mes.orbbec.com/'),
                          resolver=lambda *a, **k: [(2, 1, 6, '', ('127.0.0.1', 443))],
                          connection_factory=factory)
        try:
            c._request('GET', '/')
            c._request('GET', '/')
            assert names == ['mes.orbbec.com'] * 2
            assert factories == ['127.0.0.1']
            assert destinations == [('127.0.0.1', 443)] * 2
            assert all(b'Host: mes.orbbec.com\r\n' in request for request in requests)
        finally:
            c.close()


def test_native_keepalive_reuses_connection(config, monkeypatch):
    subsequent, factories = [], []
    def keepalive(conn, stopped):
        conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok')
        data = b''
        while b'\r\n\r\n' not in data:
            data += conn.recv(4096)
        subsequent.append(data)
        conn.sendall(b'HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: 2\r\n\r\nok')
    def factory(origin, peer, settings):
        factories.append(peer)
        return http.client.HTTPConnection(origin.hostname)
    with native_server(monkeypatch, [keepalive]) as (requests, destinations):
        c = native_client(config, resolver=lambda *a, **k: [(2, 1, 6, '', ('127.0.0.1', 80))],
                          connection_factory=factory)
        try:
            assert c._request('GET', '/first')[2] == b'ok'
            assert c._request('GET', '/second')[2] == b'ok'
            assert len(requests) == len(subsequent) == len(destinations) == len(factories) == 1
            assert subsequent[0].startswith(b'GET /second HTTP/1.1')
        finally:
            c.close()


def test_native_read_idle_timeout_is_applied_without_retry(config, monkeypatch):
    timeouts = []
    class ObservedConnection(http.client.HTTPConnection):
        def request(self, *args, **kwargs):
            timeouts.append(self.sock.gettimeout())
            return super().request(*args, **kwargs)
    def stall(conn, stopped):
        stopped.wait(3)
    with native_server(monkeypatch, [stall]) as (requests, destinations):
        c = native_client(replace(config, connect_timeout_seconds=1, read_timeout_seconds=1),
                          resolver=lambda *a, **k: [(2, 1, 6, '', ('127.0.0.1', 80))],
                          connection_factory=lambda origin, *a: ObservedConnection(origin.hostname))
        start = time.monotonic()
        with pytest.raises(Exception) as caught:
            c._request('GET', '/')
        assert caught.value.code == 'MES_TIMEOUT'
        assert time.monotonic() - start < 1.7
        assert timeouts == [1] and len(requests) == len(destinations) == 1
        assert c._connection is None


def test_native_real_tls_handshake_shares_remaining_connect_deadline(config, monkeypatch):
    # Real default TLS wrapping detaches the raw socket. A peer that accepts
    # TCP but never speaks TLS must remain interruptible during the handshake.
    context = ssl.create_default_context()
    identities = []
    real_wrap = context.wrap_socket
    def observe_wrap(sock, **kwargs):
        identities.append((kwargs['server_hostname'], kwargs['do_handshake_on_connect'],
                           context.check_hostname, context.verify_mode))
        return real_wrap(sock, **kwargs)
    monkeypatch.setattr(context, 'wrap_socket', observe_wrap)
    monkeypatch.setattr(ssl, 'create_default_context', lambda: context)
    with native_server(monkeypatch, [reply()]) as (requests, destinations):
        offline_connect = socket.create_connection
        def delayed_tcp(address, timeout=None, source_address=None):
            time.sleep(1.6)
            return offline_connect(address, timeout, source_address)
        monkeypatch.setattr(socket, 'create_connection', delayed_tcp)
        c = native_client(replace(config, base_url='https://mes.orbbec.com/',
                                  connect_timeout_seconds=2, read_timeout_seconds=1),
                          resolver=lambda *a, **k: [(2, 1, 6, '', ('127.0.0.1', 443))])
        start = time.monotonic()
        with pytest.raises(Exception) as caught:
            c._request('GET', '/')
        elapsed = time.monotonic() - start
        assert caught.value.code == 'MES_TIMEOUT'
        assert 1.8 <= elapsed < 2.7, f'TLS connection exceeded two-second budget: {elapsed:.2f}s'
        assert len(destinations) == 1 and not requests
        assert identities == [('mes.orbbec.com', False, True, ssl.CERT_REQUIRED)]
        assert c._connection is None
