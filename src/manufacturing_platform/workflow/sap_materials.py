"""Administrator-scoped SAP source observations with isolated local snapshots."""
import json
from uuid import uuid4
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from ..sap_access.errors import SapAccessError
from ..sap_access.production_order import scope as order_scope
from ..sap_access.stock_requirements import envelope as mrp_envelope
from .clock import checked_time

PREFIX = '/material-control/sap'
MESSAGES = {
    'SAP_FUNCTION_NOT_ALLOWED': 'SAP read function is not allowed',
    'SAP_AUTHENTICATION_FAILED': 'SAP source authentication failed',
    'SAP_BUSINESS_FAILURE': 'SAP source rejected the read request',
    'SAP_RESULT_LIMIT_EXCEEDED': 'SAP result exceeds the complete-read limit',
    'SAP_INVALID_RESPONSE': 'SAP source returned an invalid response',
    'SAP_INVALID_CONTRACT': 'SAP source contract is unavailable',
    'SAP_RESPONSE_TOO_LARGE': 'SAP response exceeds the permitted size',
    'SAP_NOT_CONFIGURED': 'SAP source is not configured',
    'SAP_CONFIGURATION_ERROR': 'SAP source configuration is unavailable',
    'SAP_DISABLED': 'SAP source is disabled',
    'SAP_REFRESH_FAILED': 'SAP source refresh failed',
    'SAP_SCOPE_MISMATCH': 'SAP response does not match the requested object',
    'SAP_REFRESH_SUPERSEDED': 'A newer refresh superseded this request',
    'SAP_CONFIGURATION_CHANGED': 'SAP configuration changed during refresh',
}

def error(code):
    return dict(code=code, message=MESSAGES[code])

def authorize(service, actor):
    if not actor.configuration_admin or not service.resolve_subject(actor.user_id):
        raise HTTPException(403, 'Permission denied')

def context(service):
    if service.sap_access_service is None:
        return None, error('SAP_NOT_CONFIGURED')
    try:
        return service.sap_access_service.read_context(), None
    except Exception as exc:
        code = getattr(exc, 'code', '')
        return None, error(code if code in {'SAP_DISABLED','SAP_CONFIGURATION_ERROR'} else 'SAP_CONFIGURATION_ERROR')

def read_row(tx, key):
    row = tx.execute('SELECT * FROM sap_material_observations WHERE fingerprint=? AND kind=? AND scope_json=?', key).fetchone()
    return dict(snapshot=json.loads(row['snapshot_json']) if row and row['snapshot_json'] else None,
                refresh_error=json.loads(row['refresh_error_json']) if row and row['refresh_error_json'] else None)

def same_material(left, right):
    return isinstance(left, str) and (left == right or (left.isascii() and left.isdigit() and right.isascii() and right.isdigit() and int(left) == int(right)))

