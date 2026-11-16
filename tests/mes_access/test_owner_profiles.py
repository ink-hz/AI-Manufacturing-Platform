import json
import pytest
from .conftest import implementation
from .test_source_orders import service


def test_recent_timestamp_and_private_query(config_file, raw_config, tmp_path):
    rows = [{'SHOP_ORDER':'WO_2','ORDER_DESC':None,'CREATE_DATE':{'time':1001,'nanos':1234567},'HAS_COMPONENTS':1},
            {'SHOP_ORDER':'WO_1','ORDER_DESC':'old','CREATE_DATE':None,'HAS_COMPONENTS':0}]
    s = service(config_file, raw_config, tmp_path, rows)
    result = s.source_orders_recent('WO', None, 'actor')
    assert result['items'] == [dict(shop_order='WO_2',description=None,created_at='1970-01-01T00:00:01.001234567Z',has_components=True),dict(shop_order='WO_1',description='old',created_at=None,has_components=False)]
    for key in ['source_orders_recent','source_order_components']:
        with pytest.raises(Exception) as e:s.query(key)
        assert e.value.code == 'MES_INTERFACE_DENIED'


def test_owner_empty_is_observation(config_file, raw_config, tmp_path):
    s = service(config_file, raw_config, tmp_path)
    result = s.collect_order_materials_by_owner('WO_1', 'actor')
    assert result['components'] == [] and result['total'] == 0 and len(result['request_ids']) == 1


def test_owner_projection_precision(config_file, raw_config, tmp_path):
    rows = [{'SHOP_ORDER':'WO_1','AUFNR':'PARENT','RSNUM':'R','RSPOS':'1','MATNR':'M','BDMNG':'0.1234567890123456789','ENMNG':0,'MEINS':'EA','LGORT':None,'TOTAL_ROWS':1,'READ_ROW_NUM':1}]
    s = service(config_file, raw_config, tmp_path, rows)
    result = s.collect_order_materials_by_owner('WO_1','actor')
    assert result['components'][0]['required_quantity'] == '0.1234567890123456789'


def test_fixed_private_sql(config_file, raw_config, tmp_path):
    service(config_file,raw_config,tmp_path)
    c=implementation('mes_connection').load_mes_connection_config(config_file(raw_config))
    prepare=implementation('mes_access.registry').prepare_query
    _, body=prepare(c,'source_orders_recent',{'prefix':'WO','after':'WO_2'},1,5)
    assert body['params']=={'SHOP_ORDER':'WO','AFTER_SHOP_ORDER':'WO_2'}
    assert 'CREATE_DATE DESC NULLS LAST' in body['querySql'] and 'EXISTS' in body['querySql']
    assert all(v is not None for v in body['params'].values())
    _, body=prepare(c,'source_order_components',{'shopOrder':'WO_1'},2,5)
    assert 'M_SHOP_ORDER_RESB' in body['querySql'] and 'COUNT(*) OVER()' in body['querySql']
    assert 'READ_ROW_NUM>5' in body['querySql'] and 'READ_ROW_NUM<=10' in body['querySql']


def owner_row(index=1, total=1, **changes):
    return {'SHOP_ORDER':'WO_1','AUFNR':'PARENT','RSNUM':'R','RSPOS':f'{index:04d}',
            'MATNR':'M','BDMNG':'1','ENMNG':0,'MEINS':'EA','LGORT':None,
            'TOTAL_ROWS':total,'READ_ROW_NUM':index,**changes}


@pytest.mark.parametrize('changes,code', [({'SHOP_ORDER':'OTHER'},'MES_ORDER_MISMATCH'),
    ({'READ_ROW_NUM':2},'MES_INVALID_RESPONSE'), ({'TOTAL_ROWS':101},'MES_COLLECTION_LIMIT'),
    ({'BDMNG':True},'MES_INVALID_ORDER_MATERIALS')])
def test_owner_rejects_unproven_rows(config_file, raw_config, tmp_path, changes, code):
    s=service(config_file,raw_config,tmp_path,[owner_row(**changes)])
    with pytest.raises(Exception) as e:s.collect_order_materials_by_owner('WO_1','actor')
    assert e.value.code==code


