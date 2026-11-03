"""Test, equipment and counterparty facts preserve independent source lineage."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from ..contracts import StrictModel
from ..laboratory_evidence import Parameter, RawEvidence
from ..quality_models import Measurement
from .core_models import (
    AwareTime,
    Digest,
    Name,
    SystemId,
    SourceKey,
    Text,
)
from .enterprise_models import ReturnData


class MockRawEvidence(RawEvidence):
    origin: Literal["demo"] = "demo"


class RawArtifactRef(StrictModel):
    """A project-scoped product-test object key, never a URL or filesystem path.

    The product-test adapter resolves this key and verifies the accompanying
    artifact_checksum against the exact stored bytes before emitting a fact.
    """

    system: Literal["product_test"] = "product_test"
    project_id: UUID
    artifact_id: UUID
    version: int = Field(strict=True, ge=1)
    reference: str = Field(
        min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )


class ArtifactEvidenceData(StrictModel):
    artifact_ref: RawArtifactRef
    artifact_checksum: Digest


class TestData(ArtifactEvidenceData):
    work_order_id: UUID
    unit_id: UUID
    revision_id: UUID
    plan_id: UUID
    run_id: UUID
    request: SourceKey
    station: Name
    test_version: Name
    program_version: Name
    firmware_version: Name
    algorithm_version: Name
    equipment: Name
    fixture: Name
    attempt: int = Field(strict=True, ge=1)
    result: Literal["pass", "fail"]
    measurements: list[Measurement] = Field(min_length=1, max_length=200)
    raw: MockRawEvidence
    occurred_at: AwareTime
    rework_order_id: UUID | None = None


class CalibrationData(ArtifactEvidenceData):
    run_id: UUID
    unit_id: UUID
    algorithm_version: Name
    parameters: list[Parameter] = Field(min_length=1, max_length=200)
    equipment: Name
    source_identity: Name
    source_version: Name
    evidence: Text


class EquipmentData(StrictModel):
    equipment: Name
    state: Literal["available", "unavailable", "maintenance"]
    program_version: Name
    process_request: SourceKey
    observed_at: AwareTime
    evidence: Text


class SampleData(StrictModel):
    equipment: Name
    work_order_id: UUID
    unit_id: UUID
    mes_session: SourceKey
    program_version: Name
    parameters: list[Parameter] = Field(min_length=1, max_length=200)
    observed_at: AwareTime
    evidence: Text


class ReadbackData(StrictModel):
    calibration: SourceKey
    run_id: UUID
    unit_id: UUID
    equipment: Name
    source_identity: Name
    source_version: Name
    parameters: list[Parameter] = Field(min_length=1, max_length=200)
    observed_at: AwareTime
    evidence: Text

    @model_validator(mode="after")
    def independent_source(self):
        if (
            self.calibration.system != "product_test"
            or self.calibration.object_type != "calibration"
        ):
            raise ValueError("product-test calibration source required")
        return self


class CustomerApprovalData(StrictModel):
    revision_id: UUID
    revision: SourceKey
    customer_id: Name
    decision: Literal["approved", "rejected", "unknown"]
    external_signer: Name
    signed_at: AwareTime
    evidence: Text


class DeliveryClaimData(ReturnData):
    decision: Literal["accepted", "rejected", "partial"]
    accepted_unit_ids: list[UUID] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def explicit_partial(self):
        selected = {u.unit_id for u in self.units}
        accepted = set(self.accepted_unit_ids)
        if len(accepted) != len(self.accepted_unit_ids) or not accepted <= selected:
            raise ValueError("Accepted serial subset must be unique and within claim")
        if self.decision == "partial" and not (0 < len(accepted) < len(selected)):
            raise ValueError(
                "Partial claim requires explicit nonempty strict accepted subset"
            )
        if self.decision == "rejected" and accepted:
            raise ValueError("Rejected claim cannot accept serials")
        if self.decision == "accepted" and accepted and accepted != selected:
            raise ValueError("Accepted claim must cover its complete scope")
        return self


class SerialMappingData(StrictModel):
    unit_id: UUID
    shipment: SourceKey
    customer_id: Name
    customer_serial: Name
    external_signer: Name
    evidence: Text


class MetricDefinition(StrictModel):
    metric: Literal["first_pass_yield", "final_yield", "shortage", "delivery"]
    formula_version: Name
    numerator: int = Field(strict=True, ge=0)
    denominator: int = Field(strict=True, ge=0)
    sources: list[SourceKey] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique(self):
        keys = [
            (s.system, s.object_type, s.external_id, s.version) for s in self.sources
        ]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate metric lineage")
        return self


class SourceCutoff(StrictModel):
    system: SystemId
    sequence: int = Field(strict=True, ge=0)


class SnapshotData(StrictModel):
    snapshot_version: int = Field(strict=True, ge=1)
    source_vector: list[SourceCutoff] = Field(min_length=1, max_length=15)
    workflow_version: int = Field(strict=True, ge=1)
    cohort_unit_ids: list[UUID] = Field(max_length=1000)
    cutoff: AwareTime
    metrics: list[MetricDefinition] = Field(min_length=1, max_length=20)


class ProductTestRun(TestData):
    operation: Literal["product_test.run"] = "product_test.run"


class ProductTestRunFact(TestData):
    fact_type: Literal["product_test.test"] = "product_test.test"


class ProductTestCalibrate(CalibrationData):
    operation: Literal["product_test.calibrate"] = "product_test.calibrate"


class ProductTestCalibrateFact(CalibrationData):
    fact_type: Literal["product_test.calibration"] = "product_test.calibration"


class PlcSetState(EquipmentData):
    operation: Literal["plc.set_state"] = "plc.set_state"


class PlcSetStateFact(EquipmentData):
    fact_type: Literal["plc.equipment"] = "plc.equipment"


class PlcSample(SampleData):
    operation: Literal["plc.sample"] = "plc.sample"


class PlcSampleFact(SampleData):
    fact_type: Literal["plc.sample"] = "plc.sample"


class PlcReadback(ReadbackData):
    operation: Literal["plc.readback"] = "plc.readback"


class PlcReadbackFact(ReadbackData):
    parameter_digest: Digest
    confirmation_matches: bool = Field(strict=True)
    fact_type: Literal["plc.readback"] = "plc.readback"


class CustomerApproveRevision(CustomerApprovalData):
    operation: Literal["customer.approve_revision"] = "customer.approve_revision"


class CustomerApproveRevisionFact(CustomerApprovalData):
    fact_type: Literal["customer.customer_approval"] = "customer.customer_approval"


class CustomerReceiveShipment(DeliveryClaimData):
    operation: Literal["customer.receive_shipment"] = "customer.receive_shipment"


class CustomerReceiveShipmentFact(DeliveryClaimData):
    fact_type: Literal["customer.delivery_receipt"] = "customer.delivery_receipt"


class CustomerConfirmDelivery(DeliveryClaimData):
    operation: Literal["customer.confirm_delivery"] = "customer.confirm_delivery"


class CustomerConfirmDeliveryFact(DeliveryClaimData):
    fact_type: Literal["customer.acceptance"] = "customer.acceptance"


class CustomerMapSerial(SerialMappingData):
    operation: Literal["customer.map_serial"] = "customer.map_serial"


class CustomerMapSerialFact(SerialMappingData):
    fact_type: Literal["customer.serial_mapping"] = "customer.serial_mapping"


class OverseasReceiveShipment(DeliveryClaimData):
    operation: Literal["overseas.receive_shipment"] = "overseas.receive_shipment"


class OverseasReceiveShipmentFact(DeliveryClaimData):
    fact_type: Literal["overseas.delivery_receipt"] = "overseas.delivery_receipt"


class OverseasReportReturn(ReturnData):
    operation: Literal["overseas.report_return"] = "overseas.report_return"


class OverseasReportReturnFact(ReturnData):
    fact_type: Literal["overseas.return_claim"] = "overseas.return_claim"


class BiRefresh(StrictModel):
    operation: Literal["bi.refresh"] = "bi.refresh"


class BiRefreshFact(SnapshotData):
    fact_type: Literal["bi.snapshot"] = "bi.snapshot"


class ProductTestPrepareArtifact(StrictModel):
    operation: Literal["product_test.prepare_artifact"] = (
        "product_test.prepare_artifact"
    )
    run_id: UUID
    template: Literal["pass-v1", "fail-v1", "calibration-v1"]


class PreparedTest(TestData):
    kind: Literal["test"] = "test"


class PreparedCalibration(CalibrationData):
    kind: Literal["calibration"] = "calibration"


class ProductTestArtifactFact(StrictModel):
    fact_type: Literal["product_test.artifact"] = "product_test.artifact"
    template: Literal["pass-v1", "fail-v1", "calibration-v1"]
    prepared: Annotated[PreparedTest | PreparedCalibration, Field(discriminator="kind")]


class EquipmentRecord(StrictModel):
    confirmation_state: Literal["matched", "mismatched", "not_applicable"] = (
        "not_applicable"
    )
    kind: Literal["equipment", "sample", "readback"]
    project_id: UUID
    source_key: SourceKey
    payload_hash: Digest
    observation: Annotated[
        PlcSetStateFact | PlcSampleFact | PlcReadbackFact,
        Field(discriminator="fact_type"),
    ]
    parameter_digest: Digest | None = None

    @property
    def equipment(self):
        return self.observation.equipment


class PreparedArtifactRecord(StrictModel):
    kind: Literal["artifact"] = "artifact"
    project_id: UUID
    source_key: SourceKey
    payload_hash: Digest
    artifact: ProductTestArtifactFact


class ExternalClaimRecord(StrictModel):
    kind: Literal["external_claim"] = "external_claim"
    project_id: UUID
    source_key: SourceKey
    payload_hash: Digest
    claim: Annotated[
        CustomerConfirmDeliveryFact
        | CustomerReceiveShipmentFact
        | OverseasReceiveShipmentFact
        | OverseasReportReturnFact,
        Field(discriminator="fact_type"),
    ]
    accepted_unit_ids: list[UUID] = Field(max_length=500)
    issue_unit_ids: list[UUID] = Field(max_length=500)


class MetricSnapshot(StrictModel):
    kind: Literal["snapshot"] = "snapshot"
    project_id: UUID
    source_key: SourceKey
    payload_hash: Digest
    snapshot: BiRefreshFact
