import http.client,json,threading
from uuid import uuid4
from manufacturing_platform.mes_access.relay_gateway import build_gateway,dispatch
from manufacturing_platform.mes_access.errors import MesAccessError
from .test_relay_protocol import CONTEXT,request
import pytest
class Native:
    def read_context(self):return CONTEXT
    def query(self,*args,**kw):return {'called':args,'pin':kw['expected_fingerprint']}
def test_dispatch_fixed_scopes_and_pin():
    r=dispatch(Native(),request('material_priority',{'shop_order':'MO1','material':'12','page':2,'page_size':5}))
    assert r['result']['called'][:4]==('material_priority',{'shopOrder':'MO1','itemNo':'12'},2,5)
    assert r['result']['pin']==CONTEXT['fingerprint']
def test_gateway_authentication_precedes_native_context(tmp_path):
    class Unreadable:
        def read_context(self):raise AssertionError('must not read config')
    token=tmp_path/'token';token.write_text('a'*64);token.chmod(0o600)
    server=build_gateway('/unused','/unused',str(token),service=Unreadable())
    t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
    try:
        c=http.client.HTTPConnection('127.0.0.1',server.server_port)
        c.request('POST','/v1/read',b'{}',{'Content-Type':'application/json'})
        res=c.getresponse();assert res.status==401
        assert json.loads(res.read())['error']['code']=='MES_RELAY_UNAUTHORIZED'
        c.close()
    finally:server.shutdown();server.server_close();t.join()
def test_dispatch_stale_pin_rejected():
    q=request('order_materials',{'shop_order':'MO1'});q['expected_fingerprint']='f'*64
    with pytest.raises(MesAccessError):dispatch(Native(),q)