@pytest.mark.parametrize('rows', [
    [{'SHOP_ORDER':'WO_1','ORDER_DESC':None,'HAS_COMPONENTS':1}],
    [{'SHOP_ORDER':'WO_1','ORDER_DESC':None,'CREATE_DATE':None,'HAS_COMPONENTS':True}],
    [{'SHOP_ORDER':'WO_1','ORDER_DESC':None,'CREATE_DATE':None,'HAS_COMPONENTS':0},
     {'SHOP_ORDER':'WO_2','ORDER_DESC':None,'CREATE_DATE':None,'HAS_COMPONENTS':0}],
])
def test_recent_rejects_missing_or_unordered_facts(config_file,raw_config,tmp_path,rows):
    s=service(config_file,raw_config,tmp_path,rows)
    with pytest.raises(Exception) as e:s.source_orders_recent('',None,'actor')
    assert e.value.code=='MES_INVALID_RESPONSE'


def test_owner_walks_fixed_pages_and_preserves_numeric_lexemes(config_file,raw_config,tmp_path):
    from .test_service import FakeTransport
    pages=[[owner_row(i,6) for i in range(1,6)],[owner_row(6,6)]]
    calls=[]
    def factory(c):
        class Transport(FakeTransport):
            def query(self,interface,filters,page,page_size):
                calls.append((interface,dict(filters),page,page_size))
                payload=json.dumps({'status':True,'result':{'MSTATUS':'S','DATA':pages.pop(0)}})
                return payload.replace('"BDMNG": "1"','"BDMNG": 0.123456789012345678901').encode()
        return Transport(c)
    s=service(config_file,raw_config,tmp_path,factory=factory)
    result=s.collect_order_materials_by_owner('WO_1','actor')
    assert result['total']==6 and len(result['request_ids'])==2
    assert result['components'][0]['required_quantity']=='0.123456789012345678901'
    assert calls==[('source_order_components',{'shopOrder':'WO_1'},p,5) for p in [1,2]]


@pytest.mark.parametrize('second', [[owner_row(6,7)], [owner_row(6,6,RSPOS='0001')], []])
def test_owner_rejects_changes_duplicates_and_missing_pages(config_file,raw_config,tmp_path,second):
    from .test_service import FakeTransport
    pages=[[owner_row(i,6) for i in range(1,6)],second]
    def factory(c):
        class Transport(FakeTransport):
            def query(self,*args):
                return json.dumps({'status':True,'result':{'MSTATUS':'S','DATA':pages.pop(0)}}).encode()
        return Transport(c)
    s=service(config_file,raw_config,tmp_path,factory=factory)
    with pytest.raises(Exception):s.collect_order_materials_by_owner('WO_1','actor')


@pytest.mark.parametrize('prefix,after', [('',None),('WO',None),('', 'WO_5'),('WO','WO_5')])
def test_recent_transport_binds_closed_variants_without_null(config_file,raw_config,tmp_path,prefix,after):
    service(config_file,raw_config,tmp_path)
    c=implementation('mes_connection').load_mes_connection_config(config_file(raw_config))
    calls=[]
    def request(method,path,body,headers):
        calls.append(json.loads(body))
        return 200,[],b'{"status":true,"result":{"MSTATUS":"S","DATA":[]}}'
    t=implementation('mes_access.transport').SessionTransport(c,requester=request)
    t.authenticated=True
    t.query('source_orders_recent',{'prefix':prefix,'after':after},1,5)
    params={}
    if prefix:params['SHOP_ORDER']=prefix
    if after:params['AFTER_SHOP_ORDER']=after
    assert calls[0]['params']==params
    assert all(type(v) is str and v for v in params.values())
    if after:assert 'a.SITE=:SITE AND a.SHOP_ORDER=:AFTER_SHOP_ORDER' in calls[0]['querySql']


def test_recent_nanoseconds_and_nulls_define_order(config_file,raw_config,tmp_path):
    rows=[{'SHOP_ORDER':'WO_1','ORDER_DESC':None,'CREATE_DATE':{'time':1001,'nanos':1234568},'HAS_COMPONENTS':1},
          {'SHOP_ORDER':'WO_2','ORDER_DESC':None,'CREATE_DATE':{'time':1001,'nanos':1234567},'HAS_COMPONENTS':0}]
    s=service(config_file,raw_config,tmp_path,rows)
    assert [r['shop_order'] for r in s.source_orders_recent('',None,'actor')['items']]==['WO_1','WO_2']
    rows.reverse()
    with pytest.raises(Exception) as e:implementation('mes_access.source_orders').recent_items(rows,'',None)
    assert e.value.code=='MES_INVALID_RESPONSE'


def test_owner_audit_contains_metadata_only(config_file,raw_config,tmp_path):
    s=service(config_file,raw_config,tmp_path,[owner_row()])
    result=s.collect_order_materials_by_owner('WO_1','PRIVATE-ACTOR')
    audit=(tmp_path/'audit.json').read_text()
    assert 'WO_1' not in audit and 'PRIVATE-ACTOR' not in audit and 'PARENT' not in audit
    event=json.loads(audit)['events'][-1]
    assert event['function']=='source_order_components' and event['row_count']==1
    assert event['request_id']==result['request_ids'][0]


