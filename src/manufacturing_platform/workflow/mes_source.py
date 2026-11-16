"""Administrator-scoped MES source observations with isolated local snapshots."""
import json
from uuid import uuid4
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from ..mes_access.errors import MesAccessError
import re
from .clock import checked_time

PREFIX = '/material-control/mes-source'
MESSAGES = {
    'MES_ORDER_EMPTY': 'MES工单没有组件，保留上次成功读取结果。',
    'MES_COLLECTION_LIMIT': 'MES组件超过完整读取上限。',
    'MES_COLLECTION_INCOMPLETE': 'MES组件读取不完整，未接纳本次结果。',
    'MES_UNAVAILABLE': 'MES只读源暂不可用，保留上次成功读取结果。',
    'MES_OPERATION_FAILED': 'MES只读查询失败，保留上次成功读取结果。',
    'MES_RELAY_UNAVAILABLE': 'Mac只读连接器离线，请恢复Mac与加密隧道后重试；保留上次成功读取结果。',
    'MES_RELAY_UNAUTHORIZED': 'Mac只读连接器认证失败，请联系管理员核对中转配置。',
    'MES_RELAY_CONTEXT_MISMATCH': 'Mac只读连接器来源已变更，请联系管理员重新登记。',
    'MES_RELAY_BUSY': 'Mac只读连接器繁忙，请稍后重试。',
    'MES_RELAY_INVALID_RESPONSE': 'Mac只读连接器响应校验失败，未接纳本次结果。',
    'MES_RELAY_RESPONSE_TOO_LARGE': 'Mac只读连接器响应超过读取上限，未接纳本次结果。',
    'MES_TIMEOUT': 'MES读取超时，请检查Mac只读连接器与源连接后重试。',
    'MES_FUNCTION_NOT_ALLOWED': 'MES read function is not allowed',
    'MES_AUTHENTICATION_FAILED': 'MES source authentication failed',
    'MES_BUSINESS_FAILURE': 'MES source rejected the read request',
    'MES_RESULT_LIMIT_EXCEEDED': 'MES result exceeds the complete-read limit',
    'MES_INVALID_RESPONSE': 'MES source returned an invalid response',
    'MES_INVALID_CONTRACT': 'MES source contract is unavailable',
    'MES_RESPONSE_TOO_LARGE': 'MES response exceeds the permitted size',
    'MES_NOT_CONFIGURED': 'MES source is not configured',
    'MES_CONFIGURATION_ERROR': 'MES source configuration is unavailable',
    'MES_DISABLED': 'MES source is disabled',
    'MES_REFRESH_FAILED': 'MES source refresh failed',
    'MES_SCOPE_MISMATCH': 'MES response does not match the requested object',
    'MES_REFRESH_SUPERSEDED': 'A newer refresh superseded this request',
    'MES_CONFIGURATION_CHANGED': 'MES configuration changed during refresh',
}

def error(code):
    return dict(code=code, message=MESSAGES[code])

def authorize(service, actor):
    if not actor.configuration_admin or not service.resolve_subject(actor.user_id):
        raise HTTPException(403, 'Permission denied')

def context(service):
    if service.mes_access_service is None:
        return None, error('MES_NOT_CONFIGURED')
    try:
        return service.mes_access_service.read_context(), None
    except Exception as exc:
        code = getattr(exc, 'code', '')
        return None, error(code if code in {'MES_DISABLED','MES_CONFIGURATION_ERROR'} else 'MES_CONFIGURATION_ERROR')

def read_row(tx, key):
    row = tx.execute('SELECT * FROM mes_source_observations WHERE fingerprint=? AND kind=? AND scope_json=?', key).fetchone()
    return dict(snapshot=json.loads(row['snapshot_json']) if row and row['snapshot_json'] else None,
                refresh_error=json.loads(row['refresh_error_json']) if row and row['refresh_error_json'] else None)

