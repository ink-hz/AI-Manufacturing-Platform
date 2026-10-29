"""Trusted typed extensions; registration is Python composition, never an HTTP API."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Connection
from typing import (
    TYPE_CHECKING,
    Annotated,
    Generic,
    Literal,
    TypeVar,
    Union,
    get_args,
    get_origin,
)
from uuid import UUID

from pydantic import Field, TypeAdapter

from .contracts import Actor, CommandBase, Dataset, DomainError, MutationResult

if TYPE_CHECKING:
    from .exchanges import ExchangeService


BUSINESS_ROLES = frozenset(
    {"project_owner", "engineering", "planner", "supply", "production", "quality", "warehouse"}
)
BUSINESS_QUALIFICATIONS = frozenset(
    {"inspection", "disposition", "quality_release", "readiness_verification"}
)


WorkflowAction = Literal[
    "demand.record",
    "demand.review",
    "order.register",
    "order.change",
    "order.resolve_change",
    "order.allocate",
    "engineering.revision",
    "contract.agree",
    "engineering.handoff",
    "engineering.customer_approval",
    "work_order.register",
    "readiness.record",
    "plan.receive",
    "supply.commit",
    "supply.receive",
    "supply.inspect",
    "material.define",
    "reservation.request",
    "exchange.dispatch",
    "exchange.query",
    "source.pull",
    "source.import",
    "source.import_file",
    "exchange.reconcile",
    "production.start",
    "execution.record",
    "unit.register",
    "production.interrupt",
    "production.resume",
    "first_article.record",
    "eco.open",
    "eco.disposition",
    "eco.switch",
    "eco.close",
    "test.record",
    "nonconformance.open",
    "nonconformance.disposition",
    "rework.complete",
    "release.decide",
    "shipment.request",
    "delivery.sign",
    "delivery.accept",
    "delivery.resolve_issue",
    "closure.record",
    "ownership.reconcile",
    "ownership.movement",
    "stock_basis.reconcile",
    "freeze.request",
    "rma.open",
    "capa.update",
    "capa.close",
    "project.stage",
]


class WorkflowCommand(CommandBase):
    action: WorkflowAction


@dataclass(frozen=True)
class CommandContext:
    actor: Actor
    project_id: UUID
    project_version: int
    now: datetime
    dataset: Dataset
    # Prepare writes only; the orchestrator performs I/O after the transaction closes.
    exchange_service: "ExchangeService | None" = None
    subject_profiles: dict[str, str] | None = None


C = TypeVar("C", bound=WorkflowCommand)


@dataclass(frozen=True)
class CommandRegistration(Generic[C]):
    model: type[C]
    roles: frozenset[str]
    qualifications: frozenset[str]
    handler: Callable[[Connection, CommandContext, C], MutationResult]


def literal_tag(model, field, allowed):
    annotation = model.model_fields[field].annotation
    tags = get_args(annotation)
    if (
        get_origin(annotation) is not Literal
        or len(tags) != 1
        or tags[0] not in allowed
    ):
        raise ValueError(f"{field} must be one supported Literal")
    if model.model_config.get("extra") != "forbid":
        raise ValueError("extension models must forbid extra fields")
    return tags[0]


class CommandRegistry:
    def __init__(self):
        self._entries: dict[str, CommandRegistration] = {}
        self._adapter: TypeAdapter | None = None

    def __len__(self):
        return len(self._entries)

    def register(
        self,
        model: type[C],
        *,
        roles: set[str],
        qualifications: set[str],
        handler: Callable[[Connection, CommandContext, C], MutationResult],
    ):
        if not issubclass(model, WorkflowCommand):
            raise TypeError("command must extend WorkflowCommand")
        action = literal_tag(model, "action", get_args(WorkflowAction))
        if action in self._entries or not roles:
            raise ValueError("duplicate action or empty role policy")
        if not roles <= BUSINESS_ROLES or not qualifications <= BUSINESS_QUALIFICATIONS:
            raise ValueError("invalid action policy")
        self._entries[action] = CommandRegistration(
            model, frozenset(roles), frozenset(qualifications), handler
        )
        models = tuple(entry.model for entry in self._entries.values())
        self._adapter = TypeAdapter(
            Annotated[Union[models], Field(discriminator="action")]  # noqa: UP007 - runtime union
        )

    def registration(self, action: str) -> CommandRegistration:
        entry = self._entries.get(action)
        if entry is None:
            raise DomainError("UNSUPPORTED_ACTION", 422, "Unsupported action")
        return entry

    @staticmethod
    def permits(entry, roles, qualifications):
        return bool(entry.roles.intersection(roles)) and entry.qualifications.issubset(
            qualifications
        )

    def allowed_actions(self, roles, qualifications):
        return [
            action
            for action, entry in self._entries.items()
            if self.permits(entry, roles, qualifications)
        ]

    def parse(self, value: object) -> WorkflowCommand:
        if isinstance(value, WorkflowCommand):
            value = value.model_dump(mode="json")
        if not isinstance(value, dict) or not isinstance(value.get("action"), str):
            raise DomainError("INVALID_COMMAND", 422, "Invalid command")
        self.registration(value["action"])
        return self._adapter.validate_python(value)


COMMAND_REGISTRY = CommandRegistry()
