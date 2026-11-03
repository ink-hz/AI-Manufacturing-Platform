"""Closed network envelopes. Legacy ExternalRequest/ExternalReceipt are untouched."""

from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import Field, TypeAdapter, model_validator

from ..commands import WorkflowCommand
from ..contracts import ObjectKind, SourceRef, StrictModel
from .core_models import (
    AwareTime,
    ConnectorId,
    Digest,
    MesAssemble,
    MesAssembleFact,
    MesComplete,
    MesCompleteFact,
    MesContain,
    MesContainFact,
    MesDeliveryContext,
    MesInspect,
    MesInspectFact,
    MesInterrupt,
    MesInterruptFact,
    MesPass,
    MesPassFact,
    MesProcessRequest,
    MesRelease,
    MesReleaseFact,
    MesResume,
    MesResumeFact,
    MesReturnRequirement,
    MesStart,
    MesStartFact,
    MesSwitchRevision,
    MesSwitchRevisionFact,
    MesTestRequest,
    Name,
    ProfileId,
    SapBomRequest,
    SapPostCompletion,
    SapPostCompletionFact,
    SapPostMovement,
    SapPostMovementFact,
    SapPublishPlan,
    SapPublishPlanFact,
    SapPurchaseRequirement,
    SapReleaseOrder,
    SapReleaseOrderFact,
    SapReleaseWorkOrder,
    SapReleaseWorkOrderFact,
    SourceKey,
    SystemId,
    Text,
    WmsCustody,
    WmsPick,
    WmsPickFact,
    WmsPutaway,
    WmsPutawayFact,
    WmsQualification,
    WmsReceive,
    WmsReceiveFact,
    WmsReserve,
    WmsReserveFact,
    WmsReturn,
    WmsReturnFact,
    WmsShip,
    WmsShipFact,
    WmsStocktake,
    WmsStocktakeFact,
)
from .enterprise_models import (
    CrmOpenReturn,
    CrmOpenReturnFact,
    CrmPublishDemand,
    CrmPublishDemandFact,
    HrBeisenPublishQualification,
    HrBeisenPublishQualificationFact,
    HrDingtalkAssignShift,
    HrDingtalkAssignShiftFact,
    HrSapPublishEmployee,
    HrSapPublishEmployeeFact,
    MesApprovalRequest,
    OaDecideApproval,
    OaDecideApprovalFact,
    OaRequestApproval,
    OaRequestApprovalFact,
    PdmIssueChange,
    PdmIssueChangeFact,
    PdmPublishRevision,
    PdmPublishRevisionFact,
    SrmAnnounceArrival,
    SrmAnnounceArrivalFact,
    SrmPromise,
    SrmPromiseFact,
)
from .evidence_models import (
    BiRefresh,
    BiRefreshFact,
    CustomerApproveRevision,
    CustomerApproveRevisionFact,
    CustomerConfirmDelivery,
    CustomerConfirmDeliveryFact,
    CustomerMapSerial,
    CustomerMapSerialFact,
    OverseasReceiveShipment,
    OverseasReceiveShipmentFact,
    OverseasReportReturn,
    OverseasReportReturnFact,
    PlcReadback,
    PlcReadbackFact,
    PlcSample,
    PlcSampleFact,
    PlcSetState,
    PlcSetStateFact,
    ProductTestCalibrate,
    ProductTestCalibrateFact,
    ProductTestRun,
    ProductTestRunFact,
)

OperationPayload = Annotated[
    SapReleaseOrder
    | SapReleaseWorkOrder
    | SapPublishPlan
    | SapPostMovement
    | SapPostCompletion
    | WmsReceive
    | WmsPutaway
    | WmsReserve
    | WmsPick
    | WmsReturn
    | WmsStocktake
    | WmsShip
    | MesInspect
    | MesStart
    | MesInterrupt
    | MesResume
    | MesSwitchRevision
    | MesPass
    | MesAssemble
    | MesContain
    | MesRelease
    | MesComplete
    | PdmPublishRevision
    | PdmIssueChange
    | CrmPublishDemand
    | CrmOpenReturn
    | OaRequestApproval
    | OaDecideApproval
    | HrSapPublishEmployee
    | HrBeisenPublishQualification
    | HrDingtalkAssignShift
    | SrmPromise
    | SrmAnnounceArrival
    | ProductTestRun
    | ProductTestCalibrate
    | PlcSetState
    | PlcSample
    | PlcReadback
    | CustomerApproveRevision
    | CustomerConfirmDelivery
    | CustomerMapSerial
    | OverseasReceiveShipment
    | OverseasReportReturn
    | BiRefresh,
    Field(discriminator="operation"),
]

