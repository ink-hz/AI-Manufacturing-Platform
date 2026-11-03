"""Conservation tests against the real three-source boundary and workflow bridge."""

from uuid import UUID

from manufacturing_platform.workflow.integrations.core_models import SourceKey

import pytest

from manufacturing_platform.workflow.contracts import DomainError

from .support import MockRig, NOW


@pytest.fixture
def rig(tmp_path):
    return MockRig(tmp_path, core=True)


def test_iqc_and_sap_posting_are_distinct_exactly_once(rig):
    refs = rig.core_ready(quantity=12, received=10, accepted=8)
    assert rig.physical_balance(refs.lot).qualified == 8
    with pytest.raises(DomainError):
        rig.execute(
            "wms",
            dict(
                kind="wms.reserve",
                requirement_id=str(refs.requirement),
                lot_id=str(refs.lot),
                quantity="12",
                unit="piece",
            ),
        )
    move = rig.pick_qualified(refs, quantity=8)
    rig.drain()
    rig.replay_delivery(move.source_key, "sap")
    assert rig.sap_post_count(move.source_key) == 1
    assert rig.physical_balance(refs.lot).picked == 8


def test_pending_receipt_accounting_has_no_fabricated_qualification():
    from manufacturing_platform.workflow.integrations.contracts import FACT_ADAPTER
    from uuid import uuid4

    value = dict(
        fact_type="sap.receipt_posting",
        cause=dict(system="wms", object_type="receipt", external_id="R1", version=1),
        material_lot_id=str(uuid4()),
        material_id="M",
        owner_id="C",
        amount=dict(quantity="10", unit="piece", scale=0),
        account="raw-received",
    )
    assert FACT_ADAPTER.validate_python(value).cause.object_type == "receipt"


def test_source_reservation_projects_existing_confirmed_reservation(rig):
    refs = rig.core_ready()
    move = rig.pick_qualified(refs, quantity=8)
    reservation_key = move.payload.allocations[0].reservation
    rid = rig.target(
        rig.registry.observe_fact(rig.project_id, reservation_key), "reservation"
    )
    with rig.workflow.store.transaction() as tx:
        row = tx.execute(
            "SELECT confirmed_atoms FROM reservations WHERE project_id=? AND id=?",
            (str(rig.project_id), str(rid)),
        ).fetchone()
    assert row[0] == 8


def test_containment_requires_current_hold_and_downstream_acknowledgments(rig):
    refs = rig.core_ready()
    iqc = rig.registry.adapter("mes").facts(rig.project_id, "iqc", 0, 200).records[0]

    def contain(decision, cause):
        return rig.result_fact(
            rig.execute(
                "mes",
                dict(
                    operation="mes.contain",
                    work_order_id=str(refs.work_order),
                    unit_ids=[],
                    material_lot_ids=[str(refs.lot)],
                    decision=decision,
                    cause=cause.model_dump(),
                    evidence="Quality containment",
                ),
            )
        )

    hold = contain("frozen", iqc.source_key)
    with pytest.raises(DomainError, match="acknowledgment"):
        contain("unfrozen", hold.source_key)
    rig.drain()
    newer = contain("frozen", iqc.source_key)
    rig.drain()
    with pytest.raises(DomainError, match="current hold"):
        contain("unfrozen", hold.source_key)
    released = contain("unfrozen", newer.source_key)
    # Source pending release must still prevent physical reservation.
    from manufacturing_platform.workflow.integrations.contracts import SystemOperation
    from uuid import uuid4

    op = SystemOperation(
        operation_id=uuid4(),
        system="wms",
        project_id=rig.project_id,
        payload=dict(
            operation="wms.reserve",
            work_order_id=refs.work_order,
            requirement_id=refs.requirement,
            allocations=[
                dict(
                    material_lot_id=refs.lot,
                    material_id="M",
                    owner_id="C",
                    amount=dict(quantity="8", unit="piece", scale=0),
                    qualification=refs.qualification,
                )
            ],
        ),
    )
    result = rig.registry.adapter("wms").execute(op)
    assert result.phase == "rejected"
    assert "acknowledgment" in result.error.message
    rig.drain()
    assert rig.pick_qualified(refs, quantity=8)
    assert released.payload.decision == "unfrozen"


def test_preparation_is_separate_from_start_and_delivery_context_is_postshipment():
    from manufacturing_platform.workflow.integrations.contracts import OPERATION_ADAPTER
    from manufacturing_platform.workflow.integrations.catalog import OPERATIONS
    from uuid import uuid4

    prepare = OPERATION_ADAPTER.validate_python(
        dict(
            operation="mes.prepare",
            work_order_id=str(uuid4()),
            unit_ids=[str(uuid4())],
            test_plan_id=str(uuid4()),
            equipment_id="EQ1",
        )
    )
    assert prepare.operation == "mes.prepare"
    assert OPERATIONS["mes.start"].output_fact_types == ("mes.start",)
    assert OPERATIONS["mes.release"].output_fact_types == ("mes.release",)


def test_prepare_precedes_equipment_and_start_uses_real_eligibility(rig):
    refs = rig.start_ready()
    with rig.workflow.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT state FROM units WHERE id=?", (refs.units[0]["unit_id"],)
            ).fetchone()[0]
            == "registered"
        )
    start = rig.result_fact(rig.execute("mes", refs.start_payload))
    assert start.payload.fact_type == "mes.start"
    with rig.workflow.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT state FROM units WHERE id=?", (refs.units[0]["unit_id"],)
            ).fetchone()[0]
            == "running"
        )


def test_mes_execution_has_genuine_admission_and_consumes_line_stock_once(rig):
    refs = rig.start_ready()
    rig.execute("mes", refs.start_payload)
    reservation = (
        rig.registry.adapter("wms")
        .facts(rig.project_id, "reservation", 0, 200)
        .records[0]
    )
    allocation = reservation.payload.allocations[0].model_dump(mode="json")
    allocation.update(
        amount=dict(quantity="1", unit="piece", scale=0),
        reservation=reservation.source_key.model_dump(),
    )
    payload = dict(
        operation="mes.pass",
        work_order_id=str(refs.work_order),
        unit=refs.units[0],
        revision_id=str(refs.revision),
        operator=refs.start_payload["operator"],
        shift=refs.start_payload["shift"],
        equipment=refs.start_payload["equipment"],
        station="assembly",
        route_version="S1",
        program_version="P1",
        firmware_version="F1",
        occurred_at=NOW.isoformat(),
        material_uses=[allocation],
        result="pass",
    )
    fact = rig.result_fact(rig.execute("mes", payload))
    rig.drain()
    rig.replay_delivery(fact.source_key, "wms")
    with rig.workflow.store.transaction() as tx:
        from manufacturing_platform.workflow.execution import admitted_execution_source

        row = tx.execute(
            "SELECT * FROM execution_events WHERE project_id=?", (str(rig.project_id),)
        ).fetchone()
        assert row["status"] == "accepted"
        assert admitted_execution_source(tx, rig.project_id, row).system == "mes"
        assert (
            tx.execute(
                "SELECT SUM(q_atoms) FROM material_consumption WHERE project_id=?",
                (str(rig.project_id),),
            ).fetchone()[0]
            == 1
        )
    assert rig.physical_balance(refs.lot).consumed == 1


