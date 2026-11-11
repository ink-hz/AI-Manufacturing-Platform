from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from .conftest import SECRET, implementation
from .test_queries import response


def service(config_file, tmp_path, factory, raw_config=None):
    return implementation('mes_access.service').MesAccessService(
        config_file(raw_config), str(tmp_path/'audit.json'), transport_factory=factory)


class FakeTransport:
    def __init__(self, config, payload=None, error=None):
        self.config = config
        self.payload = response() if payload is None else payload
        self.error = error
        self.response_bytes = 0
        self.closed = False
        self.calls = []
    def login(self):
        self.calls.append('login')
        if self.error:
            raise self.error
        return {'authentication_verified': True, 'site_code': self.config.site_code, 'source': 'native_mes'}
    def query(self, *args):
        self.calls.append(args)
        if self.error:
            raise self.error
        self.response_bytes += len(self.payload)
        return self.payload
    def close(self):
        self.closed = True


def test_constructor_is_lazy_and_status_interfaces_never_construct_transport(tmp_path):
    cls = implementation('mes_access.service').MesAccessService
    calls = []
    s = cls('/absent/mes.json', str(tmp_path/'audit.json'), transport_factory=lambda c: calls.append(c))
    assert not list(tmp_path.iterdir()) and not calls
    with pytest.raises(Exception) as caught:
        s.status()
    assert caught.value.code == 'MES_CONFIGURATION_ERROR' and not calls


def test_metadata_is_secret_safe_and_does_not_claim_authentication(config_file, tmp_path):
    s = service(config_file, tmp_path, lambda c: pytest.fail('metadata must not construct transport'))
    assert s.status()['authentication_verified'] is False
    assert s.status()['business_query_succeeded'] is False
    interfaces = s.interfaces()['interfaces']
    assert len(interfaces) == 10
    unconfigured = {'iqc_inspections', 'iqc_receive', 'warehouses', 'inventory_options'}
    assert all(x['execution_enabled'] for x in interfaces if x['interface'] not in unconfigured)
    assert all(not x['execution_enabled'] for x in interfaces if x['interface'] in unconfigured)
    assert all('ignoreflag' not in x['filters'] for x in interfaces)
    assert SECRET not in json.dumps(s.status())


def test_intent_is_durable_before_factory_and_rows_never_persist(config_file, tmp_path):
    transports = []
    audit = tmp_path/'audit.json'
    def factory(config):
        events = json.loads(audit.read_text())['events']
        assert events[-1]['status'] == 'started' and events[-1]['operation'] == 'query'
        t = FakeTransport(config, response([{'SHOP_ORDER': 'BUSINESS-PRIVATE-ROW'}]))
        transports.append(t)
        return t
    s = service(config_file, tmp_path, factory)
    result = s.query('order_materials', {'shopOrder': 'FILTER-PRIVATE'}, actor_id='ACTOR-PRIVATE')
    assert result['rows'] == [{'SHOP_ORDER': 'BUSINESS-PRIVATE-ROW'}]
    assert result['total_items'] == result['page'] == result['page_size'] == 1
    assert result['authentication_verified'] and result['business_query_succeeded']
    assert result['business_data_verified'] is False and result['business_reconciled'] is False
    assert transports[0].closed
    text = audit.read_text()
    assert not any(x in text for x in [SECRET, 'test-user', 'ACTOR-PRIVATE', 'FILTER-PRIVATE', 'BUSINESS-PRIVATE-ROW', 'SHOP_ORDER'])
    events = json.loads(text)['events']
    assert [e['status'] for e in events] == ['started', 'success']
    assert events[-1]['row_count'] == 1 and 'row_count' not in events[0]
    assert events[0]['request_id'] == result['request_id']
    assert s.status()['authentication_verified'] and s.status()['business_query_succeeded']
    assert 'binding' not in json.dumps(s.status())
    assert audit.stat().st_mode & 0o777 == 0o600


def test_diagnose_verifies_login_without_query_or_business_claim(config_file, tmp_path):
    transports = []
    def factory(c):
        t = FakeTransport(c); transports.append(t); return t
    s = service(config_file, tmp_path, factory)
    result = s.diagnose('actor')
    assert result['authentication_verified'] is True and result['business_data_verified'] is False
    assert transports[0].calls == ['login'] and transports[0].closed
    assert s.status()['authentication_verified'] and not s.status()['business_data_verified']


