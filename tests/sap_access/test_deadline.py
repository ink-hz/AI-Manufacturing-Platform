import socket
import threading
import time
import pytest
from .test_transport import config
from manufacturing_platform.sap_access.transport import SoapTransport
from manufacturing_platform.sap_access.errors import SapAccessError

@pytest.mark.parametrize('phase',['headers','body'])
def test_total_deadline_rejects_trickled_response(phase):
    listener=socket.socket(); listener.bind(('127.0.0.1',0)); listener.listen(1)
    port=listener.getsockname()[1]
    def serve():
        try:
            conn,_=listener.accept()
            with conn:
                conn.recv(4096)
                if phase=='headers':
                    for data in [b'HTTP/1.1 200 OK\r\n',b'Content-Type: text/xml\r\n',b'Content-Length: 4\r\n',b'\r\n',b'<x/>']:
                        conn.sendall(data); time.sleep(.30)
                else:
                    conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: text/xml\r\nContent-Length: 4\r\n\r\n')
                    for byte in b'<x/>': conn.sendall(bytes([byte])); time.sleep(.35)
        except OSError: pass
        finally: listener.close()
    thread=threading.Thread(target=serve,daemon=True); thread.start()
    c=config(application_server='127.0.0.1',http_port=port,http_scheme='http',allow_http_test=True,timeout_seconds=1)
    start=time.monotonic()
    with pytest.raises(SapAccessError) as err: SoapTransport(c).fetch_wsdl('RFC_PING')
    assert err.value.code=='SAP_TIMEOUT' and time.monotonic()-start < 1.5
    thread.join(3)

def test_delayed_resolution_is_killed_and_reaped(monkeypatch):
    import subprocess, sys
    import manufacturing_platform.sap_access.transport as module
    original=subprocess.Popen; processes=[]
    def delayed(args, **kwargs):
        code='import socket,time,runpy,sys; socket.getaddrinfo=lambda *a,**k: time.sleep(5); runpy.run_path(sys.argv[1],run_name="__main__")'
        p=original([sys.executable,'-I','-c',code,args[-1]],**kwargs); processes.append(p); return p
    monkeypatch.setattr(module.subprocess,'Popen',delayed)
    c=config(application_server='slow.invalid',timeout_seconds=1)
    started=time.monotonic()
    with pytest.raises(SapAccessError) as err: SoapTransport(c).fetch_wsdl('RFC_PING')
    assert err.value.code=='SAP_TIMEOUT' and time.monotonic()-started < 1.5
    assert len(processes)==1 and processes[0].poll() is not None

def test_worker_never_returns_echoed_credentials(monkeypatch, capsys):
    import io, json, base64, sys
    from manufacturing_platform.sap_access import http_worker
    request={'config':{},'method':'GET','path':'/','body':None,'headers':{'Authorization':'Basic '+base64.b64encode(b'user-secret:password-secret').decode()},'timeout':1,'max_bytes':1024}
    monkeypatch.setattr(http_worker,'exchange',lambda *a: (200,{'Content-Type':'text/xml'},b'<x>password-secret</x>'))
    monkeypatch.setattr(sys,'stdin',io.StringIO(json.dumps(request)))
    http_worker.main()
    output=capsys.readouterr().out
    assert 'password-secret' not in output and json.loads(output)['error']=='SAP_INVALID_RESPONSE'

def test_fast_loopback_exchange_completes_and_reaps(monkeypatch):
    import subprocess
    listener=socket.socket(); listener.bind(('127.0.0.1',0)); listener.listen(1)
    port=listener.getsockname()[1]
    def serve():
        conn,_=listener.accept()
        with conn:
            conn.recv(4096); conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: text/xml\r\nContent-Length: 4\r\n\r\n<x/>')
        listener.close()
    thread=threading.Thread(target=serve,daemon=True);thread.start()
    real=subprocess.Popen; children=[]
    def observe(args, **kwargs):
        assert 'TEST-SECRET' not in repr(args) and 'TEST-ACCOUNT' not in repr(args)
        child=real(args,**kwargs);children.append(child);return child
    monkeypatch.setattr(subprocess,'Popen',observe)
    c=config(application_server='127.0.0.1',http_port=port,http_scheme='http',allow_http_test=True,timeout_seconds=1)
    started=time.monotonic(); assert SoapTransport(c).fetch_wsdl('RFC_PING')==b'<x/>'
    assert time.monotonic()-started<1 and children[0].poll() is not None
    thread.join(1)