def test_mes_stop_resume_uses_its_control_stream_and_requires_new_plan(rig):
    from uuid import uuid4

    refs = rig.start_ready()
    rig.result_fact(rig.execute("mes", refs.start_payload))
    iid = uuid4()
    stop = rig.result_fact(
        rig.execute(
            "mes",
            dict(
                operation="mes.interrupt",
                work_order_id=str(refs.work_order),
                interruption_id=str(iid),
                reason="Process interruption",
                kind="other",
            ),
        )
    )
    assert stop.payload.interruption_id == iid
    with rig.workflow.store.transaction() as tx:
        assert tx.execute(
            "SELECT authority_stopped_at FROM interruptions WHERE id=?", (str(iid),)
        ).fetchone()[0]
    plan = rig.registry.adapter("sap").facts(rig.project_id, "plan", 0, 200).records[-1]
    old_plan_id = rig.target(plan, "plan")
    with pytest.raises(DomainError, match="new accepted plan"):
        rig.execute(
            "mes",
            dict(
                operation="mes.resume",
                work_order_id=str(refs.work_order),
                interruption_id=str(iid),
                plan_id=str(old_plan_id),
                scope="all",
                evidence="Recovery",
            ),
        )
    payload = plan.payload.model_dump(mode="json")
    payload.pop("fact_type")
    payload["requirements"][0]["requirement_id"] = str(uuid4())
    replanned = rig.result_fact(
        rig.execute("sap", dict(operation="sap.publish_plan", **payload))
    )
    rig.drain()
    old_equipment = rig.registry.observe_fact(
        rig.project_id,
        SourceKey.model_validate(refs.start_payload["equipment"]),
    )
    refresh = old_equipment.payload.model_dump(mode="json", exclude={"fact_type"})
    current_equipment = rig.result_fact(
        rig.execute("plc", dict(operation="plc.set_state", **refresh))
    )
    resumed = rig.result_fact(
        rig.execute(
            "mes",
            dict(
                operation="mes.resume",
                work_order_id=str(refs.work_order),
                interruption_id=str(iid),
                plan_id=str(rig.target(replanned, "plan")),
                scope="all",
                evidence="Recovery",
            ),
        )
    )
    assert current_equipment.source_key in resumed.caused_by
    with rig.workflow.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT state FROM units WHERE id=?", (refs.units[0]["unit_id"],)
            ).fetchone()[0]
            == "running"
        )


def test_public_reservation_uses_core_authority_facade_and_stable_query(rig):
    refs = rig.core_ready()
    reservation = rig.command(
        "reservation.request",
        work_order_id=str(refs.work_order),
        requirement_id=str(refs.requirement),
        lot_id=str(refs.lot),
        quantity="8",
        unit="piece",
    )
    rig.command("exchange.dispatch", exchange_id=str(reservation.exchange_id))
    with rig.workflow.store.transaction() as tx:
        row = tx.execute(
            "SELECT * FROM exchanges WHERE id=?", (str(reservation.exchange_id),)
        ).fetchone()
        assert row["system"] == "wms"
        assert row["phase"] == "accepted"
        original = row["receipt_json"]
        business_key = row["business_key"]
    adapter = rig.registry.exchange_adapter("wms")
    assert adapter.query("wms", business_key).model_dump_json() == original
    assert rig.physical_balance(refs.lot).reserved == 8


def test_genuine_product_test_prerequisite_preserves_qualified_lab_run(rig):
    refs = rig.measured_ready()
    test_id = rig.target(refs.test, "test")
    from manufacturing_platform.workflow.quality import (
        admitted_quality_source,
        final_good,
    )

    with rig.workflow.store.transaction() as tx:
        row = tx.execute(
            "SELECT * FROM quality_tests WHERE id=?", (str(test_id),)
        ).fetchone()
        assert (
            admitted_quality_source(tx, rig.project_id, row, "test").system
            == "product_test"
        )
        assert final_good(tx, rig.project_id, refs.units[0]["unit_id"])
        assert tx.execute(
            "SELECT finish_json FROM test_runs WHERE id=?",
            (str(refs.test.payload.run_id),),
        ).fetchone()[0]


def test_shipment_unknown_after_commit_query_does_not_repeat_physical_or_sap_post(rig):
    from uuid import uuid4

    refs = rig.measured_ready()
    releases = []
    for kind in ("manufacturing", "quality"):
        releases.append(
            rig.result_fact(
                rig.execute(
                    "mes",
                    dict(
                        operation="mes.release",
                        work_order_id=str(refs.work_order),
                        units=refs.units,
                        kind=kind,
                        decision="approved",
                        test_sources=[refs.test.source_key.model_dump()],
                        evidence="Qualified release",
                    ),
                )
            )
        )
    assert (
        rig.registry.adapter("mes")
        .facts(rig.project_id, "delivery_context", 0, 200)
        .records
        == []
    )
    opid, sid = uuid4(), uuid4()
    rig.fault("wms", opid, "timeout_after_commit")
    result = rig.execute(
        "wms",
        dict(
            operation="wms.ship",
            shipment_id=str(sid),
            order_line_id=str(refs.order_line),
            units=refs.units,
            releases=[f.source_key.model_dump() for f in releases],
            amount=dict(quantity="1", unit="piece", scale=0),
            destination="Customer C",
            evidence="Packed and handed over",
        ),
        operation_id=opid,
    )
    assert result.integration.phase == "unknown"
    original = rig.registry.adapter("wms").query(rig.project_id, opid).model_dump_json()
    recovered = rig.query(opid)
    assert recovered.integration.phase == "applied"
    rig.drain()
    key = rig.registry.adapter("wms").query(rig.project_id, opid).source_keys[0]
    rig.replay_delivery(key, "sap")
    assert (
        rig.registry.adapter("wms").query(rig.project_id, opid).model_dump_json()
        == original
    )
    assert rig.sap_post_count(key) == 1
    context = (
        rig.registry.adapter("mes")
        .facts(rig.project_id, "delivery_context", 0, 200)
        .records
    )
    assert len(context) == 1 and context[0].payload.shipment == key
    with rig.workflow.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT COUNT(*) FROM shipment_items WHERE project_id=?",
                (str(rig.project_id),),
            ).fetchone()[0]
            == 1
        )


def test_completion_only_reconciles_consumption_and_return_changes_custody(rig):
    refs = rig.start_ready()
    rig.execute("mes", refs.start_payload)
    execution = rig.pass_unit(refs)
    completion = rig.result_fact(
        rig.execute(
            "mes",
            dict(
                operation="mes.complete",
                work_order_id=str(refs.work_order),
                revision_id=str(refs.revision),
                units=refs.units,
                execution_sources=[execution.source_key.model_dump()],
                consumption=[
                    a.model_dump(mode="json") for a in execution.payload.material_uses
                ],
                occurred_at=NOW.isoformat(),
            ),
        )
    )
    returns = (
        rig.registry.adapter("mes")
        .facts(rig.project_id, "return_requirement", 0, 200)
        .records
    )
    assert len(returns) == 1
    assert sum(a.amount.quantity for a in returns[0].payload.allocations) == 11
    payload = returns[0].payload.model_dump(mode="json")
    payload.pop("fact_type")
    payload["cause"] = returns[0].source_key.model_dump()
    rig.execute(
        "wms", dict(operation="wms.return", direction="to_warehouse", **payload)
    )
    rig.drain()
    rig.replay_delivery(completion.source_key, "sap")
    assert rig.physical_balance(refs.lot).consumed == 1
    assert rig.physical_balance(refs.lot).line_side == 0
    with rig.workflow.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT SUM(q_atoms) FROM material_consumption WHERE project_id=?",
                (str(rig.project_id),),
            ).fetchone()[0]
            == 1
        )


def test_public_core_eco_cancellation_preserves_retained_unit_and_receipt(rig):
    refs = rig.start_ready()
    rig.execute("mes", refs.start_payload)
    eco = rig.command(
        "eco.open",
        old_revision_id=str(refs.revision),
        effective_work_order_ids=[str(refs.work_order)],
        reason="Cancel unstarted remaining order",
    )
    switch = rig.command(
        "eco.switch",
        eco_id=str(eco.object_id),
        target_work_order_id=str(refs.work_order),
        boundary="cancel_remaining",
        evidence="Authorized cancellation",
    )
    rig.command("exchange.dispatch", exchange_id=str(switch.exchange_id))
    with rig.workflow.store.transaction() as tx:
        row = tx.execute(
            "SELECT * FROM exchanges WHERE id=?", (str(switch.exchange_id),)
        ).fetchone()
        assert row["phase"] == "accepted"
        assert (
            tx.execute(
                "SELECT obligation_atoms FROM effective_work_orders WHERE id=?",
                (str(refs.work_order),),
            ).fetchone()[0]
            == 1
        )
        assert (
            tx.execute(
                "SELECT COUNT(*) FROM work_orders WHERE project_id=?",
                (str(rig.project_id),),
            ).fetchone()[0]
            == 1
        )
        assert (
            tx.execute(
                "SELECT state FROM units WHERE id=?", (refs.units[0]["unit_id"],)
            ).fetchone()[0]
            == "running"
        )
        original = row["receipt_json"]
        key = row["business_key"]
    assert (
        rig.registry.exchange_adapter("mes").query("mes", key).model_dump_json()
        == original
    )


