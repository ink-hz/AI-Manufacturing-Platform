"""Bounded native HTTP access to fixed, reviewed SAP SOAP RFC interfaces.

Construction is offline. HTTP redirects, proxy environment settings, retries,
advertised WSDL endpoints, and TLS verification overrides are never used.
"""
import base64
from dataclasses import dataclass
import http.client
import socket
import ssl
import xml.etree.ElementTree as ET

from ..sap_connection import KNOWN_SOAP_FUNCTIONS, SapConnectionConfig, _valid_host
from .errors import SapAccessError


SOAP_NAMESPACE = "http://schemas.xmlsoap.org/soap/envelope/"
RFC_NAMESPACE = "urn:sap-com:document:sap:rfc:functions"
SOAP_PATH = "/sap/bc/soap/rfc"
WSDL_PATH = "/sap/bc/soap/wsdl11"
# Only the diagnostic and the fixed scoped business read can be invoked.
READ_CANDIDATE_FUNCTIONS = frozenset({"RFC_PING", "BAPI_MATERIAL_STOCK_REQ_LIST"})
_XML_MEDIA_TYPES = frozenset({"text/xml", "application/xml", "application/soap+xml"})


@dataclass(frozen=True)
class HttpReply:
    status: int
    headers: dict
    body: bytes


def _xml_document(body: bytes, max_bytes: int):
    if not isinstance(body, bytes):
        raise SapAccessError("SAP_INVALID_XML", 502)
    if len(body) > max_bytes:
        raise SapAccessError("SAP_RESPONSE_TOO_LARGE", 502)
    try:
        # Restrict this adapter to UTF-8. This also prevents UTF-16/32 from
        # concealing a DTD from the declaration guard before parsing.
        text = body.decode("utf-8-sig")
    except UnicodeError:
        raise SapAccessError("SAP_INVALID_XML", 502) from None
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise SapAccessError("SAP_UNSAFE_XML", 502)
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, ValueError):
        raise SapAccessError("SAP_INVALID_XML", 502) from None
    if root.tag.rsplit("}", 1)[-1].lower() == "html":
        raise SapAccessError("SAP_INVALID_XML", 502)
    fault_tags = (f"{{{SOAP_NAMESPACE}}}Fault", "{http://www.w3.org/2003/05/soap-envelope}Fault")
    if any(root.tag == tag or root.find(f".//{tag}") is not None for tag in fault_tags):
        raise SapAccessError("SAP_SOAP_FAULT", 502)
    return root


