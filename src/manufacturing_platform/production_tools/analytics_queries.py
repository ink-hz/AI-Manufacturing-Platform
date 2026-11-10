"""Fixed native aggregate shapes; values are always bound, identifiers never supplied."""
from datetime import UTC, datetime
from functools import lru_cache
from types import MappingProxyType

from .contracts import AnalyticsFilters, ReadStatement, valid_source_id, MISSING_FIELDS
from .queries import AGGREGATE, PRODUCTION_FIELDS, missing_predicate

BUCKETS = (5, 15, 30, 60, 180, 360, 720, 1440)
DIMENSIONS = MappingProxyType({
    'summary': (),
    'stages': (('workstagesid','stage_id'), ('softwareid','software_id')),
    'errors': (('workstagesid','stage_id'), ('softwareid','software_id'), ('errorcode','error_code')),
    'denominator': (('workstagesid','stage_id'), ('softwareid','software_id')),
    'devices': (('devicename','device'),),
    'activity': (('devicename','device'),),
    'trend': (),
    'versions': (('workstagesid','stage_id'), ('softwareid','software_id'), ('version','software_version'), ('configlogsid','config_log_id'), ('cversion','config_version')),
    'overview': (),
    'overview_trend': (),
    'latest': (),
})
COUNTS = AGGREGATE + ", count_distinct(CASE WHEN status = '2' AND sn <> '' THEN sn ELSE null END) AS failed_sn, min(timestamp) AS first_time, max(timestamp) AS last_time"


def bucket_minutes(filters):
    epoch = datetime(1970,1,1,tzinfo=UTC)
    def micros(dt):
        delta = dt.astimezone(UTC)-epoch
        return (delta.days*86400+delta.seconds)*1000000+delta.microseconds
    for minutes in BUCKETS:
        width = minutes*60*1000000
        if (micros(filters.end)-1)//width-micros(filters.start)//width+1 <= 96:
            return minutes
    raise ValueError('invalid interval')


@lru_cache(maxsize=512)
def _shape(view, mask, minutes, projects, missing_mask=0):
    if view not in DIMENSIONS or type(mask) is not int or not 0 <= mask < (1 << len(PRODUCTION_FIELDS)) or type(projects) is not int or not 1 <= projects <= 100:
        raise ValueError('invalid analysis shape')
    if type(missing_mask) is not int or not 0 <= missing_mask < (1 << len(MISSING_FIELDS)):
        raise ValueError('invalid missing shape')
    missing = tuple(field for i,field in enumerate(MISSING_FIELDS) if missing_mask & (1<<i))
    timed = view in {'activity','trend','overview_trend'}
    batch = view in {'overview','overview_trend'} or (view=='latest' and projects>1)
    if (timed and minutes not in BUCKETS) or (not timed and minutes != 0) or (not batch and projects!=1) or (view=='latest' and (mask or missing_mask)):
        raise ValueError('invalid analysis shape')
    fields = tuple(name for i,name in enumerate(PRODUCTION_FIELDS) if mask & (1<<i))
    if set(fields)&set(missing) or (view=='denominator' and (set(fields)|set(missing))&{'status','error_code'}):
        raise ValueError('invalid denominator')
    dims = ((('projuectid','source_project_id'),) if batch else ()) + DIMENSIONS[view]
    def expression(native,alias):
        if alias=='source_project_id':
            return native
        condition = missing_predicate(alias, native) if alias in MISSING_FIELDS else f"{native} IS NULL"
        return f"CASE WHEN {condition} THEN null ELSE {native} END"
    select = [f'{expression(native,alias)} AS {alias}' for native,alias in dims]
    groups = [expression(native,alias) for native,alias in dims]
    if timed:
        bucket = f"timestamp_floor('{minutes}m', timestamp)"
        select.append(bucket+' AS timestamp')
        groups.append(bucket)
    select.append('max(timestamp) AS latest_at' if view=='latest' else COUNTS)
    sql = 'SELECT '+', '.join(select)+' FROM productionlog WHERE '
    sql += ('projuectid IN ('+', '.join(['%s']*projects)+')') if batch else 'projuectid = %s'
    if view != 'latest':
        sql += ' AND timestamp >= %s AND timestamp < %s'
    for name in fields:
        sql += f' AND {PRODUCTION_FIELDS[name]} = %s'
    for field in missing:
        sql += ' AND ' + missing_predicate(field, PRODUCTION_FIELDS[field])
    if view=='errors':
        sql += " AND status = '2'"
    if groups:
        sql += ' GROUP BY '+', '.join(groups)
        sql += ' ORDER BY '+('source_project_id' if view=='latest' else 'timestamp' if timed else 'failed_sn DESC')
        if timed and dims:
            sql += ', '+', '.join(alias for _,alias in dims)
        elif not timed:
            sql += ', '+', '.join(alias for _,alias in dims)
        sql += ' LIMIT %s'
    return sql