def test_empty_retained_split_has_actual_replacement_source_identity(rig):
    refs = rig.core_ready()
    change = rig.change_ready(refs)
    fact = rig.result_fact(
        rig.execute(
            "mes",
            dict(
                operation="mes.switch_revision",
                work_order_id=str(refs.work_order),
                eco_id=str(change.eco),
                from_revision_id=str(refs.revision),
                to_revision_id=str(change.revision),
                units=[],
                change=change.change.model_dump(),
                approval=change.approval.model_dump(),
                evidence="Explicit empty retained split",
            ),
        )
    )
    replacement = fact.payload.replacement_work_order_id
    with rig.workflow.store.transaction() as tx:
        import json

        row = tx.execute(
            "SELECT * FROM work_orders WHERE id=?", (str(replacement),)
        ).fetchone()
        assert row["q_atoms"] == 12
        assert json.loads(row["source_json"]) == fact.source.model_dump(mode="json")
        assert (
            tx.execute(
                "SELECT SUM(obligation_atoms) FROM effective_work_orders WHERE project_id=?",
                (str(rig.project_id),),
            ).fetchone()[0]
            == 12
        )
        assert (
            tx.execute(
                "SELECT SUM(q_atoms) FROM effective_allocations WHERE project_id=?",
                (str(rig.project_id),),
            ).fetchone()[0]
            == 12
        )


def test_replenishment_conserves_fourteen_received_twelve_qualified(rig):
    from datetime import timedelta

    refs = rig.core_ready()
    receipt = rig.result_fact(
        rig.execute(
            "wms",
            dict(
                operation="wms.receive",
                commitment_id=str(refs.commitment),
                material_lot_id=str(refs.lot),
                lot_id="LOT",
                material_id="M",
                owner_id="C",
                amount=dict(quantity="4", unit="piece", scale=0),
                location="receiving",
                custodian="warehouse",
                supplier_batch="B2",
                expiry=(NOW + timedelta(days=30)).date().isoformat(),
            ),
        )
    )
    inspected = rig.result_fact(
        rig.execute(
            "mes",
            dict(
                operation="mes.inspect",
                receipt=receipt.source_key.model_dump(),
                accepted=dict(quantity="4", unit="piece", scale=0),
                rejected=dict(quantity="0", unit="piece", scale=0),
                evidence="Replenishment IQC",
            ),
        )
    )
    # WMS and MES sequences belong to different source streams.
    wms_receipt = rig.registry.adapter("wms").query(
        rig.project_id, UUID(receipt.source.external_id)
    )
    mes_receipt = rig.registry.adapter("mes").query(
        rig.project_id, UUID(inspected.source.external_id)
    )
    assert wms_receipt.sequence > mes_receipt.sequence
    rig.drain()
    reservation = rig.command(
        "reservation.request",
        work_order_id=str(refs.work_order),
        requirement_id=str(refs.requirement),
        lot_id=str(refs.lot),
        quantity="12",
        unit="piece",
    )
    rig.command("exchange.dispatch", exchange_id=str(reservation.exchange_id))
    balance = rig.physical_balance(refs.lot)
    assert (
        balance.received,
        balance.qualified,
        balance.rejected,
        balance.reserved,
    ) == (14, 12, 2, 12)
    with rig.workflow.store.transaction() as tx:
        row = tx.execute(
            "SELECT confirmed_atoms FROM reservations WHERE id=?",
            (str(reservation.object_id),),
        ).fetchone()
        assert row[0] == 12


def test_component_is_bound_to_consumed_execution_and_original_source(rig):
    refs = rig.start_ready()
    rig.execute("mes", refs.start_payload)
    execution = rig.pass_unit(refs)
    payload = dict(
        operation="mes.assemble",
        work_order_id=str(refs.work_order),
        unit_id=refs.units[0]["unit_id"],
        material_id="M",
        material_lot_id=str(refs.lot),
        component_serial="PART-1",
        execution=execution.source_key.model_dump(),
        evidence="Scanned installed component",
    )
    fact = rig.result_fact(rig.execute("mes", payload))
    link = rig.target(fact, "component_link")
    with rig.workflow.store.transaction() as tx:
        import json

        recorded = json.loads(
            tx.execute(
                "SELECT payload_json FROM component_links WHERE id=?", (str(link),)
            ).fetchone()[0]
        )
        assert recorded["source"] == fact.source.model_dump(mode="json")
        assert recorded["origin"] == "demo"
    with pytest.raises(DomainError, match="active installation"):
        rig.execute("mes", payload)


def test_location_transfer_cannot_pick_from_another_location(rig):
    refs = rig.core_ready()
    move = rig.pick_qualified(refs, quantity=8)
    assert rig.registry.adapter("wms").facts(rig.project_id, "custody", 0, 200).records
    # The original warehouse location has been emptied by the real pick.
    payload = move.payload.model_dump(mode="json", exclude={"fact_type"})
    payload["allocations"][0]["amount"]["quantity"] = "1"
    payload["source_custody"]["location"] = "other-bin"
    with pytest.raises(DomainError, match="location"):
        rig.execute("wms", dict(operation="wms.pick", **payload))


def test_stocktake_variance_is_separate_from_receipt_and_qualification(rig):
    refs = rig.core_ready()
    payload = dict(
        operation="wms.stocktake",
        material_lot_id=str(refs.lot),
        owner_id="C",
        location="receiving",
        quality_state="qualified",
        expected=dict(quantity="8", unit="piece", scale=0),
        counted=dict(quantity="7", unit="piece", scale=0),
        cause=refs.qualification.model_dump(),
        evidence="Counted one missing qualified piece",
    )
    fact = rig.result_fact(rig.execute("wms", payload))
    balance = rig.physical_balance(refs.lot)
    assert (balance.received, balance.qualified, balance.qualified_adjustment) == (
        10,
        8,
        -1,
    )
    with rig.workflow.store.transaction() as tx:
        from manufacturing_platform.workflow.ownership import balance as ownership

        lot = tx.execute(
            "SELECT * FROM material_lots WHERE id=?", (str(refs.lot),)
        ).fetchone()
        view = ownership(tx, rig.project_id, lot)
        assert (view.received, view.adjustment, view.balance) == (10, -1, 9)
    with pytest.raises(DomainError, match="qualified"):
        rig.execute(
            "wms",
            dict(
                payload,
                expected=dict(quantity="7", unit="piece", scale=0),
                counted=dict(quantity="8", unit="piece", scale=0),
            ),
        )
    with pytest.raises(DomainError):
        rig.execute(
            "wms",
            dict(
                kind="wms.reserve",
                requirement_id=str(refs.requirement),
                lot_id=str(refs.lot),
                quantity="8",
                unit="piece",
            ),
        )
    rig.drain()
    rig.replay_delivery(fact.source_key, "sap")
    assert rig.sap_post_count(fact.source_key) == 1
    posting = (
        rig.registry.adapter("sap")
        .facts(rig.project_id, "variance_posting", 0, 200)
        .records[-1]
    )
    assert rig.pull(posting.source_key).integration.phase == "applied"


def test_sap_emits_actual_released_bom_and_plan_purchase_context(rig):
    refs = rig.core_ready()
    requests = (
        rig.registry.adapter("sap").facts(rig.project_id, "bom_request", 0, 200).records
    )
    assert len(requests) == 1
    assert requests[0].payload.work_order_id == refs.work_order
    assert requests[0].payload.material_ids == ["M"]
    purchases = (
        rig.registry.adapter("sap")
        .facts(rig.project_id, "purchase_requirement", 0, 200)
        .records
    )
    assert (
        len(purchases) == 1 and purchases[0].payload.requirement_id == refs.requirement
    )
    assert purchases[0].payload.amount.quantity == 12


