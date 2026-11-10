"""Strict, bounded client input for durable investigation metadata."""

import re
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator, model_validator

DecimalId = Annotated[StrictStr, Field(pattern=r'^[1-9][0-9]{0,19}$')]
Text = Annotated[StrictStr, Field(min_length=1, max_length=200)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

    @field_validator('*', mode='before')
    @classmethod
    def safe_text(cls, value):
        if isinstance(value, str) and any(ord(c) < 32 and c not in '\n\t' for c in value):
            raise ValueError('invalid text')
        return value


class TimeRange(InputModel):
    start: datetime
    end: datetime

    @field_validator('start', 'end', mode='before')
    @classmethod
    def iso_time(cls, value):
        if not isinstance(value, (str, datetime)) or (isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', value) is None):
            raise ValueError('ISO timestamp with timezone required')
        return value

    @model_validator(mode='after')
    def bounded(self):
        if self.start.utcoffset() is None or self.end.utcoffset() is None:
            raise ValueError('timezone required')
        if not 0 < (self.end - self.start).total_seconds() <= 31 * 86400:
            raise ValueError('range must be within 31 days')
        self.start = self.start.astimezone(UTC)
        self.end = self.end.astimezone(UTC)
        return self


class InvestigationContext(TimeRange):
    view: Literal['overview', 'project', 'anomalies', 'activity', 'device', 'history', 'records', 'catalog', 'compare'] = 'anomalies'
    stage_id: DecimalId | None = None
    software_id: DecimalId | None = None
    software_version: Text | None = None
    config_log_id: DecimalId | None = None
    config_version: Text | None = None
    device: Text | None = None
    error_code: Text | None = None
    order_id: DecimalId | None = None
    barcode: Text | None = None
    sn: Text | None = None
    candidate_csn: Text | None = None
    status: Literal['1', '2'] | None = None
    symptom: Annotated[StrictStr, Field(max_length=1000)] | None = None
    history_range: TimeRange | None = None
    evidence_range: TimeRange | None = None
    recent_range: TimeRange | None = None


class Selection(InputModel):
    snapshot_id: UUID
    offset: int = Field(strict=True, ge=0, le=999)

    @field_validator('snapshot_id', mode='before')
    @classmethod
    def uuid_text(cls, value):
        if not isinstance(value, (str, UUID)):
            raise ValueError('UUID required')
        return value


class CreateInvestigation(InputModel):
    context: InvestigationContext
    primary: Selection | None = None
    comparison: Selection | None = None
    logs: list[DecimalId] = Field(default_factory=list, max_length=5)
    note: Annotated[StrictStr, Field(max_length=4000)] = ''

    @field_validator('logs')
    @classmethod
    def unique_logs(cls, value):
        if len(value) != len(set(value)):
            raise ValueError('duplicate log IDs')
        return value


class UpdateInvestigation(InputModel):
    expected_version: int = Field(strict=True, ge=1, le=2147483647)
    context: InvestigationContext | None = None
    primary: Selection | None = None
    comparison: Selection | None = None
    logs: list[DecimalId] | None = Field(default=None, max_length=5)
    note: Annotated[StrictStr, Field(max_length=4000)] | None = None

    @model_validator(mode='after')
    def present_values(self):
        for name in ('context', 'logs', 'note'):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError('field may not be null')
        if self.logs is not None and len(self.logs) != len(set(self.logs)):
            raise ValueError('duplicate log IDs')
        return self


class CreateHandoff(InputModel):
    expected_version: int = Field(strict=True, ge=1, le=2147483647)


class ForkHandoff(InputModel):
    pass
