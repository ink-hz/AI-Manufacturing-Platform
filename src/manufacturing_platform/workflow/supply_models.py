"""Strict supply commands and read models; material scale is independent of product scale."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .commands import WorkflowCommand
from .contracts import (
    DomainValue,
    MaterialBalance,
    NonnegativeQuantity,
    Quantity,
    SourceRef,
    StrictModel,
)


class PlanOrderVersion(StrictModel):
    order_line_id: UUID
    version: int = Field(strict=True, ge=1)


class PlanRequirement(StrictModel):
    work_order_id: UUID
    execution_scope: Literal["trial", "bulk", "common"]
    material_id: str = Field(min_length=1, max_length=200)
    owner_id: str = Field(min_length=1, max_length=200)
    quantity: Quantity
    unit: str = Field(min_length=1, max_length=40)


class ReceivePlan(WorkflowCommand):
    action: Literal["plan.receive"]
    source: SourceRef
    input_revision_ids: list[UUID] = Field(min_length=1, max_length=100)
    input_order_versions: list[PlanOrderVersion] = Field(min_length=1, max_length=100)
    requirements: list[PlanRequirement] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_requirements(self):
        keys = [
            (r.work_order_id, r.execution_scope, r.material_id, r.owner_id)
            for r in self.requirements
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate scoped requirement")
        return self


class DefineMaterial(WorkflowCommand):
    action: Literal["material.define"]
    material_id: str = Field(min_length=1, max_length=200)
    lot_id: str = Field(min_length=1, max_length=200)
    owner_id: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=40)
    scale: int = Field(strict=True, ge=0, le=6)
    expiry: date
    source: SourceRef


class CommitSupply(WorkflowCommand):
    action: Literal["supply.commit"]
    commitment_id: UUID | None = None
    requirement_id: UUID
    type: Literal["purchase", "customer"]
    owner_id: str = Field(min_length=1, max_length=200)
    quantity: Quantity
    unit: str = Field(min_length=1, max_length=40)
    original_due: date
    current_due: date
    source: SourceRef


class ReceiveSupply(WorkflowCommand):
    action: Literal["supply.receive"]
    commitment_id: UUID
    material_lot_id: UUID
    quantity: Quantity
    unit: str = Field(min_length=1, max_length=40)
    source: SourceRef


class InspectSupply(WorkflowCommand):
    action: Literal["supply.inspect"]
    receipt_id: UUID
    accepted: NonnegativeQuantity
    rejected: NonnegativeQuantity
    evidence: str = Field(min_length=1, max_length=2000)


class PlanValue(DomainValue):
    kind: Literal["plan"] = "plan"
    state: Literal["confirmed", "rejected"]
    reason: str
    source: SourceRef
    input_revision_ids: list[UUID]
    input_order_versions: list[PlanOrderVersion]
    requirement_ids: list[UUID]
    cutoff: str | None


class RequirementValue(DomainValue):
    kind: Literal["requirement"] = "requirement"
    plan_id: UUID
    lineage_id: UUID
    supersedes_requirement_id: UUID | None
    work_order_id: UUID
    execution_scope: Literal["trial", "bulk", "common"]
    material_id: str
    owner_id: str
    quantity: Quantity
    unit: str
    balance: MaterialBalance
    unqualified_quantity: NonnegativeQuantity


class PromiseRevision(StrictModel):
    source: SourceRef
    quantity: Quantity
    current_due: date


class CommitmentValue(DomainValue):
    kind: Literal["commitment"] = "commitment"
    requirement_id: UUID
    type: Literal["purchase", "customer"]
    owner_id: str
    original_quantity: Quantity
    current_quantity: Quantity
    unit: str
    original_due: date
    current_due: date
    source: SourceRef
    promise_revisions: list[PromiseRevision]
    material_lot_ids: list[UUID]
    received: NonnegativeQuantity
    qualified: NonnegativeQuantity
    rejected: NonnegativeQuantity


from .delivery_models import (
    OwnershipBalance,
    MaterialMovementView,
    OwnershipReconciliationView,
)


class MaterialLotValue(DomainValue):
    ownership_balance: OwnershipBalance | None = None
    material_movements: list[MaterialMovementView] = Field(default_factory=list)
    ownership_reconciliations: list[OwnershipReconciliationView] = Field(
        default_factory=list
    )
    kind: Literal["material_lot"] = "material_lot"
    material_id: str
    lot_id: str
    owner_id: str
    unit: str
    scale: int
    expiry: date
    state: Literal["active", "frozen"]
    source: SourceRef
    received: NonnegativeQuantity
    qualified: NonnegativeQuantity
    rejected: NonnegativeQuantity


from .exchange_models import SourceConfirmation


class SourceQuantityCorrection(StrictModel):
    sequence: int
    received_delta: str
    accepted_delta: str
    rejected_delta: str
    evidence: str


class ReceiptValue(DomainValue):
    original_quantity: Quantity
    corrections: list[SourceQuantityCorrection] = Field(default_factory=list)
    confirmations: list[SourceConfirmation] = Field(default_factory=list)
    kind: Literal["receipt"] = "receipt"
    commitment_id: UUID
    material_lot_id: UUID
    quantity: Quantity
    unit: str
    source: SourceRef
    accepted: NonnegativeQuantity
    rejected: NonnegativeQuantity
    uninspected: NonnegativeQuantity
