"""Pinned generic operational helpers extracted from the previously reviewed release.

Origin SHA256 fd7f0e42c2f7af0ca6f30b8bd1f4ff182d6b5f09f87c43a4f9ca39755df1f3e3.
SDK feature-specific stages/constants are intentionally excluded.
"""
from __future__ import annotations
import copy, fcntl, hashlib, json, os, re, stat, subprocess, sys, time, uuid
from pathlib import Path
from urllib.parse import urljoin, urlsplit

API='orbbec-agent-platform-platform-api-1'
DOMAIN='https://agent.orbbec.com.cn'
ENV_FILE='/opt/orbbec-agent-platform/private/platform.env'
ACTION=Path('/opt/orbbec-agent-platform/private/agent-brain-action.lock')
DEPLOY=Path('/opt/orbbec-agent-platform/.deploy.lock')
STAGE=None
SHA=None
LOCK_TOOL=None

def configure(stage, release, lock_tool):
    global STAGE, SHA, LOCK_TOOL
    STAGE=safe_path(Path(stage),directory=True)
    require(stat.S_IMODE(STAGE.stat().st_mode)==0o700,'private_stage_required')
    require(re.fullmatch(r'[0-9a-f]{40}',release) is not None,'release_sha_required')
    SHA=release
    LOCK_TOOL=safe_path(Path(lock_tool))

def require(condition, code):
    if not condition:
        raise ValueError(code)

def bind_mount_spec(options, source, target, readonly):
    """Map reviewed compose bind options to a HostConfig mount spec.

    Returns None for the create_host_path shorthand (Binds entry), otherwise the
    explicit Mounts entry. Only `propagation: rprivate` is supported beyond
    create_host_path: it matches both the engine default and the sole reviewed
    production use; any other propagation or unknown option fails closed, and
    create_host_path combined with propagation stays unsupported.
    """
    require(set(options)<={'create_host_path','propagation'},'replay_bind_options_unsupported')
    propagation=options.get('propagation')
    require(propagation in (None,'rprivate'),'replay_bind_propagation_unsupported')
    if options.get('create_host_path',False):
        require(propagation is None,'replay_bind_options_unsupported')
        return None
    value={'Type':'bind','Source':source,'Target':target,
           'BindOptions':{'Propagation':propagation} if propagation else {}}
    if readonly:value['ReadOnly']=True
    return value

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def safe_path(path, *, directory=False):
    p = Path(path)
    require(p.is_absolute() and '..' not in p.parts, 'unsafe_path')
    current = Path(p.anchor)
    for part in p.parts[1:]:
        current /= part
        require(not current.is_symlink(), 'symlink_path')
    require(p.is_dir() if directory else p.is_file(), 'missing_path')
    return p

def file_tree(root):
    root = safe_path(root, directory=True)
    result = {}
    for p in sorted(root.rglob('*')):
        require(not p.is_symlink(), 'tree_symlink')
        if p.is_dir():
            continue
        require(p.is_file(), 'tree_not_regular')
        result[p.relative_to(root).as_posix()] = {
            'sha256': digest(p), 'size_bytes': p.stat().st_size,
            'mode': stat.S_IMODE(p.stat().st_mode)}
    return result

def discover_files(api):
    files = api['Config']['Labels']['com.docker.compose.project.config_files'].split(',')
    require(files and len(set(files)) == len(files), 'invalid_compose_chain')
    for path in files:
        safe_path(path)
    return files

REPLAY_KEYS = {'image','environment','command','entrypoint','user','healthcheck',
               'cap_drop','read_only','restart','security_opt','tmpfs','networks',
               'volumes','depends_on'}

COMPOSE_LABELS = {'com.docker.compose.project','com.docker.compose.service',
    'com.docker.compose.oneoff','com.docker.compose.container-number',
    'com.docker.compose.version','com.docker.compose.image','com.docker.compose.config-hash',
    'com.docker.compose.project.working_dir','com.docker.compose.project.config_files',
    'com.docker.compose.project.environment_file','com.docker.compose.replace','com.docker.compose.depends_on'}

def env_dict(entries):
    result={}
    for entry in entries or []:
        require(isinstance(entry,str) and '=' in entry,'replay_invalid_environment')
        key,value=entry.split('=',1)
        require(key not in result,'replay_duplicate_environment');result[key]=value
    return result

