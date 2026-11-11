from dataclasses import replace
import json

import pytest

from .conftest import implementation


def row(n):
    return {'SHOP_ORDER': 'ORDER-1', 'RSNUM': 'R', 'RSPOS': str(n), 'MATNR': 'M',
            'BDMNG': '123.00000000000000001', 'ENMNG': '0', 'MEINS': 'EA', 'LGORT': 'A'}


def test_collection_reads_all_pages_and_preserves_precision(config, tmp_path):
    service_module = implementation('mes_access.service')
    service = service_module.MesAccessService('/unused', str(tmp_path / 'audit'))
    service._context = lambda: (config, config.fingerprint(), None)
    calls = []
    def query(config, fingerprint, store, interface, filters, page, page_size, actor_id):
        calls.append((page, page_size))
        return {'rows': [row(n) for n in range((page-1)*page_size, min(page*page_size, 12))], 'total_items': 12, 'request_id': str(page)}
    service._query = query
    result = service.collect_order_materials('ORDER-1', 'actor')
    assert calls == [(1, 5), (2, 5), (3, 5)]
    assert result['components'][0]['required_quantity'] == '123.00000000000000001'
    assert len(result['components']) == 12


def test_order_material_parser_preserves_float_lexeme():
    parse = implementation('mes_access.parsing').parse_query_response
    payload = b'{"status":true,"result":{"MSTATUS":"S","pageNumber":1,"totalItems":1,"page":[{"BDMNG":0.1234567890123456789}]}}'
    assert parse('order_materials', payload)['rows'][0]['BDMNG'] == '0.1234567890123456789'


@pytest.mark.parametrize('case', ['empty', 'wrong', 'missing', 'duplicate', 'bad_amount', 'bad_unit', 'changed_total', 'short', 'over_limit', 'failure'])
def test_collection_rejects_incomplete_or_invalid_sets(config, tmp_path, case):
    service = implementation('mes_access.service').MesAccessService('/unused', str(tmp_path / 'audit'))
    service._context = lambda: (config, config.fingerprint(), None)
    def query(config, fingerprint, store, interface, filters, page, page_size, actor_id):
        from manufacturing_platform.mes_access.errors import MesAccessError
        if case == 'failure' and page == 2:
            raise MesAccessError('MES_OPERATION_FAILED')
        total = 0 if case == 'empty' else 101 if case == 'over_limit' else 6
        rows = [row(n) for n in range((page-1)*page_size, min(page*page_size, total))]
        if page == 1 and rows:
            if case == 'wrong': rows[0]['SHOP_ORDER'] = 'OTHER'
            if case == 'missing': del rows[0]['SHOP_ORDER']
            if case == 'duplicate': rows[1]['RSPOS'] = rows[0]['RSPOS']
            if case == 'bad_amount': rows[0]['BDMNG'] = '-1'
            if case == 'bad_unit': rows[0]['MEINS'] = ''
            if case == 'short': rows.pop()
        if case == 'changed_total' and page == 2: total = 7
        return {'rows': rows, 'total_items': total, 'request_id': str(page)}
    service._query = query
    with pytest.raises(Exception):
        service.collect_order_materials('ORDER-1', 'actor')


def test_configured_page_size_and_limit(config, tmp_path):
    config = replace(config, max_rows=2)
    service = implementation('mes_access.service').MesAccessService('/unused', str(tmp_path / 'audit'))
    service._context = lambda: (config, config.fingerprint(), None)
    calls = []
    def query(config, fingerprint, store, interface, filters, page, page_size, actor_id):
        calls.append(page_size)
        return {'rows': [row(n) for n in range((page-1)*page_size, min(page*page_size, 5))], 'total_items': 5, 'request_id': str(page)}
    service._query = query
    assert service.collect_order_materials('ORDER-1', 'actor')['total'] == 5
    assert calls == [2, 2, 2]


def test_namespace_ignores_credentials_but_fingerprint_does_not(config, tmp_path):
    service = implementation('mes_access.service').MesAccessService('/unused', str(tmp_path / 'audit'))
    service._context = lambda: (config, config.fingerprint(), None)
    first = service.order_materials_configuration()
    rotated = replace(config, password='new-password')
    service._context = lambda: (rotated, rotated.fingerprint(), None)
    second = service.order_materials_configuration()
    assert first['namespace'] == second['namespace']
    assert first['fingerprint'] != second['fingerprint']


def test_integer_reservation_and_empty_optional_location(config, tmp_path):
    service = implementation('mes_access.service').MesAccessService('/unused', str(tmp_path / 'audit'))
    service._context = lambda: (config, config.fingerprint(), None)
    item = row(1); item['RSNUM'] = 123; item['LGORT'] = ''
    service._query = lambda *args: {'rows': [item], 'total_items': 1, 'request_id': 'request'}
    result = service.collect_order_materials('ORDER-1', 'actor')
    assert result['components'][0]['component_key'] == '123:1'
    assert result['components'][0]['storage_location'] is None
