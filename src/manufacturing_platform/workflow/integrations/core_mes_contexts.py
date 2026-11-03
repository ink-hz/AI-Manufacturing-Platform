"""MES preparation, completion returns and actual postshipment causal contexts."""

from .core_guards import require
from .core_projections import domain_id


def prepare_contexts(system, operation, observations, facts):
    p = operation.payload
    if p.operation == "mes.prepare":
        import json
        from uuid import NAMESPACE_URL, uuid5
        from ..orders import own
        from ..engineering import fixed_revision

        wo_fact = next(
            (
                f
                for f in observations.of_type("sap.work_order")
                if domain_id(f) == p.work_order_id
            ),
            None,
        )
        if wo_fact is None:
            wo_fact = next(
                (
                    f
                    for f in observations.of_type("mes.revision_switch")
                    if f.payload.replacement_work_order_id == p.work_order_id
                ),
                None,
            )
        require(wo_fact is not None, "Actual source work order required")
        revision_fact = observations.fact(
            released_revision(observations, p.work_order_id)
        )
        with system.registry.workflow_store.transaction() as tx:
            wo = own(tx, "work_orders", operation.project_id, p.work_order_id)
            revision = fixed_revision(tx, operation.project_id, wo["revision_id"])
            plan = json.loads(
                own(tx, "test_plans", operation.project_id, p.test_plan_id)[
                    "payload_json"
                ]
            )
            require(
                plan["revision_id"] == wo["revision_id"]
                and plan["equipment"] == p.equipment_id,
                "Preparation test plan/equipment mismatch",
            )
            if p.approval_target is not None:
                validate_approval_target(
                    tx, operation.project_id, p, observations, revision_fact.source_key
                )
            units = [own(tx, "units", operation.project_id, uid) for uid in p.unit_ids]
            require(
                all(
                    u["work_order_id"] == wo["id"]
                    and u["revision_id"] == wo["revision_id"]
                    and u["state"] == "registered"
                    for u in units
                ),
                "Preparation requires registered exact work order units",
            )
        causes = [wo_fact.source_key, revision_fact.source_key]
        facts[0] = facts[0].model_copy(update={"caused_by": causes})
        for unit in units:
            for step in revision.route_steps:
                payload = dict(
                    fact_type="mes.process_request",
                    work_order_id=p.work_order_id,
                    unit_id=unit["id"],
                    revision_id=wo["revision_id"],
                    equipment=p.equipment_id,
                    station=step.station,
                    program_version=revision.test_spec.program_version,
                )
                facts.append(
                    system.make_fact(
                        operation.project_id,
                        payload,
                        uuid5(
                            NAMESPACE_URL,
                            f"{operation.operation_id}:process:{unit['id']}:{step.station}",
                        ),
                        causes=[facts[0].source_key, *causes],
                    )
                )
            payload = dict(
                fact_type="mes.test_request",
                work_order_id=p.work_order_id,
                unit_id=unit["id"],
                revision_id=wo["revision_id"],
                plan_id=p.test_plan_id,
                route_version=revision.route_steps[0].instruction_version,
                program_version=revision.test_spec.program_version,
                firmware_version=revision.firmware_version,
            )
            facts.append(
                system.make_fact(
                    operation.project_id,
                    payload,
                    uuid5(NAMESPACE_URL, f"{operation.operation_id}:test:{unit['id']}"),
                    causes=[facts[0].source_key, *causes],
                )
            )
        if p.approval_target is not None:
            payload = dict(
                fact_type="mes.approval_request",
                target=p.approval_target.model_dump(mode="json"),
                requested_by="MES preparation",
                evidence="Explicit prepared approval target",
            )
            facts.append(
                system.make_fact(
                    operation.project_id,
                    payload,
                    uuid5(NAMESPACE_URL, f"{operation.operation_id}:approval"),
                    causes=[facts[0].source_key, *causes],
                )
            )
    elif p.operation == "mes.complete":
        from uuid import uuid5, NAMESPACE_URL

        facts[0] = facts[0].model_copy(update={"caused_by": p.execution_sources})
        covered = set()
        for picked in observations.of_type("wms.pick"):
            if picked.payload.work_order_id != p.work_order_id:
                continue
            remaining = []
            for a in picked.payload.allocations:
                key = (
                    a.material_lot_id,
                    a.qualification.model_dump_json(),
                    a.reservation.model_dump_json(),
                )
                if key in covered:
                    continue
                covered.add(key)
                used = sum(
                    v.amount.quantity
                    for f in observations.of_type("mes.execution")
                    if f.payload.work_order_id == p.work_order_id
                    for v in f.payload.material_uses
                    if v.material_lot_id == a.material_lot_id
                    and v.reservation == a.reservation
                    and v.qualification == a.qualification
                )
                returned = sum(
                    v.amount.quantity
                    for f in observations.of_type("wms.return")
                    if f.payload.direction == "to_warehouse"
                    and f.payload.work_order_id == p.work_order_id
                    for v in f.payload.allocations
                    if v.material_lot_id == a.material_lot_id
                    and v.reservation == a.reservation
                    and v.qualification == a.qualification
                )
                # Each reserved allocation has one net outstanding line-side scope.
                total = sum(
                    v.amount.quantity
                    for f in observations.of_type("wms.pick")
                    if f.payload.work_order_id == p.work_order_id
                    for v in f.payload.allocations
                    if v.material_lot_id == a.material_lot_id
                    and v.reservation == a.reservation
                    and v.qualification == a.qualification
                )
                outstanding = total - used - returned
                if outstanding > 0:
                    value = a.model_dump(mode="json")
                    value["amount"]["quantity"] = str(outstanding)
                    remaining.append(value)
            if remaining:
                payload = dict(
                    fact_type="mes.return_requirement",
                    work_order_id=p.work_order_id,
                    allocations=remaining,
                    source_custody=picked.payload.destination_custody,
                    destination_custody=picked.payload.source_custody,
                    cause=facts[0].source_key,
                    evidence="Completion requests unused line stock return",
                )
                facts.append(
                    system.make_fact(
                        operation.project_id,
                        payload,
                        uuid5(
                            NAMESPACE_URL,
                            f"{operation.operation_id}:return:{picked.source.external_id}",
                        ),
                        causes=[facts[0].source_key, picked.source_key],
                    )
                )
    return facts


