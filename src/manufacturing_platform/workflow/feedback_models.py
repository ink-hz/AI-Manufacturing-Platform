"""Strict trace, physical containment and human quality-feedback contracts."""

from typing import Literal
from uuid import UUID

from pydantic import Field, StrictBool, model_validator

from .commands import WorkflowCommand
from .contracts import DomainValue, ObjectKind, SourceRef, StrictModel


class FreezeRequest(WorkflowCommand):
    action: Literal["freeze.request"]
    unit_ids: list[UUID] = Field(default_factory=list, max_length=500)
    lot_ids: list[UUID] = Field(default_factory=list, max_length=500)
    state: Literal["frozen", "unfrozen"]
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")

    @model_validator(mode="after")
    def scope(self):
        if (
            not 1 <= len(self.unit_ids) + len(self.lot_ids) <= 500
            or len(set(self.unit_ids)) != len(self.unit_ids)
            or len(set(self.lot_ids)) != len(self.lot_ids)
        ):
            raise ValueError("Freeze requires a distinct bounded scope")
        return self


class FreezePayload(StrictModel):
    kind: Literal["freeze"] = "freeze"
    freeze_id: UUID
    unit_ids: list[UUID] = Field(max_length=500)
    lot_ids: list[UUID] = Field(max_length=500)
    state: Literal["frozen", "unfrozen"]


class FreezeReceiptDetail(StrictModel):
    key: str
    object_kind: Literal["unit", "material_lot"]
    object_id: UUID
    state: Literal["frozen", "unfrozen"]


class FreezeProjection(StrictModel):
    freeze_requested: Literal["frozen", "unfrozen"] | None = None
    freeze_confirmed: Literal["frozen", "unfrozen"] | None = None
    freeze_pending: bool = False


class TraceNode(StrictModel):
    id: UUID
    kind: ObjectKind
    project_id: UUID
    title: str
    customer_id: str | None = None


class TraceEdge(StrictModel):
    source_kind: ObjectKind
    target_kind: ObjectKind
    source_id: UUID
    target_id: UUID
    relation: Literal[
        "order",
        "revision",
        "work_order",
        "consumed",
        "test",
        "prior_test",
        "rework",
        "release",
        "shipment",
        "rma",
        "capa",
    ]


class TraceResult(StrictModel):
    nodes: list[TraceNode]
    edges: list[TraceEdge]
    truncated: bool


class RmaOpen(WorkflowCommand):
    action: Literal["rma.open"]
    unit_id: UUID
    shipment_id: UUID
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    source: SourceRef


class RmaSourceRecord(StrictModel):
    object_type: Literal["rma"] = "rma"
    project_id: UUID
    unit_id: UUID
    shipment_id: UUID
    source: SourceRef


class CapaUpdate(WorkflowCommand):
    action: Literal["capa.update"]
    capa_id: UUID | None = None
    rma_id: UUID
    step: Literal["containment", "root_cause", "correction", "verification"]
    description: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    evidence: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    effective: StrictBool | None = None
    action_kind: Literal["engineering", "supplier", "training", "process"] | None = None
    implementation_evidence: str | None = Field(
        default=None, min_length=1, max_length=2000, pattern=r"\S"
    )
    eco_id: UUID | None = None


class CapaClose(WorkflowCommand):
    action: Literal["capa.close"]
    capa_id: UUID


class CapaStep(StrictModel):
    sequence: int
    step: Literal["containment", "root_cause", "correction", "verification"]
    description: str
    evidence: str
    effective: bool | None
    action_kind: Literal["engineering", "supplier", "training", "process"] | None
    implementation_evidence: str | None
    eco_id: UUID | None


class RmaValue(DomainValue):
    kind: Literal["rma"] = "rma"
    id: UUID
    unit_id: UUID
    shipment_id: UUID
    order_line_id: UUID
    customer_id: str
    revision_id: UUID
    test_ids: list[UUID]
    tests_truncated: bool
    reason: str
    source: SourceRef | None
    state: Literal["open", "closed"]


class CapaValue(DomainValue):
    kind: Literal["capa"] = "capa"
    id: UUID
    rma_id: UUID
    state: Literal["open", "closed"]
    steps: list[CapaStep]
    steps_truncated: bool
    blocking_reasons: list[str]


class BlockingReason(StrictModel):
    kind: ObjectKind
    id: UUID
    reason: str
