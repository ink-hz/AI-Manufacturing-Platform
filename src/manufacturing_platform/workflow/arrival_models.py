"""Actual package observations before purchase/material identity is established."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .commands import WorkflowCommand
from .contracts import DomainValue, SourceRef, StrictModel
from .introduction_models import Name, Text


class RecordArrival(WorkflowCommand):
    action: Literal["arrival.record"]
    arrival_number: Name
    location: Name
    package_count: int = Field(strict=True, ge=1, le=100000)
    description: Text
    source: SourceRef

    @model_validator(mode="after")
    def manual(self):
        if self.source.mode != "manual" or self.source.object_type != "arrival" or not self.source.evidence.strip():
            raise ValueError("arrival requires attributable manual observation source")
        return self


class MatchArrival(WorkflowCommand):
    action: Literal["arrival.match"]
    arrival_id: UUID
    receipt_id: UUID
    evidence: Text
    correction_reason: Text | None = None


class ArrivalMatch(StrictModel):
    id: UUID
    receipt_id: UUID
    previous_receipt_id: UUID | None
    evidence: Text
    correction_reason: Text | None
    actor_id: UUID
    recorded_at: datetime


class Arrival(DomainValue):
    kind: Literal["arrival"] = "arrival"
    id: UUID
    arrival_number: Name
    location: Name
    package_count: int
    description: Text
    source: SourceRef
    actor_id: UUID
    recorded_at: datetime
    state: Literal["unlinked", "matched"]
    receipt_id: UUID | None
    matches: list[ArrivalMatch]
