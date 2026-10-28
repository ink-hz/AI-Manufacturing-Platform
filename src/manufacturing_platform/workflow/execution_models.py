"""Fixed serial, production and source-event contracts."""

import unicodedata
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_serializer, model_validator

from .commands import WorkflowCommand
from .contracts import DomainValue, Quantity, SourceRef, StrictModel, require_timezone


def sn_key(sn: str) -> str:
    return unicodedata.normalize("NFKC", sn.strip()).casefold()


class RegisterUnits(WorkflowCommand):
    action: Literal["unit.register"]
    work_order_id: UUID
    sns: list[str] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_sns(self):
        if any(not sn.strip() or len(sn) > 200 or sn != sn.strip() for sn in self.sns):
            raise ValueError("SN must be trimmed and bounded")
        if len({sn_key(sn) for sn in self.sns}) != len(self.sns):
            raise ValueError("duplicate SN")
        return self


class StartProduction(WorkflowCommand):
    action: Literal["production.start"]
    work_order_id: UUID
    mode: Literal["trial", "bulk"]
    unit_ids: list[UUID] = Field(min_length=1, max_length=500)
    quantity: Quantity

    @model_validator(mode="after")
    def exact_count(self):
        if self.quantity != len(self.unit_ids) or len(set(self.unit_ids)) != len(
            self.unit_ids
        ):
            raise ValueError("quantity must exactly equal unique serial count")
        return self


class InterruptProduction(WorkflowCommand):
    action: Literal["production.interrupt"]
    work_order_id: UUID
    reason: str = Field(min_length=1, max_length=2000)
    kind: Literal["S3", "S4", "other"] = "other"
    interruption_id: UUID | None = None
    start_id: UUID | None = None


class ResumeProduction(WorkflowCommand):
    action: Literal["production.resume"]
    interruption_id: UUID
    plan_id: UUID
    evidence: str = Field(min_length=1, max_length=2000)
    scope: Literal["all", "trial"] = "all"

    @model_serializer(mode="wrap")
    def preserve_existing_all_scope_hash(self, handler):
        data = handler(self)
        if self.scope == "all":
            data.pop("scope", None)
        return data


class MaterialUse(StrictModel):
    lot_id: UUID
    quantity: Quantity
    unit: str = Field(min_length=1, max_length=40)


class ExecutionSourceRecord(StrictModel):
    """Internal typed manual envelope; not a pull/import catalogue entry."""

    object_type: Literal["execution"] = "execution"
    project_id: UUID
    source: SourceRef
    work_order_id: UUID
    unit_id: UUID | None = None
    material_lot_ids: list[UUID] = Field(default_factory=list, max_length=200)
    occurred_at: datetime
    _aware = field_validator("occurred_at")(require_timezone)


class RecordExecution(WorkflowCommand):
    action: Literal["execution.record"]
    source: SourceRef
    work_order_id: UUID
    sn: str = Field(min_length=1, max_length=200)
    station: str = Field(min_length=1, max_length=200)
    route_version: str = Field(min_length=1, max_length=200)
    program_version: str = Field(min_length=1, max_length=200)
    firmware_version: str = Field(min_length=1, max_length=200)
    material_uses: list[MaterialUse] = Field(default_factory=list, max_length=200)
    result: Literal["pass", "fail"]
    occurred_at: datetime
    supersedes_event_id: UUID | None = None
    rework_order_id: UUID | None = None
    _aware = field_validator("occurred_at")(require_timezone)


class TestEvidenceScope(StrictModel):
    route_fingerprint: str
    test_version: str
    program_version: str
    firmware_version: str
    equipment_check_id: UUID


class RecordFirstArticle(WorkflowCommand):
    action: Literal["first_article.record"]
    work_order_id: UUID
    unit_ids: list[UUID] = Field(min_length=1, max_length=500)
    test_ids: list[UUID] = Field(min_length=1, max_length=500)
    inspection_id: str = Field(min_length=1, max_length=200)


class UnitTestView(StrictModel):
    id: UUID
    attempt: int
    outcome: Literal["pass", "fail"]
    rework_order_id: UUID | None
    occurred_at: datetime


class UnitValue(DomainValue):
    freeze_requested: Literal["frozen", "unfrozen"] | None = None
    freeze_confirmed: Literal["frozen", "unfrozen"] | None = None
    freeze_pending: bool = False
    tests: list[UnitTestView] = Field(default_factory=list)
    test_total: int = 0
    first_pass: bool | None = None
    scrapped: bool = False
    final_good: bool = False
    kind: Literal["unit"] = "unit"
    id: UUID
    project_id: UUID
    work_order_id: UUID
    revision_id: UUID
    sn: str
    state: Literal["registered", "start_pending", "running", "stopped"]
    mode: Literal["trial", "bulk"] | None
    accepted_start_id: UUID | None
    authority_start_accepted: bool
    execution_event_ids: list[UUID]
    execution_event_total: int
    execution_events: list["ExecutionEventView"]


class HeldStartScope(StrictModel):
    id: UUID
    mode: Literal["trial", "bulk"]
    sns: list[str]
    exchange_id: UUID
    receipt_id: UUID


class MaterialConsumptionView(StrictModel):
    lot_id: UUID
    material_id: str
    owner_id: str
    quantity: Quantity
    unit: str


class ExecutionEventView(StrictModel):
    id: UUID
    claimed_sn: str
    source: SourceRef | None
    status: Literal["accepted", "rejected"]
    reason: str
    station: str
    route_version: str
    program_version: str
    firmware_version: str
    result: Literal["pass", "fail"]
    rework_order_id: UUID | None = None
    route_kind: Literal["initial", "rework"]
    supersedes_event_id: UUID | None
    occurred_at: datetime
    recorded_at: datetime
    material_uses: list[MaterialConsumptionView]


class InterruptionValue(DomainValue):
    kind: Literal["interruption"] = "interruption"
    id: UUID
    work_order_id: UUID
    reason: str
    exception_id: UUID | None
    exception_kind: Literal["S3", "S4", "other"]
    requested_at: datetime
    authority_stopped_at: datetime | None
    resolved_at: datetime | None
    trial_resumed_at: datetime | None
    superseded_by: UUID | None
    plan_id: UUID | None
    stop_exchange_id: UUID
    recovery_start_id: UUID | None
    resume_exchange_id: UUID | None
    stop_exchange_ids: list[UUID]
    resume_exchange_ids: list[UUID]
