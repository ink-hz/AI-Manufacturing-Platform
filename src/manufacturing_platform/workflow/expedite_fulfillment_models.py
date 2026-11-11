"""A point-in-time check, distinct from a coordination outcome."""
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from .contracts import NonnegativeQuantity, StrictModel


class ExpediteFulfillmentCheck(StrictModel):
    schema_version: Literal[1] = 1
    can_fulfill: bool
    evaluated_at: AwareDatetime
    project_version: int
    requirement_id: UUID
    current_requirement_id: UUID | None
    required: NonnegativeQuantity
    qualified: NonnegativeQuantity | None
    usable_reserved: NonnegativeQuantity
    line_received: NonnegativeQuantity | None
    remaining_to_receive: NonnegativeQuantity | None
    unit: str
    blocking_reasons: list[str] = Field(default_factory=list)
    evidence_refs: dict[str, list[str]] = Field(default_factory=dict)
    evidence_snapshots: dict[str, list[dict[str, str | None]]] = Field(default_factory=dict)
