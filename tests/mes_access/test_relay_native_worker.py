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
    def expire(argv,**kw):
        assert kw['timeout']==65
        assert kw['stderr']==subprocess.DEVNULL
        assert 'secret' not in repr(argv)
        raise subprocess.TimeoutExpired(argv,65)
    monkeypatch.setattr(subprocess,'run',expire)
    with pytest.raises(MesAccessError,match='MES_TIMEOUT'):isolated_dispatch('/secret','/audit',{})
