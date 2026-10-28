"""Stable workflow data contracts; host identity is never obtained from payloads."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
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
    if not isinstance(value, str) or not 1 <= len(value) <= 40:
        raise ValueError("quantity must be a bounded decimal string")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid quantity") from exc
    if not amount.is_finite() or amount <= 0 or format(amount, "f") != value:
        raise ValueError("quantity must be a positive canonical decimal")
    return amount


Quantity = Annotated[Decimal, BeforeValidator(parse_quantity)]


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
    operation_id: UUID
    project_id: UUID
    project_version: int
    object_type: str
    object_id: UUID
    exchange_id: UUID | None = None
    replayed: bool = False


class GrantChange(CommandBase):
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
    qualifications: list[Literal["inspection", "disposition", "quality_release"]] = (
        Field(max_length=20)
    )
    active: bool = Field(strict=True)
    evidence: str = Field(min_length=1, max_length=2000)


class GrantView(StrictModel):
    user_id: UUID
    roles: list[str]
    qualifications: list[str]
    active: bool


class ProjectDetail(StrictModel):
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


class ObjectKind(str, Enum):
    demand = "demand"
    order_line = "order_line"
    commitment_change = "commitment_change"
    work_order = "work_order"
    revision = "revision"
    plan = "plan"
    requirement = "requirement"
    commitment = "commitment"
    material_lot = "material_lot"
    reservation = "reservation"
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

    @field_validator("occurred_at", "collected_at", "cutoff")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("timezone required")
        return value


class ObjectSummary(StrictModel):
    id: UUID
    kind: ObjectKind
    project_id: UUID
    title: str
    state: str
    quantity: Decimal | None = None
    unit: str | None = None
    source: SourceRef | None = None
    version: int
    blocking_reasons: list[str] = []
    next_actions: list[str] = []


class ObjectPage(StrictModel):
    items: list[ObjectSummary]
    total: int
    limit: int
    offset: int


class ObjectDetail(StrictModel):
    summary: ObjectSummary


class Dashboard(StrictModel):
    cards: list[ObjectSummary]
    project_ids: list[UUID]


class DomainError(Exception):
    def __init__(self, code, status, message, fields=None, blocking_reasons=None):
        self.code, self.status, self.message = code, status, message
        self.fields = fields or {}
        self.blocking_reasons = blocking_reasons or []
        super().__init__(message)
