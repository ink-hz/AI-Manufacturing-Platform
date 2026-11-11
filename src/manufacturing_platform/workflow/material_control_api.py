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
        from .authorization import require_project
        from .contracts import DomainError
        from .material_tasks import eligible
        from uuid import UUID as UserId
        if task_kind not in ('iqc', 'trace'):
            raise DomainError('INVALID_COMMAND', 422, 'Unknown task kind')
        user = actor(request)
        with service.store.transaction() as tx:
            require_project(tx, user, project_id)
            ids = [r[0] for r in tx.execute('SELECT user_id FROM project_grants WHERE project_id=? AND active=1 ORDER BY user_id', (str(project_id),)) if eligible(tx, user, project_id, r[0], task_kind)]
            if user.configuration_admin and str(user.user_id) not in ids:
                ids.append(str(user.user_id))
        items = []
        for start in range(0, len(ids), 50):
            chunk = ids[start:start+50]
            profiles = service.member_profiles(user, project_id, [UserId(i) for i in chunk])
            items.extend({'id': i, 'display_name': profiles[i]} for i in chunk if i in profiles and service.resolve_subject(UserId(i)))
        return {'items': items, 'total': len(items)}
