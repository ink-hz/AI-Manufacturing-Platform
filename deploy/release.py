"""Manufacturing-only API rollout; private receipts and exact runtime preservation."""
from __future__ import annotations
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import time
import uuid
from release_guard import validate_candidate,validate_upgrade_candidate,workflow_environment,WORKFLOW_FIELDS
import release_support as ops
import native_release

READINESS_CODE = '''import os,sys,json
assert os.getuid()==10001
sys.path.insert(0,os.environ['PLATFORM_MANUFACTURING_ROOT']+'/src')
from manufacturing_platform.repository import Repository
from manufacturing_platform.project_repository import ProjectRepository
from manufacturing_platform.catalog import load_catalog
database=os.environ['PLATFORM_MANUFACTURING_DATABASE_PATH']
Repository(database).health()
projects=ProjectRepository(database,load_catalog())
with projects._connection() as connection:
    connection.execute('SELECT 1').fetchone()
assert os.statvfs(os.environ['PLATFORM_MANUFACTURING_ROOT']).f_flag & os.ST_RDONLY
workflow=None
keys=['WORKFLOW_DATABASE_PATH','AUTHORITY_DATABASE_PATH','DATASET_ID','DATASET_MODE','DATASET_LABEL']
values=[os.environ.get('PLATFORM_MANUFACTURING_'+key) for key in keys]
if any(v is not None for v in values):
    assert all(values)
    from pathlib import Path
    from manufacturing_platform.workflow.store import WorkflowStore
    from manufacturing_platform.workflow.schema import SCHEMA_VERSION
    domain,authority,dataset_id,mode,label=values
    paths=list(map(Path,[database,domain,authority]))
    assert len({str(p.resolve()) for p in paths})==3
    assert not any(p.is_symlink() for p in paths)
    existing=[p for p in paths if p.exists()]
    assert len({(p.stat().st_dev,p.stat().st_ino) for p in existing})==len(existing)
    store=WorkflowStore(domain,authority,{'id':dataset_id,'mode':mode,'label':label})
    with store.transaction() as connection:
        assert connection.execute('SELECT version FROM schema_version').fetchone()[0]==SCHEMA_VERSION
        assert tuple(connection.execute('SELECT id,mode,label FROM dataset_metadata').fetchone())==(dataset_id,mode,label)
        assert connection.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    workflow={'schema_ready':True,'schema_version':SCHEMA_VERSION,'dataset_id':dataset_id,'dataset_mode':mode,'dataset_label':label,'database_path':domain,'authority_database_path':authority,'authority_ready':False,'authority_status':'external_adapter_unverified'}
    if mode=='demo':
        from manufacturing_platform.workflow.adapters.mock_store import MockStore
        with MockStore(authority,dataset_id).transaction() as connection:
            assert connection.execute('SELECT dataset FROM metadata').fetchone()[0]==dataset_id
            assert connection.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        workflow.update(authority_ready=True,authority_status='independent_demo_store')
    else:assert mode=='production'
print(json.dumps({'schema_ready':True,'source_read_only':True,'business_records_written':0,'workflow':workflow}))
'''


