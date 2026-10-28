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
):
    store = WorkflowStore(database_path, authority_database_path, dataset)
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
                service.detail(a, p).model_dump(mode="json")
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
        return service.change_grant(
            a, project_id, user_id, await parse(request, GrantChange)
        )

    @router.get("/dashboard")
    def dashboard(request: Request, project_id: UUID | None = None):
        return service.dashboard(actor(request), project_id)

    @router.get("/projects/{project_id}/objects/{kind}")
    def objects(
        project_id: UUID,
        kind: ObjectKind,
        request: Request,
        limit: int = 50,
        offset: int = 0,
    ):
        if not 1 <= limit <= 200 or offset < 0:
            raise HTTPException(422, "Invalid pagination")
        return service.objects(
            actor(request), project_id, kind, limit=limit, offset=offset
        )

    @router.get("/projects/{project_id}/objects/{kind}/{object_id}")
    def object_detail(
        project_id: UUID, kind: ObjectKind, object_id: UUID, request: Request
    ):
        return service.object_detail(actor(request), project_id, kind, object_id)

    @router.post("/projects/{project_id}/commands")
    async def command(project_id: UUID, request: Request):
        service.detail(actor(request), project_id)
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

    @router.get("/projects/{project_id}/trace")
    def unavailable_project(project_id: UUID, request: Request):
        service.detail(actor(request), project_id)
        raise HTTPException(503, "Workflow feature unavailable")

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