@pytest.mark.parametrize('mutation', ['missing-parent', 'symlink', 'hardlink', 'public', 'corrupt', 'lock-symlink'])
def test_audit_failure_prevents_transport_construction(config_file, tmp_path, mutation):
    calls = []
    audit = tmp_path/'audit.json'
    if mutation == 'symlink':
        other = tmp_path/'other'; other.write_text('private'); audit.symlink_to(other)
    elif mutation == 'hardlink':
        audit.write_text('{}'); os.chmod(audit, 0o600); os.link(audit, tmp_path/'other')
    elif mutation == 'public':
        audit.write_text('{}'); os.chmod(audit, 0o644)
    elif mutation == 'corrupt':
        audit.write_text('private'); os.chmod(audit, 0o600)
    elif mutation == 'lock-symlink':
        (tmp_path/'audit.json.lock').symlink_to(tmp_path/'absent')
    s = service(config_file, tmp_path, lambda c: calls.append(c))
    if mutation == 'missing-parent':
        s.audit_path = str(tmp_path/'absent'/'audit.json')
    with pytest.raises(Exception) as caught:
        s.query('order_materials', actor_id='actor')
    assert caught.value.code == 'MES_AUDIT_UNAVAILABLE' and not calls


@pytest.mark.parametrize('operation', ['diagnose', 'query'])
def test_disabled_config_prevents_transport_construction(config_file, raw_config, tmp_path, operation):
    raw_config['enabled'] = False
    calls = []
    s = service(config_file, tmp_path, lambda c: calls.append(c), raw_config)
    with pytest.raises(Exception) as caught:
        if operation == 'diagnose': s.diagnose('actor')
        else: s.query('order_materials', actor_id='actor')
    assert caught.value.code == 'MES_DISABLED' and not calls
    assert not s.status()['authentication_verified']


@pytest.mark.parametrize('interface,filters', [('save', {}), ('order_materials', {'sql': 'SELECT'}), ('material_priority', {'ignoreflag': 'true'})])
def test_service_has_its_own_query_policy_before_transport(config_file, tmp_path, interface, filters):
    calls = []
    s = service(config_file, tmp_path, lambda c: calls.append(c))
    with pytest.raises(Exception) as caught:
        s.query(interface, filters, actor_id='actor')
    assert caught.value.code in {'MES_INTERFACE_DENIED', 'MES_INVALID_QUERY'} and not calls


def test_service_config_allowlist_is_enforced(config_file, raw_config, tmp_path):
    raw_config['allowed_api_paths'] = []
    s = service(config_file, tmp_path, lambda c: pytest.fail('must not construct'), raw_config)
    with pytest.raises(Exception) as caught:
        s.query('order_materials', actor_id='actor')
    assert caught.value.code == 'MES_INTERFACE_DENIED'
    assert not any(x['execution_enabled'] for x in s.interfaces()['interfaces'])


@pytest.mark.parametrize('failure', ['parser', 'login', 'factory'])
def test_failures_are_redacted_audited_and_transport_closed(config_file, tmp_path, failure):
    transports = []
    def factory(c):
        if failure == 'factory': raise RuntimeError(SECRET)
        t = FakeTransport(c, payload=b'private-body', error=RuntimeError(SECRET) if failure == 'login' else None)
        transports.append(t); return t
    s = service(config_file, tmp_path, factory)
    with pytest.raises(Exception) as caught:
        if failure == 'login': s.diagnose('actor')
        else: s.query('order_materials', actor_id='actor')
    assert caught.value.code in {'MES_OPERATION_FAILED', 'MES_INVALID_RESPONSE'}
    assert SECRET not in str(caught.value)
    assert all(t.closed for t in transports)
    events = json.loads((tmp_path/'audit.json').read_text())['events']
    assert [e['status'] for e in events] == ['started', 'failed']
    assert not s.status()['authentication_verified']
    assert SECRET not in json.dumps(events) and 'private-body' not in json.dumps(events)


