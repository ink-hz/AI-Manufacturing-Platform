"""Host-independent routes. Authorization precedes body parsing and all I/O."""
import inspect
from pathlib import Path
import sqlite3

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response
from starlette.routing import Match

from .catalog import load_catalog
from .models import RecordWrite, TaskCreate, TaskWrite
from .repository import Conflict, NotFound, Repository
from .project_api import register_project_routes


def build_router(*, database_path: str, assets_dir: str, authorize, release: str = 'development'):
    """Build routes using a trusted host callback; the host enforces session/CSRF.

    ``authorize(request, write=False)`` returns user_id, display_name, read_only.
    ``updated_by`` is its display_name string (falling back to stable user_id).
    Creating a router performs no database or asset I/O.
    """
    catalog = load_catalog()
    repository = Repository(database_path)

    class PrivateRoute(APIRoute):
        def get_route_handler(self):
            handler = super().get_route_handler()

            async def private_handler(request: Request):
                try:
                    write = request.method not in {'GET', 'HEAD', 'OPTIONS'}
                    identity = authorize(request, write=write)
                    if inspect.isawaitable(identity):
                        identity = await identity
                    if write and identity['read_only']:
                        raise HTTPException(403, 'Manufacturing is read-only')
                    request.state.manufacturing_identity = identity
                    response = await handler(request)
                except RequestValidationError:
                    response = JSONResponse({'detail': 'Invalid request'}, status_code=422)
                except StarletteHTTPException as exc:
                    detail = 'Invalid request' if exc.status_code == 400 else exc.detail
                    response = JSONResponse({'detail': detail}, status_code=exc.status_code, headers=exc.headers)
                except Conflict:
                    response = JSONResponse({'detail': 'Manufacturing data changed; reload before saving'}, status_code=409)
                except (KeyError, NotFound):
                    response = JSONResponse({'detail': 'Manufacturing resource not found'}, status_code=404)
                except (sqlite3.Error, OSError, ValueError):
                    response = JSONResponse({'detail': 'Manufacturing storage unavailable'}, status_code=503)
                response.headers['Cache-Control'] = 'private, no-store'
                return response

            return private_handler

    router = APIRouter(prefix='/api/v1/manufacturing', route_class=PrivateRoute)

    def identity(request):
        return request.state.manufacturing_identity

    def can_edit(request):
        return not identity(request)['read_only']

    def actor_label(request):
        actor = identity(request)
        return actor.get('display_name') or actor['user_id']

    @router.get('/access')
    def access(request: Request):
        return {'allowed': True, 'can_edit': can_edit(request), 'available': True, 'release': release}

    @router.get('/health')
    def health():
        repository.health()
        return {'ready': True, 'release': release}

    @router.get('/catalog')
    def get_catalog(request: Request):
        return {**catalog.public(), 'can_edit': can_edit(request), 'release': release}

    @router.get('/lines/{line_id}')
    def get_line(line_id: str, request: Request):
        line = catalog.line(line_id)
        indicators = repository.overview(line_id)
        stages = [{**stage, **indicators.get(stage['id'], {'recorded': False, 'open_tasks': 0})} for stage in catalog.line_stages(line_id)]
        return {'line': line, 'stages': stages, 'can_edit': can_edit(request)}

    @router.get('/lines/{line_id}/stages/{stage_id}')
    def get_stage(line_id: str, stage_id: str, request: Request):
        stage = catalog.stage(line_id, stage_id)
        return {'line': catalog.line(line_id), 'stage': stage, **repository.read_stage(line_id, stage_id), 'can_edit': can_edit(request)}

    @router.put('/lines/{line_id}/stages/{stage_id}')
    def save_stage(line_id: str, stage_id: str, value: RecordWrite, request: Request):
        catalog.stage(line_id, stage_id)
        return repository.save_record(line_id, stage_id, value, actor_label(request))

    @router.post('/lines/{line_id}/stages/{stage_id}/tasks')
    def create_task(line_id: str, stage_id: str, value: TaskCreate, request: Request):
        catalog.stage(line_id, stage_id)
        return repository.create_task(line_id, stage_id, value, identity(request)['user_id'], actor_label(request))

    @router.patch('/lines/{line_id}/stages/{stage_id}/tasks/{task_id}')
    def update_task(line_id: str, stage_id: str, task_id: str, value: TaskWrite, request: Request):
        catalog.stage(line_id, stage_id)
        return repository.update_task(line_id, stage_id, task_id, value, actor_label(request))

    @router.get('/assets/{asset_name}')
    def asset(asset_name: str, request: Request):
        media_types = {'manufacturing.js': 'text/javascript', 'manufacturing.css': 'text/css'}
        if asset_name not in media_types:
            raise HTTPException(404, 'Manufacturing asset not found')
        if any(tag != release for tag in request.query_params.getlist('release')):
            raise HTTPException(409, 'Manufacturing assets changed; reload before continuing')
        root = Path(assets_dir).resolve()
        target = (root / asset_name).resolve()
        if target.parent != root or not target.is_file():
            raise HTTPException(404, 'Manufacturing asset not found')
        return Response(target.read_bytes(), media_type=media_types[asset_name])

    register_project_routes(router, database_path=database_path, assets_dir=assets_dir, catalog=catalog, release=release)

    # Match only this prefix after all business routes. The fallback authorizes
    # and returns errors; it cannot invoke a business handler or serve an asset.
    business_routes = tuple(router.routes)

    class PrivateFallbackRoute(PrivateRoute):
        def matches(self, scope):
            match, child_scope = super().matches(scope)
            return (Match.FULL if match == Match.PARTIAL else match), child_scope

        async def handle(self, scope, receive, send):
            # Even unregistered HTTP methods must enter the private wrapper.
            await self.app(scope, receive, send)

    def unmatched(request: Request):
        allowed_methods = set()
        for route in business_routes:
            match, _ = route.matches(request.scope)
            if match != Match.NONE:
                allowed_methods.update(route.methods or ())
        if allowed_methods:
            raise HTTPException(405, 'Method not allowed', headers={'Allow': ', '.join(sorted(allowed_methods))})
        raise HTTPException(404, 'Manufacturing resource not found')

    for path in ('', '/{unmatched_path:path}'):
        router.add_api_route(path, unmatched, methods=['GET'], include_in_schema=False, route_class_override=PrivateFallbackRoute)

    return router
