"""Offline transport checks: no redirects, unsafe XML, secret errors, or unbounded reads."""
import base64
import importlib
import importlib.util
import socket
import ssl

import pytest

from manufacturing_platform.sap_connection import SapConnectionConfig


SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
RFC = "urn:sap-com:document:sap:rfc:functions"
WSDL = b'<definitions xmlns="http://schemas.xmlsoap.org/wsdl/"/>'


def envelope(function="RFC_PING", content=""):
    return f'<s:Envelope xmlns:s="{SOAP}" xmlns:r="{RFC}"><s:Body><r:{function}>{content}</r:{function}></s:Body></s:Envelope>'.encode()


def config(**changes):
    return SapConnectionConfig(**{
        "version": 2, "transport": "soap_http", "environment": "test",
        "application_server": "sap.example.test", "system_number": "10", "system_id": "S4D",
        "client": "300", "username": "TEST-ACCOUNT", "password": "TEST-SECRET",
        "enabled": True, "read_only": True, "allowed_functions": ("RFC_PING",),
        "http_scheme": "https", "http_port": 44310, "allow_http_test": False,
        "timeout_seconds": 7, "max_response_bytes": 1024, "ca_bundle_path": None,
        **changes,
    })


@pytest.fixture
def module():
    name = "manufacturing_platform.sap_access.transport"
    assert importlib.util.find_spec(name) is not None, "HTTP transport has not been implemented"
    return importlib.import_module(name)


class Sender:
    def __init__(self, reply):
        self.calls = []
        self.reply = reply

    def __call__(self, *args):
        self.calls.append(args)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_constructor_has_no_io_and_metadata_uses_only_fixed_path(module):
    sender = Sender(module.HttpReply(200, {"Content-Type": "text/xml; charset=utf-8"}, WSDL))
    transport = module.SoapTransport(config(), sender=sender)
    assert sender.calls == []
    assert transport.fetch_wsdl("ZMMRFC35") == WSDL
    method, path, body, headers, timeout, cap = sender.calls[0]
    assert (method, path, body) == ("GET", "/sap/bc/soap/wsdl11?services=ZMMRFC35&sap-client=300", None)
    assert timeout == 7 and cap == 1024
    assert "TEST-ACCOUNT" not in path and "TEST-SECRET" not in path
    assert headers["Authorization"] == "Basic " + base64.b64encode(b"TEST-ACCOUNT:TEST-SECRET").decode()


def test_ping_posts_matching_body_and_fixed_soap_action(module):
    response = envelope("RFC_PING.Response")
    sender = Sender(module.HttpReply(200, {"content-type": "text/xml"}, response))
    assert module.SoapTransport(config(), sender=sender).invoke("RFC_PING", envelope(), "http://www.sap.com/RFC_PING") == response
    method, path, body, headers, *_ = sender.calls[0]
    assert method == "POST" and path == "/sap/bc/soap/rfc?sap-client=300"
    assert body == envelope()
    assert headers["SOAPAction"] == '"http://www.sap.com/RFC_PING"'


@pytest.mark.parametrize("function", ["RFC_PING?x=1", "*", "Z_UNREVIEWED", "../RFC_PING", "rfc_ping"])
def test_unknown_metadata_function_is_rejected_before_io(module, function):
    sender = Sender(None)
    with pytest.raises(module.SapAccessError) as error:
        module.SoapTransport(config(), sender=sender).fetch_wsdl(function)
    assert error.value.code == "SAP_FUNCTION_NOT_ALLOWED" and sender.calls == []


def test_unreviewed_zmmrfc80_remains_metadata_only_even_when_configured(module):
    sender = Sender(module.HttpReply(200, {"Content-Type": "text/xml"}, WSDL))
    transport = module.SoapTransport(config(allowed_functions=("RFC_PING", "ZMMRFC80")), sender=sender)
    assert transport.fetch_wsdl("ZMMRFC80") == WSDL
    with pytest.raises(module.SapAccessError, match="SAP_FUNCTION_NOT_ALLOWED"):
        transport.invoke("ZMMRFC80", envelope("ZMMRFC80"), "http://www.sap.com/ZMMRFC80")
    assert len(sender.calls) == 1


