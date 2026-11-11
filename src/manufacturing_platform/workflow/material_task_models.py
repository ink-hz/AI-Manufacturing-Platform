"""Typed commands and durable material collaboration projections."""
from datetime import date
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field
from .commands import WorkflowCommand
from .contracts import DomainValue, NonnegativeQuantity, SourceRef, StrictModel
from .introduction_models import Name, Text

class OpenMaterialTask(WorkflowCommand):
    action: Literal['material_task.open']
    requirement_id: UUID
    task_kind: Literal['iqc', 'trace']
    receipt_id: UUID | None = None
    handoff_id: UUID | None = None
    assignee_id: UUID
    note: Text

class AcceptMaterialTask(WorkflowCommand):
    action: Literal['material_task.accept']
    task_id: UUID

class ReassignMaterialTask(WorkflowCommand):
    action: Literal['material_task.reassign']
    task_id: UUID
    assignee_id: UUID
    reason: Text

class ProgressMaterialTask(WorkflowCommand):
    action: Literal['material_task.progress']
    task_id: UUID
    note: Text
    expected_completion: AwareDatetime | None = None
    blocked_reason: Text | None = None
    found_quantity: NonnegativeQuantity | None = None
    found_location: Name | None = None

class VerifyMaterialTask(WorkflowCommand):
    action: Literal['material_task.verify']
    task_id: UUID
    evidence: Text
    handoff_ids: list[UUID] = Field(default_factory=list, max_length=50)

class CloseMaterialTask(WorkflowCommand):
    action: Literal['material_task.close']
    task_id: UUID
    outcome: Literal['fulfilled', 'discrepancy', 'false_alarm', 'superseded']
    evidence: Text
    handoff_ids: list[UUID] = Field(default_factory=list, max_length=50)

class CancelMaterialTask(WorkflowCommand):
    action: Literal['material_task.cancel']
    task_id: UUID
    reason: Text

class TaskHistory(StrictModel):
    action: str
    actor_id: UUID
    actor_name: Name
    recorded_at: AwareDatetime
    note: Text | None = None
    reason: Text | None = None
    evidence: Text | None = None
    outcome: str | None = None
    assignee_id: UUID | None = None
    expected_completion: AwareDatetime | date | None = None
    blocked_reason: Text | None = None
    found_quantity: NonnegativeQuantity | None = None
    found_location: Name | None = None
    handoff_ids: list[UUID] | None = None

class MaterialTask(DomainValue):
    kind: Literal['material_task'] = 'material_task'
    id: UUID
    requirement_id: UUID
    task_kind: Literal['iqc','trace']
    receipt_id: UUID | None
    handoff_id: UUID | None
    assignee_id: UUID
    proposed_assignee_id: UUID | None
    state: Literal['pending','processing','verification','closed','cancelled']
    note: Text
    opened_by: UUID
    recorded_at: AwareDatetime
    source: SourceRef
    history: list[TaskHistory]
    evidence_handoff_ids: list[UUID]
