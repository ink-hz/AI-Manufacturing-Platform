"""Typed commands and durable material collaboration projections."""
from datetime import date
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, model_serializer, model_validator
from .commands import WorkflowCommand
from .contracts import DomainValue, NonnegativeQuantity, SourceRef, StrictModel
from .introduction_models import Name, Text
from .material_task_reference_models import TaskReference, TaskReferenceEvidence

class OpenMaterialTask(WorkflowCommand):
    action: Literal['material_task.open']
    requirement_id: UUID | None = None
    task_kind: Literal['iqc', 'trace', 'verify']
    reference: TaskReference | None = None
    receipt_id: UUID | None = None
    handoff_id: UUID | None = None
    assignee_id: UUID
    note: Text

    @model_validator(mode='after')
    def distinct_reference_fields(self):
        if self.task_kind == 'verify' and self.reference is None:
            raise ValueError('verify requires a typed reference')
        if self.reference is not None and (self.receipt_id is not None or self.handoff_id is not None):
            raise ValueError('reference and legacy target fields cannot be mixed')
        return self

    @model_serializer(mode='wrap')
    def serialize_legacy(self, handler):
        data = handler(self)
        if self.reference is None:
            data.pop('reference', None)
        return data

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
    outcome: Literal['fulfilled', 'discrepancy', 'false_alarm', 'superseded', 'identity_verified', 'unable_to_verify', 'incorrect_observation']
    evidence: Text
    handoff_ids: list[UUID] = Field(default_factory=list, max_length=50)
    resolved_reference: TaskReference | None = None

    @model_validator(mode='after')
    def verification_lifecycle_pending(self):
        # Kind-specific close dispatch is introduced in the next task. Until then,
        # never let the legacy close handler treat verification as a legacy outcome.
        if self.outcome in {'identity_verified', 'unable_to_verify', 'incorrect_observation'} or self.resolved_reference is not None:
            raise ValueError('verification close is not yet available')
        return self

    @model_serializer(mode='wrap')
    def serialize_legacy(self, handler):
        data = handler(self)
        if self.resolved_reference is None:
            data.pop('resolved_reference', None)
        return data

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
    resolved_reference: TaskReference | None = None

class MaterialTask(DomainValue):
    kind: Literal['material_task'] = 'material_task'
    id: UUID
    requirement_id: UUID | None
    task_kind: Literal['iqc','trace','verify']
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
    reference: TaskReferenceEvidence | None = None
    closure: dict | None = None
    context_requirement_ids: list[UUID] = Field(default_factory=list)
    reference_pinned: bool = False
    reference_current: bool | None = None
    current_reference: TaskReference | None = None
    reference_issue: str | None = None