def test_config_fingerprint_invalidates_prior_evidence(config_file, raw_config, tmp_path):
    s = service(config_file, tmp_path, FakeTransport)
    s.query('order_materials', actor_id='actor')
    assert s.status()['business_query_succeeded']
    raw_config['password'] = 'changed-test-secret'; config_file(raw_config)
    assert not s.status()['authentication_verified'] and not s.status()['business_query_succeeded']
    assert not any(x['business_query_succeeded'] for x in s.interfaces()['interfaces'])


def test_concurrent_queries_use_isolated_closed_transports_and_atomic_audit(config_file, tmp_path):
    transports = []
    def factory(c):
        t = FakeTransport(c); transports.append(t); return t
    s = service(config_file, tmp_path, factory)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda n: s.query('order_materials', actor_id=str(n)), range(12)))
    assert len(transports) == 12 and len({r['request_id'] for r in results}) == 12
    assert all(t.closed and len(t.calls) == 1 for t in transports)
    events = json.loads((tmp_path/'audit.json').read_text())['events']
    assert len(events) == 24


def test_audit_store_bounds_retention_and_rejects_arbitrary_data(tmp_path):
    store = implementation('mes_access.store').MesAuditStore(str(tmp_path/'audit.json'))
    event = {'request_id': str(uuid4()), 'operation': 'query', 'function': 'order_materials',
             'timestamp': datetime.now(timezone.utc).isoformat(), 'status': 'started',
             'actor_hash': 'a'*64, 'binding': 'b'*64}
    for _ in range(1005): store.record(event)
    assert len(store.read()['events']) == 1000
    for mutation in [dict(event, rows=[{'secret': 'private'}]), dict(event, actor_hash='raw-identity'), dict(event, function='save'), dict(event, row_count=6), dict(event, row_count=True)]:
        with pytest.raises(Exception) as caught: store.record(mutation)
        assert caught.value.code == 'MES_AUDIT_UNAVAILABLE'


@pytest.mark.parametrize('audit_target', ['config', 'lock'])
def test_audit_cannot_overwrite_configuration(config_file, tmp_path, audit_target):
    path = config_file()
    s = implementation('mes_access.service').MesAccessService(path, path if audit_target == 'config' else path.removesuffix('.json'))
    if audit_target == 'lock':
        s.config_path = s.audit_path + '.lock'
        Path(s.config_path).write_bytes(Path(path).read_bytes()); os.chmod(s.config_path, 0o600)
    with pytest.raises(Exception) as caught: s.diagnose('actor')
    assert caught.value.code == 'MES_CONFIGURATION_ERROR'


def test_real_transport_parser_store_service_path_with_offline_wire(config_file, tmp_path):
    from .test_transport import Wire
    transport_module = implementation('mes_access.transport')
    transports, wires = [], []
    def factory(c):
        wire = Wire(); wire.responses.append((200, [], response([{'CREATE_DATE': {'year': 126, 'month': 10}}])))
        t = transport_module.SessionTransport(c, requester=wire)
        wires.append(wire); transports.append(t); return t
    s = service(config_file, tmp_path, factory)
    result = s.query('order_materials', actor_id='actor')
    assert result['rows'] == [{'CREATE_DATE': {'year': 126, 'month': 10}}]
    assert len(wires[0].calls) == 4 and not transports[0].authenticated
    assert s.status()['business_query_succeeded'] is True


def test_completion_audit_failure_suppresses_results_and_cleans_transport(config_file, tmp_path, monkeypatch):
    module = implementation('mes_access.service')
    real_store = module.MesAuditStore
    transports = []
    class FailingCompletionStore(real_store):
        def record(self, event):
            if event['status'] == 'success':
                raise implementation('mes_access.errors').MesAccessError('MES_AUDIT_UNAVAILABLE')
            return super().record(event)
    monkeypatch.setattr(module, 'MesAuditStore', FailingCompletionStore)
    def factory(c):
        t = FakeTransport(c); transports.append(t); return t
    s = service(config_file, tmp_path, factory)
    with pytest.raises(Exception) as caught:
        s.query('order_materials', actor_id='actor')
    assert caught.value.code == 'MES_AUDIT_UNAVAILABLE' and transports[0].closed
    assert [e['status'] for e in json.loads((tmp_path/'audit.json').read_text())['events']] == ['started']
    assert not s.status()['business_query_succeeded']
