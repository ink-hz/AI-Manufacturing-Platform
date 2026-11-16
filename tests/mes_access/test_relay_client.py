import json
from uuid import uuid4
import pytest
from manufacturing_platform.mes_access.relay_client import RelayMesAccessService,validate_result
from manufacturing_platform.mes_access.selector import MesAccessSelector
from manufacturing_platform.mes_access.errors import MesAccessError
from .test_relay_protocol import CONTEXT

def configured(tmp_path):
    token=tmp_path/'token';token.write_text('d'*64);token.chmod(0o600)
    cfg=dict(version=1,transport='mac_read_relay',enabled=True,read_only=True,environment='production',socket_path='/tmp/mes-test.sock',token_path=str(token),expected_context=CONTEXT,timeout_seconds=70,max_response_bytes=2097152)
    path=tmp_path/'cfg';path.write_text(json.dumps(cfg));path.chmod(0o600)
    return RelayMesAccessService(str(path),str(tmp_path/'audit'))
def test_local_context_uses_cloud_binding_and_factory_is_lazy(tmp_path):
    MesAccessSelector('/abs/missing','/abs/audit')
    service=configured(tmp_path)
    c=service.read_context();assert c['source']==CONTEXT['source'];assert c['fingerprint']!=CONTEXT['fingerprint']
    assert service.configuration_matches(c['fingerprint'])
def test_query_requires_exact_scope_before_io(tmp_path):
    service=configured(tmp_path)
    with pytest.raises(MesAccessError):service.query('material_priority',{'shopOrder':'M'},actor_id='a')
    with pytest.raises(MesAccessError):service.query('iqc_inspections',{'item_no':'x','status':'x'},actor_id='a')
def test_result_scope_rejects_cross_order():
    result=dict(rows=[{'SHOP_ORDER':'other','MATNR':'123'}],total_items=1,page=1,page_size=5,interface='material_priority',source='native_mes',authentication_verified=True,business_query_succeeded=True,business_data_verified=False,business_reconciled=False,request_id=str(uuid4()))
    with pytest.raises(MesAccessError):validate_result(result,'material_priority',{'shop_order':'M','material':'123','page':1,'page_size':5},CONTEXT)

def test_source_orders_roundtrip_keeps_native_namespace_but_cloud_binding(tmp_path,monkeypatch):
    from manufacturing_platform.mes_access import relay_client as c
    service=configured(tmp_path)
    def exchange(sock,token,command,timeout,max_bytes):
        assert command['expected_fingerprint']==CONTEXT['fingerprint']
        r=dict(source=CONTEXT['source'],fingerprint=CONTEXT['fingerprint'],items=[{'shop_order':'M1','description':'Order'}],next_cursor=None,total=None,page_size=5,request_id=str(uuid4()))
        return dict(version=1,request_id=command['request_id'],context=CONTEXT,result=r,error=None),100
    monkeypatch.setattr(c,'_exchange_result',exchange)
    result=service.source_orders('M','',actor_id='operator')
    assert result['fingerprint']==service.read_context()['fingerprint']
    assert result['source']==CONTEXT['source']
    assert result['items'][0]['shop_order']=='M1'

def test_unknown_or_null_transport_error_is_sanitized(monkeypatch):
    import subprocess
    from manufacturing_platform.mes_access import relay_client as c
    command=dict(version=1,request_id=str(uuid4()),operation='describe',actor_hash='0'*64,expected_fingerprint=None,scope={})
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:subprocess.CompletedProcess([],0,b'{"error":null}'))
    with pytest.raises(MesAccessError,match='MES_RELAY_INVALID_RESPONSE'):c.exchange('/tmp/x','d'*64,command)


def test_relay_validates_underscore_source_cursor():
    result=dict(source=CONTEXT['source'],fingerprint=CONTEXT['fingerprint'],items=[{'shop_order':f'WO_{i}','description':None} for i in range(1,6)],next_cursor='WO_5',total=None,page_size=5,request_id=str(uuid4()))
    assert validate_result(result,'source_orders',{'prefix':'WO','after':''},CONTEXT)['next_cursor']=='WO_5'


def test_full_identity_page_requires_roundtrippable_cursor():
    result=dict(source=CONTEXT['source'],fingerprint=CONTEXT['fingerprint'],items=[{'shop_order':f'WO_{i}','description':None} for i in range(1,6)],next_cursor=None,total=None,page_size=5,request_id=str(uuid4()))
    with pytest.raises(MesAccessError):validate_result(result,'source_orders',{'prefix':'WO','after':''},CONTEXT)