# This code never imports business modules: opening a WorkflowStore can migrate.
# mode=ro deliberately includes committed WAL state; immutable=1 must not be used.
WORKFLOW_COMPATIBILITY_CODE = '''import ast,hashlib,json,os,sqlite3,stat,struct,sys,tempfile,time
from contextlib import ExitStack,closing
from pathlib import Path
SNAPSHOT_LIMIT=16*1024*1024
result={'compatible':False,'expected_schema_version':None,'observed_schema_version':None}
def require(value,reason):
    if not value:raise ValueError(reason)
def safe_file(path,required=True):
    require(path.is_absolute() and '..' not in path.parts,'unsafe_path')
    require(not any(p.is_symlink() for p in [path,*path.parents]),'symlink_path')
    if not path.exists():
        require(not required,'missing_database')
        return None
    info=path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink==1,'nonregular_or_aliased_file')
    return (info.st_dev,info.st_ino)
def fingerprint(info):
    return {key:getattr(info,'st_'+key) for key in ['dev','ino','size','mtime_ns','ctime_ns','mode','nlink']}
def source_state(domain):
    states={}
    for suffix in ['', '-wal','-shm','-journal']:
        path=Path(str(domain)+suffix)
        states[suffix]=fingerprint(path.stat()) if safe_file(path,suffix=='') is not None else None
    require(states['-journal'] is None,'rollback_journal_present')
    return states
def stream(fd,size,destination=None):
    os.lseek(fd,0,os.SEEK_SET);digest=hashlib.sha256();remaining=size
    while remaining:
        block=os.read(fd,min(65536,remaining))
        require(block,'snapshot_source_truncated')
        remaining-=len(block);digest.update(block)
        if destination is not None:destination.write(block)
    require(not os.read(fd,1),'snapshot_source_grew')
    return digest.hexdigest()
def verify_sources(domain,states,files,hashes):
    require(source_state(domain)==states,'snapshot_source_changed')
    for suffix,fd in files.items():
        require(fingerprint(os.fstat(fd))==states[suffix],'snapshot_source_fd_changed')
        require(stream(fd,states[suffix]['size'])==hashes[suffix],'snapshot_source_hash_changed')
        require(fingerprint(os.fstat(fd))==states[suffix],'snapshot_source_fd_changed')
    require(source_state(domain)==states,'snapshot_source_changed')
def validate_wal(path):
    # SQLite ignores invalid trailing frames. Refuse them instead of accepting a
    # possibly older main DB. A zero-byte WAL is a valid no-frame state.
    data=path.read_bytes()
    if not data:return
    require(len(data)>=32,'snapshot_wal_truncated')
    magic,version,page_size=struct.unpack('>III',data[:12])
    require(magic in (0x377f0682,0x377f0683) and version==3007000,'snapshot_wal_header')
    require(512<=page_size<=65536 and page_size&(page_size-1)==0,'snapshot_wal_page_size')
    require((len(data)-32)%(24+page_size)==0,'snapshot_wal_truncated')
    endian='<' if magic==0x377f0682 else '>'
    def checksum(block,state):
        a,b=state
        for x,y in struct.iter_unpack(endian+'II',block):
            a=(a+x+b)&0xffffffff;b=(b+y+a)&0xffffffff
        return a,b
    state=checksum(data[:24],(0,0))
    require(state==struct.unpack('>II',data[24:32]),'snapshot_wal_checksum')
    for offset in range(32,len(data),24+page_size):
        frame=data[offset:offset+24+page_size]
        require(frame[8:16]==data[16:24] and struct.unpack('>I',frame[:4])[0]>0,'snapshot_wal_frame')
        state=checksum(frame[:8]+frame[24:],state)
        require(state==struct.unpack('>II',frame[16:24]),'snapshot_wal_checksum')
try:
    payload=json.load(sys.stdin);config=payload['workflow'];root=Path(payload['data_root'])
    source=Path(payload['source_root'])/'src/manufacturing_platform/workflow/schema.py'
    safe_file(source)
    require(source.stat().st_size<2000000,'schema_source_too_large')
    nodes=ast.parse(source.read_text()).body
    declarations=[n for n in nodes if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SCHEMA_VERSION' for t in n.targets)]
    require(len(declarations)==1 and len(declarations[0].targets)==1,'schema_declaration')
    value=declarations[0].value
    require(isinstance(value,ast.Constant) and type(value.value) is int and value.value>0,'schema_literal')
    expected=value.value;result['expected_schema_version']=expected
    paths=[root/'workbench.sqlite3',Path(config['database_path']),Path(config['authority_database_path'])]
    require(len(set(paths))==3 and all(p.parent==root and p.suffix=='.sqlite3' for p in paths),'database_path')
    identities=[safe_file(p,p==paths[1]) for p in paths]
    existing=[v for v in identities if v is not None]
    require(len(set(existing))==len(existing),'database_alias')
    domain=paths[1]
    result.update(database_path=str(domain),probe_method='verified_private_snapshot')
    states=source_state(domain)
    require(sum(states[s]['size'] for s in ['', '-wal'] if states[s] is not None)<=SNAPSHOT_LIMIT,'snapshot_size_limit')
    with ExitStack() as stack:
        files={};hashes={}
        for suffix in ['', '-wal']:
            if states[suffix] is None:continue
            fd=os.open(str(domain)+suffix,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            stack.callback(os.close,fd);files[suffix]=fd
            require(fingerprint(os.fstat(fd))==states[suffix],'snapshot_source_fd_changed')
            hashes[suffix]=stream(fd,states[suffix]['size'])
        verify_sources(domain,states,files,hashes)
        private=Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='workflow-probe-',dir='/tmp')))
        snapshot=private/domain.name
        for suffix,fd in files.items():
            with Path(str(snapshot)+suffix).open('xb') as destination:
                require(stream(fd,states[suffix]['size'],destination)==hashes[suffix],'snapshot_source_hash_changed')
            require(hashlib.sha256(Path(str(snapshot)+suffix).read_bytes()).hexdigest()==hashes[suffix],'snapshot_copy_hash_changed')
        verify_sources(domain,states,files,hashes)
        result['snapshot_sources']={suffix:({**states[suffix],'sha256':hashes[suffix]} if suffix in files else None) for suffix in ['', '-wal']}
        if '-wal' in files:validate_wal(Path(str(snapshot)+'-wal'))
        with closing(sqlite3.connect(snapshot.as_uri()+'?mode=ro',uri=True,timeout=2)) as connection:
            connection.execute('PRAGMA query_only=ON')
            deadline=time.monotonic()+5
            connection.set_progress_handler(lambda:time.monotonic()>deadline,1000)
            connection.execute('BEGIN')
            versions=connection.execute('SELECT version FROM schema_version').fetchmany(2)
            require(len(versions)==1 and type(versions[0][0]) is int,'schema_version_rows')
            result['observed_schema_version']=versions[0][0]
            metadata=connection.execute('SELECT id,mode,label FROM dataset_metadata').fetchmany(2)
            require(metadata==[(config['dataset_id'],config['dataset_mode'],config['dataset_label'])],'dataset_mismatch')
            require(connection.execute('PRAGMA quick_check(1)').fetchall()==[('ok',)],'database_integrity')
        verify_sources(domain,states,files,hashes)
        require([safe_file(p,p==domain) for p in paths]==identities,'database_identity_changed')
        result['source_unchanged']=True
        require(versions==[(expected,)],'schema_version_incompatible')
    result.update(compatible=True,dataset_verified=True)
except Exception as error:
    result.update(reason=str(error),error_type=type(error).__name__)
print(json.dumps(result))
'''


def require(value, reason):
    if not value:
        raise ValueError(reason)


def tree_hashes(root):
    return {p.relative_to(root).as_posix():ops.digest(p) for p in sorted(root.rglob('*')) if p.is_file()}


def request_data(stage):
    value=json.loads((stage/'request.json').read_text())
    for key in ['platform_commit','manufacturing_commit']:
        require(re.fullmatch(r'[0-9a-f]{40}',value[key]) is not None,'invalid_release_commit')
    require(value.get('mode','initial') in {'initial','upgrade'},'invalid_release_mode')
    if value.get('mode')=='upgrade':
        for key in ['expected_old_platform_commit','expected_old_manufacturing_commit']:
            require(re.fullmatch(r'[0-9a-f]{40}',value[key]) is not None,'invalid_baseline_release')
    return value


def workflow_configuration(e, *, baseline=False):
    old=e.get('baseline_workflow')
    if 'baseline_workflow' in e:workflow_environment(old)
    target=e.get('target_workflow',old)
    if 'target_workflow' in e:workflow_environment(target)
    require(old is None or target==old,'existing_workflow_configuration_changed')
    return old if baseline else target


def validate_workflow_storage(e):
    config=workflow_configuration(e)
    if config is None:return
    root=Path(e['data_host'])
    paths=[root/'workbench.sqlite3',*(root/Path(config[k]).name for k in ['database_path','authority_database_path'])]
    for path in paths:
        require(not any(p.is_symlink() for p in [path,*path.parents]),'workflow_storage_symlink')
        require(not path.exists() or path.is_file(),'workflow_storage_nonregular')
    identities=[(p.stat().st_dev,p.stat().st_ino) for p in paths if p.exists()]
    require(len(identities)==len(set(identities)),'workflow_storage_inode_alias')