@pytest.mark.parametrize("function,body,action", [
    ("ZMMRFC35", envelope("ZMMRFC35"), "http://www.sap.com/ZMMRFC35"),
    ("RFC_PING", envelope("ZMMRFC35"), "http://www.sap.com/RFC_PING"),
    ("RFC_PING", envelope(), "http://www.sap.com/ZMMRFC35"),
    ("RFC_PING", envelope(), "http://www.sap.com/RFC_PING\r\nX-Leak: TEST-SECRET"),
    ("RFC_PING", envelope().replace(b"<r:RFC_PING>", b"<r:RFC_PING/><r:ZMMRFC35>").replace(b"</r:RFC_PING>", b"</r:ZMMRFC35>"), "http://www.sap.com/RFC_PING"),
    ("RFC_PING", b'<RFC_PING/>', "http://www.sap.com/RFC_PING"),
    ("RFC_PING", envelope().replace(RFC.encode(), b"urn:other"), "http://www.sap.com/RFC_PING"),
    ("RFC_PING", envelope().replace(b"<s:Body>", b"<s:Body>TEST-SECRET"), "http://www.sap.com/RFC_PING"),
    ("RFC_PING", b'<!DOCTYPE Envelope [<!ENTITY x SYSTEM "file:///secret">]>' + envelope(), "http://www.sap.com/RFC_PING"),
])
def test_invoke_allowlist_body_and_action_reject_before_io(module, function, body, action):
    sender = Sender(None)
    with pytest.raises(module.SapAccessError) as error:
        module.SoapTransport(config(), sender=sender).invoke(function, body, action)
    assert sender.calls == [] and "TEST-SECRET" not in str(error.value)


@pytest.mark.parametrize("changes", [
    {"enabled": False}, {"version": 1, "transport": "rfc"},
    {"http_scheme": "http", "allow_http_test": False}, {"read_only": False},
    {"username": ""}, {"environment": "production"},
])
def test_disabled_or_unsafe_config_never_sends(module, changes):
    sender = Sender(None)
    transport = module.SoapTransport(config(**changes), sender=sender)
    with pytest.raises(module.SapAccessError):
        transport.fetch_wsdl("RFC_PING")
    assert sender.calls == []


@pytest.mark.parametrize("reply,code", [
    ((302, {"Location": "https://attacker.test/TEST-SECRET"}, b""), "SAP_REDIRECT_BLOCKED"),
    ((401, {"Set-Cookie": "TEST-SECRET"}, b"TEST-SECRET"), "SAP_AUTHENTICATION_FAILED"),
    ((200, {"Content-Type": "text/html"}, b"<html>TEST-SECRET</html>"), "SAP_INVALID_XML"),
    ((200, {"Content-Type": "text/xml"}, b"plain TEST-SECRET"), "SAP_INVALID_XML"),
    ((200, {"Content-Type": "text/xml"}, b'<!DOCTYPE x [<!ENTITY y "TEST-SECRET">]><x>&y;</x>'), "SAP_UNSAFE_XML"),
    ((200, {"Content-Type": "text/xml"}, b'x' * 1025), "SAP_RESPONSE_TOO_LARGE"),
    ((500, {"Content-Type": "text/html"}, b"TEST-SECRET"), "SAP_HTTP_ERROR"),
])
def test_untrusted_replies_are_rejected_and_sanitized(module, reply, code):
    sender = Sender(module.HttpReply(*reply))
    with pytest.raises(module.SapAccessError) as error:
        module.SoapTransport(config(), sender=sender).fetch_wsdl("RFC_PING")
    assert error.value.code == code
    assert str(error.value) == code and "TEST-SECRET" not in repr(error.value)
    assert len(sender.calls) == 1


