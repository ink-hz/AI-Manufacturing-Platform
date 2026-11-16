import copy
import json
from uuid import uuid4
import pytest
from manufacturing_platform.mes_access import relay_protocol as p
from manufacturing_platform.mes_access.relay_client import validate_result
from manufacturing_platform.mes_access.errors import MesAccessError
from .test_relay_protocol import CONTEXT, request

RECENT={'prefix':'WO','after':'','directory_mode':'recent'}
def recent(rows=None):
    return dict(source=CONTEXT['source'],fingerprint=CONTEXT['fingerprint'],items=rows if rows is not None else [dict(shop_order='WO9',description=None,created_at='2026-11-16T01:02:03.123456789Z',has_components=True),dict(shop_order='WO8',description='old',created_at=None,has_components=False)],next_cursor=None,total=None,page_size=5,request_id=str(uuid4()))

@pytest.mark.parametrize('op,scope',[('source_orders',RECENT),('order_materials',{'shop_order':'WO9','component_mode':'owner'})])
def test_closed_modes_accepted(op,scope):
    assert p.parse_request(json.dumps(request(op,scope)).encode())['scope']==scope

@pytest.mark.parametrize('op,scope',[('source_orders',{**RECENT,'directory_mode':'other'}),('source_orders',{**RECENT,'sql':'x'}),('order_materials',{'shop_order':'WO9','component_mode':None}),('order_materials',{'shop_order':'WO9','directory_mode':'recent'})])
def test_other_modes_denied(op,scope):
    with pytest.raises(p.RelayProtocolError):p.parse_request(json.dumps(request(op,scope)).encode())

def test_recent_accepts_dates_then_null_and_descending_identity():
    result=recent()
    assert validate_result(result,'source_orders',RECENT,CONTEXT)==result

@pytest.mark.parametrize('change',['duplicate','ascending_date','ascending_tie','null_first','invalid_date','noncanonical','wrong_bool','prefix','after','legacy_fields'])
def test_recent_rejects_invalid_projection(change):
    result=recent();rows=result['items'];scope=copy.deepcopy(RECENT)
    if change=='duplicate':rows[1]['shop_order']=rows[0]['shop_order']
    if change=='ascending_date':rows[1]['created_at']='2026-11-17T01:02:03.123456789Z'
    if change=='ascending_tie':rows[1].update(shop_order='WOZ',created_at=rows[0]['created_at'])
    if change=='null_first':rows[0]['created_at']=None;rows[1]['created_at']='2026-11-16T01:02:03.123456789Z'
    if change=='invalid_date':rows[0]['created_at']='2026-02-30T01:02:03.123456789Z'
    if change=='noncanonical':rows[0]['created_at']='2026-11-16T01:02:03Z'
    if change=='wrong_bool':rows[0]['has_components']=1
    if change=='prefix':rows[0]['shop_order']='OTHER'
    if change=='after':scope['after']='WO9'
    if change=='legacy_fields':del rows[0]['created_at']
    with pytest.raises(MesAccessError):validate_result(result,'source_orders',scope,CONTEXT)

def test_recent_cursor_requires_last_exact_identity_on_full_page():
    result=recent([dict(shop_order=f'WO_{i}',description=None,created_at=None,has_components=False) for i in range(9,4,-1)])
    result['next_cursor']='WO_5'
    assert validate_result(result,'source_orders',RECENT,CONTEXT)['next_cursor']=='WO_5'
    result['next_cursor']='WO_9'
    with pytest.raises(MesAccessError):validate_result(result,'source_orders',RECENT,CONTEXT)

def test_empty_owner_requires_read_evidence_and_legacy_stays_denied():
    result=dict(namespace=CONTEXT['source']['namespace'],fingerprint=CONTEXT['fingerprint'],environment='production',site_code='1000',request_ids=[str(uuid4())],total=0,components=[])
    scope={'shop_order':'WO9','component_mode':'owner'}
    assert validate_result(result,'order_materials',scope,CONTEXT)==result
    with pytest.raises(MesAccessError):validate_result(result,'order_materials',{'shop_order':'WO9'},CONTEXT)
    result['request_ids']=[]
    with pytest.raises(MesAccessError):validate_result(result,'order_materials',scope,CONTEXT)

