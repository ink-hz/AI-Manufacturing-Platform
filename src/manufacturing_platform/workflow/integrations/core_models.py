"""Closed SAP, WMS and MES business payloads; no adapters or persistence."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, Field, model_validator

from ..contracts import NonnegativeQuantity, Quantity, StrictModel, require_timezone
from ..execution_models import sn_key

SystemId = Literal[
    "sap",
    "pdm",
    "crm",
    "oa",
    "hr_sap",
    "hr_beisen",
    "hr_dingtalk",
    "mes",
    "wms",
    "product_test",
    "plc",
    "bi",
    "customer",
    "overseas",
    "srm",
]
ConnectorId = SystemId | Literal["erp"]
ProfileId = Literal["legacy-erp-v1", "oem-network-v1"]
Name = Annotated[
    str, Field(min_length=1, max_length=200, pattern=r"^\S(?:[^\r\n]*\S)?$")
]
Text = Annotated[str, Field(min_length=1, max_length=2000)]
AwareTime = Annotated[datetime, AfterValidator(require_timezone)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class SourceKey(StrictModel):
    system: SystemId
    object_type: Annotated[
        str, Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    ]
    external_id: Annotated[
        str,
        Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@-]*$"),
    ]
    version: int = Field(strict=True, ge=1)


class Amount(StrictModel):
    quantity: NonnegativeQuantity
    unit: Annotated[str, Field(min_length=1, max_length=40)]
    scale: int = Field(strict=True, ge=0, le=6)

    @model_validator(mode="after")
    def precision(self):
        if (
            self.quantity.as_tuple().exponent < -self.scale
            or self.quantity * 10**self.scale > 2**63 - 1
        ):
            raise ValueError("quantity exceeds unit precision or atom range")
        return self


class PositiveAmount(Amount):
    quantity: Quantity


def same_dimensions(*amounts):
    if len({(a.unit, a.scale) for a in amounts}) != 1:
        raise ValueError("mixed quantity units or scales")


class UnitIdentity(StrictModel):
    unit_id: UUID
    sn: Name


class UnitScope(StrictModel):
    units: list[UnitIdentity] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique(self):
        if len({u.unit_id for u in self.units}) != len(self.units) or len(
            {sn_key(u.sn) for u in self.units}
        ) != len(self.units):
            raise ValueError("duplicate unit or SN")
        return self


class MaterialAllocation(StrictModel):
    material_lot_id: UUID
    material_id: Name
    owner_id: Name
    amount: PositiveAmount
    qualification: SourceKey
    reservation: SourceKey | None = None


class Custody(StrictModel):
    location: Name
    custodian: Name


class OrderData(StrictModel):
    demand_id: UUID
    customer_id: Name
    product: Name
    amount: PositiveAmount
    due_date: date


class WorkOrderData(StrictModel):
    order_line_id: UUID
    revision_id: UUID
    released_revision: SourceKey
    amount: PositiveAmount
    trial_amount: PositiveAmount
    purpose: Literal["trial", "production"]
    planned_start: AwareTime
    planned_end: AwareTime

    @model_validator(mode="after")
    def scope(self):
        same_dimensions(self.amount, self.trial_amount)
        if (
            self.trial_amount.quantity > self.amount.quantity
            or self.planned_end <= self.planned_start
        ):
            raise ValueError("invalid work order trial scope or schedule")
        if (
            self.released_revision.system != "pdm"
            or self.released_revision.object_type != "revision"
        ):
            raise ValueError("released PDM revision required")
        return self


class PlanRequirement(StrictModel):
    requirement_id: UUID
    work_order_id: UUID
    execution_scope: Literal["trial", "bulk", "common"]
    material_id: Name
    owner_id: Name
    amount: PositiveAmount


class OrderVersion(StrictModel):
    order_line_id: UUID
    version: int = Field(strict=True, ge=1)


class PlanData(StrictModel):
    input_revision_ids: list[UUID] = Field(min_length=1, max_length=100)
    input_order_versions: list[OrderVersion] = Field(min_length=1, max_length=100)
    requirements: list[PlanRequirement] = Field(min_length=1, max_length=500)
    cutoff: AwareTime

    @model_validator(mode="after")
    def unique(self):
        keys = [
            (r.work_order_id, r.execution_scope, r.material_id, r.owner_id)
            for r in self.requirements
        ]
        if len(set(keys)) != len(keys) or len(
            {r.requirement_id for r in self.requirements}
        ) != len(keys):
            raise ValueError("duplicate scoped requirement")
        return self


class AccountingData(StrictModel):
    cause: SourceKey
    account: Name
    allocations: list[MaterialAllocation] = Field(min_length=1, max_length=500)
    evidence: Text

    @model_validator(mode="after")
    def physical_cause(self):
        if self.cause.system not in {"wms", "mes"}:
            raise ValueError("accounting requires WMS or MES cause")
        return self


class ReceiptData(StrictModel):
    commitment_id: UUID
    material_lot_id: UUID
    lot_id: Name
    material_id: Name
    owner_id: Name
    amount: PositiveAmount
    location: Name
    supplier_batch: Name
    expiry: date
    arrival: SourceKey | None = None


class MovementData(StrictModel):
    work_order_id: UUID | None = None
    allocations: list[MaterialAllocation] = Field(min_length=1, max_length=500)
    source_custody: Custody
    destination_custody: Custody
    cause: SourceKey
    evidence: Text


class ReservationData(StrictModel):
    requirement_id: UUID
    work_order_id: UUID
    allocations: list[MaterialAllocation] = Field(min_length=1, max_length=500)


class StocktakeData(StrictModel):
    material_lot_id: UUID
    owner_id: Name
    location: Name
    expected: Amount
    counted: Amount
    cause: SourceKey
    evidence: Text

    @model_validator(mode="after")
    def dimensions(self):
        same_dimensions(self.expected, self.counted)
        return self


class ShipmentData(UnitScope):
    order_line_id: UUID
    shipment_id: UUID
    release: SourceKey
    amount: PositiveAmount
    destination: Name
    evidence: Text

    @model_validator(mode="after")
    def count(self):
        if self.amount.quantity != len(self.units):
            raise ValueError("shipment quantity must equal unique unit count")
        return self


class InspectionData(StrictModel):
    receipt: SourceKey
    accepted: Amount
    rejected: Amount
    evidence: Text

    @model_validator(mode="after")
    def dimensions(self):
        same_dimensions(self.accepted, self.rejected)
        if self.accepted.quantity + self.rejected.quantity <= 0:
            raise ValueError("inspection must cover quantity")
        if self.receipt.system != "wms" or self.receipt.object_type != "receipt":
            raise ValueError("full WMS receipt source identity required")
        return self


class StartData(UnitScope):
    work_order_id: UUID
    revision_id: UUID
    mode: Literal["trial", "bulk"]
    operator: SourceKey
    shift: SourceKey
    equipment: SourceKey
    occurred_at: AwareTime


class InterruptData(StrictModel):
    work_order_id: UUID
    interruption_id: UUID
    reason: Text
    kind: Literal["S3", "S4", "other"]


class ResumeData(StrictModel):
    work_order_id: UUID
    interruption_id: UUID
    plan_id: UUID
    scope: Literal["all", "trial"]
    evidence: Text


class SwitchData(UnitScope):
    work_order_id: UUID
    eco_id: UUID
    from_revision_id: UUID
    to_revision_id: UUID
    change: SourceKey
    approval: SourceKey
    evidence: Text


class ExecutionData(StrictModel):
    work_order_id: UUID
    unit: UnitIdentity
    revision_id: UUID
    operator: SourceKey
    shift: SourceKey
    equipment: SourceKey
    station: Name
    route_version: Name
    program_version: Name
    firmware_version: Name
    occurred_at: AwareTime
    material_uses: list[MaterialAllocation] = Field(max_length=200)
    result: Literal["pass", "fail"]
    rework_order_id: UUID | None = None
    supersedes_event_id: UUID | None = None


class AssemblyData(StrictModel):
    work_order_id: UUID
    unit_id: UUID
    material_id: Name
    component_serial: Name
    material_lot_id: UUID
    execution: SourceKey
    evidence: Text


class ContainmentData(StrictModel):
    work_order_id: UUID
    unit_ids: list[UUID] = Field(max_length=500)
    material_lot_ids: list[UUID] = Field(max_length=500)
    decision: Literal["frozen", "unfrozen"]
    cause: SourceKey
    evidence: Text

    @model_validator(mode="after")
    def scope(self):
        if not self.unit_ids and not self.material_lot_ids:
            raise ValueError("containment requires affected scope")
        if len(set(self.unit_ids)) != len(self.unit_ids) or len(
            set(self.material_lot_ids)
        ) != len(self.material_lot_ids):
            raise ValueError("duplicate containment scope")
        return self


class ReleaseData(UnitScope):
    work_order_id: UUID
    kind: Literal["manufacturing", "quality"]
    decision: Literal["approved", "rejected"]
    test_sources: list[SourceKey] = Field(min_length=1, max_length=500)
    evidence: Text


class CompletionData(UnitScope):
    work_order_id: UUID
    revision_id: UUID
    execution_sources: list[SourceKey] = Field(min_length=1, max_length=500)
    consumption: list[MaterialAllocation] = Field(max_length=500)
    occurred_at: AwareTime


class CompletionPostingData(StrictModel):
    completion: SourceKey
    work_order_id: UUID
    account: Name
    evidence: Text

    @model_validator(mode="after")
    def cause(self):
        if (
            self.completion.system != "mes"
            or self.completion.object_type != "completion"
        ):
            raise ValueError("MES completion required")
        return self


class SapReleaseOrder(OrderData):
    operation: Literal["sap.release_order"] = "sap.release_order"


class SapReleaseOrderFact(OrderData):
    fact_type: Literal["sap.order"] = "sap.order"


class SapReleaseWorkOrder(WorkOrderData):
    operation: Literal["sap.release_work_order"] = "sap.release_work_order"


class SapReleaseWorkOrderFact(WorkOrderData):
    fact_type: Literal["sap.work_order"] = "sap.work_order"


class SapPublishPlan(PlanData):
    operation: Literal["sap.publish_plan"] = "sap.publish_plan"


class SapPublishPlanFact(PlanData):
    fact_type: Literal["sap.plan"] = "sap.plan"


class SapPostMovement(AccountingData):
    operation: Literal["sap.post_movement"] = "sap.post_movement"


class SapPostMovementFact(AccountingData):
    fact_type: Literal["sap.accounting_entry"] = "sap.accounting_entry"


class SapPostCompletion(CompletionPostingData):
    operation: Literal["sap.post_completion"] = "sap.post_completion"


class SapPostCompletionFact(CompletionPostingData):
    fact_type: Literal["sap.completion_posting"] = "sap.completion_posting"


class WmsReceive(ReceiptData):
    operation: Literal["wms.receive"] = "wms.receive"


class WmsReceiveFact(ReceiptData):
    fact_type: Literal["wms.receipt"] = "wms.receipt"


class WmsPutaway(MovementData):
    operation: Literal["wms.putaway"] = "wms.putaway"


class WmsPutawayFact(MovementData):
    fact_type: Literal["wms.putaway"] = "wms.putaway"


class WmsReserve(ReservationData):
    operation: Literal["wms.reserve"] = "wms.reserve"


class WmsReserveFact(ReservationData):
    fact_type: Literal["wms.reservation"] = "wms.reservation"


class WmsPick(MovementData):
    operation: Literal["wms.pick"] = "wms.pick"


class WmsPickFact(MovementData):
    fact_type: Literal["wms.pick"] = "wms.pick"


class WmsReturn(MovementData):
    operation: Literal["wms.return"] = "wms.return"


class WmsReturnFact(MovementData):
    fact_type: Literal["wms.return"] = "wms.return"


class WmsStocktake(StocktakeData):
    operation: Literal["wms.stocktake"] = "wms.stocktake"


class WmsStocktakeFact(StocktakeData):
    fact_type: Literal["wms.stocktake"] = "wms.stocktake"


class WmsShip(ShipmentData):
    operation: Literal["wms.ship"] = "wms.ship"


class WmsShipFact(ShipmentData):
    fact_type: Literal["wms.shipment"] = "wms.shipment"


class MesInspect(InspectionData):
    operation: Literal["mes.inspect"] = "mes.inspect"


class MesInspectFact(InspectionData):
    fact_type: Literal["mes.iqc"] = "mes.iqc"


class MesStart(StartData):
    operation: Literal["mes.start"] = "mes.start"


class MesStartFact(StartData):
    fact_type: Literal["mes.start"] = "mes.start"


class MesInterrupt(InterruptData):
    operation: Literal["mes.interrupt"] = "mes.interrupt"


class MesInterruptFact(InterruptData):
    fact_type: Literal["mes.interruption"] = "mes.interruption"


class MesResume(ResumeData):
    operation: Literal["mes.resume"] = "mes.resume"


class MesResumeFact(ResumeData):
    fact_type: Literal["mes.resume"] = "mes.resume"


class MesSwitchRevision(SwitchData):
    operation: Literal["mes.switch_revision"] = "mes.switch_revision"


class MesSwitchRevisionFact(SwitchData):
    fact_type: Literal["mes.revision_switch"] = "mes.revision_switch"


class MesPass(ExecutionData):
    operation: Literal["mes.pass"] = "mes.pass"


class MesPassFact(ExecutionData):
    fact_type: Literal["mes.execution"] = "mes.execution"


class MesAssemble(AssemblyData):
    operation: Literal["mes.assemble"] = "mes.assemble"


class MesAssembleFact(AssemblyData):
    fact_type: Literal["mes.component"] = "mes.component"


class MesContain(ContainmentData):
    operation: Literal["mes.contain"] = "mes.contain"


class MesContainFact(ContainmentData):
    fact_type: Literal["mes.containment"] = "mes.containment"


class MesRelease(ReleaseData):
    operation: Literal["mes.release"] = "mes.release"


class MesReleaseFact(ReleaseData):
    fact_type: Literal["mes.release"] = "mes.release"


class MesComplete(CompletionData):
    operation: Literal["mes.complete"] = "mes.complete"


class MesCompleteFact(CompletionData):
    fact_type: Literal["mes.completion"] = "mes.completion"


class SapBomRequest(StrictModel):
    fact_type: Literal["sap.bom_request"] = "sap.bom_request"
    work_order_id: UUID
    product: Name
    material_ids: list[Name] = Field(min_length=1, max_length=500)
    requested_revision: Name


class SapPurchaseRequirement(PlanRequirement):
    fact_type: Literal["sap.purchase_requirement"] = "sap.purchase_requirement"
    due_date: date


class WmsCustody(MovementData):
    fact_type: Literal["wms.custody"] = "wms.custody"


class WmsQualification(InspectionData):
    fact_type: Literal["wms.qualification"] = "wms.qualification"
    iqc: SourceKey
    material_lot_id: UUID


class MesProcessRequest(StrictModel):
    fact_type: Literal["mes.process_request"] = "mes.process_request"
    work_order_id: UUID
    unit_id: UUID
    revision_id: UUID
    equipment: Name
    station: Name
    program_version: Name


class MesTestRequest(StrictModel):
    fact_type: Literal["mes.test_request"] = "mes.test_request"
    work_order_id: UUID
    unit_id: UUID
    revision_id: UUID
    plan_id: UUID
    route_version: Name
    program_version: Name
    firmware_version: Name


class MesDeliveryContext(UnitScope):
    fact_type: Literal["mes.delivery_context"] = "mes.delivery_context"
    work_order_id: UUID
    revision: SourceKey
    release: SourceKey
    shipment: SourceKey
    quality_sources: list[SourceKey] = Field(min_length=1, max_length=500)


class MesReturnRequirement(MovementData):
    fact_type: Literal["mes.return_requirement"] = "mes.return_requirement"
