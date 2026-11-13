import importlib.util
from pathlib import Path
import pytest

PATH = Path(__file__).parents[2] / 'scripts/sap_relay_supervisor.py'

def module():
    assert PATH.exists(), 'supervisor implementation missing'
    spec = importlib.util.spec_from_file_location('supervisor', PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def test_ssh_argv_has_only_fixed_reverse_socket():
    m = module()
    settings = dict(ssh_host='relay.example.com', ssh_user='root', ssh_identity='/private/key', ssh_known_hosts='/private/hosts')
    argv = m.tunnel_argv(settings, 'r-' + 'a'*16 + '.sock', 12345)
    assert argv[-1] == 'root@relay.example.com'
    assert argv[argv.index('-R')+1] == m.REMOTE_DIRECTORY + '/r-'+'a'*16+'.sock:127.0.0.1:12345'
    assert 'StrictHostKeyChecking=yes' in argv
    with pytest.raises(ValueError): m.tunnel_argv(settings, '../../bad', 12345)

def test_context_failure_prevents_ssh():
    m=module(); calls=[]
    sup=m.Supervisor({}, ready_reader=lambda _: {'pid':1,'port':1,'generation':'x'}, describe=lambda *_: (_ for _ in ()).throw(ValueError()), popen=lambda *a,**k: calls.append(a))
    with pytest.raises(ValueError): sup.start()
    assert calls == []

import json
import os
import stat
import subprocess
from types import SimpleNamespace
from uuid import uuid4

CONTEXT={'source':{'system':'sap','origin':'native','fact_role':'observation','environment':'test','system_id':'DEV','client':'200','namespace':'a'*64},'fingerprint':'b'*64}

def private(path, content):
    path.write_text(content);path.chmod(0o600);return str(path)

def settings_file(tmp_path):
    settings=dict(version=1,ssh_host='relay.example.com',ssh_user='root',ssh_identity=private(tmp_path/'key','private-key'),ssh_known_hosts=private(tmp_path/'hosts','public-key'),gateway_ready=str(tmp_path/'ready'),token_path=private(tmp_path/'token','c'*64),remote_directory=module().REMOTE_DIRECTORY,expected_context=CONTEXT)
    return settings,private(tmp_path/'settings',json.dumps(settings))

@pytest.mark.parametrize('host',['-host','a b','a:b','a;id','a\nb','$(id)','a/b','','a..b','a.-b','256.1.1.1','127.1','2130706433'])
def test_settings_reject_arbitrary_hosts(tmp_path,host):
    settings,path=settings_file(tmp_path);settings['ssh_host']=host;Path(path).write_text(json.dumps(settings))
    with pytest.raises(ValueError): module().load_settings(path)

def test_settings_private_files_and_exact_keys(tmp_path):
    settings,path=settings_file(tmp_path)
    assert module().load_settings(path)==settings
    Path(settings['ssh_known_hosts']).chmod(0o644)
    assert module().load_settings(path)==settings
    Path(path).chmod(0o644)
    with pytest.raises(ValueError): module().load_settings(path)
    Path(path).chmod(0o600);settings['extra']='bad';Path(path).write_text(json.dumps(settings))
    with pytest.raises(ValueError): module().load_settings(path)

def test_ready_validates_pid_port_uuid_and_symlink(tmp_path):
    m=module();settings,path=settings_file(tmp_path)
    ready={'pid':os.getpid(),'port':1234,'generation':str(uuid4())}
    private(Path(settings['gateway_ready']),json.dumps(ready))
    assert m.read_ready(settings)==ready
    for key,value in [('pid',True),('port',False),('port',65536),('generation','not-uuid')]:
        invalid={**ready,key:value};Path(settings['gateway_ready']).write_text(json.dumps(invalid))
        with pytest.raises(ValueError):m.read_ready(settings)

class Process:
    def __init__(self):self.exit=None;self.terminated=False;self.killed=False
    def poll(self):return self.exit
    def terminate(self):self.terminated=True;self.exit=0
    def kill(self):self.killed=True;self.exit=-9
    def wait(self,timeout):return self.exit


def test_stop_cleans_only_own_socket_without_business_replay():
    m=module();events=[];p=Process()
    ready={'port':1234,'pid':os.getpid(),'generation':str(uuid4())}
    s=m.Supervisor({'ssh_host':'host','ssh_identity':'/key','ssh_known_hosts':'/hosts'},ready_reader=lambda _:ready,describe=lambda *a:events.append('describe'),popen=lambda *a,**k:p,remote=lambda _,action,name:events.append((action,name)),status=lambda _:None)
    s.start();name=s.name;s.stop();s.disconnect();s.disconnect()
    assert p.terminated
    assert events==['describe',('activate',name),('cleanup',name)]


def test_generation_change_restarts_and_never_replays_business():
    m=module();generation=[1];processes=[];events=[];s=None
    def ready(_):return {'port':1234+generation[0],'pid':1,'generation':generation[0]}
    def popen(*a,**k):p=Process();processes.append(p);return p
    def remote(_,action,name):
        events.append((action,name))
        if action=='activate' and len(processes)==2:s.stop()
    def wait(seconds):
        if seconds==1 and len(processes)==1:generation[0]=2
        return s.stopped.is_set()
    s=m.Supervisor({'ssh_host':'host','ssh_identity':'/key','ssh_known_hosts':'/hosts'},ready_reader=ready,describe=lambda *a:events.append('describe'),popen=popen,remote=remote,wait=wait,status=lambda _:None)
    s.run()
    assert len(processes)==2 and all(p.terminated for p in processes)
    assert events.count('describe')==2
    assert len({v[1] for v in events if isinstance(v,tuple)})==2


def test_remote_action_fixed_code_and_no_secret_args(tmp_path):
    m=module();settings,_=settings_file(tmp_path);calls=[];name='r-'+'d'*16+'.sock'
    def run(argv,**kwargs):
        calls.append((argv,kwargs));return SimpleNamespace(returncode=0,stdout=json.dumps(dict(ready=True,context=CONTEXT,socketname=name)).encode())
    m.remote_action(settings,'activate',name,run)
    argv,kw=calls[0]
    assert 'c'*64 not in repr(calls)
    assert argv[-1].startswith('python3 -c ')
    assert json.loads(kw['input'])['action']=='activate'
    assert kw['stderr']==subprocess.DEVNULL and kw['timeout']==20


def test_local_describe_authenticates_and_rejects_mismatch(tmp_path):
    import http.server
    import threading
    m=module();settings,_=settings_file(tmp_path);calls=[]
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append((self.path,self.headers.get('Authorization')))
            req=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert req['operation']=='describe' and req['scope']=={}
            self.send_response(200);self.end_headers()
            self.wfile.write(json.dumps(dict(version=1,request_id=req['request_id'],context=CONTEXT,result={},error=None)).encode())
        def log_message(self,*args):pass
    server=http.server.HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever);thread.start()
    try:
        m.local_describe(settings,{'port':server.server_port})
        settings['expected_context']={**CONTEXT,'fingerprint':'e'*64}
        with pytest.raises(ValueError):m.local_describe(settings,{'port':server.server_port})
        assert calls==[('/v1/read','Bearer '+'c'*64)]*2
    finally:server.shutdown();thread.join();server.server_close()


