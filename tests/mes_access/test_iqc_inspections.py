"""Offline current IQC source contract and tightly scoped inspector field policy."""
from dataclasses import replace
import json

import pytest

from .conftest import implementation
from .test_queries import parse, response
from .test_service import service
from .test_transport import Wire, client

PATH = '/orbbec/iqcInspection/iqcInspectionAction!query.action'
FILTERS = ('date_start', 'date_end', 'item_no', 'vender', 'status', 'result')


@pytest.fixture
def iqc_config(config):
    return replace(config, allowed_api_paths=(*config.allowed_api_paths, PATH))


def test_registry_has_fixed_current_iqc_encoding_and_public_filters():
    registry = implementation('mes_access.registry').INTERFACES
    assert registry['iqc_inspections'].path == PATH
    assert registry['iqc_inspections'].filters == FILTERS
    assert registry['iqc_inspections'].encoding == 'json_body'
    assert all(spec.encoding == 'param_json_url' for name, spec in registry.items()
               if name not in {'iqc_inspections', 'warehouses'})


@pytest.mark.parametrize('filters,page,size', [({}, 1, 1), (
    {'date_start': '2026-11-01', 'date_end': '2026-11-11', 'item_no': 'ITEM-1',
     'vender': 'VENDOR-1', 'status': 'S', 'result': 'PASS'}, 2, 5)])
def test_current_iqc_wire_is_single_fixed_json_body(iqc_config, filters, page, size):
    wire = Wire(); wire.responses.append((200, [], response(total=10, page=page)))
    c = client(iqc_config, wire)
    try:
        assert c.query('iqc_inspections', filters, page, size) == response(total=10, page=page)
        method, target, body, headers = wire.calls[-1]
        assert method == 'POST' and target == PATH
        assert headers['Content-Type'] == 'application/json'
        assert json.loads(body) == {**dict.fromkeys(FILTERS, ''), **filters,
            'checkBox': '', 'pageNumber': page, 'pageLimit': size}
        assert len(wire.calls) == 4
        assert wire.calls[1][3]['Content-Type'] == 'application/x-www-form-urlencoded'
    finally:
        c.close()


@pytest.mark.parametrize('filters', [
    {'date_start': '2026-02-30'}, {'date_end': '2026-1-01'},
    {'date_start': '2026-11-11', 'date_end': '2026-11-01'},
    {'date_start': 20261101}, {'date_end': '2026-11-01T00:00:00'},
    {'checkBox': ''}, {'checkBox': 'true'}, {'username': 'person'},
    {'IQC_NO': 'IQC-1'}, {'item_no': '*'}, {'vender': "x' OR 1=1"},
    {'status': None}, {'result': 'x' * 129}, {'url': 'https://evil.test'},
])
def test_current_iqc_invalid_filters_fail_before_login(iqc_config, filters):
    wire = Wire()
    with pytest.raises(Exception) as caught:
        client(iqc_config, wire).query('iqc_inspections', filters)
    assert caught.value.code == 'MES_INVALID_QUERY'
    assert not wire.calls


def test_current_iqc_config_allowlist_required_at_transport_and_service(config, config_file, tmp_path):
    wire = Wire()
    with pytest.raises(Exception) as caught:
        client(config, wire).query('iqc_inspections')
    assert caught.value.code == 'MES_INTERFACE_DENIED' and not wire.calls
    s = service(config_file, tmp_path, lambda c: pytest.fail('must not construct transport'))
    with pytest.raises(Exception) as caught:
        s.query('iqc_inspections')
    assert caught.value.code == 'MES_INTERFACE_DENIED'
    entry = next(x for x in s.interfaces()['interfaces'] if x['interface'] == 'iqc_inspections')
    assert not entry['execution_enabled'] and entry['filters'] == list(FILTERS)


@pytest.mark.parametrize('inspector', ['INSPECTOR-SYNTHETIC', '', '检验员', None])
def test_current_iqc_direct_record_allows_only_business_username(inspector):
    row = {'USERNAME': inspector, 'ITEM_NO': 'ITEM-1'}
    assert parse(response([row]), 'iqc_inspections')['rows'] == [row]


@pytest.mark.parametrize('value', [1, True, [], {}, {'name': 'INSPECTOR-SYNTHETIC'}])
def test_current_iqc_business_username_rejects_non_string_non_null(value):
    with pytest.raises(Exception) as caught:
        parse(response([{'USERNAME': value}]), 'iqc_inspections')
    assert caught.value.code == 'MES_INVALID_RESPONSE'


@pytest.mark.parametrize('key', ['username', 'Username', 'USER_NAME', 'USERNAME_EXTRA',
    'PASSWORD', 'passwd', 'pwd', 'secret', 'token', 'Cookie', 'Authorization', 'JSESSIONID'])
def test_current_iqc_still_denies_all_other_sensitive_record_keys(key):
    with pytest.raises(Exception) as caught:
        parse(response([{key: 'private'}]), 'iqc_inspections')
    assert caught.value.code == 'MES_INVALID_RESPONSE' and 'private' not in str(caught.value)


