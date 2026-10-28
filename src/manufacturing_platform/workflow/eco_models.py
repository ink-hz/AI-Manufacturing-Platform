"""Explicit change boundaries; cancellation does not invent a target revision."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_serializer, model_validator

from .commands import WorkflowCommand
from .contracts import DomainValue, NonnegativeQuantity, Quantity, StrictModel


class OpenEco(WorkflowCommand):
    action: Literal["eco.open"]
    old_revision_id: UUID
    new_revision_id: UUID | None = None
    effective_work_order_ids: list[UUID] = Field(default_factory=list, max_length=500)
    effective_sn_ids: list[UUID] = Field(default_factory=list, max_length=500)
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def explicit_boundary(self):
        if not self.effective_work_order_ids and not self.effective_sn_ids:
            raise ValueError("explicit work order or serial boundary required")
        if self.old_revision_id == self.new_revision_id:
            raise ValueError("new revision must differ")
        if len(set(self.effective_work_order_ids)) != len(
            self.effective_work_order_ids
        ) or len(set(self.effective_sn_ids)) != len(self.effective_sn_ids):
            raise ValueError("duplicate boundary")
        return self


class DisposeEco(WorkflowCommand):
    action: Literal["eco.disposition"]
    eco_id: UUID
    impact_id: UUID
    decision: Literal["use_old", "rework", "return", "scrap"]
    quantity: Quantity
    evidence: str = Field(min_length=1, max_length=2000)


class SwitchEco(WorkflowCommand):
    action: Literal["eco.switch"]
    eco_id: UUID
    target_work_order_id: UUID
    boundary: Literal["split_remaining", "cancel_remaining", "retain_existing"] = (
        "split_remaining"
    )
    retained_quantity: Quantity | None = None
    new_revision_id: UUID | None = None
    evidence: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def target(self):
        if (self.boundary == "split_remaining") != (self.new_revision_id is not None):
            raise ValueError(
                "split requires new revision; cancellation has no new revision"
            )
        if (self.boundary == "retain_existing") != (self.retained_quantity is not None):
            raise ValueError("retained outcome requires explicit complete quantity")
        return self

    @model_serializer(mode="wrap")
    def preserve_existing_hash(self, handler):
        data = handler(self)
        if self.retained_quantity is None:
            data.pop("retained_quantity", None)
        return data


class CloseEco(WorkflowCommand):
    action: Literal["eco.close"]
    eco_id: UUID


class EcoDisposition(StrictModel):
    id: UUID
    decision: Literal["use_old", "rework", "return", "scrap"]
    quantity: Quantity
    evidence: str


class EcoImpact(StrictModel):
    id: UUID
    type: Literal["purchase", "stock", "wip", "work_order", "unit"]
    object_id: UUID
    title: str
    owner_id: str
    quantity: Quantity
    unit: str
    scale: int
    state: str
    resolved_quantity: NonnegativeQuantity = "0"
    dispositions: list[EcoDisposition] = Field(default_factory=list)
    stock_basis: dict[str, NonnegativeQuantity] | None = None
    opening_consumption: NonnegativeQuantity = Field(default="0", validate_default=True)
    stock_basis_complete: bool = True


class EcoSwitch(StrictModel):
    id: UUID
    work_order_id: UUID
    new_work_order_id: UUID | None
    boundary: Literal["split_remaining", "cancel_remaining"]
    quantity: Quantity
    retained_quantity: NonnegativeQuantity
    exchange_id: UUID
    phase: str


class EcoRetention(StrictModel):
    work_order_id: UUID
    quantity: Quantity
    unit_ids: list[UUID]
    evidence: str


class EcoValue(DomainValue):
    kind: Literal["eco"] = "eco"
    id: UUID
    old_revision_id: UUID
    new_revision_id: UUID | None
    old_revision: str
    new_revision: str | None
    effective_work_order_ids: list[UUID]
    effective_sn_ids: list[UUID]
    reason: str
    state: Literal["open", "closed"]
    impacts: list[EcoImpact]
    switches: list[EcoSwitch]
    retentions: list[EcoRetention] = Field(default_factory=list)
    unresolved_stock_basis_ids: list[UUID] = Field(default_factory=list)
    implementation_outcome: Literal[
        "pending", "retained", "cancelled", "switched", "mixed"
    ] = "pending"
