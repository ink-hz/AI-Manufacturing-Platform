"""Concurrency, schema, audit and transactional invariants over real HTTP."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import sqlite3
import subprocess
from uuid import uuid4
import pytest
from fastapi import HTTPException
from test_projects import client_for, create, BASE
from test_collaboration import op, post, package, package_body, action, check_item, readiness, update_check


def test_draft_package_attention_and_query_projection(tmp_path):
    c=client_for(tmp_path); d,_=create(c); pid=d['project']['id']
    p=package(c,pid,verified=False,items=[{**package_body()['items'][0],'status':'pending'}])
    response=c.get(BASE+'/collaboration')
    assert response.status_code==200,response.text
    a=response.json()['attention'][0]
    assert a=={'project_id':pid,'project_name':d['project']['name'],'stage_id':'S2','object_type':'package','object_id':p['id'],'item_id':'bom','title':'MBOM','reason':'Engineering material requires review','owner':'Engineer','due_date':None}
    assert c.get(BASE+'/dashboard').json()['control_attention']==[a]


def test_new_task_response_source_is_consistent_with_restart(tmp_path):
    c=client_for(tmp_path); d,_=create(c); pid=d['project']['id']
    task=post(c,'/projects/'+pid+'/tasks',{'stage_id':'S1','title':'Legacy style task'})
    assert client_for(tmp_path).get(BASE+'/projects/'+pid).json()['tasks'][0]==task


def test_simultaneous_cas_and_operation_retries_create_one_fact(tmp_path):
    c=client_for(tmp_path); d,_=create(c); pid=d['project']['id']; p=package(c,pid,verified=False)
    url=BASE+'/projects/'+pid+'/packages/'+p['id']
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses=list(pool.map(lambda label:c.put(url,json=op(expected_version=1,**package_body(title=label))).status_code,['A','B']))
    assert sorted(statuses)==[200,409]
    current=c.get(BASE+'/projects/'+pid+'/controls').json()['packages'][0]
    request=op(expected_version=current['version'],action='submit')
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _:c.post(url+'/actions',json=request),range(2)))
    assert all(response.status_code==200 for response in responses)
    assert responses[0].json()==responses[1].json()
    controls=c.get(BASE+'/projects/'+pid+'/controls').json()
    assert len(controls['events'])==3
    assert controls['packages'][0]['version']==3


def test_operation_binding_actor_object_scope_and_all_project_operations(tmp_path):
    c=client_for(tmp_path); d,_=create(c); other,_=create(c); pid=d['project']['id']; bid=other['project']['id']
    request=op(**package_body())
    p=c.post(BASE+'/projects/'+pid+'/packages',json=request).json()
    assert c.post(BASE+'/projects/'+bid+'/packages',json=request).status_code==409
    assert client_for(tmp_path,actor='different').post(BASE+'/projects/'+pid+'/packages',json=request).status_code==409
    assert c.post(BASE+'/projects',json=op(operation_id=request['operation_id'],name='x',line_id='cameras',owner='y')).status_code==409
    assert c.post(BASE+'/projects/'+pid+'/tasks',json=op(operation_id=request['operation_id'],stage_id='S1',title='x')).status_code==409
    assert p['version']==1


@pytest.mark.parametrize('field,value',[
    ('owner',4),('status','verified'),('expected_version',1),('items',[]),('items',[{**package_body()['items'][0],'extra':'x'}]),
    ('items',[package_body()['items'][0],package_body()['items'][0]]),('approval_status','approved'),('scope','x'*2001),
])
def test_strict_package_inputs(tmp_path,field,value):
    c=client_for(tmp_path); d,_=create(c); pid=d['project']['id']
    response=c.post(BASE+'/projects/'+pid+'/packages',json=op(**{**package_body(),field:value}))
    assert response.status_code==422 and response.json()=={'detail':'Invalid request'}
    assert c.get(BASE+'/projects/'+pid+'/controls').json()=={'packages':[],'handoffs':[],'readiness':[],'events':[]}


@pytest.mark.parametrize('field,value',[('planned_use_date','20261027'),('planned_use_date',1),('planned_use_date','2026-02-30'),('required','true'),('items',[check_item(valid_until='2026-10-27T00:00:00Z')])])
def test_typed_readiness_dates_and_flags(tmp_path,field,value):
    c=client_for(tmp_path); d,_=create(c); pid=d['project']['id']; p=package(c,pid)
    body={'title':'x','package_id':p['id'],'work_order_ref':'WO','scope':'batch','planned_use_date':'2026-10-27','owner':'Lead','items':[check_item()],field:value}
    assert c.post(BASE+'/projects/'+pid+'/readiness',json=op(**body)).status_code==422
    assert c.get(BASE+'/projects/'+pid+'/controls').json()['readiness']==[]


def test_na_and_review_rules_and_cross_project_references(tmp_path):
    c=client_for(tmp_path); d,_=create(c); pid=d['project']['id']
    assert c.post(BASE+'/projects/'+pid+'/packages',json=op(**package_body(items=[{**package_body()['items'][0],'status':'na','reason':''}]))).status_code==422
    p=package(c,pid,verified=False,items=[{**package_body()['items'][0],'evidence':''}])
    p=action(c,pid,p,'submit')
    before=c.get(BASE+'/projects/'+pid+'/controls').json()
    assert c.post(BASE+'/projects/'+pid+'/packages/'+p['id']+'/actions',json=op(expected_version=p['version'],action='verify')).status_code==422
    assert c.get(BASE+'/projects/'+pid+'/controls').json()==before
    p=action(c,pid,p,'return',reason='Missing proof')
    assert p['status']=='returned'
    response=c.put(BASE+'/projects/'+pid+'/packages/'+p['id'],json=op(expected_version=p['version'],**package_body()))
    assert response.status_code==200
    p=action(c,pid,response.json(),'submit'); p=action(c,pid,p,'verify')
    assert c.post(BASE+'/projects/'+pid+'/readiness',json=op(title='x',package_id=p['id'],work_order_ref='W',scope='s',planned_use_date='2026-10-27',owner='x',items=[check_item(package_item_id='missing')])).status_code==404


def test_issue_failure_rolls_back_task_operation_and_audit(tmp_path,monkeypatch):
    from manufacturing_platform.readiness import ReadinessService
    c=client_for(tmp_path); d,_=create(c); pid=d['project']['id']; p=package(c,pid); r=readiness(c,pid,p)
    before=c.get(BASE+'/projects/'+pid+'/controls').json()
    original=ReadinessService._save
    def failing_save(db,detail):
        original(db,detail)
        raise HTTPException(422,'Injected failure after project mutation')
    monkeypatch.setattr(ReadinessService,'_save',staticmethod(failing_save))
    request=op(item_id='version',title='Need proof')
    url=BASE+'/projects/'+pid+'/readiness/'+r['id']+'/issues'
    assert c.post(url,json=request).status_code==422
    assert c.get(BASE+'/projects/'+pid+'/controls').json()==before
    assert c.get(BASE+'/project-tasks').json()['items']==[]
    monkeypatch.setattr(ReadinessService,'_save',staticmethod(original))
    assert c.post(url,json=request).status_code==200
    assert len(c.get(BASE+'/project-tasks').json()['items'])==1


def test_process_reread_paging_and_append_only_event_storage(tmp_path):
    c=client_for(tmp_path); d,_=create(c); pid=d['project']['id']; p=package(c,pid)
    expected=c.get(BASE+'/projects/'+pid+'/controls').json()
    script='''import json,sys
from manufacturing_platform.collaboration_store import CollaborationStore
from manufacturing_platform.catalog import load_catalog
s=CollaborationStore(sys.argv[1],load_catalog())
with s._connection() as db:
 print(json.dumps(s.rows(db,'packages',sys.argv[2])))
'''
    result=subprocess.run(['/Users/neo/Developer/work/AI-Agent-Platform/backend/.venv/bin/python','-c',script,str(tmp_path/'db.sqlite3'),pid],capture_output=True,text=True,check=True,env={**os.environ,'PYTHONPATH':'src'})
    assert json.loads(result.stdout)==expected['packages']
    first=c.get(BASE+'/projects/'+pid+'/controls?limit=2').json()['events']
    second=c.get(BASE+'/projects/'+pid+'/controls?limit=2&offset=2').json()['events']
    assert first+second==expected['events']
    assert expected['events'][-1]['snapshot']['status']=='draft'
    with sqlite3.connect(tmp_path/'db.sqlite3') as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('DELETE FROM manufacturing_control_events')
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('UPDATE manufacturing_control_operations SET payload=?',('tamper',))


def test_retired_authority_preserves_reference_and_line_scope_changes(tmp_path):
    c=client_for(tmp_path)
    s=post(c,'/systems',{'name':'Manual register','kind':'paper','line_ids':['cameras','oem']})
    a=post(c,'/authorities',{'line_id':'cameras','object_type':'mbom','system_id':s['id'],'entry_point':'Controlled register','owner':'Eng'})
    response=c.patch(BASE+'/systems/'+s['id'],json=op(expected_version=1,line_ids=['oem']))
    assert response.status_code==200
    overview=c.get(BASE+'/collaboration').json()
    assert overview['authorities'][0]['active'] is False
    assert overview['authorities'][0]['id']==a['id']
    assert c.patch(BASE+'/authorities/'+a['id'],json=op(expected_version=2,active=True)).status_code==422


def test_new_revision_requires_external_approval_reconfirmation(tmp_path):
    c=client_for(tmp_path); d,_=create(c,line_id='oem'); pid=d['project']['id']
    p=package(c,pid,customer_version='C',internal_version='A',approval_party='Customer',approval_status='confirmed',approval_evidence='APPROVAL-A')
    newer=action(c,pid,p,'revise')
    assert newer['approval_status']=='unknown' and newer['approval_evidence']==''
    assert newer['items'][0]['status']=='pending'
    old=next(row for row in c.get(BASE+'/projects/'+pid+'/controls').json()['packages'] if row['id']==p['id'])
    assert old['approval_status']=='confirmed' and old['approval_evidence']=='APPROVAL-A'


def test_linked_issue_enforces_existing_project_task_owner_bound(tmp_path):
    c=client_for(tmp_path); d,_=create(c); pid=d['project']['id']; p=package(c,pid); r=readiness(c,pid,p)
    response=c.post(BASE+'/projects/'+pid+'/readiness/'+r['id']+'/issues',json=op(item_id='version',title='Need proof',owner='x'*201))
    assert response.status_code==422
    assert c.get(BASE+'/projects/'+pid).status_code==200
    assert c.get(BASE+'/project-tasks').json()['items']==[]