def emit_delivery_context(system, tx, delivery, observations):
    if delivery.fact.payload.fact_type != "wms.shipment":
        return
    from uuid import NAMESPACE_URL, uuid5

    shipment = delivery.fact
    releases = [observations.fact(key) for key in shipment.payload.releases]
    groups = {}
    for release in releases:
        require(
            release.payload.fact_type == "mes.release"
            and release.payload.decision == "approved",
            "Shipment lacks approved MES release",
        )
        groups.setdefault(release.payload.work_order_id, []).append(release)
    for work_order_id, scoped in groups.items():
        members = {u.unit_id for release in scoped for u in release.payload.units}
        units = [u for u in shipment.payload.units if u.unit_id in members]
        revision_key = released_revision(observations, work_order_id)
        tests = list(
            {
                key.model_dump_json(): key
                for release in scoped
                for key in release.payload.test_sources
                if observations.fact(key).payload.unit_id in {u.unit_id for u in units}
            }.values()
        )
        payload = dict(
            fact_type="mes.delivery_context",
            work_order_id=work_order_id,
            units=[u.model_dump(mode="json") for u in units],
            revision=revision_key,
            releases=[r.source_key for r in scoped],
            shipment=shipment.source_key,
            quality_sources=tests,
        )
        fact = system.make_fact(
            delivery.project_id,
            payload,
            uuid5(NAMESPACE_URL, f"{delivery.delivery_id}:context:{work_order_id}"),
            causes=[shipment.source_key, *[r.source_key for r in scoped], *tests],
        )
        system.emit(tx, fact)


def released_revision(observations, work_order_id):
    for f in observations.of_type("sap.work_order"):
        if domain_id(f) == work_order_id:
            return f.payload.released_revision
    for f in observations.of_type("mes.revision_switch"):
        if f.payload.replacement_work_order_id == work_order_id:
            return observations.fact(f.payload.change).payload.released_revision
    require(False, "Actual source work order revision lineage required")


def validate_approval_target(
    tx, project_id, preparation, observations, revision_source
):
    import json
    from ..orders import own

    target = preparation.approval_target
    cause = observations.fact(target.source_key)
    wo = own(tx, "work_orders", project_id, preparation.work_order_id)
    if target.target_type == "engineering":
        npi = own(tx, "npis", project_id, target.npi_id)
        require(
            str(target.revision_id) == wo["revision_id"] == npi["revision_id"]
            and target.source_key == revision_source,
            "Prepared approval revision/source mismatch",
        )
        bound = [
            r[0]
            for r in tx.execute(
                "SELECT work_order_id FROM npi_work_orders WHERE project_id=? AND npi_id=?",
                (str(project_id), str(target.npi_id)),
            )
        ]
        require(
            not bound or str(preparation.work_order_id) in bound,
            "Prepared approval work order outside NPI",
        )
        require(
            set(json.loads(npi["required_checks_json"]))
            <= {c.code for c in target.checks},
            "Prepared approval omits required review checks",
        )
    else:
        nc = own(tx, "nonconformances", project_id, target.nonconformance_id)
        require(
            target.work_order_id == preparation.work_order_id
            and nc["unit_id"] in {str(u) for u in preparation.unit_ids},
            "Prepared disposition target mismatch",
        )
        unit_id = getattr(
            cause.payload,
            "unit_id",
            getattr(getattr(cause.payload, "unit", None), "unit_id", None),
        )
        require(
            cause.payload.fact_type in {"product_test.test", "mes.execution"}
            and str(unit_id) == nc["unit_id"]
            and cause.payload.work_order_id == preparation.work_order_id,
            "Prepared disposition source scope mismatch",
        )
