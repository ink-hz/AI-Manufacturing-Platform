"""Fixed ownership and policy mappings; existing authorization hooks still apply."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import get_args

from . import core_models as core
from . import enterprise_models as enterprise
from . import evidence_models as evidence
from .core_models import SystemId

SYSTEM_IDS: tuple[str, ...] = get_args(SystemId)


@dataclass(frozen=True)
class OperationSpec:
    system: SystemId
    input_model: type
    output_fact_types: tuple[str, ...]
    underlying_action: str
    required_target_discriminator: str | None = None
    target_policies: tuple[tuple[str, str], ...] = ()
    variant_restrictions: tuple[str, ...] = ()

    def policy_for(self, payload) -> str:
        if not isinstance(payload, self.input_model):
            raise ValueError("operation payload does not match policy")
        if self.required_target_discriminator:
            return dict(self.target_policies)[payload.target.target_type]
        return self.underlying_action


@dataclass(frozen=True)
class EdgeSpec:
    producer: SystemId
    consumer: SystemId
    fact_types: tuple[str, ...]
    maturity: str = "modeled"


OPERATIONS: Mapping[str, OperationSpec] = MappingProxyType(
    {
        "sap.release_order": OperationSpec(
            "sap", core.SapReleaseOrder, ("sap.order",), "order.register"
        ),
        "sap.release_work_order": OperationSpec(
            "sap",
            core.SapReleaseWorkOrder,
            ("sap.work_order", "sap.bom_request"),
            "work_order.register",
        ),
        "sap.publish_plan": OperationSpec(
            "sap",
            core.SapPublishPlan,
            ("sap.plan", "sap.purchase_requirement"),
            "plan.receive",
        ),
        "sap.post_movement": OperationSpec(
            "sap", core.SapPostMovement, ("sap.accounting_entry",), "ownership.movement"
        ),
        "sap.post_completion": OperationSpec(
            "sap",
            core.SapPostCompletion,
            ("sap.completion_posting",),
            "ownership.movement",
        ),
        "wms.receive": OperationSpec(
            "wms", core.WmsReceive, ("wms.receipt",), "supply.receive"
        ),
        "wms.putaway": OperationSpec(
            "wms", core.WmsPutaway, ("wms.putaway",), "ownership.movement"
        ),
        "wms.reserve": OperationSpec(
            "wms", core.WmsReserve, ("wms.reservation",), "reservation.request"
        ),
        "wms.pick": OperationSpec(
            "wms", core.WmsPick, ("wms.pick", "wms.custody"), "ownership.movement"
        ),
        "wms.return": OperationSpec(
            "wms", core.WmsReturn, ("wms.return",), "ownership.movement"
        ),
        "wms.stocktake": OperationSpec(
            "wms", core.WmsStocktake, ("wms.stocktake",), "ownership.movement"
        ),
        "wms.ship": OperationSpec(
            "wms", core.WmsShip, ("wms.shipment",), "shipment.request"
        ),
        "mes.inspect": OperationSpec(
            "mes", core.MesInspect, ("mes.iqc",), "supply.inspect"
        ),
        "mes.start": OperationSpec(
            "mes",
            core.MesStart,
            (
                "mes.start",
                "mes.process_request",
                "mes.test_request",
                "mes.approval_request",
            ),
            "production.start",
        ),
        "mes.interrupt": OperationSpec(
            "mes", core.MesInterrupt, ("mes.interruption",), "production.interrupt"
        ),
        "mes.resume": OperationSpec(
            "mes", core.MesResume, ("mes.resume",), "production.resume"
        ),
        "mes.switch_revision": OperationSpec(
            "mes", core.MesSwitchRevision, ("mes.revision_switch",), "eco.switch"
        ),
        "mes.pass": OperationSpec(
            "mes", core.MesPass, ("mes.execution",), "execution.record"
        ),
        "mes.assemble": OperationSpec(
            "mes", core.MesAssemble, ("mes.component",), "component.install"
        ),
        "mes.contain": OperationSpec(
            "mes",
            core.MesContain,
            ("mes.containment",),
            "freeze.request",
            variant_restrictions=(
                "decision:frozen|unfrozen; existing freeze.request authorize hook",
            ),
        ),
        "mes.release": OperationSpec(
            "mes",
            core.MesRelease,
            ("mes.release", "mes.delivery_context"),
            "release.decide",
            variant_restrictions=(
                "kind:manufacturing|quality; existing release.decide authorize hook",
            ),
        ),
        "mes.complete": OperationSpec(
            "mes",
            core.MesComplete,
            ("mes.completion", "mes.return_requirement"),
            "execution.record",
        ),
        "pdm.publish_revision": OperationSpec(
            "pdm",
            enterprise.PdmPublishRevision,
            ("pdm.revision",),
            "engineering.revision",
        ),
        "pdm.issue_change": OperationSpec(
            "pdm", enterprise.PdmIssueChange, ("pdm.change",), "eco.open"
        ),
        "crm.publish_demand": OperationSpec(
            "crm", enterprise.CrmPublishDemand, ("crm.demand",), "demand.record"
        ),
        "crm.open_return": OperationSpec(
            "crm", enterprise.CrmOpenReturn, ("crm.return_claim",), "rma.open"
        ),
        "oa.request_approval": OperationSpec(
            "oa",
            enterprise.OaRequestApproval,
            ("oa.approval_request",),
            "npi.review",
            required_target_discriminator="target.target_type",
            target_policies=(
                ("engineering", "npi.review"),
                ("quality", "nonconformance.disposition"),
            ),
        ),
        "oa.decide_approval": OperationSpec(
            "oa",
            enterprise.OaDecideApproval,
            ("oa.approval_decision",),
            "npi.review",
            required_target_discriminator="target.target_type",
            target_policies=(
                ("engineering", "npi.review"),
                ("quality", "nonconformance.disposition"),
            ),
        ),
        "hr_sap.publish_employee": OperationSpec(
            "hr_sap",
            enterprise.HrSapPublishEmployee,
            ("hr_sap.employee",),
            "authority.register",
        ),
        "hr_beisen.publish_qualification": OperationSpec(
            "hr_beisen",
            enterprise.HrBeisenPublishQualification,
            ("hr_beisen.qualification",),
            "authority.register",
        ),
        "hr_dingtalk.assign_shift": OperationSpec(
            "hr_dingtalk",
            enterprise.HrDingtalkAssignShift,
            ("hr_dingtalk.shift",),
            "authority.register",
        ),
        "srm.promise": OperationSpec(
            "srm", enterprise.SrmPromise, ("srm.promise",), "supply.commit"
        ),
        "srm.announce_arrival": OperationSpec(
            "srm", enterprise.SrmAnnounceArrival, ("srm.arrival",), "arrival.record"
        ),
        "product_test.run": OperationSpec(
            "product_test",
            evidence.ProductTestRun,
            ("product_test.test",),
            "test.record",
        ),
        "product_test.calibrate": OperationSpec(
            "product_test",
            evidence.ProductTestCalibrate,
            ("product_test.calibration",),
            "calibration.record",
        ),
        "plc.set_state": OperationSpec(
            "plc", evidence.PlcSetState, ("plc.equipment",), "execution.record"
        ),
        "plc.sample": OperationSpec(
            "plc", evidence.PlcSample, ("plc.sample",), "execution.record"
        ),
        "plc.readback": OperationSpec(
            "plc", evidence.PlcReadback, ("plc.readback",), "execution.record"
        ),
        "customer.approve_revision": OperationSpec(
            "customer",
            evidence.CustomerApproveRevision,
            ("customer.customer_approval",),
            "engineering.customer_approval",
        ),
        "customer.confirm_delivery": OperationSpec(
            "customer",
            evidence.CustomerConfirmDelivery,
            ("customer.acceptance",),
            "delivery.accept",
        ),
        "customer.map_serial": OperationSpec(
            "customer",
            evidence.CustomerMapSerial,
            ("customer.serial_mapping",),
            "unit.alias",
        ),
        "overseas.receive_shipment": OperationSpec(
            "overseas",
            evidence.OverseasReceiveShipment,
            ("overseas.delivery_receipt",),
            "delivery.sign",
        ),
        "overseas.report_return": OperationSpec(
            "overseas",
            evidence.OverseasReportReturn,
            ("overseas.return_claim",),
            "rma.open",
        ),
        "bi.refresh": OperationSpec(
            "bi", evidence.BiRefresh, ("bi.snapshot",), "plan.receive"
        ),
    }
)


EDGES: tuple[EdgeSpec, ...] = (
    EdgeSpec("sap", "mes", ("sap.work_order", "sap.plan")),
    EdgeSpec("mes", "sap", ("mes.completion", "mes.execution", "mes.containment")),
    EdgeSpec("sap", "wms", ("sap.order", "sap.purchase_requirement", "sap.plan")),
    EdgeSpec(
        "wms",
        "sap",
        ("wms.receipt", "wms.pick", "wms.return", "wms.stocktake", "wms.shipment"),
    ),
    EdgeSpec("sap", "pdm", ("sap.bom_request",)),
    EdgeSpec("pdm", "sap", ("pdm.revision", "pdm.change")),
    EdgeSpec("pdm", "mes", ("pdm.revision", "pdm.change")),
    EdgeSpec(
        "wms",
        "mes",
        ("wms.receipt", "wms.qualification", "wms.pick", "wms.custody", "wms.shipment"),
    ),
    EdgeSpec(
        "mes",
        "wms",
        ("mes.iqc", "mes.containment", "mes.execution", "mes.return_requirement"),
    ),
    EdgeSpec("mes", "oa", ("mes.approval_request",)),
    EdgeSpec("oa", "mes", ("oa.approval_decision",)),
    EdgeSpec("hr_sap", "mes", ("hr_sap.employee",)),
    EdgeSpec("hr_beisen", "mes", ("hr_beisen.qualification",)),
    EdgeSpec("hr_dingtalk", "mes", ("hr_dingtalk.shift",)),
    EdgeSpec("crm", "mes", ("crm.return_claim",)),
    EdgeSpec("crm", "sap", ("crm.demand",)),
    EdgeSpec("mes", "product_test", ("mes.test_request",)),
    EdgeSpec("product_test", "mes", ("product_test.test", "product_test.calibration")),
    EdgeSpec("mes", "customer", ("mes.delivery_context",)),
    EdgeSpec(
        "customer",
        "mes",
        (
            "customer.customer_approval",
            "customer.acceptance",
            "customer.serial_mapping",
        ),
    ),
    EdgeSpec("mes", "overseas", ("mes.delivery_context",)),
    EdgeSpec("overseas", "mes", ("overseas.delivery_receipt", "overseas.return_claim")),
    EdgeSpec("mes", "plc", ("mes.process_request",)),
    EdgeSpec("plc", "mes", ("plc.equipment", "plc.sample", "plc.readback")),
    EdgeSpec(
        "sap", "bi", ("sap.order", "sap.accounting_entry", "sap.completion_posting")
    ),
    EdgeSpec("mes", "bi", ("mes.execution", "mes.completion")),
    EdgeSpec("product_test", "bi", ("product_test.test",)),
    EdgeSpec("sap", "srm", ("sap.purchase_requirement",), "planned"),
    EdgeSpec("srm", "sap", ("srm.promise", "srm.arrival"), "planned"),
    EdgeSpec("srm", "wms", ("srm.promise", "srm.arrival"), "planned"),
    EdgeSpec("product_test", "plc", ("product_test.calibration",)),
    EdgeSpec("plc", "product_test", ("plc.readback",)),
)
