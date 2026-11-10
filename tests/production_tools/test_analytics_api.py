from datetime import timedelta
import sqlite3

import pytest

from manufacturing_platform.production_tools.contracts import ProductionToolsConfig
from .test_analytics import NOW, PARAMS, Reader, source

BASE='/api/v1/manufacturing/workflow/production-tools'


def install(workflow, reader=None):
    reader = reader or Reader()
    workflow.production_tools = ProductionToolsConfig(source(reader), 'native', 'v1', {}, str(workflow.paths.domain.parent/'analytics.db'))
    workflow.reopen()
    return workflow.client('admin'), reader


def test_server_aggregate_does_not_consume_snapshot_quota(workflow):
    client, r = install(workflow)
    r.rows = [r.rows[0] | {'sn':str(i%12)} for i in range(2500)]
    for _ in range(3):
        response=client.get(BASE+'/projects/1/analysis', params=PARAMS|{'view':'summary'})
        assert response.status_code==200, response.text
        item=response.json()['items'][0]
        assert item['records']=='2500' and item['failed_sn']=='12'
    assert r.used_aggregate_sql
    with sqlite3.connect(workflow.production_tools.snapshot_path) as conn:
        assert conn.execute('SELECT count(*) FROM snapshots').fetchone()[0]==0


@pytest.mark.parametrize('path,params', [('/overview',PARAMS),('/projects/1/analysis',PARAMS|{'view':'summary'}),('/projects/1/availability',{})])
def test_unauthorized_zero_io(workflow,path,params):
    _,r=install(workflow)
    response=workflow.client('outsider').get(BASE+path,params=params)
    assert response.status_code==403
    assert r.calls==[]


@pytest.mark.parametrize('params', [PARAMS|{'view':'private'},PARAMS|{'view':'summary','column':'secret'},PARAMS|{'view':'summary','start':'1794182400'},PARAMS|{'view':'summary','stage_id':'1e2'},list((PARAMS|{'view':'summary'}).items())+[('view','errors')]])
def test_strict_queries_reject_before_io(workflow,params):
    client,r=install(workflow)
    response=client.get(BASE+'/projects/1/analysis',params=params)
    assert response.status_code==422,response.text
    assert r.calls==[]


def test_zero_source_unavailable_and_availability_are_distinct(workflow):
    client,r=install(workflow)
    r.rows=[]
    result=client.get(BASE+'/projects/1/analysis',params=PARAMS|{'view':'summary'})
    assert result.status_code==200 and result.json()['items'][0]['records']=='0'
    assert client.get(BASE+'/projects/1/availability').json()['latest_at'] is None
    r.failure=True
    result=client.get(BASE+'/projects/1/analysis',params=PARAMS|{'view':'summary'})
    assert result.status_code==503 and 'private-password' not in result.text


def test_overview_bounded_directory_and_batched_source_reads(workflow):
    r=Reader(projects=[{'id':i,'name':str(i)} for i in range(101,0,-1)])
    client,r=install(workflow,r)
    result=client.get(BASE+'/overview',params=PARAMS)
    assert result.status_code==200,result.text
    data=result.json()
    assert len(data['items'])==100 and data['has_more'] and not data['complete']
    assert data['next_before_id']=='2' and data['limit']==100
    assert 'total' not in data
    assert len(r.calls)<=4
    assert data['items'][0]['state']=='ready'
    assert data['items'][0]['statistics']['records']=='0'
    assert client.get(BASE+'/overview',params=PARAMS|{'before_id':'2'}).json()['items'][0]['statistics']['records']=='1'


def test_full_filters_reach_legacy_http_and_frozen_investigation_impact(workflow):
    from .test_analytics import FULL
    client,r=install(workflow)
    fields=FULL|{'stage_id':'10'}
    # Exact native statistics SQL through the legacy HTTP route.
    response=client.get(BASE+'/projects/1/statistics',params=PARAMS|fields|{'kind':'production'})
    assert response.status_code==200,response.text
    assert response.json()['items'][0]['records']==1
    r.rows += [r.rows[0]|{'status':'1','errorcode':'OTHER'},r.rows[0]|{'errorcode':'OTHER'}]
    response=client.post(BASE+'/projects/1/investigations',json={'context':PARAMS|fields})
    assert response.status_code==200,response.text
    draft=response.json()
    impact=draft['impact']
    assert impact['state']=='available',impact
    assert impact['baseline']['counts']['records']=='3'
    assert impact['failure']['counts']['records']=='1'
    assert impact['failure']['counts']['distinct_sn']=='1'
    assert impact['failure']['filters']['error_code']=='E'
    assert 'status' not in impact['baseline']['filters'] and 'error_code' not in impact['baseline']['filters']
    handoff=client.post(BASE+'/projects/1/investigations/'+draft['id']+'/handoffs',json={'expected_version':1}).json()
    r.rows=[]
    changed=client.put(BASE+'/projects/1/investigations/'+draft['id'],json={'expected_version':1,'context':PARAMS|{'device':'OTHER'}})
    assert changed.status_code==200,changed.text
    frozen=client.get(BASE+'/handoffs/'+handoff['id']).json()
    assert frozen['impact']==impact


def test_overview_source_failure_is_unavailable_not_zero(workflow):
    client,r=install(workflow)
    r.failure=True
    response=client.get(BASE+'/overview',params=PARAMS)
    assert response.status_code==200,response.text
    data=response.json()
    assert not data['complete']
    assert data['items'][0]['state']=='unavailable'
    assert data['items'][0]['statistics'] is None
    assert data['items'][0]['trend']==[]
    assert 'private-password' not in response.text


def test_availability_is_historical_metadata_and_rejects_window(workflow):
    client,r=install(workflow)
    old=NOW-timedelta(days=365)
    r.rows[0]['timestamp']=old
    response=client.get(BASE+'/projects/1/availability')
    assert response.status_code==200,response.text
    assert response.json()['captured_at']=='2026-11-10T00:00:00Z'
    assert response.json()['latest_at']==old.isoformat().replace('+00:00','Z')
    assert len(r.calls)==2 # project authorization + one metadata SELECT
    r.calls=[]
    assert client.get(BASE+'/projects/1/availability',params=PARAMS).status_code==422
    assert not r.calls
