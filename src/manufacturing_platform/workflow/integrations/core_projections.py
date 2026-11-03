"""Trusted core fact translation into existing domain validators and persistence."""

from uuid import NAMESPACE_URL, UUID, uuid5

from .. import engineering, orders, supply
from ..contracts import ObjectKind
from ..engineering_models import RegisterWorkOrder
from ..exchange_models import InboundIQC, InboundReceipt
from ..order_models import RegisterOrder
from ..supply_models import ReceivePlan
from .contracts import AuxiliaryRef, ObjectRef, ProjectionResult
from .core_guards import require
from .core_admission import execution_command, test_command
from .store import canonical_hash, identity


def domain_id(fact):
    return uuid5(
        NAMESPACE_URL, ":".join(map(str, identity(fact.project_id, fact.source_key)))
    )


def command_data(context):
    return dict(operation_id=UUID(int=0), expected_version=context.project_version)


def translated(context, fact):
    p, base = fact.payload, command_data(context)
    if p.fact_type == "sap.order":
        return RegisterOrder(
            **base,
            action="order.register",
            source=fact.source,
            demand_id=p.demand_id,
            quantity=str(p.amount.quantity),
            unit=p.amount.unit,
            due_date=p.due_date,
        )
    if p.fact_type == "sap.work_order":
        return RegisterWorkOrder(
            **base,
            action="work_order.register",
            source=fact.source,
            order_line_id=p.order_line_id,
            revision_id=p.revision_id,
            quantity=str(p.amount.quantity),
            unit=p.amount.unit,
            purpose=p.purpose,
            trial_quantity=str(p.trial_amount.quantity),
            planned_start=p.planned_start.isoformat(),
            planned_end=p.planned_end.isoformat(),
        )
    if p.fact_type == "sap.plan":
        return ReceivePlan(
            **base,
            action="plan.receive",
            source=fact.source.model_copy(update={"cutoff": p.cutoff}),
            input_revision_ids=p.input_revision_ids,
            input_order_versions=[v.model_dump() for v in p.input_order_versions],
            requirements=[
                dict(
                    work_order_id=r.work_order_id,
                    execution_scope=r.execution_scope,
                    material_id=r.material_id,
                    owner_id=r.owner_id,
                    quantity=str(r.amount.quantity),
                    unit=r.amount.unit,
                )
                for r in p.requirements
            ],
        )


