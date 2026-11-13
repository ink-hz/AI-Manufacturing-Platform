#!/usr/bin/env python3
"""Foreground supervisor for a single fixed, authenticated SAP read relay tunnel."""
import argparse
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from manufacturing_platform.sap_access.relay_protocol import (
    read_private_json, load_token, strict_json, validate_context, validate_response,
    _private_bytes, MAX_RESPONSE_BYTES,
)

REMOTE_DIRECTORY = '/data/orbbec-agent-platform/manufacturing/data/sap-relay/bridge'
SOCKET_PATTERN = r'r-[0-9a-f]{16}\.sock'
PROBE_TIMEOUT = 5


def load_settings(path):
    value = read_private_json(path)
    if stat.S_IMODE(os.lstat(path).st_mode) != 0o600: raise ValueError("invalid private mode")
    keys = {'version','ssh_host','ssh_user','ssh_identity','ssh_known_hosts',
            'gateway_ready','token_path','remote_directory','expected_context'}
    if set(value) != keys or type(value['version']) is not int or value['version'] != 1:
        raise ValueError('invalid settings')
    host = value['ssh_host']
    if type(host) is not str or len(host)>253 or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?',host):
        raise ValueError('invalid host')
    if re.fullmatch(r'[0-9.]+',host):
        ipaddress.IPv4Address(host)
    elif any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',label) for label in host.split('.')):
        raise ValueError('invalid host')
    if value['ssh_user'] != 'root' or value['remote_directory'] != REMOTE_DIRECTORY:
        raise ValueError('invalid target')
    _private_bytes(value['ssh_identity'], 65536)
    load_token(value['token_path'])
    for key in ('ssh_identity','token_path'):
        if stat.S_IMODE(os.lstat(value[key]).st_mode) != 0o600: raise ValueError('invalid private mode')
    for key in ('gateway_ready','ssh_known_hosts'):
        if type(value[key]) is not str or not os.path.isabs(value[key]): raise ValueError('invalid path')
    fd = os.open(value['ssh_known_hosts'], os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid not in (0,os.getuid()) or info.st_mode & 0o022 or info.st_size>1048576:
            raise ValueError('invalid known hosts')
    finally: os.close(fd)
    validate_context(value['expected_context'])
    return value


def read_ready(settings):
    value=read_private_json(settings['gateway_ready'],1024)
    if set(value)!={'pid','port','generation'} or type(value['pid']) is not int or value['pid']<=0 or type(value['port']) is not int or not 1<=value['port']<=65535:
        raise ValueError('invalid ready')
    if type(value['generation']) is not str or str(UUID(value['generation']))!=value['generation']: raise ValueError('invalid generation')
    os.kill(value['pid'],0)
    return value


def describe_request():
    nonce=str(uuid4())
    return nonce,json.dumps(dict(version=1, request_id=nonce, operation='describe', actor_hash='0'*64, expected_fingerprint=None, scope={})).encode()


def local_describe(settings, ready):
    nonce,body=describe_request()
    connection=http.client.HTTPConnection('127.0.0.1',ready['port'],timeout=PROBE_TIMEOUT)
    started=time.monotonic()
    connection.connect()
    probe_socket=connection.sock
    def expire():
        try: probe_socket.shutdown(socket.SHUT_RDWR)
        except OSError: pass
    timer=threading.Timer(max(.001,PROBE_TIMEOUT-(time.monotonic()-started)),expire);timer.daemon=True;timer.start()
    try:
        connection.request('POST','/v1/read',body,{'Authorization':'Bearer '+load_token(settings['token_path']),'Content-Type':'application/json','Connection':'close'})
        response=connection.getresponse()
        payload=response.read(MAX_RESPONSE_BYTES+1)
        if response.status!=200 or len(payload)>MAX_RESPONSE_BYTES: raise ValueError('probe failed')
        result=validate_response(strict_json(payload),request_id=nonce,expected_context=settings['expected_context'])
        if result['error'] is not None or result['result']!={}: raise ValueError('probe failed')
    except http.client.HTTPException:
        raise ValueError('probe failed') from None
    finally:
        timer.cancel();connection.close()


def ssh_base_argv(settings):
    return ['/usr/bin/ssh','-T','-a','-x','-i',settings['ssh_identity'],
            '-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
            '-o','UserKnownHostsFile='+settings['ssh_known_hosts'],'-o','ConnectTimeout=8',
            '-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2']


def tunnel_argv(settings, name, port):
    if not re.fullmatch(SOCKET_PATTERN,name) or type(port) is not int or not 1<=port<=65535: raise ValueError('invalid tunnel')
    return ssh_base_argv(settings)+['-N','-o','ExitOnForwardFailure=yes','-R',REMOTE_DIRECTORY+'/'+name+':127.0.0.1:'+str(port),'root@'+settings['ssh_host']]


# This is the entire permitted remote program. No caller-provided code or paths.
REMOTE_CODE = r'''
import os,sys,json,stat,re,socket,http.client,uuid,fcntl,time,signal
D='/data/orbbec-agent-platform/manufacturing/data/sap-relay/bridge'
def fail(): raise ValueError()
def pairs(items):
 d={}
 for k,v in items:
  if k in d: fail()
  d[k]=v
 return d
def decode(b): return json.loads(b,object_pairs_hook=pairs,parse_constant=lambda _:fail())
def metadata(path,kind,owners,mode):
 s=os.lstat(path)
 if not kind(s.st_mode) or s.st_uid not in owners or stat.S_IMODE(s.st_mode)!=mode: fail()
 return s
try:
 raw=sys.stdin.buffer.read(4097)
 if len(raw)>4096: fail()
 p=decode(raw)
 if set(p)!={'action','nonce','socketname','expected_context'} or p['action'] not in ('activate','cleanup'): fail()
 if type(p['nonce']) is not str or str(uuid.UUID(p['nonce']))!=p['nonce']: fail()
 n=p['socketname']
 if type(n) is not str or not re.fullmatch(r'r-[0-9a-f]{16}\.sock',n): fail()
 c=p['expected_context']
 if type(c) is not dict or set(c)!={'source','fingerprint'}: fail()
 metadata(os.path.dirname(D),stat.S_ISDIR,(10001,),0o700)
 ds=metadata(D,stat.S_ISDIR,(0,),0o750)
 if ds.st_gid!=10001: fail()
 path=D+'/'+n
 if len(path.encode())>=108: fail()
 if p['action']=='activate':
  metadata(path,stat.S_ISSOCK,(0,),stat.S_IMODE(os.lstat(path).st_mode))
  fd=os.open(os.path.dirname(D)+'/token',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
  with os.fdopen(fd,'rb') as f:
   s=os.fstat(f.fileno())
   if not stat.S_ISREG(s.st_mode) or s.st_uid not in (0,10001) or stat.S_IMODE(s.st_mode)!=0o600 or s.st_size>65: fail()
   token=f.read(66).decode('ascii').removesuffix('\n')
  if not re.fullmatch('[0-9a-f]{64}',token): fail()
  rid=str(uuid.uuid4())
  body=json.dumps(dict(version=1,request_id=rid,operation='describe',actor_hash='0'*64,expected_fingerprint=None,scope={}))
  class Conn(http.client.HTTPConnection):
   def connect(self):
    self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.sock.settimeout(5);self.sock.connect(path)
  conn=Conn('localhost',timeout=5)
  signal.signal(signal.SIGALRM,lambda *_:fail());signal.alarm(5)
  try:
   conn.request('POST','/v1/read',body,{'Authorization':'Bearer '+token,'Content-Type':'application/json','Connection':'close'})
   res=conn.getresponse();b=res.read(2097153)
   if res.status!=200 or len(b)>2097152: fail()
   v=decode(b)
   if type(v) is not dict or set(v)!={'version','request_id','context','result','error'} or type(v['version']) is not int or v['version']!=1 or v['request_id']!=rid or v['context']!=c or v['result']!={} or v['error'] is not None: fail()
  finally: signal.alarm(0);conn.close()
 fd=os.open(D+'/.active.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
 with os.fdopen(fd,'r+') as lock:
  s=os.fstat(lock.fileno())
  if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or stat.S_IMODE(s.st_mode)!=0o600 or s.st_nlink!=1: fail()
  deadline=time.monotonic()+5
  while True:
   try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
   except BlockingIOError:
    if time.monotonic()>=deadline: fail()
    time.sleep(.05)
  active=D+'/active.sock'
  if os.path.lexists(active) and not stat.S_ISLNK(os.lstat(active).st_mode): fail()
  if p['action']=='activate':
   metadata(path,stat.S_ISSOCK,(0,),stat.S_IMODE(os.lstat(path).st_mode))
   os.chown(path,0,10001,follow_symlinks=False);os.chmod(path,0o660)
   temporary=D+'/.active-'+p['nonce']
   try:
    os.symlink(n,temporary);os.replace(temporary,active)
   finally:
    if os.path.islink(temporary): os.unlink(temporary)
  else:
   if os.path.lexists(path): metadata(path,stat.S_ISSOCK,(0,),stat.S_IMODE(os.lstat(path).st_mode))
   if os.path.islink(active) and os.readlink(active)==n: os.unlink(active)
   if os.path.lexists(path):
    metadata(path,stat.S_ISSOCK,(0,),stat.S_IMODE(os.lstat(path).st_mode));os.unlink(path)
 print(json.dumps({'ready':p['action']=='activate','context':c,'socketname':n}))
except Exception:
 print('{"error":"SAP_RELAY_UNAVAILABLE"}');sys.exit(1)
'''


def remote_action(settings, action, name, runner=subprocess.run):
    if action not in ('activate','cleanup') or type(name) is not str or not re.fullmatch(SOCKET_PATTERN,name): raise ValueError('invalid action')
    payload=dict(action=action,nonce=str(uuid4()),socketname=name,expected_context=settings['expected_context'])
    argv=ssh_base_argv(settings)+['root@'+settings['ssh_host'],'python3 -c '+shlex.quote(REMOTE_CODE)]
    result=runner(argv,input=json.dumps(payload).encode(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=20,check=False)
    if result.returncode or len(result.stdout)>4096: raise ValueError('remote unavailable')
    value=strict_json(result.stdout)
    if value!={'ready':action=='activate','context':settings['expected_context'],'socketname':name}: raise ValueError('remote unavailable')


class Supervisor:
    def __init__(self,settings,*,ready_reader=read_ready,describe=local_describe,popen=subprocess.Popen,remote=remote_action,wait=None,status=None):
        self.settings=settings;self.ready_reader=ready_reader;self.describe=describe;self.popen=popen;self.remote=remote
        self.stopped=threading.Event();self.wait=wait or self.stopped.wait;self.status=status or (lambda phase: print(phase,flush=True))
        self.process=None;self.ready=None;self.name=None

    def start(self):
        ready=self.ready_reader(self.settings)
        self.describe(self.settings,ready)
        self.ready=ready;self.name='r-'+uuid4().hex[:16]+'.sock'
        self.process=self.popen(tunnel_argv(self.settings,self.name,ready['port']),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            # Forward creation is asynchronous; retry only fixed describe activation.
            for attempt in range(5):
                if self.process.poll() is not None or self.stopped.is_set(): raise ValueError('tunnel unavailable')
                try:
                    self.remote(self.settings,'activate',self.name)
                    if self.ready_reader(self.settings)!=ready: raise ValueError('gateway changed')
                    self.status('relay ready');return
                except Exception:
                    if self.ready_reader(self.settings)!=ready or attempt==4: raise
                    if self.wait(1): raise ValueError('stopped')
        except Exception:
            self.disconnect();raise

    def disconnect(self):
        process,self.process=self.process,None
        if process is not None:
            try:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill();process.wait(timeout=5)
            except (OSError,subprocess.TimeoutExpired): pass
        name,self.name=self.name,None
        if name:
            try: self.remote(self.settings,'cleanup',name)
            except Exception: self.status('relay cleanup pending')
        self.ready=None

    def stop(self): self.stopped.set()

    def run(self):
        try:
            while not self.stopped.is_set():
                try:
                    self.start()
                    while not self.wait(1):
                        if self.process.poll() is not None or self.ready_reader(self.settings)!=self.ready: break
                except Exception: self.status('relay unavailable')
                finally: self.disconnect()
                if self.wait(5): break
        finally: self.disconnect()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--settings',required=True)
    args=parser.parse_args()
    try:
        settings=load_settings(args.settings);supervisor=Supervisor(settings)
        for sig in (signal.SIGTERM,signal.SIGINT): signal.signal(sig,lambda *_:supervisor.stop())
        supervisor.run()
        return 0
    except Exception:
        print('relay configuration unavailable',file=sys.stderr);return 1

if __name__=='__main__': sys.exit(main())
