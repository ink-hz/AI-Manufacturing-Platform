from dataclasses import replace
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from .conftest import PATHS, implementation
from .test_transport import Wire, client


def parse(payload, interface='order_materials', page=1, page_size=1):
    return implementation('mes_access.parsing').parse_query_response(
        interface, payload, page=page, page_size=page_size)


def response(rows=None, *, total=1, page=1, rows_key='page'):
    result = {'MSTATUS': 'S', 'totalItems': total, rows_key: [{'SHOP_ORDER': 'SYNTHETIC'}] if rows is None else rows}
    if page is not None:
        result['pageNumber'] = page
    return json.dumps({'status': True, 'result': result}).encode()


def test_all_six_wire_shapes_match_current_source(config):
    ids = ['order_materials', 'order_operations', 'material_priority', 'iqc_records', 'production_reports', 'inventory_counts']
    expected = [ {'shopOrder': ''}, {'shopOrder': ''}, {'shopOrder': '', 'itemNo': '', 'ignoreflag': False},
        {'IQC_NO': '', 'ITEM_NO': '', 'ITEM_LOT': '', 'startDate': '', 'endDate': ''},
        {'data02': '', 'vornr': '', 'begindate': '', 'enddate': '', 'flag': '', 'flag1': ''},
        {'statCode': '', 'initUser': '', 'status': '', 'warehouseNo': '', 'startDate': '', 'endDate': ''} ]
    for index, interface in enumerate(ids):
        wire = Wire(); wire.responses.append((200, [('Content-Type', 'application/json')], response()))
        c = client(config, wire)
        try:
            c.query(interface)
            method, target, body, headers = wire.calls[-1]
            assert method == 'POST' and body == b''
            assert headers['Content-Type'] == 'application/x-www-form-urlencoded'
            assert urlsplit(target).path == PATHS[index]
            params = parse_qs(urlsplit(target).query)
            assert set(params) == {'paramJson'}
            payload = json.loads(params['paramJson'][0])
            size_key = 'pageSize' if interface == 'iqc_records' else 'pageLimit'
            assert payload == {**expected[index], 'pageNumber': 1, size_key: 1}
        finally:
            c.close()


@pytest.mark.parametrize('interface,filters,page,size', [
    ('save', {}, 1, 1), ('https://evil.test/', {}, 1, 1), ('order_materials', {'sql': 'SELECT'}, 1, 1),
    ('material_priority', {'ignoreflag': 'true'}, 1, 1), ('order_materials', {'shopOrder': '*'}, 1, 1),
    ('order_materials', {'shopOrder': "x' OR 1=1"}, 1, 1), ('order_materials', {'shopOrder': 'a%b'}, 1, 1),
    ('order_materials', {'shopOrder': 'a\nb'}, 1, 1), ('order_materials', {'shopOrder': 123}, 1, 1),
    ('order_materials', {'shopOrder': 'a'*129}, 1, 1), ('iqc_records', {'startDate': '2026-02-30'}, 1, 1),
    ('iqc_records', {'startDate': '2026-11-02', 'endDate': '2026-11-01'}, 1, 1),
    ('order_materials', {}, True, 1), ('order_materials', {}, 0, 1), ('order_materials', {}, 1, 6),
    ('order_materials', {}, 1, True), ('order_materials', [], 1, 1),
])
def test_query_policy_denies_before_even_login(config, interface, filters, page, size):
    wire = Wire(); c = client(config, wire)
    with pytest.raises(Exception) as caught:
        c.query(interface, filters, page, size)
    assert caught.value.code in {'MES_INTERFACE_DENIED', 'MES_INVALID_QUERY'}
    assert wire.calls == []


def test_transport_enforces_both_fixed_and_config_allowlists(config):
    wire = Wire(); c = client(replace(config, allowed_api_paths=()), wire)
    with pytest.raises(Exception) as caught:
        c.query('order_materials')
    assert caught.value.code == 'MES_INTERFACE_DENIED' and not wire.calls


def test_parser_preserves_bounded_java_date_and_iqc_shape():
    row = {'CREATE_DATE': {'year': 126, 'month': 10, 'time': 1794355200000}, 'other': [None, True, 1.5]}
    assert parse(response([row]), 'order_operations') == {'rows': [row], 'total_items': 1, 'page': 1, 'page_size': 1}
    assert parse(response([row]))['rows'][0]['other'][-1] == '1.5'
    assert parse(response([], total=0, page=None, rows_key='iqcList'), 'iqc_records')['rows'] == []