def environment_delta(e):
    config=workflow_configuration(e)
    native=native_release.native_configuration(e)
    return {**(native_release.native_environment(native) if native else {}),**(workflow_environment(config) if config else {}),'PLATFORM_RELEASE_SHA':e['platform_commit'],
            'PLATFORM_MANUFACTURING_ROOT':'/opt/manufacturing',
            'PLATFORM_MANUFACTURING_DATABASE_PATH':'/app/data/manufacturing/workbench.sqlite3',
            'PLATFORM_MANUFACTURING_RELEASE':e['manufacturing_commit']}


def added_mounts(e):
    return [{'type':'bind','source':e['manufacturing_host'],'target':'/opt/manufacturing','read_only':True,'bind':{'create_host_path':False}},
            {'type':'bind','source':e['data_host'],'target':'/app/data/manufacturing','read_only':False,'bind':{'create_host_path':False}}]


def overlay_mounts(e):
    return added_mounts(e)[:1] if e.get('mode')=='upgrade' else added_mounts(e)


def baseline_environment(e):
    old={k:v for k,v in e.items() if k not in {'target_workflow','baseline_workflow','target_native','baseline_native'}}
    config=workflow_configuration(e,baseline=True)
    if config is not None:old['target_workflow']=config
    native=native_release.native_configuration(e,baseline=True)
    if native is not None:old['target_native']=native
    return {**environment_delta(old),'PLATFORM_RELEASE_SHA':e['expected_old_platform_commit'],
            'PLATFORM_MANUFACTURING_RELEASE':e['expected_old_manufacturing_commit']}


def previous_source(e):
    return '/data/orbbec-agent-platform/manufacturing/releases/'+e['expected_old_manufacturing_commit']


def validate_baseline(e,old):
    if e.get('mode')!='upgrade':return
    env=ops.actual_environment(old)
    for key in (set(WORKFLOW_FIELDS.values())|set(native_release.NATIVE_FIELDS.values()))-set(baseline_environment(e)):
        require(key not in env,'upgrade_baseline_workflow_expected_absent')
    require(all(env.get(key)==value for key,value in baseline_environment(e).items()),'upgrade_baseline_environment_drift')
    require(len({m['Destination'] for m in old['Mounts']})==len(old['Mounts']),'baseline_duplicate_mount')
    mounts={m['Destination']:m for m in old['Mounts']}
    code=mounts.get('/opt/manufacturing',{});data=mounts.get('/app/data/manufacturing',{})
    require(code.get('Type')=='bind' and code.get('Source')==previous_source(e) and code.get('RW') is False and code.get('Propagation')=='rprivate','baseline_code_mount')
    require(data.get('Type')=='bind' and data.get('Source')==e['data_host'] and data.get('RW') is True and data.get('Propagation')=='rprivate','baseline_data_mount')
    declarations=[m for m in old['HostConfig'].get('Mounts',[]) if m.get('Target')=='/opt/manufacturing']
    require(len(declarations)==1 and declarations[0].get('Source')==previous_source(e),'baseline_code_declaration')


def validate_configuration(e,baseline,candidate):
    if e.get('mode')=='upgrade':
        validate_upgrade_candidate(baseline,candidate,target_image=e['target_image'],environment_delta=environment_delta(e),
            baseline_environment=baseline_environment(e),new_code_mount=added_mounts(e)[0],data_mount=added_mounts(e)[1],native_enabled=native_release.native_configuration(e) is not None)
    else:
        validate_candidate(baseline,candidate,target_image=e['target_image'],environment_delta=environment_delta(e),new_mounts=added_mounts(e))


def validate_backend_manifest(e):
    old,new=e['backend_base_hashes'],e['backend_hashes']
    added=e.get('backend_added_files',[])
    require(isinstance(old,dict) and isinstance(new,dict) and set(old)==set(new),'backend_manifest_inventory')
    require(isinstance(added,list) and len(added)==len(set(added)) and set(added)<=(set(new)),'backend_added_inventory')
    require({k for k,v in old.items() if v is None}==set(added),'backend_expected_absence_review')
    for name in new:
        require(re.fullmatch(r'[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)*\.py',name) is not None,'backend_manifest_path')
        for value in [new[name],*([old[name]] if name not in added else [])]:
            require(isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value),'backend_manifest_hash')


def validate_backend_baseline(e,source):
    validate_backend_manifest(e)
    for path,expected in e['backend_base_hashes'].items():
        require((path not in source) if expected is None else source.get(path)==expected,'baseline_source_drift:'+path)


def validate_paths(e):
    native_release.sdk_request(e)
    native_release.native_configuration(e)
    workflow_configuration(e)
    base='/data/orbbec-agent-platform/manufacturing'
    require(e['manufacturing_host']==base+'/releases/'+e['manufacturing_commit'] and e['data_host']==base+'/data','unapproved_manufacturing_path')


trusted_stat=lambda path:path.lstat()


def validate_release_metadata(root):
    for path in [root,*sorted(root.rglob('*'))]:
        info=trusted_stat(path)
        require(info.st_uid==0 and info.st_gid==0,'business_ownership')
        if stat.S_ISDIR(info.st_mode):
            require(stat.S_IMODE(info.st_mode)==0o555,'business_directory_metadata')
        else:
            require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode)==0o444,'business_file_metadata')


def check_rollback_image(old):
    require(json.loads(ops.run(['docker','image','inspect',old['Config']['Image']]))[0]['Id']==old['Image'],'rollback_tag_drift')


def validate_image_defaults(baseline,target):
    require(baseline['Config']==target['Config'],'image_defaults_changed')


def check_images(e,old):
    check_rollback_image(old)
    baseline=json.loads(ops.run(['docker','image','inspect',old['Image']]))[0]
    target=json.loads(ops.run(['docker','image','inspect',e['target_image']]))[0]
    require(target['Id']==e['target_image_id'],'target_tag_drift')
    validate_image_defaults(baseline,target)


def invalidate_success():
    for name in ['cutover.json','future-maintenance.json']:
        (ops.STAGE/name).unlink(missing_ok=True)


