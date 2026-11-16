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

def test_interfaces_advertise_only_exact_generic_queries(tmp_path):
    entries=configured(tmp_path).interfaces()['interfaces']
    assert {e['interface'] for e in entries}=={'material_priority','iqc_inspections'}
    assert {e['interface']:e['required_filters'] for e in entries}=={'material_priority':['shopOrder','itemNo'],'iqc_inspections':['item_no']}

def test_cloud_audit_retains_validated_upstream_uuid(tmp_path,monkeypatch):
    from manufacturing_platform.mes_access import relay_client as c
    from manufacturing_platform.mes_access.store import MesAuditStore
    service=configured(tmp_path);upstream=str(uuid4())
    def exchange(sock,token,command,timeout,max_bytes):
        result=dict(rows=[],total_items=0,page=1,page_size=5,interface='iqc_inspections',source='native_mes',authentication_verified=True,business_query_succeeded=True,business_data_verified=False,business_reconciled=False,request_id=upstream)
        return dict(version=1,request_id=command['request_id'],context=CONTEXT,result=result,error=None),100
    monkeypatch.setattr(c,'_exchange_result',exchange)
    service.query('iqc_inspections',{'item_no':'123'},1,5,'operator')
    event=MesAuditStore(service.audit_path).read()['events'][-1]
    assert event['source_request_ids']==[upstream]
    assert event['request_id']!=upstream

def test_collection_audit_retains_only_upstream_uuids(tmp_path,monkeypatch):
    from manufacturing_platform.mes_access import relay_client as c
    from manufacturing_platform.mes_access.store import MesAuditStore
    service=configured(tmp_path);upstream=[str(uuid4()),str(uuid4())]
    def exchange(sock,token,command,timeout,max_bytes):
        result=dict(namespace=CONTEXT['source']['namespace'],fingerprint=CONTEXT['fingerprint'],environment='production',site_code='1000',request_ids=upstream,total=1,components=[dict(component_key='1:1',material_id='123',required_quantity='2',withdrawn_quantity=None,unit='EA',storage_location=None)])
        return dict(version=1,request_id=command['request_id'],context=CONTEXT,result=result,error=None),100
    monkeypatch.setattr(c,'_exchange_result',exchange)
    service.collect_order_materials('M1','operator')
    event=MesAuditStore(service.audit_path).read()['events'][-1]
    assert event['source_request_ids']==upstream
    assert 'components' not in event and 'shop_order' not in event

@pytest.mark.parametrize('ids',[[],[str(uuid4())]*2,['bad'],[str(uuid4()).upper()],[str(uuid4()) for _ in range(21)]])
def test_audit_rejects_invalid_upstream_uuid_lists(tmp_path,ids):
    from datetime import datetime,timezone
    from manufacturing_platform.mes_access.store import MesAuditStore
    event=dict(request_id=str(uuid4()),operation='query',function='material_priority',timestamp=datetime.now(timezone.utc).isoformat(),status='success',actor_hash='a'*64,binding='b'*64,source_request_ids=ids)
    with pytest.raises(MesAccessError):MesAuditStore(str(tmp_path/'audit')).record(event)

def test_sap_audit_keeps_closed_default_fields(tmp_path):
    from manufacturing_platform.sap_access.store import SapAuditStore
    from manufacturing_platform.sap_access.errors import SapAccessError
    with pytest.raises(SapAccessError):SapAuditStore(str(tmp_path/'sap')).record({'source_request_ids':[str(uuid4())]})

@pytest.mark.parametrize('operation,status,function',[('query','started','material_priority'),('query','failed','iqc_inspections'),('diagnose','success',None)])
def test_audit_upstream_uuids_only_on_successful_queries(tmp_path,operation,status,function):
    from datetime import datetime,timezone
    from manufacturing_platform.mes_access.store import MesAuditStore
    event=dict(request_id=str(uuid4()),operation=operation,function=function,timestamp=datetime.now(timezone.utc).isoformat(),status=status,actor_hash='a'*64,binding='b'*64,source_request_ids=[str(uuid4())])
    with pytest.raises(MesAccessError):MesAuditStore(str(tmp_path/'audit')).record(event)

@pytest.mark.parametrize('site_code',['SITE_A','_SITE','-SITE'])
def test_cloud_factory_reads_native_site_code_locally(tmp_path,site_code):
    from manufacturing_platform.mes_access import build_mes_access_service
    service=configured(tmp_path)
    path=service.config_path
    config=json.loads(open(path).read());config['expected_context']['source']['site_code']=site_code
    with open(path,'w') as stream:json.dump(config,stream)
    selected=build_mes_access_service(path,service.audit_path)
    assert selected.read_context()['source']['site_code']==site_code
