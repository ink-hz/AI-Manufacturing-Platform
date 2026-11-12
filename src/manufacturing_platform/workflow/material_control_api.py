from uuid import UUID
from typing import Literal
from fastapi import Request, Query
from .material_control import overview, project_view


def register_material_control_routes(router, service, actor):
    @router.get('/material-control/overview')
    def material_overview(request: Request, limit: int = 50, offset: int = 0):
        return overview(service, actor(request), limit, offset)

    @router.get('/projects/{project_id}/material-control')
    def material_project(project_id: UUID, request: Request, limit: int = 50, offset: int = 0,
                         work_order_id: UUID | None = None, requirement_id: UUID | None = None,
                         search: str = Query(default="", max_length=200),
                         problem: Literal["all", "attention", "shortage", "urgent", "pending_iqc", "unreceived", "verification"] = "all"):
        return project_view(service, actor(request), project_id, limit, offset, work_order_id, requirement_id, search, problem)

    @router.get('/projects/{project_id}/material-task-references')
    def material_task_references(project_id: UUID, request: Request, task_kind: Literal['verify','iqc'] = 'verify',
                                 kind: Literal['all','arrival','mes_component','receipt','source_receipt'] = 'all',
                                 work_order_id: UUID | None = None, requirement_id: UUID | None = None,
                                 search: str = Query(default='', max_length=200), limit: int = 50, offset: int = 0):
        from .material_task_references import reference_page
        return reference_page(service, actor(request), project_id, task_kind=task_kind, kind=kind,
                              work_order_id=work_order_id, requirement_id=requirement_id, search=search,
                              limit=limit, offset=offset)

    @router.get('/projects/{project_id}/material-tasks')
    def project_material_tasks(project_id: UUID, request: Request, limit: int = 50, offset: int = 0):
        from .contracts import ObjectKind
        return service.objects(actor(request), project_id, ObjectKind.material_task, limit=limit, offset=offset)

    @router.get('/material-control/tasks')
    def global_material_tasks(request: Request, project_id: UUID | None = None, limit: int = 50, offset: int = 0):
        from .contracts import ObjectKind
        return service.ledger(actor(request), ObjectKind.material_task, project_id=project_id, limit=limit, offset=offset)

    @router.get('/projects/{project_id}/material-control/assignees')
    def material_task_assignees(project_id: UUID, request: Request, task_kind: str):
        from .contracts import DomainError
        from .material_tasks import assignees
        if task_kind not in ('iqc', 'trace', 'verify'):
            raise DomainError('INVALID_COMMAND', 422, 'Unknown task kind')
        items = assignees(service, actor(request), project_id, task_kind)
        return {'items': items, 'total': len(items)}
