import inspect
import sqlite3
import stat
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response

from ..production_tools.contracts import ProductionToolsConfig
from .assistance import AssistanceKind, AssistanceResult
from .contracts import Actor, DomainError, GrantChange, ObjectKind, ProjectCreate
from .security import log_denial
from .service import WorkflowService
from .store import WorkflowStore

WORKFLOW_API_VERSION = 1


def build_workflow_router(
    *,
    database_path,
    authority_database_path,
    assets_dir,
    authenticate,
    resolve_subject,
    release,
    dataset,
    test_evidence_reader=None,
    resolve_subject_profiles=None,
    business_clock=None,
    production_tools: ProductionToolsConfig | None = None,
):
    store = WorkflowStore(database_path, authority_database_path, dataset, business_clock=business_clock)
    service = WorkflowService(
        store,
        resolve_subject,
        test_evidence_reader=test_evidence_reader,
        resolve_subject_profiles=resolve_subject_profiles,
    )

    class PrivateRoute(APIRoute):
        def get_route_handler(self):
            handler = super().get_route_handler()

            async def private(request):
                denial_code = "PROTOCOL_DENIED"
                authenticated_actor = None
                try:
                    write = request.method not in {"GET", "HEAD", "OPTIONS"}
                    identity = authenticate(request, write=write)
                    if inspect.isawaitable(identity):
                        identity = await identity
                    actor = Actor.model_validate(identity)
                    authenticated_actor = actor
                    if write and actor.read_only:
                        raise HTTPException(403, "Workflow is read-only")
                    request.state.workflow_actor = actor
                    response = await handler(request)
                except DomainError as exc:
                    denial_code = exc.code
                    response = JSONResponse(
                        {
                            "code": exc.code,
                            "message": exc.message,
                            "fields": exc.fields,
                            "blocking_reasons": exc.blocking_reasons,
                        },
                        status_code=exc.status,
                    )
                except (RequestValidationError, ValidationError):
                    response = JSONResponse(
                        {"detail": "Invalid request"}, status_code=422
                    )
                except StarletteHTTPException as exc:
                    response = JSONResponse(
                        {"detail": exc.detail},
                        status_code=exc.status_code,
                        headers=exc.headers,
                    )
                except (sqlite3.Error, OSError, ValueError):
                    import traceback
                    traceback.print_exc()
                    response = JSONResponse(
                        {"detail": "Workflow storage unavailable"}, status_code=503
                    )
                if response.status_code >= 400:
                    request.state.workflow_denial_logged = True
                    log_denial(
                        status=response.status_code,
                        code=denial_code,
                        method=request.method,
                        route=self.path,
                        actor_id=authenticated_actor.user_id
                        if authenticated_actor
                        else None,
                    )
                response.headers["Cache-Control"] = "private, no-store"
                return response

            return private

    router = APIRouter(
        prefix="/api/v1/manufacturing/workflow", route_class=PrivateRoute
    )

    def actor(request):
        return request.state.workflow_actor

    from ..production_tools.api import register_production_tools_routes
    from ..production_tools.service import ProductionToolsService

    try:
        if production_tools is not None:
            from ..production_tools.store import validate_snapshot_path
            validate_snapshot_path(
                production_tools.snapshot_path, (database_path, authority_database_path)
            )
        production_service = ProductionToolsService(
            production_tools, clock=store.business_clock
        )
    except (sqlite3.Error, OSError, ValueError):
        # Optional connector misconfiguration must not disable workflow routes.
        production_service = ProductionToolsService(None, clock=store.business_clock)
    register_production_tools_routes(router, production_service, actor)

    async def parse(request, model):
        try:
            return model.model_validate(await request.json())
        except (ValueError, ValidationError):
            raise HTTPException(422, "Invalid request")

    @router.get("/access")
    def access(request: Request):
        a = actor(request)
        ids = service.project_ids(a)
        workflow_access = bool(ids) or a.configuration_admin
        legacy_access = a.configuration_admin
        return {
            "allowed": legacy_access or workflow_access,
            "available": True,
            "workflow_available": True,
            "can_edit": not a.read_only,
            "release": release,
            "protocol": 1,
            "legacy_access": legacy_access,
            "workflow_access": workflow_access,
            "configuration_admin": a.configuration_admin,
            "dataset": dataset,
            "user": {"id": str(a.user_id), "display_name": a.display_name},
            "project_ids": ids,
        }

    @router.get("/projects")
    def projects(request: Request):
        a = actor(request)
        return {
            "items": [
                service.detail(a, p, include_progress=False).model_dump(mode="json")
                for p in service.project_ids(a)
            ]
        }

    @router.post("/projects")
    async def create(request: Request):
        a = actor(request)
        if not a.configuration_admin:
            raise HTTPException(403, "Permission denied")
        return service.create_project(a, await parse(request, ProjectCreate))

    @router.get("/projects/{project_id}")
    def detail(project_id: UUID, request: Request):
        return service.detail(actor(request), project_id)

    @router.get("/projects/{project_id}/members")
    def members(
        project_id: UUID,
        request: Request,
        limit: int = 50,
        offset: int = 0,
        user_id: UUID | None = None,
    ):
        return {
            "items": service.members(
                actor(request), project_id, limit=limit, offset=offset, user_id=user_id
            )
        }

    @router.put("/projects/{project_id}/members/{user_id}")
    async def grant(project_id: UUID, user_id: UUID, request: Request):
        a = actor(request)
        if not a.configuration_admin:
            raise HTTPException(403, "Permission denied")
        value = await parse(request, GrantChange)
        return await run_in_threadpool(service.change_grant, a, project_id, user_id, value)

    @router.get("/projects/{project_id}/assistance", response_model=AssistanceResult)
    def assistance(project_id: UUID, request: Request, kind: AssistanceKind):
        return service.assistance(actor(request), project_id, kind)

    @router.get("/reusable-assets")
    def reusable_assets(request: Request, limit: int = 50, offset: int = 0):
        return service.reusable_assets(actor(request), limit=limit, offset=offset)

    @router.get("/dashboard")
    def dashboard(request: Request, project_id: UUID | None = None):
        return service.dashboard(actor(request), project_id)

    @router.get("/objects/{kind}")
    def ledger(
        kind: ObjectKind, request: Request, limit: int = 50, offset: int = 0,
        project_id: UUID | None = None,
    ):
        return service.ledger(
            actor(request), kind, limit=limit, offset=offset, project_id=project_id
        )

    @router.get("/tasks")
    def tasks(
        request: Request, limit: int = 50, offset: int = 0,
        project_id: UUID | None = None,
    ):
        return service.tasks(
            actor(request), limit=limit, offset=offset, project_id=project_id
        )

    @router.get("/projects/{project_id}/objects/{kind}")
    def objects(
        project_id: UUID,
        kind: ObjectKind,
        request: Request,
        limit: int = 50,
        offset: int = 0,
        requirement_id: UUID | None = None,
    ):
        if not 1 <= limit <= 200 or offset < 0:
            raise HTTPException(422, "Invalid pagination")
        return service.objects(
            actor(request), project_id, kind, limit=limit, offset=offset,
            requirement_id=requirement_id,
        )

    @router.get("/projects/{project_id}/objects/{kind}/{object_id}")
    def object_detail(
        project_id: UUID, kind: ObjectKind, object_id: UUID, request: Request
    ):
        return service.object_detail(actor(request), project_id, kind, object_id)

    @router.post("/projects/{project_id}/commands")
    async def command(project_id: UUID, request: Request):
        service.detail(actor(request), project_id, include_progress=False)
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(422, "Invalid request")
        return await run_in_threadpool(
            service.execute, actor(request), project_id, payload
        )

    @router.get("/projects/{project_id}/exchanges")
    def exchanges(project_id: UUID, request: Request, limit: int = 50, offset: int = 0):
        return service.objects(
            actor(request), project_id, ObjectKind.exchange, limit=limit, offset=offset
        )

    @router.get("/projects/{project_id}/integration-intents")
    def integration_intents(project_id: UUID, request: Request, limit: int = 50, offset: int = 0):
        return service.integration_intents(actor(request), project_id, limit=limit, offset=offset)

    @router.get("/projects/{project_id}/integration-links")
    def integration_links(
        project_id: UUID,
        target_kind: ObjectKind,
        target_id: UUID,
        request: Request,
        cursor: int = 0,
        limit: int = 50,
    ):
        return service.integration_links(
            actor(request),
            project_id,
            target_kind,
            target_id,
            cursor=cursor,
            limit=limit,
        )

    @router.get("/projects/{project_id}/systems")
    def integration_systems(project_id: UUID, request: Request):
        return service.integration_systems(actor(request), project_id)

    @router.get("/projects/{project_id}/systems/{system}/facts")
    def integration_facts(
        project_id: UUID,
        system: str,
        object_type: str,
        request: Request,
        cursor: int = 0,
        limit: int = 50,
    ):
        return service.integration_facts(
            actor(request), project_id, system, object_type, cursor=cursor, limit=limit
        )

    @router.get(
        "/projects/{project_id}/systems/{system}/facts/{object_type}/{external_id}"
    )
    def integration_fact(
        project_id: UUID,
        system: str,
        object_type: str,
        external_id: str,
        request: Request,
        version: int,
    ):
        from .integrations.contracts import SourceKey

        return service.integration_fact(
            actor(request),
            project_id,
            SourceKey(
                system=system,
                object_type=object_type,
                external_id=external_id,
                version=version,
            ),
        )

    @router.get("/projects/{project_id}/systems/product_test/artifacts/{artifact_id}")
    def integration_artifact(project_id: UUID, artifact_id: UUID, request: Request):
        from .integrations.core_models import SourceKey

        user = actor(request)
        detail = service.integration_fact(
            user,
            project_id,
            SourceKey(
                system="product_test",
                object_type="artifact",
                external_id=str(artifact_id),
                version=1,
            ),
        )
        prepared = detail.fact.payload.prepared
        content = service.integration_artifact(
            user, project_id, prepared.artifact_ref, prepared.artifact_checksum
        )
        return Response(
            content,
            media_type="application/json",
            headers={
                "ETag": '"' + prepared.artifact_checksum + '"',
                "Content-Disposition": f'attachment; filename="artifact-{artifact_id}.json"',
            },
        )

    @router.get("/projects/{project_id}/trace")
    def trace(project_id: UUID, request: Request, sn: str | None = None, material_lot_id: UUID | None = None, limit: int = 500):
        return service.trace(actor(request), project_id, sn=sn, material_lot_id=material_lot_id, limit=limit)

    @router.get("/assets/{asset_name}")
    def assets(asset_name: str, request: Request):
        a = actor(request)
        if not a.configuration_admin and not service.project_ids(a):
            raise HTTPException(403, "Permission denied")
        types = {"manufacturing.js": "text/javascript", "manufacturing.css": "text/css"}
        if asset_name not in types:
            raise HTTPException(404, "Asset not found")
        if request.query_params.getlist("release") != [release]:
            raise HTTPException(409, "Assets changed")
        root = Path(assets_dir).resolve()
        target = (root / asset_name).resolve()
        if not target.is_relative_to(root):
            raise HTTPException(404, "Asset not found")
        if not stat.S_ISREG(target.stat().st_mode):
            raise HTTPException(404, "Asset not found")
        return Response(target.read_bytes(), media_type=types[asset_name])

    @router.get("/handbook")
    def handbook(request: Request):
        a = actor(request)
        if not a.configuration_admin and not service.project_ids(a):
            raise HTTPException(403, "Permission denied")
        from ..handbook import read_handbook

        return read_handbook(assets_dir, "handbook", release)

    return router