def test_gateway_dispatches_modes_and_keeps_legacy():
    from manufacturing_platform.mes_access.relay_gateway import dispatch
    class Fake:
        def read_context(self):return CONTEXT
        def __getattr__(self,name):return lambda *a,**k: {'method':name,'args':a,'pin':k}
    for op,scope,method in [('source_orders',RECENT,'source_orders_recent'),('source_orders',{'prefix':'','after':''},'source_orders'),('order_materials',{'shop_order':'WO9','component_mode':'owner'},'collect_order_materials_by_owner'),('order_materials',{'shop_order':'WO9'},'collect_order_materials')]:
        assert dispatch(Fake(),request(op,scope))['result']['method']==method

def test_selector_routes_both_backends_to_new_aliases(monkeypatch):
    from manufacturing_platform.mes_access.selector import MesAccessSelector
    class Fake:
        def source_orders_recent(self,*a,**kw):return ('recent',a,kw)
        def collect_order_materials_by_owner(self,*a,**kw):return ('owner',a,kw)
    selector=MesAccessSelector('unused','unused');monkeypatch.setattr(selector,'_service',lambda:Fake())
    assert selector.source_orders('WO','','actor',expected_fingerprint='pin')[0]=='recent'
    assert selector.collect_order_materials('WO9','actor',expected_fingerprint='pin')[0]=='owner'

def test_relay_aliases_send_exact_modes(tmp_path,monkeypatch):
    from .test_relay_client import configured
    service=configured(tmp_path);calls=[]
    monkeypatch.setattr(service,'_query',lambda *a:calls.append(a))
    service.source_orders_recent('WO','','actor',expected_fingerprint='pin')
    service.collect_order_materials_by_owner('WO9','actor',expected_fingerprint='pin')
    assert calls==[('source_orders',RECENT,'actor','pin'),('order_materials',{'shop_order':'WO9','component_mode':'owner'},'actor','pin')]

@pytest.mark.parametrize('owner',[False,True])
def test_new_relay_roundtrip_preserves_binding_and_read_audit(tmp_path,monkeypatch,owner):
    from .test_relay_client import configured
    from manufacturing_platform.mes_access import relay_client as c
    from manufacturing_platform.mes_access.store import MesAuditStore
    service=configured(tmp_path);upstream=str(uuid4())
    def exchange(sock,token,command,timeout,max_bytes):
        assert command['expected_fingerprint']==CONTEXT['fingerprint']
        if owner:
            assert command['operation']=='order_materials'
            assert command['scope']=={'shop_order':'WO9','component_mode':'owner'}
            result=dict(namespace=CONTEXT['source']['namespace'],fingerprint=CONTEXT['fingerprint'],environment='production',site_code='1000',request_ids=[upstream],total=0,components=[])
        else:
            assert command['operation']=='source_orders'
            assert command['scope']==RECENT
            result=recent();result['request_id']=upstream
        return dict(version=1,request_id=command['request_id'],context=CONTEXT,result=result,error=None),100
    monkeypatch.setattr(c,'_exchange_result',exchange)
    binding=service.read_context()['fingerprint']
    result=service.collect_order_materials_by_owner('WO9','operator',expected_fingerprint=binding) if owner else service.source_orders_recent('WO','','operator',expected_fingerprint=binding)
    assert result['fingerprint']==binding
    event=MesAuditStore(service.audit_path).read()['events'][-1]
    assert event['source_request_ids']==[upstream]
    assert event['status']=='success'
    assert 'components' not in event and 'items' not in event

@pytest.mark.parametrize('operation,scope',[
    ('source_orders',{**RECENT,'directory_mode':'sql'}),
    ('order_materials',{'shop_order':'WO9','component_mode':'other'}),
    ('source_orders',{**RECENT,'site_code':'OTHER'}),
])
def test_invalid_mode_never_reaches_transport(tmp_path,monkeypatch,operation,scope):
    from .test_relay_client import configured
    from manufacturing_platform.mes_access import relay_client as c
    service=configured(tmp_path)
    def forbidden(*args):raise AssertionError('transport must not run')
    monkeypatch.setattr(c,'_exchange_result',forbidden)
    with pytest.raises(MesAccessError,match='MES_INVALID_QUERY'):service._query(operation,scope,'actor',None)

def test_legacy_projection_rejects_new_fields():
    with pytest.raises(MesAccessError):validate_result(recent(),'source_orders',{'prefix':'WO','after':''},CONTEXT)
