"""Authenticated loopback gateway exposing only native MES observation reads."""
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
from .errors import MesAccessError
from .service import MesAccessService
from .relay_protocol import (MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES, SAFE_CODES, RelayProtocolError,
                             load_token, parse_request, validate_context, read_private_json)

import subprocess

class NativeChildren:
    """Serialize creation against shutdown and retain ownership until reaped."""
    def __init__(self):
        self.lock=threading.Lock();self.children=set();self.closed=False
    def start(self,argv):
        with self.lock:
            if self.closed:raise MesAccessError('MES_RELAY_UNAVAILABLE')
            child=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            self.children.add(child)
            return child
    def release(self,child):
        with self.lock:self.children.discard(child)
    @staticmethod
    def reap(child):
        try:
            if child.poll() is None:child.terminate()
            try:child.wait(timeout=2)
            except subprocess.TimeoutExpired:child.kill();child.wait(timeout=2)
        except (OSError,subprocess.TimeoutExpired):pass
    def close(self):
        with self.lock:
            self.closed=True;children=tuple(self.children)
        for child in children:self.reap(child)
        with self.lock:self.children.difference_update(children)

class Gateway(ThreadingHTTPServer):
    def shutdown(self):
        self.native_children.close()
        super().shutdown()
    def server_close(self):
        self.native_children.close()
        super().server_close()
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
        self.reply(code,None,error='MES_RELAY_INVALID_REQUEST')
    def reply(self,status,request_id,*,context=None,result=None,error=None):
        value=dict(version=1,request_id=request_id,context=context,result=result,error={'code':error} if error else None)
        try:body=json.dumps(value,separators=(',',':'),allow_nan=False).encode()
        except (ValueError,TypeError,RecursionError):return self.reply(503,request_id,error='MES_RELAY_UNAVAILABLE')
        if len(body)>MAX_RESPONSE_BYTES:return self.reply(502,request_id,error='MES_RELAY_RESPONSE_TOO_LARGE')
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Connection','close');self.end_headers();self.wfile.write(body)
    def do_POST(self):
        request_id=None
        if self.path!='/v1/read':return self.reply(404,None,error='MES_RELAY_INVALID_REQUEST')
        auth=self.headers.get_all('Authorization',[])
        if len(auth)!=1 or not hmac.compare_digest(auth[0].encode(),('Bearer '+self.server.token).encode()):return self.reply(401,None,error='MES_RELAY_UNAUTHORIZED')
        try:
            lengths=self.headers.get_all('Content-Length',[])
            if (len(lengths)!=1 or not lengths[0].isascii() or not lengths[0].isdigit()
                or self.headers.get_all('Transfer-Encoding') or int(lengths[0])>MAX_REQUEST_BYTES
                or self.headers.get_all('Content-Type',[])!=['application/json']):raise RelayProtocolError()
            size=int(lengths[0]);body=self.rfile.read(size)
            if len(body)!=size:raise RelayProtocolError()
            command=parse_request(body);request_id=command['request_id']
        except (RelayProtocolError,ValueError,TimeoutError,OSError):return self.reply(400,request_id,error='MES_RELAY_INVALID_REQUEST')
        if not self.server.source_slots.acquire(blocking=False):return self.reply(503,request_id,error='MES_RELAY_BUSY')
        try:
            if self.server.service is None:
                reply=isolated_dispatch(self.server.config_path,self.server.audit_path,command,children=self.server.native_children)
            else:
                reply=dispatch(self.server.service,command)
            self.reply(200,request_id,context=reply['context'],result=reply['result'])
        except Exception as exc:
            code=exc.code if isinstance(exc,MesAccessError) and exc.code in SAFE_CODES else 'MES_RELAY_UNAVAILABLE'
            self.reply(503,request_id,error=code)
        finally:self.server.source_slots.release()

def dispatch(service,command):
    context=validate_context(service.read_context())
    op=command['operation'];scope=command['scope']
    if op=='describe':result={}
    else:
        if not hmac.compare_digest(context['fingerprint'],command['expected_fingerprint']):
            raise MesAccessError('MES_RELAY_CONTEXT_MISMATCH',409)
        pin={'expected_fingerprint':context['fingerprint']}
        actor=command['actor_hash']
        if op=='source_orders':result=service.source_orders(scope['prefix'],scope['after'],actor,**pin)
        elif op=='order_materials':result=service.collect_order_materials(scope['shop_order'],actor,**pin)
        elif op=='material_priority':result=service.query(op,{'shopOrder':scope['shop_order'],'itemNo':scope['material']},scope['page'],scope['page_size'],actor,**pin)
        elif op=='iqc_inspections':result=service.query(op,{'item_no':scope['material']},scope['page'],scope['page_size'],actor,**pin)
        else:raise RelayProtocolError()
        if validate_context(service.read_context())!=context:raise MesAccessError('MES_RELAY_CONTEXT_MISMATCH',409)
    return {'context':context,'result':result}

def isolated_dispatch(config,audit,command,*,children=None):
    import subprocess,sys
    from pathlib import Path
    pool=children if children is not None else NativeChildren()
    child=None
    try:
        child=pool.start([sys.executable,'-I',str(Path(__file__).with_name('relay_native_worker.py')),str(os.getpid())])
        output,_=child.communicate(json.dumps({'config':config,'audit':audit,'command':command}).encode(),timeout=65)
        if child.returncode or len(output)>MAX_RESPONSE_BYTES:raise ValueError()
        from .relay_protocol import strict_json
        reply=strict_json(output)
        if type(reply) is dict and set(reply)=={'error'}:
            code=reply['error']
            raise MesAccessError(code if type(code) is str and code in SAFE_CODES else 'MES_RELAY_UNAVAILABLE')
        if type(reply) is not dict or set(reply)!={'context','result'}:raise ValueError()
        validate_context(reply['context'])
        if type(reply['result']) is not dict:raise ValueError()
        return reply
    except subprocess.TimeoutExpired:raise MesAccessError('MES_TIMEOUT') from None
    except MesAccessError:raise
    except Exception:raise MesAccessError('MES_RELAY_UNAVAILABLE') from None
    finally:
        if child is not None:
            pool.reap(child);pool.release(child)

def build_gateway(config_path,audit_path,token_path,*,port=0,service=None):
    token=load_token(token_path)
    if type(port) is not int or not 0<=port<=65535:raise ValueError('invalid port')
    server=Gateway(('127.0.0.1',port),Handler)
    server.native_children=NativeChildren()
    server.token=token;server.service=service;server.config_path=config_path;server.audit_path=audit_path
    server.source_slots=threading.BoundedSemaphore(4)
    server.handler_slots=threading.BoundedSemaphore(16)
    return server

from ..sap_access.relay_gateway import validate_ready_paths,ready_lock,publish_ready,cleanup_ready

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
        validate_context(MesAccessService(args.config,args.audit).read_context())
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
        raise SystemExit('MES_RELAY_UNAVAILABLE') from None
