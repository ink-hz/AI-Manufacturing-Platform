"""Real read-only SQLite probes plus mocked Docker failure-ordering boundaries."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import io
import tarfile
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import release
from test_upgrade_runtime import fixture


def probe_fixture(tmp_path):
    source=tmp_path/'previous';schema=source/'src/manufacturing_platform/workflow/schema.py'
    schema.parent.mkdir(parents=True)
    # The actual pinned baseline declaration is parsed without importing its dependencies.
    schema.write_bytes(subprocess.check_output(['git','show','f324cca22574638b598ea174b0ccf585ccf60d3b:src/manufacturing_platform/workflow/schema.py'],cwd=Path(__file__).parents[2]))
    data=tmp_path/'data';data.mkdir()
    config={'database_path':str(data/'workflow.sqlite3'),'authority_database_path':str(data/'authority.sqlite3'),
            'dataset_id':'d','dataset_mode':'demo','dataset_label':'Demo'}
    db=sqlite3.connect(config['database_path'])
    db.executescript("CREATE TABLE schema_version(version); INSERT INTO schema_version VALUES(17); CREATE TABLE dataset_metadata(id,mode,label); INSERT INTO dataset_metadata VALUES('d','demo','Demo');")
    db.commit()
    return db,{'workflow':config,'source_root':str(source),'data_root':str(data)}


def run_probe(payload):
    result=subprocess.run([sys.executable,'-B','-c',release.WORKFLOW_COMPATIBILITY_CODE],input=json.dumps(payload),text=True,capture_output=True,timeout=15)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def bytes_map(root):
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}


@pytest.mark.parametrize('version,compatible',[(17,True),(21,False),(18,False),(16,False)])
def test_probe_observes_committed_wal_and_never_changes_database(tmp_path,version,compatible):
    db,payload=probe_fixture(tmp_path)
    db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA wal_autocheckpoint=0')
    db.execute('UPDATE schema_version SET version=?',(version,));db.commit()
    data=Path(payload['data_root']);before=bytes_map(data)
    result=run_probe(payload)
    assert result['compatible'] is compatible
    assert result['expected_schema_version']==17 and result['observed_schema_version']==version
    # SQLite may update WAL-index read marks; DB and WAL bytes must remain identical.
    after=bytes_map(data)
    assert set(after)==set(before)
    assert {k:v for k,v in before.items() if not k.endswith('-shm')}=={k:v for k,v in after.items() if not k.endswith('-shm')}
    assert db.execute('SELECT version FROM schema_version').fetchall()==[(version,)]
    db.close()


@pytest.mark.parametrize('fault',['dataset','extra_dataset','extra_version','text_version','absent','symlink','hardlink','wrong_path','schema_expression','schema_missing','corrupt','missing_table','sidecar_symlink'])
def test_probe_refuses_uncertain_or_foreign_state(tmp_path,fault):
    db,payload=probe_fixture(tmp_path);path=Path(payload['workflow']['database_path'])
    if fault=='dataset':db.execute("UPDATE dataset_metadata SET label='Other'")
    if fault=='extra_dataset':db.execute("INSERT INTO dataset_metadata VALUES('d','demo','Demo')")
    if fault=='extra_version':db.execute('INSERT INTO schema_version VALUES(17)')
    if fault=='text_version':db.execute("UPDATE schema_version SET version='17'")
    if fault=='missing_table':db.execute('DROP TABLE dataset_metadata')
    db.commit();db.close()
    if fault=='absent':path.unlink()
    if fault=='symlink':path.rename(path.with_suffix('.real'));path.symlink_to(path.with_suffix('.real'))
    if fault=='hardlink':os.link(path,payload['workflow']['authority_database_path'])
    if fault=='wrong_path':payload['workflow']['database_path']=str(tmp_path/'foreign.sqlite3')
    if fault.startswith('schema_'):
        (Path(payload['source_root'])/'src/manufacturing_platform/workflow/schema.py').write_text('SCHEMA_VERSION = 16+1' if fault=='schema_expression' else 'OTHER=17')
    if fault=='corrupt':path.write_bytes(b'not sqlite')
    if fault=='sidecar_symlink':Path(str(path)+'-wal').symlink_to(path)
    assert run_probe(payload)['compatible'] is False
    if fault=='absent':assert not path.exists()


def rollback_harness(tmp_path,monkeypatch,*,compatible=True,fault=None,configured=True):
    e,old,target=fixture();e['previous_manifest']='previous-manifest'
    config={'database_path':'/app/data/manufacturing/workflow.sqlite3','authority_database_path':'/app/data/manufacturing/authority.sqlite3','dataset_id':'d','dataset_mode':'demo','dataset_label':'Demo'}
    if configured:
        e.update(baseline_workflow=config,target_workflow=config)
        for row in [old,target]:row['Config']['Env'] += [k+'='+v for k,v in release.workflow_environment(config).items()]
    old['State']={'Running':True,'Health':{'Status':'healthy'}}
    target['State']={'Running':True,'Health':{'Status':'healthy'}}
    restored=copy.deepcopy(old);restored['Id']='3'*64;restored['Config']['Hostname']='3'*12
    state={'row':old};events=[];writes={};locks=SimpleNamespace(retained=False)
    class Locks:
        def __enter__(self):return locks
        def __exit__(self,*args):pass
    monkeypatch.setattr(release.ops,'Locks',lambda **kw:Locks())
    monkeypatch.setattr(release.ops,'STAGE',tmp_path)
    (tmp_path/'sqlite_backup.py').write_text('BACKUP')
    pre={'old':old,'files':['base.yml'],'baseline_content':{'old':True},'expected_source':{},'expected_static':{},'containers':{}}
    checked={'passed':True,'preflight_sha256':'pin','request_sha256':'pin','image':e['target_image_id']}
    monkeypatch.setattr(release.ops,'read',lambda name:pre if name=='preflight.json' else checked)
    monkeypatch.setattr(release.ops,'digest',lambda p:'pin')
    monkeypatch.setattr(release.ops,'environment',lambda row:{})
    monkeypatch.setattr(release.ops,'compose',lambda files,overlay=False:['compose','target' if overlay else 'old'])
    monkeypatch.setattr(release.ops,'discover_files',lambda row:['base.yml']+([str(tmp_path/'overlay.json')] if row['Id']==target['Id'] else []))
    monkeypatch.setattr(release.ops,'maps',lambda name:pre['baseline_content'] if state['row']['Image']==old['Image'] else {'source':{},'static':{}})
    monkeypatch.setattr(release,'unchanged',lambda *a:events.append('unchanged'))
    monkeypatch.setattr(release,'validate_configuration',lambda *a:None)
    monkeypatch.setattr(release,'check_images',lambda *a:None)
    monkeypatch.setattr(release,'check_rollback_image',lambda *a:None)
    monkeypatch.setattr(release,'others_unchanged',lambda *a:None)
    monkeypatch.setattr(release,'http_checks',lambda *a:(_ for _ in ()).throw(ValueError('cutover_failure')))
    monkeypatch.setattr(release,'ready',lambda image:copy.deepcopy(state['row']))
    monkeypatch.setattr(release.ops,'identities',lambda:{release.ops.API:{'id':state['row']['Id'],'image':state['row']['Image']}})
    def inspect(name):
        if fault=='unknown_runtime' and state['row']['Id']==target['Id'] and events.count('target_readiness'):
            row=copy.deepcopy(target);row['Config']['Env'].append('DRIFT=1');return row
        return copy.deepcopy(state['row'])
    monkeypatch.setattr(release.ops,'inspect',inspect)
    def write(name,value):
        events.append(name)
        if fault==name:raise OSError('receipt_write_failed')
        writes[name]=copy.deepcopy(value)
    monkeypatch.setattr(release.ops,'write',write)
    readiness={'schema_ready':True,'workflow':{'schema_ready':True,**config,'schema_version':17}}
    def run(args,**kw):
        if args[:1]==['compose']:
            if 'config' in args:return b'{}'
            events.append(args[1]+'_compose')
            if fault==args[1]+'_compose':raise ValueError(args[1]+'_compose_failed')
            state['row']=copy.deepcopy(target if args[1]=='target' else restored)
            return b''
        if args[:2]==['docker','exec']:
            if args[-1]=='BACKUP':return b'{"verified":true,"legacy_schema_present":true}'
            kind='target_readiness' if state['row']['Image']==target['Image'] else 'old_readiness'
            events.append(kind)
            if fault==kind:raise ValueError(kind)
            result=copy.deepcopy(readiness)
            if fault=='wrong_readiness' and kind=='old_readiness':result['workflow']['dataset_label']='Wrong'
            return json.dumps(result).encode()
        if args[:2]==['docker','stop']:
            assert args[-1] in {old['Id'],target['Id']};assert locks.retained
            events.append('stop');state['row']['State']['Running']=False
            if fault=='stop':raise ValueError('stop_uncertain')
            return b''
        if args[:2]==['docker','start']:
            assert args[-1]==target['Id'];events.append('restart')
            if fault=='restart':raise ValueError('restart_failed')
            state['row']['State']['Running']=True;return b''
        if args[:2]==['docker','run']:
            events.append('probe');assert not state['row']['State']['Running']
            assert args[args.index('--user')+1]=='10001:10001'
            assert args[args.index('--network')+1]=='none'
            assert '--read-only' in args and '--cap-drop' in args and 'no-new-privileges' in args
            mounts=[args[i+1] for i,v in enumerate(args) if v=='--mount']
            assert len(mounts)==2 and all(m.endswith(',readonly') for m in mounts)
            assert args[args.index('--entrypoint')+2]==e['target_image_id']
            assert not any(v.startswith('KEEP=') for v in args)
            assert json.loads(kw['data'])['workflow']==config
            if fault=='probe':raise ValueError('probe_failed')
            if fault=='signal_probe':raise SystemExit('signal')
            if fault=='incomplete_probe':return b'{"compatible":true}'
            return json.dumps({'compatible':compatible,'expected_schema_version':17,'observed_schema_version':17 if compatible else 21,
                               'dataset_verified':True,'database_path':config['database_path']}).encode()
        raise AssertionError(args)
    monkeypatch.setattr(release.ops,'run',run)
    return e,events,writes,locks,state


def test_compatible_rollback_stops_before_probe_and_publishes_only_after_old_readiness(tmp_path,monkeypatch):
    e,events,writes,locks,state=rollback_harness(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='cutover_failure'):release.cutover(e)
    assert events.index('stop')<events.index('probe')<events.index('old_compose')<events.index('old_readiness')<events.index('rollback.json')
    assert writes['rollback.json']['restored'] is True and writes['rollback.json']['readiness']['workflow']['schema_ready']
    assert not locks.retained


@pytest.mark.parametrize('fault',[None,'probe','signal_probe','incomplete_probe','restart','unknown_runtime','stop','cutover-failure.private.json','workflow-rollback-state.private.json'])
def test_incompatible_or_unknown_rollback_never_recreates_old_and_retains_locks(tmp_path,monkeypatch,fault):
    e,events,writes,locks,state=rollback_harness(tmp_path,monkeypatch,compatible=False,fault=fault)
    with pytest.raises(BaseException):release.cutover(e)
    assert 'old_compose' not in events and 'rollback.json' not in writes and locks.retained
    if fault in {None,'probe','signal_probe','incomplete_probe','restart','stop'}:assert 'restart' in events
    if fault is None:
        receipt=writes['workflow-rollback-state.private.json']
        assert receipt['forward_repair_required'] and receipt['old_runtime_restored'] is False
        assert receipt['target_restart']['healthy'] is True


@pytest.mark.parametrize('fault',['old_readiness','wrong_readiness','rollback.json'])
def test_old_readiness_or_receipt_failure_keeps_locks(tmp_path,monkeypatch,fault):
    e,events,writes,locks,state=rollback_harness(tmp_path,monkeypatch,fault=fault)
    with pytest.raises(ValueError,match='cutover_failure'):release.cutover(e)
    assert 'rollback.json' not in writes and locks.retained
    assert 'old_readiness' in events


def test_unconfigured_release_keeps_legacy_rollback(tmp_path,monkeypatch):
    e,events,writes,locks,state=rollback_harness(tmp_path,monkeypatch,configured=False)
    with pytest.raises(ValueError,match='cutover_failure'):release.cutover(e)
    assert writes['rollback.json']['restored'] is True and not locks.retained
    assert 'probe' not in events and 'stop' not in events


def test_actual_old_workflow_accepts_17_then_rejects_target_migrated_21_without_reset(tmp_path):
    db,payload=probe_fixture(tmp_path);db.close()
    Path(payload['workflow']['database_path']).unlink()
    source=Path(payload['source_root']);repo=Path(__file__).parents[2]
    archive=subprocess.check_output(['git','archive','f324cca22574638b598ea174b0ccf585ccf60d3b','src'],cwd=repo)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tree:tree.extractall(source,filter='data')
    code="""import json,sys