def compile_analysis(scope, filters, view, *, project_ids=None):
    if view not in DIMENSIONS or view=='latest':
        raise ValueError('invalid analysis view')
    if not isinstance(filters, AnalyticsFilters):
        raise ValueError('invalid analysis filters')
    ids = tuple(project_ids) if project_ids is not None else (scope.source_project_id,)
    if not ids or len(set(ids))!=len(ids) or not all(valid_source_id(x) for x in ids):
        raise ValueError('invalid source ids')
    values = filters.public()
    names = tuple(n for n in PRODUCTION_FIELDS if values.get(n) is not None)
    mask = sum(1<<i for i,n in enumerate(PRODUCTION_FIELDS) if n in names)
    minutes = bucket_minutes(filters) if view in {'activity','trend','overview_trend'} else 0
    missing_mask = sum(1<<i for i,field in enumerate(MISSING_FIELDS) if field in (filters.missing_fields or ()))
    sql = _shape(view, mask, minutes, len(ids), missing_mask)
    params = list(ids)+[d.astimezone(UTC).replace(tzinfo=None) for d in (filters.start,filters.end)]+[values[n] for n in names]
    grouped = bool(DIMENSIONS[view]) or view in {'activity','trend','overview','overview_trend'}
    if grouped:
        params.append(1001)
    return ReadStatement(f'analytics:{view}:{mask}:{minutes}:{len(ids)}'+(f':{missing_mask}' if missing_mask else ''), 'questdb', sql, tuple(params), 1001 if grouped else 1)


def latest_statement(project_ids):
    ids=tuple(project_ids)
    if not ids or len(set(ids))!=len(ids) or not all(valid_source_id(x) for x in ids):
        raise ValueError('invalid source ids')
    sql = _shape('latest',0,0,len(ids))
    # Multi-project metadata is a bounded grouped query; one project remains single-row.
    params=ids+( (1001,) if len(ids)>1 else ())
    return ReadStatement(f'analytics:latest:0:0:{len(ids)}', 'questdb', sql, params, 1001 if len(ids)>1 else 1)


def validate_analytics_statement(statement):
    try:
        parts=statement.name.split(':')
        prefix,view,mask,minutes,projects=parts[:5]
        missing=parts[5] if len(parts)==6 else '0'
        if len(parts) not in (5,6) or (len(parts)==6 and missing=='0'):
            return False
        if prefix!='analytics' or any(not s.isdecimal() or str(int(s))!=s for s in (mask,minutes,projects,missing)):
            return False
        mask,minutes,projects=map(int,(mask,minutes,projects))
        expected=_shape(view,mask,minutes,projects,int(missing))
        grouped=' GROUP BY ' in expected
        cap=1001 if grouped else 1
        return statement.backend=='questdb' and statement.sql==expected and type(statement.max_rows) is int and statement.max_rows==cap and len(statement.params)==expected.count('%s') and (not grouped or type(statement.params[-1]) is int and statement.params[-1]==1001)
    except (ValueError,TypeError,KeyError):
        return False
