"""Native child with its own deadline and gateway-liveness enforcement."""
import os,signal,threading,time
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from manufacturing_platform.mes_access.relay_protocol import parse_request,SAFE_CODES
from manufacturing_platform.mes_access.errors import MesAccessError

def guard_parent(parent_pid):
    """Bound the entire child, even if its gateway disappears without cleanup."""
    if type(parent_pid) is not int or parent_pid<=1 or os.getppid()!=parent_pid:os._exit(1)
    signal.signal(signal.SIGALRM,lambda *_:os._exit(1))
    signal.setitimer(signal.ITIMER_REAL,65)
    def watch():
        while True:
            if os.getppid()!=parent_pid:os._exit(1)
            time.sleep(.05)
    threading.Thread(target=watch,daemon=True).start()

def main():
    try:
        raw=sys.stdin.buffer.read(8193)
        if len(raw)>8192:raise ValueError()
        value=json.loads(raw)
        if set(value)!={'config','audit','command'}:raise ValueError()
        command=parse_request(json.dumps(value['command']).encode())
        from manufacturing_platform.mes_access.service import MesAccessService
        from manufacturing_platform.mes_access.relay_gateway import dispatch
        reply=dispatch(MesAccessService(value['config'],value['audit']),command)
    except Exception as exc:
        code=exc.code if isinstance(exc,MesAccessError) and exc.code in SAFE_CODES else 'MES_RELAY_UNAVAILABLE'
        reply={'error':code}
    sys.stdout.write(json.dumps(reply,allow_nan=False))
if __name__=='__main__':
    guard_parent(int(sys.argv[1]) if len(sys.argv)==2 else os.getppid())
    main()