def publish_success(receipt,maintenance):
    try:
        ops.write('future-maintenance.json',maintenance)
        ops.write('cutover.json',receipt)  # Commit marker is published last.
    except BaseException:
        invalidate_success()
        raise


def snapshot_files(e):
    names=['request.json','release.py','release_support.py','release_guard.py','candidate_verify.py','candidate_fixture.py','sqlite_backup.py','native_release.py']
    result={name:ops.digest(ops.STAGE/name) for name in names}
    sdk=native_release.validate_sdk(ops.STAGE,e)
    if sdk is not None:
        native_release.validate_sdk_copy_metadata(ops.STAGE,e)
        result['build/native-sdk-manifest.json']=ops.digest(ops.STAGE/'build/native-sdk-manifest.json')
        result.update({'build/native-sdk/'+name:value for name,value in sdk['files'].items()})
    result.update(native_release.validate_native_storage(e))
    if workflow_configuration(e) is not None:
        require(re.fullmatch('[0-9a-f]{64}',e.get('candidate_fixture_sha256','')) is not None,'candidate_fixture_pin_required')
        result['candidate_fixture']=ops.digest(ops.STAGE/'candidate-fixture/fixture.json')
        require(result['candidate_fixture']==e['candidate_fixture_sha256'],'candidate_fixture_pin_mismatch')
    validate_paths(e)
    validate_workflow_storage(e)
    release=ops.safe_path(e['manufacturing_host'],directory=True)
    validate_release_metadata(release)
    state=ops.safe_path(e['data_host'],directory=True)
    info=state.stat()
    require(info.st_uid==10001 and info.st_gid==10001 and stat.S_IMODE(info.st_mode)==0o700,'state_directory_metadata')
    for parent in [release.parent,release.parent.parent,state.parent]:
        info=parent.stat()
        require(info.st_uid==0 and info.st_gid==0 and not stat.S_IMODE(info.st_mode)&0o022,'untrusted_manufacturing_parent')
    result['business_manifest']=ops.digest(release/'manifest.json')
    manifest=json.loads((release/'manifest.json').read_text())
    require(manifest['commit']==e['manufacturing_commit'],'business_commit_mismatch')
    observed=tree_hashes(release);observed.pop('manifest.json')
    require(observed==manifest['files'],'business_tree_mismatch')
    require(not any(p.is_symlink() for p in release.rglob('*')),'business_symlink')
    result['business_metadata']=hashlib.sha256(ops.canonical(ops.file_tree(release))).hexdigest()
    if e.get('mode')=='upgrade':
        previous=ops.safe_path(previous_source(e),directory=True)
        validate_release_metadata(previous)
        prior=json.loads((previous/'manifest.json').read_text())
        require(prior['commit']==e['expected_old_manufacturing_commit'],'previous_business_commit')
        actual=tree_hashes(previous);actual.pop('manifest.json')
        require(actual==prior['files'],'previous_business_content')
        result['previous_business_metadata']=hashlib.sha256(ops.canonical(ops.file_tree(previous))).hexdigest()
    return result


def compare_networks(old,new):
    before,after=old['NetworkSettings']['Networks'],new['NetworkSettings']['Networks']
    require(set(before)==set(after),'runtime_network_set_changed')
    for name in before:
        for key in ['NetworkID','IPAMConfig','GwPriority','Aliases','DriverOpts','Links']:
            require(before[name].get(key)==after[name].get(key),'runtime_network_option_changed')
        ipam=before[name].get('IPAMConfig') or {}
        if ipam.get('IPv4Address'):
            for key in ['IPAddress','IPPrefixLen']:
                require(before[name].get(key)==after[name].get(key),'runtime_fixed_ip_changed')
        if ipam.get('IPv6Address'):
            for key in ['GlobalIPv6Address','GlobalIPv6PrefixLen']:
                require(before[name].get(key)==after[name].get(key),'runtime_fixed_ipv6_changed')
        if 'DNSNames' in before[name] or 'DNSNames' in after[name]:
            expected=[new['Id'][:12] if value==old['Id'][:12] else value for value in before[name].get('DNSNames',[])]
            require(sorted(expected)==sorted(after[name].get('DNSNames',[])),'runtime_network_dns_changed')


def compare_rollback_runtime(old,restored):
    require(restored['Image']==old['Image'],'rollback_image_mismatch')
    require(ops.actual_environment(restored)==ops.actual_environment(old),'rollback_environment_mismatch')
    require(sorted(restored['Mounts'],key=lambda m:m['Destination'])==sorted(old['Mounts'],key=lambda m:m['Destination']),'rollback_mount_mismatch')
    ops.runtime_values(old,restored)
    before,after=copy.deepcopy(old['HostConfig']),copy.deepcopy(restored['HostConfig'])
    for row in [before,after]:
        if row.get('Mounts'):row['Mounts']=sorted(row['Mounts'],key=lambda m:m['Target'])
        if row.get('Binds'):row['Binds']=sorted(row['Binds'])
    require(before==after,'rollback_hostconfig_changed')
    compare_networks(old,restored)


