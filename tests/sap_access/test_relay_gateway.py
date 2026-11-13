import json
import threading
import http.client
from uuid import uuid4
import pytest
from manufacturing_platform.sap_access.relay_protocol import parse_request, validate_response, RelayProtocolError, load_token
from manufacturing_platform.sap_access.relay_gateway import build_gateway

TOKEN='a'*64
CONTEXT={'source':{'system':'sap','origin':'native','fact_role':'observation','environment':'test','system_id':'TST','client':'100','namespace':'b'*64},'fingerprint':'c'*64}
def request(operation='describe'):
    return dict(version=1,request_id=str(uuid4()),operation=operation,actor_hash='d'*64,expected_fingerprint=None if operation=='describe' else 'c'*64,scope={} if operation=='describe' else {'number':'12','plant':'1000'})
class Service:
    def __init__(self): self.calls=[]
    def read_context(self): self.calls.append('context'); return CONTEXT
    def production_order(self,*args,**kwargs): self.calls.append((args,kwargs)); return {'native':'retained'}
@pytest.fixture
def gateway(tmp_path):
    token=tmp_path/'token'; token.write_text(TOKEN); token.chmod(0o600)
    service=Service(); server=build_gateway('/unused','/unused-audit',str(token),service=service)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    yield server,service
    server.shutdown();server.server_close();thread.join()
def send(gateway, payload, token=TOKEN, method='POST',path='/v1/read'):
    server,_=gateway; conn=http.client.HTTPConnection(*server.server_address,timeout=3)
    conn.request(method,path,body=payload,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    response=conn.getresponse(); data=response.read();conn.close();return response.status,json.loads(data)
def test_describe(gateway):
    value=request();status,result=send(gateway,json.dumps(value));assert status==200
    assert validate_response(result,request_id=value['request_id'])['context']==CONTEXT
    assert result['result']=={}
def test_auth_first(gateway):
    assert send(gateway,'not json',token='wrong')[0]==401
    assert gateway[1].calls==[]
@pytest.mark.parametrize('patch',[{'version':True},{'url':'http://bad'},{'operation':'ping'},{'scope':{'function':'bad'}},{'actor_hash':'x'}])
def test_bad_protocol(patch):
    value=request();value.update(patch)
    with pytest.raises(RelayProtocolError):parse_request(json.dumps(value).encode())
@pytest.mark.parametrize('payload',[b'{"version":1,"version":1}',b'{"x":NaN}',b' '*2049])
def test_bad_json(payload):
    with pytest.raises(RelayProtocolError):parse_request(payload)
def test_order_binding(gateway):
    value=request('production_order');status,result=send(gateway,json.dumps(value));assert status==200
    assert result['result']=={'native':'retained'}
    assert gateway[1].calls[1]==(('000000000012','1000','d'*64),{'expected_fingerprint':'c'*64})
def test_mismatch_before_query(gateway):
    value=request('production_order');value['expected_fingerprint']='e'*64
    assert send(gateway,json.dumps(value))[1]['error']=={'code':'SAP_RELAY_CONTEXT_MISMATCH'}
    assert gateway[1].calls==['context']
@pytest.mark.parametrize('method,path',[('GET','/v1/read'),('POST','/'),('PUT','/v1/read')])
def test_route_closed(gateway,method,path):
    assert send(gateway,'{}',method=method,path=path)[0]>=400
    assert gateway[1].calls==[]
def test_private_token(tmp_path):
    path=tmp_path/'token';path.write_text(TOKEN);path.chmod(0o644)
    with pytest.raises(RelayProtocolError):load_token(str(path))

def test_changed_context_after_read(gateway):
    server,service=gateway
    def changed(*args,**kwargs):
        service.read_context=lambda: {**CONTEXT,'fingerprint':'e'*64}
        return {'discard':'data'}
    service.production_order=changed
    status,value=send(gateway,json.dumps(request('production_order')))
    assert status==409 and value['result'] is None

def test_safe_exception(gateway,capsys):
    def broken(*args,**kwargs):raise RuntimeError('PRIVATE SECRET')
    gateway[1].production_order=broken
    _,value=send(gateway,json.dumps(request('production_order')))
    assert value['error']=={'code':'SAP_RELAY_UNAVAILABLE'}
    assert 'PRIVATE' not in json.dumps(value)+str(capsys.readouterr())

def test_four_source_queries_maximum(gateway):
    from concurrent.futures import ThreadPoolExecutor
    server,service=gateway;entered=threading.Event();release=threading.Event();lock=threading.Lock();count=0
    def blocked(*args,**kwargs):
        nonlocal count
        with lock:
            count+=1
            if count==4:entered.set()
        assert release.wait(3)
        return {}
    service.production_order=blocked
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(send,gateway,json.dumps(request('production_order'))) for _ in range(4)]
        try:
            assert entered.wait(3)
            assert send(gateway,json.dumps(request('production_order')))[1]['error']=={'code':'SAP_RELAY_BUSY'}
        finally:release.set()
        assert all(f.result()[0]==200 for f in futures)
    assert count==4