def observe(service, actor, kind, scope, refresh=False):
    ctx, unavailable = context(service)
    if ctx is None:
        return dict(snapshot=None, refresh_error=unavailable)
    key = (ctx['fingerprint'], kind, json.dumps(scope, sort_keys=True, separators=(',', ':')))
    if not refresh:
        with service.store.transaction() as tx:
            result = read_row(tx, key)
        if not service.sap_access_service.configuration_matches(ctx['fingerprint']):
            return dict(snapshot=None, refresh_error=error('SAP_CONFIGURATION_CHANGED'))
        return result
    with service.store.transaction(write=True) as tx:
        tx.execute('INSERT INTO sap_material_observations(fingerprint,kind,scope_json,refresh_seq) VALUES(?,?,?,1) ON CONFLICT(fingerprint,kind,scope_json) DO UPDATE SET refresh_seq=refresh_seq+1', key)
        seq = tx.execute('SELECT refresh_seq FROM sap_material_observations WHERE fingerprint=? AND kind=? AND scope_json=?', key).fetchone()[0]
    # All network and configuration access happens outside workflow transactions.
    failure = None
    data = None
    try:
        sap = service.sap_access_service
        if kind == 'production-order':
            data = sap.production_order(scope['number'], scope['plant'], str(actor.user_id))
            if data.get('number') != scope['number'] or data.get('plant') != scope['plant']:
                failure = error('SAP_SCOPE_MISMATCH')
        else:
            data = sap.stock_requirements(scope['material'], scope['plant'], str(actor.user_id))
            header = data.get('mrp_list') or {}
            if header.get('PLANT') != scope['plant'] or not same_material(header.get('MATERIAL_LONG') or header.get('MATERIAL'), scope['material']):
                failure = error('SAP_SCOPE_MISMATCH')
    except SapAccessError as exc:
        failure = error(exc.code if exc.code in MESSAGES else 'SAP_REFRESH_FAILED')
    except Exception:
        failure = error('SAP_REFRESH_FAILED')
    authorize(service, actor)
    if not service.sap_access_service.configuration_matches(ctx['fingerprint']):
        return dict(snapshot=None, refresh_error=error('SAP_CONFIGURATION_CHANGED'))
    snapshot = None
    if failure is None:
        snapshot = dict(id=str(uuid4()), kind=kind, scope=scope, source=ctx['source'],
                        collected_at=checked_time(service.store.business_clock).isoformat(),
                        data={k:v for k,v in data.items() if k not in {'source','function','request_id'}},
                        request_id=data.get('request_id'))
    with service.store.transaction(write=True) as tx:
        if failure:
            cursor = tx.execute('UPDATE sap_material_observations SET refresh_error_json=? WHERE fingerprint=? AND kind=? AND scope_json=? AND refresh_seq=?', (json.dumps(failure), *key, seq))
        else:
            cursor = tx.execute('UPDATE sap_material_observations SET snapshot_json=?,refresh_error_json=NULL WHERE fingerprint=? AND kind=? AND scope_json=? AND refresh_seq=?', (json.dumps(snapshot), *key, seq))
        result = read_row(tx, key)
        if cursor.rowcount != 1:
            result['refresh_error'] = error('SAP_REFRESH_SUPERSEDED')
    if not service.sap_access_service.configuration_matches(ctx['fingerprint']):
        return dict(snapshot=None, refresh_error=error('SAP_CONFIGURATION_CHANGED'))
    return result

def register_sap_material_routes(router, service, actor):
    async def validate(request, kind=None):
        user = actor(request)
        authorize(service, user)
        expected = set() if kind is None else {'plant', 'number' if kind == 'production-order' else 'material'}
        query = request.query_params
        if set(query) != expected or any(len(query.getlist(k)) != 1 for k in expected):
            raise HTTPException(422, 'Invalid SAP scope')
        if request.method == 'POST':
            async for chunk in request.stream():
                if chunk:
                    raise HTTPException(422, 'Invalid SAP request body')
        scope = dict(query)
        try:
            if kind == 'production-order':
                scope['number'], scope['plant'] = order_scope(scope['number'], scope['plant'])
            elif kind == 'stock-requirements':
                mrp_envelope(scope['material'], scope['plant'])
        except (SapAccessError, ValueError):
            raise HTTPException(422, 'Invalid SAP scope') from None
        return user, scope

    @router.get(PREFIX+'/status')
    async def status(request: Request):
        user, _ = await validate(request)
        ctx, failure = context(service)
        result = dict(configured=ctx is not None, source=ctx['source'] if ctx else None, can_refresh=ctx is not None and not user.read_only)
        if failure and failure['code'] != 'SAP_NOT_CONFIGURED':
            result['refresh_error'] = failure
        return result

    def register(kind):
        async def endpoint(request: Request):
            user, scope = await validate(request, kind)
            return await run_in_threadpool(observe, service, user, kind, scope, request.method == 'POST')
        router.add_api_route(PREFIX+'/'+kind, endpoint, methods=['GET'])
        router.add_api_route(PREFIX+'/'+kind, endpoint, methods=['POST'])
    register('production-order')
    register('stock-requirements')
