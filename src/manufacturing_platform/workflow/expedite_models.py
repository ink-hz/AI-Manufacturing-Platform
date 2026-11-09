"""Strict expedite commands; urgency is a coordination fact, never a quantity."""
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from .commands import WorkflowCommand
from .contracts import DomainValue, SourceRef, StrictModel
from .introduction_models import Name, Text


class OpenExpedite(WorkflowCommand):
    action: Literal["expedite.open"]
    requirement_id: UUID
    reason: Text
    impact: Text


class ProgressExpedite(WorkflowCommand):
    action: Literal["expedite.progress"]
    expedite_id: UUID
    note: Text


class CloseExpedite(WorkflowCommand):
    action: Literal["expedite.close"]
    expedite_id: UUID
    outcome: Literal["fulfilled", "false_alarm", "superseded"]
    reason: Text


class ExpediteActorFact(StrictModel):
    actor_id: UUID
    actor_name: Name
    recorded_at: AwareDatetime


class ExpediteProgressEntry(ExpediteActorFact):
    note: Text


class ExpediteClosure(ExpediteActorFact):
    outcome: Literal["fulfilled", "false_alarm", "superseded"]
    reason: Text


class ExpediteMilestones(StrictModel):
    """Derived from linked facts at read time; a missing fact stays None."""

    opened_at: AwareDatetime
    arrival_at: AwareDatetime | None = None
    receipt_at: AwareDatetime | None = None
    inspection_at: AwareDatetime | None = None
    handoff_at: AwareDatetime | None = None


class MaterialExpedite(DomainValue):
    kind: Literal["material_expedite"] = "material_expedite"
    id: UUID
    state: Literal["open", "closed"]
    requirement_id: UUID
    work_order_id: UUID
    material_id: str
    owner_id: str
    expedite_number: Name
    reason: Text
    impact: Text
    opened_by: UUID
    opened_by_name: Name
    recorded_at: AwareDatetime
    source: SourceRef
    milestones: ExpediteMilestones
    progress: list[ExpediteProgressEntry] = Field(default_factory=list)
    closure: ExpediteClosure | None = None