def observe(service, actor, kind, scope, refresh=False):
    ctx, unavailable = context(service)
    if ctx is None:
        return dict(snapshot=None, refresh_error=unavailable)
    key = (ctx['fingerprint'], kind, json.dumps(scope, sort_keys=True, separators=(',', ':')))
    if not refresh:
        with service.store.transaction() as tx:
            result = read_row(tx, key)
        if not service.mes_access_service.configuration_matches(ctx['fingerprint']):
            return dict(snapshot=None, refresh_error=error('MES_CONFIGURATION_CHANGED'))
        return result
    with service.store.transaction(write=True) as tx:
        tx.execute('INSERT INTO mes_source_observations(fingerprint,kind,scope_json,refresh_seq) VALUES(?,?,?,1) ON CONFLICT(fingerprint,kind,scope_json) DO UPDATE SET refresh_seq=refresh_seq+1', key)
        seq = tx.execute('SELECT refresh_seq FROM mes_source_observations WHERE fingerprint=? AND kind=? AND scope_json=?', key).fetchone()[0]
    # Source network I/O stays outside transactions; config is rechecked under the final write lock.
    failure = None
    data = None
    try:
        mes = service.mes_access_service
        kwargs = dict(expected_fingerprint=ctx['fingerprint'])
        actor_id = str(actor.user_id)
        if kind == 'orders':
            data = mes.source_orders(scope['prefix'], scope['after'], actor_id, **kwargs)
        elif kind == 'order-materials':
            data = mes.collect_order_materials(scope['shop_order'], actor_id, **kwargs)
        else:
            interface = 'material_priority' if kind == 'priority' else 'iqc_inspections'
            filters = dict(shopOrder=scope['shop_order'], itemNo=scope['material']) if kind == 'priority' else dict(item_no=scope['material'])
            data = mes.query(interface, filters, scope['page'], 5, actor_id, **kwargs)
            for row in data['rows']:
                if kind == 'priority' and (row.get('SHOP_ORDER') != scope['shop_order'] or row.get('MATNR') != scope['material']):
                    failure = error('MES_SCOPE_MISMATCH')
                elif kind == 'iqc' and row.get('ITEM_NO') != scope['material']:
                    failure = error('MES_SCOPE_MISMATCH')
    except MesAccessError as exc:
        failure = error(exc.code if exc.code in MESSAGES else 'MES_REFRESH_FAILED')
    except Exception:
        failure = error('MES_REFRESH_FAILED')
    authorize(service, actor)
    if not service.mes_access_service.configuration_matches(ctx['fingerprint']):
        return dict(snapshot=None, refresh_error=error('MES_CONFIGURATION_CHANGED'))
    snapshot = None
    if failure is None:
        snapshot = dict(id=str(uuid4()), kind=kind, scope=scope, source=ctx['source'],
                        collected_at=checked_time(service.store.business_clock).isoformat(),
                        data={k:v for k,v in data.items() if k not in {'source','function','request_id','fingerprint'}})
    with service.store.transaction(write=True) as tx:
        # Acceptance point: source-pinned observations remain valid after later config changes.
        if not service.mes_access_service.configuration_matches(ctx['fingerprint']):
            return dict(snapshot=None, refresh_error=error('MES_CONFIGURATION_CHANGED'))
        if failure:
            cursor = tx.execute('UPDATE mes_source_observations SET refresh_error_json=? WHERE fingerprint=? AND kind=? AND scope_json=? AND refresh_seq=?', (json.dumps(failure), *key, seq))
        else:
            cursor = tx.execute('UPDATE mes_source_observations SET snapshot_json=?,refresh_error_json=NULL WHERE fingerprint=? AND kind=? AND scope_json=? AND refresh_seq=?', (json.dumps(snapshot), *key, seq))
        result = read_row(tx, key)
        if cursor.rowcount != 1:
            result['refresh_error'] = error('MES_REFRESH_SUPERSEDED')
    return result

def register_mes_source_routes(router, service, actor):
    async def validate(request, kind=None):
        user = actor(request)
        authorize(service, user)
        expected = {None: set(), 'orders': {'prefix','after'}, 'order-materials': {'shop_order'}, 'priority': {'shop_order','material','page'}, 'iqc': {'material','page'}}[kind]
        query = request.query_params
        if set(query) != expected or any(len(query.getlist(k)) != 1 for k in expected):
            raise HTTPException(422, 'Invalid MES scope')
        async for chunk in request.stream():
            if chunk:
                raise HTTPException(422, 'Invalid MES request body')
        scope = dict(query)
        for key, value in scope.items():
            if key == 'page':
                if not re.fullmatch(r'[1-9][0-9]{0,6}', value) or int(value) > 1000000:
                    raise HTTPException(422, 'Invalid MES scope')
                scope[key] = int(value)
            else:
                limit = 64 if key in {'prefix','after','shop_order'} else 128
                empty = key in {'prefix','after'}
                pattern = r'[A-Za-z0-9][A-Za-z0-9_.:/ -]*' if key in {'after','shop_order'} else r'[A-Za-z0-9][A-Za-z0-9.:/ -]*'
                if len(value) > limit or value != value.strip() or (not value and not empty) or (value and not re.fullmatch(pattern, value)):
                    raise HTTPException(422, 'Invalid MES scope')
        return user, scope

    @router.get(PREFIX+'/status')
    async def status(request: Request):
        user, _ = await validate(request)
        ctx, failure = context(service)
        result = dict(configured=ctx is not None, source=ctx['source'] if ctx else None, can_refresh=ctx is not None and not user.read_only)
        if failure and failure['code'] != 'MES_NOT_CONFIGURED':
            result['refresh_error'] = failure
        return result

    def register(kind):
        async def endpoint(request: Request):
            user, scope = await validate(request, kind)
            return await run_in_threadpool(observe, service, user, kind, scope, request.method == 'POST')
        router.add_api_route(PREFIX+'/'+kind, endpoint, methods=['GET'])
        router.add_api_route(PREFIX+'/'+kind, endpoint, methods=['POST'])
    for kind in ('orders','order-materials','priority','iqc'):
        register(kind)
