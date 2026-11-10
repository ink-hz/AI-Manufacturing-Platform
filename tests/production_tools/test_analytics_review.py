"""Review regressions: independent coverage and exact nullable-group drills."""
from dataclasses import replace
from datetime import timedelta
import pytest

from manufacturing_platform.production_tools.contracts import ProductionQuery
from manufacturing_platform.production_tools.queries import compile_query, validate_statement
from manufacturing_platform.workflow.contracts import DomainError
from .test_analytics import NOW, PARAMS, SCOPE, Reader, filters, source
from .test_analytics_api import BASE, install
from .test_investigations import investigation


@pytest.mark.parametrize('failed_block',['overview_trend','latest'])
def test_overview_retains_successful_blocks_and_attempts_all_three_reads(workflow,failed_block):
    r=Reader()
    select=r.select
    def fail_one(st):
        if st.name.startswith('analytics:'+failed_block+':'):
            r.calls.append(st)
            raise RuntimeError('private credential')
        return select(st)
    r.select=fail_one
    client,_=install(workflow,r)
    response=client.get(BASE+'/overview',params=PARAMS)
    assert response.status_code==200,response.text
    data=response.json();item=data['items'][0]
    assert item['statistics']['records']=='1'
    assert not data['complete'] and item['state']=='partial'
    assert len([x for x in r.calls if x.name.startswith('analytics:')])==3
    block='trend' if failed_block=='overview_trend' else 'latest'
    assert item['blocks'][block]['state']=='unavailable'
    assert not item['blocks'][block]['complete']
    assert item['blocks']['statistics']['state']=='ready'
    assert item['blocks']['statistics']['captured_at']=='2026-11-10T00:00:00Z'
    if block=='latest':
        assert len(item['trend'])==1
    else:
        assert item['latest_at']=='2026-11-09T22:00:00Z'
    assert 'private credential' not in response.text
    # Every failure path releases the shared source slot.
    r.select=select
    assert client.get(BASE+'/overview',params=PARAMS).json()['complete']


def test_overview_explicit_empty_and_partial_trend_coverage(workflow):
    r=Reader();r.rows=[]
    client,_=install(workflow,r)
    item=client.get(BASE+'/overview',params=PARAMS).json()['items'][0]
    assert item['statistics']['records']=='0' and item['trend']==[] and item['latest_at'] is None
    assert all(x['state']=='ready' and x['complete'] for x in item['blocks'].values())
    # Dense batched trend has >1000 SQL groups without exceeding96/project.
    r=Reader(projects=[{'id':i,'name':str(i)} for i in range(12,0,-1)])
    row=r.rows[0]
    r.rows=[row|{'projuectid':str(p),'timestamp':NOW-timedelta(minutes=15*n+1)} for p in range(1,13) for n in range(96)]
    client,_=install(workflow,r)
    data=client.get(BASE+'/overview',params=PARAMS).json()
    assert not data['complete']
    for item in data['items']:
        assert item['statistics']['records']=='96'
        assert item['blocks']['statistics']['complete']
        assert item['blocks']['trend']['state']=='partial'
        assert item['blocks']['trend']['truncation_reason']=='group_limit'
        assert item['blocks']['latest']['complete']


MISSING={'stage_id':'workstagesid','software_id':'softwareid','config_log_id':'configlogsid','software_version':'version','config_version':'cversion','device':'devicename','error_code':'errorcode'}
@pytest.mark.parametrize('field,native',MISSING.items())
def test_missing_scope_exactly_matches_nullable_group(field,native):
    r=Reader();row=r.rows[0]
    values=[None,'']+(['0','-1'] if field.endswith('_id') else [])
    r.rows=[row|{native:value} for value in values]+[row]
    f=filters(missing_fields=[field])
    result=source(r).analysis(SCOPE,f,'summary')
    assert result['items'][0]['records']==str(len(values))
    assert result['items'][0]['first_time']=='2026-11-09T22:00:00Z'
    assert result['filters']['missing_fields']==[field]
    for kind in ('production','stopover','production_statistics','stopover_statistics'):
        st=compile_query(SCOPE,ProductionQuery(kind=kind,**PARAMS,missing_fields=[field]))
        assert native+' IS NULL' in st.sql
        validate_statement(st)
        with pytest.raises(ValueError):
            validate_statement(replace(st,sql=st.sql.replace(native+' IS NULL','private IS NULL')))
    with pytest.raises(ValueError):
        ProductionQuery(kind='production',**PARAMS,missing_fields=[field],**{field:'1' if field.endswith('_id') else 'exact'})


