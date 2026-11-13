"""HTTP boundary tests with an inert SAP service; no SAP connection is used."""

import asyncio
import importlib
from threading import get_ident
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

BASE = "/api/v1/manufacturing/sap"
ADMIN = {"user_id": "admin-1", "read_only": False, "configuration_admin": True}
SECRET = "password=private-token; http://sap-private/internal"


class Service:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.thread = None

    def _call(self, name, *args):
        self.calls.append((name, *args))
        self.thread = get_ident()
        if self.failure is not None:
            raise self.failure
        return {"operation": name, "arguments": list(args)}

    def status(self):
        return self._call("status")

    def interfaces(self):
        return self._call("interfaces")

    def contract(self, function):
        return self._call("contract", function)

    def ping(self, actor_id):
        return self._call("ping", actor_id)

    def refresh_contracts(self, actor_id):
        return self._call("refresh_contracts", actor_id)


def build(service, authorize):
    try:
        module = importlib.import_module("manufacturing_platform.sap_access.api")
    except ModuleNotFoundError as exc:
        pytest.fail(f"SAP access router implementation is missing: {exc.name}")
    return module.build_sap_access_router(service=service, authorize=authorize)


def install(identity=None, *, authorize=None):
    service = Service()
    authorization_calls = []

    def default_authorize(request, *, write):
        authorization_calls.append((request.method, write))
        return ADMIN.copy() if identity is None else identity

    app = FastAPI()
    app.include_router(build(service, authorize or default_authorize))
    return TestClient(app), service, authorization_calls, app