def test_public_shipment_facade_consumes_actual_release_and_exact_wire(rig):
    refs = rig.measured_ready()
    for kind in ("manufacturing", "quality"):
        rig.execute(
            "mes",
            dict(
                operation="mes.release",
                work_order_id=str(refs.work_order),
                units=refs.units,
                kind=kind,
                decision="approved",
                test_sources=[refs.test.source_key.model_dump()],
                evidence="Qualified release",
            ),
        )
    shipment = rig.command(
        "shipment.request",
        order_line_id=str(refs.order_line),
        unit_ids=[refs.units[0]["unit_id"]],
        quantity="1",
        unit="piece",
    )
    rig.command("exchange.dispatch", exchange_id=str(shipment.exchange_id))
    with rig.workflow.store.transaction() as tx:
        row = tx.execute(
            "SELECT * FROM exchanges WHERE id=?", (str(shipment.exchange_id),)
        ).fetchone()
        assert row["phase"] == "accepted"
        original, key = row["receipt_json"], row["business_key"]
    assert (
        rig.registry.exchange_adapter("wms").query("wms", key).model_dump_json()
        == original
    )
    assert (
        len(
            rig.registry.adapter("wms")
            .facts(rig.project_id, "shipment", 0, 200)
            .records
        )
        == 1
    )


def test_public_freeze_facade_supports_proactive_hold_and_acknowledged_release(rig):
    refs = rig.core_ready()
    for decision in ("frozen", "unfrozen"):
        freeze = rig.command(
            "freeze.request",
            unit_ids=[],
            lot_ids=[str(refs.lot)],
            state=decision,
            reason="Authorized proactive quality hold",
        )
        rig.command("exchange.dispatch", exchange_id=str(freeze.exchange_id))
        with rig.workflow.store.transaction() as tx:
            assert (
                tx.execute(
                    "SELECT phase FROM exchanges WHERE id=?", (str(freeze.exchange_id),)
                ).fetchone()[0]
                == "accepted"
            )
        rig.drain()


def test_source_rejects_revoked_employee_without_partial_start(rig):
    refs = rig.start_ready()
    rig.execute(
        "hr_sap",
        dict(
            operation="hr_sap.publish_employee",
            employee_id="E1",
            display_name="External operator",
            organization="Factory",
            position="Assembly",
            active=False,
        ),
    )
    with pytest.raises(DomainError, match="active/current"):
        rig.execute("mes", refs.start_payload)
    assert (
        not rig.registry.adapter("mes").facts(rig.project_id, "start", 0, 200).records
    )
    with rig.workflow.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT accepted_start_id FROM units WHERE id=?",
                (refs.units[0]["unit_id"],),
            ).fetchone()[0]
            is None
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_id", "OTHER"),
        ("material_id", "OTHER"),
        ("amount", dict(quantity="1", unit="kg", scale=0)),
    ],
)
def test_source_rejects_mismatched_allocation_without_effect(rig, field, value):
    from uuid import uuid4
    from manufacturing_platform.workflow.integrations.contracts import SystemOperation

    refs = rig.core_ready()
    allocation = dict(
        material_lot_id=refs.lot,
        material_id="M",
        owner_id="C",
        amount=dict(quantity="1", unit="piece", scale=0),
        qualification=refs.qualification,
    )
    allocation[field] = value
    operation = SystemOperation(
        operation_id=uuid4(),
        system="wms",
        project_id=rig.project_id,
        payload=dict(
            operation="wms.reserve",
            work_order_id=refs.work_order,
            requirement_id=refs.requirement,
            allocations=[allocation],
        ),
    )
    receipt = rig.registry.adapter("wms").execute(operation)
    assert receipt.phase == "rejected"
    assert (
        rig.registry.adapter("wms").query(rig.project_id, operation.operation_id)
        == receipt
    )
    assert rig.physical_balance(refs.lot).reserved == 0


def _competing_reservation(config, raw_operation, queue):
    from manufacturing_platform.workflow.integrations.contracts import SystemOperation
    from manufacturing_platform.workflow.service import WorkflowService
    from manufacturing_platform.workflow.store import WorkflowStore

    store = WorkflowStore(*config, business_clock=lambda: NOW)
    registry = WorkflowService(store, lambda _: True).system_registry
    operation = SystemOperation.model_validate_json(raw_operation)
    queue.put(registry.adapter("wms").execute(operation).phase)


def test_two_processes_cannot_reserve_the_same_qualified_stock(rig):
    import multiprocessing
    from uuid import uuid4
    from manufacturing_platform.workflow.integrations.contracts import SystemOperation

    refs = rig.core_ready()
    operation = SystemOperation(
        operation_id=uuid4(),
        system="wms",
        project_id=rig.project_id,
        payload=dict(
            operation="wms.reserve",
            work_order_id=refs.work_order,
            requirement_id=refs.requirement,
            allocations=[
                dict(
                    material_lot_id=refs.lot,
                    material_id="M",
                    owner_id="C",
                    amount=dict(quantity="5", unit="piece", scale=0),
                    qualification=refs.qualification,
                )
            ],
        ),
    )
    config = (
        str(rig.workflow.store.database_path),
        str(rig.workflow.store.authority_database_path),
        rig.workflow.store.dataset,
    )
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    workers = [
        ctx.Process(
            target=_competing_reservation,
            args=(
                config,
                operation.model_copy(
                    update={"operation_id": uuid4()}
                ).model_dump_json(),
                queue,
            ),
        )
        for _ in range(2)
    ]
    for process in workers:
        process.start()
    for process in workers:
        process.join(timeout=15)
        assert process.exitcode == 0
    assert sorted(queue.get(timeout=2) for _ in workers) == ["accepted", "rejected"]
    assert rig.physical_balance(refs.lot).reserved == 5


def test_public_source_effect_can_be_pulled_with_original_wire_binding(rig):
    refs = rig.core_ready()
    reservation = rig.command(
        "reservation.request",
        work_order_id=str(refs.work_order),
        requirement_id=str(refs.requirement),
        lot_id=str(refs.lot),
        quantity="8",
        unit="piece",
    )
    rig.command("exchange.dispatch", exchange_id=str(reservation.exchange_id))
    fact = (
        rig.registry.adapter("wms")
        .facts(rig.project_id, "reservation", 0, 200)
        .records[0]
    )
    assert rig.pull(fact.source_key).integration.phase == "applied"
    assert rig.target(fact, "reservation") == reservation.object_id
    assert rig.physical_balance(refs.lot).reserved == 8


def test_accounting_receipt_and_posted_state_are_truthful_and_stable(rig):
    refs = rig.core_ready()
    before = rig.accounting_balance(refs.lot)
    assert before.received == 10 and before.consumed == 0
    move = rig.pick_qualified(refs, quantity=8)
    rig.drain()
    entries = (
        rig.registry.adapter("sap")
        .facts(rig.project_id, "accounting_entry", 0, 200)
        .records
    )
    entry = next(f for f in entries if f.payload.cause == move.source_key)
    assert entry.payload.posted_at == NOW
    receipt = rig.original_receipt_bytes("wms", move.source.external_id)
    rig.replay_delivery(move.source_key, "sap")
    assert rig.original_receipt_bytes("wms", move.source.external_id) == receipt
    assert rig.accounting_balance(refs.lot).picked == 8


def test_multiple_iqc_decisions_for_one_receipt_share_one_original_basis(rig):
    from datetime import timedelta

    refs = rig.core_ready()
    receipt = rig.result_fact(
        rig.execute(
            "wms",
            dict(
                operation="wms.receive",
                commitment_id=str(refs.commitment),
                material_lot_id=str(refs.lot),
                lot_id="LOT",
                material_id="M",
                owner_id="C",
                amount=dict(quantity="4", unit="piece", scale=0),
                location="receiving",
                custodian="warehouse",
                supplier_batch="B2",
                expiry=(NOW + timedelta(days=30)).date().isoformat(),
            ),
        )
    )
    for _ in range(2):
        rig.execute(
            "mes",
            dict(
                operation="mes.inspect",
                receipt=receipt.source_key.model_dump(),
                accepted=dict(quantity="2", unit="piece", scale=0),
                rejected=dict(quantity="0", unit="piece", scale=0),
                evidence="Partial receipt inspection",
            ),
        )
    rig.drain()
    reservation = rig.command(
        "reservation.request",
        work_order_id=str(refs.work_order),
        requirement_id=str(refs.requirement),
        lot_id=str(refs.lot),
        quantity="12",
        unit="piece",
    )
    rig.command("exchange.dispatch", exchange_id=str(reservation.exchange_id))
    with rig.workflow.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT confirmed_atoms FROM reservations WHERE id=?",
                (str(reservation.object_id),),
            ).fetchone()[0]
            == 12
        )


