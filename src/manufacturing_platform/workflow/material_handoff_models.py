"""Strict commands and attributable, non-accounting material handoff facts."""
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime

from .commands import WorkflowCommand
from .contracts import DomainValue, NonnegativeQuantity, Quantity, SourceRef, StrictModel
from .introduction_models import Name, Text


class RecordMaterialHandoff(WorkflowCommand):
    action: Literal["material_handoff.record"]
    material_lot_id: UUID
    work_order_id: UUID | None = None
    quantity: Quantity
    unit: Name
    from_location: Name
    to_location: Name
    receiver_id: UUID
    occurred_at: AwareDatetime | None = None
    note: Text | None = None


class ReceiveMaterialHandoff(WorkflowCommand):
    action: Literal["material_handoff.receive"]
    handoff_id: UUID
    received_quantity: NonnegativeQuantity
    received_location: Name
    occurred_at: AwareDatetime | None = None
    note: Text | None = None


class ResolveMaterialHandoff(WorkflowCommand):
    action: Literal["material_handoff.resolve"]
    handoff_id: UUID
    resolution: Text


class CancelMaterialHandoff(WorkflowCommand):
    action: Literal["material_handoff.cancel"]
    handoff_id: UUID
    reason: Text


class HandoffActorFact(StrictModel):
    actor_id: UUID
    actor_name: Name
    recorded_at: AwareDatetime


class HandoffReceipt(HandoffActorFact):
    received_quantity: NonnegativeQuantity
    received_location: Name
    note: Text | None
    occurred_at: AwareDatetime


class HandoffResolution(HandoffActorFact):
    resolution: Text


class HandoffCancellation(HandoffActorFact):
    reason: Text


class MaterialHandoff(DomainValue):
    kind: Literal["material_handoff"] = "material_handoff"
    id: UUID
    state: Literal["pending", "received", "disputed", "resolved", "cancelled"]
    material_lot_id: UUID
    work_order_id: UUID | None
    handoff_number: Name
    quantity: Quantity
    unit: Name
    from_location: Name
    to_location: Name
    sender_id: UUID
    sender_name: Name
    receiver_id: UUID
    receiver_name: Name
    occurred_at: AwareDatetime
    recorded_at: AwareDatetime
    note: Text | None
    source: SourceRef
    receipt: HandoffReceipt | None = None
    resolution: HandoffResolution | None = None
    cancellation: HandoffCancellation | None = None
