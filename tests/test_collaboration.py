"""Real private HTTP workflows for engineering collaboration."""
from uuid import uuid4
from copy import deepcopy
import pytest
from test_projects import client_for, create, stage_body, BASE


def op(**values):
    return {'operation_id': str(uuid4()), **values}


def post(client, url, body):
    response = client.post(BASE+url, json=op(**body))
    assert response.status_code == 200, response.text
    return response.json()


def package_body(**values):
    return {'title':'Production basis', 'product_ref':'CAM-1', 'scope':'WO-1', 'provider':'Engineering', 'owner':'Lead',
            'customer_version':'', 'internal_version':'A', 'approval_party':'', 'approval_status':'unknown', 'approval_evidence':'',
            'items':[{'id':'bom','kind':'mbom','title':'MBOM','source_system_id':None,'source_name':'Manual register','source_ref':'BOM-1','revision':'A','evidence':'DOC-1','owner':'Engineer','status':'verified','reason':''}], **values}


def package(client, pid, verified=True, **values):
    p = post(client, '/projects/'+pid+'/packages', package_body(**values))
    if verified:
        p = action(client, pid, p, 'submit')
        p = action(client, pid, p, 'verify')
    return p


def action(client, pid, p, name, **values):
    return post(client, '/projects/'+pid+'/packages/'+p['id']+'/actions', {'expected_version':p['version'],'action':name, **values})


def check_item(kind='version', **values):
    return {'id':kind,'kind':kind,'label':kind,'required':True,'owner':'Lead','due_date':None,'status':'pending','evidence':'','source_ref':'','source_system_id':None,'reason':'','valid_until':None,'package_item_id':'bom' if kind=='version' else None,'supply_mode':'unknown','first_article_result':'unknown', **values}


def readiness(client,pid,p,items=None,**values):
    return post(client,'/projects/'+pid+'/readiness',{'title':'Start check','package_id':p['id'],'work_order_ref':'WO-1','scope':'batch 1','planned_use_date':'2026-10-27','required':True,'owner':'Lead','items':items or [check_item()],**values})


def update_check(client,pid,r,items,expected=200):
    response=client.put(BASE+'/projects/'+pid+'/readiness/'+r['id'],json=op(expected_version=r['version'],items=items))
    assert response.status_code==expected,response.text
    return response.json()


def test_system_authority_uniqueness_cas_and_retirement(tmp_path):
    c=client_for(tmp_path)
    assert c.get(BASE+'/collaboration').status_code==200
    body={'name':'ERP','kind':'erp','line_ids':['cameras'],'business_owner':'Ops','it_owner':'IT','usage':'manual_effective','method':'manual','notes':'Actual carrier','active':True}
    request=op(**body)
    s=c.post(BASE+'/systems',json=request).json()
    assert c.post(BASE+'/systems',json=request).json()==s
    assert c.post(BASE+'/systems',json={**request,'name':'Changed'}).status_code==409
    a=post(c,'/authorities',{'line_id':'cameras','object_type':'mbom','system_id':s['id'],'entry_point':'BOM editor','owner':'Ops','notes':'','active':True})
    assert c.post(BASE+'/authorities',json=op(**{k:v for k,v in a.items() if k in {'line_id','object_type','system_id','entry_point','owner','notes','active'}})).status_code==409
    assert c.patch(BASE+'/systems/'+s['id'],json=op(expected_version=9,active=False)).status_code==409
    assert c.patch(BASE+'/systems/'+s['id'],json=op(expected_version=1,active=False)).status_code==200
    overview=c.get(BASE+'/collaboration').json()
    assert overview['authorities'][0]['system_id']==s['id'] and overview['systems'][0]['active'] is False
    assert c.post(BASE+'/authorities',json=op(line_id='oem',object_type='ebom',system_id=s['id'],entry_point='x',owner='x')).status_code==422


def test_package_freeze_revision_invalidation_and_action_replay(tmp_path):
    c=client_for(tmp_path); d,_=create(c); pid=d['project']['id']
    p=package(c,pid)
    assert p['status']=='verified' and p['revision']==1
    url=BASE+'/projects/'+pid+'/packages/'+p['id']
    assert c.put(url,json=op(expected_version=p['version'],**package_body(title='Changed'))).status_code==422
    r=readiness(c,pid,p)
    r=update_check(c,pid,r,[check_item(status='verified',evidence='Checked',source_ref='BOM-1')])
    assert r['status']=='complete'
    newer=action(c,pid,p,'revise')
    assert newer['family_id']==p['family_id'] and newer['revision']==2 and newer['supersedes_id']==p['id'] and newer['status']=='draft'
    controls=c.get(BASE+'/projects/'+pid+'/controls').json()
    assert controls['readiness'][0]['package_id']==p['id']
    request=op(expected_version=p['version'],action='invalidate',reason='Approval withdrawn')
    invalid=c.post(url+'/actions',json=request)
    assert invalid.status_code==200,invalid.text
    assert c.post(url+'/actions',json=request).json()==invalid.json()
    r=c.get(BASE+'/projects/'+pid+'/controls').json()['readiness'][0]
    assert r['status']=='pending' and r['items'][0]['status']=='pending'
    assert 'Approval withdrawn' in r['items'][0]['reason']