def test_remote_unix_probe_publish_and_cleanup_preserve_new_session(tmp_path,monkeypatch):
    import builtins
    import io
    import http.server
    import socketserver
    import threading
    import tempfile
    temporary=tempfile.TemporaryDirectory(prefix='sr-',dir='/tmp')
    m=module();parent=Path(temporary.name);bridge=parent/'bridge';bridge.mkdir(mode=0o750)
    private(parent/'token','c'*64)
    name='r-'+'a'*16+'.sock';other='r-'+'b'*16+'.sock';path=bridge/name
    context=[CONTEXT];calls=[]
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            req=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(req['operation']);assert self.headers['Authorization']=='Bearer '+'c'*64
            self.send_response(200);self.end_headers();self.wfile.write(json.dumps(dict(version=1,request_id=req['request_id'],context=context[0],result={},error=None)).encode())
        def log_message(self,*args):pass
    server=socketserver.UnixStreamServer(str(path),Handler)
    thread=threading.Thread(target=server.serve_forever);thread.start()
    # Model Linux root/UID10001 deployment metadata without requiring root in tests.
    real_lstat=os.lstat;real_fstat=os.fstat
    def normalized(info,uid=0,gid=10001):
        return SimpleNamespace(st_mode=info.st_mode,st_uid=uid,st_gid=gid,st_size=info.st_size,st_nlink=info.st_nlink)
    class OS:
        def __getattr__(self,key):return getattr(os,key)
        def lstat(self,p):return normalized(real_lstat(p),10001 if str(p)==str(parent) else 0)
        def fstat(self,fd):return normalized(real_fstat(fd))
        def chown(self,*args,**kwargs):pass
    original_import=builtins.__import__
    def imports(name,*args,**kwargs):return OS() if name=='os' else original_import(name,*args,**kwargs)
    import signal
    old_alarm=signal.getsignal(signal.SIGALRM)
    code=m.REMOTE_CODE.replace(m.REMOTE_DIRECTORY,str(bridge))
    def execute(action):
        payload=json.dumps(dict(action=action,nonce=str(uuid4()),socketname=name,expected_context=CONTEXT)).encode()
        output=io.StringIO();fake_sys=SimpleNamespace(stdin=SimpleNamespace(buffer=io.BytesIO(payload)),exit=lambda code: (_ for _ in ()).throw(SystemExit(code)))
        def importing(n,*a,**k):return fake_sys if n=='sys' else imports(n,*a,**k)
        namespace={'__builtins__':{**vars(builtins),'__import__':importing,'print':lambda value:output.write(value)}}
        try:exec(code,namespace)
        except SystemExit:pass
        return json.loads(output.getvalue())
    try:
        os.symlink(other,bridge/'active.sock')
        context[0]={**CONTEXT,'fingerprint':'f'*64}
        assert execute('activate')=={'error':'SAP_RELAY_UNAVAILABLE'}
        assert os.readlink(bridge/'active.sock')==other
        context[0]=CONTEXT
        assert execute('activate')['ready'] is True
        assert os.readlink(bridge/'active.sock')==name
        assert stat.S_IMODE(path.stat().st_mode)==0o660
        # The stable lock serializes cleanup against another publisher.
        import fcntl
        import time
        results=[]
        with open(bridge/'.active.lock','r+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            cleaner=threading.Thread(target=lambda:results.append(execute('cleanup')))
            cleaner.start();time.sleep(.1)
            assert cleaner.is_alive() and path.exists()
            (bridge/'active.sock').unlink();os.symlink(other,bridge/'active.sock')
            fcntl.flock(lock,fcntl.LOCK_UN)
        cleaner.join(timeout=2)
        assert results[0]['ready'] is False
        assert not path.exists() and os.readlink(bridge/'active.sock')==other
        assert (bridge/'.active.lock').is_file()
        assert calls==['describe','describe']
    finally:
        signal.signal(signal.SIGALRM,old_alarm)
        server.shutdown();thread.join();server.server_close();temporary.cleanup()

@pytest.mark.parametrize('key',['settings','ssh_identity','token_path'])
def test_exact_private_mode_required(tmp_path,key):
    settings,path=settings_file(tmp_path)
    Path(path if key=='settings' else settings[key]).chmod(0o400)
    with pytest.raises(ValueError):module().load_settings(path)


def test_invalid_remote_action_never_spawns_ssh(tmp_path):
    m=module();settings,_=settings_file(tmp_path)
    with pytest.raises(ValueError):m.remote_action(settings,'arbitrary','../../file',lambda *a,**k:pytest.fail('SSH invoked'))


def test_failed_activation_terminates_and_cleans_only_own_socket():
    m=module();events=[];p=Process()
    def remote(_,action,name):
        events.append((action,name))
        if action=='activate':raise ValueError('private token must never escape')
    s=m.Supervisor({'ssh_host':'host','ssh_identity':'/key','ssh_known_hosts':'/hosts'},ready_reader=lambda _:{'port':1234},describe=lambda *a:None,popen=lambda *a,**k:p,remote=remote,wait=lambda _:False,status=events.append)
    with pytest.raises(ValueError):s.start()
    assert p.terminated and events[-1][0]=='cleanup'
    assert len({e[1] for e in events})==1


def test_generation_change_during_activation_aborts_without_old_port_retry():
    m=module();p=Process();calls=[];ready=[{'port':1234,'generation':'one'}]
    def remote(_,action,name):
        calls.append(action)
        if action=='activate':ready[0]={'port':1235,'generation':'two'}
    s=m.Supervisor({'ssh_host':'host','ssh_identity':'/key','ssh_known_hosts':'/hosts'},ready_reader=lambda _:ready[0],describe=lambda *a:None,popen=lambda *a,**k:p,remote=remote,wait=lambda _:False,status=lambda _:None)
    with pytest.raises(ValueError):s.start()
    assert calls==['activate','cleanup']


def test_local_probe_has_total_deadline_for_trickled_body(tmp_path,monkeypatch):
    import socketserver
    import threading
    import time
    m=module();settings,_=settings_file(tmp_path);monkeypatch.setattr(m,'PROBE_TIMEOUT',.1,raising=False)
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.recv(2048)
            try:
                self.request.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n')
                for _ in range(30):self.request.sendall(b' ');time.sleep(.03)
            except OSError:pass
    server=socketserver.TCPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever);thread.start()
    started=time.monotonic()
    try:
        with pytest.raises((ValueError,OSError)):m.local_describe(settings,{'port':server.server_address[1]})
        assert time.monotonic()-started<.6
    finally:server.shutdown();thread.join();server.server_close()


def test_stop_kills_unresponsive_owned_tunnel_with_bounded_waits():
    m=module();events=[]
    class Slow(Process):
        def terminate(self):self.terminated=True
        def wait(self,timeout):
            events.append(timeout)
            if not self.killed:raise subprocess.TimeoutExpired('fixed ssh',timeout)
            return -9
    process=Slow();s=m.Supervisor({},remote=lambda *args:events.append(args[1:]),status=lambda _:None)
    s.process=process;s.name='r-'+'a'*16+'.sock';s.disconnect()
    assert process.terminated and process.killed
    assert events==[5,5,('cleanup','r-'+'a'*16+'.sock')]
