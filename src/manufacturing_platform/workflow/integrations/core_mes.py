"""MES quality state owns receipt-scoped inspection decisions."""

from uuid import UUID

from .core_guards import require
from .core_systems import CoreSystem
from .core_projections import domain_id


class MesSystem(CoreSystem):
    def prepare(self, operation, observations):
        p = operation.payload
        if p.operation in {"mes.switch_revision", "mes.cancel_remaining"}:
            from .core_preparation import bound_requests

            with self.registry.workflow_store.transaction() as tx:
                requests = bound_requests(
                    tx, operation.project_id, operation.operation_id
                )
                require(
                    len(requests) == 1
                    and requests[0].typed_payload.kind == "eco_switch",
                    "Prepared ECO scope required",
                )
                request = requests[0].typed_payload
                project = tx.execute(
                    "SELECT unit_code,unit_scale FROM projects WHERE id=?",
                    (str(operation.project_id),),
                ).fetchone()
            payload = p.model_dump(mode="json", exclude={"operation"})
            payload["remaining_amount"] = dict(
                quantity=str(request.remaining_quantity),
                unit=project["unit_code"],
                scale=project["unit_scale"],
            )
            payload["fact_type"] = (
                "mes.revision_switch"
                if p.operation == "mes.switch_revision"
                else "mes.remaining_cancellation"
            )
            if p.operation == "mes.switch_revision":
                payload["replacement_work_order_id"] = request.new_work_order_id
            facts = [
                self.make_fact(
                    operation.project_id,
                    payload,
                    operation.operation_id,
                    causes=[p.change, p.approval]
                    if p.operation == "mes.switch_revision"
                    else [],
                )
            ]
        else:
            facts = super().prepare(operation, observations)
        if p.operation in {"mes.prepare", "mes.complete"}:
            from .core_mes_contexts import prepare_contexts

            facts = prepare_contexts(self, operation, observations, facts)
        elif p.operation == "mes.interrupt":
            starts = [
                f
                for f in observations.of_type("mes.start")
                if f.payload.work_order_id == p.work_order_id
            ]
            if p.start_id:
                with self.registry.workflow_store.transaction() as tx:
                    row = tx.execute(
                        "SELECT accepted_receipt_id FROM start_requests WHERE project_id=? AND id=? AND work_order_id=?",
                        (
                            str(operation.project_id),
                            str(p.start_id),
                            str(p.work_order_id),
                        ),
                    ).fetchone()
                    members = {
                        r[0]
                        for r in tx.execute(
                            "SELECT unit_id FROM start_units WHERE project_id=? AND start_id=?",
                            (str(operation.project_id), str(p.start_id)),
                        )
                    }
                require(
                    row is not None and row[0] is not None,
                    "Scoped stop requires actual accepted start",
                )
                starts = [
                    f
                    for f in starts
                    if {str(u.unit_id) for u in f.payload.units} == members
                ]
            require(bool(starts), "No actual source start to stop")
            facts[0] = facts[0].model_copy(
                update={"caused_by": [f.source_key for f in starts]}
            )
        elif p.operation in {"mes.start", "mes.pass"}:
            facts[0] = facts[0].model_copy(
                update={"caused_by": self.eligibility(operation, observations)}
            )
        elif p.operation == "mes.resume":
            from .core_eligibility import current_start

            starts = [
                f
                for f in observations.of_type("mes.start")
                if f.payload.work_order_id == p.work_order_id
                and (p.scope == "all" or f.payload.mode == "trial")
            ]
            causes = []
            for start in starts:
                causes.extend(
                    self.eligibility(
                        current_start(
                            operation, start, observations, self.store.clock()
                        ),
                        observations,
                    )
                )
            causes.extend(
                f.source_key
                for f in observations.of_type("mes.interruption")
                if f.payload.interruption_id == p.interruption_id
            )
            causes.extend(
                f.source_key
                for f in observations.of_type("sap.plan")
                if domain_id(f) == p.plan_id
            )
            facts[0] = facts[0].model_copy(
                update={
                    "caused_by": list({k.model_dump_json(): k for k in causes}.values())
                }
            )
        if p.operation == "mes.assemble":
            facts[0] = facts[0].model_copy(update={"caused_by": [p.execution]})
        if p.operation == "mes.release":
            facts[0] = facts[0].model_copy(update={"caused_by": p.test_sources})
        if operation.payload.operation == "mes.inspect":
            facts[0] = facts[0].model_copy(
                update={"caused_by": [operation.payload.receipt]}
            )
        elif operation.payload.operation == "mes.contain":
            facts[0] = facts[0].model_copy(
                update={
                    "caused_by": ([p.cause] if p.cause else []) + p.additional_causes
                }
            )
        return facts

    def transition(self, tx, operation, facts, observations):
        p = operation.payload
        if p.operation in {"mes.prepare", "mes.shortage"}:
            return
        if p.operation == "mes.assemble":
            execution = observations.fact(p.execution).payload
            require(
                execution.fact_type == "mes.execution"
                and execution.work_order_id == p.work_order_id
                and execution.unit.unit_id == p.unit_id
                and execution.result == "pass",
                "Component execution scope mismatch",
            )
            require(
                any(
                    a.material_lot_id == p.material_lot_id
                    and a.material_id == p.material_id
                    for a in execution.material_uses
                ),
                "Component must bind actual consumed material",
            )
            observations.containment(unit_ids=[p.unit_id], lot_ids=[p.material_lot_id])
            return
        if p.operation == "mes.start":
            observations.containment(unit_ids=[u.unit_id for u in p.units])
            prior = {
                u.unit_id
                for f in observations.of_type("mes.start")
                for u in f.payload.units
            }
            require(
                not prior.intersection(u.unit_id for u in p.units),
                "Source unit already started",
            )
            return
        if p.operation in {"mes.switch_revision", "mes.cancel_remaining"}:
            retained = {
                u.unit_id
                for f in observations.of_type("mes.start")
                if f.payload.work_order_id == p.work_order_id
                for u in f.payload.units
            }
            declared = (
                {u.unit_id for u in p.units}
                if p.operation == "mes.switch_revision"
                else set(p.retained_unit_ids)
            )
            require(retained == declared, "ECO retained unit conservation mismatch")
            require(
                not any(
                    f.payload.work_order_id == p.work_order_id
                    for tag in ("mes.revision_switch", "mes.remaining_cancellation")
                    for f in observations.of_type(tag)
                ),
                "Source remaining scope already disposed",
            )
            if p.operation == "mes.switch_revision":
                change, approval = (
                    observations.fact(p.change),
                    observations.fact(p.approval),
                )
                require(
                    change.payload.fact_type == "pdm.change"
                    and (
                        change.payload.work_order_id,
                        change.payload.from_revision_id,
                        change.payload.to_revision_id,
                    )
                    == (p.work_order_id, p.from_revision_id, p.to_revision_id),
                    "PDM change scope mismatch",
                )
                require(
                    approval.payload.fact_type == "oa.approval_decision"
                    and approval.payload.decision == "approved"
                    and approval.payload.target.target_type == "engineering"
                    and approval.payload.target.revision_id == p.to_revision_id
                    and approval.payload.target.source_key
                    == change.payload.released_revision,
                    "OA change approval scope mismatch",
                )
                current = [
                    f
                    for f in observations.of_type("oa.approval_decision")
                    if f.payload.request == approval.payload.request
                ]
                require(
                    current[-1].source_key == approval.source_key
                    and current[-1].payload.decision == "approved",
                    "OA approval is no longer current",
                )
                request = observations.fact(approval.payload.request)
                require(
                    request.payload.fact_type == "oa.approval_request"
                    and request.payload.target == approval.payload.target,
                    "OA decision differs from actual request target",
                )
            return
        if p.operation == "mes.complete":
            from .store import canonical

            require(
                len({k.model_dump_json() for k in p.execution_sources})
                == len(p.execution_sources),
                "Duplicate completion execution",
            )
            executions = [observations.fact(key) for key in p.execution_sources]
            units = {u.unit_id for u in p.units}
            require(
                {f.payload.unit.unit_id for f in executions} == units
                and all(
                    f.payload.fact_type == "mes.execution"
                    and f.payload.work_order_id == p.work_order_id
                    and f.payload.revision_id == p.revision_id
                    and f.payload.result == "pass"
                    for f in executions
                ),
                "Completion requires exact passed execution scope",
            )
            require(
                sorted(canonical(a) for a in p.consumption)
                == sorted(
                    canonical(a) for f in executions for a in f.payload.material_uses
                ),
                "Completion consumption must reconcile exact execution consumption",
            )
            require(
                not any(
                    units.intersection(u.unit_id for u in f.payload.units)
                    for f in observations.of_type("mes.completion")
                ),
                "Unit completion already recorded",
            )
            return
        if p.operation == "mes.release":
            units = {u.unit_id for u in p.units}
            tests = [observations.fact(key) for key in p.test_sources]
            require(
                len({f.source_key.model_dump_json() for f in tests}) == len(tests)
                and {f.payload.unit_id for f in tests} == units,
                "Release test source scope mismatch",
            )
            for f in tests:
                require(
                    f.payload.fact_type == "product_test.test"
                    and f.payload.work_order_id == p.work_order_id,
                    "Qualified product-test source required",
                )
                latest = [
                    t
                    for t in observations.of_type("product_test.test")
                    if t.payload.unit_id == f.payload.unit_id
                ][-1]
                require(
                    latest.source_key == f.source_key
                    and (p.decision != "approved" or f.payload.result == "pass"),
                    "Release requires latest passed source test",
                )
            lots = [
                a.material_lot_id
                for f in observations.of_type("mes.execution")
                if f.payload.unit.unit_id in units
                for a in f.payload.material_uses
            ]
            if p.decision == "approved":
                observations.containment(unit_ids=units, lot_ids=lots)
            return
        if p.operation == "mes.pass":
            observations.containment(
                unit_ids=[p.unit.unit_id],
                lot_ids=[a.material_lot_id for a in p.material_uses],
            )
            starts = [
                f
                for f in observations.of_type("mes.start")
                if any(
                    u.unit_id == p.unit.unit_id and u.sn == p.unit.sn
                    for u in f.payload.units
                )
            ]
            require(bool(starts), "Exact source-confirmed start required")
            for a in p.material_uses:
                require(
                    a.reservation is not None,
                    "Consumption requires reservation lineage",
                )
                reservation = observations.fact(a.reservation)
                require(
                    reservation.payload.work_order_id == p.work_order_id
                    and any(
                        v.material_lot_id == a.material_lot_id
                        and v.qualification == a.qualification
                        and v.owner_id == a.owner_id
                        and v.material_id == a.material_id
                        and (v.amount.unit, v.amount.scale)
                        == (a.amount.unit, a.amount.scale)
                        for v in reservation.payload.allocations
                    ),
                    "Consumption allocation scope mismatch",
                )
                picked = sum(
                    v.amount.quantity
                    for f in observations.of_type("wms.pick")
                    if f.payload.work_order_id == p.work_order_id
                    for v in f.payload.allocations
                    if v.reservation == a.reservation
                    and v.material_lot_id == a.material_lot_id
                    and v.qualification == a.qualification
                )
                used = sum(
                    v.amount.quantity
                    for f in observations.of_type("mes.execution")
                    for v in f.payload.material_uses
                    if v.reservation == a.reservation
                    and v.material_lot_id == a.material_lot_id
                    and v.qualification == a.qualification
                )
                proposed = sum(
                    v.amount.quantity
                    for v in p.material_uses
                    if v.reservation == a.reservation
                    and v.material_lot_id == a.material_lot_id
                    and v.qualification == a.qualification
                )
                returned = sum(
                    v.amount.quantity
                    for f in observations.of_type("wms.return")
                    if f.payload.direction == "to_warehouse"
                    for v in f.payload.allocations
                    if v.reservation == a.reservation
                    and v.material_lot_id == a.material_lot_id
                    and v.qualification == a.qualification
                )
                require(
                    used + proposed <= picked - returned,
                    "Execution exceeds physical line-side custody",
                )
            return
        if p.operation in {"mes.interrupt", "mes.resume"}:
            starts = [
                f
                for f in observations.of_type("mes.start")
                if f.payload.work_order_id == p.work_order_id
            ]
            require(bool(starts), "No source start to control")
            if p.operation == "mes.resume":
                stops = [
                    f
                    for f in observations.of_type("mes.interruption")
                    if f.payload.work_order_id == p.work_order_id
                ]
                require(
                    bool(stops)
                    and stops[-1].payload.interruption_id == p.interruption_id,
                    "Resume must reference current source interruption",
                )
                for start in starts:
                    if p.scope == "all" or start.payload.mode == "trial":
                        from .core_eligibility import current_start

                        self.eligibility(
                            current_start(
                                operation, start, observations, self.store.clock()
                            ),
                            observations,
                        )
                observations.containment(
                    unit_ids=[
                        u.unit_id for start in starts for u in start.payload.units
                    ]
                )
                require(
                    any(
                        domain_id(f) == p.plan_id
                        for f in observations.of_type("sap.plan")
                    ),
                    "Exact accepted SAP replan required",
                )
            return
        if p.operation == "mes.contain":
            for cause_key in ([p.cause] if p.cause else []) + p.additional_causes:
                cause = observations.fact(cause_key)
                require(
                    cause.source.system in {"mes", "product_test", "crm", "pdm"},
                    "Containment requires a quality/engineering cause",
                )
            if p.decision == "unfrozen":
                latest = {}
                for previous in observations.of_type("mes.containment"):
                    for kind, ids in (
                        ("unit", previous.payload.unit_ids),
                        ("lot", previous.payload.material_lot_ids),
                    ):
                        for ident in ids:
                            latest[kind, ident] = previous
                for kind, ids in (("unit", p.unit_ids), ("lot", p.material_lot_ids)):
                    for ident in ids:
                        current = latest.get((kind, ident))
                        require(
                            current is not None
                            and current.source_key
                            in ([p.cause] if p.cause else []) + p.additional_causes
                            and current.payload.decision == "frozen",
                            "Release must reference current hold",
                        )
                        observations.acknowledged(current)
            return
        require(p.operation == "mes.inspect", "MES operation prerequisite unavailable")
        receipt = observations.fact(p.receipt)
        require(
            (p.accepted.unit, p.accepted.scale)
            == (receipt.payload.amount.unit, receipt.payload.amount.scale),
            "IQC receipt dimensions mismatch",
        )
        used = sum(
            f.payload.accepted.quantity + f.payload.rejected.quantity
            for f in observations.of_type("mes.iqc")
            if f.payload.receipt == p.receipt
        )
        require(
            used + p.accepted.quantity + p.rejected.quantity
            <= receipt.payload.amount.quantity,
            "Inspection exceeds uninspected receipt quantity",
        )

    def validate_operation(self, tx, context, operation, requests):
        p = operation.payload
        if p.operation in {"mes.switch_revision", "mes.cancel_remaining"}:
            from ..eco import accepted_membership, revision_ready, open_row
            from ..orders import own

            require(
                len(requests) == 1 and requests[0].typed_payload.kind == "eco_switch",
                "Prepared ECO wire required",
            )
            payload = requests[0].typed_payload
            open_row(tx, context.project_id, p.eco_id)
            wo = own(tx, "work_orders", context.project_id, p.work_order_id)
            require(
                payload.work_order_id == p.work_order_id
                and payload.eco_id == p.eco_id
                and set(payload.retained_unit_ids)
                == {
                    UUID(i)
                    for i in accepted_membership(
                        tx, context.project_id, p.work_order_id
                    )
                },
                "Current ECO membership differs from prepared scope",
            )
            if p.operation == "mes.switch_revision":
                require(
                    wo["revision_id"] == str(p.from_revision_id)
                    and payload.new_revision_id == p.to_revision_id,
                    "ECO revision mismatch",
                )
                revision_ready(tx, context.project_id, p.to_revision_id)
        if p.operation == "mes.resume":
            from ..execution import outbound_execution_ready

            require(
                len(requests) == 1
                and requests[0].typed_payload.kind == "resume"
                and requests[0].typed_payload.work_order_id == p.work_order_id,
                "Resume prepared scope mismatch",
            )
            require(
                outbound_execution_ready(
                    tx, context.project_id, requests[0].typed_payload, context.now
                ),
                "Current resume readiness blocked",
            )
        if p.operation == "mes.interrupt":
            require(
                len(requests) == 1
                and requests[0].typed_payload.interruption_id == p.interruption_id
                and requests[0].typed_payload.start_id == p.start_id
                and requests[0].typed_payload.work_order_id == p.work_order_id,
                "Interruption prepared scope mismatch",
            )
        if p.operation == "mes.start":
            from ..execution import outbound_execution_ready
            from ..orders import own

            require(
                len(requests) == 1 and requests[0].typed_payload.kind == "start",
                "Source start requires prepared domain scope",
            )
            require(
                outbound_execution_ready(
                    tx, context.project_id, requests[0].typed_payload, context.now
                ),
                "Current production readiness blocked",
            )
            for identity in p.units:
                unit = own(tx, "units", context.project_id, identity.unit_id)
                require(
                    (unit["sn"], unit["work_order_id"], unit["revision_id"])
                    == (identity.sn, str(p.work_order_id), str(p.revision_id)),
                    "Unit/SN/revision mismatch",
                )
        if p.operation == "mes.contain":
            from ..orders import own

            require(
                len(requests) == 1 and requests[0].typed_payload.kind == "freeze",
                "Exact prepared freeze authority required",
            )
            prepared = requests[0].typed_payload
            require(
                set(prepared.unit_ids) == set(p.unit_ids)
                and set(prepared.lot_ids) == set(p.material_lot_ids)
                and prepared.state == p.decision,
                "Containment differs from prepared scope",
            )
            original = tx.execute(
                "SELECT reason FROM freeze_requests WHERE project_id=? AND id=?",
                (str(context.project_id), str(prepared.freeze_id)),
            ).fetchone()
            require(
                original is not None and original[0] == p.evidence,
                "Containment reason differs from original request",
            )
            if p.work_order_id:
                own(tx, "work_orders", context.project_id, p.work_order_id)
            for uid in p.unit_ids:
                unit = own(tx, "units", context.project_id, uid)
                require(
                    p.work_order_id is None
                    or unit["work_order_id"] == str(p.work_order_id),
                    "Containment unit outside work order",
                )
            for lid in p.material_lot_ids:
                lot = own(tx, "material_lots", context.project_id, lid)
                require(
                    p.work_order_id is None
                    or tx.execute(
                        "SELECT 1 FROM requirements WHERE project_id=? AND work_order_id=? AND material_id=? AND owner_id=?",
                        (
                            str(context.project_id),
                            str(p.work_order_id),
                            lot["material_id"],
                            lot["owner_id"],
                        ),
                    ).fetchone()
                    is not None,
                    "Containment lot outside work order",
                )

    def eligibility(self, operation, observations):
        from .core_eligibility import validate_eligibility

        return validate_eligibility(operation, observations, self.store.clock())

    def consume_fact(self, tx, delivery, observations):
        from .core_mes_contexts import emit_delivery_context

        emit_delivery_context(self, tx, delivery, observations)
        if delivery.fact.payload.fact_type in {
            "crm.return_claim",
            "overseas.return_claim",
        }:
            p = delivery.fact.payload
            self.emit(
                tx,
                self.child(
                    delivery,
                    dict(
                        fact_type="mes.containment",
                        work_order_id=None,
                        unit_ids=[u.unit_id for u in p.units],
                        material_lot_ids=[],
                        decision="frozen",
                        cause=delivery.fact.source_key,
                        evidence="External returned-product containment: " + p.reason,
                    ),
                ),
            )
