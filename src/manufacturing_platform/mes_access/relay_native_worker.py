"""Isolated native operation. Parent enforces the whole-operation hard deadline."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from manufacturing_platform.mes_access.relay_protocol import parse_request,SAFE_CODES
from manufacturing_platform.mes_access.errors import MesAccessError

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
if __name__=='__main__':main()
