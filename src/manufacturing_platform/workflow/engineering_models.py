"""Strict fixed engineering and work order contracts."""

from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BeforeValidator, ConfigDict, Field, model_validator

from ..collaboration_models import EventTime, PackageItem
from .commands import WorkflowCommand
from .contracts import (
    DomainValue,
    NonnegativeQuantity,
    Quantity,
    SourceRef,
    StrictModel,
)
from .execution_models import ExecutionEventView, HeldStartScope


def parse_measurement_bound(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 40:
        raise ValueError("measurement bound must be a bounded decimal string")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid measurement bound") from exc
    if (
        not amount.is_finite()
        or (amount == 0 and amount.is_signed())
        or format(amount, "f") != value
    ):
        raise ValueError("measurement bound must be a finite canonical decimal")
    return amount


MeasurementBound = Annotated[Decimal, BeforeValidator(parse_measurement_bound)]


class RouteStep(StrictModel):
    station: str = Field(min_length=1, max_length=200)
    instruction_version: str = Field(min_length=1, max_length=200)


class MeasurementLimit(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=40)
    lower: MeasurementBound
    upper: MeasurementBound

    @model_validator(mode="after")
    def bounded(self):
        if self.lower > self.upper:
            raise ValueError("measurement limits required in ascending order")
        return self


class TestSpec(StrictModel):
    version: str = Field(min_length=1, max_length=200)
    program_version: str = Field(min_length=1, max_length=200)
    measurements: list[MeasurementLimit] = Field(min_length=1, max_length=200)


class RecordRevision(WorkflowCommand):
    action: Literal["engineering.revision"]
    package_id: str = Field(min_length=1, max_length=200)
    revision: str = Field(min_length=1, max_length=200)
    customer_revision: str = Field(min_length=1, max_length=200)
    internal_revision: str = Field(min_length=1, max_length=200)
    items: list[PackageItem] = Field(min_length=1, max_length=500)
    route_steps: list[RouteStep] = Field(min_length=1, max_length=200)
    test_spec: TestSpec
    firmware_version: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_parts(self):
        if len({i.id for i in self.items}) != len(self.items):
            raise ValueError("duplicate package item")
        if len({s.station for s in self.route_steps}) != len(self.route_steps):
            raise ValueError("duplicate route station")
        return self


class RecordHandoff(WorkflowCommand):
    action: Literal["engineering.handoff"]
    revision_id: UUID
    to_system: str = Field(min_length=1, max_length=200)
    received_revision: str = Field(min_length=1, max_length=200)
    decision: Literal["accepted", "rejected"]
    evidence: str = Field(min_length=1, max_length=2000)


class RecordCustomerApproval(WorkflowCommand):
    action: Literal["engineering.customer_approval"]
    revision_id: UUID
    method: Literal["manual"] = "manual"
    decision: Literal["approved", "rejected", "unknown"]
    customer_id: str = Field(min_length=1, max_length=200)
    external_signatory: str = Field(min_length=1, max_length=200)
    evidence: str = Field(min_length=1, max_length=2000)


class RegisterWorkOrder(WorkflowCommand):
    action: Literal["work_order.register"]
    order_line_id: UUID
    revision_id: UUID
    source: SourceRef
    quantity: Quantity
    unit: str = Field(min_length=1, max_length=40)
    purpose: Literal["trial", "production"]
    trial_quantity: Quantity
    planned_start: EventTime
    planned_end: EventTime

    @model_validator(mode="after")
    def valid_plan(self):
        if (
            self.trial_quantity > self.quantity
            or self.planned_end <= self.planned_start
        ):
            raise ValueError("invalid trial quantity or planned dates")
        return self


class RecordReadiness(WorkflowCommand):
    action: Literal["readiness.record"]
    work_order_id: UUID
    kind: Literal["equipment", "people"]
    reference: str = Field(min_length=1, max_length=200)
    evidence: str = Field(min_length=1, max_length=2000)
    valid_until: EventTime
    decision: Literal["verified", "rejected"]


class HandoffView(StrictModel):
    id: UUID
    to_system: str
    received_revision: str
    status: Literal["verified", "rejected"]
    evidence: str


class CustomerApprovalView(StrictModel):
    source: SourceRef | None = None
    id: UUID
    method: Literal["manual", "file", "mock", "api"]
    recorded_by: UUID
    customer_id: str
    external_signatory: str
    decision: Literal["approved", "rejected", "unknown"]
    evidence: str


class EngineeringRevision(DomainValue):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["revision"] = "revision"
    id: UUID
    project_id: UUID
    package_id: str
    revision: str
    customer_revision: str
    internal_revision: str
    items: tuple[PackageItem, ...]
    route_steps: tuple[RouteStep, ...]
    test_spec: TestSpec
    firmware_version: str
    content_hash: str
    handoffs: tuple[HandoffView, ...]
    customer_approvals: tuple[CustomerApprovalView, ...]


class ReadinessCheck(StrictModel):
    kind: Literal[
        "version",
        "equipment",
        "people",
        "customer",
        "material",
        "plan",
        "first_article",
    ]
    required: bool
    status: Literal["ready", "blocked", "not_required"]
    reason: str
    evidence_ids: list[UUID] = Field(default_factory=list)


class ReadinessResult(StrictModel):
    ready: bool
    checks: list[ReadinessCheck]
    input_versions: dict[str, str | int]


class WorkOrder(DomainValue):
    kind: Literal["work_order"] = "work_order"
    order_line_id: UUID
    revision_id: UUID
    quantity: Quantity
    unit: str
    purpose: Literal["trial", "production"]
    trial_quantity: Quantity
    source: SourceRef
    planned_start: EventTime
    planned_end: EventTime
    state: Literal["planned"] = "planned"
    trial_readiness: ReadinessResult
    bulk_readiness: ReadinessResult
    remaining_obligation: NonnegativeQuantity
    execution_event_total: int
    execution_events: list[ExecutionEventView]
    held_start_scopes: list[HeldStartScope] = Field(default_factory=list)