def test_handoffs_fixed_revision_independent_receivers_and_scope(tmp_path):
    c=client_for(tmp_path); d,_=create(c); other,_=create(c); pid=d['project']['id']; bid=other['project']['id']
    p=package(c,pid)
    def hand(to): return post(c,'/projects/'+pid+'/handoffs',{'package_id':p['id'],'from_party':'Eng','to_party':to,'to_system_id':None,'owner':'Lead','due_date':'2026-10-28','method':'file','evidence':'sent file','occurred_at':'2026-10-27T05:00:00Z'})
    h=hand('Test'); second=hand('Assembly'); url=BASE+'/projects/'+pid+'/handoffs/'+h['id']
    sent=c.patch(url,json=op(expected_version=1,action='send',evidence='send-1',occurred_at='2026-10-27T05:00:00Z')).json()
    assert sent['status']=='sent' and sent['package_revision']==1
    bad=op(expected_version=2,action='receive',received_revision=999,evidence='receipt',occurred_at='2026-10-27T06:00:00Z')
    assert c.patch(url,json=bad).status_code==422
    received=c.patch(url,json={**bad,'operation_id':str(uuid4()),'received_revision':1})
    assert received.status_code==200,received.text
    assert received.json()['status']=='received'
    hs=c.get(BASE+'/projects/'+pid+'/controls').json()['handoffs']
    assert next(x for x in hs if x['id']==second['id'])['status']=='draft'
    assert c.patch(BASE+'/projects/'+bid+'/handoffs/'+h['id'],json=op(expected_version=3,action='cancel',reason='x')).status_code==404
    assert c.post(BASE+'/projects/'+bid+'/readiness',json=op(title='x',package_id=p['id'],work_order_ref='WO',scope='x',planned_use_date='2026-10-27',owner='x',items=[check_item()])).status_code==404


@pytest.mark.parametrize('kind,changes',[
    ('equipment',{'valid_until':'2026-10-26'}),('equipment',{'valid_until':None}),
    ('people',{'evidence':''}),('people',{'owner':''}),('people',{'source_ref':''}),
    ('first_article',{'first_article_result':'planned'}),('first_article',{'first_article_result':'failed'}),
    ('materials',{'supply_mode':'unknown'}),('customer_material',{'supply_mode':'self'}),
])
def test_readiness_rejects_missing_proof_expiry_first_article_and_ownership(tmp_path,kind,changes):
    c=client_for(tmp_path); d,_=create(c); pid=d['project']['id']; p=package(c,pid)
    r=readiness(c,pid,p,[check_item(kind)])
    i=check_item(kind,status='verified',evidence='proof',source_ref='DOC',valid_until='2026-10-27',first_article_result='passed',supply_mode='customer',**{})
    i.update(changes)
    update_check(c,pid,r,[i],422)
    assert c.get(BASE+'/projects/'+pid+'/controls').json()['readiness'][0]==r


def test_oem_unknown_approval_na_reason_scope_and_optional_checks(tmp_path):
    c=client_for(tmp_path); d,_=create(c,line_id='oem'); pid=d['project']['id']; p=package(c,pid,customer_version='C',approval_party='Customer')
    assert p['approval_status']=='unknown'
    r=readiness(c,pid,p,[check_item('customer'),check_item('people',required=False)])
    update_check(c,pid,r,[check_item('customer',status='verified',source_ref='C',evidence='Internal note'),check_item('people',required=False)],422)
    update_check(c,pid,r,[check_item('customer',status='na'),check_item('people',required=False)],422)
    done=update_check(c,pid,r,[check_item('customer',status='na',reason='No external approval applicable'),check_item('people',required=False)])
    assert done['status']=='complete'
    update_check(c,pid,done,[check_item('customer',required=False),check_item('people',required=False)],422)


def test_issues_audit_retention_readonly_persistence_and_project_projection(tmp_path):
    c=client_for(tmp_path); d,_=create(c); pid=d['project']['id']; p=package(c,pid); r=readiness(c,pid,p)
    url=BASE+'/projects/'+pid
    for s in d['stages']:
        assert c.put(url+'/stages/'+s['id'],json=stage_body(status='done')).status_code==200
    assert c.get(url).json()['project']['status']=='active'
    r=update_check(c,pid,r,[check_item(status='blocked',reason='Missing proof')])
    assert c.get(url).json()['project']['status']=='blocked'
    assert c.get(BASE+'/dashboard').json()['counts']['blocked_projects']==1
    assert c.get(BASE+'/dashboard').json()['control_attention']==c.get(BASE+'/collaboration').json()['attention']
    request=op(item_id='version',title='Obtain proof',owner='Lead',due_date='2026-11-01',priority='high',notes='Need source')
    issue_url=url+'/readiness/'+r['id']+'/issues'
    issue=c.post(issue_url,json=request)
    assert issue.status_code==200,issue.text
    issue=issue.json()
    assert issue['source']=={'type':'readiness','id':r['id'],'item_id':'version'}
    assert c.post(issue_url,json=request).json()==issue
    assert len(c.get(BASE+'/project-tasks').json()['items'])==1
    assert c.patch(url+'/tasks/'+issue['id'],json={'expected_version':1,'status':'done'}).status_code==200
    assert c.get(url).json()['project']['status']=='blocked'
    r=update_check(c,pid,r,[check_item(status='verified',evidence='proof',source_ref='BOM-1')])
    assert c.get(url).json()['project']['status']=='completed'
    assert c.get(BASE+'/project-tasks').json()['items'][0]['source']==issue['source']
    for n in range(205):
        r=update_check(c,pid,r,[check_item(status='verified',evidence='proof'+str(n),source_ref='BOM-1')])
    saved=c.get(url+'/controls?limit=1000').json()
    assert len(saved['events'])>200
    assert client_for(tmp_path).get(url+'/controls?limit=1000').json()==saved
    assert client_for(tmp_path,mode='read').put(url+'/readiness/'+r['id'],json=op(expected_version=r['version'],items=r['items'])).status_code==403
    assert c.patch(url,json={'expected_version':1,'archived':True}).status_code==200
    assert c.get(BASE+'/collaboration').json()['attention']==[]
    assert c.get(url+'/controls?limit=1000').json()==saved
