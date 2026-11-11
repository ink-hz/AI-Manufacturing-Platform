"""Offline fixed inventory reads; every wire response and identifier is synthetic."""
from dataclasses import replace
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from .conftest import implementation
from .test_api import BASE, install, private
from .test_cli import cli
from .test_queries import parse, response
from .test_service import FakeTransport, service
from .test_transport import Wire, client

WAREHOUSES = '/orbbec/customCommon/customCommonAction!query.action'
OPTIONS = '/orbbec/appointIssue/appointIssueAction!queryInventoryOptions.action'
FILTERS = {'warehouseNo': 'WAREHOUSE-1', 'itemNo': 'ITEM-1'}
SELECT = ('SELECT VAREHOUSE_NO,VAREHOUSE_NAME FROM W_WAREHOUSE '
          'WHERE SITE=:SITE AND ROWNUM<={limit} ORDER BY VAREHOUSE_NO ASC')


@pytest.fixture
def inventory_config(config):
    return replace(config, allowed_api_paths=(*config.allowed_api_paths, WAREHOUSES, OPTIONS))


def warehouse_response(rows=None, **metadata):
    rows = [{'VAREHOUSE_NO': 'WAREHOUSE-1', 'VAREHOUSE_NAME': 'Synthetic warehouse'}] if rows is None else rows
    return json.dumps({'status': True, 'result': {'MSTATUS': 'S', 'DATA': rows, **metadata}}).encode()


@pytest.mark.parametrize('limit', [1, 2, 5])
def test_warehouses_wire_contains_only_code_owned_site_scoped_bounded_select(inventory_config, limit):
    wire = Wire(); wire.responses.append((200, [], warehouse_response()))
    c = client(inventory_config, wire)
    try:
        c.query('warehouses', {}, page_size=limit)
        method, target, body, headers = wire.calls[-1]
        assert method == 'POST' and target == WAREHOUSES
        assert headers['Content-Type'] == 'application/json'
        assert json.loads(body) == {'querySql': SELECT.format(limit=limit)}
        assert ':SITE' in json.loads(body)['querySql']
        assert len(wire.calls) == 4
    finally:
        c.close()


@pytest.mark.parametrize('filters,page,size', [
    ({'sql': 'SELECT'}, 1, 1), ({'querySql': 'SELECT'}, 1, 1),
    ({'table': 'W_WAREHOUSE'}, 1, 1), ({'columns': 'VAREHOUSE_NO'}, 1, 1),
    ({'SITE': '2000'}, 1, 1), ({'paramJson': '{}'}, 1, 1),
    ({'body': '{}'}, 1, 1), ([], 1, 1), ({}, 2, 1),
    ({}, True, 1), ({}, 1, True), ({}, 1, 6), ({}, 1, 0),
])
def test_warehouse_invalid_inputs_never_even_login(inventory_config, filters, page, size):
    wire = Wire()
    with pytest.raises(Exception) as caught:
        client(inventory_config, wire).query('warehouses', filters, page, size)
    assert caught.value.code == 'MES_INVALID_QUERY'
    assert wire.calls == []


def test_warehouses_honor_stricter_config_row_cap_before_login(inventory_config):
    wire = Wire()
    with pytest.raises(Exception) as caught:
        client(replace(inventory_config, max_rows=2), wire).query('warehouses', page_size=3)
    assert caught.value.code == 'MES_INVALID_QUERY' and not wire.calls


@pytest.mark.parametrize('count', range(6))
def test_warehouse_data_has_unknown_total_even_for_empty_or_full_page(count):
    rows = [{'VAREHOUSE_NO': 'WAREHOUSE-' + str(n)} for n in range(count)]
    result = parse(warehouse_response(rows), 'warehouses', page_size=5)
    assert result == {'rows': rows, 'total_items': None, 'total_items_known': False,
                      'page': 1, 'page_size': 5}


def test_warehouse_does_not_promote_unproven_upstream_count_into_total():
    result = parse(warehouse_response(totalItems=123), 'warehouses')
    assert result['total_items'] is None and result['total_items_known'] is False