sys.path.insert(0,sys.argv[1]+'/src')
from manufacturing_platform.workflow.store import WorkflowStore
config=json.loads(sys.argv[2])
store=WorkflowStore(config['database_path'],config['authority_database_path'],{'id':config['dataset_id'],'mode':config['dataset_mode'],'label':config['dataset_label']})
with store.transaction() as connection:
    print(connection.execute('SELECT version FROM schema_version').fetchone()[0])
"""
    def store(root):
        return subprocess.run([sys.executable,'-B','-c',code,str(root),json.dumps(payload['workflow'])],capture_output=True,text=True)
    old=store(source);assert old.returncode==0,old.stderr
    assert old.stdout.strip()=='17' and run_probe(payload)['compatible'] is True
    target=store(repo);assert target.returncode==0,target.stderr
    assert target.stdout.strip()=='21' and run_probe(payload)['compatible'] is False
    before=bytes_map(Path(payload['data_root']))
    old=store(source)
    assert old.returncode!=0 and 'workflow dataset mismatch' in old.stderr
    assert bytes_map(Path(payload['data_root']))['workflow.sqlite3']==before['workflow.sqlite3']
    with sqlite3.connect(payload['workflow']['database_path']) as connection:
        assert connection.execute('SELECT version FROM schema_version').fetchall()==[(21,)]


def test_future_maintenance_records_forward_only_schema_policy(tmp_path,monkeypatch):
    e,events,writes,locks,state=rollback_harness(tmp_path,monkeypatch)
    previous=tmp_path/'previous';schema=previous/'src/manufacturing_platform/workflow/schema.py'
    schema.parent.mkdir(parents=True);schema.write_text('SCHEMA_VERSION = 17')
    monkeypatch.setattr(release,'previous_source',lambda e:str(previous))
    # Existing runtime fixture checks depend on the canonical mount path.
    monkeypatch.setattr(release,'validate_baseline',lambda *a:None)
    monkeypatch.setattr(release,'http_checks',lambda *a:{})
    release.cutover(e)
    policy=writes['future-maintenance.json']['workflow_rollback']
    assert policy['policy']=='forward_only_after_schema_advance'
    assert policy['baseline_schema_version']==17 and policy['target_schema_version']==17
    assert policy['readiness']['schema_ready'] is True
    assert 'forward repair' in policy['recovery']


def test_other_running_writer_mount_blocks_probe_and_stop(tmp_path,monkeypatch):
    e,events,writes,locks,state=rollback_harness(tmp_path,monkeypatch)
    inspect=release.ops.inspect
    monkeypatch.setattr(release.ops,'identities',lambda:{'other':{'id':'other','image':'other'}})
    monkeypatch.setattr(release.ops,'inspect',lambda name:{'State':{'Running':True},'Mounts':[{'Source':'/data','RW':True}]} if name=='other' else inspect(name))
    with pytest.raises(ValueError,match='cutover_failure'):release.cutover(e)
    assert locks.retained and not {'stop','probe','old_compose'}.intersection(events)
    assert writes['workflow-rollback-state.private.json']['failure']['reason']=='other_workflow_writer_mount'


@pytest.mark.parametrize('missing_baseline',[False,True])
def test_initial_or_unconfigured_baseline_workflow_refuses_probe(monkeypatch,missing_baseline):
    e,_,_=fixture()
    if not missing_baseline:e['mode']='initial'
    monkeypatch.setattr(release.ops,'run',lambda *a,**kw:pytest.fail('must not launch compatibility helper'))
    with pytest.raises(ValueError,match='workflow_baseline_unconfigured'):release.workflow_compatibility(e)


def test_real_exclusive_sqlite_lock_refuses_readonly_probe(tmp_path):
    db,payload=probe_fixture(tmp_path)
    db.execute('BEGIN EXCLUSIVE')
    try:
        result=run_probe(payload)
        assert not result['compatible'] and 'locked' in result['reason']
    finally:db.rollback();db.close()


def test_failure_after_stop_receipt_write_recovers_same_target_without_old_compose(tmp_path,monkeypatch):
    e,events,writes,locks,state=rollback_harness(tmp_path,monkeypatch)
    write=release.ops.write
    def fail_once(name,value):
        if name=='workflow-rollback-state.private.json' and value['phase']=='probing':raise OSError('full disk after stop')
        return write(name,value)
    monkeypatch.setattr(release.ops,'write',fail_once)
    with pytest.raises(ValueError,match='cutover_failure'):release.cutover(e)
    assert locks.retained and 'restart' in events and 'old_compose' not in events


def test_old_recreate_failure_never_restarts_stale_target_or_publishes_success(tmp_path,monkeypatch):
    e,events,writes,locks,state=rollback_harness(tmp_path,monkeypatch,fault='old_compose')
    with pytest.raises(ValueError,match='cutover_failure'):release.cutover(e)
    assert locks.retained and 'restart' not in events and 'rollback.json' not in writes


def test_target_recreate_failure_with_known_baseline_still_checks_quiesced_schema_and_readiness(tmp_path,monkeypatch):
    e,events,writes,locks,state=rollback_harness(tmp_path,monkeypatch,fault='target_compose')
    with pytest.raises(ValueError,match='target_compose_failed'):release.cutover(e)
    assert events.index('stop')<events.index('probe')<events.index('old_readiness')
    assert writes['rollback.json']['restored'] and not locks.retained