def test_completion_returns_one_net_scope_after_return_and_repick(rig):
    refs = rig.start_ready()
    pick = rig.registry.adapter("wms").facts(rig.project_id, "pick", 0, 200).records[0]
    data = pick.payload.model_dump(mode="json", exclude={"fact_type"})
    data["allocations"][0]["amount"]["quantity"] = "6"
    data["source_custody"], data["destination_custody"] = (
        data["destination_custody"],
        data["source_custody"],
    )
    data["cause"] = pick.source_key.model_dump()
    returned = rig.result_fact(
        rig.execute(
            "wms", dict(operation="wms.return", direction="to_warehouse", **data)
        )
    )
    data["source_custody"], data["destination_custody"] = (
        data["destination_custody"],
        data["source_custody"],
    )
    data["cause"] = returned.source_key.model_dump()
    rig.execute("wms", dict(operation="wms.pick", **data))
    rig.execute("mes", refs.start_payload)
    execution = rig.pass_unit(refs)
    rig.execute(
        "mes",
        dict(
            operation="mes.complete",
            work_order_id=str(refs.work_order),
            revision_id=str(refs.revision),
            units=refs.units,
            execution_sources=[execution.source_key.model_dump()],
            consumption=[
                a.model_dump(mode="json") for a in execution.payload.material_uses
            ],
            occurred_at=NOW.isoformat(),
        ),
    )
    returns = (
        rig.registry.adapter("mes")
        .facts(rig.project_id, "return_requirement", 0, 200)
        .records
    )
    assert sum(a.amount.quantity for f in returns for a in f.payload.allocations) == 11


def test_scoped_safety_stop_controls_actual_source_accepted_held_start(
    rig, monkeypatch
):
    from uuid import uuid4

    refs = rig.start_ready()
    adapter = rig.registry.adapter("mes")
    execute = adapter.execute
    opid = uuid4()

    def contain_after_commit(operation):
        receipt = execute(operation)
        if operation.operation_id == opid:
            rig.command(
                "freeze.request",
                unit_ids=[refs.units[0]["unit_id"]],
                lot_ids=[],
                state="frozen",
                reason="Safety condition discovered after source acceptance",
            )
        return receipt

    monkeypatch.setattr(adapter, "execute", contain_after_commit)
    with pytest.raises(DomainError, match="Project changed"):
        rig.execute("mes", refs.start_payload, operation_id=opid)
    monkeypatch.setattr(adapter, "execute", execute)
    rig.query(opid)
    with rig.workflow.store.transaction() as tx:
        unit = tx.execute(
            "SELECT * FROM units WHERE id=?", (refs.units[0]["unit_id"],)
        ).fetchone()
        assert unit["state"] == "start_pending" and unit["accepted_start_id"]
        start_id = unit["accepted_start_id"]
    stop = rig.command(
        "production.interrupt",
        work_order_id=str(refs.work_order),
        start_id=start_id,
        kind="S4",
        reason="Stop actual accepted held scope",
    )
    rig.command("exchange.dispatch", exchange_id=str(stop.exchange_id))
    with rig.workflow.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT phase FROM exchanges WHERE id=?", (str(stop.exchange_id),)
            ).fetchone()[0]
            == "accepted"
        )
    fact = (
        rig.registry.adapter("mes")
        .facts(rig.project_id, "interruption", 0, 200)
        .records[-1]
    )
    assert str(fact.payload.start_id) == start_id
    assert fact.payload.kind == "S4"


def test_failed_downstream_hold_delivery_has_no_ack_and_blocks_release(
    rig, monkeypatch
):
    refs = rig.core_ready()
    hold = rig.result_fact(
        rig.execute(
            "mes",
            dict(
                operation="mes.contain",
                work_order_id=str(refs.work_order),
                unit_ids=[],
                material_lot_ids=[str(refs.lot)],
                decision="frozen",
                evidence="Proactive safety hold",
            ),
        )
    )
    consumer = rig.registry.adapter("wms")
    consume = consumer.consume

    def unavailable(delivery):
        if delivery.fact.source_key == hold.source_key:
            raise TimeoutError("WMS unavailable")
        return consume(delivery)

    monkeypatch.setattr(consumer, "consume", unavailable)
    rig.drain()
    with pytest.raises(DomainError, match="acknowledgment"):
        rig.execute(
            "mes",
            dict(
                operation="mes.contain",
                work_order_id=str(refs.work_order),
                unit_ids=[],
                material_lot_ids=[str(refs.lot)],
                decision="unfrozen",
                cause=hold.source_key.model_dump(),
                evidence="Recovery",
            ),
        )
    monkeypatch.setattr(consumer, "consume", consume)
    rig.drain()
    released = rig.result_fact(
        rig.execute(
            "mes",
            dict(
                operation="mes.contain",
                work_order_id=str(refs.work_order),
                unit_ids=[],
                material_lot_ids=[str(refs.lot)],
                decision="unfrozen",
                cause=hold.source_key.model_dump(),
                evidence="Recovery",
            ),
        )
    )
    assert released.payload.decision == "unfrozen"


def test_pending_positive_stocktake_never_creates_qualified_stock(rig):
    refs = rig.core_ready()
    rig.execute(
        "wms",
        dict(
            operation="wms.stocktake",
            material_lot_id=str(refs.lot),
            owner_id="C",
            location="receiving",
            quality_state="pending",
            expected=dict(quantity="0", unit="piece", scale=0),
            counted=dict(quantity="2", unit="piece", scale=0),
            cause=refs.receipt.model_dump(),
            evidence="Unidentified surplus awaiting reconciliation",
        ),
    )
    balance = rig.physical_balance(refs.lot)
    assert (balance.received, balance.qualified, balance.pending_adjustment) == (
        10,
        8,
        2,
    )
    with pytest.raises(DomainError):
        rig.execute(
            "wms",
            dict(
                kind="wms.reserve",
                requirement_id=str(refs.requirement),
                lot_id=str(refs.lot),
                quantity="10",
                unit="piece",
            ),
        )


def test_facade_business_rejection_is_an_immutable_queryable_source_receipt(rig):
    refs = rig.core_ready()
    reservation = rig.command(
        "reservation.request",
        work_order_id=str(refs.work_order),
        requirement_id=str(refs.requirement),
        lot_id=str(refs.lot),
        quantity="12",
        unit="piece",
    )
    rig.command("exchange.dispatch", exchange_id=str(reservation.exchange_id))
    from manufacturing_platform.workflow.exchange_models import ExternalRequest

    with rig.workflow.store.transaction() as tx:
        row = tx.execute(
            "SELECT * FROM exchanges WHERE id=?", (str(reservation.exchange_id),)
        ).fetchone()
        request = ExternalRequest.model_validate_json(row["request_json"])
    adapter = rig.registry.exchange_adapter("wms")
    receipt = adapter.query("wms", request.business_key)
    assert receipt is not None and receipt.phase == "rejected"
    assert adapter.submit(request).model_dump_json() == receipt.model_dump_json()
    assert rig.physical_balance(refs.lot).reserved == 0


def test_revision_split_rejects_superseded_external_approval(rig):
    refs = rig.core_ready()
    change = rig.change_ready(refs)
    old = rig.registry.observe_fact(rig.project_id, change.approval)
    payload = old.payload.model_dump(mode="json", exclude={"fact_type"})
    rig.execute(
        "oa",
        dict(operation="oa.decide_approval", **(payload | {"decision": "rejected"})),
    )
    with pytest.raises(DomainError, match="current"):
        rig.execute(
            "mes",
            dict(
                operation="mes.switch_revision",
                work_order_id=str(refs.work_order),
                eco_id=str(change.eco),
                from_revision_id=str(refs.revision),
                to_revision_id=str(change.revision),
                units=[],
                change=change.change.model_dump(),
                approval=change.approval.model_dump(),
                evidence="Attempt stale approval",
            ),
        )
    assert (
        not rig.registry.adapter("mes")
        .facts(rig.project_id, "revision_switch", 0, 200)
        .records
    )


