"""Attributable append-only unit identity and component history."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from .contracts import SourceRef, StrictModel

Name = Annotated[str, Field(min_length=1, max_length=200, pattern=r"\S")]
Text = Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]
Origin = Literal["manual", "demo"]


class Attribution(StrictModel):
    actor_id: UUID
    recorded_at: datetime
    evidence: Text


class UnitAlias(Attribution):
    id: UUID
    customer_id: Name
    customer_serial: Name


class ComponentHistory(Attribution):
    source: SourceRef | None = Field(default=None, exclude_if=lambda v: v is None)
    id: UUID
    unit_id: UUID
    material_id: Name
    component_serial: Name
    lot_id: UUID | None = None
    origin: Origin
    state: Literal["installed", "removed"]
    removal: Attribution | None = None
