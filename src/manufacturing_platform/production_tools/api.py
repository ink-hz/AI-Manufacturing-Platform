"""Seven synchronous GET handlers on the workflow's protected route class."""

import re
from collections.abc import Callable
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Path, Query, Request
from starlette.responses import Response

from ..workflow.contracts import Actor, DomainError
from .contracts import ProductionQuery
from .service import ProductionToolsService
from .source import MAX_ATTACHMENT, error

PREFIX = "/projects/{project_id}/production-tools"


def _query(request, kind, allowed):
    keys = list(request.query_params)
    if set(keys) - allowed or any(
        len(request.query_params.getlist(key)) != 1 for key in keys
    ):
        raise error("SOURCE_INVALID_QUERY", 422)
    values = dict(request.query_params)
    values.pop("kind", None)
    for key in ("parent_id", "before_id"):
        if key in values:
            try:
                text = values[key]
                if not re.fullmatch(r"[1-9][0-9]{0,19}", text):
                    raise ValueError()
                values[key] = int(text)
            except ValueError:
                raise error("SOURCE_INVALID_QUERY", 422) from None
    return ProductionQuery(kind=kind, **values)


def register_production_tools_routes(
    router: APIRouter,
    service: ProductionToolsService,
    actor: Callable[[Request], Actor],
) -> None:
    @router.get(PREFIX + "/status")
    def status(project_id: UUID, request: Request):
        if request.query_params:
            raise error("SOURCE_INVALID_QUERY", 422)
        return service.status(actor(request), project_id)

    @router.get(PREFIX + "/observations")
    def observations(
        project_id: UUID, request: Request, kind: Literal["production", "stopover"]
    ):
        return service.query(
            actor(request),
            project_id,
            _query(
                request,
                kind,
                {"kind", "start", "end", "sn", "order_id", "device", "status"},
            ),
        )

    @router.get(PREFIX + "/catalog/{kind}")
    def catalog(
        project_id: UUID,
        kind: Literal[
            "software",
            "software_versions",
            "configs",
            "config_versions",
            "review_orders",
        ],
        request: Request,
    ):
        return service.query(
            actor(request),
            project_id,
            _query(request, kind, {"parent_id", "before_id"}),
        )

    @router.get(PREFIX + "/evidence")
    def evidence(project_id: UUID, request: Request):
        return service.query(
            actor(request),
            project_id,
            _query(
                request, "evidence", {"start", "end", "sn", "order_id", "before_id"}
            ),
        )

    @router.get(PREFIX + "/statistics")
    def statistics(
        project_id: UUID, request: Request, kind: Literal["production", "stopover"]
    ):
        return service.query(
            actor(request),
            project_id,
            _query(
                request,
                kind + "_statistics",
                {"kind", "start", "end", "sn", "order_id", "device", "status"},
            ),
        )

    @router.get(PREFIX + "/snapshots/{snapshot_id}")
    def snapshot(
        project_id: UUID,
        snapshot_id: UUID,
        request: Request,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ):
        if set(request.query_params) - {"offset", "limit"} or any(
            len(request.query_params.getlist(key)) != 1 for key in request.query_params
        ):
            raise error("SOURCE_INVALID_QUERY", 422)
        return service.snapshot(
            actor(request), project_id, snapshot_id, offset=offset, limit=limit
        )

    @router.get(PREFIX + "/evidence/{source_log_id}/content")
    def content(
        project_id: UUID,
        source_log_id: Annotated[int, Path(ge=1, le=99999999999999999999)],
        request: Request,
    ):
        if request.query_params:
            raise error("SOURCE_INVALID_QUERY", 422)
        current_actor = actor(request)
        binding = service._authorized_binding(current_actor, project_id)
        opened = service.evidence(current_actor, project_id, source_log_id)
        try:
            if opened.size is not None and (
                type(opened.size) is not int or not 0 <= opened.size <= MAX_ATTACHMENT
            ):
                raise error("SOURCE_LIMIT_EXCEEDED", 422)
            data = bytearray()
            while True:
                chunk = opened.stream.read(min(65536, MAX_ATTACHMENT + 1 - len(data)))
                if not isinstance(chunk, bytes):
                    raise error("SOURCE_SCHEMA_INVALID")
                data.extend(chunk)
                if len(data) > MAX_ATTACHMENT:
                    raise error("SOURCE_LIMIT_EXCEEDED", 422)
                if not chunk:
                    break
            if opened.size is not None and len(data) != opened.size:
                raise error("SOURCE_SCHEMA_INVALID")
            filename = quote(opened.filename, safe="")
        except DomainError:
            raise
        except Exception:  # noqa: BLE001 - Sanitize SDK/storage errors at the connector boundary.
            raise error() from None
        finally:
            try:
                opened.stream.close()
            except Exception:  # noqa: BLE001, S110 - SDK cleanup must not expose private errors.
                pass
        service._reauthorize(current_actor, project_id, binding)
        return Response(
            bytes(data),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename=\"evidence.bin\"; filename*=UTF-8''{filename}",
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "private, no-store",
            },
        )
