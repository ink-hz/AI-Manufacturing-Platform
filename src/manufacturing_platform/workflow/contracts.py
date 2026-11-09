"""Stable workflow data contracts; host identity is never obtained from payloads."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Actor(StrictModel):
    user_id: UUID
    display_name: str = Field(max_length=200)
    read_only: bool
    configuration_admin: bool


class Unit(StrictModel):
    code: str = Field(min_length=1, max_length=40)
    scale: int = Field(strict=True, ge=0, le=6)


class ContractPolicy(StrictModel):
    customer_approval_required: StrictBool | Literal["unknown"]
    customer_release_required: StrictBool | Literal["unknown"]
    acceptance_required: StrictBool | Literal["unknown"]
    customer_revision: str = Field(min_length=1, max_length=200)
    internal_revision: str = Field(min_length=1, max_length=200)
    material_ownership_rules: str = Field(min_length=1, max_length=1000)


def parse_quantity(value):
    amount = parse_nonnegative_quantity(value)
    if amount <= 0:
        raise ValueError("quantity must be positive")
    return amount


def parse_nonnegative_quantity(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 40:
        raise ValueError("quantity must be a bounded decimal string")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid quantity") from exc
    if (
        not amount.is_finite()
        or amount < 0
        or (amount == 0 and amount.is_signed())
        or format(amount, "f") != value
    ):
        raise ValueError("quantity must be a nonnegative canonical decimal")
    return amount


Quantity = Annotated[Decimal, BeforeValidator(parse_quantity)]
NonnegativeQuantity = Annotated[Decimal, BeforeValidator(parse_nonnegative_quantity)]


class ProjectCreate(StrictModel):
    operation_id: UUID
    name: str = Field(min_length=1, max_length=200)
    line_id: str = Field(min_length=1, max_length=200)
    product: str = Field(min_length=1, max_length=200)
    customer_id: str = Field(min_length=1, max_length=200)
    mode: Literal["internal", "oem"]
    unit: Unit
    quantity: Quantity
    contract: ContractPolicy
    legacy_project_id: UUID | None = None

    @field_validator("quantity")
    @classmethod
    def valid_scale(cls, value, info):
        unit = info.data.get("unit")
        if unit and value.as_tuple().exponent < -unit.scale:
            raise ValueError("quantity exceeds unit precision")
        if unit and value * (10**unit.scale) > 2**63 - 1:
            raise ValueError("quantity out of range")
        return value


class CommandBase(StrictModel):
    operation_id: UUID
    expected_version: int = Field(strict=True, ge=1)


class CommandResult(StrictModel):
    # Live read metadata; never rewrites the immutable saved intent result.
    current_project_version: int | None = Field(default=None, strict=True, ge=1)
    operation_id: UUID
    project_id: UUID
    project_version: int
    object_type: str
    object_id: UUID
    exchange_id: UUID | None = None
    replayed: bool = False


class GrantScope(StrictModel):
    kind: Literal["project"]
    project_id: UUID


class GrantChange(CommandBase):
    scope: GrantScope
    roles: list[
        Literal[
            "project_owner",
            "engineering",
            "planner",
            "supply",
            "production",
            "quality",
            "warehouse",
        ]
    ] = Field(max_length=20)
    qualifications: list[
        Literal[
            "inspection", "disposition", "quality_release", "readiness_verification"
        ]
    ] = Field(max_length=20)
    active: bool = Field(strict=True)
    evidence: str = Field(min_length=1, max_length=2000)


class GrantView(StrictModel):
    display_name: str | None = None
    scope: GrantScope
    user_id: UUID
    roles: list[str]
    qualifications: list[str]
    active: bool


class ScopeGrantView(GrantView):
    """A grant always carries its explicit project boundary."""


class ProjectStageView(StrictModel):
    stage: Literal["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"]
    status: Literal["pending", "active", "blocked", "complete"]
    reason: str | None = Field(default=None, max_length=2000)


class ProjectQualitySummary(StrictModel):
    first_tested: int
    first_passed: int
    final_good: int
    scrapped: int
    open_nonconformances: int


class ClosureProgress(StrictModel):
    status: Literal["blocked", "ready", "closed"]
    recorded_count: int
    blocking_reasons: list[str]


class ProgressSummary(StrictModel):
    stages: list[ProjectStageView]
    blocking_objects: list["ObjectSummary"]
    blockers_truncated: bool
    fulfillment: ClosureProgress
    quality: ClosureProgress
    cost: ClosureProgress


class OwnedTask(StrictModel):
    category: Literal["readiness", "source", "acceptance", "business"]
    title: str
    target: "ObjectSummary"
    owner_id: UUID | None = None
    owner_name: str


class ActorTaskPage(StrictModel):
    """Total counts available tasks within each project's existing bounded scope."""

    items: list[OwnedTask]
    total: int
    limit: int
    offset: int
    truncated: bool


