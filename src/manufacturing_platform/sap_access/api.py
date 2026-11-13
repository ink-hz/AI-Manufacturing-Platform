"""Private administrative HTTP boundary for a host-supplied SAP access service."""

import json
import re

from fastapi import APIRouter, Request

from .._admin_access import private_admin_routes
from ..sap_connection import KNOWN_SOAP_FUNCTIONS
from .errors import SapAccessError
from .stock_requirements import envelope

PREFIX = "/api/v1/manufacturing/sap"
_FUNCTIONS = KNOWN_SOAP_FUNCTIONS
_MAX_BODY_BYTES = 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError()
        result[key] = value
    return result


async def _validate_request(request):
    # These operations have no browser-supplied SAP parameters or configuration.
    if request.scope.get("query_string"):
        raise SapAccessError("SAP_INVALID_QUERY", 422)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > _MAX_BODY_BYTES:
            raise SapAccessError("SAP_INVALID_BODY", 422)
        body.extend(chunk)
    if not body:
        if request.url.path == PREFIX + "/mrp/stock-requirements":
            raise SapAccessError("SAP_INVALID_BODY", 422)
        return
    if request.method != "POST":
        raise SapAccessError("SAP_INVALID_BODY", 422)
    try:
        value = json.loads(body, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError):
        raise SapAccessError("SAP_INVALID_BODY", 422) from None
    if request.url.path == PREFIX + '/mrp/stock-requirements':
        try:
            if type(value) is not dict or set(value) != {'material', 'plant'}:
                raise ValueError()
            envelope(value['material'], value['plant'])
        except (ValueError, SapAccessError):
            raise SapAccessError('SAP_INVALID_BODY', 422) from None
        request.state.sap_stock_scope = (value['material'], value['plant'])
    elif type(value) is not dict or value:
        raise SapAccessError("SAP_INVALID_BODY", 422)


def build_sap_access_router(*, service, authorize):
    """Build the fixed SAP routes without configuration, credential or storage I/O."""
    PrivateRoute, DeniedRoute = private_admin_routes(
        authorize=authorize, error_type=SapAccessError, system='SAP',
        validate_request=_validate_request, actor_state='sap_access_actor_id',
    )

    router = APIRouter(prefix=PREFIX, route_class=PrivateRoute)

    @router.get("/status")
    def status():
        return service.status()

    @router.get("/interfaces")
    def interfaces():
        return service.interfaces()

    @router.get("/interfaces/{function}/contract")
    def contract(function: str):
        if function not in _FUNCTIONS:
            raise SapAccessError("SAP_FUNCTION_DENIED", 404)
        return service.contract(function)

    @router.post("/diagnostics/ping")
    def ping(request: Request):
        return service.ping(request.state.sap_access_actor_id)

    @router.post('/mrp/stock-requirements')
    def stock_requirements(request: Request):
        material, plant = request.state.sap_stock_scope
        return service.stock_requirements(material, plant, request.state.sap_access_actor_id)

    @router.post("/interfaces/refresh")
    def refresh(request: Request):
        return service.refresh_contracts(request.state.sap_access_actor_id)

    def deny(request: Request):
        path = request.path_params.get("sap_path", "")
        known_path = path in {
            "status", "interfaces", "diagnostics/ping", "interfaces/refresh", "mrp/stock-requirements"
        } or re.fullmatch(r"interfaces/[^/]+/contract", path)
        if known_path:
            raise SapAccessError("SAP_METHOD_DENIED", 405)
        raise SapAccessError("SAP_ROUTE_DENIED", 404)

    # Include the prefix itself so a slash redirect cannot bypass authorization.
    for path in ("", "/{sap_path:path}"):
        router.add_api_route(
            path, deny, methods=["GET"], include_in_schema=False,
            route_class_override=DeniedRoute,
        )
    return router