def test_owner_reservation_uses_numeric_column_order(config_file,raw_config,tmp_path):
    rows=[owner_row(1,2,RSNUM=2),owner_row(2,2,RSNUM=10)]
    s=service(config_file,raw_config,tmp_path,rows)
    assert [r['component_key'] for r in s.collect_order_materials_by_owner('WO_1','actor')['components']]==['2:0001','10:0002']


def test_owner_collects_exact_100_with_20_audited_pages(config_file,raw_config,tmp_path):
    from .test_service import FakeTransport
    calls=[]
    def factory(c):
        class Transport(FakeTransport):
            def query(self,interface,filters,page,page_size):
                calls.append(page)
                rows=[owner_row(i,100,RSNUM=2) for i in range((page-1)*5+1,page*5+1)]
                return json.dumps({'status':True,'result':{'MSTATUS':'S','DATA':rows}}).encode()
        return Transport(c)
    s=service(config_file,raw_config,tmp_path,factory=factory)
    result=s.collect_order_materials_by_owner('WO_1','actor')
    assert result['total']==len(result['components'])==100
    assert len(set(result['request_ids']))==20 and calls==list(range(1,21))


@pytest.mark.parametrize('rows', [
    [{'SHOP_ORDER':'WO_1','ORDER_DESC':None,'CREATE_DATE':{'time':1000,'nanos':0},'HAS_COMPONENTS':0},
     {'SHOP_ORDER':'WO_2','ORDER_DESC':None,'CREATE_DATE':{'time':1000,'nanos':0},'HAS_COMPONENTS':1}],
    [{'SHOP_ORDER':'WO_1','ORDER_DESC':None,'CREATE_DATE':None,'HAS_COMPONENTS':0},
     {'SHOP_ORDER':'WO_2','ORDER_DESC':None,'CREATE_DATE':{'time':1000,'nanos':0},'HAS_COMPONENTS':1}],
    [{'SHOP_ORDER':'WO_1','ORDER_DESC':None,'CREATE_DATE':{'time':1000,'nanos':1_000_000},'HAS_COMPONENTS':0}],
])
def test_recent_rejects_tie_null_and_timestamp_mismatch(config_file,raw_config,tmp_path,rows):
    s=service(config_file,raw_config,tmp_path,rows)
    with pytest.raises(Exception) as e:s.source_orders_recent('',None,'actor')
    assert e.value.code=='MES_INVALID_RESPONSE'


def test_owner_later_empty_is_incomplete_not_true_zero(config_file,raw_config,tmp_path):
    from .test_service import FakeTransport
    pages=[[owner_row(i,6) for i in range(1,6)],[]]
    def factory(c):
        class Transport(FakeTransport):
            def query(self,*args):
                return json.dumps({'status':True,'result':{'MSTATUS':'S','DATA':pages.pop(0)}}).encode()
        return Transport(c)
    s=service(config_file,raw_config,tmp_path,factory=factory)
    with pytest.raises(Exception) as e:s.collect_order_materials_by_owner('WO_1','actor')
    assert e.value.code=='MES_COLLECTION_INCOMPLETE'


@pytest.mark.parametrize('method,args', [('source_orders_recent',('',None,'actor')),
    ('collect_order_materials_by_owner',('WO_1','actor'))])
def test_new_methods_fail_fingerprint_before_io(config_file,raw_config,tmp_path,method,args):
    s=service(config_file,raw_config,tmp_path,factory=lambda c:pytest.fail('fingerprint must reject before transport'))
    with pytest.raises(Exception) as e:getattr(s,method)(*args,expected_fingerprint='0'*64)
    assert e.value.code=='MES_CONFIGURATION_CHANGED'


def test_recent_full_page_cursor_is_exact_last_identity(config_file,raw_config,tmp_path):
    rows=[{'SHOP_ORDER':f'WO_{i}','ORDER_DESC':None,'CREATE_DATE':None,'HAS_COMPONENTS':i%2} for i in range(5,0,-1)]
    s=service(config_file,raw_config,tmp_path,rows)
    result=s.source_orders_recent('WO',None,'actor')
    assert result['next_cursor']=='WO_1' and result['total'] is None and result['page_size']==5
    assert set(result)=={'source','fingerprint','items','next_cursor','total','page_size','request_id'}
    audit=json.loads((tmp_path/'audit.json').read_text())['events'][-1]
    assert audit['function']=='source_orders_recent' and audit['row_count']==5