def test_response_size(gateway):
    gateway[1].production_order=lambda *args,**kwargs:{'large':'a'*(2*1024*1024)}
    assert send(gateway,json.dumps(request('production_order')))[1]['error']=={'code':'SAP_RELAY_RESPONSE_TOO_LARGE'}

def test_private_json_rejects_duplicates_and_symlinks(tmp_path):
    from manufacturing_platform.sap_access.relay_protocol import read_private_json
    path=tmp_path/'config';path.write_text('{"x":1,"x":2}');path.chmod(0o600)
    with pytest.raises(RelayProtocolError):read_private_json(str(path))
    link=tmp_path/'link';link.symlink_to(path)
    with pytest.raises(RelayProtocolError):read_private_json(str(link))

@pytest.mark.parametrize('mutate',[lambda v:v.update(extra=True),lambda v:v.update(version=True),lambda v:v.update(context={}),lambda v:v.update(result=[]),lambda v:v.update(error={'code':'PRIVATE_SECRET'})])
def test_response_fail_closed(mutate):
    value={'version':1,'request_id':str(uuid4()),'context':CONTEXT,'result':{},'error':None};mutate(value)
    with pytest.raises(RelayProtocolError):validate_response(value,request_id=value['request_id'])

def test_stock_native_validation():
    value=request('stock_requirements');value['scope']={'material':'X'*19,'plant':'1000'}
    with pytest.raises(RelayProtocolError):parse_request(json.dumps(value).encode())

def test_oversize_and_duplicate_headers(gateway):
    assert send(gateway,' '*2049)[0]==400
    conn=http.client.HTTPConnection(*gateway[0].server_address,timeout=3)
    conn.putrequest('POST','/v1/read');conn.putheader('Authorization','Bearer '+TOKEN);conn.putheader('Content-Type','application/json');conn.putheader('Content-Length','2');conn.putheader('Content-Length','2');conn.endheaders(b'{}')
    assert conn.getresponse().status==400;conn.close()
    assert gateway[1].calls==[]

def test_handler_capacity_bounded(gateway):
    assert gateway[0].handler_slots._value==16

def test_truncated_body(gateway):
    import socket
    with socket.create_connection(gateway[0].server_address,timeout=3) as connection:
        connection.sendall(('POST /v1/read HTTP/1.0\r\nAuthorization: Bearer '+TOKEN+'\r\nContent-Type: application/json\r\nContent-Length: 99\r\n\r\n{}').encode())
        connection.shutdown(socket.SHUT_WR)
        assert b'400' in connection.recv(4096)
    assert gateway[1].calls==[]

def test_cli_private_ready_and_ownership(tmp_path,monkeypatch):
    import os
    from manufacturing_platform.sap_access import relay_gateway as module
    ready=tmp_path/'ready'
    class Server:
        server_port=12345
        service=Service()
        def serve_forever(self):
            info=json.loads(ready.read_text())
            assert set(info)=={'pid','port','generation'} and info['pid']==os.getpid()
            assert ready.stat().st_mode&0o777==0o600
        def server_close(self):pass
    monkeypatch.setattr(module,'build_gateway',lambda *args,**kwargs:Server())
    monkeypatch.setattr(module.signal,'signal',lambda *args:None)
    module.main(['--config','/private/config','--audit','/private/audit','--token','/private/token','--ready',str(ready)])
    assert not ready.exists()
    def replace(self):
        ready.write_text(json.dumps({'pid':1,'port':2,'generation':'another-instance'}));ready.chmod(0o600)
    monkeypatch.setattr(Server,'serve_forever',replace)
    module.main(['--config','/private/config','--audit','/private/audit','--token','/private/token','--ready',str(ready)])
    assert json.loads(ready.read_text())['generation']=='another-instance'

def test_context_uses_native_system_id_contract():
    from manufacturing_platform.sap_access.relay_protocol import validate_context
    with pytest.raises(RelayProtocolError):validate_context({**CONTEXT,'source':{**CONTEXT['source'],'system_id':'123'}})
