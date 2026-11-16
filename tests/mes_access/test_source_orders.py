"""Offline contract tests for the fixed MES identity observation."""
import json
import pytest
from .conftest import implementation
from .test_service import FakeTransport

PATH = '/orbbec/customCommon/customCommonAction!query.action'


def service(config_file, raw_config, tmp_path, rows=None, factory=None):
    raw_config['allowed_api_paths'].append(PATH)
    payload = json.dumps({'status': True, 'result': {'MSTATUS': 'S', 'DATA': rows or []}}).encode()
    return implementation('mes_access.service').MesAccessService(config_file(raw_config), str(tmp_path/'audit.json'),
        transport_factory=factory or (lambda c: FakeTransport(c, payload)))


def test_context_and_exact_identity_result(config_file, raw_config, tmp_path):
    s = service(config_file, raw_config, tmp_path, [{'SHOP_ORDER': 'WO1', 'ORDER_DESC': None}])
    context = s.read_context()
    assert set(context) == {'source', 'fingerprint'}
    assert context['source'] == {'system': 'mes', 'origin': 'native', 'fact_role': 'observation',
        'environment': 'production', 'site_code': '1000', 'namespace': s.order_materials_configuration()['namespace']}
    result = s.source_orders('WO', None, 'actor', expected_fingerprint=context['fingerprint'])
    assert set(result) == {'source', 'fingerprint', 'items', 'next_cursor', 'total', 'page_size', 'request_id'}
    assert result['source'] == context['source']
    assert result['fingerprint'] == context['fingerprint']
    assert result['items'] == [{'shop_order': 'WO1', 'description': None}]
    assert result['next_cursor'] is result['total'] is None and result['page_size'] == 5


def test_fixed_bound_query(config_file, raw_config, tmp_path):
    service(config_file, raw_config, tmp_path)
    config = implementation('mes_connection').load_mes_connection_config(config_file(raw_config))
    prepare = implementation('mes_access.registry').prepare_query
    spec, body = prepare(config, 'source_orders', {'prefix': 'WO', 'after': 'WO1'}, 1, 5)
    assert spec.path == PATH and spec.encoding == 'json_body'
    assert set(body) == {'querySql', 'params'}
    assert body['params'] == {'SHOP_ORDER': 'WO', 'AFTER_SHOP_ORDER': 'WO1'}
    sql = body['querySql']
    assert 'SITE=:SITE' in sql and 'ORDER BY SHOP_ORDER ASC) WHERE ROWNUM<=5' in sql
    assert ':SHOP_ORDER' in sql and ':AFTER_SHOP_ORDER' in sql and 'WO1' not in sql
    assert sql.startswith('SELECT SHOP_ORDER,ORDER_DESC FROM (SELECT SHOP_ORDER,ORDER_DESC FROM M_SHOP_ORDER')
    for filters in [{'SITE': 'evil'}, {'querySql': 'DELETE'}, {'prefix': '%'}, {'prefix': "x'"}, {'after': 'x\n'}, {'prefix': 'a'*65}]:
        with pytest.raises(Exception) as exc:
            prepare(config, 'source_orders', filters, 1, 5)
        assert exc.value.code == 'MES_INVALID_QUERY'
    with pytest.raises(Exception):
        prepare(config, 'source_orders', {}, 2, 5)


@pytest.mark.parametrize('rows', [
    [{'SHOP_ORDER': 'WO1', 'ORDER_DESC': None}]*2,
    [{'SHOP_ORDER': 'WO3', 'ORDER_DESC': None}, {'SHOP_ORDER': 'WO2', 'ORDER_DESC': None}],
    [{'SHOP_ORDER': 'NO1', 'ORDER_DESC': None}],
    [{'SHOP_ORDER': 'WO1', 'ORDER_DESC': None}],
    [{'SHOP_ORDER': 'WO2', 'ORDER_DESC': 42}],
    [{'ORDER_DESC': None}],
])
def test_invalid_identity_page_fails_closed(config_file, raw_config, tmp_path, rows):
    s = service(config_file, raw_config, tmp_path, rows)
    with pytest.raises(Exception) as exc:
        s.source_orders('WO', 'WO1', 'actor')
    assert exc.value.code == 'MES_INVALID_RESPONSE'


def test_full_page_has_explicit_cursor(config_file, raw_config, tmp_path):
    s = service(config_file, raw_config, tmp_path, [{'SHOP_ORDER': 'WO'+str(i), 'ORDER_DESC': '说明'} for i in range(1, 6)])
    assert s.source_orders('WO', None, 'actor')['next_cursor'] == 'WO5'