def compare_runtime(old, new, e):
    require(new['Image']==e['target_image_id'],'deployed_image_mismatch')
    sdk=native_release.validate_sdk(ops.STAGE,e)
    if sdk is not None:native_release.check_container_sdk(ops.run,ops.API,sdk)
    require(ops.actual_environment(new)=={**ops.actual_environment(old),**environment_delta(e)},'runtime_environment_changed')
    old_mounts={v['Destination']:v for v in copy.deepcopy(old['Mounts'])}
    new_mounts={v['Destination']:v for v in new['Mounts']}
    require(len(old_mounts)==len(old['Mounts']),'baseline_duplicate_mount')
    require(len(new_mounts)==len(new['Mounts']),'runtime_duplicate_mounts')
    upgrade=e.get('mode')=='upgrade'
    if upgrade:
        validate_baseline(e,old)
        old_mounts['/opt/manufacturing']['Source']=e['manufacturing_host']
    else:
        for mount in added_mounts(e):
            row=new_mounts.pop(mount['target'],None)
            require(row and row['Type']=='bind' and row['Source']==mount['source'] and row['RW'] is (not mount['read_only']) and row.get('Propagation')=='rprivate','runtime_manufacturing_mount_mismatch')
    require(old_mounts==new_mounts,'existing_mount_changed')
    for field in ['Config','HostConfig']:
        before,after=copy.deepcopy(old[field]),copy.deepcopy(new[field])
        if field=='HostConfig' and upgrade:
            selected=[m for m in before.get('Mounts',[]) if m.get('Target')=='/opt/manufacturing']
            require(len(selected)==1,'runtime_code_declaration')
            selected[0]['Source']=e['manufacturing_host']
            for row in [before,after]:
                if row.get('Mounts'):row['Mounts']=sorted(row['Mounts'],key=lambda m:m['Target'])
                if row.get('Binds'):row['Binds']=sorted(row['Binds'])
        for row in [before,after]:
            for key in (['Hostname','Image','Env','Labels'] if field=='Config' else [] if upgrade else ['Binds','Mounts']):row.pop(key,None)
        require(before==after,'runtime_'+field+'_changed')
    for item in [old,new]:
        require(item['Config'].get('Hostname')==item['Id'][:12],'custom_hostname_changed')
    before,after=copy.deepcopy(old['Config']['Labels']),copy.deepcopy(new['Config']['Labels'])
    for row in [before,after]:
        for key in ['com.docker.compose.config-hash','com.docker.compose.image','com.docker.compose.project.config_files']:row.pop(key,None)
    require(before==after,'runtime_labels_changed')
    compare_networks(old,new)


def ready(image):
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        row=ops.inspect(ops.API)
        if row['State'].get('Health',{}).get('Status')=='healthy':
            require(row['Image']==image,'healthy_image_mismatch')
            return row
        time.sleep(2)
    raise ValueError('health_timeout')


def others_unchanged(before):
    observed=ops.identities()
    require({k:v for k,v in observed.items() if k!=ops.API}=={k:v for k,v in before.items() if k!=ops.API},'other_container_changed')


def workflow_compatibility(e):
    require(e.get('mode')=='upgrade' and workflow_configuration(e,baseline=True) is not None,'workflow_baseline_unconfigured')
    args=['docker','run','--rm','-i','--network','none','--read-only','--cap-drop','ALL',
          '--security-opt','no-new-privileges','--user','10001:10001',
          '--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=32m,mode=0700,uid=10001,gid=10001',
          '--mount',f"type=bind,source={previous_source(e)},target=/opt/manufacturing-previous,readonly",
          '--mount',f"type=bind,source={e['data_host']},target=/app/data/manufacturing,readonly",
          '--entrypoint','python',e['target_image_id'],'-B','-c',WORKFLOW_COMPATIBILITY_CODE]
    payload={'workflow':workflow_configuration(e),'source_root':'/opt/manufacturing-previous','data_root':'/app/data/manufacturing'}
    return json.loads(ops.run(args,data=ops.canonical(payload),timeout=30))


def no_other_workflow_writers(e,current):
    # All API workers/threads stop with their container. Refuse another running
    # container with a writable bind at, above, or below this dedicated data dir.
    root=Path(e['data_host'])
    for identity in ops.identities().values():
        if identity['id']==current['Id']:continue
        row=ops.inspect(identity['id'])
        if not row['State'].get('Running'):continue
        for mount in row['Mounts']:
            source=Path(mount['Source'])
            require(not (mount.get('RW') and (source==root or source in root.parents or root in source.parents)),
                    'other_workflow_writer_mount')


def workflow_readiness(config,container,expected_schema):
    result=json.loads(ops.run(['docker','exec',container,'python','-c',READINESS_CODE]))
    workflow=result.get('workflow') or {}
    require(result.get('schema_ready') is True and workflow.get('schema_ready') is True,'rollback_workflow_not_ready')
    require(all(workflow.get(k)==v for k,v in config.items()),'rollback_workflow_identity')
    require(workflow.get('schema_version')==expected_schema,'rollback_workflow_schema')
    return result


def workflow_maintenance(e,readiness):
    workflow=readiness.get('workflow') or {}
    require(workflow.get('schema_ready') is True and type(workflow.get('schema_version')) is int,'workflow_schema_not_recorded')
    baseline=None
    if e.get('mode')=='upgrade' and workflow_configuration(e,baseline=True) is not None:
        source=Path(previous_source(e))/'src/manufacturing_platform/workflow/schema.py'
        declarations=[n for n in ast.parse(source.read_text()).body if isinstance(n,ast.Assign)
                      and any(isinstance(t,ast.Name) and t.id=='SCHEMA_VERSION' for t in n.targets)]
        require(len(declarations)==1 and len(declarations[0].targets)==1,'baseline_schema_declaration')
        value=declarations[0].value
        require(isinstance(value,ast.Constant) and type(value.value) is int and value.value>0,'baseline_schema_literal')
        baseline=value.value
    return {'policy':'forward_only_after_schema_advance','baseline_schema_version':baseline,
            'target_schema_version':workflow['schema_version'],'readiness':workflow,
            'recovery':'After schema advance the previous release is not a valid source-only rollback target. '
                       'Preserve the live database and WAL; do not restore pre-cutover backups. Use forward repair. '
                       'Inspect failure/rollback receipts and actual runtime/schema before reconciling retained locks.'}


