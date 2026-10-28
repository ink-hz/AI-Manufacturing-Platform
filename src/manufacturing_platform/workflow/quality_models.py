"""Measured quality facts and independent sign-off contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_serializer, model_validator

from .commands import WorkflowCommand
from .contracts import DomainValue, NonnegativeQuantity, SourceRef, StrictModel
from .engineering_models import MeasurementBound, MeasurementLimit, RouteStep
from .execution_models import ExecutionEventView, TestEvidenceScope


class Measurement(MeasurementLimit):
    value: MeasurementBound

    @field_serializer("value", "lower", "upper")
    def decimal_string(self, value):
        return format(value, "f")


class RecordTest(WorkflowCommand):
    action: Literal["test.record"]
    source: SourceRef
    unit_id: UUID
    attempt: int = Field(strict=True, ge=1)
    program_version: str = Field(min_length=1, max_length=200)
    limit_version: str = Field(min_length=1, max_length=200)
    firmware_version: str = Field(min_length=1, max_length=200)
    measurements: list[Measurement] = Field(min_length=1, max_length=200)
    rework_order_id: UUID | None = None


class QualitySourceRecord(StrictModel):
    object_type: Literal["test", "customer_release"]
    project_id: UUID
    source: SourceRef
    unit_ids: list[UUID]
    revision_id: UUID | None = None
    customer_id: str | None = None


class OpenNonconformance(WorkflowCommand):
    action: Literal["nonconformance.open"]
    test_id: UUID
    defect: str = Field(min_length=1, max_length=2000)
    evidence: str = Field(min_length=1, max_length=2000)


class Disposition(WorkflowCommand):
    action: Literal["nonconformance.disposition"]
    nonconformance_id: UUID
    decision: Literal["rework", "scrap", "concession"]
    route_id: str | None = Field(default=None, min_length=1, max_length=200)
    route_steps: list[RouteStep] = Field(default_factory=list, max_length=200)
    evidence: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def route(self):
        if self.decision == "rework":
            if (
                not self.route_id
                or not self.route_steps
                or len({s.station for s in self.route_steps}) != len(self.route_steps)
            ):
                raise ValueError("rework requires a unique independent route")
        elif self.route_id or self.route_steps:
            raise ValueError("route only belongs to rework")
        return self


class CompleteRework(WorkflowCommand):
    action: Literal["rework.complete"]
    rework_order_id: UUID
    execution_event_ids: list[UUID] = Field(min_length=1, max_length=200)
    test_ids: list[UUID] = Field(min_length=1, max_length=200)


ReleaseKind = Literal["manufacturing", "quality", "customer"]


class DecideRelease(WorkflowCommand):
    action: Literal["release.decide"]
    kind: ReleaseKind
    unit_ids: list[UUID] = Field(min_length=1, max_length=500)
    decision: Literal["approved", "rejected", "conditional"]
    evidence: str = Field(min_length=1, max_length=2000)
    customer_id: str | None = None
    revision_id: UUID | None = None
    customer_revision: str | None = None
    external_signatory: str | None = Field(default=None, min_length=1, max_length=200)
    method: Literal["manual"] | None = None
    source: SourceRef | None = None


class TestView(StrictModel):
    id: UUID
    attempt: int
    outcome: Literal["pass", "fail"]
    rework_order_id: UUID | None
    occurred_at: datetime


class TestValue(DomainValue):
    kind: Literal["test"] = "test"
    id: UUID
    unit_id: UUID
    revision_id: UUID
    attempt: int
    scope: TestEvidenceScope
    measurements: list[Measurement]
    outcome: Literal["pass", "fail"]
    rework_order_id: UUID | None
    execution_event_ids: list[UUID]
    source: SourceRef
    actor_id: UUID
    occurred_at: datetime
    recorded_at: datetime


class NonconformanceValue(DomainValue):
    kind: Literal["nonconformance"] = "nonconformance"
    id: UUID
    unit_id: UUID
    test_id: UUID
    defect: str
    evidence: str
    state: Literal["open", "rework", "resolved", "scrapped"]
    rework_order_id: UUID | None
    disposition: Literal["rework", "scrap"] | None
    disposition_evidence: str | None


class ReworkValue(DomainValue):
    candidate_execution_events: list[ExecutionEventView] = Field(
        default_factory=list, max_length=200
    )
    kind: Literal["rework"] = "rework"
    id: UUID
    unit_id: UUID
    nonconformance_id: UUID
    revision_id: UUID
    route_id: str
    route_steps: list[RouteStep]
    state: Literal["open", "complete"]
    execution_event_ids: list[UUID]
    test_ids: list[UUID]


class ReleaseValue(DomainValue):
    kind: Literal["release"] = "release"
    id: UUID
    release_kind: ReleaseKind
    unit_ids: list[UUID]
    decision: Literal["approved", "rejected"]
    evidence: str
    test_ids: list[UUID]
    actor_id: UUID
    customer_id: str | None
    revision_id: UUID | None
    customer_revision: str | None
    external_signatory: str | None
    method: Literal["manual"] | None
    source: SourceRef | None
    recorded_at: datetime


class QualitySummary(StrictModel):
    first_tested: int
    first_passed: int
    final_good: int
    scrapped: int
    open_nonconformances: int


class Eligibility(StrictModel):
    allowed: bool
    reasons: list[str]
    qualified_quantity: NonnegativeQuantity
    release_ids: list[UUID]