@pytest.mark.parametrize('payload', [
    b'{"status":true,"status":true,"result":{}}', b'{', b'[]', b'<html>login</html>',
    b'{"status":true,"result":{"MSTATUS":"S","totalItems":1,"pageNumber":1,"page":[{"n":NaN}]}}',
    b'{"status":true,"result":{"MSTATUS":"S","totalItems":1,"pageNumber":1,"page":[{"n":Infinity}]}}',
    response([{'password': 'private'}]), response([{'date': {'JSESSIONID': 'private'}}]),
    response([{'a': [[[[[[1]]]]]]}]), response([{'a': list(range(129))}]),
    response([{'a': 'x'*4097}]), response([{'a': 2**64}]), response([1]), response([{}, {}], total=2),
    response([], total=-1), response([], total=True), response([], total='1'), response([], total=2**31),
    response(total=0), response(page=2), response(page=True), response(page=None),
    response().replace(b'"MSTATUS": "S"', b'"MSTATUS": "E"'),
    response().replace(b'"status": true', b'"status": false'),
    response().replace(b'"status": true', b'"status": 1'),
])
def test_parser_rejects_unsafe_or_unverified_responses(payload):
    with pytest.raises(Exception) as caught:
        parse(payload)
    assert caught.value.code in {'MES_INVALID_RESPONSE', 'MES_BUSINESS_FAILURE', 'MES_SESSION_EXPIRED'}
    assert 'private' not in str(caught.value)


@pytest.mark.parametrize('status,headers,body', [
    (302, [('Location', '/login.jsp')], b''), (401, [], b'private'),
    (200, [('Content-Type', 'text/html')], b'<html>login</html>'),
    (500, [], b'private'), (200, [('Location', 'http://evil.test')], b'{}'),
])
def test_query_session_or_http_failure_does_not_reauthenticate(config, status, headers, body):
    wire = Wire(); wire.responses.append((status, headers, body)); c = client(config, wire)
    with pytest.raises(Exception) as caught:
        c.query('order_materials')
    assert caught.value.code in {'MES_SESSION_EXPIRED', 'MES_INVALID_RESPONSE', 'MES_REDIRECT_BLOCKED'}
    assert len(wire.calls) == 4 and not c.authenticated


@pytest.mark.parametrize('code', ['ORDER_1', ' a', 'a\t', 'a"b', 'a\\b'])
def test_only_literal_code_characters_are_accepted(config, code):
    wire = Wire()
    with pytest.raises(Exception) as caught:
        client(config, wire).query('order_materials', {'shopOrder': code})
    assert caught.value.code == 'MES_INVALID_QUERY' and not wire.calls


def test_node_budget_rejects_wide_nested_rows():
    row = {str(n): list(range(100)) for n in range(30)}
    with pytest.raises(Exception) as caught:
        parse(response([row]))
    assert caught.value.code == 'MES_INVALID_RESPONSE'


def test_nested_duplicate_keys_and_numeric_overflow_rejected():
    for value in [b'{"a":1,"a":2}', b'{"a":1e999}']:
        payload = b'{"status":true,"result":{"MSTATUS":"S","pageNumber":1,"totalItems":1,"page":[' + value + b']}}'
        with pytest.raises(Exception) as caught:
            parse(payload)
        assert caught.value.code == 'MES_INVALID_RESPONSE'


def test_explicit_page_is_one_request_and_preserves_supplied_literals(config):
    wire = Wire(); wire.responses.append((200, [], response(total=9, page=3)))
    client(config, wire).query('order_materials', {'shopOrder': 'ORDER-123.4'}, 3, 2)
    params = json.loads(parse_qs(urlsplit(wire.calls[-1][1]).query)['paramJson'][0])
    assert params == {'shopOrder': 'ORDER-123.4', 'pageNumber': 3, 'pageLimit': 2}
    assert len(wire.calls) == 4


def test_config_row_cap_is_stricter_than_global_cap(config):
    wire = Wire()
    with pytest.raises(Exception) as caught:
        client(replace(config, max_rows=2), wire).query('order_materials', page_size=3)
    assert caught.value.code == 'MES_INVALID_QUERY' and not wire.calls


def test_legacy_json_with_html_mime_is_parsed_by_body(config):
    payload = response([{'SHOP_ORDER': 'SYNTHETIC'}])
    wire = Wire(); wire.responses.append((200, [('Content-Type', 'text/html; charset=UTF-8')], payload))
    c = client(config, wire)
    try:
        assert parse(c.query('order_materials'))['rows'] == [{'SHOP_ORDER': 'SYNTHETIC'}]
        assert len(wire.calls) == 4
    finally:
        c.close()
