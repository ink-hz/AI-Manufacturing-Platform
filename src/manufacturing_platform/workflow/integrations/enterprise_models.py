"""Enterprise source contracts. External employees never imply platform grants."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from ...collaboration_models import PackageItem
from ..contracts import StrictModel
from ..engineering_models import RouteStep, TestSpec
from ..introduction_models import ReviewCheck
from .core_models import AwareTime, Name, PositiveAmount, SourceKey, Text, UnitScope


class BomMaterial(StrictModel):
    material_id: Name
    per_unit: PositiveAmount


class RevisionData(StrictModel):
    bom_materials: list[BomMaterial] = Field(min_length=1, max_length=500)
    package_id: Name
    revision: Name
    customer_revision: Name
    internal_revision: Name
    firmware_version: Name
    items: list[PackageItem] = Field(min_length=1, max_length=500)
    route_steps: list[RouteStep] = Field(min_length=1, max_length=200)
    test_spec: TestSpec
    released_at: AwareTime

    @model_validator(mode="after")
    def unique(self):
        if len({m.material_id for m in self.bom_materials}) != len(self.bom_materials):
            raise ValueError("duplicate BOM material")
        if len({i.id for i in self.items}) != len(self.items) or len(
            {r.station for r in self.route_steps}
        ) != len(self.route_steps):
            raise ValueError("duplicate BOM item or route station")
        return self


class ChangeData(StrictModel):
    work_order_id: UUID
    from_revision_id: UUID
    to_revision_id: UUID
    released_revision: SourceKey
    boundary_unit_ids: list[UUID] = Field(min_length=1, max_length=500)
    reason: Text

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.boundary_unit_ids)) != len(self.boundary_unit_ids):
            raise ValueError("duplicate ECN unit scope")
        return self


class DemandData(StrictModel):
    customer_id: Name
    demand_kind: Literal["inquiry", "forecast", "firm"]
    product: Name
    amount: PositiveAmount
    due_date: date
    supersedes_demand_id: UUID | None = None


class ReturnData(UnitScope):
    shipment_id: UUID
    shipment: SourceKey
    amount: PositiveAmount
    customer_id: Name
    external_signer: Name
    reason: Text
    signed_evidence: Text
    occurred_at: AwareTime

    @model_validator(mode="after")
    def count(self):
        if self.amount.quantity != len(self.units):
            raise ValueError("claim quantity must equal unique SN count")
        if self.shipment.system != "wms" or self.shipment.object_type != "shipment":
            raise ValueError("WMS shipment required")
        return self


class EngineeringTarget(StrictModel):
    target_type: Literal["engineering"] = "engineering"
    source_key: SourceKey
    npi_id: UUID
    revision_id: UUID
    checks: list[ReviewCheck] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_checks(self):
        if len({c.code for c in self.checks}) != len(self.checks):
            raise ValueError("duplicate review check")
        return self


class QualityTarget(StrictModel):
    target_type: Literal["quality"] = "quality"
    source_key: SourceKey
    nonconformance_id: UUID
    work_order_id: UUID
    disposition: Literal["rework", "scrap", "concession"]
    route_id: Name | None = None
    route_steps: list[RouteStep] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def rework_route(self):
        if self.disposition == "rework":
            if (
                not self.route_id
                or not self.route_steps
                or len({s.station for s in self.route_steps}) != len(self.route_steps)
            ):
                raise ValueError("rework requires a unique independent route")
        elif self.route_id or self.route_steps:
            raise ValueError("route only belongs to rework")
        return self


ApprovalTarget = Annotated[
    EngineeringTarget | QualityTarget, Field(discriminator="target_type")
]


class ApprovalRequestData(StrictModel):
    target: ApprovalTarget
    requested_by: Name
    evidence: Text


class ApprovalDecisionData(StrictModel):
    target: ApprovalTarget
    request: SourceKey
    decision: Literal["approved", "rejected"]
    external_signer: Name
    signed_at: AwareTime
    evidence: Text


class EmployeeData(StrictModel):
    employee_id: Name
    display_name: Name
    organization: Name
    position: Name
    active: bool = Field(strict=True)


class QualificationData(StrictModel):
    employee: SourceKey
    qualification: Name
    training_reference: Name
    valid_from: AwareTime
    valid_until: AwareTime
    evidence: Text

    @model_validator(mode="after")
    def scope(self):
        if self.employee.system != "hr_sap" or self.employee.object_type != "employee":
            raise ValueError("HR SAP employee source required")
        if self.valid_until <= self.valid_from:
            raise ValueError("qualification expiry must follow start")
        return self


class ShiftData(StrictModel):
    employee: SourceKey
    work_order_id: UUID
    shift_id: Name
    starts_at: AwareTime
    ends_at: AwareTime
    attendance: Literal["present", "absent"]

    @model_validator(mode="after")
    def scope(self):
        if self.employee.system != "hr_sap" or self.employee.object_type != "employee":
            raise ValueError("HR SAP employee source required")
        if self.ends_at <= self.starts_at:
            raise ValueError("shift end must follow start")
        return self


class PromiseData(StrictModel):
    requirement_id: UUID
    purchase_requirement: SourceKey
    commitment_id: UUID
    supplier_id: Name
    owner_id: Name
    supply_type: Literal["purchase", "customer"]
    amount: PositiveAmount
    original_due: date
    current_due: date
    evidence: Text


class ArrivalData(StrictModel):
    commitment_id: UUID
    promise: SourceKey
    material_id: Name
    supplier_batch: Name
    supplier_id: Name
    amount: PositiveAmount
    expected_at: AwareTime
    coa_reference: Name
    coa_evidence: Text


class PdmPublishRevision(RevisionData):
    operation: Literal["pdm.publish_revision"] = "pdm.publish_revision"


class PdmPublishRevisionFact(RevisionData):
    fact_type: Literal["pdm.revision"] = "pdm.revision"


class PdmIssueChange(ChangeData):
    operation: Literal["pdm.issue_change"] = "pdm.issue_change"


class PdmIssueChangeFact(ChangeData):
    fact_type: Literal["pdm.change"] = "pdm.change"


class CrmPublishDemand(DemandData):
    operation: Literal["crm.publish_demand"] = "crm.publish_demand"


class CrmPublishDemandFact(DemandData):
    fact_type: Literal["crm.demand"] = "crm.demand"


class CrmOpenReturn(ReturnData):
    operation: Literal["crm.open_return"] = "crm.open_return"


class CrmOpenReturnFact(ReturnData):
    fact_type: Literal["crm.return_claim"] = "crm.return_claim"


class OaRequestApproval(ApprovalRequestData):
    operation: Literal["oa.request_approval"] = "oa.request_approval"


class OaRequestApprovalFact(ApprovalRequestData):
    fact_type: Literal["oa.approval_request"] = "oa.approval_request"


class OaDecideApproval(ApprovalDecisionData):
    operation: Literal["oa.decide_approval"] = "oa.decide_approval"


class OaDecideApprovalFact(ApprovalDecisionData):
    fact_type: Literal["oa.approval_decision"] = "oa.approval_decision"


class HrSapPublishEmployee(EmployeeData):
    operation: Literal["hr_sap.publish_employee"] = "hr_sap.publish_employee"


class HrSapPublishEmployeeFact(EmployeeData):
    fact_type: Literal["hr_sap.employee"] = "hr_sap.employee"


class HrBeisenPublishQualification(QualificationData):
    operation: Literal["hr_beisen.publish_qualification"] = (
        "hr_beisen.publish_qualification"
    )


class HrBeisenPublishQualificationFact(QualificationData):
    fact_type: Literal["hr_beisen.qualification"] = "hr_beisen.qualification"


class HrDingtalkAssignShift(ShiftData):
    operation: Literal["hr_dingtalk.assign_shift"] = "hr_dingtalk.assign_shift"


class HrDingtalkAssignShiftFact(ShiftData):
    fact_type: Literal["hr_dingtalk.shift"] = "hr_dingtalk.shift"


class SrmPromise(PromiseData):
    operation: Literal["srm.promise"] = "srm.promise"


class SrmPromiseFact(PromiseData):
    fact_type: Literal["srm.promise"] = "srm.promise"


class SrmAnnounceArrival(ArrivalData):
    operation: Literal["srm.announce_arrival"] = "srm.announce_arrival"


class SrmAnnounceArrivalFact(ArrivalData):
    fact_type: Literal["srm.arrival"] = "srm.arrival"


class MesApprovalRequest(ApprovalRequestData):
    fact_type: Literal["mes.approval_request"] = "mes.approval_request"


class PreparationData(StrictModel):
    work_order_id: UUID
    unit_ids: list[UUID] = Field(min_length=1, max_length=500)
    test_plan_id: UUID
    equipment_id: Name
    approval_target: ApprovalTarget | None = None

    @model_validator(mode="after")
    def unique_units(self):
        if len(set(self.unit_ids)) != len(self.unit_ids):
            raise ValueError("Preparation requires distinct units")
        return self


class MesPrepare(PreparationData):
    operation: Literal["mes.prepare"] = "mes.prepare"


class MesPreparation(PreparationData):
    fact_type: Literal["mes.preparation"] = "mes.preparation"


class EnterpriseRecordIdentity(StrictModel):
    project_id: UUID
    source_key: SourceKey
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class EmployeeRecord(EnterpriseRecordIdentity, EmployeeData):
    kind: Literal["employee"] = "employee"


class QualificationRecord(EnterpriseRecordIdentity, QualificationData):
    kind: Literal["qualification"] = "qualification"


class ShiftRecord(EnterpriseRecordIdentity, ShiftData):
    kind: Literal["shift"] = "shift"


HRRecord = Annotated[
    EmployeeRecord | QualificationRecord | ShiftRecord, Field(discriminator="kind")
]


class ApprovalRequestRecord(EnterpriseRecordIdentity, ApprovalRequestData):
    kind: Literal["approval_request"] = "approval_request"


class ApprovalDecisionRecord(EnterpriseRecordIdentity, ApprovalDecisionData):
    kind: Literal["approval_decision"] = "approval_decision"


class SupplierNotice(EnterpriseRecordIdentity, ArrivalData):
    kind: Literal["supplier_notice"] = "supplier_notice"


EnterpriseRecord = Annotated[
    EmployeeRecord
    | QualificationRecord
    | ShiftRecord
    | ApprovalRequestRecord
    | ApprovalDecisionRecord
    | SupplierNotice,
    Field(discriminator="kind"),
]


class BomConfirmationData(StrictModel):
    request: SourceKey
    released_revision: SourceKey
    work_order_id: UUID
    bom_materials: list[BomMaterial] = Field(min_length=1, max_length=500)
    bom_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class PdmBomConfirmation(BomConfirmationData):
    fact_type: Literal["pdm.bom_confirmation"] = "pdm.bom_confirmation"


class BomConfirmationRecord(EnterpriseRecordIdentity, BomConfirmationData):
    kind: Literal["bom_confirmation"] = "bom_confirmation"
