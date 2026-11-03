"""Exact enterprise evidence admission and shared manufacturing domain writes."""

from .. import engineering, orders, supply, introduction, quality, eco
from ..supply_models import CommitSupply
from ..introduction_models import ReviewNPI
from ..quality_models import Disposition
from ..eco_models import OpenEco
from .enterprise_admission import projected_fact, validate_target
from ..engineering_models import RecordRevision
from ..order_models import RecordDemand
from .contracts import AuxiliaryRef, ObjectRef, ProjectionResult
from .core_projections import command_data, domain_id
from .core_guards import require
from .enterprise_models import (
    EmployeeRecord,
    QualificationRecord,
    ShiftRecord,
    BomConfirmationRecord,
    ApprovalRequestRecord,
    ApprovalDecisionRecord,
    SupplierNotice,
)
from .store import canonical_hash


def translated(context, fact):
    p, base = fact.payload, command_data(context)
    if p.fact_type == "pdm.revision":
        fields = p.model_dump(
            mode="json", exclude={"fact_type", "released_at", "bom_materials"}
        )
        return RecordRevision(**base, action="engineering.revision", **fields)
    if p.fact_type == "crm.demand":
        return RecordDemand(
            **base,
            action="demand.record",
            source=fact.source,
            kind=p.demand_kind,
            product=p.product,
            quantity=str(p.amount.quantity),
            unit=p.amount.unit,
            due_date=p.due_date,
            supersedes_demand_id=p.supersedes_demand_id,
        )

    if p.fact_type == "srm.promise":
        return CommitSupply(
            **base,
            action="supply.commit",
            requirement_id=p.requirement_id,
            type=p.supply_type,
            owner_id=p.owner_id,
            quantity=str(p.amount.quantity),
            unit=p.amount.unit,
            original_due=p.original_due,
            current_due=p.current_due,
            source=fact.source,
        )
    if p.fact_type == "pdm.change":
        return OpenEco(
            **base,
            action="eco.open",
            old_revision_id=p.from_revision_id,
            new_revision_id=p.to_revision_id,
            effective_work_order_ids=[p.work_order_id],
            effective_sn_ids=p.boundary_unit_ids,
            reason=p.reason,
        )
    if p.fact_type == "oa.approval_decision" and p.decision == "approved":
        t = p.target
        if t.target_type == "engineering":
            return ReviewNPI(
                **base, action="npi.review", npi_id=t.npi_id, checks=t.checks
            )
        return Disposition(
            **base,
            action="nonconformance.disposition",
            nonconformance_id=t.nonconformance_id,
            decision=t.disposition,
            route_id=t.route_id,
            route_steps=t.route_steps,
            evidence=p.evidence,
        )


