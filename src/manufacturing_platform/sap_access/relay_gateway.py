"""Authenticated loopback gateway exposing only native SAP observation reads."""
import argparse
from contextlib import contextmanager
import fcntl
import stat
from time import monotonic, sleep
import hmac
import json
import os
import signal
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4
from .errors import SapAccessError
from .service import SapAccessService
from .relay_protocol import (MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, SAFE_CODES, RelayProtocolError,
                             load_token, parse_request, validate_context, read_private_json)

class Gateway(ThreadingHTTPServer):
    daemon_threads=True
    request_queue_size=16
    def process_request(self, request, client_address):
        if not self.handler_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.handler_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.handler_slots.release()

    def handle_error(self, request, client_address):
        # Base implementation prints exception values, potentially including data.
        pass

    def get_request(self):
        connection,address=super().get_request();connection.settimeout(5);return connection,address

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.0'
    def log_message(self,*args):pass
    def send_error(self,code,message=None,explain=None):
        self.reply(code,None,error='SAP_RELAY_INVALID_REQUEST')
    def reply(self,status,request_id,*,context=None,result=None,error=None):
        value=dict(version=1,request_id=request_id,context=context,result=result,error={'code':error} if error else None)
        try:body=json.dumps(value,separators=(',',':'),allow_nan=False).encode()
        except (ValueError,TypeError,RecursionError):return self.reply(503,request_id,error='SAP_RELAY_UNAVAILABLE')
        if len(body)>MAX_RESPONSE_BYTES:return self.reply(502,request_id,error='SAP_RELAY_RESPONSE_TOO_LARGE')
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Connection','close');self.end_headers();self.wfile.write(body)
    def do_POST(self):
        request_id=None
        if self.path!='/v1/read':return self.reply(404,None,error='SAP_RELAY_INVALID_REQUEST')
        auth=self.headers.get_all('Authorization',[])
        if len(auth)!=1 or not hmac.compare_digest(auth[0].encode(),('Bearer '+self.server.token).encode()):return self.reply(401,None,error='SAP_RELAY_UNAUTHORIZED')
        try:
            lengths=self.headers.get_all('Content-Length',[])
            if (len(lengths)!=1 or not lengths[0].isascii() or not lengths[0].isdigit()
                or self.headers.get_all('Transfer-Encoding') or int(lengths[0])>MAX_REQUEST_BYTES
                or self.headers.get_all('Content-Type',[])!=['application/json']):raise RelayProtocolError()
            size=int(lengths[0]);body=self.rfile.read(size)
            if len(body)!=size:raise RelayProtocolError()
            command=parse_request(body);request_id=command['request_id']
        except (RelayProtocolError,ValueError,TimeoutError,OSError):return self.reply(400,request_id,error='SAP_RELAY_INVALID_REQUEST')
        if not self.server.source_slots.acquire(blocking=False):return self.reply(503,request_id,error='SAP_RELAY_BUSY')
        try:
            context=validate_context(self.server.service.read_context())
            op=command['operation']
            if op=='describe':result={}
            else:
                if not hmac.compare_digest(context['fingerprint'],command['expected_fingerprint']):return self.reply(409,request_id,error='SAP_RELAY_CONTEXT_MISMATCH')
                scope=command['scope'];key='number' if op=='production_order' else 'material'
                result=getattr(self.server.service,op)(scope[key],scope['plant'],command['actor_hash'],expected_fingerprint=context['fingerprint'])
                if validate_context(self.server.service.read_context())!=context:return self.reply(409,request_id,error='SAP_RELAY_CONTEXT_MISMATCH')
                if type(result) is not dict:raise RelayProtocolError()
            self.reply(200,request_id,context=context,result=result)
        except Exception as exc:
            code=exc.code if isinstance(exc,SapAccessError) and exc.code in SAFE_CODES else 'SAP_RELAY_UNAVAILABLE'
            self.reply(503,request_id,error=code)
        finally:self.server.source_slots.release()

def build_gateway(config_path,audit_path,token_path,*,port=0,service=None):
    token=load_token(token_path)
    if type(port) is not int or not 0<=port<=65535:raise ValueError('invalid port')
    server=Gateway(('127.0.0.1',port),Handler)
    server.token=token;server.service=service if service is not None else SapAccessService(config_path,audit_path)
    server.source_slots=threading.BoundedSemaphore(4)
    server.handler_slots=threading.BoundedSemaphore(16)
    return server

def _private_stat(info, *, directory=False):
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if not kind(info.st_mode) or info.st_uid not in (0, os.getuid()) or info.st_mode & 0o077:
        raise RelayProtocolError()


def validate_ready_paths(path, protected_paths=()):
    """Reject aliases before any readiness mutation; callers hold the stable lock."""
    if not os.path.isabs(path):
        raise RelayProtocolError()
    try:
        _private_stat(os.stat(os.path.dirname(path), follow_symlinks=False), directory=True)
        candidates = (path, path + '.lock')
        for candidate in candidates:
            if os.path.lexists(candidate):
                _private_stat(os.stat(candidate, follow_symlinks=False))
            other_ready_path = candidates[1] if candidate == path else path
            for protected in (*protected_paths, other_ready_path):
                if os.path.realpath(candidate) == os.path.realpath(protected):
                    raise RelayProtocolError()
                if os.path.exists(candidate) and os.path.exists(protected) and os.path.samefile(candidate, protected):
                    raise RelayProtocolError()
    except OSError:
        raise RelayProtocolError() from None


@contextmanager
def ready_lock(path, *, timeout=5):
    """A stable private inode serializes every publisher and cleanup; never rename it."""
    validate_ready_paths(path)
    descriptor = None
    try:
        descriptor = os.open(path + '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        _private_stat(os.fstat(descriptor))
        deadline = monotonic() + timeout
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if monotonic() >= deadline:
                    raise RelayProtocolError()
                sleep(.01)
        yield
    except OSError:
        raise RelayProtocolError() from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def publish_ready(path, value, protected_paths=()):
    validate_ready_paths(path, protected_paths)
    with ready_lock(path):
        validate_ready_paths(path, protected_paths)
        descriptor, temporary = tempfile.mkstemp(prefix='.relay-ready-', dir=os.path.dirname(path))
        try:
            with os.fdopen(descriptor, 'w') as stream:
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def cleanup_ready(path, value, protected_paths=()):
    try:
        validate_ready_paths(path, protected_paths)
        with ready_lock(path):
            validate_ready_paths(path, protected_paths)
            if read_private_json(path) == value:
                os.unlink(path)
    except (OSError, RelayProtocolError):
        pass


def main(argv=None):
    parser = argparse.ArgumentParser()
    for name in ('config', 'audit', 'token', 'ready'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    protected = (args.config, args.token, args.audit, args.audit + '.lock')
    validate_ready_paths(args.ready, protected)
    server = build_gateway(args.config, args.audit, args.token, port=args.port)
    ready = {'pid': os.getpid(), 'port': server.server_port, 'generation': str(uuid4())}
    try:
        validate_context(server.service.read_context())
        publish_ready(args.ready, ready, protected)
        def stop(*unused):
            threading.Thread(target=server.shutdown, daemon=True).start()
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        server.serve_forever()
    finally:
        server.server_close()
        cleanup_ready(args.ready, ready, protected)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('SAP_RELAY_UNAVAILABLE') from None