def command_value(value):
    require(isinstance(value,list) and all(isinstance(v,str) for v in value),'replay_command_form')
    # `compose config` escapes the already interpolated literal dollar sign.
    return [v.replace('$$','$') for v in value]

def duration_ns(value):
    require(isinstance(value,str),'replay_health_duration_type')
    match=re.fullmatch(r'(\d+)(ns|us|ms|s|m|h)',value)
    require(match is not None,'replay_health_duration_form')
    return int(match[1])*{'ns':1,'us':1000,'ms':1000000,'s':10**9,'m':60*10**9,'h':3600*10**9}[match[2]]

def replay_equivalence(config,api,image,probe,volume_info):
    s=config['services']['platform-api'];ic=image['Config']
    require(set(s)<=REPLAY_KEYS,'replay_unknown_service_key')
    require(probe['Image']==image['Id']==api['Image'],'replay_probe_image')
    require(probe['Config']['Image']==image['Id'] and probe['Config']['Hostname']==probe['Id'][:12],'replay_probe_overrides')
    require(probe['State']['Status']=='created' and probe['State']['Running'] is False,'replay_probe_started')
    require(not probe.get('Mounts') and not probe['HostConfig'].get('Binds') and not probe['HostConfig'].get('Mounts') and
            probe['HostConfig']['NetworkMode']=='none','replay_probe_has_mounts_or_network')
    require(env_dict(probe['Config'].get('Env'))==env_dict(ic.get('Env')),'replay_probe_environment_injected')
    for key in ['Cmd','Entrypoint','User','WorkingDir','Healthcheck','Volumes','ExposedPorts','Labels']:
        require(probe['Config'].get(key)==ic.get(key),'replay_probe_image_defaults_changed:'+key)
    expected=copy.deepcopy(probe['Config'])
    expected['Hostname']=api['Id'][:12];expected['Image']=s['image']
    expected_env=env_dict(ic.get('Env'));given_env=s.get('environment',{})
    require(all(isinstance(k,str) and isinstance(v,str) for k,v in given_env.items()),'replay_null_or_invalid_environment')
    expected_env.update(given_env)
    require(env_dict(api['Config'].get('Env'))==expected_env,'replay_environment_mismatch')
    for source,target in [('command','Cmd'),('entrypoint','Entrypoint')]:
        if s.get(source) is not None:expected[target]=command_value(s[source])
    if 'user' in s:expected['User']=s['user']
    if 'healthcheck' in s:
        health=s['healthcheck'];require(set(health)<={'test','timeout','interval','retries','start_period'},'replay_health_unknown_key')
        expected['Healthcheck']=copy.deepcopy(ic.get('Healthcheck') or {})
        for field,docker_field in [('test','Test'),('timeout','Timeout'),('interval','Interval'),('retries','Retries'),('start_period','StartPeriod')]:
            if field in health:
                value=health[field]
                expected['Healthcheck'][docker_field]=command_value(value) if field=='test' else value if field=='retries' else duration_ns(value)
    actual=copy.deepcopy(api['Config'])
    for row in [actual,expected]:
        row.pop('Env',None);row.pop('Labels',None)
    require(actual==expected,'replay_config_mismatch')
    labels=api['Config'].get('Labels') or {}
    require(not any(k.startswith('com.docker.compose.') and k not in COMPOSE_LABELS for k in labels),'replay_unknown_compose_label')
    require({k:v for k,v in labels.items() if k not in COMPOSE_LABELS}==(ic.get('Labels') or {}),'replay_custom_runtime_label')

    host=copy.deepcopy(probe['HostConfig'])
    host.update(ReadonlyRootfs=s.get('read_only',False),CapDrop=s.get('cap_drop'),
                SecurityOpt=s.get('security_opt'),RestartPolicy={'Name':s.get('restart','no'),'MaximumRetryCount':0})
    # Compose sends an explicit empty ExtraHosts array when the key is absent.
    host['ExtraHosts']=[]
    tmpfs={}
    for value in s.get('tmpfs',[]):
        require(isinstance(value,str) and ':' in value,'replay_tmpfs_form')
        target,options=value.split(':',1);require(target not in tmpfs,'replay_tmpfs_duplicate');tmpfs[target]=options
    host['Tmpfs']=tmpfs
    binds,mounts,effective=[],[],[]
    for volume in s.get('volumes',[]):
        require(set(volume)<={'type','source','target','read_only','bind','volume'},'replay_volume_unknown_key')
        kind,source,target=volume['type'],volume['source'],volume['target']
        readonly=volume.get('read_only',False);mode='ro' if readonly else 'rw'
        require(isinstance(readonly,bool),'replay_volume_readonly_form')
        if kind=='volume':
            require(volume.get('volume',{})=={},'replay_volume_options_unsupported')
            name=config['volumes'][source]['name'];info=volume_info[name]
            require(info['Name']==name and info['Driver']=='local','replay_named_volume_identity')
            binds.append(name+':'+target+':'+mode)
            effective.append({'Type':'volume','Name':name,'Source':info['Mountpoint'],'Destination':target,
                              'Driver':'local','Mode':mode,'RW':not readonly,'Propagation':''})
        elif kind=='bind':
            options=volume.get('bind',{})
            spec=bind_mount_spec(options,source,target,readonly)
            if spec is None:binds.append(source+':'+target+':'+mode)
            else:mounts.append(spec)
            effective.append({'Type':'bind','Source':source,'Destination':target,'Mode':mode if options.get('create_host_path',False) else '',
                              'RW':not readonly,'Propagation':'rprivate'})
        else:raise ValueError('replay_volume_type_unsupported')
    require(len({v['Destination'] for v in effective})==len(effective),'replay_duplicate_mount')
    host['Binds']=binds or probe['HostConfig'].get('Binds')
    if mounts:host['Mounts']=mounts
    actual_host=copy.deepcopy(api['HostConfig'])
    for row in [host,actual_host]:
        if row.get('Binds'):row['Binds']=sorted(row['Binds'])
        if row.get('Mounts'):row['Mounts']=sorted(row['Mounts'],key=lambda v:v['Target'])
        # Engine JSON uses null and [] for the same absent list depending on
        # docker CLI versus Compose request encoding. Keep every key and reject
        # every nonempty difference; this is not an absent-field bypass.
        for key in ['BlkioWeightDevice','BlkioDeviceReadBps','BlkioDeviceWriteBps',
                    'BlkioDeviceReadIOps','BlkioDeviceWriteIOps','Devices','DnsOptions','DnsSearch','Ulimits']:
            if key in row and row[key] is None:row[key]=[]
        if 'OomKillDisable' in row and row['OomKillDisable'] is None:row['OomKillDisable']=False
    networks=s['networks'];expected_names={config['networks'][n]['name'] for n in networks}
    priority=[]
    for name,options in networks.items():
        options=options or {};require(set(options)<={'gw_priority','ipv4_address'},'replay_network_options_unsupported')
        priority.append((options.get('gw_priority',0),config['networks'][name]['name']))
    require(priority,'replay_network_missing');priority.sort(reverse=True)
    require(len(priority)==1 or priority[0][0]>priority[1][0],'replay_network_primary_ambiguous')
    host['NetworkMode']=priority[0][1]
    require(actual_host==host,'replay_hostconfig_mismatch')
    require(sorted(api['Mounts'],key=lambda v:v['Destination'])==sorted(effective,key=lambda v:v['Destination']),'replay_effective_mounts_mismatch')
    actual_networks=api['NetworkSettings']['Networks']
    require(set(actual_networks)==expected_names,'replay_network_set_mismatch')
    require(api['Name']=='/'+config['name']+'-platform-api-1','replay_container_name')
    for name,options in networks.items():
        options=options or {};row=actual_networks[config['networks'][name]['name']]
        ipam={'IPv4Address':options.get('ipv4_address',''),'IPv6Address':''}
        require(row.get('IPAMConfig')==ipam,'replay_network_ipam_mismatch')
        if options.get('ipv4_address'):require(row.get('IPAddress')==options['ipv4_address'],'replay_network_fixed_ip_mismatch')
        require(row.get('GwPriority',0)==options.get('gw_priority',0),'replay_network_gateway_priority')
        require(sorted(row.get('Aliases') or [])==sorted([api['Name'].lstrip('/'),'platform-api']),'replay_network_alias_mismatch')
        require(row.get('DriverOpts') is None and row.get('Links') is None,'replay_network_runtime_options')
        if 'DNSNames' in row:
            require(sorted(row['DNSNames'])==sorted([api['Name'].lstrip('/'),'platform-api',api['Id'][:12]]),'replay_network_dns_names')
    return {'replay_equivalent':True,'environment_keys':len(expected_env),'mounts':len(effective),'networks':len(networks),
            'config_fields':len(actual),'hostconfig_fields':len(host),'defaults_origin':'pinned_never_started_no_mount_probe'}