def validate_fact(tx, context, fact):
    p = fact.payload
    project = orders.project(tx, context.project_id)
    require(fact.project_id == context.project_id, "Source project mismatch")
    require(
        fact.source.occurred_at <= fact.source.collected_at <= context.now,
        "Enterprise source timestamp invalid",
    )
    command = translated(context, fact)
    if p.fact_type == "pdm.revision":
        require(p.released_at <= context.now, "Engineering release is in the future")
        engineering.validate_revision(tx, context, command)
    elif p.fact_type == "pdm.bom_confirmation":
        revision = projected_fact(tx, context.project_id, p.released_revision)
        from .bom_sync import bom_digest

        require(
            revision.payload.fact_type == "pdm.revision"
            and revision.payload.bom_materials == p.bom_materials
            and bom_digest(p.bom_materials) == p.bom_digest,
            "BOM confirmation differs from projected release",
        )
        orders.own(tx, "work_orders", context.project_id, p.work_order_id)
    elif p.fact_type == "crm.demand":
        require(
            (p.customer_id, p.amount.unit, p.amount.scale)
            == (project["customer_id"], project["unit_code"], project["unit_scale"]),
            "Demand customer/dimensions mismatch",
        )
        orders.validate_demand(tx, context, command)
    elif p.fact_type == "crm.return_claim":
        from .external_claims import validate

        validate(tx, context, fact)
    elif p.fact_type == "pdm.change":
        projected_fact(
            tx,
            context.project_id,
            p.released_revision,
            kind="revision",
            ident=p.to_revision_id,
        )
        wo = orders.own(tx, "work_orders", context.project_id, p.work_order_id)
        require(
            wo["revision_id"] == str(p.from_revision_id)
            and p.from_revision_id != p.to_revision_id,
            "ECN revision boundary mismatch",
        )
        for uid in p.boundary_unit_ids:
            unit = orders.own(tx, "units", context.project_id, uid)
            require(
                (unit["work_order_id"], unit["revision_id"])
                == (str(p.work_order_id), str(p.from_revision_id)),
                "ECN unit boundary mismatch",
            )
    elif p.fact_type in {"oa.approval_request", "oa.approval_decision"}:
        validate_target(tx, context, p.target)
        if p.fact_type == "oa.approval_decision":
            request = projected_fact(tx, context.project_id, p.request)
            require(
                request.payload.fact_type
                in {"oa.approval_request", "mes.approval_request"}
                and request.payload.target == p.target,
                "OA request target/version mismatch",
            )
            require(p.signed_at <= context.now, "OA signature is in the future")
            if command and p.target.target_type == "quality":
                quality.validate_disposition(tx, context, command)
            if command and p.target.target_type == "engineering":
                require(
                    not any(
                        c.decision == "blocked" for c in p.target.checks if c.required
                    ),
                    "Approved OA decision contains blocked checks",
                )
    elif p.fact_type == "srm.promise":
        require(
            not tx.execute(
                "SELECT 1 FROM supply_commitments WHERE id=?", (str(p.commitment_id),)
            ).fetchone(),
            "SRM commitment identity already exists",
        )
        supply.validate_commitment(tx, context, command)
        req = orders.own(tx, "requirements", context.project_id, p.requirement_id)
        require(p.amount.scale == req["scale"], "SRM promise precision mismatch")
    elif p.fact_type == "srm.arrival":
        promise = projected_fact(
            tx, context.project_id, p.promise, kind="commitment", ident=p.commitment_id
        )
        require(
            promise.payload.fact_type == "srm.promise", "Exact SRM promise required"
        )
        q = promise.payload
        req = orders.own(tx, "requirements", context.project_id, q.requirement_id)
        require(
            (p.material_id, p.supplier_id, p.amount.unit, p.amount.scale)
            == (req["material_id"], q.supplier_id, q.amount.unit, q.amount.scale)
            and p.amount.quantity <= q.amount.quantity,
            "ASN scope differs from supplier promise",
        )
    elif p.fact_type == "hr_dingtalk.shift":
        orders.own(tx, "work_orders", context.project_id, p.work_order_id)
    elif p.fact_type not in {"hr_sap.employee", "hr_beisen.qualification"}:
        require(False, "Enterprise fact admission not implemented")


def auxiliary_record(fact):
    cls = {
        "hr_sap.employee": EmployeeRecord,
        "hr_beisen.qualification": QualificationRecord,
        "hr_dingtalk.shift": ShiftRecord,
        "oa.approval_request": ApprovalRequestRecord,
        "oa.approval_decision": ApprovalDecisionRecord,
        "srm.arrival": SupplierNotice,
        "pdm.bom_confirmation": BomConfirmationRecord,
    }.get(fact.payload.fact_type)
    if cls is None:
        return None
    return cls(
        project_id=fact.project_id,
        source_key=fact.source_key,
        payload_hash=canonical_hash(fact),
        **fact.payload.model_dump(mode="json", exclude={"fact_type"}),
    )


def project_fact(tx, context, fact):
    validate_fact(tx, context, fact)
    p, targets, auxiliary = fact.payload, [], []
    command = translated(context, fact)
    if p.fact_type == "pdm.revision":
        result = engineering.record_revision(tx, context, command)
    elif p.fact_type == "crm.demand":
        result = orders._record_demand(tx, context, command)
    elif p.fact_type == "crm.return_claim":
        from .external_claims import project

        targets.extend(project(tx, context, fact))
        result = None
    elif p.fact_type == "srm.promise":
        result = supply._commit_supply(
            tx, context, command, assigned_id=p.commitment_id
        )
    elif p.fact_type == "pdm.change":
        result = eco.open_eco(tx, context, command)
    elif p.fact_type == "oa.approval_decision" and command:
        result = (
            introduction.review_npi(tx, context, command)
            if p.target.target_type == "engineering"
            else quality.disposition(tx, context, command)
        )
    else:
        result = None
        require(
            auxiliary_record(fact) is not None, "Typed enterprise read model required"
        )
    record = auxiliary_record(fact)
    if record:
        auxiliary.append(
            AuxiliaryRef(
                project_id=context.project_id, kind=record.kind, id=domain_id(fact)
            )
        )
    if result:
        targets.append(
            ObjectRef(
                project_id=context.project_id,
                kind=result.object_type,
                id=result.object_id,
            )
        )
    return ProjectionResult(
        project_id=context.project_id,
        source_key=fact.source_key,
        payload_hash=canonical_hash(fact),
        targets=targets,
        auxiliary=auxiliary,
    )
