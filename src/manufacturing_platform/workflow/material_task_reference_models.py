"""Server-resolved, typed references to existing material observations."""
from typing import Annotated, Literal
from uuid import UUID
from pydantic import AwareDatetime, Field
from .contracts import StrictModel
from .integrations.core_models import SourceKey
from .quantity_provenance import Origin, Environment


class ArrivalTaskReference(StrictModel):
    kind: Literal['arrival']
    id: UUID
    version: int = Field(strict=True, ge=1)


class MesComponentTaskReference(StrictModel):
    kind: Literal['mes_component']
    binding_id: UUID
    snapshot_id: UUID
    component_key: str = Field(min_length=1, max_length=128)


class ReceiptTaskReference(StrictModel):
    kind: Literal['receipt']
    id: UUID


class SourceReceiptTaskReference(StrictModel):
    kind: Literal['source_receipt']
    source_key: SourceKey


TaskReference = Annotated[ArrivalTaskReference | MesComponentTaskReference | ReceiptTaskReference | SourceReceiptTaskReference, Field(discriminator='kind')]


class TaskReferenceEvidence(StrictModel):
    reference: TaskReference
    scope_key: str
    title: str
    origin: Origin
    environment: Environment
    system: str | None = None
    source_type: str | None = None
    external_id: str | None = None
    version: int | str | None = None
    namespace: str | None = None
    occurred_at: AwareDatetime | None = None
    collected_at: AwareDatetime | None = None
    work_order_id: UUID | None = None
    material_id: str | None = None
    material_lot_id: UUID | None = None
    receipt_id: UUID | None = None
    unit: str | None = None


class ResolvedTaskReference(TaskReferenceEvidence):
    requirement_id: UUID | None = None
    task_kinds: list[Literal['verify', 'iqc']]