def rollback_workflow(e,pre,old,env,locks,error):
    """Only a quiesced, proven compatible database permits old-source replay."""
    locks.retained=True
    state={'policy':'forward_only_after_schema_advance','forward_repair_required':True,
           'old_runtime_restored':False,'original_failure':{'type':type(error).__name__,'reason':str(error)},
           'phase':'checking_runtime','target_restart':{'attempted':False}}
    current=None;stop_attempted=False;recreate_attempted=False
    def record():ops.write('workflow-rollback-state.private.json',state)
    try:
        record();unchanged(e,pre)
        current=ops.inspect(ops.API)
        baseline=current['Id']==old['Id']
        if baseline:compare_rollback_runtime(old,current)
        else:compare_runtime(old,current,e)
        require(ops.discover_files(current)==pre['files']+([] if baseline else [str(ops.STAGE/'overlay.json')]),'rollback_current_chain')
        require(current['State'].get('Running') is True,'rollback_current_not_running')
        no_other_workflow_writers(e,current)
        state.update(container=current['Id'],runtime='baseline' if baseline else 'target',phase='stopping')
        record()
        # Stop by full identity, never a mutable name. A failed stop command may
        # already have stopped it, so inspect/recover this same identity below.
        stop_attempted=True
        ops.run(['docker','stop','--time','30',current['Id']],timeout=45)
        stopped=ops.inspect(current['Id'])
        require(stopped['Id']==current['Id'] and stopped['State'].get('Running') is False,'rollback_stop_unconfirmed')
        if baseline:compare_rollback_runtime(old,stopped)
        else:compare_runtime(old,stopped,e)
        state['phase']='probing';record()
        state['compatibility']=workflow_compatibility(e)
        compatibility=state['compatibility']
        require(compatibility.get('compatible') is True and compatibility.get('dataset_verified') is True
                and type(compatibility.get('expected_schema_version')) is int and compatibility['expected_schema_version']>0
                and compatibility.get('observed_schema_version')==compatibility['expected_schema_version']
                and compatibility.get('database_path')==workflow_configuration(e)['database_path'],'workflow_rollback_refused')
        state['phase']='recreating_baseline';record()
        unchanged(e,pre);check_rollback_image(old)
        require(ops.inspect(current['Id'])['State'].get('Running') is False,'rollback_target_restarted')
        no_other_workflow_writers(e,current)
        recreate_attempted=True
        ops.run(ops.compose(pre['files'])+['up','-d','--no-build','--no-deps','--force-recreate','platform-api'],env=env)
        restored=ready(old['Image']);compare_rollback_runtime(old,restored)
        require(ops.discover_files(restored)==pre['files'],'rollback_chain_mismatch')
        require(ops.maps(ops.API)==pre['baseline_content'],'rollback_content_mismatch')
        others_unchanged(pre['containers'])
        state['phase']='checking_old_workflow';record()
        readiness=workflow_readiness(workflow_configuration(e,baseline=True),restored['Id'],state['compatibility']['expected_schema_version'])
        state.update(phase='verified_baseline',old_runtime_restored=True,forward_repair_required=False,readiness=readiness)
        record()
        ops.write('rollback.json',{'restored':True,'image':restored['Image'],'container':restored['Id'],
                  'manufacturing_data_retained':True,'compatibility':state['compatibility'],'readiness':readiness})
        locks.retained=False
    except BaseException as rollback_error:
        state.update(phase='forward_repair_required',old_runtime_restored=False,forward_repair_required=True,
                     failure={'type':type(rollback_error).__name__,'reason':str(rollback_error)})
        if stop_attempted and not recreate_attempted:
            try:
                observed=ops.inspect(current['Id'])
                require(observed['Id']==current['Id'] and ops.inspect(ops.API)['Id']==current['Id'],'recovery_identity_changed')
                compare_rollback_runtime(current,observed)
                if observed['State'].get('Running') is False:
                    state['target_restart']={'attempted':True,'container':current['Id']}
                    ops.run(['docker','start',current['Id']])
                resumed=ready(current['Image'])
                require(resumed['Id']==current['Id'],'recovery_identity_changed')
                compare_rollback_runtime(current,resumed)
                state['target_restart'].update(container=current['Id'],healthy=True)
            except BaseException as restart_error:
                state['target_restart'].update(healthy=False,error=str(restart_error))
        record()  # Failure here must keep locks, never trigger old Compose.


def prepare(e):
    with ops.Locks():
        require(not (ops.STAGE/'preflight.json').exists(),'prepare_already_done')
        old=ops.inspect(ops.API)
        require(old['State'].get('Health',{}).get('Status')=='healthy','baseline_unhealthy')
        require(old['Image']==e['expected_old_image'],'baseline_image_drift')
        validate_baseline(e,old)
        check_images(e,old)
        sdk=native_release.validate_sdk(ops.STAGE,e)
        if sdk is not None:
            native_release.validate_sdk_copy_metadata(ops.STAGE,e)
            native_release.check_container_sdk(ops.run,ops.API,sdk,baseline=True)
        native_release.validate_native_storage(e)
        files=ops.discover_files(old)
        require(len(files)==e['expected_chain_length'],'compose_chain_length_drift')
        env=ops.environment(old)
        baseline=json.loads(ops.run(ops.compose(files)+['config','--format','json'],env=env))
        image=json.loads(ops.run(['docker','image','inspect',old['Image']]))[0]
        probe_id=ops.run(['docker','create','--network','none',old['Image']]).decode().strip()
        try:probe=ops.inspect(probe_id)
        finally:ops.run(['docker','rm',probe_id])
        volumes={}
        for mount in baseline['services']['platform-api'].get('volumes',[]):
            if mount['type']=='volume':
                name=baseline['volumes'][mount['source']]['name']
                volumes[name]=json.loads(ops.run(['docker','volume','inspect',name]))[0]
        replay=ops.replay_equivalence(baseline,old,image,probe,volumes)
        overlay={'services':{'platform-api':{'image':e['target_image'],'environment':environment_delta(e),'volumes':overlay_mounts(e)}}}
        ops.write('overlay.json',overlay)
        candidate=json.loads(ops.run(ops.compose(files,True)+['config','--format','json'],env=env))
        validate_configuration(e,baseline,candidate)
        current=ops.maps(ops.API)
        validate_backend_baseline(e,current['source'])
        expected_source={**current['source'],**e['backend_hashes']}
        expected_static={**current['static'],**e['static_hashes']}
        require(json.loads(ops.run(['docker','image','inspect',e['target_image']]))[0]['Id']==e['target_image_id'],'target_tag_drift')
        (ops.STAGE/'backup').mkdir(mode=0o700)
        ops.write('backup/api-inspect.private.json',old)
        config_hashes={}
        for number,name in enumerate(dict.fromkeys(files+[ops.ENV_FILE,e['nginx_path']])):
            data=ops.safe_path(name).read_bytes();ops.private_bytes('backup/'+str(number)+'.private',data);config_hashes[name]=hashlib.sha256(data).hexdigest()
        resources=ops.resource_snapshot(e['resource_urls'])
        pre={'old':old,'files':files,'config_hashes':config_hashes,'artifact_hashes':snapshot_files(e),'containers':ops.identities(),'resources':resources,'baseline_content':current,'expected_source':expected_source,'expected_static':expected_static,'replay':replay,'overlay_sha256':ops.digest(ops.STAGE/'overlay.json')}
        ops.write('baseline-compose.private.json',baseline);ops.write('candidate-compose.private.json',candidate);ops.write('preflight.json',pre)
        print(json.dumps({'prepared':True,'compose_files':len(files),'runtime_replay':True,'unchanged_non_api':len(pre['containers'])-1}))


