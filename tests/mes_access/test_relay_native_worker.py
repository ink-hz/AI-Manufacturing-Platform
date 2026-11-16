import json,subprocess,sys
from pathlib import Path
from manufacturing_platform.mes_access.relay_gateway import isolated_dispatch
from manufacturing_platform.mes_access.errors import MesAccessError
import pytest

def test_worker_isolated_entrypoint_sanitizes_invalid_input():
    worker=Path(__file__).parents[2]/'src/manufacturing_platform/mes_access/relay_native_worker.py'
    result=subprocess.run([sys.executable,'-I',str(worker)],input=b'{"password":"private"}',stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
    assert result.returncode==0
    assert json.loads(result.stdout)=={'error':'MES_RELAY_UNAVAILABLE'}
    assert result.stderr==b''
def test_hard_deadline_terminates_native_child(monkeypatch):
    class ExpiringChild:
        def communicate(self,payload,timeout):
            assert timeout==65
            raise subprocess.TimeoutExpired([],65)
        def poll(self):return None
        def terminate(self):pass
        def wait(self,timeout):pass
    def expire(argv,**kw):
        assert kw['stderr']==subprocess.DEVNULL
        assert 'secret' not in repr(argv)
        return ExpiringChild()
    monkeypatch.setattr(subprocess,'Popen',expire)
    with pytest.raises(MesAccessError,match='MES_TIMEOUT'):isolated_dispatch('/secret','/audit',{})

def test_worker_guard_stops_after_parent_sigkill(tmp_path):
    marker=tmp_path/'continued'
    worker=tmp_path/'worker.py'
    root=Path(__file__).parents[2]/'src'
    worker.write_text(f"import sys,os,time\nsys.path.insert(0,{str(root)!r})\nfrom manufacturing_platform.mes_access.relay_native_worker import guard_parent\nguard_parent(int(sys.argv[1]))\nprint('ready',flush=True)\ntime.sleep(1)\nopen({str(marker)!r},'w').write('continued')\n")
    controller=tmp_path/'parent.py'
    controller.write_text(f"import subprocess,sys,os\np=subprocess.Popen([sys.executable,{str(worker)!r},str(os.getpid())],stdout=subprocess.PIPE)\nprint(p.stdout.readline().decode().strip(),flush=True)\nsys.stdin.read()\n")
    p=subprocess.Popen([sys.executable,str(controller)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        assert p.stdout.readline()==b'ready\n'
        p.kill();p.wait(timeout=5)
        import time;time.sleep(1.3)
        assert not marker.exists()
    finally:
        if p.poll() is None:p.kill();p.wait()

@pytest.mark.parametrize('method',['shutdown','server_close'])
def test_gateway_close_terminates_and_reaps_children(tmp_path,monkeypatch,method):
    from manufacturing_platform.mes_access.relay_gateway import NativeChildren,Gateway,ThreadingHTTPServer
    marker=tmp_path/'continued'
    worker=tmp_path/'continuing.py'
    worker.write_text(f"import time\nprint('ready',flush=True)\ntime.sleep(1)\nopen({str(marker)!r},'w').write('continued')\n")
    gateway=object.__new__(Gateway);gateway.native_children=NativeChildren()
    child=gateway.native_children.start([sys.executable,str(worker)])
    assert child.stdout.readline()==b'ready\n'
    monkeypatch.setattr(ThreadingHTTPServer,method,lambda _:None)
    getattr(gateway,method)()
    assert child.poll() is not None and not gateway.native_children.children
    import time;time.sleep(1.2)
    assert not marker.exists()