def run(args, *, env=None, data=None, timeout=180):
    token = uuid.uuid4().hex
    try:
        result = subprocess.run([str(a) for a in args], env=env, input=data, capture_output=True, timeout=timeout)
    except BaseException as error:
        if isinstance(error,subprocess.TimeoutExpired):
            private_bytes('operation-'+token+'.stdout.private',error.stdout or b'')
            private_bytes('operation-'+token+'.stderr.private',error.stderr or b'')
        write('operation-' + token + '.private.json', {'status': 'exception', 'kind': type(error).__name__, 'program': str(args[0])})
        raise RuntimeError('operation_exception:' + token) from None
    # Successful output can also include configuration, accounts or business data.
    private_bytes('operation-' + token + '.stdout.private', result.stdout)
    private_bytes('operation-' + token + '.stderr.private', result.stderr)
    require(result.returncode == 0, 'operation_failed:' + token)
    return result.stdout

def private_bytes(name, raw):
    path = STAGE / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(raw)

def write(name, value):
    # Receipts are replaced atomically; the stage itself is never public.
    path = STAGE / name
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex)
    private_bytes(str(temp.relative_to(STAGE)), json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode() + b'\n')
    os.replace(temp, path)

def read(name):
    return json.loads(safe_path(STAGE / name).read_text())

