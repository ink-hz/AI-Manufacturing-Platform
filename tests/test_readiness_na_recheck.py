"""Independent NA applicability review can recover an invalidated all-NA basis."""
from copy import deepcopy
import pytest
from test_projects import client_for, create, stage_body, BASE
from test_collaboration import op, package, package_body, action, check_item, readiness
from test_readiness_lifecycle import controls, replacement_body


def fresh_na(**changes):
    return check_item(status='na', package_item_id=None, owner='New reviewer',
                      source_ref='APPLICABILITY-REV2', evidence='NEW-REVIEW-2',
                      reason='New scope independently reviewed: no applicable version material', **changes)


def all_na_revision(c, pid, p):
    newer = action(c, pid, p, 'revise')
    body = package_body(items=[{**package_body()['items'][0], 'status':'na',
                               'reason':'No applicable material in this scoped basis'}])
    saved = c.put(BASE+'/projects/'+pid+'/packages/'+newer['id'],
                  json=op(expected_version=newer['version'], **body))
    assert saved.status_code == 200, saved.text
    return action(c, pid, action(c, pid, saved.json(), 'submit'), 'verify')


def prepare(c):
    d,_ = create(c); pid = d['project']['id']
    p = package(c, pid, items=[{**package_body()['items'][0], 'status':'na',
                               'reason':'No material applicable to first scope'}])
    old = readiness(c, pid, p, [check_item(status='na',package_item_id=None,
                    owner='Old reviewer',source_ref='APPLICABILITY-REV1',
                    evidence='OLD-REVIEW-1',reason='Previous independent applicability review')])
    assert old['status'] == 'complete'
    for stage in d['stages']:
        assert c.put(BASE+'/projects/'+pid+'/stages/'+stage['id'],
                     json=stage_body(status='done')).status_code == 200
    assert c.get(BASE+'/projects/'+pid).json()['project']['status'] == 'completed'
    invalid = action(c,pid,p,'invalidate',reason='Revise scope and review applicability')
    old = controls(c,pid)['readiness'][0]
    assert old['status'] == 'pending'
    newer = all_na_revision(c,pid,invalid)
    return pid, old, newer


def test_all_na_replacement_restores_completion_and_retains_old_history(tmp_path):
    c=client_for(tmp_path); pid, old, newer=prepare(c)
    history=deepcopy(old)
    body={**replacement_body(newer,old),'items':[fresh_na()]}
    response=c.post(BASE+'/projects/'+pid+'/readiness',json=body)
    assert response.status_code == 200, response.text
    current=response.json()
    assert current['status']=='complete' and current['items']==body['items']
    assert c.post(BASE+'/projects/'+pid+'/readiness',json=body).json()==current
    data=controls(c,pid)
    historical=next(row for row in data['readiness'] if row['id']==old['id'])
    assert historical['items']==history['items'] and historical['status']=='pending'
    assert historical['superseded_by']==current['id'] and historical['package_id']==history['package_id']
    assert c.get(BASE+'/projects/'+pid).json()['project']['status']=='completed'
    assert c.get(BASE+'/projects').json()['items'][0]['status']=='completed'
    assert c.get(BASE+'/dashboard').json()['control_attention']==[]
    create_event=next(e for e in data['events'] if e['action']=='create' and e['object_id']==current['id'])
    assert create_event['snapshot']['items'][0]['evidence']=='NEW-REVIEW-2'
    assert create_event['actor'] and create_event['operation_id']==body['operation_id']
    assert any(e['snapshot'].get('items',[{}])[0].get('evidence')=='OLD-REVIEW-1'
               and e['snapshot']['items'][0]['reason']=='Previous independent applicability review'
               for e in data['events'])
    assert sum(e['action']=='supersede' for e in data['events'])==1
    assert client_for(tmp_path).get(BASE+'/projects/'+pid+'/controls?limit=1000').json()==data


@pytest.mark.parametrize('field',['owner','source_ref','evidence','reason'])
def test_replacement_na_requires_every_independent_proof_field(tmp_path,field):
    c=client_for(tmp_path); pid,old,newer=prepare(c)
    item=fresh_na();item[field]=''
    before=controls(c,pid)
    response=c.post(BASE+'/projects/'+pid+'/readiness',
                    json={**replacement_body(newer,old),'items':[item]})
    assert response.status_code==422,response.text
    assert controls(c,pid)==before


@pytest.mark.parametrize('status',['pending','verified','blocked'])
def test_all_na_basis_does_not_make_unbound_non_na_assertions_valid(tmp_path,status):
    c=client_for(tmp_path); pid,old,newer=prepare(c)
    item={**fresh_na(),'status':status}
    before=controls(c,pid)
    response=c.post(BASE+'/projects/'+pid+'/readiness',
                    json={**replacement_body(newer,old),'items':[item]})
    assert response.status_code==422,response.text
    assert controls(c,pid)==before


@pytest.mark.parametrize('status',['verified','blocked'])
def test_replacement_never_inherits_non_na_conclusions_even_with_valid_binding(tmp_path,status):
    c=client_for(tmp_path); d,_=create(c);pid=d['project']['id']
    p=package(c,pid);old=readiness(c,pid,p)
    from test_readiness_lifecycle import revised_package
    newer=revised_package(c,pid,p)
    before=controls(c,pid)
    item={**fresh_na(),'status':status,'package_item_id':'bom'}
    response=c.post(BASE+'/projects/'+pid+'/readiness',
                    json={**replacement_body(newer,old),'items':[item]})
    assert response.status_code==422,response.text
    assert controls(c,pid)==before
