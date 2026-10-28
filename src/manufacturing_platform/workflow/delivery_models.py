"""Typed shipment, signed receipt, acceptance, and independent closure facts."""

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


class ShipmentBox(StrictModel):
    box_id: str = Field(min_length=1, max_length=200)
    unit_ids: list[UUID] = Field(min_length=1, max_length=500)


class RequestShipment(WorkflowCommand):
    action: Literal["shipment.request"]
    order_line_id: UUID
    unit_ids: list[UUID] = Field(min_length=1, max_length=500)
    boxes: list[ShipmentBox] = Field(default_factory=list, max_length=500)
    quantity: Quantity
    unit: str = Field(min_length=1, max_length=40)


class DeliverySign(WorkflowCommand):
    action: Literal["delivery.sign"]
    shipment_id: UUID
    quantity: Quantity
    source: SourceRef
    external_signatory: str = Field(min_length=1, max_length=200)


class IssueInput(StrictModel):
    title: str = Field(min_length=1, max_length=2000)
    owner_id: UUID
    required: bool


class DeliveryAccept(DeliverySign):
    action: Literal["delivery.accept"]
    issues: list[IssueInput] = Field(default_factory=list, max_length=50)


class ResolveIssue(WorkflowCommand):
    action: Literal["delivery.resolve_issue"]
    issue_id: UUID
    evidence: str = Field(min_length=1, max_length=2000)


class ClosureRecord(WorkflowCommand):
    action: Literal["closure.record"]
    kind: Literal["fulfillment", "quality", "cost"]
    source: SourceRef
    evidence: str = Field(min_length=1, max_length=2000)


class DeliveryBalance(StrictModel):
    ordered: NonnegativeQuantity
    allocated: NonnegativeQuantity
    qualified: NonnegativeQuantity
    pending_shipment: NonnegativeQuantity
    shipped: NonnegativeQuantity
    signed: NonnegativeQuantity
    accepted: NonnegativeQuantity
    remaining_to_ship: NonnegativeQuantity
    remaining_to_accept: NonnegativeQuantity
    unit: str


class FreezeEligibility(StrictModel):
    """C3 writes append-only pending/frozen/released events; pending fails closed."""

    allowed: bool
    reasons: list[str]


class AcceptanceIssue(StrictModel):
    id: UUID
    title: str
    owner_id: UUID
    owner_name: str
    required: bool
    resolved: bool
    evidence: str | None


class DeliveryFact(StrictModel):
    id: UUID
    action: Literal["sign", "accept"]
    quantity: Quantity
    source: SourceRef | None
    external_signatory: str
    recorded_by: UUID


class ShipmentValue(DomainValue):
    kind: Literal["shipment"] = "shipment"
    id: UUID
    order_line_id: UUID
    unit_ids: list[UUID]
    boxes: list[ShipmentBox]
    exchange_id: UUID
    state: Literal["pending", "accepted", "rejected", "held"]
    quantity: Quantity
    shipped: NonnegativeQuantity
    signed: NonnegativeQuantity
    accepted: NonnegativeQuantity
    unit: str
    remaining: DeliveryBalance
    facts: list[DeliveryFact]
    issues: list[AcceptanceIssue]
    blocking_reasons: list[str]


class DeliverySourceRecord(StrictModel):
    project_id: UUID
    object_type: Literal["delivery_sign", "delivery_accept"]
    shipment_id: UUID
    source: SourceRef


class MemberProfile(StrictModel):
    user_id: UUID
    display_name: str = Field(min_length=1, max_length=200, pattern=r"\S")


class ClosureValue(DomainValue):
    kind: Literal["closure"] = "closure"
    id: UUID
    closure_kind: Literal["fulfillment", "quality", "cost"]
    status: Literal["closed", "blocked"]
    source: SourceRef | None
    evidence: str
    blocking_reasons: list[str]


class ClosureSourceRecord(StrictModel):
    project_id: UUID
    object_type: Literal["closure"] = "closure"
    source: SourceRef


class MaterialScope(StrictModel):
    material_lot_id: UUID
    material_id: str = Field(min_length=1, max_length=200)
    owner_id: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=40)


class MaterialMovement(WorkflowCommand, MaterialScope):
    action: Literal["ownership.movement"]
    movement: Literal["return", "raw_loss"]
    quantity: Quantity
    supersedes_id: UUID | None = None
    source: SourceRef
    external_signatory: str = Field(min_length=1, max_length=200)
    evidence: str = Field(min_length=1, max_length=2000)


class OwnershipReconcile(WorkflowCommand, MaterialScope):
    action: Literal["ownership.reconcile"]
    received: NonnegativeQuantity
    consumed: NonnegativeQuantity
    scrapped: NonnegativeQuantity
    returned: NonnegativeQuantity
    balance: NonnegativeQuantity
    source: SourceRef


class OwnershipBalance(StrictModel):
    hold_reason: str | None = None
    received: NonnegativeQuantity
    consumed: NonnegativeQuantity
    scrapped: NonnegativeQuantity
    returned: NonnegativeQuantity
    balance: NonnegativeQuantity
    complete: bool
    unit: str
    owner_id: str
    material_id: str


class OwnershipSourceRecord(StrictModel):
    project_id: UUID
    object_type: Literal["material_movement", "ownership"]
    material_lot_id: UUID
    source: SourceRef


class ReconcileStockBasis(WorkflowCommand):
    action: Literal["stock_basis.reconcile"]
    eco_id: UUID
    reservation_id: UUID


class MaterialMovementView(StrictModel):
    id: UUID
    movement: Literal["return", "raw_loss"]
    quantity: Quantity
    supersedes_id: UUID | None
    current: bool
    source: SourceRef | None
    external_signatory: str
    evidence: str


class OwnershipReconciliationView(StrictModel):
    id: UUID
    current: bool
    source: SourceRef | None
    balance: OwnershipBalance