def inspect(name):
    return json.loads(run(['docker', 'inspect', name]))[0]

def identities():
    names = run(['docker', 'ps', '-a', '--format', '{{.Names}}']).decode().splitlines()
    return {name: {'id': row['Id'], 'image': row['Image']} for name in names for row in [inspect(name)]}

def actual_environment(api):
    entries = api['Config']['Env']
    require(len({v.split('=', 1)[0] for v in entries}) == len(entries), 'duplicate_runtime_environment')
    return dict(v.split('=', 1) for v in entries)

def environment(api):
    # Compose interpolation must not inherit arbitrary caller overrides. Current
    # effective environment is subsequently compared with the running container.
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PLATFORM_', 'COMPOSE_', 'SDK_'))}
    actual = actual_environment(api)
    if 'PLATFORM_HR_AGENT_MODEL' in actual:
        env['PLATFORM_HR_AGENT_MODEL'] = actual['PLATFORM_HR_AGENT_MODEL']
    return env

def compose(files, added=False):
    cmd = ['docker', 'compose', '--project-name', 'orbbec-agent-platform', '--env-file', ENV_FILE]
    for path in files:
        cmd += ['-f', path]
    if added:
        cmd += ['-f', str(STAGE / 'overlay.json')]
    return cmd

MAP_CODE = """from pathlib import Path
import hashlib,json
r=Path('/app/backend/app')
source={p.relative_to(r).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in r.rglob('*') if p.is_file() and 'static' not in p.relative_to(r).parts and '__pycache__' not in p.parts and p.suffix!='.pyc'}
s=r/'static';static={p.relative_to(s).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in s.rglob('*') if p.is_file()}
print(json.dumps({'source':source,'static':static}))
"""

def maps(container):
    return json.loads(run(['docker', 'exec', container, 'python', '-c', MAP_CODE]))