FactPayload = Annotated[
    SapReleaseOrderFact
    | SapReleaseWorkOrderFact
    | SapPublishPlanFact
    | SapPostMovementFact
    | SapPostCompletionFact
    | WmsReceiveFact
    | WmsPutawayFact
    | WmsReserveFact
    | WmsPickFact
    | WmsReturnFact
    | WmsStocktakeFact
    | WmsShipFact
    | MesInspectFact
    | MesStartFact
    | MesInterruptFact
    | MesResumeFact
    | MesSwitchRevisionFact
    | MesPassFact
    | MesAssembleFact
    | MesContainFact
    | MesReleaseFact
    | MesCompleteFact
    | PdmPublishRevisionFact
    | PdmIssueChangeFact
    | CrmPublishDemandFact
    | CrmOpenReturnFact
    | OaRequestApprovalFact
    | OaDecideApprovalFact
    | HrSapPublishEmployeeFact
    | HrBeisenPublishQualificationFact
    | HrDingtalkAssignShiftFact
    | SrmPromiseFact
    | SrmAnnounceArrivalFact
    | ProductTestRunFact
    | ProductTestCalibrateFact
    | PlcSetStateFact
    | PlcSampleFact
    | PlcReadbackFact
    | CustomerApproveRevisionFact
    | CustomerConfirmDeliveryFact
    | CustomerMapSerialFact
    | OverseasReceiveShipmentFact
    | OverseasReportReturnFact
    | BiRefreshFact
    | SapBomRequest
    | SapPurchaseRequirement
    | WmsCustody
    | WmsQualification
    | MesProcessRequest
    | MesTestRequest
    | MesDeliveryContext
    | MesReturnRequirement
    | MesApprovalRequest,
    Field(discriminator="fact_type"),
]

OPERATION_ADAPTER = TypeAdapter(OperationPayload)
FACT_ADAPTER = TypeAdapter(FactPayload)


class MockSourceRef(SourceRef):
    system: SystemId
    mode: Literal["mock"] = "mock"

    @model_validator(mode="after")
    def identity(self):
        SourceKey.model_validate(
            {
                k: getattr(self, k)
                for k in ("system", "object_type", "external_id", "version")
            }
        )
        return self


class SystemOperation(StrictModel):
    operation_id: UUID
    system: SystemId
    project_id: UUID
    payload: OperationPayload

    @model_validator(mode="after")
    def matching_system(self):
        if self.payload.operation.split(".")[0] != self.system:
            raise ValueError("system and operation mismatch")
        return self


class IntegrationFact(StrictModel):
    source: MockSourceRef
    project_id: UUID
    payload: FactPayload
    external_actor: Name
    evidence: Text
    caused_by: list[SourceKey] = Field(default_factory=list, max_length=1000)

    @property
    def source_key(self) -> SourceKey:
        return SourceKey(
            system=self.source.system,
            object_type=self.source.object_type,
            external_id=self.source.external_id,
            version=self.source.version,
        )

    @model_validator(mode="after")
    def identity(self):
        if self.payload.fact_type != f"{self.source.system}.{self.source.object_type}":
            raise ValueError("source identity and fact type mismatch")
        keys = [
            (s.system, s.object_type, s.external_id, s.version) for s in self.caused_by
        ]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate causal source")
        return self


class SystemError(StrictModel):
    code: Name
    message: Text
    retryable: bool = Field(strict=True)


class SystemReceipt(StrictModel):
    operation_id: UUID
    system: SystemId
    request_hash: Digest
    phase: Literal["accepted", "rejected", "pending", "unknown"]
    source_keys: list[SourceKey] = Field(max_length=1000)
    sequence: int = Field(strict=True, ge=0)
    occurred_at: AwareTime
    received_at: AwareTime
    posted_at: AwareTime | None = None
    error: SystemError | None = None

    @model_validator(mode="after")
    def source_system(self):
        if any(k.system != self.system for k in self.source_keys):
            raise ValueError("receipt contains another producer source")
        return self


