import json
from pathlib import Path

import pytest

from manufacturing_platform.sap_access.contracts import parse_wsdl
from manufacturing_platform.sap_access.errors import SapAccessError
from manufacturing_platform.sap_access.service import SapAccessService
from manufacturing_platform.sap_access.store import SapAuditStore


WSDL = b'''<definitions xmlns="http://schemas.xmlsoap.org/wsdl/" xmlns:s="http://schemas.xmlsoap.org/wsdl/soap/" xmlns:x="http://www.w3.org/2001/XMLSchema" xmlns:t="urn:sap-com:document:sap:rfc:functions" targetNamespace="urn:sap-com:document:sap:rfc:functions"><types><x:schema targetNamespace="urn:sap-com:document:sap:rfc:functions"><x:element name="RFC_PING"><x:complexType><x:all/></x:complexType></x:element><x:element name="RFC_PING.Response"><x:complexType><x:all/></x:complexType></x:element></x:schema></types><message name="In"><part name="parameters" element="t:RFC_PING"/></message><message name="Out"><part name="parameters" element="t:RFC_PING.Response"/></message><portType name="Port"><operation name="RFC_PING"><input message="t:In"/><output message="t:Out"/></operation></portType><binding name="Binding" type="t:Port"><s:binding style="document" transport="http://schemas.xmlsoap.org/soap/http"/><operation name="RFC_PING"><s:operation soapAction="http://www.sap.com/RFC_PING"/><input><s:body use="literal"/></input><output><s:body use="literal"/></output></operation></binding><service name="Service"><port name="Port" binding="t:Binding"><s:address location="http://example.invalid/sap/bc/soap/rfc"/></port></service></definitions>'''
PING = b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><n:RFC_PING.Response xmlns:n="urn:sap-com:document:sap:rfc:functions"/></s:Body></s:Envelope>'


def config_file(tmp_path):
    p = tmp_path / 'config.json'
    p.write_text(json.dumps(dict(version=2, transport='soap_http', environment='test',
        application_server='example.invalid', system_number='10', system_id='S4D', client='300',
        username='secret-user', password='secret-password', enabled=True, read_only=True,
        allowed_functions=['RFC_PING'], http_scheme='http', http_port=8010, allow_http_test=True,
        timeout_seconds=10, max_response_bytes=2097152, ca_bundle_path=None)))
    p.chmod(0o600)
    return str(p)


class FakeTransport:
    calls = []
    reply = PING

    def __init__(self, config):
        pass

    def fetch_wsdl(self, function):
        self.calls.append(('wsdl', function))
        if function != 'RFC_PING':
            raise SapAccessError('SAP_INVALID_XML')
        return WSDL

    def invoke(self, function, envelope, action):
        self.calls.append(('invoke', function))
        assert b'RFC_PING' in envelope
        return self.reply


@pytest.fixture
def service(tmp_path):
    FakeTransport.calls = []
    FakeTransport.reply = PING
    return SapAccessService(config_file(tmp_path), str(tmp_path / 'audit.json'), transport_factory=FakeTransport)


def test_contract_uses_exact_current_binding_and_never_follows_advertised_address():
    result = parse_wsdl('RFC_PING', WSDL)
    assert result['soap_action'] == 'http://www.sap.com/RFC_PING'
    assert result['request_fields'] == []
    assert len(result['digest']) == 64


@pytest.mark.parametrize('payload', [b'<html/>', WSDL.replace(b'http://www.sap.com/RFC_PING', b'http://attacker/'),
    WSDL.replace(b't:RFC_PING.Response', b't:Other'),
    b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + WSDL,
    WSDL.replace(b'<x:all/>', b'<x:sequence><x:element name="x" type="t:Missing"/></x:sequence>', 1)])
def test_contract_rejects_wrong_or_unsafe_metadata(payload):
    with pytest.raises(SapAccessError):
        parse_wsdl('RFC_PING', payload)


def test_descriptor_expansion_has_a_global_budget():
    types = '<x:complexType name="T0"><x:sequence><x:element name="leaf" type="x:string"/></x:sequence></x:complexType>'
    for level in range(1, 7):
        children = ''.join(f'<x:element name="f{i}" type="t:T{level-1}"/>' for i in range(4))
        types += f'<x:complexType name="T{level}"><x:sequence>{children}</x:sequence></x:complexType>'
    payload = WSDL.replace(b'</x:schema>', types.encode()+b'</x:schema>')
    payload = payload.replace(b'<x:all/>', b'<x:sequence><x:element name="tree" type="t:T6"/></x:sequence>', 1)
    with pytest.raises(SapAccessError):
        parse_wsdl('RFC_PING', payload)


@pytest.mark.parametrize('field', [
    '<x:element type="x:string"/>',
    '<x:element name="bad name" type="x:string"/>',
    '<x:element name="X" type="x:unknownType"/>',
    '<x:element name="X" type="x:string" minOccurs="-4"/>',
    '<x:element name="X" type="x:string" maxOccurs="arbitrary-text"/>',
    '<x:element name="X" type="x:string"/><x:element name="X" type="x:string"/>',
])
def test_contract_rejects_malformed_fields(field):
    payload = WSDL.replace(b'<x:all/>', ('<x:sequence>'+field+'</x:sequence>').encode(), 1)
    with pytest.raises(SapAccessError):
        parse_wsdl('RFC_PING', payload)


@pytest.mark.parametrize('address', ['http://user:password@example.invalid/sap/bc/soap/rfc',
    'http://example.invalid/sap/bc/soap/rfc?token=secret', 'javascript:alert(1)'])