def validate_fact(tx, context, fact):
    """Read-only domain admission, used both before source commit and at projection."""
    p = fact.payload
    project = orders.project(tx, context.project_id)
    require(fact.project_id == context.project_id, "Source project mismatch")
    command = translated(context, fact)
    if p.fact_type == "sap.order":
        require(
            (p.customer_id, p.product, p.amount.unit, p.amount.scale)
            == (
                project["customer_id"],
                project["product"],
                project["unit_code"],
                project["unit_scale"],
            ),
            "Order scope mismatch",
        )
        orders.validate_order(tx, context, command)
    elif p.fact_type == "sap.work_order":
        require(
            (p.amount.unit, p.amount.scale)
            == (project["unit_code"], project["unit_scale"]),
            "Work order dimensions mismatch",
        )
        row = tx.execute(
            "SELECT result_json FROM integration_projections WHERE project_id=? AND system=? AND object_type=? AND external_id=? AND version=?",
            identity(context.project_id, p.released_revision),
        ).fetchone()
        require(
            row is not None
            and any(
                t.kind == ObjectKind.revision and t.id == p.revision_id
                for t in ProjectionResult.model_validate_json(row[0]).targets
            ),
            "Exact released PDM revision must be projected",
        )
        engineering.validate_work_order(tx, context, command)
    elif p.fact_type == "sap.plan":
        reasons, _material_meta = supply.validate_plan(tx, context, command)
        require(not reasons, "; ".join(dict.fromkeys(reasons)))
        for req in p.requirements:
            lot = tx.execute(
                "SELECT scale FROM material_lots WHERE project_id=? AND material_id=? AND owner_id=?",
                (str(context.project_id), req.material_id, req.owner_id),
            ).fetchone()
            require(
                lot is not None and lot[0] == req.amount.scale,
                "Plan material scale mismatch",
            )
            require(
                not tx.execute(
                    "SELECT 1 FROM requirements WHERE id=?", (str(req.requirement_id),)
                ).fetchone(),
                "Requirement identity already exists",
            )
    elif p.fact_type == "wms.receipt":
        lot = orders.own(tx, "material_lots", context.project_id, p.material_lot_id)
        commitment = orders.own(
            tx, "supply_commitments", context.project_id, p.commitment_id
        )
        req = orders.own(
            tx, "requirements", context.project_id, commitment["requirement_id"]
        )
        require(
            (
                lot["lot_id"],
                lot["material_id"],
                lot["owner_id"],
                lot["unit"],
                lot["scale"],
                lot["expiry"],
            )
            == (
                p.lot_id,
                p.material_id,
                p.owner_id,
                p.amount.unit,
                p.amount.scale,
                p.expiry.isoformat(),
            ),
            "Receipt lot identity mismatch",
        )
        require(
            (req["material_id"], commitment["owner_id"], req["unit"], req["scale"])
            == (p.material_id, p.owner_id, p.amount.unit, p.amount.scale),
            "Receipt commitment dimensions mismatch",
        )
    elif p.fact_type == "wms.reservation_release":
        from .core_reservations import validate_projection

        validate_projection(tx, context, fact)
    elif p.fact_type == "mes.component":
        from ..laboratory import validate_install
        from ..laboratory_models import InstallComponent

        command = InstallComponent(
            **command_data(context),
            action="component.install",
            unit_id=p.unit_id,
            material_id=p.material_id,
            component_serial=p.component_serial,
            lot_id=p.material_lot_id,
            origin="demo",
            evidence=p.evidence,
        )
        unit = orders.own(tx, "units", context.project_id, p.unit_id)
        require(
            unit["work_order_id"] == str(p.work_order_id),
            "Component work order mismatch",
        )
        validate_install(tx, context, command)
    elif p.fact_type == "mes.completion":
        from ..quality import route_events
        from ..engineering import fixed_revision

        revision = fixed_revision(tx, context.project_id, p.revision_id)
        current_events = set()
        for member in p.units:
            unit = orders.own(tx, "units", context.project_id, member.unit_id)
            require(
                (unit["work_order_id"], unit["revision_id"], unit["sn"])
                == (str(p.work_order_id), str(p.revision_id), member.sn),
                "Completion unit scope mismatch",
            )
            current_events.update(
                route_events(
                    tx,
                    context.project_id,
                    unit,
                    revision.route_steps,
                    None,
                    p.occurred_at.isoformat(),
                )
            )
        declared_events = set()
        for key in p.execution_sources:
            row = tx.execute(
                "SELECT * FROM execution_events WHERE project_id=? AND source_system=? AND source_type=? AND source_external_id=? AND source_version=?",
                identity(context.project_id, key),
            ).fetchone()
            require(
                row is not None, "Completion requires projected current route execution"
            )
            from ..execution import admitted_execution_source

            source = admitted_execution_source(tx, context.project_id, row)
            require(source is not None, "Completion execution source admission missing")
            declared_events.add(row["id"])
        require(
            current_events == declared_events,
            "Completion requires exact current route execution",
        )
    elif p.fact_type == "mes.release":
        from ..quality import validate_release, latest_test
        from ..quality_models import DecideRelease

        command = DecideRelease(
            **command_data(context),
            action="release.decide",
            kind=p.kind,
            decision=p.decision,
            unit_ids=[u.unit_id for u in p.units],
            evidence=p.evidence,
        )
        validate_release(tx, context, command)
        proofs = {}
        for key in p.test_sources:
            row = tx.execute(
                "SELECT result_json FROM integration_projections WHERE project_id=? AND system=? AND object_type=? AND external_id=? AND version=?",
                identity(context.project_id, key),
            ).fetchone()
            require(row is not None, "Exact source test must be projected")
            for target in ProjectionResult.model_validate_json(row[0]).targets:
                if target.kind == ObjectKind.test:
                    test = orders.own(
                        tx, "quality_tests", context.project_id, target.id
                    )
                    proofs[test["unit_id"]] = test["id"]
        for member in p.units:
            unit = orders.own(tx, "units", context.project_id, member.unit_id)
            require(
                (unit["work_order_id"], unit["sn"])
                == (str(p.work_order_id), member.sn),
                "Release unit scope mismatch",
            )
            latest = latest_test(tx, context.project_id, member.unit_id)
            require(
                latest is not None and proofs.get(str(member.unit_id)) == latest["id"],
                "Release requires exact latest test proof",
            )
    elif p.fact_type == "product_test.test":
        from ..quality import validate_test

        command = test_command(context, fact)
        validate_test(tx, context, command, trusted_fact=fact)
    elif p.fact_type == "mes.execution":
        from ..execution import validate_execution

        command = execution_command(context, fact)
        validation = validate_execution(tx, context, command, trusted_fact=fact)
        require(not validation[6], validation[6] or "Execution invalid")
    elif p.fact_type == "mes.iqc":
        receipt = tx.execute(
            "SELECT r.* FROM effective_supply_receipts r WHERE r.project_id=? AND r.source_system=? AND r.source_type=? AND r.source_external_id=? AND r.source_version=?",
            identity(context.project_id, p.receipt),
        ).fetchone()
        require(receipt is not None, "Exact WMS receipt must be projected before IQC")
        lot = orders.own(
            tx, "material_lots", context.project_id, receipt["material_lot_id"]
        )
        require(
            (p.accepted.unit, p.accepted.scale) == (lot["unit"], lot["scale"]),
            "IQC dimensions mismatch",
        )
        from ..imports import record_scope, inspection_target

        record = InboundIQC(
            project_id=context.project_id,
            source=fact.source,
            external_actor=fact.external_actor,
            signature=fact.evidence,
            receipt_system=p.receipt.system,
            receipt_external_id=p.receipt.external_id,
            accepted=str(p.accepted.quantity),
            rejected=str(p.rejected.quantity),
            evidence=p.evidence,
            manual_iqc_id=p.manual_iqc_id,
        )
        record_scope(tx, context.project_id, record, object_type="iqc")
        inspection_target(tx, context.project_id, receipt["id"], record)
    return command