@pytest.mark.parametrize('params',[{'missing_fields':'device,device'},{'missing_fields':'private'},{'missing_fields':'device,'},{'missing_fields':'device','device':'PC'}])
def test_http_missing_scope_rejects_invalid_before_io(workflow,params):
    client,r=install(workflow)
    assert client.get(BASE+'/projects/1/analysis',params=PARAMS|{'view':'summary'}|params).status_code==422
    assert r.calls==[]


def test_missing_http_legacy_records_and_evidence_scope(workflow):
    r=Reader();r.rows=[r.rows[0]|{'devicename':''},r.rows[0]]
    client,_=install(workflow,r)
    for route,extra in [('analysis',{'view':'summary'}),('statistics',{'kind':'production'}),('observations',{'kind':'production'})]:
        response=client.get(BASE+'/projects/1/'+route,params=PARAMS|extra|{'missing_fields':'device'})
        assert response.status_code==200,response.text
        assert response.json()['filters']['missing_fields']==['device']
        if route=='observations':
            assert len(response.json()['items'])==1 and response.json()['items'][0]['devicename']==''
        else:
            assert str(response.json()['items'][0]['records'])=='1'
    evidence=compile_query(SCOPE,ProductionQuery(kind='evidence',**PARAMS,missing_fields=['device']))
    assert 'devicename IS NULL' in evidence.sql
    validate_statement(evidence)
    with pytest.raises(ValueError):
        compile_query(SCOPE,ProductionQuery(kind='evidence',**PARAMS,missing_fields=['error_code']))


def test_missing_context_impact_freeze_and_primary_contradiction(workflow):
    r=Reader();row=r.rows[0]
    r.rows=[row|{'devicename':'','errorcode':''},row|{'devicename':'','status':'1','errorcode':'OTHER'},row]
    client,_=install(workflow,r)
    missing=['device','error_code']
    context=PARAMS|{'missing_fields':missing,'status':'2'}
    response=client.post(BASE+'/projects/1/investigations',json={'context':context})
    assert response.status_code==200,response.text
    draft=response.json();impact=draft['impact']
    assert draft['context']['missing_fields']==missing
    assert impact['state']=='available'
    assert impact['baseline']['filters']['missing_fields']==['device']
    assert impact['baseline']['counts']['records']=='2'
    assert impact['selected']['filters']['missing_fields']==missing
    assert impact['failure']['counts']['records']=='1'
    assert impact['failed_involved_sn']['numerator']=='1'
    handoff=client.post(BASE+'/projects/1/investigations/'+draft['id']+'/handoffs',json={'expected_version':1}).json()
    assert client.get(BASE+'/handoffs/'+handoff['id']).json()['context']['missing_fields']==missing
    # An exact event with a machine cannot be selected into missing-machine scope.
    page=client.get(BASE+'/projects/1/observations',params=PARAMS|{'kind':'production','device':'PC'}).json()
    response=client.put(BASE+'/projects/1/investigations/'+draft['id'],json={'expected_version':1,'primary':{'snapshot_id':page['snapshot_id'],'offset':0}})
    assert response.status_code==422,response.text
    # A matching missing event survives durable restore and expired exact requery.
    page=client.get(BASE+'/projects/1/observations',params=PARAMS|{'kind':'production','missing_fields':'device,error_code'}).json()
    response=client.put(BASE+'/projects/1/investigations/'+draft['id'],json={'expected_version':1,'primary':{'snapshot_id':page['snapshot_id'],'offset':0}})
    assert response.status_code==200,response.text
    assert response.json()['primary']['filters']['missing_fields']==missing
    resolved=client.get(BASE+'/projects/1/investigations/'+draft['id']+'/resolve')
    assert resolved.status_code==200 and resolved.json()['primary']['state']=='verified'
    r.rows=[]
    assert client.get(BASE+'/handoffs/'+handoff['id']).json()['impact']==impact


def test_first_occurrence_is_source_minimum_not_bucket_start():
    r=Reader();row=r.rows[0]
    first=NOW-timedelta(hours=2,minutes=3)
    r.rows=[row|{'timestamp':first},row]
    item=source(r).analysis(SCOPE,filters(),'errors')['items'][0]
    assert item['first_time']==first.isoformat().replace('+00:00','Z')
    assert item['last_time']=='2026-11-09T22:00:00Z'


def test_absent_empty_missing_list_preserves_old_statement_and_json_shape():
    plain=ProductionQuery(kind='production',**PARAMS)
    empty=ProductionQuery(kind='production',**PARAMS,missing_fields=[])
    assert empty.model_dump(mode='json',exclude_none=True)==plain.model_dump(mode='json',exclude_none=True)
    assert compile_query(SCOPE,empty)==compile_query(SCOPE,plain)
    with pytest.raises(ValueError):
        ProductionQuery(kind='production',**PARAMS,missing_fields='device')