def test_component_source_remains_readable_in_existing_unit_history(rig):
    refs = rig.start_ready()
    rig.execute("mes", refs.start_payload)
    execution = rig.pass_unit(refs)
    component = rig.result_fact(
        rig.execute(
            "mes",
            dict(
                operation="mes.assemble",
                work_order_id=str(refs.work_order),
                unit_id=refs.units[0]["unit_id"],
                material_id="M",
                material_lot_id=str(refs.lot),
                component_serial="PART-HISTORY",
                execution=execution.source_key.model_dump(),
                evidence="Component source history",
            ),
        )
    )
    from manufacturing_platform.workflow.execution import unit_detail

    with rig.workflow.store.transaction() as tx:
        view = unit_detail(tx, rig.project_id, refs.units[0]["unit_id"])
        assert (
            view.value.components[0].source.model_dump()
            == component.source.model_dump()
        )


def test_multi_work_order_shipment_emits_only_actual_per_work_order_contexts(rig):
    from uuid import uuid4
    from datetime import timedelta
    from dataclasses import replace

    first = rig.measured_ready(
        rig.core_ready(quantity=12, received=12, accepted=12, work_order_quantity=6)
    )
    releases = []
    for kind in ("manufacturing", "quality"):
        releases.append(
            rig.result_fact(
                rig.execute(
                    "mes",
                    dict(
                        operation="mes.release",
                        work_order_id=str(first.work_order),
                        units=first.units,
                        kind=kind,
                        decision="approved",
                        test_sources=[first.test.source_key.model_dump()],
                        evidence="First WO release",
                    ),
                )
            )
        )
    old_wo = (
        rig.registry.adapter("sap")
        .facts(rig.project_id, "work_order", 0, 200)
        .records[0]
    )
    new_wo = rig.result_fact(
        rig.execute(
            "sap",
            dict(
                operation="sap.release_work_order",
                order_line_id=str(first.order_line),
                revision_id=str(first.revision),
                released_revision=old_wo.payload.released_revision.model_dump(),
                amount=dict(quantity="6", unit="piece", scale=0),
                trial_amount=dict(quantity="1", unit="piece", scale=0),
                purpose="production",
                planned_start=NOW.isoformat(),
                planned_end=(NOW + timedelta(days=1)).isoformat(),
            ),
        )
    )
    wid = rig.target(new_wo, "work_order")
    rig.command(
        "order.allocate",
        order_line_id=str(first.order_line),
        work_order_id=str(wid),
        quantity="6",
        unit="piece",
    )
    req = uuid4()
    rig.execute(
        "sap",
        dict(
            operation="sap.publish_plan",
            input_revision_ids=[str(first.revision)],
            input_order_versions=[dict(order_line_id=str(first.order_line), version=1)],
            requirements=[
                dict(
                    requirement_id=str(req),
                    work_order_id=str(wid),
                    execution_scope="common",
                    material_id="M",
                    owner_id="C",
                    amount=dict(quantity="6", unit="piece", scale=0),
                )
            ],
            cutoff=NOW.isoformat(),
        ),
    )
    second = rig.measured_ready(
        replace(first, work_order=wid, requirement=req, units=[]), sn="SN2"
    )
    for kind in ("manufacturing", "quality"):
        releases.append(
            rig.result_fact(
                rig.execute(
                    "mes",
                    dict(
                        operation="mes.release",
                        work_order_id=str(second.work_order),
                        units=second.units,
                        kind=kind,
                        decision="approved",
                        test_sources=[second.test.source_key.model_dump()],
                        evidence="Second WO release",
                    ),
                )
            )
        )
    shipment = rig.command(
        "shipment.request",
        order_line_id=str(first.order_line),
        unit_ids=[first.units[0]["unit_id"], second.units[0]["unit_id"]],
        quantity="2",
        unit="piece",
    )
    rig.command("exchange.dispatch", exchange_id=str(shipment.exchange_id))
    rig.drain()
    contexts = (
        rig.registry.adapter("mes")
        .facts(rig.project_id, "delivery_context", 0, 200)
        .records
    )
    assert len(contexts) == 2
    assert {f.payload.work_order_id for f in contexts} == {
        first.work_order,
        second.work_order,
    }
    assert len({f.payload.shipment.model_dump_json() for f in contexts}) == 1
    assert all(
        len(f.payload.units) == 1 and len(f.payload.releases) == 2 for f in contexts
    )


def test_replacement_work_order_preparation_keeps_actual_revision_switch_lineage(rig):
    refs = rig.core_ready()
    change = rig.change_ready(refs)
    switch = rig.result_fact(
        rig.execute(
            "mes",
            dict(
                operation="mes.switch_revision",
                work_order_id=str(refs.work_order),
                eco_id=str(change.eco),
                from_revision_id=str(refs.revision),
                to_revision_id=str(change.revision),
                units=[],
                change=change.change.model_dump(),
                approval=change.approval.model_dump(),
                evidence="Actual replacement order",
            ),
        )
    )
    wid = switch.payload.replacement_work_order_id
    unit = rig.command(
        "unit.register", work_order_id=str(wid), sns=["REPLACEMENT-SN"]
    ).object_id
    plan = rig.command(
        "test_plan.publish",
        revision_id=str(change.revision),
        level="final",
        station="assembly",
        equipment="EQ2",
        fixture="FX2",
        algorithm_version="ALG2",
    ).object_id
    prepared = rig.result_fact(
        rig.execute(
            "mes",
            dict(
                operation="mes.prepare",
                work_order_id=str(wid),
                unit_ids=[str(unit)],
                test_plan_id=str(plan),
                equipment_id="EQ2",
            ),
        )
    )
    assert switch.source_key in prepared.caused_by
    assert change.source in prepared.caused_by


def test_preparation_emits_actual_scoped_approval_request(rig):
    refs = rig.start_ready()
    npi = rig.command(
        "npi.open",
        revision_id=str(refs.revision),
        product_family="P",
        scenario="first_introduction",
        required_checks=["design"],
        work_order_ids=[str(refs.work_order)],
    )
    revision = (
        rig.registry.adapter("sap")
        .facts(rig.project_id, "work_order", 0, 200)
        .records[0]
        .payload.released_revision
    )
    target = dict(
        target_type="engineering",
        source_key=revision.model_dump(),
        npi_id=str(npi.object_id),
        revision_id=str(refs.revision),
        checks=[
            dict(
                code="design",
                required=True,
                decision="pass",
                evidence="Design review request",
                reason="Verified",
            )
        ],
    )
    preparation = rig.result_fact(
        rig.execute(
            "mes",
            dict(
                operation="mes.prepare",
                work_order_id=str(refs.work_order),
                unit_ids=[u["unit_id"] for u in refs.units],
                test_plan_id=str(refs.test_plan),
                equipment_id="EQ1",
                approval_target=target,
            ),
        )
    )
    requests = (
        rig.registry.adapter("mes")
        .facts(rig.project_id, "approval_request", 0, 200)
        .records
    )
    assert len(requests) == 1 and preparation.source_key in requests[0].caused_by
    assert requests[0].payload.target.source_key == revision


def test_unrelated_training_cannot_replace_expired_station_qualification(rig):
    from datetime import timedelta

    refs = rig.start_ready()
    base = dict(
        employee=refs.start_payload["operator"],
        training_reference="TRAIN-UPDATE",
        valid_from=(NOW - timedelta(days=2)).isoformat(),
        evidence="External training update",
    )
    rig.execute(
        "hr_beisen",
        dict(
            operation="hr_beisen.publish_qualification",
            qualification="assembly",
            valid_until=(NOW - timedelta(days=1)).isoformat(),
            **base,
        ),
    )
    rig.execute(
        "hr_beisen",
        dict(
            operation="hr_beisen.publish_qualification",
            qualification="unrelated",
            valid_until=(NOW + timedelta(days=1)).isoformat(),
            **base,
        ),
    )
    with pytest.raises(DomainError, match="qualification"):
        rig.execute("mes", refs.start_payload)
    assert (
        not rig.registry.adapter("mes").facts(rig.project_id, "start", 0, 200).records
    )


