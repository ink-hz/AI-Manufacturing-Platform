"""One isolated, bounded HTTP exchange. Credentials travel only through stdin."""
import base64
import http.client
import json
import os
import subprocess
import time
import socket
import ssl
import sys

class WorkerError(Exception):
    def __init__(self, code): self.code = code

def exchange(config, method, path, body, headers, timeout, max_bytes):
    connection = None
    try:
        if config['scheme'] == 'https':
            context = ssl.create_default_context(cafile=config['ca'])
            connection = http.client.HTTPSConnection(config['host'], config['port'], timeout=timeout, context=context)
        else:
            connection = http.client.HTTPConnection(config['host'], config['port'], timeout=timeout)
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        response_headers = dict(response.getheaders())
        if 300 <= response.status < 400: raise WorkerError('SAP_REDIRECT_BLOCKED')
        if response.status in {401,403}: raise WorkerError('SAP_AUTHENTICATION_FAILED')
        declared = None
        for name, value in response.getheaders():
            if name.lower() == 'content-length':
                try: length = int(value)
                except (ValueError, TypeError): raise WorkerError('SAP_HTTP_ERROR') from None
                if length < 0: raise WorkerError('SAP_HTTP_ERROR')
                if length > max_bytes: raise WorkerError('SAP_RESPONSE_TOO_LARGE')
                if declared is not None and declared != length: raise WorkerError('SAP_HTTP_ERROR')
                declared = length
        content = response.read(max_bytes + 1)
        if len(content) > max_bytes: raise WorkerError('SAP_RESPONSE_TOO_LARGE')
        if declared is not None and len(content) != declared: raise WorkerError('SAP_HTTP_ERROR')
        return response.status, response_headers, content
    finally:
        if connection is not None: connection.close()

def run_worker(request, timeout, max_output):
    started=time.monotonic()
    payload=json.dumps(request, separators=(',', ':')).encode()
    process=subprocess.Popen([sys.executable, '-I', os.path.abspath(__file__)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        try:
            output,_=process.communicate(payload, timeout=max(0,timeout-(time.monotonic()-started)))
        except subprocess.TimeoutExpired:
            process.kill(); process.communicate()
            raise TimeoutError() from None
        if time.monotonic()-started >= timeout: raise TimeoutError()
        if process.returncode != 0 or len(output)>max_output: raise WorkerError('SAP_TRANSPORT_ERROR')
        result=json.loads(output)
        if 'error' in result: raise WorkerError(result['error'])
        return result
    finally:
        if process.poll() is None:
            process.kill(); process.communicate()

def main():
    try:
        request=json.load(sys.stdin)
        if request.get('operation') == 'resolve':
            addresses=socket.getaddrinfo(request['host'],request['port'],type=socket.SOCK_STREAM)
            if not addresses: raise OSError()
            json.dump({'peer':addresses[0][4][0]},sys.stdout)
            return
        body = base64.b64decode(request['body'], validate=True) if request['body'] is not None else None
        status, headers, content=exchange(request['config'],request['method'],request['path'],body,
                                          request['headers'],request['timeout'],request['max_bytes'])
        authorization=request['headers'].get('Authorization', '')
        if authorization.startswith('Basic '):
            decoded=base64.b64decode(authorization[6:], validate=True)
            credentials=decoded.split(b':', 1) + [authorization.encode()]
            projected=json.dumps(headers).encode()+content
            if any(value and value in projected for value in credentials):
                raise WorkerError('SAP_INVALID_RESPONSE')
        result={'status':status,'headers':headers,'body':base64.b64encode(content).decode('ascii')}
    except WorkerError as exc: result={'error':exc.code}
    except (socket.timeout, TimeoutError): result={'error':'SAP_TIMEOUT'}
    except ssl.SSLError: result={'error':'SAP_TLS_ERROR'}
    except OSError: result={'error':'SAP_CONNECTION_FAILED'}
    except Exception: result={'error':'SAP_TRANSPORT_ERROR'}
    json.dump(result,sys.stdout,separators=(',',':'))

if __name__ == '__main__': main()