@pytest.mark.parametrize('location', ['root', 'result', 'nested_object', 'nested_list', 'other_list'])
def test_current_iqc_username_exception_does_not_escape_direct_page_record(location):
    payload = json.loads(response())
    if location == 'root': payload['USERNAME'] = 'private'
    elif location == 'result': payload['result']['USERNAME'] = 'private'
    elif location == 'nested_object': payload['result']['page'] = [{'details': {'USERNAME': 'private'}}]
    elif location == 'nested_list': payload['result']['page'] = [{'details': [{'USERNAME': 'private'}]}]
    else: payload['result']['other'] = [{'USERNAME': 'private'}]
    with pytest.raises(Exception) as caught:
        parse(json.dumps(payload).encode(), 'iqc_inspections')
    assert caught.value.code == 'MES_INVALID_RESPONSE'


@pytest.mark.parametrize('interface,rows_key', [
    ('order_materials', 'page'), ('order_operations', 'page'), ('material_priority', 'page'),
    ('iqc_records', 'iqcList'), ('production_reports', 'page'), ('inventory_counts', 'page')])
def test_other_interfaces_still_reject_uppercase_username(interface, rows_key):
    with pytest.raises(Exception) as caught:
        parse(response([{'USERNAME': 'private'}], rows_key=rows_key), interface)
    assert caught.value.code == 'MES_INVALID_RESPONSE'


@pytest.mark.parametrize('mutation', ['over_rows', 'missing_page', 'business_failure', 'oversized_name'])
def test_current_iqc_keeps_response_bounds_and_business_contract(mutation):
    payload = json.loads(response([{'USERNAME': 'INSPECTOR-SYNTHETIC'}]))
    if mutation == 'over_rows':
        payload['result']['page'] *= 2
        payload['result']['totalItems'] = 2
    elif mutation == 'missing_page': del payload['result']['pageNumber']
    elif mutation == 'business_failure': payload['result']['MSTATUS'] = 'E'
    else: payload['result']['page'][0]['USERNAME'] = 'x' * 4097
    with pytest.raises(Exception) as caught:
        parse(json.dumps(payload).encode(), 'iqc_inspections')
    assert caught.value.code == ('MES_BUSINESS_FAILURE' if mutation == 'business_failure' else 'MES_INVALID_RESPONSE')


def test_current_iqc_service_wire_parser_and_durable_audit(config_file, raw_config, tmp_path):
    raw_config['allowed_api_paths'].append(PATH)
    wire = Wire(); wire.responses.append((200, [], response([{'USERNAME': 'INSPECTOR-SYNTHETIC'}])))
    transports = []
    def factory(config):
        events = json.loads((tmp_path / 'audit.json').read_text())['events']
        assert events[-1]['status'] == 'started'
        c = client(config, wire); transports.append(c); return c
    s = service(config_file, tmp_path, factory, raw_config)
    result = s.query('iqc_inspections', {'item_no': 'ITEM-PRIVATE'}, actor_id='actor')
    assert result['rows'] == [{'USERNAME': 'INSPECTOR-SYNTHETIC'}]
    assert result['business_query_succeeded'] and not result['business_data_verified']
    assert len(wire.calls) == 4 and wire.calls[-1][1] == PATH
    assert not transports[0].authenticated
    audit = (tmp_path / 'audit.json').read_text()
    events = json.loads(audit)['events']
    assert [event['status'] for event in events] == ['started', 'success']
    assert all(event['function'] == 'iqc_inspections' for event in events)
    assert events[-1]['row_count'] == 1
    assert 'USERNAME' not in audit and 'INSPECTOR-SYNTHETIC' not in audit and 'ITEM-PRIVATE' not in audit


@pytest.mark.parametrize('status,body,code', [
    (302, b'', 'MES_SESSION_EXPIRED'), (401, b'', 'MES_SESSION_EXPIRED'),
    (500, b'private', 'MES_INVALID_RESPONSE'),
    (200, b'x' * 65537, 'MES_RESPONSE_TOO_LARGE'),
])
def test_current_iqc_transport_failure_closes_without_retry(iqc_config, status, body, code):
    wire = Wire(); wire.responses.append((status, [], body))
    c = client(iqc_config, wire)
    with pytest.raises(Exception) as caught:
        c.query('iqc_inspections')
    assert caught.value.code == code
    assert len(wire.calls) == 4 and not c.authenticated and c._cookie is None


@pytest.mark.parametrize('filters', [{'checkBox': ''}, {'date_start': '2026-02-30'}])
def test_current_iqc_service_rejects_filters_before_transport(config_file, raw_config, tmp_path, filters):
    raw_config['allowed_api_paths'].append(PATH)
    s = service(config_file, tmp_path, lambda c: pytest.fail('must not construct transport'), raw_config)
    with pytest.raises(Exception) as caught:
        s.query('iqc_inspections', filters)
    assert caught.value.code == 'MES_INVALID_QUERY'
    assert not (tmp_path / 'audit.json').exists()


def test_current_iqc_browser_route_accepts_only_public_filter_names():
    from .test_api import BASE, install, private
    browser, s, _, _ = install()
    route = BASE + '/interfaces/iqc_inspections/query'
    assert private(browser.post(route, json={'filters': {'item_no': 'ITEM-1'}})).status_code == 200
    assert s.calls == [('query', 'iqc_inspections', {'item_no': 'ITEM-1'}, 1, 1, 'admin-1')]
    s.calls.clear()
    assert private(browser.post(route, json={'filters': {'checkBox': ''}})).status_code == 422
    assert not s.calls