def test_an_account_name_cannot_post_a_physical_movement_twice(rig):
    refs = rig.core_ready()
    move = rig.pick_qualified(refs, quantity=8)
    rig.drain()
    with pytest.raises(DomainError, match="account"):
        rig.execute(
            "sap",
            dict(
                operation="sap.post_movement",
                cause=move.source_key.model_dump(),
                account="another-credit",
                allocations=[
                    a.model_dump(mode="json") for a in move.payload.allocations
                ],
                evidence="Duplicate physical cause",
            ),
        )
    assert rig.sap_post_count(move.source_key) == 1


def test_source_receipt_and_iqc_confirm_original_manual_observations_once(rig):
    from uuid import uuid4
    from datetime import timedelta

    refs = rig.core_ready()
    opid = uuid4()
    source = rig.manual_source("receipt") | dict(system="wms", external_id=str(opid))
    manual = rig.command(
        "supply.receive",
        commitment_id=str(refs.commitment),
        material_lot_id=str(refs.lot),
        quantity="4",
        unit="piece",
        source=source,
    )
    rig.command(
        "supply.inspect",
        receipt_id=str(manual.object_id),
        accepted="4",
        rejected="0",
        evidence="Documented manual IQC observation",
    )
    receipt = rig.result_fact(
        rig.execute(
            "wms",
            dict(
                operation="wms.receive",
                commitment_id=str(refs.commitment),
                material_lot_id=str(refs.lot),
                lot_id="LOT",
                material_id="M",
                owner_id="C",
                amount=dict(quantity="4", unit="piece", scale=0),
                location="receiving",
                custodian="warehouse",
                supplier_batch="B2",
                expiry=(NOW + timedelta(days=30)).date().isoformat(),
            ),
            operation_id=opid,
        )
    )
    inspection = rig.result_fact(
        rig.execute(
            "mes",
            dict(
                operation="mes.inspect",
                receipt=receipt.source_key.model_dump(),
                accepted=dict(quantity="4", unit="piece", scale=0),
                rejected=dict(quantity="0", unit="piece", scale=0),
                evidence="Actual source inspection",
            ),
        )
    )
    rig.pull(inspection.source_key)
    rig.drain()
    with rig.workflow.store.transaction() as tx:
        import json

        row = tx.execute(
            "SELECT * FROM supply_receipts WHERE id=?", (str(manual.object_id),)
        ).fetchone()
        assert json.loads(row["source_json"])["mode"] == "manual"
        assert (
            tx.execute(
                "SELECT SUM(q_atoms) FROM effective_supply_receipts WHERE project_id=?",
                (str(rig.project_id),),
            ).fetchone()[0]
            == 14
        )
        assert (
            tx.execute(
                "SELECT SUM(accepted_atoms) FROM effective_iqc_results WHERE project_id=?",
                (str(rig.project_id),),
            ).fetchone()[0]
            == 12
        )
        assert (
            tx.execute(
                "SELECT COUNT(*) FROM source_confirmations WHERE fact_id=?",
                (str(manual.object_id),),
            ).fetchone()[0]
            == 1
        )
    assert rig.physical_balance(refs.lot).qualified == 12


def test_explicit_manual_iqc_links_keep_two_real_observations_distinct(rig):
    from uuid import uuid4
    from datetime import timedelta

    refs = rig.core_ready()
    opid = uuid4()
    source = rig.manual_source("receipt") | dict(system="wms", external_id=str(opid))
    manual = rig.command(
        "supply.receive",
        commitment_id=str(refs.commitment),
        material_lot_id=str(refs.lot),
        quantity="4",
        unit="piece",
        source=source,
    )
    for _ in range(2):
        rig.command(
            "supply.inspect",
            receipt_id=str(manual.object_id),
            accepted="2",
            rejected="0",
            evidence="Distinct documented manual inspection",
        )
    with rig.workflow.store.transaction() as tx:
        ids = [
            r[0]
            for r in tx.execute(
                "SELECT id FROM iqc_results WHERE receipt_id=?",
                (str(manual.object_id),),
            )
        ]
    receipt = rig.result_fact(
        rig.execute(
            "wms",
            dict(
                operation="wms.receive",
                commitment_id=str(refs.commitment),
                material_lot_id=str(refs.lot),
                lot_id="LOT",
                material_id="M",
                owner_id="C",
                amount=dict(quantity="4", unit="piece", scale=0),
                location="receiving",
                custodian="warehouse",
                supplier_batch="B2",
                expiry=(NOW + timedelta(days=30)).date().isoformat(),
            ),
            operation_id=opid,
        )
    )
    for iid in ids:
        rig.execute(
            "mes",
            dict(
                operation="mes.inspect",
                receipt=receipt.source_key.model_dump(),
                accepted=dict(quantity="2", unit="piece", scale=0),
                rejected=dict(quantity="0", unit="piece", scale=0),
                manual_iqc_id=iid,
                evidence="Actual separate source inspection",
            ),
        )
    rig.drain()
    with rig.workflow.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT SUM(accepted_atoms) FROM effective_iqc_results WHERE project_id=?",
                (str(rig.project_id),),
            ).fetchone()[0]
            == 12
        )
    assert rig.physical_balance(refs.lot).qualified == 12


def test_location_name_does_not_authorize_another_custodian_to_move_stock(rig):
    refs = rig.core_ready()
    with pytest.raises(DomainError, match="custody"):
        rig.execute(
            "wms",
            dict(
                operation="wms.putaway",
                allocations=[
                    dict(
                        material_lot_id=str(refs.lot),
                        material_id="M",
                        owner_id="C",
                        amount=dict(quantity="1", unit="piece", scale=0),
                        qualification=refs.qualification.model_dump(),
                    )
                ],
                source_custody=dict(location="receiving", custodian="NOT-RECEIVER"),
                destination_custody=dict(location="bin-A", custodian="warehouse"),
                cause=refs.qualification.model_dump(),
                evidence="Wrong source custodian",
            ),
        )
    assert (
        not rig.registry.adapter("wms").facts(rig.project_id, "putaway", 0, 200).records
    )


def test_source_reservation_aggregates_all_qualifications_against_requirement(rig):
    from datetime import timedelta
    from uuid import uuid4
    from manufacturing_platform.workflow.integrations.contracts import SystemOperation

    refs = rig.core_ready(quantity=10)
    receipt = rig.result_fact(
        rig.execute(
            "wms",
            dict(
                operation="wms.receive",
                commitment_id=str(refs.commitment),
                material_lot_id=str(refs.lot),
                lot_id="LOT",
                material_id="M",
                owner_id="C",
                amount=dict(quantity="4", unit="piece", scale=0),
                location="receiving",
                custodian="warehouse",
                supplier_batch="B2",
                expiry=(NOW + timedelta(days=30)).date().isoformat(),
            ),
        )
    )
    rig.execute(
        "mes",
        dict(
            operation="mes.inspect",
            receipt=receipt.source_key.model_dump(),
            accepted=dict(quantity="4", unit="piece", scale=0),
            rejected=dict(quantity="0", unit="piece", scale=0),
            evidence="Actual qualified surplus",
        ),
    )
    rig.drain()
    qualifications = (
        rig.registry.adapter("wms")
        .facts(rig.project_id, "qualification", 0, 200)
        .records
    )
    allocations = [
        dict(
            material_lot_id=refs.lot,
            material_id="M",
            owner_id="C",
            amount=q.payload.accepted.model_dump(mode="json"),
            qualification=q.source_key,
        )
        for q in qualifications
    ]
    op = SystemOperation(
        operation_id=uuid4(),
        system="wms",
        project_id=rig.project_id,
        payload=dict(
            operation="wms.reserve",
            work_order_id=refs.work_order,
            requirement_id=refs.requirement,
            allocations=allocations,
        ),
    )
    receipt = rig.registry.adapter("wms").execute(op)
    assert receipt.phase == "rejected"
    assert rig.physical_balance(refs.lot).reserved == 0


