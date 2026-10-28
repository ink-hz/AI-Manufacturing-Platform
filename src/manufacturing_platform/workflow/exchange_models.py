"""Typed boundary contracts. Only implemented authority actions can be submitted."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator

from .commands import WorkflowCommand
from .contracts import (
    DomainValue,
    NonnegativeQuantity,
    Quantity,
    SourceRef,
    StrictModel,
    require_timezone,
)

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


class ExternalRequest(StrictModel):
    id: UUID
    system: str = Field(min_length=1, max_length=200)
    action: Literal["reservation.request"]
    business_key: str = Field(min_length=1, max_length=200)
    source_version: int = Field(strict=True, ge=1)
    project_id: UUID
    typed_payload: ReservePayload


class ReceiptDetail(StrictModel):
    key: str = Field(min_length=1, max_length=200)
    lot_id: UUID
    owner_id: str = Field(min_length=1, max_length=200)
    quantity: NonnegativeQuantity
    unit: str = Field(min_length=1, max_length=40)


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
    details: list[ReceiptDetail] = Field(max_length=500)
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


class ExchangeValue(DomainValue):
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