@pytest.mark.parametrize('method', ['source_orders', 'query', 'collect_order_materials'])
def test_expected_fingerprint_prevents_source_io(config_file, raw_config, tmp_path, method):
    s = service(config_file, raw_config, tmp_path, factory=lambda c: pytest.fail('must not construct source transport'))
    args = {'source_orders': ('', None, 'actor'), 'query': ('order_materials',), 'collect_order_materials': ('WO1', 'actor')}[method]
    with pytest.raises(Exception) as exc:
        getattr(s, method)(*args, expected_fingerprint='0'*64)
    assert exc.value.code == 'MES_CONFIGURATION_CHANGED'


def test_configuration_change_during_identity_read_rejects_result(config_file, raw_config, tmp_path):
    def factory(c):
        raw_config['site_code'] = '2000'
        config_file(raw_config)
        return FakeTransport(c, b'{"status":true,"result":{"MSTATUS":"S","DATA":[]}}')
    s = service(config_file, raw_config, tmp_path, factory=factory)
    with pytest.raises(Exception) as exc:
        s.source_orders('', None, 'actor')
    assert exc.value.code == 'MES_CONFIGURATION_CHANGED'


@pytest.mark.parametrize('interface,field', [('material_priority', 'DFQTY'), ('iqc_inspections', 'INSP_QTY')])
def test_priority_iqc_preserve_decimal_lexemes(interface, field):
    payload = ('{"status":true,"result":{"MSTATUS":"S","pageNumber":1,"totalItems":1,"page":[{"'+field+'":0.123456789012345678901}]}}').encode()
    result = implementation('mes_access.parsing').parse_query_response(interface, payload)
    assert result['rows'][0][field] == '0.123456789012345678901'


def test_transport_sends_only_fixed_json_body(config_file, raw_config, tmp_path):
    service(config_file, raw_config, tmp_path)
    config = implementation('mes_connection').load_mes_connection_config(config_file(raw_config))
    captured = []
    def request(method, path, body, headers):
        captured.append((method, path, json.loads(body), headers))
        return 200, [], b'{"status":true,"result":{"MSTATUS":"S","DATA":[]}}'
    transport = implementation('mes_access.transport').SessionTransport(config, requester=request)
    transport.authenticated = True
    transport.query('source_orders', {'prefix': 'WO', 'after': None}, 1, 5)
    method, path, body, headers = captured[0]
    assert method == 'POST' and path == PATH and headers['Content-Type'] == 'application/json'
    assert set(body) == {'querySql', 'params'} and 'SITE' not in body['params']


@pytest.mark.parametrize('value', ['%', '_', "x'", 'x;', 'x\n', ' x', 'x ', True, {}, 'x'*65])
def test_invalid_scope_prevents_source_io(config_file, raw_config, tmp_path, value):
    s = service(config_file, raw_config, tmp_path, factory=lambda c: pytest.fail('invalid input must not perform I/O'))
    with pytest.raises(Exception) as exc:
        s.source_orders(value, None, 'actor')
    assert exc.value.code == 'MES_INVALID_QUERY'


def test_identity_audit_is_durable_and_contains_only_metadata(config_file, raw_config, tmp_path):
    s = service(config_file, raw_config, tmp_path, [{'SHOP_ORDER': 'WO-PRIVATE', 'ORDER_DESC': 'PRIVATE-DESCRIPTION'}])
    result = s.source_orders('WO', None, 'PRIVATE-ACTOR')
    text = (tmp_path/'audit.json').read_text()
    assert all(value not in text for value in ['WO-PRIVATE', 'PRIVATE-DESCRIPTION', 'PRIVATE-ACTOR'])
    events = json.loads(text)['events']
    assert [event['status'] for event in events] == ['started', 'success']
    assert all(event['function'] == 'source_orders' and event['operation'] == 'query' for event in events)
    assert events[-1]['row_count'] == 1 and events[-1]['request_id'] == result['request_id']


def test_private_identity_profile_is_not_generic_query_interface(config_file, raw_config, tmp_path):
    s = service(config_file, raw_config, tmp_path, factory=lambda c: pytest.fail('private profile must use typed method'))
    with pytest.raises(Exception) as exc:
        s.query('source_orders', {'prefix': 'WO'})
    assert exc.value.code == 'MES_INTERFACE_DENIED'


def test_underscore_page_cursor_roundtrips(config_file, raw_config, tmp_path):
    pages = [[{'SHOP_ORDER': f'WO_{i}', 'ORDER_DESC': None} for i in range(1, 6)],
             [{'SHOP_ORDER': 'WO_6', 'ORDER_DESC': None}]]
    calls = []
    def factory(c):
        class PageTransport(FakeTransport):
            def query(self, interface, filters, page, page_size):
                calls.append(filters)
                return json.dumps({'status': True, 'result': {'MSTATUS': 'S', 'DATA': pages.pop(0)}}).encode()
        return PageTransport(c)
    s = service(config_file, raw_config, tmp_path, factory=factory)
    first = s.source_orders('WO', None, 'actor')
    assert first['next_cursor'] == 'WO_5'
    second = s.source_orders('WO', first['next_cursor'], 'actor')
    assert second['items'] == [{'shop_order': 'WO_6', 'description': None}]
    assert calls[-1]['after'] == 'WO_5'