def test_explicit_reservation_release_frees_only_returned_unused_stock(rig):
    from uuid import uuid4

    refs = rig.start_ready()
    rig.execute("mes", refs.start_payload)
    execution = rig.pass_unit(refs)
    rig.execute(
        "mes",
        dict(
            operation="mes.complete",
            work_order_id=str(refs.work_order),
            revision_id=str(refs.revision),
            units=refs.units,
            execution_sources=[execution.source_key.model_dump()],
            consumption=[
                a.model_dump(mode="json") for a in execution.payload.material_uses
            ],
            occurred_at=NOW.isoformat(),
        ),
    )
    needed = (
        rig.registry.adapter("mes")
        .facts(rig.project_id, "return_requirement", 0, 200)
        .records[-1]
    )
    payload = needed.payload.model_dump(mode="json", exclude={"fact_type"}) | {
        "cause": needed.source_key.model_dump()
    }
    returned = rig.result_fact(
        rig.execute(
            "wms", dict(operation="wms.return", direction="to_warehouse", **payload)
        )
    )
    assert rig.physical_balance(refs.lot).reserved == 12
    reservation = (
        rig.registry.adapter("wms")
        .facts(rig.project_id, "reservation", 0, 200)
        .records[0]
    )
    rid = rig.target(reservation, "reservation")
    original = rig.original_receipt_bytes("wms", reservation.source.external_id)
    release_payload = dict(
        operation="wms.release_reservation",
        work_order_id=str(refs.work_order),
        reservation=reservation.source_key.model_dump(),
        allocations=[a.model_dump(mode="json") for a in returned.payload.allocations],
        cause=returned.source_key.model_dump(),
        evidence="Explicit release of completed unused allocation",
    )
    import copy

    invalid = copy.deepcopy(release_payload)
    invalid["allocations"][0]["amount"]["quantity"] = "12"
    with pytest.raises(DomainError, match="warehouse-held"):
        rig.execute("wms", invalid)
    invalid = copy.deepcopy(release_payload)
    invalid["allocations"][0]["owner_id"] = "FOREIGN"
    with pytest.raises(DomainError):
        rig.execute("wms", invalid)
    assert rig.physical_balance(refs.lot).reserved == 12
    opid = uuid4()
    release = rig.result_fact(rig.execute("wms", release_payload, operation_id=opid))
    rig.query(opid)
    from manufacturing_platform.workflow.integrations.contracts import SystemOperation

    with rig.registry.adapter("wms").store.transaction() as tx:
        original_release = SystemOperation.model_validate_json(
            tx.execute(
                "SELECT payload_json FROM operations WHERE project_id=? AND id=?",
                (str(rig.project_id), str(opid)),
            ).fetchone()[0]
        )
    rig.registry.adapter("wms").execute(original_release)
    assert (
        len(
            rig.registry.adapter("wms")
            .facts(rig.project_id, "reservation_release", 0, 200)
            .records
        )
        == 1
    )
    assert rig.physical_balance(refs.lot).reserved == 1
    assert rig.original_receipt_bytes("wms", reservation.source.external_id) == original
    with rig.workflow.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT confirmed_atoms FROM reservations WHERE id=?", (str(rid),)
            ).fetchone()[0]
            == 12
        )
        assert (
            tx.execute(
                "SELECT confirmed_atoms FROM effective_reservations WHERE id=?",
                (str(rid),),
            ).fetchone()[0]
            == 1
        )
        from manufacturing_platform.workflow.exchanges import detail

        value = detail(tx, rig.project_id, "reservation", rid).value
        assert (value.confirmed, value.released, value.remaining) == (1, 11, 0)
    pick = rig.registry.adapter("wms").facts(rig.project_id, "pick", 0, 200).records[0]
    old = pick.payload.model_dump(mode="json", exclude={"fact_type"})
    old["allocations"][0]["amount"]["quantity"] = "1"
    with pytest.raises(DomainError, match="reservation"):
        rig.execute("wms", dict(operation="wms.pick", **old))
    rig.pick_qualified(refs, quantity=11)
    assert rig.physical_balance(refs.lot).reserved == 12
    assert rig.sap_post_count(release.source_key) == 0
    with rig.workflow.store.transaction() as tx:
        from manufacturing_platform.workflow.ownership import balance

        lot = tx.execute(
            "SELECT * FROM material_lots WHERE id=?", (str(refs.lot),)
        ).fetchone()
        current = balance(tx, rig.project_id, lot)
        assert (current.received, current.consumed, current.balance) == (12, 1, 11)


def test_unprojected_source_reservations_still_consume_requirement_budget(rig):
    from uuid import uuid4
    from manufacturing_platform.workflow.integrations.contracts import SystemOperation

    refs = rig.core_ready(quantity=8, received=12, accepted=12)

    def reserve(amount):
        return rig.registry.adapter("wms").execute(
            SystemOperation(
                operation_id=uuid4(),
                system="wms",
                project_id=rig.project_id,
                payload=dict(
                    operation="wms.reserve",
                    work_order_id=refs.work_order,
                    requirement_id=refs.requirement,
                    allocations=[
                        dict(
                            material_lot_id=refs.lot,
                            material_id="M",
                            owner_id="C",
                            amount=dict(quantity=str(amount), unit="piece", scale=0),
                            qualification=refs.qualification,
                        )
                    ],
                ),
            )
        )

    assert reserve(5).phase == "accepted"
    assert reserve(5).phase == "rejected"
    assert rig.physical_balance(refs.lot).reserved == 5


def test_core_stock_proof_cannot_substitute_the_original_exchange_identity(rig):
    from uuid import uuid4
    import hashlib
    from manufacturing_platform.workflow.exchange_models import (
        ExternalRequest,
        StockProofPayload,
    )

    refs = rig.core_ready()
    reservation = rig.command(
        "reservation.request",
        work_order_id=str(refs.work_order),
        requirement_id=str(refs.requirement),
        lot_id=str(refs.lot),
        quantity="8",
        unit="piece",
    )
    rig.command("exchange.dispatch", exchange_id=str(reservation.exchange_id))
    with rig.workflow.store.transaction() as tx:
        row = tx.execute(
            "SELECT * FROM exchanges WHERE id=?", (str(reservation.exchange_id),)
        ).fetchone()
        original = ExternalRequest.model_validate_json(row["request_json"])
        receipt_hash = hashlib.sha256(row["receipt_json"].encode()).hexdigest()
    payload = StockProofPayload(
        eco_id=uuid4(),
        reservation_id=reservation.object_id,
        original_exchange_id=original.id,
        original_business_key=original.business_key,
        original_receipt_hash=receipt_hash,
        original_opening_hash="a" * 64,
        original_accounted_atoms=0,
    )
    proof_request = ExternalRequest(
        id=uuid4(),
        project_id=rig.project_id,
        system="wms",
        action="stock_basis.reconcile",
        business_key="proof",
        source_version=1,
        typed_payload=payload,
    )
    adapter = rig.registry.exchange_adapter("wms")
    assert (
        adapter.stock_basis(proof_request).receipt.request_hash
        == adapter.query("wms", original.business_key).request_hash
    )
    with pytest.raises(DomainError, match="scope"):
        adapter.stock_basis(
            proof_request.model_copy(
                update={
                    "typed_payload": payload.model_copy(
                        update={"original_exchange_id": uuid4()}
                    )
                }
            )
        )


def test_completion_cannot_substitute_an_older_passed_route_execution(rig):
    refs = rig.start_ready()
    rig.execute("mes", refs.start_payload)
    previous = rig.pass_unit(refs)
    rig.pass_unit(refs)
    with pytest.raises(DomainError, match="current route"):
        rig.execute(
            "mes",
            dict(
                operation="mes.complete",
                work_order_id=str(refs.work_order),
                revision_id=str(refs.revision),
                units=refs.units,
                execution_sources=[previous.source_key.model_dump()],
                consumption=[
                    a.model_dump(mode="json") for a in previous.payload.material_uses
                ],
                occurred_at=NOW.isoformat(),
            ),
        )
    assert (
        rig.registry.adapter("mes").facts(rig.project_id, "completion", 0, 200).records
        == []
    )
    rig.drain()
    assert rig.physical_balance(refs.lot).consumed == 2
