"""Applicable version checks must have a usable immutable package-item binding."""
import pytest
from test_projects import client_for, create, BASE
from test_collaboration import op, package, package_body, check_item, readiness, update_check


def setup_checks(tmp_path):
    c=client_for(tmp_path); d,_=create(c); pid=d['project']['id']
    items=package_body()['items']+[{**package_body()['items'][0],'id':'not-applicable','kind':'firmware','title':'No firmware','status':'na','reason':'Hardware only'}]
    p=package(c,pid,items=items)
    return c,pid,p


def create_body(p,item):
    return op(title='Start check',package_id=p['id'],work_order_ref='WO-1',scope='batch',planned_use_date='2026-10-27',owner='Lead',items=[item])


def controls(c,pid):
    return c.get(BASE+'/projects/'+pid+'/controls').json()


@pytest.mark.parametrize('reference',[None,'not-applicable'])
@pytest.mark.parametrize('status',['pending','blocked','verified'])
def test_create_rejects_unusable_applicable_version_binding(tmp_path,reference,status):
    c,pid,p=setup_checks(tmp_path)
    before=controls(c,pid)
    item=check_item(status=status,package_item_id=reference,reason='Waiting for review',source_ref='BOM-1',evidence='Checked')
    response=c.post(BASE+'/projects/'+pid+'/readiness',json=create_body(p,item))
    assert response.status_code==422,response.text
    assert controls(c,pid)==before


@pytest.mark.parametrize('reference',[None,'not-applicable'])
def test_documented_na_exemption_stays_readable_but_cannot_become_applicable(tmp_path,reference):
    c,pid,p=setup_checks(tmp_path)
    record=readiness(c,pid,p,[check_item(status='na',package_item_id=reference,reason='Version check does not apply')])
    assert record['status']=='complete'
    before=controls(c,pid)
    for status in ['pending','blocked','verified']:
        update_check(c,pid,record,[check_item(status=status,package_item_id=reference,reason='Review version',source_ref='BOM-1',evidence='Checked')],422)
        assert controls(c,pid)==before
    update_check(c,pid,record,[check_item(status='na',package_item_id=reference,reason='')],422)
    saved=update_check(c,pid,record,[check_item(status='na',package_item_id=reference,reason='Confirmed hardware-only scope')])
    assert saved['status']=='complete' and saved['items'][0]['package_item_id']==reference
    assert client_for(tmp_path).get(BASE+'/projects/'+pid+'/controls').json()['readiness']==[saved]


def test_valid_version_binding_can_progress_and_na_can_become_applicable(tmp_path):
    c,pid,p=setup_checks(tmp_path)
    record=readiness(c,pid,p,[check_item(package_item_id='bom')])
    assert record['status']=='pending'
    record=update_check(c,pid,record,[check_item(status='blocked',package_item_id='bom',reason='Need proof')])
    assert record['status']=='blocked'
    record=update_check(c,pid,record,[check_item(status='verified',package_item_id='bom',source_ref='BOM-1',evidence='Checked')])
    assert record['status']=='complete'
    record=update_check(c,pid,record,[check_item(status='na',package_item_id='bom',reason='No applicable run yet')])
    record=update_check(c,pid,record,[check_item(status='pending',package_item_id='bom')])
    assert record['status']=='pending'
    assert record['items'][0]['package_item_id']=='bom'


@pytest.mark.parametrize('status',['pending','na'])
def test_nonexistent_version_reference_remains404_with_no_saved_fact(tmp_path,status):
    c,pid,p=setup_checks(tmp_path); before=controls(c,pid)
    response=c.post(BASE+'/projects/'+pid+'/readiness',json=create_body(p,check_item(status=status,package_item_id='missing',reason='Explicit exemption')))
    assert response.status_code==404,response.text
    assert controls(c,pid)==before
