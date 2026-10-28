"""Typed boundary contracts. Only implemented authority actions can be submitted."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_serializer, model_validator

from .commands import WorkflowCommand
from .contracts import (
    DomainValue,
    NonnegativeQuantity,
    Quantity,
    SourceRef,
    StrictModel,
    require_timezone,
)
from .execution_models import sn_key

Phase = Literal[
    "requested",
    "received",
    "validated",
    "approved",
    "accepted",
    "posted",
    "rejected",
    "unknown",
]
ImportObjectType = Literal["receipt", "iqc", "customer_approval"]


class ReservePayload(StrictModel):
    kind: Literal["reserve"] = "reserve"
    reservation_id: UUID
    work_order_id: UUID
    requirement_id: UUID
    lot_id: UUID
    material_id: str = Field(min_length=1, max_length=200)
    owner_id: str = Field(min_length=1, max_length=200)
    quantity: Quantity
    unit: str = Field(min_length=1, max_length=40)
    scale: int = Field(strict=True, ge=0, le=6)
    plan_id: UUID
    plan_version: int = Field(strict=True, ge=1)


class StartPayload(StrictModel):
    kind: Literal["start"] = "start"
    start_id: UUID
    work_order_id: UUID
    revision_id: UUID
    mode: Literal["trial", "bulk"]
    work_order_quantity: int = Field(strict=True, ge=1)
    trial_quantity: int = Field(strict=True, ge=1)
    units: list[tuple[UUID, str]] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def whole_unique_scope(self):
        if (
            len(self.units) > self.work_order_quantity
            or (self.mode == "trial" and len(self.units) > self.trial_quantity)
            or len({uid for uid, _ in self.units}) != len(self.units)
            or len({sn_key(sn) for _, sn in self.units}) != len(self.units)
            or any(not sn_key(sn) or len(sn) > 200 for _, sn in self.units)
        ):
            raise ValueError(
                "authority start scope must contain distinct whole serials within budget"
            )
        return self


class StopPayload(StrictModel):
    kind: Literal["stop"] = "stop"
    interruption_id: UUID
    work_order_id: UUID
    reason: str = Field(min_length=1, max_length=2000)
    start_id: UUID | None = None


class ResumePayload(StrictModel):
    kind: Literal["resume"] = "resume"
    interruption_id: UUID
    work_order_id: UUID
    plan_id: UUID
    scope: Literal["all", "trial"] = "all"

    @model_serializer(mode="wrap")
    def preserve_existing_all_scope_hash(self, handler):
        data = handler(self)
        if self.scope == "all":
            data.pop("scope", None)
        return data


class EcoSwitchPayload(StrictModel):
    kind: Literal["eco_switch"] = "eco_switch"
    switch_id: UUID
    eco_id: UUID
    work_order_id: UUID
    old_revision_id: UUID
    new_revision_id: UUID | None
    new_work_order_id: UUID | None
    boundary: Literal["split_remaining", "cancel_remaining"]
    original_quantity: int = Field(strict=True, ge=1)
    original_trial_quantity: int = Field(strict=True, ge=1)
    remaining_quantity: int = Field(strict=True, ge=1)
    retained_unit_ids: list[UUID] = Field(max_length=500)
    new_trial_quantity: int = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def scope_conservation(self):
        split = self.boundary == "split_remaining"
        if len(set(self.retained_unit_ids)) != len(
            self.retained_unit_ids
        ) or self.original_quantity != self.remaining_quantity + len(
            self.retained_unit_ids
        ):
            raise ValueError("remaining scope must conserve original quantity")
        if split != (
            self.new_revision_id is not None and self.new_work_order_id is not None
        ) or (not split and (self.new_revision_id or self.new_work_order_id)):
            raise ValueError(
                "split requires creation identity; cancellation creates nothing"
            )
        if split and not 1 <= self.new_trial_quantity <= self.remaining_quantity:
            raise ValueError("new trial quantity must be within replacement scope")
        return self


class EcoReceiptDetail(StrictModel):
    key: str = Field(min_length=1, max_length=200)
    effect: Literal["cancel_remaining", "create_replacement"]
    work_order_id: UUID
    revision_id: UUID
    quantity: Quantity
    retained_quantity: NonnegativeQuantity


class ShipPayload(StrictModel):
    kind: Literal["ship"] = "ship"
    shipment_id: UUID
    order_line_id: UUID
    quantity: Quantity
    unit: str
    scale: int = Field(strict=True, ge=0, le=6)
    order_quantity: Quantity
    units: list[tuple[UUID, str, UUID]] = Field(min_length=1, max_length=500)
    boxes: list["ShipmentBox"] = Field(max_length=500)


from .delivery_models import ShipmentBox


class ShipmentReceiptDetail(StrictModel):
    key: str
    unit_id: UUID
    sn: str
    work_order_id: UUID
    order_line_id: UUID
    box_id: str | None


class StockProofPayload(StrictModel):
    kind: Literal["stock_proof"] = "stock_proof"
    eco_id: UUID
    reservation_id: UUID
    original_exchange_id: UUID
    original_business_key: str
    original_receipt_hash: str
    original_opening_hash: str
    original_accounted_atoms: int = Field(strict=True, ge=0)


class ExternalRequest(StrictModel):
    id: UUID
    system: str = Field(min_length=1, max_length=200)
    action: Literal[
        "stock_basis.reconcile",
        "shipment.request",
        "eco.switch",
        "reservation.request",
        "production.start",
        "production.interrupt",
        "production.resume",
    ]
    business_key: str = Field(min_length=1, max_length=200)
    source_version: int = Field(strict=True, ge=1)
    project_id: UUID
    typed_payload: Annotated[
        ReservePayload
        | StartPayload
        | StopPayload
        | ResumePayload
        | EcoSwitchPayload
        | ShipPayload
        | StockProofPayload,
        Field(discriminator="kind"),
    ]

    @model_validator(mode="after")
    def matching_action(self):
        expected = {
            "stock_basis.reconcile": "stock_proof",
            "shipment.request": "ship",
            "eco.switch": "eco_switch",
            "reservation.request": "reserve",
            "production.start": "start",
            "production.interrupt": "stop",
            "production.resume": "resume",
        }
        if self.typed_payload.kind != expected[self.action]:
            raise ValueError("request action and payload differ")
        return self


class StockBasis(StrictModel):
    project_id: UUID
    lot_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=40)
    system: str = Field(min_length=1, max_length=200)
    external_id: str = Field(min_length=1, max_length=200)
    source_version: int = Field(strict=True, ge=1)
    source_quantity: Quantity
    quantity: Quantity


class ReceiptDetail(StrictModel):
    key: str = Field(min_length=1, max_length=200)
    lot_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    quantity: NonnegativeQuantity
    unit: str = Field(min_length=1, max_length=40)
    stock_basis: list[StockBasis] | None = Field(default=None, max_length=500)

    @model_serializer(mode="wrap")
    def preserve_legacy_receipt(self, handler):
        data = handler(self)
        if self.stock_basis is None:
            data.pop("stock_basis", None)
        return data


class UnitReceiptDetail(StrictModel):
    key: str = Field(min_length=1, max_length=200)
    unit_id: UUID
    sn: str = Field(min_length=1, max_length=200)
    state: Literal["running", "stopped"]


class ControlReceiptDetail(StrictModel):
    key: str = Field(min_length=1, max_length=200)
    work_order_id: UUID
    scope: Literal["all", "trial"]
    state: Literal["running", "partial"]


class ExternalReceipt(StrictModel):
    receipt_id: UUID
    business_key: str = Field(min_length=1, max_length=200)
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_object_id: str = Field(min_length=1, max_length=200)
    source_version: int = Field(strict=True, ge=1)
    sequence: int = Field(strict=True, ge=0)
    phase: Literal[
        "received", "validated", "approved", "accepted", "posted", "rejected", "unknown"
    ]
    accepted_quantity: NonnegativeQuantity
    rejected_quantity: NonnegativeQuantity
    details: list[
        ReceiptDetail
        | UnitReceiptDetail
        | ControlReceiptDetail
        | EcoReceiptDetail
        | ShipmentReceiptDetail
    ] = Field(max_length=500)
    occurred_at: datetime
    error: str | None = Field(default=None, max_length=2000)
    _timezone = field_validator("occurred_at")(require_timezone)


class InboundBase(StrictModel):
    project_id: UUID
    source: SourceRef
    external_actor: str = Field(min_length=1, max_length=200)
    signature: str = Field(min_length=1, max_length=2000)


class InboundReceipt(InboundBase):
    object_type: Literal["receipt"] = "receipt"
    commitment_id: UUID
    material_lot_id: UUID
    quantity: Quantity
    unit: str = Field(min_length=1, max_length=40)


class InboundIQC(InboundBase):
    object_type: Literal["iqc"] = "iqc"
    receipt_system: str = Field(min_length=1, max_length=200)
    receipt_external_id: str = Field(min_length=1, max_length=200)
    accepted: NonnegativeQuantity
    rejected: NonnegativeQuantity
    evidence: str = Field(min_length=1, max_length=2000)
    manual_iqc_id: UUID | None = None


class InboundApproval(InboundBase):
    object_type: Literal["customer_approval"] = "customer_approval"
    revision_id: UUID
    customer_id: str = Field(min_length=1, max_length=200)
    decision: Literal["approved", "rejected"]
    evidence: str = Field(min_length=1, max_length=2000)


TypedInboundRecord = Annotated[
    InboundReceipt | InboundIQC | InboundApproval, Field(discriminator="object_type")
]


class AuthoritySnapshot(StrictModel):
    system: str
    object_type: ImportObjectType
    sequence: int = Field(strict=True, ge=0)
    records: list[TypedInboundRecord] = Field(max_length=500)


class RequestReservation(WorkflowCommand):
    action: Literal["reservation.request"]
    work_order_id: UUID
    requirement_id: UUID
    lot_id: UUID
    quantity: Quantity
    unit: str = Field(min_length=1, max_length=40)


class DispatchExchange(WorkflowCommand):
    action: Literal["exchange.dispatch"]
    exchange_id: UUID


class QueryExchange(WorkflowCommand):
    action: Literal["exchange.query"]
    exchange_id: UUID


class PullSource(WorkflowCommand):
    action: Literal["source.pull"]
    system: str = Field(min_length=1, max_length=200)
    object_type: ImportObjectType
    external_id: str = Field(min_length=1, max_length=200)


class ImportSource(WorkflowCommand):
    action: Literal["source.import"]
    object_type: ImportObjectType
    rows: list[TypedInboundRecord] = Field(min_length=1, max_length=500)


class ImportFile(WorkflowCommand):
    action: Literal["source.import_file"]
    object_type: ImportObjectType
    format: Literal["json", "csv"]
    content_base64: str = Field(max_length=1398104)


class ReconcileExchange(WorkflowCommand):
    action: Literal["exchange.reconcile"]
    exchange_id: UUID
    source: SourceRef
    object_type: Literal["reservation", "receipt", "iqc", "customer_approval"]
    source_version: int = Field(strict=True, ge=1)
    details: list[ReceiptDetail] = Field(max_length=500)
    evidence: str = Field(min_length=1, max_length=2000)
    resolution: Literal["compare", "accept_authority"] = "compare"


class ExchangeEvent(StrictModel):
    sequence: int
    phase: Phase
    reason: str


class ExchangeDiscrepancy(StrictModel):
    sequence: int
    owner_id: UUID
    owner_name: str
    reason: str
    evidence: str
    resolves_sequence: int | None


class StockSourceEvent(StrictModel):
    project_id: UUID
    lot_id: UUID
    owner_id: str
    material_id: str
    unit: str
    quantity: Quantity
    source: SourceRef
    sequence: int = Field(strict=True, ge=1)


class StockBasisProof(StrictModel):
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    mode: Literal["mock", "api"]
    receipt: ExternalReceipt
    sources: list[StockSourceEvent] = Field(min_length=1, max_length=500)


class ExchangeValue(DomainValue):
    stock_basis_proof: StockBasisProof | None = None
    discrepancies: list[ExchangeDiscrepancy] = Field(default_factory=list)
    kind: Literal["exchange"] = "exchange"
    action: str
    policy_action: str
    source: SourceRef | None = None
    source_object_type: ImportObjectType | None = None
    system: str
    business_key: str
    mode: Literal["mock", "api", "unavailable", "file"]
    phase: Phase
    requested: NonnegativeQuantity
    accepted: NonnegativeQuantity
    rejected: NonnegativeQuantity
    unit: str
    reason: str
    events: list[ExchangeEvent]
    receipt: ExternalReceipt | None
    reservation_id: UUID | None


class ReservationValue(DomainValue):
    kind: Literal["reservation"] = "reservation"
    requirement_id: UUID
    work_order_id: UUID
    material_lot_id: UUID
    requested: Quantity
    confirmed: NonnegativeQuantity
    remaining: NonnegativeQuantity
    unit: str
    source_version: int
    authority_receipt_id: UUID | None
    exchange_id: UUID


class SourceConfirmation(StrictModel):
    source: SourceRef
    external_actor: str
    signature: str
    recorded_by: UUID
    sequence: int
