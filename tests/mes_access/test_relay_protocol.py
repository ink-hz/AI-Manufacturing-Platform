import json
from uuid import uuid4
import pytest
from manufacturing_platform.mes_access import relay_protocol as p

CONTEXT={'source':{'system':'mes','origin':'native','fact_role':'observation','environment':'production','site_code':'1000','namespace':'a'*64},'fingerprint':'b'*64}
def request(op,scope):
    return dict(version=1,request_id=str(uuid4()),operation=op,actor_hash='c'*64,expected_fingerprint=None if op=='describe' else 'b'*64,scope=scope)
def test_context_and_closed_operations():
    assert p.validate_context(CONTEXT)==CONTEXT
    for op,scope in [('describe',{}),('source_orders',{'prefix':'MO','after':''}),('order_materials',{'shop_order':'MO1'}),('material_priority',{'shop_order':'MO1','material':'123','page':1,'page_size':5}),('iqc_inspections',{'material':'123','page':1,'page_size':5})]:
        assert p.parse_request(json.dumps(request(op,scope)).encode())['operation']==op
@pytest.mark.parametrize('op,scope',[('query',{}),('material_priority',{'shop_order':'MO1','material':'','page':1,'page_size':5}),('iqc_inspections',{'material':'x','page':True,'page_size':5}),('source_orders',{'prefix':'%','after':''}),('order_materials',{'shop_order':'x','url':'x'})])
def test_rejects_open_or_unbounded_requests(op,scope):
    with pytest.raises(p.RelayProtocolError):p.parse_request(json.dumps(request(op,scope)).encode())
def test_nonce_and_null_safe_error():
    rid=str(uuid4())
    envelope=dict(version=1,request_id=rid,context=None,result=None,error={'code':'MES_TIMEOUT'})
    assert p.validate_response(envelope,request_id=rid)==envelope
    with pytest.raises(p.RelayProtocolError):p.validate_response(envelope,request_id=str(uuid4()))
    envelope['error']['code']=None
    with pytest.raises(p.RelayProtocolError):p.validate_response(envelope,request_id=rid)
@pytest.mark.parametrize('code',['MES_INVALID_COOKIE','MES_LOGIN_CONTRACT_CHANGED','MES_TRANSPORT_ERROR','MES_UNSUPPORTED_ENCODING','MES_OPERATION_FAILED'])
def test_known_native_failures_remain_safe_codes(code):
    rid=str(uuid4())
    p.validate_response(dict(version=1,request_id=rid,context=None,result=None,error={'code':code}),request_id=rid)


@pytest.mark.parametrize('operation,scope', [
    ('source_orders', {'prefix':'WO','after':'WO_5'}),
    ('order_materials', {'shop_order':'WO_5'}),
    ('material_priority', {'shop_order':'WO_5','material':'MAT','page':1,'page_size':5}),
])
def test_exact_order_identifier_accepts_underscore(operation, scope):
    from uuid import uuid4
    request = dict(version=1,request_id=str(uuid4()),operation=operation,actor_hash='a'*64,expected_fingerprint='b'*64,scope=scope)
    assert p.parse_request(json.dumps(request).encode())['scope'] == scope


@pytest.mark.parametrize('operation,scope', [
    ('source_orders', {'prefix':'WO_','after':''}),
    ('source_orders', {'prefix':'','after':'W'*65}),
    ('order_materials', {'shop_order':'W'*65}),
])
def test_prefix_wildcard_and_overlong_exact_order_denied(operation, scope):
    from uuid import uuid4
    request=dict(version=1,request_id=str(uuid4()),operation=operation,actor_hash='a'*64,expected_fingerprint='b'*64,scope=scope)
    with pytest.raises(p.RelayProtocolError):p.parse_request(json.dumps(request).encode())

@pytest.mark.parametrize('site_code',['SITE_A','_SITE','-SITE','a'*32])
def test_native_site_code_context_grammar(site_code):
    import copy
    context=copy.deepcopy(CONTEXT);context['source']['site_code']=site_code
    assert p.validate_context(context)==context

@pytest.mark.parametrize('site_code',['SITE.A','a'*33,'SITE/A',''])
def test_context_rejects_non_native_site_codes(site_code):
    import copy
    context=copy.deepcopy(CONTEXT);context['source']['site_code']=site_code
    with pytest.raises(p.RelayProtocolError):p.validate_context(context)
