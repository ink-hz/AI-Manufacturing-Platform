"""Standalone isolated UNIX HTTP exchange; stdin/stdout only, no source retries."""
import json
import socket
import sys
import time


def run(value):
    deadline = time.monotonic() + value['timeout']
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    def remaining():
        left = deadline-time.monotonic()
        if left <= 0: raise TimeoutError()
        sock.settimeout(left)
    try:
        remaining(); sock.connect(value['socket_path'])
        body = json.dumps(value['command'], separators=(',', ':'), allow_nan=False).encode()
        request = (b'POST /v1/read HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer ' + value['token'].encode('ascii') +
                   b'\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
        remaining(); sock.sendall(request)
        data = b''
        while b'\r\n\r\n' not in data:
            remaining(); part=sock.recv(1)
            if not part: raise ConnectionError()
            data += part
            if len(data)>16384: return {'error':'SAP_RELAY_INVALID_RESPONSE'}
        head=data[:-4].decode('ascii').split('\r\n')
        status = head[0].split(' ')
        if len(status)<3 or status[0] not in ('HTTP/1.0','HTTP/1.1'): raise ValueError()
        if status[1]=='401': return {'error':'SAP_RELAY_UNAUTHORIZED'}
        if status[1] not in ('200','400','409','502','503'): raise ValueError()
        headers={}
        for line in head[1:]:
            key, val=line.split(':',1); key=key.lower(); val=val.strip()
            if key in headers: raise ValueError()
            headers[key]=val
        if ('transfer-encoding' in headers or 'content-encoding' in headers or
            headers.get('content-type','').split(';')[0] != 'application/json'): raise ValueError()
        length=headers.get('content-length','')
        if not length.isascii() or not length.isdecimal(): raise ValueError()
        length=int(length)
        if length>value['max_bytes']: return {'error':'SAP_RELAY_RESPONSE_TOO_LARGE'}
        body=b''
        while len(body)<length:
            remaining(); part=sock.recv(min(65536,length-len(body)))
            if not part: raise ConnectionError()
            body+=part
        return {'body':body.decode('utf-8'),'status':int(status[1])}
    finally: sock.close()

if __name__ == '__main__':
    try:
        raw=sys.stdin.buffer.read(8193)
        if len(raw)>8192: raise ValueError()
        result=run(json.loads(raw))
    except (TimeoutError, socket.timeout): result={'error':'SAP_TIMEOUT'}
    except (ConnectionError,OSError): result={'error':'SAP_RELAY_UNAVAILABLE'}
    except Exception: result={'error':'SAP_RELAY_INVALID_RESPONSE'}
    sys.stdout.write(json.dumps(result))
