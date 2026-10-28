"""Strict wire contracts for demand review and order obligations."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field

from .commands import WorkflowCommand
from .contracts import (
    DomainValue,
    NonnegativeQuantity,
    Quantity,
    SourceRef,
    StrictModel,
)


class RecordDemand(WorkflowCommand):
    action: Literal["demand.record"]
    kind: Literal["inquiry", "forecast", "firm"]
    product: str = Field(min_length=1, max_length=200)
    quantity: Quantity
    unit: str = Field(min_length=1, max_length=40)
    due_date: date
    source: SourceRef
    supersedes_demand_id: UUID | None = None


class ReviewDemand(WorkflowCommand):
    action: Literal["demand.review"]
    demand_id: UUID
    dimension: Literal["technical", "material", "capacity", "commercial", "quality"]
    decision: Literal["approved", "rejected", "unknown"]
    evidence: str = Field(min_length=1, max_length=2000)


class RegisterOrder(WorkflowCommand):
    action: Literal["order.register"]
    demand_id: UUID
    source: SourceRef
    quantity: Quantity
    unit: str = Field(min_length=1, max_length=40)
    due_date: date


class ChangeOrder(WorkflowCommand):
    action: Literal["order.change"]
    order_line_id: UUID
    new_quantity: Quantity
    new_due_date: date
    cancel: bool = Field(strict=True)
    reason: str = Field(min_length=1, max_length=2000)
    source: SourceRef


class ChangeDisposition(StrictModel):
    object_type: Literal["work_order", "commitment", "unit", "shipment"]
    object_id: UUID
    decision: Literal["retain", "cancel", "transfer", "rework", "return"]
    evidence: str = Field(min_length=1, max_length=2000)


class ResolveOrderChange(WorkflowCommand):
    action: Literal["order.resolve_change"]
    change_id: UUID
    dispositions: list[ChangeDisposition] = Field(max_length=500)


class AllocateOrder(WorkflowCommand):
    action: Literal["order.allocate"]
    order_line_id: UUID
    work_order_id: UUID
    quantity: Quantity
    unit: str = Field(min_length=1, max_length=40)


class DemandValue(DomainValue):
    kind: Literal["demand"] = "demand"
    demand_kind: Literal["inquiry", "forecast", "firm"]
    product: str
    quantity: Quantity
    unit: str
    due_date: date
    source: SourceRef
    supersedes_demand_id: UUID | None
    reviews: dict[str, str]


class WorkOrderImpactReference(StrictModel):
    id: UUID
    source_system: str
    external_id: str
    quantity: NonnegativeQuantity
    unit: str


class WorkOrderImpactPreview(StrictModel):
    registered_quantity: NonnegativeQuantity
    total: int = Field(strict=True, ge=0)
    shown: int = Field(strict=True, ge=0, le=50)
    has_more: bool
    items: list[WorkOrderImpactReference] = Field(max_length=50)


class OrderLineValue(DomainValue):
    fulfillment_status: Literal["open", "eligible", "closed"] = "open"
    kind: Literal["order_line"] = "order_line"
    work_order_impact: WorkOrderImpactPreview
    demand_id: UUID
    original_quantity: Quantity
    current_quantity: NonnegativeQuantity
    unit: str
    original_due: date
    current_due: date
    source: SourceRef
    state: Literal["active", "cancelled"]
    allocated: NonnegativeQuantity
    produced_good: NonnegativeQuantity
    shipped: NonnegativeQuantity
    signed: NonnegativeQuantity
    accepted: NonnegativeQuantity
    remaining_to_ship: NonnegativeQuantity
    remaining_to_accept: NonnegativeQuantity


class ChangeImpact(StrictModel):
    object_type: Literal["work_order", "commitment", "unit", "shipment"]
    object_id: UUID
    quantity: NonnegativeQuantity
    unit: str
    decision: str | None
    evidence: str | None


class CommitmentChangeValue(DomainValue):
    kind: Literal["commitment_change"] = "commitment_change"
    order_line_id: UUID
    old_quantity: Quantity
    new_quantity: NonnegativeQuantity
    unit: str
    old_due: date
    new_due: date
    cancel: bool
    reason: str
    source: SourceRef
    state: Literal["pending", "applied"]
    impacts: list[ChangeImpact]
