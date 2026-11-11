"""Fixed, private MES administrator routes with bounded browser input."""
import json
import re

from fastapi import APIRouter, Request

from .._admin_access import private_admin_routes
from .errors import MesAccessError
from .registry import INTERFACES

PREFIX = '/api/v1/manufacturing/mes'
_MAX_BODY_BYTES = 4096


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate key')
        value[key] = item
    return value


async def _validate_request(request):
    if request.scope.get('query_string'):
        raise MesAccessError('MES_INVALID_QUERY', 422)
    interface = request.path_params.get('interface')
    if interface is not None and interface not in INTERFACES:
        raise MesAccessError('MES_INTERFACE_DENIED', 404)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > _MAX_BODY_BYTES:
            raise MesAccessError('MES_INVALID_BODY', 422)
        body.extend(chunk)
    if request.method != 'POST':
        if body:
            raise MesAccessError('MES_INVALID_BODY', 422)
        return
    if not body and interface is None:
        return
    try:
        value = json.loads(body, object_pairs_hook=_unique_object)
        if type(value) is not dict:
            raise ValueError()
        if interface is None:
            if value:
                raise ValueError()
            return
        if set(value) - {'filters', 'page', 'page_size'}:
            raise ValueError()
        filters, page, page_size = value.get('filters', {}), value.get('page', 1), value.get('page_size', 1)
        spec = INTERFACES[interface]
        if (type(filters) is not dict or set(filters) - set(spec.filters)
                or any(type(item) is not str or len(item) > 128 for item in filters.values())
                or any(not filters.get(key, '').strip() for key in spec.required_filters)
                or type(page) is not int or not 1 <= page <= 1_000_000
                or spec.pagination_mode == 'bounded_data' and page != 1
                or type(page_size) is not int or not 1 <= page_size <= 5):
            raise ValueError()
    except (ValueError, UnicodeError, RecursionError):
        raise MesAccessError('MES_INVALID_BODY', 422) from None
    request.state.mes_access_query = (filters, page, page_size)


def build_mes_access_router(*, service, authorize):
    """Build lazily; the trusted host callback enforces session and CSRF policy."""
    private, denied = private_admin_routes(authorize=authorize, error_type=MesAccessError,
        system='MES', validate_request=_validate_request, actor_state='mes_access_actor_id')
    router = APIRouter(prefix=PREFIX, route_class=private)

    @router.get('/status')
    def status():
        return service.status()

    @router.get('/interfaces')
    def interfaces():
        return service.interfaces()

    @router.post('/diagnostics/login')
    def diagnose(request: Request):
        return service.diagnose(request.state.mes_access_actor_id)

    @router.post('/interfaces/{interface}/query')
    def query(interface: str, request: Request):
        filters, page, page_size = request.state.mes_access_query
        return service.query(interface, filters, page, page_size, request.state.mes_access_actor_id)

    def deny(request: Request):
        path = request.path_params.get('mes_path', '')
        known = path in {'status', 'interfaces', 'diagnostics/login'} or re.fullmatch(r'interfaces/[^/]+/query', path)
        raise MesAccessError('MES_METHOD_DENIED' if known else 'MES_ROUTE_DENIED', 405 if known else 404)

    for path in ('', '/{mes_path:path}'):
        router.add_api_route(path, deny, methods=['GET'], include_in_schema=False, route_class_override=denied)
    return router