def unchanged(e,pre):
    require(snapshot_files(e)==pre['artifact_hashes'],'release_artifact_changed')
    require(ops.digest(ops.STAGE/'overlay.json')==pre['overlay_sha256'],'overlay_changed')
    for path,digest in pre['config_hashes'].items():require(ops.digest(path)==digest,'baseline_config_changed')
    others_unchanged(pre['containers'])


def candidate(e):
    with ops.Locks():
        pre=ops.read('preflight.json');unchanged(e,pre)
        require(ops.inspect(ops.API)['Id']==pre['old']['Id'],'running_container_drift')
        check_images(e,pre['old'])
        args=['docker','run','--rm','-i','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','10001:10001','--tmpfs','/tmp:rw,noexec,nosuid,size=32m']
        args+=['--mount',f"type=bind,source={e['manufacturing_host']},target=/opt/manufacturing,readonly"]
        if e.get('mode') == 'upgrade':
            args+=['--mount',f"type=bind,source={previous_source(e)},target=/opt/manufacturing-previous,readonly"]
            args+=['-e','PLATFORM_MANUFACTURING_PREVIOUS_ROOT=/opt/manufacturing-previous',
                   '-e','PLATFORM_MANUFACTURING_PREVIOUS_RELEASE='+e['expected_old_manufacturing_commit']]
        args+=['-e','PLATFORM_MANUFACTURING_ROOT=/opt/manufacturing','-e','PLATFORM_MANUFACTURING_DATABASE_PATH=/tmp/manufacturing-candidate.sqlite3','-e','PLATFORM_MANUFACTURING_RELEASE='+e['manufacturing_commit']]
        workflow=workflow_configuration(e) is not None
        payload={'expected_source':pre['expected_source'],'expected_static':pre['expected_static'],'business_commit':e['manufacturing_commit'],'workflow':workflow}
        if workflow:
            import candidate_fixture
            spec=candidate_fixture.validate_fixture(ops.STAGE,e,pre)
            candidate_name='manufacturing-private-'+uuid.uuid4().hex
            args.remove('--rm');args+=['--name',candidate_name]
            extra,private_env=candidate_fixture.candidate_arguments(ops.STAGE,e,spec)
            args+=extra
            private_env.update({'PLATFORM_MANUFACTURING_WORKFLOW_DATABASE_PATH':'/tmp/workflow-candidate.sqlite3',
                                'PLATFORM_MANUFACTURING_AUTHORITY_DATABASE_PATH':'/tmp/authority-candidate.sqlite3',
                                'PLATFORM_MANUFACTURING_DATASET_ID':'isolated-candidate-smoke',
                                'PLATFORM_MANUFACTURING_DATASET_MODE':'test','PLATFORM_MANUFACTURING_DATASET_LABEL':'Synthetic candidate test'})
            for key,value in private_env.items():args+=['-e',key+'='+value]
            payload['source_manifest_sha256']=spec['source_manifest_sha256']
        verifier=(ops.STAGE/'candidate_verify.py').read_text()
        sdk=native_release.validate_sdk(ops.STAGE,e)
        if sdk is not None:
            payload['native_sdk']=sdk
            verifier=(ops.STAGE/'native_release.py').read_text()+'\n'+verifier
        args+=['--entrypoint','python',e['target_image_id'],'-c',verifier]
        try:
            checked=json.loads(ops.run(args,data=ops.canonical(payload),timeout=3900 if workflow else 180))
        finally:
            if workflow:
                # Stop descendants before hashing/archive, including CLI timeout.
                ops.run(['docker','rm','-f',candidate_name])
                candidate_fixture.archive_evidence(ops.STAGE)
        if workflow:
            require(checked.get('workflow_acceptance',{}).get('cases')==36 and checked['workflow_acceptance'].get('passed') is True,'candidate_exact36_required')
        require(checked['passed'] is True,'candidate_not_passed')
        checked.update(preflight_sha256=ops.digest(ops.STAGE/'preflight.json'),request_sha256=ops.digest(ops.STAGE/'request.json'),image=e['target_image_id'])
        ops.write('candidate-validation.json',checked)
        print(json.dumps({'candidate_passed':True,'authenticated_identity':'synthetic_candidate_only','production_business_writes':0}))


def http_checks(e,pre):
    statuses={}
    for path,expected in [('/api/health',200),('/manufacturing',200),('/api/v1/manufacturing/access',401),('/api/v1/manufacturing/catalog',401),('/api/v1/manufacturing/health',401),('/api/v1/manufacturing/dashboard',401),('/api/v1/manufacturing/projects',401),('/api/v1/manufacturing/project-tasks',401),('/api/v1/manufacturing/handbook',401),('/api/v1/manufacturing/assets/manufacturing.js',401),('/sdk-admin',200),('/sdk/api.php/v1/users',403)]:
        status,body,headers=ops.http(ops.DOMAIN+path);require(status==expected,'http_status:'+path)
        require('no-store' in headers.get('cache-control',''),'http_cache:'+path)
        statuses[path]=status
    for path,expected_hash in e['static_hashes'].items():
        if not path.startswith('assets/'):continue
        status,body,headers=ops.http(ops.DOMAIN+'/'+path)
        if status==200:require(hashlib.sha256(body).hexdigest()==expected_hash,'public_asset_hash:'+path)
        else:require(status in {401,403} and 'no-store' in headers.get('cache-control',''),'public_asset_policy:'+path)
    require(ops.resource_snapshot(e['resource_urls'])==pre['resources'],'other_app_resource_changed')
    return statuses


