from uuid import UUID
from fastapi import Request
from .material_control import overview, project_view


def register_material_control_routes(router, service, actor):
    @router.get('/material-control/overview')
    def material_overview(request: Request, limit: int = 50, offset: int = 0):
        return overview(service, actor(request), limit, offset)

    @router.get('/projects/{project_id}/material-control')
    def material_project(project_id: UUID, request: Request, limit: int = 50, offset: int = 0,
                         work_order_id: UUID | None = None, requirement_id: UUID | None = None):
        return project_view(service, actor(request), project_id, limit, offset, work_order_id, requirement_id)
