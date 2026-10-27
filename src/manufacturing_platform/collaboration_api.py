"""Collaboration routes registered inside the existing protected route boundary."""
import json
from fastapi import Query, Request
from .collaboration_models import (SystemCreate, SystemPatch, AuthorityCreate, AuthorityPatch,
    PackageCreate, PackageWrite, PackageAction, HandoffCreate, HandoffAction,
    ReadinessCreate, ReadinessWrite, IssueCreate)
from .systems import SystemService
from .engineering import EngineeringService
from .readiness import ReadinessService
from .collaboration_queries import attention


def register_collaboration_routes(router, *, database_path, catalog):
    systems = SystemService(database_path,catalog)
    engineering = EngineeringService(database_path,catalog)
    readiness = ReadinessService(database_path,catalog)

    def actor(request):
        identity = request.state.manufacturing_identity
        return identity['user_id'],identity.get('display_name') or identity['user_id']

    @router.get('/collaboration')
    def collaboration():
        with systems._connection() as db:
            names = {row[0]:json.loads(row[1])['project']['name'] for row in db.execute('SELECT id,body FROM manufacturing_projects')}
            handoffs = [{**row,'project_name':names[row['project_id']]} for row in systems.rows(db,'handoffs')]
            return {'systems':systems.rows(db,'systems'),'authorities':systems.rows(db,'authorities'),'handoffs':handoffs,'attention':attention(db)}

    @router.post('/systems')
    def create_system(value:SystemCreate, request:Request):
        return systems.system(value,*actor(request))

    @router.patch('/systems/{system_id}')
    def update_system(system_id:str,value:SystemPatch,request:Request):
        return systems.system(value,*actor(request),system_id=system_id)

    @router.post('/authorities')
    def create_authority(value:AuthorityCreate,request:Request):
        return systems.authority(value,*actor(request))

    @router.patch('/authorities/{authority_id}')
    def update_authority(authority_id:str,value:AuthorityPatch,request:Request):
        return systems.authority(value,*actor(request),authority_id=authority_id)

    @router.get('/projects/{project_id}/controls')
    def controls(project_id:str,limit:int=Query(100,ge=1,le=1000),offset:int=Query(0,ge=0)):
        with systems._connection() as db:
            systems._read(db,project_id)
            events = [json.loads(row[0]) for row in db.execute('SELECT body FROM manufacturing_control_events WHERE project_id=? ORDER BY sequence DESC LIMIT ? OFFSET ?',(project_id,limit,offset))]
            return {**{kind:systems.rows(db,kind,project_id) for kind in ('packages','handoffs','readiness')},'events':events}

    @router.post('/projects/{project_id}/packages')
    def create_package(project_id:str,value:PackageCreate,request:Request):
        return engineering.package(project_id,value,*actor(request))

    @router.put('/projects/{project_id}/packages/{package_id}')
    def update_package(project_id:str,package_id:str,value:PackageWrite,request:Request):
        return engineering.package(project_id,value,*actor(request),package_id=package_id)

    @router.post('/projects/{project_id}/packages/{package_id}/actions')
    def package_action(project_id:str,package_id:str,value:PackageAction,request:Request):
        return engineering.package_action(project_id,package_id,value,*actor(request))

    @router.post('/projects/{project_id}/handoffs')
    def create_handoff(project_id:str,value:HandoffCreate,request:Request):
        return engineering.handoff(project_id,value,*actor(request))

    @router.patch('/projects/{project_id}/handoffs/{handoff_id}')
    def handoff_action(project_id:str,handoff_id:str,value:HandoffAction,request:Request):
        return engineering.handoff_action(project_id,handoff_id,value,*actor(request))

    @router.post('/projects/{project_id}/readiness')
    def create_readiness(project_id:str,value:ReadinessCreate,request:Request):
        return readiness.readiness(project_id,value,*actor(request))

    @router.put('/projects/{project_id}/readiness/{readiness_id}')
    def update_readiness(project_id:str,readiness_id:str,value:ReadinessWrite,request:Request):
        return readiness.readiness(project_id,value,*actor(request),readiness_id=readiness_id)

    @router.post('/projects/{project_id}/readiness/{readiness_id}/issues')
    def create_issue(project_id:str,readiness_id:str,value:IssueCreate,request:Request):
        return readiness.issue(project_id,readiness_id,value,*actor(request))