def test_contract_never_caches_url_credentials_or_tokens(address):
    with pytest.raises(SapAccessError):
        parse_wsdl('RFC_PING', WSDL.replace(b'http://example.invalid/sap/bc/soap/rfc', address.encode()))


def test_table_cardinality_and_decimal_precision_are_retained():
    field = b'''<x:sequence><x:element name="ROWS"><x:complexType><x:sequence><x:element name="item" minOccurs="0" maxOccurs="unbounded"><x:complexType><x:sequence><x:element name="AMOUNT" minOccurs="0"><x:simpleType><x:restriction base="x:decimal"><x:totalDigits value="23"/><x:fractionDigits value="2"/></x:restriction></x:simpleType></x:element></x:sequence></x:complexType></x:element></x:sequence></x:complexType></x:element></x:sequence>'''
    d = parse_wsdl('RFC_PING', WSDL.replace(b'<x:all/>', field, 1))
    table = d['request_fields'][0]
    assert table['required'] and table['table']
    row = table['fields'][0]
    assert row['min_occurs'] == 0 and row['max_occurs'] == 'unbounded'
    amount = row['fields'][0]
    assert amount['total_digits'] == 23 and amount['fraction_digits'] == 2
    assert amount['required'] is False


def test_auth_failure_stops_refresh_instead_of_repeating_credentials(service):
    class Rejected(FakeTransport):
        def fetch_wsdl(self, function):
            self.calls.append(('wsdl', function))
            raise SapAccessError('SAP_AUTHENTICATION_FAILED', 502)
    service.transport_factory = Rejected
    with pytest.raises(SapAccessError):
        service.refresh_contracts('admin')
    assert FakeTransport.calls == [('wsdl', 'RFC_PING')]


@pytest.mark.parametrize('payload', [
    PING.replace(b'</s:Envelope>', b'<s:Body/></s:Envelope>'),
    PING.replace(b'<s:Body>', b'<s:Body>unexpected-text'),
    PING.replace(b'xmlns:n=', b'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true" xmlns:n='),
    PING.replace(b'</s:Body>', b'unexpected-tail</s:Body>'),
    PING.replace(b'<s:Body>', b'unexpected-envelope-text<s:Body>'),
    PING.replace(b'</s:Body>', b'</s:Body>unexpected-envelope-tail'),
    PING.replace(b'<s:Body>', b'<s:Header/><s:Header/><s:Body>'),
    PING.replace(b'</s:Envelope>', b'<s:Header/></s:Envelope>'),
])
def test_ping_rejects_ambiguous_response_shapes(payload):
    from manufacturing_platform.sap_access.contracts import validate_ping
    with pytest.raises(SapAccessError):
        validate_ping(payload)


def test_cached_status_is_offline_and_ping_is_not_business_verification(service):
    assert service.status()['authentication_verified'] is False
    assert not FakeTransport.calls
    result = service.ping('admin')
    assert result['authentication_verified'] is True
    assert result['business_data_verified'] is False
    assert service.status()['authentication_verified'] is True
    assert service.contract('RFC_PING')['function'] == 'RFC_PING'
    assert FakeTransport.calls == [('wsdl', 'RFC_PING'), ('invoke', 'RFC_PING')]
    text = Path(service.audit_path).read_text()
    assert 'secret-user' not in text and 'secret-password' not in text
    assert '<s:Envelope' not in text


def test_metadata_partial_success_does_not_claim_business_ready(service):
    result = service.refresh_contracts('admin')
    assert result['successful'] == ['RFC_PING']
    assert len(result['failed']) == 5
    assert result['business_data_verified'] is False


def test_nonempty_or_wrong_ping_response_is_rejected_and_audited(service):
    FakeTransport.reply = PING.replace(b'RFC_PING.Response', b'ZMMRFC35.Response')
    with pytest.raises(SapAccessError):
        service.ping('admin')
    assert service.status()['authentication_verified'] is False
    assert 'SAP_INVALID_RESPONSE' in Path(service.audit_path).read_text()


def test_configuration_change_invalidates_previous_success(service):
    service.ping('admin')
    p = Path(service.config_path)
    raw = json.loads(p.read_text())
    raw['password'] = 'rotated-password'
    p.write_text(json.dumps(raw))
    assert service.status()['authentication_verified'] is False
    with pytest.raises(SapAccessError):
        service.contract('RFC_PING')


def test_all_business_functions_remain_closed_without_network(service):
    for fn in ['ZMMRFC35', 'ZMMRFC78', 'ZPPRFC06', 'ZMMRFC80']:
        item = next(i for i in service.interfaces()['interfaces'] if i['function'] == fn)
        assert item['execution_enabled'] is False
        assert item['blocking_reasons']
    with pytest.raises(SapAccessError):
        service.contract('EVIL')
    assert not FakeTransport.calls


def test_audit_store_rejects_symlinks_and_credential_collision(tmp_path):
    config = config_file(tmp_path)
    with pytest.raises(SapAccessError):
        SapAccessService(config, config).status()
    target = tmp_path / 'linked.json'
    target.symlink_to(config)
    with pytest.raises(SapAccessError):
        SapAuditStore(str(target)).read()


def test_audit_failure_prevents_network(service):
    Path(service.audit_path).write_text('{}')
    Path(service.audit_path).chmod(0o644)
    with pytest.raises(SapAccessError):
        service.ping('admin')
    assert not FakeTransport.calls