def private(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert SECRET not in response.text
    return response


def test_router_construction_does_not_read_service():
    class Untouchable:
        def __getattr__(self, name):
            raise AssertionError("construction accessed SAP service")

    router = build(Untouchable(), lambda request, write: ADMIN)
    assert router.prefix == BASE


@pytest.mark.parametrize(
    "method,path,body,expected",
    [
        ("GET", "/status", None, ("status",)),
        ("GET", "/interfaces", None, ("interfaces",)),
        ("GET", "/interfaces/RFC_PING/contract", None, ("contract", "RFC_PING")),
        ("GET", "/interfaces/ZMMRFC35/contract", None, ("contract", "ZMMRFC35")),
        ("GET", "/interfaces/BAPI_PRODORD_GET_DETAIL/contract", None, ("contract", "BAPI_PRODORD_GET_DETAIL")),
        ("POST", "/diagnostics/ping", b"", ("ping", "admin-1")),
        ("POST", "/diagnostics/ping", b"{}", ("ping", "admin-1")),
        ("POST", "/interfaces/refresh", b" \n{}\t", ("refresh_contracts", "admin-1")),
    ],
)
def test_fixed_routes_call_only_the_supplied_service(method, path, body, expected):
    client, service, calls, _ = install()
    response = private(client.request(method, BASE + path, content=body))
    assert response.status_code == 200, response.text
    assert service.calls == [expected]
    assert calls == [(method, method not in {"GET", "HEAD", "OPTIONS"})]


@pytest.mark.parametrize("identity", [
    {},
    {**ADMIN, "configuration_admin": False},
    {**ADMIN, "configuration_admin": "true"},
    {**ADMIN, "read_only": "false"},
    {**ADMIN, "user_id": ""},
    {**ADMIN, "user_id": None},
])
def test_invalid_or_nonadmin_identity_is_denied_before_service(identity):
    client, service, _, _ = install(identity)
    response = private(client.get(BASE + "/status"))
    assert response.status_code == 403
    assert not service.calls


def test_authentication_denial_is_redacted_and_not_cached():
    def deny(request, *, write):
        raise HTTPException(401, SECRET, headers={"Set-Cookie": SECRET})

    client, service, _, _ = install(authorize=deny)
    response = private(client.post(BASE + "/diagnostics/ping", content=b"not-json"))
    assert response.status_code == 401
    assert "set-cookie" not in response.headers
    assert not service.calls


def test_unauthorized_request_never_reads_body():
    identity = {**ADMIN, "configuration_admin": False}
    _, service, _, app = install(identity)
    outgoing = []

    async def receive():
        raise AssertionError("unauthorized body was read")

    async def send(message):
        outgoing.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": BASE + "/diagnostics/ping",
        "raw_path": (BASE + "/diagnostics/ping").encode(), "query_string": b"",
        "root_path": "", "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1), "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    start = next(message for message in outgoing if message["type"] == "http.response.start")
    assert start["status"] == 403
    assert (b"cache-control", b"private, no-store") in start["headers"]
    assert not service.calls


def test_async_authorization_is_awaited_and_sync_service_runs_off_event_loop():
    loop_threads = []

    async def authorize(request, *, write):
        await asyncio.sleep(0)
        loop_threads.append(get_ident())
        return ADMIN.copy()

    client, service, _, _ = install(authorize=authorize)
    response = private(client.get(BASE + "/status"))
    assert response.status_code == 200
    assert len(loop_threads) == 1
    assert service.thread != loop_threads[0]


def test_uuid_actor_id_is_passed_as_a_string():
    actor_id = UUID("00000000-0000-0000-0000-000000000123")
    client, service, _, _ = install({**ADMIN, "user_id": actor_id})
    assert private(client.post(BASE + "/diagnostics/ping")).status_code == 200
    assert service.calls == [("ping", str(actor_id))]


@pytest.mark.parametrize("path", ["/diagnostics/ping", "/interfaces/refresh"])
def test_read_only_administrator_cannot_initiate_network_operations(path):
    client, service, calls, _ = install({**ADMIN, "read_only": True})
    response = private(client.post(BASE + path, content=b"not-json"))
    assert response.status_code == 403
    assert calls == [("POST", True)]
    assert not service.calls


def test_read_only_administrator_can_read_cached_status():
    client, service, _, _ = install({**ADMIN, "read_only": True})
    assert private(client.get(BASE + "/status")).status_code == 200
    assert service.calls == [("status",)]


@pytest.mark.parametrize("method,path", [
    ("GET", "/status"), ("GET", "/interfaces"),
    ("GET", "/interfaces/RFC_PING/contract"),
    ("POST", "/diagnostics/ping"), ("POST", "/interfaces/refresh"),
])
def test_query_parameters_are_rejected_before_service(method, path):
    client, service, _, _ = install()
    response = private(client.request(method, BASE + path + "?password=private-token"))
    assert response.status_code == 422
    assert "private-token" not in response.text
    assert not service.calls


@pytest.mark.parametrize("body", [
    b'{"function":"ZMMRFC35"}', b'{"password":"private-token"}', b"[]",
    b"null", b"true", b"1", b'"{}"', b"<xml>private-token</xml>",
    b"{", b"\xff", b" " * 1025 + b"{}",
])
def test_nonempty_arguments_and_invalid_bodies_are_rejected_before_service(body):
    client, service, _, _ = install()
    response = private(client.post(BASE + "/diagnostics/ping", content=body))
    assert response.status_code == 422
    assert "private-token" not in response.text
    assert not service.calls


def test_get_request_with_a_body_is_rejected_before_service():
    client, service, _, _ = install()
    response = private(client.request("GET", BASE + "/status", content=b"{}"))
    assert response.status_code == 422
    assert not service.calls


@pytest.mark.parametrize("function", ["CUSTOM_READ", "rfc_ping", "RFC_PING;DROP", "ZMMRFC35%2Fextra"])
def test_function_path_cannot_select_arbitrary_sap_calls(function):
    client, service, _, _ = install()
    response = private(client.get(BASE + "/interfaces/" + function + "/contract"))
    assert response.status_code in {404, 422}
    assert not service.calls


@pytest.mark.parametrize("method,path,status", [
    ("PUT", "/status", 405), ("DELETE", "/interfaces", 405),
    ("TRACE", "/status", 405), ("BREW", "/status", 405),
    ("HEAD", "/status", 405), ("OPTIONS", "/status", 405),
    ("POST", "/interfaces/ZMMRFC35/invoke", 404),
    ("GET", "/config", 404), ("POST", "/config", 404),
    ("GET", "/status/", 404), ("GET", "", 404), ("GET", "/", 404),
])
def test_unexposed_routes_and_methods_are_guarded_without_service_io(method, path, status):
    client, service, calls, _ = install()
    response = private(client.request(method, BASE + path, content=b""))
    assert response.status_code == status
    assert calls == [(method, method not in {"GET", "HEAD", "OPTIONS"})]
    assert not service.calls


@pytest.mark.parametrize("method,path", [("BREW", "/status"), ("POST", "/config"), ("GET", "")])
def test_unknown_requests_do_not_bypass_authorization(method, path):
    client, service, calls, _ = install({**ADMIN, "configuration_admin": False})
    assert private(client.request(method, BASE + path)).status_code == 403
    assert len(calls) == 1
    assert not service.calls


def test_unexpected_service_error_is_redacted():
    client, service, _, _ = install()
    service.failure = RuntimeError(SECRET)
    response = private(client.get(BASE + "/status"))
    assert response.status_code == 503
    assert response.json() == {"code": "SAP_UNAVAILABLE"}


def test_unexpected_authorization_error_is_redacted():
    def fail(request, *, write):
        raise RuntimeError(SECRET)

    client, service, _, _ = install(authorize=fail)
    response = private(client.get(BASE + "/status"))
    assert response.status_code == 503
    assert not service.calls


def test_sap_access_error_exposes_only_safe_code_and_status():
    client, service, _, _ = install()
    from manufacturing_platform.sap_access.errors import SapAccessError

    service.failure = SapAccessError("SAP_TIMEOUT", 504)
    service.failure.args = (SECRET,)
    response = private(client.post(BASE + "/diagnostics/ping"))
    assert response.status_code == 504
    assert response.json() == {"code": "SAP_TIMEOUT"}
