"""Real HTTP acceptance for durable, isolated manufacturing projects."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import sqlite3
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from manufacturing_platform.api import build_router

BASE = '/api/v1/manufacturing'


def client_for(tmp_path, *, mode='edit', actor='trusted-id'):
    def authorize(request, write=False):
        if mode == 'anonymous':
            raise HTTPException(401, 'Sign in')
        return {'user_id': actor, 'display_name': '可信用户', 'read_only': mode == 'read'}
    app = FastAPI()
    app.include_router(build_router(database_path=str(tmp_path/'db.sqlite3'), assets_dir=str(tmp_path/'webui'/'dist'), authorize=authorize, release='release-123'))
    return TestClient(app)


def create(client, **changes):
    body = {'operation_id':str(uuid4()), 'name':'相机试产', 'line_id':'cameras', 'owner':'负责人', **changes}
    response = client.post(BASE+'/projects', json=body)
    assert response.status_code == 200, response.text
    return response.json(), body


def stage_body(**changes):
    return {'expected_version':1, 'status':'doing', 'owner':'工程', 'due_date':None, 'blocker':'', 'practice':'实际记录', 'participants':[], 'handoffs':[], 'systems':[], **changes}


def task(client, project, **changes):
    response = client.post(BASE+'/projects/'+project+'/tasks', json={'operation_id':str(uuid4()),'stage_id':'S1','title':'确认资料',**changes})
    assert response.status_code == 200, response.text
    return response.json()


def test_create_retry_immutable_response_and_global_idempotency(tmp_path):
    client = client_for(tmp_path)
    detail, body = create(client, name='  相机试产  ')
    p = detail['project']; pid = p['id']
    assert p['name'] == '相机试产' and p['status'] == 'planned' and p['version'] == 1
    assert p['current_stage_id'] == 'S1' and p['total_stages'] == 9
    assert all(s['practice'] == '' and s['participants'] == [] for s in detail['stages'])
    assert len(detail['activity']) == 1 and detail['activity'][0]['actor'] == '可信用户'
    assert client.patch(BASE+'/projects/'+pid,json={'expected_version':1,'name':'更新'}).status_code == 200
    assert client.post(BASE+'/projects',json=body).json() == detail
    assert client.post(BASE+'/projects',json={**body,'name':'不同'}).status_code == 409
    assert client_for(tmp_path,actor='other').post(BASE+'/projects',json=body).status_code == 409
    assert client.post(BASE+'/projects/'+pid+'/tasks',json={'operation_id':body['operation_id'],'stage_id':'S1','title':'x'}).status_code == 409
    assert client_for(tmp_path).get(BASE+'/projects/'+pid).json()['project']['name'] == '更新'


def test_stage_progress_block_reopen_isolation_core_and_child_cas(tmp_path):
    client = client_for(tmp_path)
    a,_ = create(client); b,_ = create(client,line_id='oem')
    pid = a['project']['id']; bid = b['project']['id']; url = BASE+'/projects/'+pid
    saved = client.put(url+'/stages/S1',json=stage_body()).json()
    assert saved['version'] == 2 and saved['status'] == 'doing'
    assert client.get(url).json()['project']['status'] == 'active'
    assert client.put(url+'/stages/S1',json=stage_body()).status_code == 409
    assert client.put(url+'/stages/S2',json=stage_body(status='blocked',blocker=' ')).status_code == 422
    assert client.put(url+'/stages/S2',json=stage_body(status='blocked',blocker='缺资料')).status_code == 200
    current = client.get(url).json()
    assert current['project']['status'] == 'blocked' and current['project']['version'] == 1
    assert current['stages'][0] == saved
    assert client.patch(url,json={'expected_version':1,'owner':'新负责人'}).json()['project']['version'] == 2
    assert client.patch(url,json={'expected_version':1,'owner':'旧版本'}).status_code == 409
    for stage in client.get(url).json()['stages']:
        assert client.put(url+'/stages/'+stage['id'],json=stage_body(expected_version=stage['version'],status='done')).status_code == 200
    assert client.get(url).json()['project']['status'] == 'completed'
    assert client.put(url+'/stages/S1',json=stage_body(expected_version=3,status='todo')).status_code == 200
    assert client.get(url).json()['project']['status'] == 'active'
    assert client.get(BASE+'/projects/'+bid).json() == b


def test_tasks_scoping_retry_fields_flatten_dashboard_and_archive(tmp_path):
    client=client_for(tmp_path); today=date.today()
    a,_=create(client,due_date=today.isoformat()); b,_=create(client,line_id='oem',due_date=(today-timedelta(days=1)).isoformat())
    pid=a['project']['id']; bid=b['project']['id']; url=BASE+'/projects/'+pid
    body={'operation_id':str(uuid4()),'stage_id':'S1','title':'确认版本','kind':'confirmation','priority':'urgent','owner':'工程','due_date':today.isoformat(),'notes':'待核对'}
    created=client.post(url+'/tasks',json=body).json()
    assert created['kind']=='confirmation' and created['priority']=='urgent' and created['due_date']==today.isoformat()
    assert client.post(url+'/tasks',json=body).json()==created
    assert client.post(BASE+'/projects/'+bid+'/tasks',json=body).status_code==409
    assert client.patch(BASE+'/projects/'+bid+'/tasks/'+created['id'],json={'expected_version':1,'status':'done'}).status_code==404
    t=client.patch(url+'/tasks/'+created['id'],json={'expected_version':1,'status':'blocked','notes':'缺版本'}).json()
    assert t['version']==2 and t['status']=='blocked'
    assert client.post(url+'/tasks',json=body).json()==created
    assert client.patch(url+'/tasks/'+t['id'],json={'expected_version':1,'status':'done'}).status_code==409
    flat=client.get(BASE+'/project-tasks').json()['items']
    assert flat[0]['project_name']==a['project']['name'] and flat[0]['stage_name']==a['stages'][0]['name']
    d=client.get(BASE+'/dashboard').json()
    assert d['counts']=={'active_projects':2,'blocked_projects':1,'due_soon':1,'open_tasks':1,'pending_confirmations':1}
    assert d['attention'][0]['id']==t['id'] and d['blockers'][0]['task_id']==t['id']
    assert client.patch(url+'/tasks/'+t['id'],json={'expected_version':2,'status':'done'}).status_code==200
    assert client.patch(url+'/tasks/'+t['id'],json={'expected_version':3,'status':'todo'}).status_code==200
    assert client.patch(url,json={'expected_version':1,'archived':True}).json()['project']['status']=='archived'
    assert len(client.get(BASE+'/projects').json()['items'])==2
    assert client.get(BASE+'/project-tasks').json()['items']==[]
    d=client.get(BASE+'/dashboard').json()
    assert d['counts']['open_tasks']==0 and d['counts']['due_soon']==0
    assert all(p['id']!=pid for p in d['projects']) and all(x['project_id']!=pid for x in d['activity'])


@pytest.mark.parametrize('field,value', [('name',' '),('name','x'*201),('owner',4),('target_quantity',True),('target_quantity',0),('target_quantity',1000000001),('summary','x'*6001),('due_date','2026-99-01'),('extra','secret')])
def test_strict_create_validation(tmp_path,field,value):
    client=client_for(tmp_path)
    response=client.post(BASE+'/projects',json={'operation_id':str(uuid4()),'name':'x','owner':'y','line_id':'cameras',field:value})
    assert response.status_code==422 and response.json()=={'detail':'Invalid request'}
    assert not (tmp_path/'db.sqlite3').exists()


def test_unknown_scope_private_errors_and_auth_before_io(tmp_path):
    client=client_for(tmp_path)
    body={'operation_id':str(uuid4()),'name':'x','owner':'y','line_id':'missing'}
    assert client.post(BASE+'/projects',json=body).status_code==404
    assert not (tmp_path/'db.sqlite3').exists()
    for method,path in [('get','/projects'),('get','/dashboard'),('get','/project-tasks'),('get','/projects/unknown'),('post','/projects')]:
        response=getattr(client_for(tmp_path,mode='anonymous'),method)(BASE+path, **({'json':body} if method=='post' else {}))
        assert response.status_code==401 and response.headers['cache-control']=='private, no-store'
    assert not (tmp_path/'db.sqlite3').exists()
    assert client_for(tmp_path,mode='read').post(BASE+'/projects',json=body).status_code==403


def test_child_changes_preserve_concurrent_aggregate_and_legacy_rows(tmp_path):
    client=client_for(tmp_path)
    old=client.put(BASE+'/lines/cameras/stages/S1',json={'expected_version':0,'practice':'legacy','participants':[],'handoffs':[],'systems':[]}).json()
    client.post(BASE+'/lines/cameras/stages/S1/tasks',json={'title':'legacy task','operation_id':str(uuid4())})
    with sqlite3.connect(tmp_path/'db.sqlite3') as db:
        before={table:db.execute('SELECT * FROM '+table).fetchall() for table in ('stage_records','tasks','task_operations')}
    detail,_=create(client); pid=detail['project']['id']; url=BASE+'/projects/'+pid
    t=task(client,pid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda sid: client.put(url+'/stages/'+sid,json=stage_body()).status_code,['S1','S2']))
    assert results==[200,200]
    final=client_for(tmp_path).get(url).json()
    assert len(final['tasks'])==1 and final['tasks'][0]==t
    assert [s['version'] for s in final['stages'][:2]]==[2,2]
    assert client.get(BASE+'/lines/cameras/stages/S1').json()['record']==old
    with sqlite3.connect(tmp_path/'db.sqlite3') as db:
        assert before=={table:db.execute('SELECT * FROM '+table).fetchall() for table in before}


def test_completion_requires_tasks_and_blocker_precedes_all_done_stages(tmp_path):
    client=client_for(tmp_path); detail,_=create(client); pid=detail['project']['id']; url=BASE+'/projects/'+pid
    pending=task(client,pid,kind='confirmation')
    for stage in detail['stages']:
        assert client.put(url+'/stages/'+stage['id'],json=stage_body(status='done')).status_code==200
    assert client.get(url).json()['project']['status']=='active'
    assert client.patch(url+'/tasks/'+pending['id'],json={'expected_version':1,'status':'blocked'}).status_code==200
    assert client.get(url).json()['project']['status']=='blocked'
    assert client.patch(url+'/tasks/'+pending['id'],json={'expected_version':2,'status':'done'}).status_code==200
    assert client.get(url).json()['project']['status']=='completed'
    assert client.patch(url+'/tasks/'+pending['id'],json={'expected_version':3,'status':'todo'}).status_code==200
    assert client.get(url).json()['project']['status']=='active'


@pytest.mark.parametrize('method,suffix,body',[
    ('patch','',{'expected_version':True,'name':'x'}),
    ('patch','',{'expected_version':1,'owner':None}),
    ('patch','',{'expected_version':1,'archived':'true'}),
    ('patch','',{'expected_version':1,'line_id':'oem'}),
    ('put','/stages/S1',{'expected_version':1,'status':'done'}),
    ('put','/stages/S1',stage_body(owner='x'*201)),
    ('put','/stages/S1',stage_body(participants=[{'name':'x','extra':'x'}])),
    ('put','/stages/S1',stage_body(systems=[{'name':'x','method':'connected'}])),
    ('post','/tasks',{'operation_id':str(uuid4()),'stage_id':'S1','title':'x','kind':'approval'}),
    ('post','/tasks',{'operation_id':str(uuid4()),'stage_id':'S1','title':'x','owner':3}),
    ('post','/tasks',{'operation_id':str(uuid4()),'stage_id':'S1','title':'x','due_date':0}),
    ('post','/tasks',{'operation_id':str(uuid4()),'stage_id':'S1','title':'x','priority':'top'}),
    ('patch','/tasks/missing',{'expected_version':1,'status':None}),
])
def test_strict_child_patch_and_full_stage_input(tmp_path,method,suffix,body):
    client=client_for(tmp_path); detail,_=create(client)
    response=getattr(client,method)(BASE+'/projects/'+detail['project']['id']+suffix,json=body)
    assert response.status_code==422 and response.json()=={'detail':'Invalid request'}
    assert client.get(BASE+'/projects/'+detail['project']['id']).json()==detail


def test_noop_writes_no_duplicate_activity_and_tasks_can_move_stage(tmp_path):
    client=client_for(tmp_path); detail,_=create(client); pid=detail['project']['id']; url=BASE+'/projects/'+pid
    assert client.patch(url,json={'expected_version':1,'name':detail['project']['name']}).json()==detail
    t=task(client,pid)
    body={'expected_version':1,'stage_id':'S2','title':'移动','kind':'issue','owner':'质量','priority':'high','notes':'说明','due_date':'2026-11-01','status':'doing'}
    changed=client.patch(url+'/tasks/'+t['id'],json=body).json()
    assert changed['stage_id']=='S2' and changed['version']==2 and changed['kind']=='issue'
    saved=client.get(url).json()
    assert client.patch(url+'/tasks/'+t['id'],json={**body,'expected_version':2}).json()==changed
    assert client.get(url).json()==saved
    assert client.patch(url+'/tasks/'+t['id'],json={'expected_version':2,'stage_id':'bad'}).status_code==404
    assert client.post(url+'/tasks',json={'operation_id':str(uuid4()),'stage_id':'bad','title':'x'}).status_code==404
    assert client.put(url+'/stages/bad',json=stage_body()).status_code==404


def test_project_snapshots_survive_catalog_changes(tmp_path,monkeypatch):
    from manufacturing_platform import api
    from manufacturing_platform.catalog import Catalog,load_catalog
    client=client_for(tmp_path); detail,_=create(client); pid=detail['project']['id']
    raw=load_catalog().definition.model_dump()
    for line in raw['lines']: line['enabled']=False
    monkeypatch.setattr(api,'load_catalog',lambda:Catalog(raw))
    restarted=client_for(tmp_path)
    assert restarted.get(BASE+'/projects/'+pid).json()==detail
    assert restarted.put(BASE+'/projects/'+pid+'/stages/S1',json=stage_body()).status_code==200


def test_dashboard_caps_attention_order_and_due_window(tmp_path):
    client=client_for(tmp_path); today=date.today()
    for offset in [-1,0,6,7]:
        create(client,due_date=(today+timedelta(days=offset)).isoformat())
    detail,_=create(client); pid=detail['project']['id']
    for i in range(5): create(client)
    for i in range(22): task(client,pid,title=str(i))
    urgent=task(client,pid,title='urgent',priority='urgent',due_date=(today-timedelta(days=1)).isoformat())
    high=task(client,pid,title='high',priority='high')
    blocked=task(client,pid,title='blocked')
    client.patch(BASE+'/projects/'+pid+'/tasks/'+blocked['id'],json={'expected_version':1,'status':'blocked'})
    dashboard=client.get(BASE+'/dashboard').json()
    assert dashboard['counts']['due_soon']==2
    assert len(dashboard['projects'])==8 and len(client.get(BASE+'/projects').json()['items'])==10
    assert len(dashboard['attention'])==20
    assert [t['id'] for t in dashboard['attention'][:3]]==[blocked['id'],urgent['id'],high['id']]


def test_activity_newest50_retain200_and_safe_corrupted_storage(tmp_path):
    client=client_for(tmp_path); detail,_=create(client); pid=detail['project']['id']; url=BASE+'/projects/'+pid
    for version in range(1,205):
        assert client.patch(url,json={'expected_version':version,'name':str(version)}).status_code==200
    current=client.get(url).json()
    assert len(current['activity'])==50
    assert current['activity'][0]['created_at']>=current['activity'][-1]['created_at']
    with sqlite3.connect(tmp_path/'db.sqlite3') as db:
        import json
        aggregate=json.loads(db.execute('SELECT body FROM manufacturing_projects WHERE id=?',(pid,)).fetchone()[0])
        assert len(aggregate['activity'])==200
        db.execute('UPDATE manufacturing_projects SET body=? WHERE id=?',('{"private":"secret"}',pid))
    response=client.get(url)
    assert response.status_code==503 and response.json()=={'detail':'Manufacturing storage unavailable'}


def test_child_mutation_refreshes_parent_timestamp_keeps_core_version(tmp_path):
    client=client_for(tmp_path); detail,_=create(client); pid=detail['project']['id']; url=BASE+'/projects/'+pid
    before=detail['project']
    child=client.put(url+'/stages/S1',json=stage_body()).json()
    after=client.get(url).json()['project']
    assert after['updated_at']>before['updated_at'] and after['version']==before['version']
    saved=client.patch(url,json={'expected_version':before['version'],'owner':'新版'}).json()
    assert saved['stages'][0]==child and saved['project']['version']==2


def test_project_retry_stays_immutable_when_template_disabled_and_changed_scope_conflicts(tmp_path,monkeypatch):
    from manufacturing_platform import api
    from manufacturing_platform.catalog import Catalog,load_catalog
    client=client_for(tmp_path); detail,body=create(client)
    assert client.post(BASE+'/projects',json={**body,'line_id':'missing'}).status_code==409
    raw=load_catalog().definition.model_dump()
    for line in raw['lines']: line['enabled']=False
    monkeypatch.setattr(api,'load_catalog',lambda:Catalog(raw))
    restarted=client_for(tmp_path)
    assert restarted.post(BASE+'/projects',json=body).json()==detail
    assert restarted.post(BASE+'/projects',json={**body,'operation_id':str(uuid4())}).status_code==404
