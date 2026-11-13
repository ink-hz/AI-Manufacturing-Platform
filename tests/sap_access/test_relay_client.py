import pytest

def test_factory_is_lazy_and_returns_selector(tmp_path, monkeypatch):
    from manufacturing_platform.sap_access import build_sap_access_service
    monkeypatch.setattr('os.open', lambda *a, **kw: pytest.fail('constructor file I/O'))
    monkeypatch.setattr('socket.socket', lambda *a, **kw: pytest.fail('constructor network I/O'))
    service = build_sap_access_service(str(tmp_path/'missing'), str(tmp_path/'audit'))
    assert type(service).__name__ == 'SapAccessSelector'
    assert callable(service.production_order)

def test_exchange_missing_socket_is_safe():
    from manufacturing_platform.sap_access.relay_client import exchange
    from manufacturing_platform.sap_access.errors import SapAccessError
    with pytest.raises(SapAccessError, match='SAP_RELAY_UNAVAILABLE'):
        exchange('/tmp/nonexistent-sap-relay-test.sock', 'a'*64, describe_command(), timeout=1)

import json
import socket
import threading
from uuid import uuid4
from manufacturing_platform.sap_access.relay_client import RelaySapAccessService, exchange
from manufacturing_platform.sap_access.errors import SapAccessError

def describe_command():
    return {'version':1,'request_id':str(uuid4()),'operation':'describe','actor_hash':'a'*64,'expected_fingerprint':None,'scope':{}}

CONTEXT={'source':{'system':'sap','origin':'native','fact_role':'observation','environment':'test','system_id':'TST','client':'100','namespace':'a'*64},'fingerprint':'b'*64}

def setup_config(tmp_path):
    token=tmp_path/'token'; token.write_text('c'*64); token.chmod(0o600)
    cfg={'version':1,'transport':'mac_read_relay','enabled':True,'read_only':True,'environment':'test','socket_path':'/tmp/sap-test-unused.sock','token_path':str(token),'expected_context':CONTEXT,'timeout_seconds':1,'max_response_bytes':2097152}
    path=tmp_path/'config'; path.write_text(json.dumps(cfg));path.chmod(0o600)
    from manufacturing_platform.sap_access import build_sap_access_service
    return build_sap_access_service(str(path),str(tmp_path/'audit')),cfg,path

def server(path, handler):
    sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);sock.bind(path);sock.listen()
    def serve():
        try:
            conn,_=sock.accept()
            with conn:
                data=b''
                while b'\r\n\r\n' not in data: data+=conn.recv(4096)
                head,body=data.split(b'\r\n\r\n',1)
                size=int([x for x in head.split(b'\r\n') if x.lower().startswith(b'content-length:')][0].split(b':')[1])
                while len(body)<size: body+=conn.recv(4096)
                response=handler(head,json.loads(body))
                conn.sendall(response)
        finally:sock.close()
    thread=threading.Thread(target=serve,daemon=True);thread.start();return thread

def response(value):
    body=json.dumps(value).encode()
    return b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body

def order_result():
    return {'number':'000000000123','plant':'1000','material':'MAT1','description':'Synthetic','quantity':'10.000','unit':'EA','components':[{'component_key':'1:1:','material':'MAT2','plant':'1000','storage_location':'0001','required_quantity':'5','withdrawn_quantity':'0','unit':'EA','required_at':'20261113'}],'total':1,'function':'BAPI_PRODORD_GET_DETAIL','source':CONTEXT['source'],'request_id':str(uuid4())}

def test_local_context_and_config_switch_fail_before_io(tmp_path,monkeypatch):
    service,cfg,path=setup_config(tmp_path)
    binding=service.read_context()['fingerprint']
    assert binding!=CONTEXT['fingerprint']
    cfg['socket_path']='/tmp/changed.sock';path.write_text(json.dumps(cfg))
    monkeypatch.setattr('manufacturing_platform.sap_access.relay_client._exchange_result',lambda *a:pytest.fail('I/O'))
    with pytest.raises(SapAccessError,match='SAP_CONFIGURATION_ERROR'):
        service.production_order('123','1000','actor',expected_fingerprint=binding)

