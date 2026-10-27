"""Validated business input and persisted read models, independent of the host app."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(strict=True, max_length=500)]
Name = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=500)]
Title = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=300)]
Version = Annotated[int, Field(strict=True, ge=0)]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Participant(Model):
    name: Name
    role: Text = ''
    responsibility: Text = ''


class Handoff(Model):
    name: Name
    from_party: Text = ''
    to_party: Text = ''
    version_reference: Text = ''
    notes: Text = ''


class SystemRelationship(Model):
    name: Name
    kind: Text = ''
    objects: Text = ''
    maintainer: Text = ''
    method: Literal['unknown', 'manual', 'file', 'api'] = 'unknown'
    notes: Text = ''


class RecordContent(Model):
    practice: Annotated[str, StringConstraints(strict=True, max_length=12000)]
    participants: Annotated[list[Participant], Field(max_length=20)]
    handoffs: Annotated[list[Handoff], Field(max_length=20)]
    systems: Annotated[list[SystemRelationship], Field(max_length=20)]


class RecordWrite(RecordContent):
    expected_version: Version


class Record(RecordContent):
    version: Version
    updated_at: str | None
    updated_by: str | None


class TaskCreate(Model):
    title: Title
    operation_id: UUID


class TaskWrite(Model):
    title: Title
    completed: Annotated[bool, Field(strict=True)]
    expected_version: Annotated[int, Field(strict=True, ge=1)]


class Task(Model):
    id: str
    title: Title
    completed: Annotated[bool, Field(strict=True)]
    version: Annotated[int, Field(strict=True, ge=1)]
    created_at: str
    updated_at: str
    updated_by: str