@pytest.mark.parametrize('mutation', [
    'too_many', 'bad_row', 'missing_data', 'wrong_page', 'false_status', 'bad_business',
    'secret', 'deep_tree', 'too_many_nodes', 'oversize',
])
def test_warehouse_data_keeps_all_status_shape_and_resource_limits(mutation):
    doc = json.loads(warehouse_response())
    if mutation == 'too_many': doc['result']['DATA'] *= 2
    elif mutation == 'bad_row': doc['result']['DATA'] = [1]
    elif mutation == 'missing_data': del doc['result']['DATA']
    elif mutation == 'wrong_page': doc['result']['pageNumber'] = 2
    elif mutation == 'false_status': doc['status'] = False
    elif mutation == 'bad_business': doc['result']['MSTATUS'] = 'E'
    elif mutation == 'secret': doc['result']['DATA'] = [{'password': 'PRIVATE'}]
    elif mutation == 'deep_tree': doc['result']['DATA'] = [{'a': [[[[[[1]]]]]]}]
    elif mutation == 'too_many_nodes': doc['result']['DATA'] = [{str(n): list(range(100)) for n in range(30)}]
    else: doc['padding'] = 'x' * (2 * 1024 * 1024)
    with pytest.raises(Exception) as caught:
        parse(json.dumps(doc).encode(), 'warehouses')
    assert caught.value.code in {'MES_INVALID_RESPONSE', 'MES_BUSINESS_FAILURE'}


@pytest.mark.parametrize('interface', ['order_materials', 'order_operations', 'material_priority',
    'iqc_records', 'iqc_inspections', 'production_reports', 'inventory_counts', 'inventory_options'])
def test_unknown_total_permission_does_not_escape_warehouses(interface):
    rows_key = 'iqcList' if interface == 'iqc_records' else 'page'
    payload = json.loads(response(rows_key=rows_key))
    del payload['result']['totalItems']
    with pytest.raises(Exception) as caught:
        parse(json.dumps(payload).encode(), interface)
    assert caught.value.code == 'MES_INVALID_RESPONSE'


@pytest.mark.parametrize('filters,page,limit', [(FILTERS, 1, 1),
    ({**FILTERS, 'appointBatch': 'BATCH-1', 'shippingSpace': 'SPACE-1'}, 2, 5)])
def test_inventory_options_exact_six_fields_and_original_paged_response(inventory_config, filters, page, limit):
    wire = Wire(); wire.responses.append((200, [], response(total=10, page=page)))
    c = client(inventory_config, wire)
    try:
        result = parse(c.query('inventory_options', filters, page, limit), 'inventory_options', page, limit)
        method, target, body, headers = wire.calls[-1]
        assert method == 'POST' and body == b''
        assert urlsplit(target).path == OPTIONS
        assert headers['Content-Type'] == 'application/x-www-form-urlencoded'
        params = parse_qs(urlsplit(target).query)
        assert set(params) == {'paramJson'}
        assert json.loads(params['paramJson'][0]) == {
            'warehouseNo': filters['warehouseNo'], 'itemNo': filters['itemNo'],
            'appointBatch': filters.get('appointBatch', ''), 'shippingSpace': filters.get('shippingSpace', ''),
            'pageNumber': page, 'pageLimit': limit}
        assert result['total_items'] == 10 and result['page'] == page
        assert len(wire.calls) == 4
    finally:
        c.close()


@pytest.mark.parametrize('filters', [None, {}, {'warehouseNo': 'WAREHOUSE-1'}, {'itemNo': 'ITEM-1'},
    {**FILTERS, 'warehouseNo': ''}, {**FILTERS, 'itemNo': ''}, {**FILTERS, 'itemNo': ' '},
    {**FILTERS, 'itemNo': '*'}, {**FILTERS, 'warehouseNo': "x' OR 1=1"},
    {**FILTERS, 'querySql': 'SELECT'}, {**FILTERS, 'pageNumber': '1'},
    {**FILTERS, 'shippingSpace': None}, {**FILTERS, 'appointBatch': 'A%'}])
def test_inventory_options_require_nonempty_literals_before_login(inventory_config, filters):
    wire = Wire()
    with pytest.raises(Exception) as caught:
        client(inventory_config, wire).query('inventory_options', filters)
    assert caught.value.code == 'MES_INVALID_QUERY' and not wire.calls


@pytest.mark.parametrize('name', ['warehouses', 'inventory_options'])
def test_new_read_requires_separate_runtime_path_allowlist(config, name):
    wire = Wire()
    with pytest.raises(Exception) as caught:
        client(config, wire).query(name, FILTERS if name == 'inventory_options' else {})
    assert caught.value.code == 'MES_INTERFACE_DENIED' and not wire.calls


