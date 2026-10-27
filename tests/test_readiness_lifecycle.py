"""Frozen readiness bindings and explicit current-versus-historical replacement."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import pytest
from test_projects import client_for, create, stage_body, BASE
from test_collaboration import op, package, package_body, action, check_item, readiness, update_check, post


def revised_package(c,pid,p):
    newer=action(c,pid,p,'revise')
    response=c.put(BASE+'/projects/'+pid+'/packages/'+newer['id'],json=op(expected_version=newer['version'],**package_body()))
    assert response.status_code==200,response.text
    newer=action(c,pid,response.json(),'submit')
    return action(c,pid,newer,'verify')


def replacement_body(p,r,**changes):
    return op(title='Recheck revised basis',package_id=p['id'],work_order_ref=r['work_order_ref'],scope=r['scope'],planned_use_date=r['planned_use_date'],required=r['required'],owner='Lead',items=[check_item()],supersedes_id=r['id'],supersedes_version=r['version'],**changes)


def controls(c,pid):
    return c.get(BASE+'/projects/'+pid+'/controls?limit=1000').json()


@pytest.mark.parametrize('status',['draft','review','returned','invalid'])
def test_readiness_binds_only_verified_frozen_package(tmp_path,status):
    c=client_for(tmp_path); d,_=create(c); pid=d['project']['id']; p=package(c,pid,verified=False)
    if status in {'review','returned','invalid'}:
        p=action(c,pid,p,'submit')
    if status=='returned': p=action(c,pid,p,'return',reason='Wrong basis')
    if status=='invalid':
        p=action(c,pid,p,'verify'); p=action(c,pid,p,'invalidate',reason='Withdrawn')
    before=controls(c,pid)
    response=c.post(BASE+'/projects/'+pid+'/readiness',json=op(title='No mutable basis',package_id=p['id'],work_order_ref='WO-1',scope='batch',planned_use_date='2026-10-27',owner='Lead',items=[check_item('people',status='verified',source_ref='P',evidence='E')]))
    assert response.status_code==422,response.text
    assert controls(c,pid)==before


def test_replacement_completion_preserves_history_and_issue_sources(tmp_path):
    c=client_for(tmp_path); d,_=create(c); pid=d['project']['id']; p=package(c,pid); old=readiness(c,pid,p)
    issue=post(c,'/projects/'+pid+'/readiness/'+old['id']+'/issues',{'item_id':'version','title':'Old proof issue'})
    old=update_check(c,pid,old,[check_item(status='verified',source_ref='BOM-1',evidence='OLD-VERIFICATION')])
    p=action(c,pid,p,'invalidate',reason='Old approval withdrawn')
    old=controls(c,pid)['readiness'][0]
    newer=revised_package(c,pid,p)
    before=deepcopy(old)
    body=replacement_body(newer,old)
    response=c.post(BASE+'/projects/'+pid+'/readiness',json=body)
    assert response.status_code==200,response.text
    current=response.json()
    assert current['supersedes_id']==old['id'] and current['superseded_by'] is None and current['status']=='pending'
    historical=next(row for row in controls(c,pid)['readiness'] if row['id']==old['id'])
    assert historical['superseded_by']==current['id'] and historical['version']==before['version']+1
    assert historical['items']==before['items'] and historical['package_id']==before['package_id']
    assert c.post(BASE+'/projects/'+pid+'/readiness',json=body).json()==current
    for stage in d['stages']:
        assert c.put(BASE+'/projects/'+pid+'/stages/'+stage['id'],json=stage_body(status='done')).status_code==200
    assert c.patch(BASE+'/projects/'+pid+'/tasks/'+issue['id'],json={'expected_version':1,'status':'done'}).status_code==200
    assert c.get(BASE+'/projects/'+pid).json()['project']['status']=='active'
    assert all(row['object_id']!=old['id'] for row in c.get(BASE+'/collaboration').json()['attention'])
    current=update_check(c,pid,current,[check_item(status='verified',source_ref='BOM-1',evidence='NEW-VERIFICATION')])
    assert current['status']=='complete'
    assert c.get(BASE+'/projects/'+pid).json()['project']['status']=='completed'
    assert c.get(BASE+'/projects').json()['items'][0]['status']=='completed'
    assert c.get(BASE+'/dashboard').json()['counts']['active_projects']==0
    assert c.get(BASE+'/dashboard').json()['control_attention']==[]
    for n in range(201):
        current=update_check(c,pid,current,[check_item(status='verified',source_ref='BOM-1',evidence='NEW-VERIFICATION-'+str(n))])
    data=controls(c,pid)
    assert len(data['events'])>200
    assert any(e['snapshot'].get('items',[{}])[0].get('evidence')=='OLD-VERIFICATION' for e in data['events'])
    superseded=next(e for e in data['events'] if e['action']=='supersede')
    assert superseded['object_id']==old['id'] and superseded['snapshot']['superseded_by']==current['id']
    assert client_for(tmp_path).get(BASE+'/projects/'+pid+'/controls?limit=1000').json()==data
    tasks=c.get(BASE+'/project-tasks').json()['items']
    assert tasks[0]['source']=={'type':'readiness','id':old['id'],'item_id':'version'}
    assert c.put(BASE+'/projects/'+pid+'/readiness/'+old['id'],json=op(expected_version=historical['version'],items=historical['items'])).status_code==409
    assert c.post(BASE+'/projects/'+pid+'/readiness/'+old['id']+'/issues',json=op(item_id='version',title='Cannot mutate history')).status_code==409


@pytest.mark.parametrize('change',[
    {'work_order_ref':'OTHER-WO'},{'scope':'other batch'},{'required':False},
    {'items':[check_item('people')]},{'items':[check_item(required=False)]},
    {'items':[{**check_item(),'kind':'people'}]},
    {'items':[check_item(status='verified',source_ref='BOM-1',evidence='Inherited completion')]},
])
def test_replacement_cannot_change_scope_downgrade_or_inherit_completion(tmp_path,change):
    c=client_for(tmp_path); d,_=create(c); pid=d['project']['id']; p=package(c,pid); old=readiness(c,pid,p); newer=revised_package(c,pid,p)
    body={**replacement_body(newer,old),**change}
    before=controls(c,pid)
    response=c.post(BASE+'/projects/'+pid+'/readiness',json=body)
    assert response.status_code==422,response.text
    assert controls(c,pid)==before


def test_replacement_requires_same_project_family_and_strictly_higher_revision(tmp_path):
    c=client_for(tmp_path); d,_=create(c); other,_=create(c); pid=d['project']['id']; bid=other['project']['id']
    p=package(c,pid); old=readiness(c,pid,p); newer=revised_package(c,pid,p); unrelated=package(c,pid); foreign=package(c,bid)
    for selected in [p,unrelated]:
        assert c.post(BASE+'/projects/'+pid+'/readiness',json=replacement_body(selected,old)).status_code==422
    assert c.post(BASE+'/projects/'+bid+'/readiness',json=replacement_body(foreign,old)).status_code==404
    later=readiness(c,pid,newer)
    assert c.post(BASE+'/projects/'+pid+'/readiness',json=replacement_body(p,later)).status_code==422
    assert len(controls(c,pid)['readiness'])==2


def test_supersession_cas_concurrency_new_required_checks_and_invalidation_history(tmp_path):
    c=client_for(tmp_path); d,_=create(c); pid=d['project']['id']; p=package(c,pid); old=readiness(c,pid,p); newer=revised_package(c,pid,p)
    old=update_check(c,pid,old,[check_item(status='blocked',reason='Review old basis')])
    stale={**replacement_body(newer,old),'supersedes_version':1}
    assert c.post(BASE+'/projects/'+pid+'/readiness',json=stale).status_code==409
    bodies=[{**replacement_body(newer,old),'items':[check_item(),check_item('equipment')]} for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda body:c.post(BASE+'/projects/'+pid+'/readiness',json=body),bodies))
    assert sorted(response.status_code for response in responses)==[200,409]
    current=next(response.json() for response in responses if response.status_code==200)
    historical=next(row for row in controls(c,pid)['readiness'] if row['id']==old['id'])
    assert len(current['items'])==2 and historical['status']=='blocked'
    fresh_attempt={**replacement_body(newer,historical)}
    assert c.post(BASE+'/projects/'+pid+'/readiness',json=fresh_attempt).status_code==409
    assert sum(event['action']=='supersede' for event in controls(c,pid)['events'])==1
    assert c.get(BASE+'/projects/'+pid).json()['project']['status']!='blocked'
    assert all(row['object_id']!=old['id'] for row in c.get(BASE+'/collaboration').json()['attention'])
    action(c,pid,p,'invalidate',reason='Historic basis withdrawn')
    assert next(row for row in controls(c,pid)['readiness'] if row['id']==old['id'])==historical
    assert not any(e['action']=='basis_invalidated' and e['object_id']==old['id'] for e in controls(c,pid)['events'])
    assert len(controls(c,pid)['readiness'])==2


@pytest.mark.parametrize('fields',[{'supersedes_id':'unknown'},{'supersedes_version':1},{'supersedes_id':'unknown','supersedes_version':True}])
def test_supersession_reference_and_cas_are_paired_strict_inputs(tmp_path,fields):
    c=client_for(tmp_path); d,_=create(c); pid=d['project']['id']; p=package(c,pid)
    body=op(title='x',package_id=p['id'],work_order_ref='WO',scope='batch',planned_use_date='2026-10-27',owner='Lead',items=[check_item()],**fields)
    assert c.post(BASE+'/projects/'+pid+'/readiness',json=body).status_code==422
