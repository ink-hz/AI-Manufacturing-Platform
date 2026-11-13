"""Private SAP connection settings. Loading does not import an SDK or make calls."""
from dataclasses import dataclass, field
import ipaddress
import json
import os
import re
import stat


KNOWN_SOAP_FUNCTIONS = frozenset({'RFC_PING', 'ZMMRFC35', 'ZMMRFC78', 'ZPPRFC06', 'ZMMRFC80', 'BAPI_MATERIAL_STOCK_REQ_LIST', 'BAPI_PRODORD_GET_DETAIL'})
_HTTP_FIELDS = frozenset({
    'http_scheme', 'http_port', 'allow_http_test', 'timeout_seconds',
    'max_response_bytes', 'ca_bundle_path',
})


@dataclass(frozen=True)
class SapConnectionConfig:
    version: int
    transport: str
    environment: str
    application_server: str
    system_number: str
    system_id: str
    client: str
    username: str = field(repr=False)
    password: str = field(repr=False)
    enabled: bool
    read_only: bool
    allowed_functions: tuple[str, ...]
    http_scheme: str = 'https'
    http_port: int = 443
    allow_http_test: bool = False
    timeout_seconds: int = 15
    max_response_bytes: int = 2 * 1024 * 1024
    ca_bundle_path: str | None = field(default=None, repr=False)

    def summary(self):
        """Explicit non-secret projection, never a dump of the credential object."""
        return {
            'configuration_valid': True,
            'version': self.version,
            'transport': self.transport,
            'protocol': self.http_scheme if self.transport == 'soap_http' else self.transport,
            'environment': self.environment,
            'application_server': self.application_server,
            'system_number': self.system_number,
            'system_id': self.system_id,
            'client': self.client,
            'enabled': self.enabled,
            'read_only': self.read_only,
            'credentials_configured': bool(self.username and self.password),
            'allowed_function_count': len(self.allowed_functions),
            'authentication_verified': False,
        }


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _valid_host(host):
    if not isinstance(host, str) or not host or len(host) > 253:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return bool(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', host)) and all(
            label and len(label) <= 63 and not label.startswith('-') and not label.endswith('-')
            for label in host.split('.')
        )


def _validate(raw):
    if not isinstance(raw, dict) or type(raw.get('version')) is not int or raw['version'] not in {1, 2}:
        raise ValueError()
    fields = set(SapConnectionConfig.__dataclass_fields__)
    expected = fields - _HTTP_FIELDS if raw['version'] == 1 else fields
    if set(raw) != expected:
        raise ValueError()
    expected_transport = 'rfc' if raw['version'] == 1 else 'soap_http'
    if raw['transport'] != expected_transport or raw['environment'] not in {'development', 'test'}:
        raise ValueError()
    if not _valid_host(raw['application_server']):
        raise ValueError()
    for name, pattern in [('system_number', r'[0-9]{2}'), ('client', r'[0-9]{3}'), ('system_id', r'[A-Z][A-Z0-9]{2}')]:
        if not isinstance(raw[name], str) or not re.fullmatch(pattern, raw[name]):
            raise ValueError()
    if type(raw['enabled']) is not bool or raw['read_only'] is not True:
        raise ValueError()
    if not isinstance(raw['username'], str) or not isinstance(raw['password'], str):
        raise ValueError()
    if raw['username'] and (not raw['username'].strip() or raw['username'] != raw['username'].strip()):
        raise ValueError()
    functions = raw['allowed_functions']
    if (not isinstance(functions, list) or len(functions) > 100
            or any(not isinstance(f, str) or not re.fullmatch(r'(?:/[A-Z0-9_]+/)?[A-Z][A-Z0-9_]{0,63}', f) for f in functions)
            or len(set(functions)) != len(functions)):
        raise ValueError()
    if raw['enabled'] and not (raw['username'] and raw['password'] and functions):
        raise ValueError()
    if raw['version'] == 2:
        if any(function not in KNOWN_SOAP_FUNCTIONS for function in functions):
            raise ValueError()
        if raw['http_scheme'] not in {'http', 'https'} or type(raw['allow_http_test']) is not bool:
            raise ValueError()
        if raw['http_scheme'] == 'http' and raw['allow_http_test'] is not True:
            raise ValueError()
        for name, minimum, maximum in [
            ('http_port', 1, 65535), ('timeout_seconds', 1, 30),
            ('max_response_bytes', 1024, 2 * 1024 * 1024),
        ]:
            if type(raw[name]) is not int or not minimum <= raw[name] <= maximum:
                raise ValueError()
        ca_path = raw['ca_bundle_path']
        if ca_path is not None and (
            not isinstance(ca_path, str) or not os.path.isabs(ca_path) or '\x00' in ca_path
        ):
            raise ValueError()
    return SapConnectionConfig(**{**raw, 'allowed_functions': tuple(functions)})


def load_sap_connection_config(config_path: str) -> SapConnectionConfig:
    """Read a trusted private JSON file; failures never contain settings or secrets."""
    descriptor = None
    try:
        if not isinstance(config_path, str) or not os.path.isabs(config_path):
            raise ValueError()
        descriptor = os.open(config_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid not in {0, os.geteuid()}
                or info.st_mode & 0o077 or info.st_size > 128 * 1024):
            raise ValueError()
        with os.fdopen(descriptor, 'r', encoding='utf-8') as stream:
            descriptor = None
            text = stream.read(128 * 1024 + 1)
        if len(text.encode('utf-8')) > 128 * 1024:
            raise ValueError()
        return _validate(json.loads(text, object_pairs_hook=_unique_keys))
    except Exception:
        raise ValueError('invalid SAP connection configuration') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