@pytest.mark.parametrize('name', ['warehouses', 'inventory_options'])
@pytest.mark.parametrize('count', range(6))
def test_new_reads_service_and_audit_count_actual_rows_only(config_file, raw_config, tmp_path, name, count):
    raw_config['allowed_api_paths'] += [WAREHOUSES, OPTIONS]
    rows = [{'SYNTHETIC_ROW': str(n)} for n in range(count)]
    payload = warehouse_response(rows) if name == 'warehouses' else response(rows, total=count)
    transports = []
    def factory(config):
        t = FakeTransport(config, payload); transports.append(t); return t
    s = service(config_file, tmp_path, factory, raw_config)
    result = s.query(name, FILTERS if name == 'inventory_options' else {}, page_size=5)
    assert result['rows'] == rows and transports[0].closed
    if name == 'warehouses':
        assert result['total_items'] is None and result['total_items_known'] is False
    else:
        assert result['total_items'] == count
    text = (tmp_path / 'audit.json').read_text(); events = json.loads(text)['events']
    assert [e['status'] for e in events] == ['started', 'success']
    assert events[-1]['row_count'] == count and events[-1]['response_bytes'] == len(payload)
    assert 'SYNTHETIC_ROW' not in text and 'querySql' not in text


def test_missing_inventory_filters_fail_before_service_constructs_transport(config_file, raw_config, tmp_path):
    raw_config['allowed_api_paths'].append(OPTIONS)
    s = service(config_file, tmp_path, lambda c: pytest.fail('must not construct transport'), raw_config)
    with pytest.raises(Exception) as caught:
        s.query('inventory_options', {})
    assert caught.value.code == 'MES_INVALID_QUERY'
    assert not (tmp_path / 'audit.json').exists()


def test_metadata_exposes_single_page_unknown_total_without_enabling_new_paths(config_file, tmp_path):
    s = service(config_file, tmp_path, lambda c: pytest.fail('metadata must be offline'))
    entries = {x['interface']: x for x in s.interfaces()['interfaces']}
    assert entries['warehouses']['total_items_known'] is False
    assert entries['warehouses']['max_page'] == 1
    assert entries['inventory_options']['required_filters'] == ['warehouseNo', 'itemNo']
    assert not entries['warehouses']['execution_enabled']
    assert not entries['inventory_options']['execution_enabled']


@pytest.mark.parametrize('name,body', [
    ('warehouses', {'page': 2}), ('warehouses', {'filters': {'querySql': 'SELECT'}}),
    ('warehouses', {'querySql': 'SELECT'}), ('inventory_options', {}),
    ('inventory_options', {'filters': {'warehouseNo': 'WAREHOUSE-1'}}),
    ('inventory_options', {'filters': {**FILTERS, 'itemNo': ''}}),
])
def test_browser_rejects_invalid_new_reads_before_calling_service(name, body):
    browser, s, _, _ = install()
    assert private(browser.post(BASE + '/interfaces/' + name + '/query', json=body)).status_code == 422
    assert not s.calls


@pytest.mark.parametrize('arguments', [
    ['--interface', 'warehouses', '--page', '2'],
    ['--interface', 'warehouses', '--filters', '{"querySql":"SELECT"}'],
    ['--interface', 'inventory_options'],
    ['--interface', 'inventory_options', '--filters', '{"warehouseNo":"WAREHOUSE-1"}'],
])
def test_cli_invalid_new_queries_fail_before_builder(cli, arguments):
    module, calls = cli
    with pytest.raises(SystemExit) as caught:
        module.main(['query', '--live', '--config', '/private/config', '--audit', '/private/audit', *arguments])
    assert caught.value.code == 2 and not calls


def test_cli_projects_unknown_total_as_null_and_omits_rows(cli, monkeypatch, capsys):
    module, _ = cli
    class UnknownTotalService:
        def status(self): pytest.fail('query must not call status')
        def interfaces(self): pytest.fail('query must not call interfaces')
        def diagnose(self, *args): pytest.fail('query must not diagnose')
        def query(self, *args):
            return {'interface': 'warehouses', 'rows': [{'PRIVATE_ROW': 'PRIVATE'}],
                    'total_items': None, 'total_items_known': False, 'page': 1, 'page_size': 1}
    monkeypatch.setattr(module, 'build_mes_access_service', lambda *args: UnknownTotalService())
    assert module.main(['query', '--live', '--interface', 'warehouses',
                        '--config', '/private/config', '--audit', '/private/audit']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['total_items'] is None and output['total_items_known'] is False
    assert output['row_count'] == 1 and 'rows' not in output and 'PRIVATE' not in str(output)