@pytest.mark.parametrize("status", [200, 500])
def test_soap_fault_details_are_discarded(module, status):
    fault = f'<s:Envelope xmlns:s="{SOAP}"><s:Body><s:Fault><faultstring>TEST-SECRET</faultstring></s:Fault></s:Body></s:Envelope>'.encode()
    sender = Sender(module.HttpReply(status, {"Content-Type": "text/xml"}, fault))
    with pytest.raises(module.SapAccessError) as error:
        module.SoapTransport(config(), sender=sender).invoke("RFC_PING", envelope(), "http://www.sap.com/RFC_PING")
    assert error.value.code == "SAP_SOAP_FAULT" and "TEST-SECRET" not in str(error.value)


@pytest.mark.parametrize("failure,code,status", [
    (socket.timeout("TEST-SECRET"), "SAP_TIMEOUT", 504),
    (ssl.SSLCertVerificationError("TEST-SECRET"), "SAP_TLS_ERROR", 503),
    (OSError("TEST-SECRET"), "SAP_CONNECTION_FAILED", 503),
    (RuntimeError("TEST-SECRET"), "SAP_TRANSPORT_ERROR", 503),
])
def test_sender_failures_have_safe_codes_and_no_exception_chain(module, failure, code, status):
    sender = Sender(failure)
    with pytest.raises(module.SapAccessError) as error:
        module.SoapTransport(config(), sender=sender).fetch_wsdl("RFC_PING")
    assert (error.value.code, error.value.status, str(error.value)) == (code, status, code)
    assert error.value.__suppress_context__


def test_error_constructor_never_echoes_arbitrary_messages(module):
    error = module.SapAccessError("TEST-SECRET cookie=secret", 999)
    assert str(error) == "SAP_ACCESS_ERROR" and error.status == 503


class Response:
    status = 200

    def __init__(self, body=WSDL, headers=None):
        self.body = body
        self.headers = headers or {"Content-Type": "text/xml"}
        self.reads = []

    def getheaders(self):
        return list(self.headers.items())

    def read(self, size):
        self.reads.append(size)
        return self.body[:size]


