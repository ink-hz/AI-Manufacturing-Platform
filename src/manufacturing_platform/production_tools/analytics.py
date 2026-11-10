"""Bounded normalization of whole-interval SQL aggregates (never captured samples)."""
import json
import re
from datetime import UTC, datetime

from .analytics_queries import DIMENSIONS, bucket_minutes, compile_analysis, latest_statement
from .contracts import valid_source_id
from .source import MAX_BYTES, error, normalize
from .queries import dictionary_statement

COUNT_FIELDS = ('records','distinct_sn','pass_records','fail_records','failed_sn')
ID_FIELDS = {'stage_id','software_id','config_log_id','source_project_id'}


def _timestamp(value):
    if value is None:
        return None
    if isinstance(value, str):
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})',value) is None:
            raise error('SOURCE_SCHEMA_INVALID')
        try:
            value=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError:
            raise error('SOURCE_SCHEMA_INVALID') from None
    if not isinstance(value, datetime):
        raise error('SOURCE_SCHEMA_INVALID')
    return normalize(value,set())


def _dimension(name,value):
    if value is None or value=='':
        return None
    if name in ID_FIELDS:
        if type(value) not in (int,str) or not valid_source_id(str(value)):
            raise error('SOURCE_SCHEMA_INVALID')
        return str(value)
    if not isinstance(value,str) or len(value)>200:
        raise error('SOURCE_SCHEMA_INVALID')
    return value


def aggregate(row, dimensions):
    if not isinstance(row,dict) or any(key not in row for key in (*COUNT_FIELDS,'last_time',*dimensions)):
        raise error('SOURCE_SCHEMA_INVALID')
    counts={name: row[name] for name in COUNT_FIELDS}
    # SUM over no records can be NULL; count and distinct remain strict integer counts.
    for name in ('pass_records','fail_records'):
        if counts[name] is None:
            counts[name]=0
    if any(type(value) is not int or not 0<=value<10**20 for value in counts.values()):
        raise error('SOURCE_SCHEMA_INVALID')
    if counts['pass_records']+counts['fail_records']>counts['records'] or counts['distinct_sn']>counts['records'] or counts['failed_sn']>min(counts['fail_records'],counts['distinct_sn']):
        raise error('SOURCE_SCHEMA_INVALID')
    item={name: _timestamp(row[name]) if name=='timestamp' else _dimension(name,row[name]) for name in dimensions}
    item['key']=json.dumps(list(item.values()),ensure_ascii=False,separators=(',',':'))
    item.update({name:str(value) for name,value in counts.items()})
    item['unknown_records']=str(counts['records']-counts['pass_records']-counts['fail_records'])
    item['last_time']=_timestamp(row['last_time'])
    return item


def _read(source,statement):
    rows=source._select(statement)
    if not isinstance(rows,list) or len(rows)>statement.max_rows or any(not isinstance(row,dict) for row in rows):
        raise error('SOURCE_SCHEMA_INVALID')
    return rows


def _groups(source,statement,view):
    rows=_read(source,statement)
    if statement.max_rows==1 and len(rows)!=1:
        raise error('SOURCE_SCHEMA_INVALID')
    dims=(["source_project_id"] if view in {'overview','overview_trend'} else [])+[alias for _,alias in DIMENSIONS[view]]+(['timestamp'] if view in {'activity','trend','overview_trend'} else [])
    items=[]
    size=1024
    reason='group_limit' if len(rows)>1000 else None
    keys=set()
    for row in rows[:1000]:
        item=aggregate(row,dims)
        if item['key'] in keys:
            raise error('SOURCE_SCHEMA_INVALID')
        keys.add(item['key'])
        size+=len(json.dumps(item,ensure_ascii=False,allow_nan=False).encode('utf-8'))+1
        if size>MAX_BYTES:
            if not items:
                raise error('SOURCE_LIMIT_EXCEEDED',422)
            reason='byte_limit'
            break
        items.append(item)
    return items,reason


def _acquire(source):
    if not source._slots.acquire(blocking=False):
        raise error('SOURCE_BUSY')


def _bound_result(result):
    """Include dictionary labels, keys and the full public envelope in the byte cap."""
    envelope=result|{'items':[]}
    size=len(json.dumps(envelope,ensure_ascii=False,allow_nan=False).encode('utf-8'))+100
    kept=[]
    for item in result['items']:
        size+=len(json.dumps(item,ensure_ascii=False,allow_nan=False).encode('utf-8'))+2
        if size>MAX_BYTES:
            result['complete']=False
            result['truncation_reason']='byte_limit'
            break
        kept.append(item)
    result['items']=kept
    return result


def _names(source,scope,items):
    from ..workflow.contracts import DomainError
    for kind,field in (("stage","stage_id"),("software","software_id")):
        if not any(field in item for item in items):
            continue
        mapping={}
        try:
            rows=_read(source,dictionary_statement(scope,kind))
            previous=None
            for row in rows[:1000]:
                if set(row)!={"id","name"}:
                    raise error("SOURCE_SCHEMA_INVALID")
                identifier=_dimension(field,row["id"])
                name=row["name"]
                if identifier is None or (previous is not None and int(identifier)>=previous) or not isinstance(name,str) or not 0<len(name)<=200:
                    raise error("SOURCE_SCHEMA_INVALID")
                previous=int(identifier)
                mapping[identifier]=name
        except DomainError:
            mapping={}
        for item in items:
            if field in item:
                item[kind+"_name"]=mapping.get(item[field], f"Unknown {kind} ({item[field]})" if item[field] is not None else f"{kind.title()} not provided")


