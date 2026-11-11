"""Requirement-specific, append-only material need times."""
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime

from .commands import COMMAND_REGISTRY, WorkflowCommand
from .contracts import MutationResult, StrictModel
from .introduction_models import Text
from .orders import own
from .quality import fail


SCHEMA = """
CREATE TABLE IF NOT EXISTS material_need_time_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),requirement_id TEXT NOT NULL REFERENCES requirements(id),plan_id TEXT NOT NULL REFERENCES plans(id),need_at TEXT,evidence TEXT NOT NULL,actor_id TEXT NOT NULL,recorded_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS material_need_time_scope ON material_need_time_events(project_id,requirement_id,seq);
"""


class SetMaterialNeedTime(WorkflowCommand):
    action: Literal['material.need_time']
    requirement_id: UUID
    need_at: AwareDatetime | None
    evidence: Text


class MaterialNeedTimeEvent(StrictModel):
    id: UUID
    requirement_id: UUID
    plan_id: UUID
    need_at: AwareDatetime | None
    evidence: str
    actor_id: UUID
    recorded_at: AwareDatetime


def events(tx, project_id, requirement_id):
    return [dict(row) for row in tx.execute(
        'SELECT id,requirement_id,plan_id,need_at,evidence,actor_id,recorded_at FROM material_need_time_events WHERE project_id=? AND requirement_id=? ORDER BY seq',
        (str(project_id), str(requirement_id)))]


def set_need_time(tx, context, command):
    from .supply import current_plan_id
    req = own(tx, 'requirements', context.project_id, command.requirement_id)
    if req['plan_id'] != current_plan_id(tx, context.project_id, req['work_order_id']):
        fail('Need time requires the current confirmed requirement')
    ident = str(uuid4())
    tx.execute('INSERT INTO material_need_time_events(id,project_id,requirement_id,plan_id,need_at,evidence,actor_id,recorded_at) VALUES (?,?,?,?,?,?,?,?)',
        (ident, str(context.project_id), str(command.requirement_id), req['plan_id'], command.need_at.isoformat() if command.need_at else None, command.evidence, str(context.actor.user_id), context.now.isoformat()))
    return MutationResult(object_type='requirement', object_id=str(command.requirement_id))


COMMAND_REGISTRY.register(SetMaterialNeedTime, roles={'project_owner', 'planner', 'supply'}, qualifications=set(), handler=set_need_time)
