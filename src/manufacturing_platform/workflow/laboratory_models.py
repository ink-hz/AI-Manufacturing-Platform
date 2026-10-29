"""Strict laboratory command and object contracts; no hardware control claims."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from .commands import WorkflowCommand
from .contracts import DomainValue, SourceRef
from .engineering_models import TestSpec
from .execution_models import TestEvidenceScope
from .genealogy_models import Attribution, ComponentHistory, Name, Origin, Text
from .laboratory_evidence import Parameter, RawEvidence
from .quality_models import Measurement


class PublishTestPlan(WorkflowCommand):
    action: Literal["test_plan.publish"]
    revision_id: UUID
    level: Name
    station: Name
    equipment: Name
    fixture: Name
    algorithm_version: Name


class StartTestRun(WorkflowCommand):
    action: Literal["test_run.start"]
    plan_id: UUID
    unit_id: UUID
    rework_order_id: UUID | None = None


class FinishTestRun(WorkflowCommand):
    action: Literal["test_run.finish"]
    run_id: UUID
    state: Literal["completed", "aborted", "invalid"]
    source: SourceRef
    measurements: list[Measurement] = Field(default_factory=list, max_length=200)
    raw: RawEvidence
    reason: Text | None = None

    @model_validator(mode="after")
    def consistent(self):
        if self.source.mode != "manual":
            raise ValueError("laboratory acquisition is manually registered evidence")
        if self.state == "completed" and not self.measurements:
            raise ValueError("completed run requires measurements")
        if self.state != "completed" and (self.measurements or not self.reason):
            raise ValueError(
                "incomplete run requires reason and cannot produce measurements"
            )
        return self


class RecordCalibration(WorkflowCommand):
    action: Literal["calibration.record"]
    run_id: UUID
    algorithm_version: Name
    parameters: list[Parameter] = Field(min_length=1, max_length=200)
    source_identity: Name
    source_version: Name
    origin: Origin
    evidence: Text


class ConfirmCalibration(WorkflowCommand):
    action: Literal["calibration.confirm"]
    calibration_id: UUID
    readback: list[Parameter] = Field(min_length=1, max_length=200)
    origin: Origin
    source_identity: Name
    source_version: Name
    evidence: Text


class InstallComponent(WorkflowCommand):
    action: Literal["component.install"]
    unit_id: UUID
    material_id: Name
    component_serial: Name
    lot_id: UUID | None = None
    origin: Origin
    evidence: Text


class RemoveComponent(WorkflowCommand):
    action: Literal["component.remove"]
    component_link_id: UUID
    evidence: Text


class AliasUnit(WorkflowCommand):
    action: Literal["unit.alias"]
    unit_id: UUID
    customer_serial: Name
    evidence: Text


class TestPlan(DomainValue):
    kind: Literal["test_plan"] = "test_plan"
    id: UUID
    revision_id: UUID
    level: Name
    station: Name
    equipment: Name
    fixture: Name
    algorithm_version: Name
    test_spec: TestSpec
    firmware_version: Name
    revision_hash: Name
    actor_id: UUID
    recorded_at: datetime
    state: Literal["published"] = "published"


class RunFinish(Attribution):
    source: SourceRef
    state: Literal["completed", "aborted", "invalid"]
    measurements: list[Measurement]
    raw: RawEvidence
    raw_digest: str
    outcome: Literal["pass", "fail"] | None
    test_id: UUID | None


class TestRun(DomainValue):
    kind: Literal["test_run"] = "test_run"
    id: UUID
    plan_id: UUID
    unit_id: UUID
    revision_id: UUID
    rework_order_id: UUID | None
    attempt: int
    accepted_start_id: UUID
    scope: TestEvidenceScope
    execution_event_ids: list[UUID]
    actor_id: UUID
    recorded_at: datetime
    state: Literal["running", "completed", "aborted", "invalid"] = "running"
    outcome: Literal["pass", "fail"] | None = None
    test_id: UUID | None = None
    raw: RawEvidence | None = None
    raw_digest: str | None = None
    finish: RunFinish | None = None


class CalibrationConfirmation(Attribution):
    origin: Origin
    source_identity: Name
    source_version: Name
    readback: list[Parameter]
    parameter_digest: str


class Calibration(DomainValue):
    kind: Literal["calibration"] = "calibration"
    id: UUID
    run_id: UUID
    unit_id: UUID
    algorithm_version: Name
    parameters: list[Parameter]
    parameter_digest: str
    source_identity: Name
    source_version: Name
    origin: Origin
    evidence: Text
    actor_id: UUID
    recorded_at: datetime
    state: Literal["pending", "confirmed"] = "pending"
    confirmation: CalibrationConfirmation | None = None


class ComponentLink(ComponentHistory, DomainValue):
    kind: Literal["component_link"] = "component_link"