@pytest.mark.parametrize('fields',[['device','device'],['private'],[True],['device']])
def test_missing_json_context_strict_and_conflicting_scope_zero_io(workflow,fields):
    client,r=install(workflow)
    context=PARAMS|{'missing_fields':fields}
    if fields==['device']:
        context['device']='PC'
    response=client.post(BASE+'/projects/1/investigations',json={'context':context})
    assert response.status_code==422,response.text
    assert r.calls==[]


def test_missing_restore_requery_retains_saved_missing_filters(investigation):
    service,actor,src,now,_,_=investigation
    src.rows[0]['devicename']=''
    query=ProductionQuery(kind='production',**PARAMS,missing_fields=['device'])
    page=service.production.query(actor,'1',query)
    draft=service.create(actor,'1',{'context':PARAMS|{'missing_fields':['device']},'primary':{'snapshot_id':page['snapshot_id'],'offset':0}})
    now[0]+=timedelta(hours=25)
    resolved=service.resolve(actor,'1',draft['id'])
    assert resolved['primary']['state']=='verified'
    assert src.calls[-1].missing_fields==('device',)
    assert service.get(actor,'1',draft['id'])['context']['missing_fields']==['device']


def test_event_missing_symptom_does_not_become_log_identity_or_log_symptom(investigation):
    service,actor,src,_,_,_=investigation
    src.rows=[{'id':1,'projuectid':1,'csn':'UNRELATED','createtime':1794186000000,'devicename':'','toolsname':'Tool','errorcode':'E'}]
    draft=service.create(actor,'1',{'context':PARAMS|{'sn':'EVENT','missing_fields':['stage_id','device','error_code']},'logs':['1']})
    saved=draft['logs'][0]
    assert saved['filters']['missing_fields']==['device']
    assert 'sn' not in saved['filters']
    assert saved['descriptor']['csn']=='UNRELATED'
    resolved=service.resolve(actor,'1',draft['id'])
    assert resolved['logs'][0]['state']=='verified'
    evidence_queries=[q for q in src.calls if q.kind=='evidence']
    assert all(q.missing_fields==('device',) and q.sn is None for q in evidence_queries)


def test_overview_statistics_failure_preserves_independent_trend_and_latest(workflow):
    r=Reader();select=r.select
    def bad_statistics(st):
        if st.name.startswith('analytics:overview:'):
            r.calls.append(st)
            return [{'records':True}]
        return select(st)
    r.select=bad_statistics
    client,_=install(workflow,r)
    data=client.get(BASE+'/overview',params=PARAMS).json()
    item=data['items'][0]
    assert not data['complete'] and item['state']=='partial'
    assert item['statistics'] is None
    assert len(item['trend'])==1 and item['latest_at']=='2026-11-09T22:00:00Z'
    assert item['blocks']['statistics']['error']=='SOURCE_SCHEMA_INVALID'
    assert item['blocks']['trend']['complete'] and item['blocks']['latest']['complete']


def test_overview_block_read_times_are_independent_completion_times():
    r=Reader();src=source(r)
    n=[0]
    def clock():
        value=NOW+timedelta(seconds=n[0]);n[0]+=1
        return value
    src.clock=clock
    data=src.overview('native',filters())
    blocks=data['items'][0]['blocks']
    assert blocks['statistics']['captured_at']=='2026-11-10T00:00:00Z'
    assert blocks['trend']['captured_at']=='2026-11-10T00:00:01Z'
    assert blocks['latest']['captured_at']=='2026-11-10T00:00:02Z'
    assert data['captured_at']=='2026-11-10T00:00:03Z'


def test_missing_error_analysis_denominator_removes_only_symptom():
    r=Reader();row=r.rows[0]
    r.rows=[row|{'devicename':'','errorcode':''},row|{'devicename':'','errorcode':'OTHER','status':'1'},row]
    result=source(r).analysis(SCOPE,filters(missing_fields=['device','error_code']),'errors')
    item=result['items'][0]
    assert item['records']=='1' and item['denominator_records']=='2'
    denominator=next(st for st in r.calls if st.name.startswith('analytics:denominator:'))
    assert 'devicename IS NULL' in denominator.sql
    assert 'errorcode IS NULL' not in denominator.sql


def test_partial_statistics_omission_is_unknown_instead_of_observed_zero(monkeypatch):
    from manufacturing_platform.production_tools import analytics
    original=analytics._groups
    def partial(src,statement,view):
        return ([], 'byte_limit') if view=='overview' else original(src,statement,view)
    monkeypatch.setattr(analytics,'_groups',partial)
    data=source(Reader()).overview('native',filters())
    item=data['items'][0]
    assert not data['complete'] and item['statistics'] is None
    assert item['blocks']['statistics']['state']=='partial'
