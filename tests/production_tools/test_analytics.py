"""Native-shaped transport rows exercise full-source registered aggregates."""
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import re

import pytest

from manufacturing_platform.production_tools.contracts import ProductionQuery, SourceScope
from manufacturing_platform.production_tools.queries import compile_query, validate_statement
from manufacturing_platform.production_tools.source import NativeProductionSource
from manufacturing_platform.workflow.contracts import DomainError

NOW = datetime(2026, 11, 10, tzinfo=UTC)
SCOPE = SourceScope('native', '1', 'v1', '')
PARAMS = {'start': '2026-11-09T00:00:00Z', 'end': '2026-11-10T00:00:00Z'}
FULL = dict(sn='SN', order_id='8', device='PC', status='2', stage_id='99999999999999999999', software_id='20', software_version='3.1', config_log_id='30', config_version='4.2', error_code='E', barcode='B')


def filters(**kw):
    from manufacturing_platform.production_tools.contracts import AnalyticsFilters
    return AnalyticsFilters(**(PARAMS | kw))


class Reader:
    def __init__(self, rows=None, projects=None):
        self.rows = rows if rows is not None else [dict(projuectid='1', timestamp=NOW-timedelta(hours=2), sn='SN', status='2', workstagesid='10', softwareid='20', version='3.1', configlogsid='30', cversion='4.2', devicename='PC', errorcode='E', barcode='B', orderid='8')]
        self.projects = projects or [{'id': 1, 'name': 'Project'}]
        self.calls = []
        self.failure = False
        self.used_aggregate_sql = False

    def select(self, st):
        validate_statement(st)
        self.calls.append(st)
        if st.name == 'analytics_stage_names':
            return [{'id':10,'name':'Native stage'}]
        if st.name == 'analytics_software_names':
            return [{'id':20,'name':'Native tool'}]
        if st.name.startswith('source_project'):
            rows = self.projects
            if st.name == 'source_project':
                rows = [r for r in rows if str(r['id']) == str(st.params[0])]
            elif st.name == 'source_projects_before':
                rows = [r for r in rows if int(r['id']) < st.params[0]]
            return rows[:st.max_rows]
        if self.failure:
            raise RuntimeError('private-password')
        # This transport evaluates native source predicates before any grouping or cap.
        where = st.sql.split(' WHERE ', 1)[1].split(' GROUP BY ')[0].split(' ORDER BY ')[0].split(' LIMIT ')[0]
        predicates = re.findall(r'(\w+) (>=|<|=) %s', where)
        batch = re.search(r'projuectid IN \(([^)]+)\)', where)
        n = batch.group(1).count('%s') if batch else 0
        rows = self.rows
        if batch:
            rows = [r for r in rows if str(r['projuectid']) in st.params[:n]]
        for (field, op), val in zip(predicates, st.params[n:]):
            if isinstance(val, datetime):
                val = val.replace(tzinfo=UTC)
            rows = [r for r in rows if (str(r.get(field)) == str(val) if op == '=' else r[field] >= val if op == '>=' else r[field] < val)]
        for native,literals in re.findall(r"AND \((\w+) IS NULL OR \w+ IN \(([^)]+)\)\)",where):
            missing_values=re.findall(r"'([^']*)'",literals)
            rows=[row for row in rows if row.get(native) is None or str(row[native]) in missing_values]
        if "status = '2'" in where:
            rows = [r for r in rows if r.get('status') == '2']
        if 'max(timestamp) AS latest_at' in st.sql:
            if batch:
                ids = dict.fromkeys(str(r['projuectid']) for r in rows)
                return [dict(source_project_id=p, latest_at=max(r['timestamp'] for r in rows if str(r['projuectid'])==p)) for p in ids]
            return [{'latest_at': max((r['timestamp'] for r in rows), default=None)}]
        if st.sql.startswith('SELECT *'):
            return rows[:st.max_rows]
        assert 'count(*) AS records' in st.sql, st.sql
        self.used_aggregate_sql = True
        dims = re.findall(r'(workstagesid|softwareid|devicename|errorcode|version|configlogsid|cversion|projuectid) (?:END )?AS (\w+)', st.sql)
        bucket = re.search(r"timestamp_floor\('(\d+)m', timestamp\) AS timestamp", st.sql)
        groups = defaultdict(list)
        for row in rows:
            def value(n,alias):
                raw=row.get(n)
                if f'{n} IS NULL OR' in st.sql and (raw is None or raw=='' or (alias in {'stage_id','software_id','config_log_id'} and str(raw) in {'0','-1'})):
                    return None
                return str(raw) if raw is not None else None
            values = tuple(value(n,alias) for n,alias in dims)
            if bucket:
                seconds = int(bucket.group(1))*60
                values += (datetime.fromtimestamp(int(row['timestamp'].timestamp())//seconds*seconds, UTC),)
            groups[values].append(row)
        if not dims and not bucket:
            groups[()] = rows
        result = []
        for vals, group in groups.items():
            item = dict(zip([alias for _,alias in dims] + (['timestamp'] if bucket else []), vals))
            item.update(records=len(group), distinct_sn=len({r['sn'] for r in group if r.get('sn')}), pass_records=sum(r.get('status')=='1' for r in group), fail_records=sum(r.get('status')=='2' for r in group))
            if ' AS failed_sn' in st.sql:
                item.update(failed_sn=len({r['sn'] for r in group if r.get('sn') and r.get('status')=='2'}), first_time=min((r['timestamp'] for r in group), default=None), last_time=max((r['timestamp'] for r in group), default=None))
            result.append(item)
        return result[:st.max_rows]


def source(reader):
    return NativeProductionSource(reader, reader, None, allowed_object_host='', clock=lambda: NOW)


def test_full_interval_duplicates_unknown_and_missing_error():
    reader = Reader()
    row = reader.rows[0]
    reader.rows = [row.copy() for _ in range(2500)] + [row | {'sn':'PASS','status':'1'}, row | {'sn':'','status':'?', 'errorcode':None}]
    result = source(reader).analysis(SCOPE, filters(), 'summary')
    assert result['items'][0] | {} == dict(key='[]', records='2502', distinct_sn='2', pass_records='1', fail_records='2500', unknown_records='1', failed_sn='1', first_time='2026-11-09T22:00:00Z', last_time='2026-11-09T22:00:00Z')
    assert reader.used_aggregate_sql
    assert result['captured_at'] == '2026-11-10T00:00:00Z'
    assert result['complete']
    errors = source(reader).analysis(SCOPE, filters(), 'errors')['items']
    assert errors[0]['denominator_records'] == '2502'
    reader.rows.append(row | {'errorcode':None})
    assert any(x['error_code'] is None for x in source(reader).analysis(SCOPE, filters(), 'errors')['items'])


def test_error_denominator_drops_only_result_and_symptom():
    r = Reader()
    r.rows += [r.rows[0] | {'status':'1','errorcode':'OTHER'}, r.rows[0] | {'workstagesid':'99'}]
    result = source(r).analysis(SCOPE, filters(stage_id='10', status='2', error_code='E', software_version='3.1'), 'errors')
    assert result['items'][0]['records'] == '1'
    assert result['items'][0]['denominator_records'] == '2'
    denominator = next(st for st in r.calls if st.name.startswith('analytics:denominator:'))
    assert 'workstagesid = %s' in denominator.sql and 'version = %s' in denominator.sql
    assert 'status = %s' not in denominator.sql and 'errorcode = %s' not in denominator.sql


@pytest.mark.parametrize('view', ['summary','stages','errors','devices','activity','trend','versions'])
def test_registered_views_filters_and_injection(view):
    r = Reader()
    source(r).analysis(SCOPE, filters(**FULL), view)
    st = r.calls[0]
    for field in ('sn','orderid','devicename','workstagesid','softwareid','version','configlogsid','cversion','errorcode','barcode'):
        assert f'{field} = %s' in st.sql
    validate_statement(st)
    with pytest.raises(ValueError):
        validate_statement(replace(st, sql=st.sql.replace('productionlog', 'private')))
    with pytest.raises(ValueError):
        validate_statement(replace(st, max_rows=1000000))
    with pytest.raises(ValueError):
        source(r).analysis(SCOPE, filters(), 'private;DROP TABLE')


def test_group_sentinel_and_exact_counts():
    r = Reader()
    r.rows = [r.rows[0] | {'devicename':str(i)} for i in range(1001)]
    result = source(r).analysis(SCOPE, filters(), 'devices')
    assert len(result['items']) == 1000 and not result['complete']
    assert result['truncation_reason'] == 'group_limit'
    r = Reader()
    huge = 99999999999999999999
    r.select = lambda st: [dict(records=huge, distinct_sn=huge, pass_records=0, fail_records=huge, failed_sn=huge, first_time=NOW, last_time=NOW)]
    result = source(r).analysis(SCOPE, filters(), 'summary')
    assert result['items'][0]['records'] == str(huge)


@pytest.mark.parametrize('bad', [True, 1.5, '2', -1])
def test_invalid_aggregate_counts_are_sanitized(bad):
    r = Reader()
    r.select = lambda st: [dict(records=bad, distinct_sn=0, pass_records=0, fail_records=0, failed_sn=0, first_time=None, last_time=None)]
    with pytest.raises(DomainError) as exc:
        source(r).analysis(SCOPE, filters(), 'summary')
    assert exc.value.code == 'SOURCE_SCHEMA_INVALID'


@pytest.mark.parametrize('days', [1/12, 1, 31])
def test_bucket_count_including_unaligned_boundary_at_most_96(days):
    from manufacturing_platform.production_tools.analytics_queries import bucket_minutes
    f = filters(start=(NOW-timedelta(days=days, minutes=1)).isoformat(), end=(NOW-timedelta(minutes=1)).isoformat())
    m = bucket_minutes(f)
    assert m in (5,15,30,60,180,360,720,1440)
    first = int(f.start.timestamp())//(m*60)
    last = (int(f.end.timestamp()*1000000)-1)//(m*60*1000000)
    assert last-first+1 <= 96
    if days == 1/12:
        assert m == 5


def test_availability_ignores_window_and_raw_history():
    r = Reader()
    result = source(r).availability(SCOPE)
    assert result['latest_at'] == '2026-11-09T22:00:00Z'
    assert len(r.calls)==1 and r.calls[0].max_rows==1
    assert 'timestamp >=' not in r.calls[0].sql and 'SELECT *' not in r.calls[0].sql


def test_all_native_scope_fields_compile_to_actual_statistics_sql():
    st = compile_query(SCOPE, ProductionQuery(kind='production_statistics', **PARAMS, **FULL))
    for native in ('workstagesid','softwareid','version','configlogsid','cversion','errorcode','barcode'):
        assert native+' = %s' in st.sql
    assert FULL['stage_id'] in st.params
    validate_statement(st)


def test_bounded_dictionary_names_and_missing_mapping_fallback():
    r=Reader()
    result=source(r).analysis(SCOPE,filters(),'stages')
    assert result['items'][0]['stage_name']=='Native stage'
    assert result['items'][0]['software_name']=='Native tool'
    names=[s for s in r.calls if s.name.endswith('_names')]
    assert len(names)==2
    assert names[0].sql=='SELECT id, name FROM workstages WHERE del = 0 ORDER BY id DESC LIMIT %s'
    assert names[0].max_rows==1001
    for st in names:
        validate_statement(st)
        with pytest.raises(ValueError):
            validate_statement(replace(st,sql=st.sql.replace('name','private')))
    original=r.select
    def unavailable(st):
        if st.name.endswith('_names'):
            raise RuntimeError('private secret')
        return original(st)
    r.select=unavailable
    result=source(r).analysis(SCOPE,filters(),'stages')
    assert result['items'][0]['records']=='1'
    assert result['items'][0]['stage_id']=='10'
    assert result['items'][0]['stage_name']=='Unknown stage (10)'


def test_selected_distribution_denominator_retains_base_scope():
    r=Reader()
    r.rows += [r.rows[0]|{'status':'1','errorcode':None}]
    result=source(r).analysis(SCOPE,filters(status='2',error_code='E'),'devices')
    assert result['items'][0]['records']=='1'
    assert result['items'][0]['denominator_records']=='2'


def test_missing_and_sentinel_dimensions_remain_one_unknown_group():
    r=Reader()
    row=r.rows[0]
    r.rows=[row|{'workstagesid':v,'errorcode':code} for v,code in [(None,None),('', ''),('0',None),('-1','')]]
    result=source(r).analysis(SCOPE,filters(),'errors')
    assert result['complete']
    assert len(result['items'])==1
    item=result['items'][0]
    assert item['stage_id'] is None and item['error_code'] is None
    assert item['records']=='4' and item['distinct_sn']=='1'
    assert item['stage_name']=='Stage not provided'


def test_multibyte_labels_stay_within_response_byte_bound():
    import json
    from manufacturing_platform.production_tools.source import MAX_BYTES
    r=Reader()
    row=r.rows[0]
    r.rows=[row|{'version':'😀'*197+str(i),'cversion':'😀'*200} for i in range(1000)]
    select=r.select
    def named(st):
        if st.name.endswith('_names'):
            return [{'id':10 if st.name=='analytics_stage_names' else 20,'name':'😀'*200}]
        return select(st)
    r.select=named
    result=source(r).analysis(SCOPE,filters(),'versions')
    assert len(json.dumps(result,ensure_ascii=False).encode('utf-8'))<=MAX_BYTES
    assert not result['complete'] and result['truncation_reason']=='byte_limit'


def test_distinct_sn_across_error_groups_is_never_a_project_sum():
    r=Reader()
    r.rows += [r.rows[0]|{'errorcode':'OTHER'},r.rows[0]|{'errorcode':'OTHER'}]
    summary=source(r).analysis(SCOPE,filters(),'summary')['items'][0]
    errors=source(r).analysis(SCOPE,filters(),'errors')['items']
    assert summary['failed_sn']=='1' and summary['fail_records']=='3'
    assert len(errors)==2 and all(item['failed_sn']=='1' for item in errors)
    assert all(item['denominator_records']=='3' for item in errors)


def test_aggregate_slots_fail_closed_and_release_after_transport_error():
    r=Reader()
    src=source(r)
    for _ in range(4):
        assert src._slots.acquire(blocking=False)
    with pytest.raises(DomainError) as caught:
        src.analysis(SCOPE,filters(),'summary')
    assert caught.value.code=='SOURCE_BUSY' and not r.calls
    for _ in range(4):
        src._slots.release()
    r.failure=True
    with pytest.raises(DomainError) as caught:
        src.analysis(SCOPE,filters(),'summary')
    assert caught.value.code=='SOURCE_UNAVAILABLE'
    r.failure=False
    assert src.analysis(SCOPE,filters(),'summary')['complete']
