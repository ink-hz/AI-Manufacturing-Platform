"""Register project routes onto the host's trusted private router."""
from fastapi import HTTPException, Request

from .handbook import Document, read_handbook
from .project_models import ProjectCreate, ProjectUpdate, ProjectStageWrite, ProjectTaskCreate, ProjectTaskWrite
from .project_repository import ProjectRepository


def register_project_routes(router, *, database_path, assets_dir, catalog, release):
    repository = ProjectRepository(database_path, catalog)

    def actor(request):
        identity = request.state.manufacturing_identity
        return identity['user_id'], identity.get('display_name') or identity['user_id']

    @router.get('/dashboard')
    def dashboard():
        return repository.dashboard()

    @router.get('/projects')
    def projects():
        return {'items': repository.list()}

    @router.post('/projects')
    def create_project(value: ProjectCreate, request: Request):
        actor_id, label = actor(request)
        return repository.create(value, actor_id, label)

    @router.get('/projects/{project_id}')
    def project(project_id: str):
        return repository.get(project_id)

    @router.patch('/projects/{project_id}')
    def update_project(project_id: str, value: ProjectUpdate, request: Request):
        return repository.update(project_id, value, actor(request)[1])

    @router.put('/projects/{project_id}/stages/{stage_id}')
    def update_stage(project_id: str, stage_id: str, value: ProjectStageWrite, request: Request):
        return repository.update_stage(project_id, stage_id, value, actor(request)[1])

    @router.post('/projects/{project_id}/tasks')
    def create_task(project_id: str, value: ProjectTaskCreate, request: Request):
        actor_id, label = actor(request)
        return repository.create_task(project_id, value, actor_id, label)

    @router.patch('/projects/{project_id}/tasks/{task_id}')
    def update_task(project_id: str, task_id: str, value: ProjectTaskWrite, request: Request):
        return repository.update_task(project_id, task_id, value, actor(request)[1])

    @router.get('/project-tasks')
    def tasks():
        return {'items': repository.tasks()}

    @router.get('/handbook')
    def handbook(request: Request, document: Document = 'handbook'):
        if any(tag != release for tag in request.query_params.getlist('release')):
            raise HTTPException(409, 'Manufacturing documents changed; reload before continuing')
        try:
            return read_handbook(assets_dir, document, release)
        except (KeyError, TypeError, OSError, ValueError) as exc:
            raise HTTPException(503, 'Manufacturing storage unavailable') from exc
