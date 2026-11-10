"""Protected, bounded investigation HTTP handlers."""

import json
from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from ..workflow.contracts import Actor
from .api import BASE, PREFIX, SourceId
from .source import error


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate field')
        result[key] = value
    return result


async def _body(request):
    if request.query_params:
        raise error('SOURCE_INVALID_QUERY', 422)
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > 32768:
            raise error('SOURCE_INVALID_QUERY', 422)
    try:
        value = json.loads(payload, object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value, dict):
            raise ValueError('object required')
        return value
    except (ValueError, TypeError, RecursionError):
        raise error('SOURCE_INVALID_QUERY', 422) from None


def _no_query(request):
    if request.query_params:
        raise error('SOURCE_INVALID_QUERY', 422)


def register_investigation_routes(router: APIRouter, service, actor: Callable[[Request], Actor]):
    path = PREFIX + '/investigations'

    @router.get(path)
    def list_drafts(source_project_id: SourceId, request: Request):
        _no_query(request)
        return service.list(actor(request), source_project_id)

    @router.post(path)
    async def create(source_project_id: SourceId, request: Request):
        current = actor(request)
        service.production._authorize(current)
        body = await _body(request)
        return await run_in_threadpool(service.create, current, source_project_id, body)

    @router.get(path + '/{investigation_id}')
    def get(source_project_id: SourceId, investigation_id: UUID, request: Request):
        _no_query(request)
        return service.get(actor(request), source_project_id, investigation_id)

    @router.put(path + '/{investigation_id}')
    async def update(source_project_id: SourceId, investigation_id: UUID, request: Request):
        current = actor(request)
        service.production._authorize(current)
        body = await _body(request)
        return await run_in_threadpool(service.update, current, source_project_id, investigation_id, body)

    @router.get(path + '/{investigation_id}/resolve')
    def resolve(source_project_id: SourceId, investigation_id: UUID, request: Request):
        _no_query(request)
        return service.resolve(actor(request), source_project_id, investigation_id)

    @router.post(path + '/{investigation_id}/handoffs')
    async def handoff(source_project_id: SourceId, investigation_id: UUID, request: Request):
        current = actor(request)
        service.production._authorize(current)
        body = await _body(request)
        return await run_in_threadpool(service.create_handoff, current, source_project_id, investigation_id, body)

    @router.get(BASE + '/handoffs/{handoff_id}')
    def get_handoff(handoff_id: UUID, request: Request):
        _no_query(request)
        return service.get_handoff(actor(request), handoff_id)

    @router.get(BASE + '/handoffs/{handoff_id}/resolve')
    def resolve_handoff(handoff_id: UUID, request: Request):
        _no_query(request)
        return service.resolve_handoff(actor(request), handoff_id)

    @router.post(BASE + '/handoffs/{handoff_id}/fork')
    async def fork(handoff_id: UUID, request: Request):
        current = actor(request)
        service.production._authorize(current)
        body = await _body(request)
        return await run_in_threadpool(service.fork, current, handoff_id, body)