def analysis(source,scope,filters,view):
    if view not in {'summary','stages','errors','devices','activity','trend','versions'}:
        raise ValueError('invalid analysis view')
    statement=compile_analysis(scope,filters,view)
    _acquire(source)
    try:
        items,reason=_groups(source,statement,view)
        if filters.status is not None:
            expected='pass_records' if filters.status=='1' else 'fail_records'
            if any(item[expected]!=item['records'] for item in items):
                raise error('SOURCE_SCHEMA_INVALID')
        if view=='errors':
            if any(item['fail_records']!=item['records'] for item in items):
                raise error('SOURCE_SCHEMA_INVALID')
            baseline=filters.model_copy(update={'status':None,'error_code':None})
            denominators,denominator_reason=_groups(source,compile_analysis(scope,baseline,'denominator'),'denominator')
            index={(x['stage_id'],x['software_id']):x['records'] for x in denominators}
            for item in items:
                value=index.get((item['stage_id'],item['software_id']))
                if value is None and not denominator_reason:
                    raise error('SOURCE_SCHEMA_INVALID')
                if value is not None:
                    item['denominator_records']=value
            reason=reason or denominator_reason
        elif filters.status is not None or filters.error_code is not None:
            baseline=filters.model_copy(update={'status':None,'error_code':None})
            denominators,denominator_reason=_groups(source,compile_analysis(scope,baseline,view),view)
            index={item['key']:item['records'] for item in denominators}
            for item in items:
                value=index.get(item['key'])
                if value is None and not denominator_reason:
                    raise error('SOURCE_SCHEMA_INVALID')
                if value is not None:
                    item['denominator_records']=value
            reason=reason or denominator_reason
        _names(source,scope,items)
        result=dict(view=view,source_namespace=scope.source_namespace,source_project_id=scope.source_project_id,captured_at=_timestamp(source.clock()),filters=filters.public(),items=items,complete=reason is None,truncation_reason=reason)
        if view in {'activity','trend'}:
            result['bucket_minutes']=bucket_minutes(filters)
        return _bound_result(result)
    finally:
        source._slots.release()


def _latest(source,ids):
    rows=_read(source,latest_statement(ids))
    batch=len(ids)>1
    if not batch and len(rows)!=1:
        raise error('SOURCE_SCHEMA_INVALID')
    result={}
    for row in rows:
        if set(row)!=({'source_project_id','latest_at'} if batch else {'latest_at'}):
            raise error('SOURCE_SCHEMA_INVALID')
        identifier=_dimension('source_project_id',row['source_project_id']) if batch else ids[0]
        if identifier not in ids or identifier in result:
            raise error('SOURCE_SCHEMA_INVALID')
        result[identifier]=_timestamp(row['latest_at'])
    return result


def availability(source,scope):
    _acquire(source)
    try:
        latest=_latest(source,(scope.source_project_id,))
        return dict(source_namespace=scope.source_namespace,source_project_id=scope.source_project_id,captured_at=_timestamp(source.clock()),latest_at=latest.get(scope.source_project_id))
    finally:
        source._slots.release()


def _zero():
    return dict(key='[]',**{name:'0' for name in (*COUNT_FIELDS,'unknown_records')},last_time=None)


def overview(source,namespace,filters,*,before_id=None):
    from ..workflow.contracts import DomainError
    page=source.projects(before_id=before_id)
    ids=tuple(x['id'] for x in page['items'])
    result=dict(items=[],captured_at=None,complete=not page['has_more'],limit=100,has_more=page['has_more'],next_before_id=page['next_before_id'],source_namespace=namespace)
    statistics={}
    trends={identifier:[] for identifier in ids}
    latest={}
    state='ready'
    if ids:
        _acquire(source)
        try:
            rows,reason=_groups(source,compile_analysis(None,filters,'overview',project_ids=ids),'overview')
            for item in rows:
                identifier=item.pop('source_project_id')
                if identifier not in ids or identifier in statistics:
                    raise error('SOURCE_SCHEMA_INVALID')
                item['key']='[]'
                statistics[identifier]=item
            trend_rows,trend_reason=_groups(source,compile_analysis(None,filters,'overview_trend',project_ids=ids),'overview_trend')
            for item in trend_rows:
                identifier=item.pop('source_project_id')
                if identifier not in ids:
                    raise error('SOURCE_SCHEMA_INVALID')
                item['key']=json.dumps([item['timestamp']],separators=(',',':'))
                trends[identifier].append(item)
            latest=_latest(source,ids)
            result['complete']=result['complete'] and not reason and not trend_reason
        except DomainError:
            state='unavailable'
            statistics={}
            trends={identifier:[] for identifier in ids}
            latest={}
            result['complete']=False
        finally:
            source._slots.release()
    result['items']=[item|dict(state=state,statistics=statistics.get(item['id'],_zero()) if state=='ready' else None,trend=trends[item['id']],latest_at=latest.get(item['id'])) for item in page['items']]
    result['captured_at']=_timestamp(source.clock())
    return result