class SoapTransport:
    def __init__(self, config: SapConnectionConfig, sender=None):
        self.config = config
        self._sender = sender if sender is not None else self._send_http

    def _ensure_ready(self):
        config = self.config
        if config.enabled is not True:
            raise SapAccessError("SAP_DISABLED")
        if (
            config.version != 2 or config.transport != "soap_http"
            or config.environment not in {"development", "test"} or config.read_only is not True
            or not config.username or not config.password or not config.allowed_functions
            or config.http_scheme not in {"http", "https"}
            or (config.http_scheme == "http" and config.allow_http_test is not True)
            or not _valid_host(config.application_server)
            or not isinstance(config.client, str) or len(config.client) != 3
            or not config.client.isascii() or not config.client.isdigit()
            or type(config.http_port) is not int or not 1 <= config.http_port <= 65535
            or type(config.timeout_seconds) is not int or not 1 <= config.timeout_seconds <= 30
            or type(config.max_response_bytes) is not int
            or not 1024 <= config.max_response_bytes <= 2 * 1024 * 1024
        ):
            raise SapAccessError("SAP_CONFIGURATION_ERROR")

    def _check_function(self, function: str, *, invocation=False):
        if (
            not isinstance(function, str) or function not in KNOWN_SOAP_FUNCTIONS
            or (invocation and (
                function not in READ_CANDIDATE_FUNCTIONS or function not in self.config.allowed_functions
            ))
        ):
            raise SapAccessError("SAP_FUNCTION_NOT_ALLOWED", 403)

    def fetch_wsdl(self, function: str) -> bytes:
        self._ensure_ready()
        self._check_function(function)
        path = f"{WSDL_PATH}?services={function}&sap-client={self.config.client}"
        return self._request("GET", path, None, {})

    def invoke(self, function: str, envelope: bytes, soap_action: str) -> bytes:
        self._ensure_ready()
        self._check_function(function, invocation=True)
        if soap_action != f"http://www.sap.com/{function}":
            raise SapAccessError("SAP_INVALID_REQUEST", 400)
        root = _xml_document(envelope, self.config.max_response_bytes)
        if root.tag != f"{{{SOAP_NAMESPACE}}}Envelope" or len(root) != 1 or (root.text or "").strip():
            raise SapAccessError("SAP_INVALID_REQUEST", 400)
        body = root[0]
        if (
            body.tag != f"{{{SOAP_NAMESPACE}}}Body" or len(body) != 1
            or body[0].tag != f"{{{RFC_NAMESPACE}}}{function}"
            or (body.text or "").strip() or (body.tail or "").strip()
            or (body[0].tail or "").strip()
        ):
            raise SapAccessError("SAP_INVALID_REQUEST", 400)
        if function == 'BAPI_MATERIAL_STOCK_REQ_LIST':
            from .stock_requirements import envelope as fixed_envelope
            values = {n.tag: n.text or '' for n in body[0]}
            try:
                expected = ET.fromstring(fixed_envelope(values['MATERIAL'], values['PLANT']))
                if ET.tostring(root) != ET.tostring(expected):
                    raise ValueError()
            except Exception:
                raise SapAccessError('SAP_INVALID_REQUEST', 400) from None
        return self._request("POST", f"{SOAP_PATH}?sap-client={self.config.client}", envelope, {
            "Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"{soap_action}"',
        })

    def _request(self, method, path, body, extra_headers):
        credentials = f"{self.config.username}:{self.config.password}".encode("utf-8")
        headers = {
            "Authorization": "Basic " + base64.b64encode(credentials).decode("ascii"),
            "Accept": "text/xml, application/xml", "Accept-Encoding": "identity",
            **extra_headers,
        }
        try:
            reply = self._sender(
                method, path, body, headers, self.config.timeout_seconds, self.config.max_response_bytes,
            )
            return self._validate_reply(reply)
        except SapAccessError:
            raise
        except (socket.timeout, TimeoutError):
            raise SapAccessError("SAP_TIMEOUT", 504) from None
        except ssl.SSLError:
            raise SapAccessError("SAP_TLS_ERROR") from None
        except OSError:
            raise SapAccessError("SAP_CONNECTION_FAILED") from None
        except Exception:
            raise SapAccessError("SAP_TRANSPORT_ERROR") from None

    def _validate_reply(self, reply):
        if not isinstance(reply, HttpReply) or type(reply.status) is not int:
            raise SapAccessError("SAP_TRANSPORT_ERROR")
        if 300 <= reply.status < 400:
            raise SapAccessError("SAP_REDIRECT_BLOCKED", 502)
        if reply.status in {401, 403}:
            raise SapAccessError("SAP_AUTHENTICATION_FAILED")
        headers = {key.lower(): value for key, value in reply.headers.items()}
        media_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if not 200 <= reply.status < 300:
            if media_type in _XML_MEDIA_TYPES:
                try:
                    _xml_document(reply.body, self.config.max_response_bytes)
                except SapAccessError as error:
                    if error.code == "SAP_SOAP_FAULT":
                        raise
            raise SapAccessError("SAP_HTTP_ERROR", 502)
        if media_type not in _XML_MEDIA_TYPES:
            raise SapAccessError("SAP_INVALID_XML", 502)
        if headers.get("content-encoding", "identity").lower().strip() not in {"", "identity"}:
            raise SapAccessError("SAP_INVALID_XML", 502)
        _xml_document(reply.body, self.config.max_response_bytes)
        return reply.body

    def _send_http(self, method, path, body, headers, timeout, max_bytes):
        connection = None
        try:
            if self.config.http_scheme == "https":
                context = ssl.create_default_context(cafile=self.config.ca_bundle_path)
                connection = http.client.HTTPSConnection(
                    self.config.application_server, self.config.http_port, timeout=timeout, context=context,
                )
            else:
                connection = http.client.HTTPConnection(
                    self.config.application_server, self.config.http_port, timeout=timeout,
                )
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            response_headers = dict(response.getheaders())
            if 300 <= response.status < 400:
                raise SapAccessError("SAP_REDIRECT_BLOCKED", 502)
            if response.status in {401, 403}:
                raise SapAccessError("SAP_AUTHENTICATION_FAILED")
            declared_length = None
            for name, value in response_headers.items():
                if name.lower() == "content-length":
                    try:
                        length = int(value)
                    except (ValueError, TypeError):
                        raise SapAccessError("SAP_HTTP_ERROR", 502) from None
                    if length < 0:
                        raise SapAccessError("SAP_HTTP_ERROR", 502)
                    if length > max_bytes:
                        raise SapAccessError("SAP_RESPONSE_TOO_LARGE", 502)
                    if declared_length is not None and declared_length != length:
                        raise SapAccessError("SAP_HTTP_ERROR", 502)
                    declared_length = length
            content = response.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise SapAccessError("SAP_RESPONSE_TOO_LARGE", 502)
            if declared_length is not None and len(content) != declared_length:
                raise SapAccessError("SAP_HTTP_ERROR", 502)
            return HttpReply(response.status, response_headers, content)
        finally:
            if connection is not None:
                connection.close()
