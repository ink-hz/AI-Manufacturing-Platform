"""Test, equipment and counterparty facts preserve independent source lineage."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from ..contracts import StrictModel
from ..laboratory_evidence import Parameter, RawEvidence
from ..quality_models import Measurement
from .core_models import (
    AwareTime,
    Digest,
    Name,
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


class SnapshotData(StrictModel):
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
    fact_type: Literal["plc.readback"] = "plc.readback"


class CustomerApproveRevision(CustomerApprovalData):
    operation: Literal["customer.approve_revision"] = "customer.approve_revision"


class CustomerApproveRevisionFact(CustomerApprovalData):
    fact_type: Literal["customer.customer_approval"] = "customer.customer_approval"


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


class BiRefresh(SnapshotData):
    operation: Literal["bi.refresh"] = "bi.refresh"


class BiRefreshFact(SnapshotData):
    fact_type: Literal["bi.snapshot"] = "bi.snapshot"