class ObjectRef(StrictModel):
    project_id: UUID
    kind: ObjectKind
    id: UUID


class AuxiliaryRef(StrictModel):
    project_id: UUID
    kind: Literal[
        "employee",
        "qualification",
        "shift",
        "equipment",
        "sample",
        "readback",
        "snapshot",
        "network_context",
        "accounting",
    ]
    id: UUID


class ProjectionResult(StrictModel):
    project_id: UUID
    source_key: SourceKey
    payload_hash: Digest
    targets: list[ObjectRef] = Field(max_length=1000)
    auxiliary: list[AuxiliaryRef] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def same_project(self):
        if any(
            ref.project_id != self.project_id
            for ref in [*self.targets, *self.auxiliary]
        ):
            raise ValueError("cross-project projection")
        return self


class FactPage(StrictModel):
    project_id: UUID
    records: list[IntegrationFact] = Field(max_length=200)
    continuation: Annotated[int, Field(strict=True, ge=0)] | Name | None
    source_cutoff: int = Field(strict=True, ge=0)
    projections: list[ProjectionResult] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def same_project(self):
        if any(
            r.project_id != self.project_id for r in [*self.records, *self.projections]
        ):
            raise ValueError("cross-project fact page")
        return self


class NetworkDelivery(StrictModel):
    delivery_id: UUID
    project_id: UUID
    consumer: SystemId
    fact: IntegrationFact
    payload_hash: Digest

    @model_validator(mode="after")
    def same_project(self):
        if self.fact.project_id != self.project_id:
            raise ValueError("cross-project delivery")
        return self


class DeliveryReceipt(StrictModel):
    delivery_id: UUID
    project_id: UUID
    consumer: SystemId
    source_key: SourceKey
    payload_hash: Digest
    phase: Literal["accepted", "rejected", "pending", "unknown"]
    received_at: AwareTime
    error: SystemError | None = None


class DeliveryBatch(StrictModel):
    project_id: UUID
    receipts: list[DeliveryReceipt] = Field(max_length=200)
    pending: int = Field(strict=True, ge=0)

    @model_validator(mode="after")
    def same_project(self):
        if any(r.project_id != self.project_id for r in self.receipts):
            raise ValueError("cross-project delivery batch")
        return self


class SystemDescriptor(StrictModel):
    system: ConnectorId
    profile: ProfileId
    mode: Literal["production", "demo", "test"]
    maturity: Literal["legacy", "modeled", "planned"]
    status: Literal[
        "unconfigured",
        "unexercised",
        "pending",
        "connected-mock",
        "degraded",
        "unavailable",
    ]
    capabilities: list[Name] = Field(max_length=100)
    permitted_operations: list[Name] = Field(max_length=100)
    pending_count: int = Field(strict=True, ge=0)
    last_receipt: SystemReceipt | None = None


class ExecuteSystemOperation(WorkflowCommand):
    action: Literal["mock_system.execute"] = "mock_system.execute"
    system: SystemId
    payload: OperationPayload

    @model_validator(mode="after")
    def matching_system(self):
        if self.payload.operation.split(".")[0] != self.system:
            raise ValueError("system and operation mismatch")
        return self


class QuerySystemOperation(WorkflowCommand):
    action: Literal["mock_system.query"] = "mock_system.query"
    intent_id: UUID


class RetrySystemOperation(WorkflowCommand):
    action: Literal["mock_system.retry"] = "mock_system.retry"
    intent_id: UUID


class PullIntegrationFact(WorkflowCommand):
    action: Literal["integration.pull"] = "integration.pull"
    source_key: SourceKey


class SystemAdapter(Protocol):
    def execute(self, operation: SystemOperation) -> SystemReceipt: ...
    def query(self, project_id: UUID, operation_id: UUID) -> SystemReceipt | None: ...
    def facts(
        self, project_id: UUID, object_type: str, cursor: int, limit: int
    ) -> FactPage: ...
    def consume(self, delivery: NetworkDelivery) -> DeliveryReceipt: ...