def install_connection(monkeypatch, module, response):
    calls = []

    class Connection:
        def __init__(self, host, port, **kwargs):
            calls.append((host, port, kwargs))
            self.closed = False

        def request(self, method, path, body=None, headers=None):
            self.request_args = (method, path, body, headers)

        def getresponse(self):
            return response

        def close(self):
            self.closed = True

    connections = []

    def factory(*args, **kwargs):
        connection = Connection(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(module.http.client, "HTTPSConnection", factory)
    monkeypatch.setattr(module.http.client, "HTTPConnection", factory)
    return calls, connections


def test_direct_https_uses_verified_context_timeout_and_bounded_read(module, monkeypatch):
    response = Response()
    calls, connections = install_connection(monkeypatch, module, response)
    assert module.SoapTransport(config()).fetch_wsdl("RFC_PING") == WSDL
    host, port, kwargs = calls[0]
    assert (host, port, kwargs["timeout"]) == ("sap.example.test", 44310, 7)
    assert kwargs["context"].verify_mode == ssl.CERT_REQUIRED
    assert kwargs["context"].check_hostname is True
    assert response.reads == [1025] and connections[0].closed


def test_direct_response_declared_too_large_is_closed_without_read(module, monkeypatch):
    response = Response(headers={"Content-Type": "text/xml", "Content-Length": "1025"})
    _, connections = install_connection(monkeypatch, module, response)
    with pytest.raises(module.SapAccessError, match="SAP_RESPONSE_TOO_LARGE"):
        module.SoapTransport(config()).fetch_wsdl("RFC_PING")
    assert response.reads == [] and connections[0].closed


def test_direct_oversized_chunked_reply_is_capped_and_closed(module, monkeypatch):
    response = Response(body=b"x" * 2048)
    _, connections = install_connection(monkeypatch, module, response)
    with pytest.raises(module.SapAccessError, match="SAP_RESPONSE_TOO_LARGE"):
        module.SoapTransport(config()).fetch_wsdl("RFC_PING")
    assert response.reads == [1025] and connections[0].closed


def test_direct_redirect_closes_without_read_or_second_request(module, monkeypatch):
    response = Response(headers={"Location": "https://attacker.test/TEST-SECRET"})
    response.status = 307
    calls, connections = install_connection(monkeypatch, module, response)
    with pytest.raises(module.SapAccessError, match="SAP_REDIRECT_BLOCKED"):
        module.SoapTransport(config()).fetch_wsdl("RFC_PING")
    assert len(calls) == 1 and response.reads == [] and connections[0].closed


def test_explicit_ca_bundle_is_used_without_relaxing_tls(module, monkeypatch):
    response = Response()
    calls, _ = install_connection(monkeypatch, module, response)
    ca_paths = []
    context = ssl.create_default_context()

    def create_context(*, cafile=None):
        ca_paths.append(cafile)
        return context

    monkeypatch.setattr(module.ssl, "create_default_context", create_context)
    module.SoapTransport(config(ca_bundle_path="/private/ca.pem")).fetch_wsdl("RFC_PING")
    assert ca_paths == ["/private/ca.pem"]
    assert calls[0][2]["context"].verify_mode == ssl.CERT_REQUIRED


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32"])
def test_wide_encoded_entity_documents_never_reach_parser_or_sender(module, encoding):
    document = '<!DOCTYPE x [<!ENTITY token "TEST-SECRET">]><x>&token;</x>'.encode(encoding)
    sender = Sender(module.HttpReply(200, {"Content-Type": "text/xml"}, document))
    with pytest.raises(module.SapAccessError, match="SAP_INVALID_XML"):
        module.SoapTransport(config(), sender=sender).fetch_wsdl("RFC_PING")


def test_compressed_response_is_rejected_without_decompression(module):
    sender = Sender(module.HttpReply(200, {"Content-Type": "text/xml", "Content-Encoding": "gzip"}, WSDL))
    with pytest.raises(module.SapAccessError, match="SAP_INVALID_XML"):
        module.SoapTransport(config(), sender=sender).fetch_wsdl("RFC_PING")


def test_soap12_fault_is_also_sanitized(module):
    fault = b'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"><s:Body><s:Fault><s:Reason>TEST-SECRET</s:Reason></s:Fault></s:Body></s:Envelope>'
    sender = Sender(module.HttpReply(200, {"Content-Type": "application/soap+xml"}, fault))
    with pytest.raises(module.SapAccessError, match="SAP_SOAP_FAULT"):
        module.SoapTransport(config(), sender=sender).fetch_wsdl("RFC_PING")


def test_direct_incomplete_content_length_is_rejected_and_closed(module, monkeypatch):
    response = Response(headers={"Content-Type": "text/xml", "Content-Length": str(len(WSDL) + 3)})
    _, connections = install_connection(monkeypatch, module, response)
    with pytest.raises(module.SapAccessError, match="SAP_HTTP_ERROR"):
        module.SoapTransport(config()).fetch_wsdl("RFC_PING")
    assert connections[0].closed


def test_direct_read_timeout_is_sanitized_and_connection_closed(module, monkeypatch):
    response = Response()

    def read(size):
        raise socket.timeout("TEST-SECRET")

    response.read = read
    calls, connections = install_connection(monkeypatch, module, response)
    with pytest.raises(module.SapAccessError, match="^SAP_TIMEOUT$"):
        module.SoapTransport(config()).fetch_wsdl("RFC_PING")
    assert len(calls) == 1 and connections[0].closed


def test_explicit_http_test_opt_in_uses_plain_connection_only(module, monkeypatch):
    calls, _ = install_connection(monkeypatch, module, Response())
    assert module.SoapTransport(config(http_scheme="http", http_port=8010, allow_http_test=True)).fetch_wsdl("RFC_PING") == WSDL
    assert calls[0][1] == 8010 and "context" not in calls[0][2]