class Locks:
    """Host flock + persistent action/input locks; uncertainty keeps persistent locks."""
    def __init__(self, input_lock=False):
        self.input_lock = input_lock
        self.fd = None
        self.action_owned = self.input_owned = self.retained = False
        self.token, self.deploy_id = str(uuid.uuid4()), uuid.uuid4().hex

    def __enter__(self):
        self.fd = os.open(DEPLOY, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self.fd);self.fd=None
            raise
        try:
            ACTION.mkdir(mode=0o700)
            self.action_owned = True
            fd=os.open(ACTION/'owner',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w') as f: f.write(self.token+'\n')
            if self.input_lock:
                self.retained=True
                run(['python3', LOCK_TOOL, 'acquire', SHA, self.deploy_id])
                self.input_owned = True
                self.retained=False
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def __exit__(self, *error):
        try:
            if self.retained:
                write('locks-retained.private.json', {'action_owner':self.token,'deploy_id':self.deploy_id,'reason':'rollback_uncertain','flock_lifetime':'process_only'})
                return
            if self.input_owned:
                try:
                    run(['python3',LOCK_TOOL,'release',SHA,self.deploy_id])
                except BaseException:
                    self.retained=True
                    write('locks-retained.private.json',{'action_owner':self.token,'deploy_id':self.deploy_id,'reason':'input_lock_release_failed'})
                    raise
            if self.action_owned:
                require((ACTION/'owner').read_text().strip()==self.token,'action_lock_owner_changed')
                (ACTION/'owner').unlink();ACTION.rmdir()
        finally:
            if self.fd is not None:
                os.close(self.fd);self.fd=None

def http(url, *, method='GET', body=None, headers=None):
    u=urlsplit(url)
    require(u.scheme=='https' and u.hostname in {'agent.orbbec.com.cn','fae.orbbec.com.cn'},'http_url_forbidden')
    header_path=STAGE/('headers-'+uuid.uuid4().hex+'.private')
    args=['curl','--silent','--show-error','--max-time','12','--resolve',u.hostname+':443:127.0.0.1',
          '--dump-header',str(header_path),'--write-out','\n%{http_code}','--request',method]
    for key,value in (headers or {}).items(): args+=['--header',key+': '+value]
    if body is not None: args+=['--header','Content-Type: application/json','--data-binary','@-']
    args += [url]
    # umask is 077 before any command, including curl file creation.
    raw=run(args,data=None if body is None else canonical(body),timeout=20)
    response,status=raw.rsplit(b'\n',1)
    lines=header_path.read_text().splitlines()
    parsed={k.strip().lower():v.strip() for line in lines if ':' in line for k,v in [line.split(':',1)]}
    return int(status),response,parsed

def resource_snapshot(urls):
    pending=list(urls); result={}
    while pending:
        url=pending.pop(0)
        if url in result: continue
        code,body,headers=http(url)
        result[url]={'status':code,'sha256':hashlib.sha256(body).hexdigest(),
                     'location':headers.get('location')}
        if code==200 and ('text/html' in headers.get('content-type','') or b'<html' in body[:1000].lower()):
            for value in re.findall(r'(?:src|href)=[\"\x27]([^\"\x27]+)[\"\x27]',body.decode(errors='replace')):
                linked=urljoin(url,value);u=urlsplit(linked)
                if u.hostname==urlsplit(url).hostname and u.path.endswith(('.js','.css')):
                    require(len(result)+len(pending)<512,'resource_limit')
                    pending.append(linked)
    require(any('/office/' in url and urlsplit(url).path.endswith(('.js','.css')) and row['status']==200 for url,row in result.items()),'office_assets_not_observed')
    return result


def runtime_values(old,new):
    a,b=copy.deepcopy(old['Config']),copy.deepcopy(new['Config'])
    if 'Hostname' in a or 'Hostname' in b:
        require(a.get('Hostname')==old['Id'][:12] and b.get('Hostname')==new['Id'][:12],'runtime_custom_hostname')
        a.pop('Hostname');b.pop('Hostname')
    for value in [a,b]:
        for key in ['Image','Env','Labels']:value.pop(key,None)
    require(a==b,'runtime_config_changed')
    a,b=copy.deepcopy(old['HostConfig']),copy.deepcopy(new['HostConfig'])
    for value in [a,b]:
        value.pop('Binds',None);value.pop('Mounts',None)
    require(a==b,'runtime_hostconfig_changed')
    require(set(old['NetworkSettings']['Networks'])==set(new['NetworkSettings']['Networks']),'runtime_network_changed')
    a,b=copy.deepcopy(old['Config']['Labels']),copy.deepcopy(new['Config']['Labels'])
    for value in [a,b]:
        for key in ['com.docker.compose.config-hash','com.docker.compose.image','com.docker.compose.project.config_files']:
            value.pop(key,None)
    require(a==b,'runtime_labels_changed')