class ProjectDetail(StrictModel):
    tasks: list[OwnedTask] = Field(default_factory=list)
    tasks_truncated: bool = False

    release_kinds: list[Literal["manufacturing", "quality", "customer"]] = Field(
        default_factory=list
    )
    progress: ProgressSummary | None = None
    quality_summary: ProjectQualitySummary | None = None
    allowed_actions: list[str] = Field(default_factory=list)
    id: UUID
    version: int
    name: str
    line_id: str
    product: str
    customer_id: str
    mode: Literal["internal", "oem"]
    unit: Unit
    quantity: Decimal
    contract: ContractPolicy
    legacy_project_id: UUID | None = None
    stages: list[ProjectStageView]
    summary: "ProjectQuantitySummary"


class ProjectQuantitySummary(StrictModel):
    original_order_quantity: NonnegativeQuantity
    current_order_quantity: NonnegativeQuantity
    allocated: NonnegativeQuantity
    produced_good: NonnegativeQuantity
    shipped: NonnegativeQuantity
    signed: NonnegativeQuantity
    accepted: NonnegativeQuantity
    remaining_to_ship: NonnegativeQuantity
    remaining_to_accept: NonnegativeQuantity


class ObjectKind(str, Enum):
    authority_rule = "authority_rule"
    arrival = "arrival"
    material_handoff = "material_handoff"
    issue_mark = "issue_mark"
    material_expedite = "material_expedite"
    test_plan = "test_plan"
    test_run = "test_run"
    calibration = "calibration"
    component_link = "component_link"
    npi = "npi"
    npi_issue = "npi_issue"
    reusable_asset = "reusable_asset"
    asset_use = "asset_use"
    demand = "demand"
    order_line = "order_line"
    commitment_change = "commitment_change"
    work_order = "work_order"
    revision = "revision"
    plan = "plan"
    requirement = "requirement"
    commitment = "commitment"
    receipt = "receipt"
    material_lot = "material_lot"
    reservation = "reservation"
    exchange = "exchange"
    unit = "unit"
    interruption = "interruption"
    eco = "eco"
    test = "test"
    nonconformance = "nonconformance"
    rework = "rework"
    release = "release"
    shipment = "shipment"
    closure = "closure"
    rma = "rma"
    capa = "capa"
    exception = "exception"


def require_timezone(value: datetime | None) -> datetime | None:
    if value is not None and value.utcoffset() is None:
        raise ValueError("timezone required")
    return value


class SourceRef(StrictModel):
    system: str = Field(min_length=1, max_length=200)
    object_type: str = Field(min_length=1, max_length=200)
    external_id: str = Field(min_length=1, max_length=200)
    version: int = Field(strict=True, ge=1)
    mode: Literal["manual", "file", "mock", "api"]
    occurred_at: datetime
    collected_at: datetime
    cutoff: datetime | None = None
    evidence: str = Field(min_length=1, max_length=2000)

    @field_validator("system", "object_type", "external_id")
    @classmethod
    def source_identity_required(cls, value):
        if not value.strip():
            raise ValueError("source identity must not be blank")
        return value

    @field_validator("occurred_at", "collected_at", "cutoff")
    @classmethod
    def timezone_required(cls, value):
        return require_timezone(value)


