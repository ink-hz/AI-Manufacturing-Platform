"""Strict project inputs and validated durable project snapshots."""
from datetime import date
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from .catalog import Identifier
from .models import Model, RecordContent, Participant, Handoff, SystemRelationship

Name = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)]
Text = Annotated[str, StringConstraints(strict=True, max_length=200)]
Summary = Annotated[str, StringConstraints(strict=True, max_length=6000)]
Title = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=300)]
Version = Annotated[int, Field(strict=True, ge=1)]
Quantity = Annotated[int, Field(strict=True, ge=1, le=1_000_000_000)]
Status = Literal['todo', 'doing', 'blocked', 'done']
Kind = Literal['task', 'issue', 'confirmation']
Priority = Literal['normal', 'high', 'urgent']


class Dated(Model):
    @field_validator('due_date', mode='before', check_fields=False)
    @classmethod
    def calendar_date(cls, value):
        if value is not None and not (isinstance(value, date) or isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)):
            raise ValueError('Expected a calendar date')
        return value


class ProjectCreate(Dated):
    operation_id: UUID
    name: Name
    line_id: Identifier
    owner: Name
    product: Text = ''
    customer: Text = ''
    due_date: date | None = None
    target_quantity: Quantity | None = None
    summary: Summary = ''


class ProjectUpdate(Dated):
    expected_version: Version
    # Nonnullable annotations reject explicit null; omitted fields are excluded.
    name: Name = None
    owner: Name = None
    product: Text = None
    customer: Text = None
    due_date: date | None = None
    target_quantity: Quantity | None = None
    summary: Summary = None
    archived: Annotated[bool, Field(strict=True)] = None


class StageContent(RecordContent, Dated):
    status: Status
    owner: Text
    due_date: date | None
    blocker: Annotated[str, StringConstraints(strict=True, max_length=2000)]

    @model_validator(mode='after')
    def blocked_reason(self):
        if self.status == 'blocked' and not self.blocker.strip():
            raise ValueError('Blocked stages require a reason')
        return self


class ProjectStageWrite(StageContent):
    expected_version: Version


class ProjectTaskCreate(Dated):
    operation_id: UUID
    stage_id: Identifier
    title: Title
    kind: Kind = 'task'
    owner: Text = ''
    due_date: date | None = None
    priority: Priority = 'normal'
    notes: Summary = ''


class ProjectTaskWrite(Dated):
    expected_version: Version
    stage_id: Identifier = None
    title: Title = None
    kind: Kind = None
    owner: Text = None
    due_date: date | None = None
    priority: Priority = None
    notes: Summary = None
    status: Status = None


class ProjectStage(StageContent):
    id: Identifier
    name: str
    purpose: str
    help: str
    prompts: list[str]
    reference_participants: list[Participant]
    reference_handoffs: list[Handoff]
    reference_systems: list[SystemRelationship]
    version: Version
    updated_at: str
    updated_by: str


class ProjectTask(Dated):
    id: str
    project_id: str
    stage_id: Identifier
    title: Title
    kind: Kind
    owner: Text
    due_date: date | None
    priority: Priority
    notes: Summary
    status: Status
    version: Version
    created_at: str
    updated_at: str
    updated_by: str


class ProjectSummary(Dated):
    id: str
    code: str
    name: Name
    line_id: Identifier
    line_name: str
    group_id: Identifier
    owner: Name
    product: Text
    customer: Text
    due_date: date | None
    target_quantity: Quantity | None
    summary: Summary
    archived: Annotated[bool, Field(strict=True)]
    version: Version
    created_at: str
    updated_at: str
    updated_by: str
    status: Literal['planned', 'active', 'blocked', 'completed', 'archived']
    current_stage_id: str
    current_stage_name: str
    completed_stages: Annotated[int, Field(strict=True, ge=0)]
    total_stages: Annotated[int, Field(strict=True, ge=1)]
    open_tasks: Annotated[int, Field(strict=True, ge=0)]


class Activity(Model):
    id: str
    created_at: str
    actor: str
    action: str
    summary: str
    stage_id: str | None
    task_id: str | None


class ProjectDetail(Model):
    project: ProjectSummary
    stages: Annotated[list[ProjectStage], Field(min_length=1)]
    tasks: list[ProjectTask]
    activity: list[Activity]