def project_fact(tx, context, fact):
    command = validate_fact(tx, context, fact)
    p, result, targets, auxiliary = fact.payload, None, [], []
    if p.fact_type == "sap.order":
        result = orders._register_order(tx, context, command, object_id=domain_id(fact))
    elif p.fact_type == "sap.work_order":
        result = engineering._register_work_order(
            tx, context, command, object_id=domain_id(fact)
        )
    elif p.fact_type == "sap.plan":
        result = supply._receive_plan(
            tx,
            context,
            command,
            object_id=domain_id(fact),
            requirement_ids=[r.requirement_id for r in p.requirements],
        )
        targets += [
            ObjectRef(project_id=context.project_id, kind="requirement", id=r[0])
            for r in tx.execute(
                "SELECT id FROM requirements WHERE project_id=? AND plan_id=?",
                (str(context.project_id), str(result.object_id)),
            )
        ]
    elif p.fact_type in {"wms.receipt", "mes.iqc"}:
        from ..imports import ingest

        fields = dict(
            project_id=context.project_id,
            source=fact.source,
            external_actor=fact.external_actor,
            signature=fact.evidence,
        )
        if p.fact_type == "wms.receipt":
            record = InboundReceipt(
                **fields,
                commitment_id=p.commitment_id,
                material_lot_id=p.material_lot_id,
                quantity=str(p.amount.quantity),
                unit=p.amount.unit,
            )
        else:
            record = InboundIQC(
                **fields,
                receipt_system=p.receipt.system,
                receipt_external_id=p.receipt.external_id,
                accepted=str(p.accepted.quantity),
                rejected=str(p.rejected.quantity),
                evidence=p.evidence,
                manual_iqc_id=p.manual_iqc_id,
            )
        result = ingest(
            tx,
            context,
            [record],
            object_type=record.object_type,
            trusted=True,
            system=fact.source.system,
            external_id=fact.source.external_id,
            mode="mock",
        )[0]
    elif p.fact_type == "wms.reservation_release":
        from .core_reservations import project_release

        targets.extend(project_release(tx, context, fact))
    elif p.fact_type == "mes.release":
        from ..quality import decide_release

        result = decide_release(tx, context, command)
    elif p.fact_type == "mes.component":
        from ..laboratory import _install

        result = _install(tx, context, command, trusted_fact=fact)
    elif p.fact_type == "mes.execution":
        from ..execution import _record_execution

        result = _record_execution(tx, context, command, trusted_fact=fact)
    elif p.fact_type in {
        "wms.reservation",
        "mes.containment",
        "mes.start",
        "mes.interruption",
        "mes.resume",
        "wms.shipment",
        "mes.revision_switch",
        "mes.remaining_cancellation",
    }:
        from .core_preparation import project_bound_effect

        if (
            p.fact_type == "mes.containment"
            and p.cause
            and (p.cause.system, p.cause.object_type)
            in {("crm", "return_claim"), ("overseas", "return_claim")}
        ):
            from .enterprise_admission import projected_fact

            original = projected_fact(tx, context.project_id, p.cause)
            require(
                p.decision == "frozen"
                and not p.material_lot_ids
                and set(p.unit_ids) == {u.unit_id for u in original.payload.units},
                "Return containment scope mismatch",
            )
            targets.extend(
                ObjectRef(project_id=context.project_id, kind="unit", id=uid)
                for uid in p.unit_ids
            )
        else:
            targets.extend(project_bound_effect(tx, context, fact))
        if p.fact_type == "wms.shipment":
            target = ObjectRef(
                project_id=context.project_id, kind="shipment", id=p.shipment_id
            )
            if target not in targets:
                targets.append(target)
        if p.fact_type == "mes.start":
            targets.extend(
                ObjectRef(project_id=context.project_id, kind="unit", id=u.unit_id)
                for u in p.units
            )
    elif p.fact_type == "mes.completion":
        targets.append(
            ObjectRef(
                project_id=context.project_id, kind="work_order", id=p.work_order_id
            )
        )
        targets.extend(
            ObjectRef(project_id=context.project_id, kind="unit", id=u.unit_id)
            for u in p.units
        )
    elif p.fact_type in {
        "wms.pick",
        "wms.return",
        "wms.putaway",
        "wms.custody",
        "wms.consumption",
        "mes.return_requirement",
    }:
        targets.extend(
            ObjectRef(project_id=context.project_id, kind="material_lot", id=lid)
            for lid in dict.fromkeys(a.material_lot_id for a in p.allocations)
        )
        if p.work_order_id:
            targets.append(
                ObjectRef(
                    project_id=context.project_id, kind="work_order", id=p.work_order_id
                )
            )
    elif p.fact_type == "wms.stocktake":
        targets.append(
            ObjectRef(
                project_id=context.project_id, kind="material_lot", id=p.material_lot_id
            )
        )
    elif p.fact_type == "wms.qualification":
        targets.append(
            ObjectRef(
                project_id=context.project_id, kind="material_lot", id=p.material_lot_id
            )
        )
    else:
        auxiliary.append(
            AuxiliaryRef(
                project_id=context.project_id,
                kind="accounting" if fact.source.system == "sap" else "network_context",
                id=domain_id(fact),
            )
        )
    if result:
        targets.insert(
            0,
            ObjectRef(
                project_id=context.project_id,
                kind=result.object_type,
                id=result.object_id,
            ),
        )
    return ProjectionResult(
        project_id=context.project_id,
        source_key=fact.source_key,
        payload_hash=canonical_hash(fact),
        targets=targets,
        auxiliary=auxiliary,
    )