class MaterialBalance(StrictModel):
    blocking_reasons: list[str] = Field(default_factory=list)
    required: NonnegativeQuantity
    in_transit: NonnegativeQuantity
    received: NonnegativeQuantity
    qualified: NonnegativeQuantity
    rejected: NonnegativeQuantity
    reserved: NonnegativeQuantity
    shortage: NonnegativeQuantity
    unit: str
    cutoff: str | None
    source_version: int


class ActionVariant(StrictModel):
    ready: bool | None = None
    blocking_reasons: list[str] = Field(default_factory=list)


class ActionCapability(StrictModel):
    action: str
    variants: dict[str, ActionVariant] = Field(default_factory=dict)


class ObjectSummary(StrictModel):
    action_capabilities: list[ActionCapability] = Field(default_factory=list)
    revision_family_id: str | None = None
    revision_id: UUID | None = None
    id: UUID
    kind: ObjectKind
    project_id: UUID
    title: str
    state: str
    quantity: NonnegativeQuantity | None = None
    unit: str | None = None
    source: SourceRef | None = None
    version: int
    blocking_reasons: list[str] = []
    next_actions: list[str] = []
    material_balance: MaterialBalance | None = None


class ObjectPage(StrictModel):
    items: list[ObjectSummary]
    total: int
    limit: int
    offset: int


class DomainValue(StrictModel):
    """Domains override kind with a single Literal and add their strict fields."""

    kind: ObjectKind


DomainT = TypeVar("DomainT", bound=DomainValue)


class ObjectRelation(StrictModel):
    relation: str = Field(min_length=1, max_length=80)
    project_id: UUID
    kind: ObjectKind
    id: UUID


class ObjectEvidence(StrictModel):
    reference: str = Field(min_length=1, max_length=2000)
    source: SourceRef | None = None


class ObjectHistory(StrictModel):
    event_id: int = Field(ge=1)
    actor_id: UUID
    action: str = Field(min_length=1, max_length=80)
    occurred_at: datetime
    recorded_at: datetime
    evidence: list[ObjectEvidence] = Field(default_factory=list)

    @field_validator("occurred_at", "recorded_at")
    @classmethod
    def timezone_required(cls, value):
        return require_timezone(value)


class ObjectDetail(StrictModel, Generic[DomainT]):
    summary: ObjectSummary
    value: DomainT
    relations: list[ObjectRelation]
    evidence: list[ObjectEvidence]
    history: list[ObjectHistory]

    @model_validator(mode="after")
    def matching_kind(self):
        if self.summary.kind != self.value.kind:
            raise ValueError("detail kind mismatch")
        if any(r.project_id != self.summary.project_id for r in self.relations):
            raise ValueError("cross-project relation")
        return self


class Dashboard(StrictModel):
    cards: list[ObjectSummary]
    project_ids: list[UUID]
    project_count: int = Field(ge=0)
    counts: dict[ObjectKind, int]


class Dataset(StrictModel):
    id: str = Field(min_length=1, max_length=200)
    mode: Literal["production", "demo", "test"]
    label: str = Field(min_length=1, max_length=200)


class MutationResult(StrictModel):
    object_type: ObjectKind | Literal["project"]
    object_id: UUID
    exchange_id: UUID | None = None


class DomainError(Exception):
    def __init__(self, code, status, message, fields=None, blocking_reasons=None):
        self.code, self.status, self.message = code, status, message
        self.fields = fields or {}
        self.blocking_reasons = blocking_reasons or []
        super().__init__(message)
