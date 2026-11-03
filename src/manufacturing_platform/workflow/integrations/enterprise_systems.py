"""Fixed enterprise family composition using the guarded source lifecycle."""

from .core_guards import require
from .core_systems import CoreSystem, authorize
from .enterprise_projections import project_fact, validate_fact


class EnterpriseSystem(CoreSystem):
    def __init__(self, system, store, registry):
        require(
            system == store.system
            and system
            in {"pdm", "crm", "oa", "hr_sap", "hr_beisen", "hr_dingtalk", "srm"},
            "Enterprise store identity mismatch",
        )
        super().__init__(store, registry)

    validate_fact = staticmethod(validate_fact)

    def prepare(self, operation, observations):
        facts = super().prepare(operation, observations)
        p = operation.payload
        causes = []
        if p.operation in {
            "hr_beisen.publish_qualification",
            "hr_dingtalk.assign_shift",
        }:
            employee = observations.fact(p.employee)
            require(
                employee.payload.fact_type == "hr_sap.employee",
                "Employee source required",
            )
            current = [
                f
                for f in observations.of_type("hr_sap.employee")
                if f.payload.employee_id == employee.payload.employee_id
            ][-1]
            require(
                current.source_key == employee.source_key and current.payload.active,
                "Current active employee required",
            )
            causes.append(employee.source_key)
        if p.operation in {"oa.request_approval", "oa.decide_approval"}:
            observations.fact(p.target.source_key)
            causes.append(p.target.source_key)
            if p.operation == "oa.decide_approval":
                request = observations.fact(p.request)
                require(
                    request.payload.fact_type
                    in {"oa.approval_request", "mes.approval_request"}
                    and request.payload.target == p.target,
                    "OA exact request target required",
                )
                require(
                    not any(
                        f.payload.request == p.request
                        for f in observations.of_type("oa.approval_decision")
                    ),
                    "OA request already decided",
                )
                causes.append(p.request)
        if p.operation == "srm.promise":
            request = observations.fact(p.purchase_requirement)
            require(
                request.payload.fact_type == "sap.purchase_requirement"
                and request.payload.requirement_id == p.requirement_id,
                "Exact SAP purchase requirement required",
            )
            causes.append(p.purchase_requirement)
        if p.operation == "srm.announce_arrival":
            observations.fact(p.promise)
            causes.append(p.promise)
        if p.operation == "pdm.issue_change":
            observations.fact(p.released_revision)
            causes.append(p.released_revision)
        if p.operation in {
            "crm.open_return",
            "overseas.report_return",
            "overseas.receive_shipment",
            "customer.confirm_delivery",
        }:
            from .external_claims import source_causes, accepted_units

            causes.extend(source_causes(p, observations))
            if p.operation in {
                "overseas.receive_shipment",
                "customer.confirm_delivery",
            }:
                tag = (
                    "customer.acceptance"
                    if p.operation == "customer.confirm_delivery"
                    else "overseas.delivery_receipt"
                )
                for previous in observations.of_type(tag):
                    require(
                        not accepted_units(previous.payload) & accepted_units(p),
                        "Serial already confirmed by counterparty",
                    )
        return [f.model_copy(update={"caused_by": causes}) for f in facts]

    def consume_fact(self, tx, delivery, observations):
        if self.store.system == "pdm":
            from .bom_sync import emit_confirmation

            emit_confirmation(self, tx, delivery, observations)

    def transition(self, tx, operation, facts, observations):
        # These immutable source records are their own owned enterprise state.
        require(operation.system == self.store.system, "Enterprise source mismatch")


def register_enterprise(registry):
    for system in ("pdm", "crm", "oa", "hr_sap", "hr_beisen", "hr_dingtalk", "srm"):
        registry.register(
            system,
            factory=lambda store, system=system: EnterpriseSystem(
                system, store, registry
            ),
            projector=project_fact,
            authorize=authorize,
        )


def register_enterprise_network(registry):
    from .core_systems import register_core

    register_core(registry)
    register_enterprise(registry)
    from .evidence_systems import register_evidence

    register_evidence(registry)
