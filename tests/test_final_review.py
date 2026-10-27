"""Real old/current source interoperability and required readiness gates."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile

import pytest
from test_projects import client_for, create, stage_body, BASE
from test_collaboration import op, package, check_item, readiness, post


@pytest.fixture
def old_source(tmp_path):
    archive = Path(__file__).parent/'fixtures/manufacturing-161292be.tar.gz'
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == 'ae37d3d9ef165408616aeb8ee08a99c812a2acd6764d6308031ba82a3ddd6fea'
    target = tmp_path/'old'
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            assert not Path(member.name).is_absolute() and '..' not in Path(member.name).parts
            assert member.isdir() or member.isfile()
            assert member.name == 'src' or member.name.startswith('src/manufacturing_platform')
        bundle.extractall(target, filter='data')
    return target/'src'


def run_old(source, db, script, *args):
    result = subprocess.run([sys.executable, '-c', '''
import json, sys
from uuid import uuid4
from manufacturing_platform.catalog import load_catalog
from manufacturing_platform.project_repository import ProjectRepository
from manufacturing_platform.project_models import ProjectCreate, ProjectTaskCreate as TaskCreate, ProjectTaskWrite as TaskPatch, ProjectStageWrite as StageUpdate
repo = ProjectRepository(sys.argv[1], load_catalog())
''' + script, str(db), *args], env={**os.environ, 'PYTHONPATH':str(source)}, cwd=source.parent, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_actual_old_reader_writer_then_current_forward_source(old_source, tmp_path):
    db = tmp_path/'db.sqlite3'
    legacy = run_old(old_source, db, '''
d = repo.create(ProjectCreate(operation_id=uuid4(), name='Legacy fixture', line_id='cameras', owner='Lead'), 'old', 'Old')
pid = d['project']['id']
body = TaskCreate(operation_id=uuid4(), stage_id='S1', title='Legacy task')
t = repo.create_task(pid, body, 'trusted-id', 'Old')
print(json.dumps({'id':pid,'task':t['id'],'body':body.model_dump(mode='json')}))
''')
    c = client_for(tmp_path)
    new, _ = create(c)
    ids = [new['project']['id'], legacy['id']]
    sources = {}
    replays = {}
    assert c.post(BASE+'/projects/'+legacy['id']+'/tasks',json=legacy['body']).json()['source'] is None
    for pid in ids:
        url = '/projects/'+pid
        assert c.patch(BASE+url,json={'expected_version':1,'owner':'Current owner'}).status_code == 200
        assert c.put(BASE+url+'/stages/S1',json=stage_body()).status_code == 200
        ordinary_body=op(stage_id='S2',title='Ordinary current task')
        ordinary=c.post(BASE+url+'/tasks',json=ordinary_body).json()
        assert ordinary['source'] is None
        assert c.post(BASE+url+'/tasks',json=ordinary_body).json()==ordinary
        p=package(c,pid)
        r=readiness(c,pid,p,[check_item(status='blocked',reason='Evidence missing')])
        issue_body=op(item_id='version',title='Linked issue')
        issue=c.post(BASE+url+'/readiness/'+r['id']+'/issues',json=issue_body).json()
        assert c.post(BASE+url+'/readiness/'+r['id']+'/issues',json=issue_body).json()==issue
        sources[pid]=(issue['id'],issue['source'])
        replays[pid]=ordinary_body
    if legacy['task']:
        assert c.patch(BASE+'/projects/'+legacy['id']+'/tasks/'+legacy['task'],json={'expected_version':1,'notes':'Current update'}).status_code==200
    before = {pid:c.get(BASE+'/projects/'+pid+'/controls').json() for pid in ids}
    # This executes the strict extra=forbid deployed source against the SAME DB.
    old = run_old(old_source, db, '''
from manufacturing_platform.project_models import ProjectTask
result=[]
replays=json.loads(sys.argv[-1])
for pid in sys.argv[2:-1]:
    replay=repo.create_task(pid, TaskCreate(**replays[pid]), 'trusted-id', 'Old')
    ProjectTask.model_validate(replay)
    d=repo.get(pid)
    task=d['tasks'][-1]
    repo.update_task(pid, task['id'], TaskPatch(expected_version=task['version'], status='done'), 'Old writer')
    stage=d['stages'][0]
    repo.update_stage(pid, stage['id'], StageUpdate(expected_version=stage['version'], status='done', owner='Old writer', due_date=None, blocker='', practice='Old update', participants=[], handoffs=[], systems=[]), 'Old writer')
    result.append(repo.get(pid))
print(json.dumps({'details':result,'list':repo.list(),'dashboard':repo.dashboard()}))
''', *ids, json.dumps(replays))
    assert len(old['list']) == 2 and len(old['dashboard']['projects']) == 2
    with sqlite3.connect(db) as connection:
        for (body,) in connection.execute('SELECT body FROM manufacturing_projects'):
            assert all('source' not in t for t in json.loads(body)['tasks'])
        assert connection.execute('SELECT count(*) FROM manufacturing_task_sources').fetchone()[0] == 2
    c=client_for(tmp_path)
    for pid in ids:
        current=c.get(BASE+'/projects/'+pid).json()
        tid,source=sources[pid]
        linked=next(t for t in current['tasks'] if t['id']==tid)
        assert linked['source']==source and linked['status']=='done'
        assert current['project']['status']=='blocked'
        assert c.get(BASE+'/projects/'+pid+'/controls').json()==before[pid]
        assert next(t for t in c.get(BASE+'/project-tasks').json()['items'] if t['id']==tid)['source']==source
        assert c.patch(BASE+'/projects/'+pid+'/tasks/'+tid,json={'expected_version':2,'status':'todo'}).json()['source']==source
        assert next(t for t in c.get(BASE+'/dashboard').json()['attention'] if t['id']==tid)['source']==source


@pytest.mark.parametrize('table', ['manufacturing_task_sources','manufacturing_control_events','manufacturing_control_operations'])
def test_issue_task_link_audit_receipt_are_atomic(tmp_path, table):
    c=client_for(tmp_path);d,_=create(c);pid=d['project']['id'];p=package(c,pid);r=readiness(c,pid,p)
    db=tmp_path/'db.sqlite3'
    tables=['manufacturing_projects','manufacturing_task_sources','manufacturing_control_events','manufacturing_control_operations']
    with sqlite3.connect(db) as connection:
        before={t:connection.execute('SELECT * FROM '+t).fetchall() for t in tables}
        connection.execute(f"CREATE TRIGGER fail_issue BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    body=op(item_id='version',title='Atomic issue')
    assert c.post(BASE+'/projects/'+pid+'/readiness/'+r['id']+'/issues',json=body).status_code==503
    with sqlite3.connect(db) as connection:
        assert {t:connection.execute('SELECT * FROM '+t).fetchall() for t in tables}==before
        connection.execute('DROP TRIGGER fail_issue')
    response=c.post(BASE+'/projects/'+pid+'/readiness/'+r['id']+'/issues',json=body)
    assert response.status_code==200,response.text
    assert c.post(BASE+'/projects/'+pid+'/readiness/'+r['id']+'/issues',json=body).json()==response.json()


def test_required_record_rejects_all_optional_without_audit_or_receipt(tmp_path):
    c=client_for(tmp_path);d,_=create(c);pid=d['project']['id'];p=package(c,pid)
    url=BASE+'/projects/'+pid
    before=c.get(url+'/controls').json()
    body=op(title='Optional checks',package_id=p['id'],work_order_ref='WO1',scope='batch',planned_use_date='2026-10-27',owner='Lead',required=True,items=[check_item(required=False)])
    response=c.post(url+'/readiness',json=body)
    assert response.status_code==422,response.text
    assert c.get(url+'/controls').json()==before
    with sqlite3.connect(tmp_path/'db.sqlite3') as db:
        assert db.execute('SELECT count(*) FROM manufacturing_control_operations WHERE operation_id=?',(body['operation_id'],)).fetchone()[0]==0
    body['items'][0]['required']=True
    assert c.post(url+'/readiness',json=body).status_code==200


def test_explicit_optional_readiness_does_not_block_completed_project(tmp_path):
    c=client_for(tmp_path);d,_=create(c);pid=d['project']['id'];p=package(c,pid)
    readiness(c,pid,p,[check_item(required=False)],required=False)
    for stage in d['stages']:
        assert c.put(BASE+'/projects/'+pid+'/stages/'+stage['id'],json=stage_body(status='done')).status_code==200
    assert c.get(BASE+'/projects/'+pid).json()['project']['status']=='completed'


def test_existing_inline_source_is_preserved_when_legacy_json_is_saved(tmp_path):
    c=client_for(tmp_path);d,_=create(c);pid=d['project']['id'];p=package(c,pid);r=readiness(c,pid,p)
    issue=post(c,'/projects/'+pid+'/readiness/'+r['id']+'/issues',{'item_id':'version','title':'Historical source'})
    before=c.get(BASE+'/projects/'+pid+'/controls').json()
    # Model a candidate DB from before source normalization; preserve its reference.
    with sqlite3.connect(tmp_path/'db.sqlite3') as db:
        body=json.loads(db.execute('SELECT body FROM manufacturing_projects WHERE id=?',(pid,)).fetchone()[0])
        body['tasks'][0]['source']=issue['source']
        db.execute('UPDATE manufacturing_projects SET body=? WHERE id=?',(json.dumps(body),pid))
        db.execute('DELETE FROM manufacturing_task_sources WHERE project_id=?',(pid,))
    assert c.get(BASE+'/project-tasks').json()['items'][0]['source']==issue['source']
    response=c.patch(BASE+'/projects/'+pid,json={'expected_version':1,'owner':'Updated'})
    assert response.status_code==200 and response.json()['tasks'][0]['source']==issue['source']
    with sqlite3.connect(tmp_path/'db.sqlite3') as db:
        body=json.loads(db.execute('SELECT body FROM manufacturing_projects WHERE id=?',(pid,)).fetchone()[0])
        assert 'source' not in body['tasks'][0]
        assert db.execute('SELECT readiness_id,item_id FROM manufacturing_task_sources WHERE project_id=?',(pid,)).fetchone()==(r['id'],'version')
    assert c.get(BASE+'/projects/'+pid+'/controls').json()==before
    assert client_for(tmp_path).get(BASE+'/projects/'+pid).json()['tasks'][0]['source']==issue['source']