@pytest.mark.parametrize('order', ['WO中文', 'W'*65, 'WO%', 'WO\x7f'])
def test_unusable_source_identity_rejected(config_file, raw_config, tmp_path, order):
    s = service(config_file, raw_config, tmp_path, [{'SHOP_ORDER': order, 'ORDER_DESC': None}])
    with pytest.raises(Exception) as exc:
        s.source_orders('', None, 'actor')
    assert exc.value.code == 'MES_INVALID_RESPONSE'


def test_native_collector_queries_underscore_order_and_checks_identity(config_file, raw_config, tmp_path):
    row = {'SHOP_ORDER': 'WO_1', 'RSNUM': 'R', 'RSPOS': '1', 'MATNR': 'M', 'BDMNG': '1', 'MEINS': 'EA'}
    payload = json.dumps({'status': True, 'result': {'MSTATUS': 'S', 'page': [row], 'pageNumber': 1, 'totalItems': 1}}).encode()
    s = service(config_file, raw_config, tmp_path, factory=lambda c: FakeTransport(c, payload))
    assert s.collect_order_materials('WO_1', 'actor')['components'][0]['material_id'] == 'M'
    with pytest.raises(Exception) as exc:
        s.collect_order_materials('WO_2', 'actor')
    assert exc.value.code == 'MES_ORDER_MISMATCH'


@pytest.mark.parametrize('after', ['WO中文', 'W'*65, 'WO%', 'WO\x7f', True, {}])
def test_unusable_cursor_rejected_before_io(config_file, raw_config, tmp_path, after):
    s = service(config_file, raw_config, tmp_path, factory=lambda c: pytest.fail('invalid cursor must not perform I/O'))
    with pytest.raises(Exception) as exc:
        s.source_orders('', after, 'actor')
    assert exc.value.code == 'MES_INVALID_QUERY'


def test_registry_exact_order_boundaries_do_not_expand_other_filters(config):
    from manufacturing_platform.mes_access.registry import prepare_query
    assert prepare_query(config, 'material_priority', {'shopOrder':'WO_1'}, 1, 5)[1]['shopOrder']=='WO_1'
    assert prepare_query(config, 'order_materials', {'shopOrder':'W'*64}, 1, 5)[1]['shopOrder']=='W'*64
    for interface,filters in [('order_materials',{'shopOrder':'W'*65}),('material_priority',{'itemNo':'MAT_1'})]:
        with pytest.raises(Exception) as exc:prepare_query(config,interface,filters,1,5)
        assert exc.value.code=='MES_INVALID_QUERY'


@pytest.mark.parametrize('prefix,after', [('', ''), ('WO', ''), ('', 'WO_5'), ('WO', 'WO_5')])
def test_fixed_variants_omit_null_binds_for_legacy_driver(config_file, raw_config, tmp_path, prefix, after):
    service(config_file, raw_config, tmp_path)
    config = implementation('mes_connection').load_mes_connection_config(config_file(raw_config))
    captured = []
    def legacy_driver(method, path, body, headers):
        wire = json.loads(body)
        # Model the observed Oracle JDBC failure without contacting any source.
        assert all(type(value) is str and value for value in wire['params'].values()), 'legacy JDBC rejects null binds'
        captured.append(wire)
        return 200, [], b'{"status":true,"result":{"MSTATUS":"S","DATA":[]}}'
    transport = implementation('mes_access.transport').SessionTransport(config, requester=legacy_driver)
    transport.authenticated = True
    transport.query('source_orders', {'prefix': prefix, 'after': after}, 1, 5)
    params = {}
    predicate = 'WHERE SITE=:SITE'
    if prefix:
        params['SHOP_ORDER'] = prefix
        predicate += " AND SHOP_ORDER LIKE :SHOP_ORDER||'%'"
    if after:
        params['AFTER_SHOP_ORDER'] = after
        predicate += ' AND SHOP_ORDER>:AFTER_SHOP_ORDER'
    assert captured == [{'querySql': 'SELECT SHOP_ORDER,ORDER_DESC FROM (SELECT SHOP_ORDER,ORDER_DESC FROM M_SHOP_ORDER '
                        + predicate + ' ORDER BY SHOP_ORDER ASC) WHERE ROWNUM<=5', 'params': params}]