@pytest.mark.parametrize('tamper',['none','request','context','plant','quantity','duplicate','extra','source'])
def test_real_unix_native_order_validation(tmp_path,tamper):
    import tempfile
    service,cfg,path=setup_config(tmp_path)
    # macOS sun_path limit requires a short synthetic socket pathname.
    with tempfile.TemporaryDirectory(prefix='sr-',dir='/tmp') as directory:
        cfg['socket_path']=directory+'/s';path.write_text(json.dumps(cfg))
        def handler(head,command):
            assert head.startswith(b'POST /v1/read HTTP/1.1')
            assert b'Authorization: Bearer '+b'c'*64 in head
            assert command['expected_fingerprint']==CONTEXT['fingerprint']
            assert json.loads((tmp_path/'audit').read_text())['events'][-1]['status']=='started'
            value={'version':1,'request_id':command['request_id'],'context':CONTEXT,'result':order_result(),'error':None}
            if tamper=='request':value['request_id']=str(uuid4())
            if tamper=='context':value['context']={**CONTEXT,'fingerprint':'d'*64}
            if tamper=='plant':value['result']['components'][0]['plant']='2000'
            if tamper=='quantity':value['result']['quantity']=1.5
            if tamper=='duplicate':value['result']['components']*=2;value['result']['total']=2
            if tamper=='extra':value['result']['unexpected']='field'
            if tamper=='source':value['result']['source']='native_sap'
            return response(value)
        thread=server(cfg['socket_path'],handler)
        if tamper=='none':assert service.production_order('123','1000','actor')['number']=='000000000123'
        else:
            with pytest.raises(SapAccessError,match='SAP_RELAY_INVALID_RESPONSE'):service.production_order('123','1000','actor')
        thread.join(2)
        audit=(tmp_path/'audit').read_text()
        assert 'Synthetic' not in audit and 'MAT1' not in audit and 'c'*64 not in audit

@pytest.mark.parametrize('raw,code',[(b'HTTP/1.1 401 Unauthorized\r\n\r\n','SAP_RELAY_UNAUTHORIZED'),(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 9999999\r\n\r\n','SAP_RELAY_RESPONSE_TOO_LARGE'),(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nContent-Length: 2\r\n\r\n{}','SAP_RELAY_INVALID_RESPONSE')])
def test_worker_headers(tmp_path,raw,code):
    import tempfile
    with tempfile.TemporaryDirectory(prefix='sr-',dir='/tmp') as directory:
        path=directory+'/s';thread=server(path,lambda *_:raw)
        with pytest.raises(SapAccessError,match=code):exchange(path,'c'*64,describe_command(),1)
        thread.join(2)

@pytest.mark.parametrize('change',[{'read_only':False},{'environment':'production'},{'timeout_seconds':True},{'max_response_bytes':9999999},{'extra':'no'}])
def test_strict_config(tmp_path,change):
    service,cfg,path=setup_config(tmp_path);cfg.update(change);path.write_text(json.dumps(cfg))
    with pytest.raises(SapAccessError,match='SAP_CONFIGURATION_ERROR'):service.read_context()


def test_worker_hard_deadline(tmp_path):
    import tempfile,time
    with tempfile.TemporaryDirectory(prefix='sr-',dir='/tmp') as directory:
        path=directory+'/s'
        def stall(*_):
            time.sleep(1.3)
            return response({})
        # Ignore the expected broken pipe after hard cancellation.
        sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);sock.bind(path);sock.listen()
        def hold():
            conn,_=sock.accept()
            with conn:time.sleep(1.5)
            sock.close()
        thread=threading.Thread(target=hold,daemon=True);thread.start()
        start=time.monotonic()
        with pytest.raises(SapAccessError,match='SAP_TIMEOUT'):exchange(path,'c'*64,describe_command(),1)
        assert time.monotonic()-start<1.4
        thread.join(2)

@pytest.mark.parametrize('code',['SAP_BUSINESS_FAILURE','SAP_AUTHENTICATION_FAILED','SAP_RELAY_BUSY','SAP_RELAY_CONTEXT_MISMATCH'])
def test_source_business_errors_preserved(tmp_path,code):
    import tempfile
    service,cfg,path=setup_config(tmp_path)
    with tempfile.TemporaryDirectory(prefix='sr-',dir='/tmp') as directory:
        cfg['socket_path']=directory+'/s';path.write_text(json.dumps(cfg))
        def handler(_,command):
            return response({'version':1,'request_id':command['request_id'],'context':None,'result':None,'error':{'code':code}}).replace(b'200 OK',b'503 Unavailable')
        thread=server(cfg['socket_path'],handler)
        with pytest.raises(SapAccessError,match=code):service.production_order('123','1000','actor')
        thread.join(2)