def cutover(e):
    with ops.Locks(input_lock=True) as locks:
        pre=ops.read('preflight.json');checked=ops.read('candidate-validation.json');unchanged(e,pre)
        require(not (ops.STAGE/'cutover.json').exists(),'cutover_already_done')
        require(checked.get('passed') is True,'candidate_not_passed')
        require(checked['preflight_sha256']==ops.digest(ops.STAGE/'preflight.json') and checked['request_sha256']==ops.digest(ops.STAGE/'request.json') and checked['image']==e['target_image_id'],'candidate_receipt_changed')
        old=ops.inspect(ops.API);require(old['Id']==pre['old']['Id'] and old['Image']==pre['old']['Image'],'baseline_drift')
        require(ops.discover_files(old)==pre['files'],'compose_chain_drift')
        env=ops.environment(old)
        baseline=json.loads(ops.run(ops.compose(pre['files'])+['config','--format','json'],env=env))
        candidate_config=json.loads(ops.run(ops.compose(pre['files'],True)+['config','--format','json'],env=env))
        validate_configuration(e,baseline,candidate_config)
        check_images(e,old)  # Both target defaults and rollback tag are pinned before mutation.
        validate_baseline(e,old)
        backup=None
        if e.get('mode')=='upgrade':
            config=workflow_configuration(e)
            backup_paths={} if config is None else {'workflow':config['database_path'],'authority':config['authority_database_path']}
            backup=json.loads(ops.run(['docker','exec','-i','--user','10001:10001',ops.API,'python','-c',(ops.STAGE/'sqlite_backup.py').read_text()],data=ops.canonical(backup_paths),timeout=120))
            require(backup.get('verified') is True and backup.get('legacy_schema_present') is True,'sqlite_backup_not_verified')
            ops.write('sqlite-backup.private.json',backup)
        # Backup can take time. Recheck immutable rollback/target and live state
        # immediately before the first live container mutation.
        unchanged(e,pre);check_images(e,old)
        require(ops.inspect(ops.API)['Id']==old['Id'],'baseline_drift_after_backup')
        try:
            ops.run(ops.compose(pre['files'],True)+['up','-d','--no-build','--no-deps','--force-recreate','platform-api'],env=env,timeout=180)
            new=ready(e['target_image_id']);compare_runtime(old,new,e)
            require(ops.discover_files(new)==pre['files']+[str(ops.STAGE/'overlay.json')],'new_chain_mismatch')
            require(ops.maps(ops.API)=={'source':pre['expected_source'],'static':pre['expected_static']},'deployed_content_mismatch')
            # Initializes new SQLite schema under the actual UID; writes no business records.
            readiness=json.loads(ops.run(['docker','exec',ops.API,'python','-c',READINESS_CODE]))
            statuses=http_checks(e,pre);unchanged(e,pre)
            receipt={'status':'healthy','platform_commit':e['platform_commit'],'manufacturing_commit':e['manufacturing_commit'],'image':new['Image'],'container':new['Id'],'compose_files':pre['files']+[str(ops.STAGE/'overlay.json')],'readiness':readiness,'http_statuses':statuses,'database_backup':backup,'browser_acceptance':'not_run','production_erp_connections':'unverified'}
            maintenance={'compose_files_in_order':receipt['compose_files'],'platform_commit':e['platform_commit'],'manufacturing_commit':e['manufacturing_commit'],'image':new['Image'],'previous_manifest':e['previous_manifest'],'preservation':'All prior ordered overlays, mounts, networks, runtime security and Git capability retained.'}
            if workflow_configuration(e) is not None:maintenance['workflow_rollback']=workflow_maintenance(e,readiness)
            publish_success(receipt,maintenance)
            print(json.dumps({'deployed':True,'platform_commit':e['platform_commit'],'manufacturing_commit':e['manufacturing_commit'],'image':new['Image'],'compose_files':len(receipt['compose_files'])}))
        except BaseException as error:
            if workflow_configuration(e) is not None:
                locks.retained=True
                invalidate_success()
                ops.write('cutover-failure.private.json',{'type':type(error).__name__,'reason':str(error)})
                rollback_workflow(e,pre,old,env,locks,error)
                raise
            try:invalidate_success()
            except OSError:pass
            try:
                ops.write('cutover-failure.private.json',{'type':type(error).__name__,'reason':str(error)})
            except OSError:
                pass  # A full receipt disk must not block the rollback attempt.
            try:
                check_rollback_image(old)
                ops.run(ops.compose(pre['files'])+['up','-d','--no-build','--no-deps','--force-recreate','platform-api'],env=env)
                restored=ready(old['Image'])
                compare_rollback_runtime(old,restored)
                require(ops.discover_files(restored)==pre['files'],'rollback_chain_mismatch')
                require(ops.maps(ops.API)==pre['baseline_content'],'rollback_content_mismatch')
                others_unchanged(pre['containers'])
                ops.write('rollback.json',{'restored':True,'image':restored['Image'],'manufacturing_data_retained':True})
            except BaseException as rollback_error:
                locks.retained=True;ops.write('rollback-failure.private.json',{'type':type(rollback_error).__name__,'reason':str(rollback_error)})
            raise


if __name__=='__main__':
    os.umask(0o077)
    require(len(sys.argv)==3 and sys.argv[2] in {'prepare','candidate','cutover'},'usage_release_stage_action')
    stage=Path(sys.argv[1]);e=request_data(stage)
    ops.configure(stage,e['platform_commit'],e['lock_tool'])
    require(ops.digest(ops.LOCK_TOOL)==e['lock_tool_sha256'],'lock_tool_changed')
    def interrupted(number, frame):
        raise SystemExit('release_signal:'+str(number))
    for number in [signal.SIGTERM,signal.SIGHUP]:
        signal.signal(number,interrupted)
    try:globals()[sys.argv[2]](e)
    except BaseException as error:
        ops.write('failure-'+uuid.uuid4().hex+'.private.json',{'type':type(error).__name__,'reason':str(error)})
        print('MANUFACTURING_RELEASE_FAILED private_receipt_written',file=sys.stderr)
        raise SystemExit(1)