@pytest.mark.parametrize('change',['none','material','plant','return','rows','float'])
def test_native_mrp_shape_scope_and_raw_fields(tmp_path,change):
    from manufacturing_platform.sap_access.relay_client import validate_result
    result={'return':{'TYPE':'S','MESSAGE':''},'mrp_list':{'MATERIAL':'000000000000000123','PLANT':'1000','BASE_UOM':'EA'},'items':[{'MRP_ELEMENT':'AA','REC_REQD_QTY':'-1.000','UNRESTRICTED_STCK':'2.000'}],'function':'BAPI_MATERIAL_STOCK_REQ_LIST','source':'native_sap','request_id':str(uuid4())}
    if change=='material':result['mrp_list']['MATERIAL']='124'
    if change=='plant':result['mrp_list']['PLANT']='2000'
    if change=='return':result['return']['TYPE']='E'
    if change=='rows':result['items']*=51
    if change=='float':result['items'][0]['REC_REQD_QTY']=1.0
    if change=='none':assert validate_result(result,'stock_requirements',{'material':'123','plant':'1000'},CONTEXT['source'])==result
    else:
        with pytest.raises(SapAccessError,match='SAP_RELAY_INVALID_RESPONSE'):validate_result(result,'stock_requirements',{'material':'123','plant':'1000'},CONTEXT['source'])


def test_describe_bootstrap_and_no_secret_in_process_arguments(tmp_path,monkeypatch):
    import tempfile
    from manufacturing_platform.sap_access import relay_client
    original=relay_client.subprocess.run
    def checked(argv,**kwargs):
        assert 'c'*64 not in repr(argv)
        assert kwargs.get('stderr')==relay_client.subprocess.DEVNULL
        return original(argv,**kwargs)
    monkeypatch.setattr(relay_client.subprocess,'run',checked)
    with tempfile.TemporaryDirectory(prefix='sr-',dir='/tmp') as directory:
        path=directory+'/s';request_id=str(uuid4())
        command={'version':1,'request_id':request_id,'operation':'describe','actor_hash':'d'*64,'expected_fingerprint':None,'scope':{}}
        thread=server(path,lambda _,cmd:response({'version':1,'request_id':cmd['request_id'],'context':CONTEXT,'result':{},'error':None}))
        reply=exchange(path,'c'*64,command,1)
        from manufacturing_platform.sap_access.relay_protocol import validate_response
        assert validate_response(reply,request_id=request_id)['context']==CONTEXT
        thread.join(2)


def test_audit_failure_prevents_exchange(tmp_path,monkeypatch):
    service,_,_=setup_config(tmp_path)
    (tmp_path/'audit.lock').write_text('not private')
    (tmp_path/'audit.lock').chmod(0o644)
    monkeypatch.setattr('manufacturing_platform.sap_access.relay_client._exchange_result',lambda *a:pytest.fail('I/O before audit'))
    with pytest.raises(SapAccessError,match='SAP_AUDIT_UNAVAILABLE'):
        service.production_order('123','1000','actor')


def test_private_config_token_alias_rejected(tmp_path):
    service,cfg,path=setup_config(tmp_path)
    cfg['token_path']=str(path);path.write_text(json.dumps(cfg))
    with pytest.raises(SapAccessError,match='SAP_CONFIGURATION_ERROR'):service.read_context()


def test_real_unix_mrp_query_preserves_raw_strings(tmp_path):
    import tempfile
    service,cfg,path=setup_config(tmp_path)
    with tempfile.TemporaryDirectory(prefix='sr-',dir='/tmp') as directory:
        cfg['socket_path']=directory+'/s';path.write_text(json.dumps(cfg))
        upstream_id=str(uuid4())
        def handler(_,command):
            assert command['operation']=='stock_requirements'
            assert command['scope']=={'material':'123','plant':'1000'}
            result={'return':{'TYPE':'S'},'mrp_list':{'MATERIAL':'000123','PLANT':'1000'},'items':[{'REC_REQD_QTY':'-1.000','MRP_ELEMENT':'AA'}],'function':'BAPI_MATERIAL_STOCK_REQ_LIST','source':'native_sap','request_id':upstream_id}
            return response({'version':1,'request_id':command['request_id'],'context':CONTEXT,'result':result,'error':None})
        thread=server(cfg['socket_path'],handler)
        result=service.stock_requirements('123','1000','actor',expected_fingerprint=service.read_context()['fingerprint'])
        assert result['items']==[{'REC_REQD_QTY':'-1.000','MRP_ELEMENT':'AA'}]
        assert result['request_id']!=upstream_id
        assert json.loads((tmp_path/'audit').read_text())['events'][-1]['source_request_id']==upstream_id
        thread.join(2)

@pytest.mark.parametrize('header',[b'X-Test: '+b'a'*17000+b'\r\n',b'Transfer-Encoding: chunked\r\n',b'Content-Encoding: gzip\r\n'])
def test_worker_rejects_oversized_or_unsupported_headers(tmp_path,header):
    import tempfile
    with tempfile.TemporaryDirectory(prefix='sr-',dir='/tmp') as directory:
        path=directory+'/s'
        raw=b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\n'+header+b'\r\n{}'
        thread=server(path,lambda *_:raw)
        with pytest.raises(SapAccessError,match='SAP_RELAY_INVALID_RESPONSE'):exchange(path,'c'*64,describe_command(),1)
        thread.join(2)
