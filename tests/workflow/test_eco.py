"""ECO boundaries exercised through public commands and two durable stores."""

import pytest

from .conftest import WorkflowHarness


def open_eco_with_stock(self):
    p, _requirement, scope = self.material_requirement(required="100", qualified="80")
    new = self.revision(p["id"], internal_revision="M2")
    result = self.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=scope["revision_id"],
        new_revision_id=new["id"],
        effective_work_order_ids=[scope["work_order_id"]],
        effective_sn_ids=[],
        reason="M2 change",
    )
    eco = self.object(p["id"], "eco", result["object_id"])
    stock = next(i for i in eco["impacts"] if i["type"] == "stock")
    return p, eco, stock


WorkflowHarness.open_eco_with_stock = open_eco_with_stock


def test_eco_cannot_close_with_unresolved_old_stock(workflow):
    p, eco, impact = workflow.open_eco_with_stock()
    result = workflow.command(
        p["id"],
        "eco.close",
        actor_name="engineering",
        eco_id=eco["id"],
        expected_status=409,
    )
    assert impact["id"] in result["fields"]["unresolved_impact_ids"]
    assert workflow.object(p["id"], "eco", eco["id"])["state"] == "open"


def cancellation(workflow, *, allocated=False):
    p, order, wo, rev = workflow.order_workorder(quantity="20")
    if allocated:
        workflow.command(
            p["id"],
            "order.allocate",
            actor_name="planner",
            order_line_id=order["id"],
            work_order_id=wo["id"],
            quantity="20",
            unit="piece",
        )
    eco = workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=rev["id"],
        effective_work_order_ids=[wo["id"]],
        reason="order cancellation",
    )
    switch = workflow.command(
        p["id"],
        "eco.switch",
        actor_name="engineering",
        eco_id=eco["object_id"],
        target_work_order_id=wo["id"],
        boundary="cancel_remaining",
        evidence="cancel unstarted obligation",
    )
    return p, order, wo, eco, switch


def test_unallocated_cancellation_releases_obligation_only_after_authority_receipt(
    workflow,
):
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    p, order, wo, _eco, switch = cancellation(workflow)
    before = workflow.object(p["id"], "order_line", order["id"])
    assert before["work_order_impact"]["registered_quantity"] == "20"
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="engineering",
        exchange_id=switch["exchange_id"],
    )
    after = workflow.object(p["id"], "order_line", order["id"])
    assert after["work_order_impact"]["registered_quantity"] == "0"
    assert workflow.object(p["id"], "work_order", wo["id"])["quantity"] == "20"
    assert (
        workflow.object(p["id"], "work_order", wo["id"])["remaining_obligation"] == "0"
    )
    authority = MockAuthorityAdapter(str(workflow.paths.authority), "workflow-test")
    with authority.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT total_units FROM authority_work_orders WHERE work_order_id=?",
                (wo["id"],),
            ).fetchone()[0]
            == 0
        )
    assert authority.operation_count(switch["exchange_id"]) == 1


def test_rejected_and_lost_cancel_receipts_keep_allocations_until_query(workflow):
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    p, order, wo, eco, switch = cancellation(workflow, allocated=True)
    authority = MockAuthorityAdapter(str(workflow.paths.authority), "workflow-test")
    authority.configure_fault("reject")
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="engineering",
        exchange_id=switch["exchange_id"],
    )
    assert workflow.object(p["id"], "order_line", order["id"])["allocated"] == "20"
    retry = workflow.command(
        p["id"],
        "eco.switch",
        actor_name="engineering",
        eco_id=eco["object_id"],
        target_work_order_id=wo["id"],
        boundary="cancel_remaining",
        evidence="retry confirmed rejection",
    )
    authority.configure_fault("timeout_after_commit")
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="engineering",
        exchange_id=retry["exchange_id"],
    )
    assert workflow.object(p["id"], "order_line", order["id"])["allocated"] == "20"
    workflow.command(
        p["id"],
        "exchange.query",
        actor_name="engineering",
        exchange_id=retry["exchange_id"],
    )
    assert workflow.object(p["id"], "order_line", order["id"])["allocated"] == "0"
    with workflow.db() as tx:
        assert (
            tx.execute(
                "SELECT SUM(q_atoms) FROM allocations WHERE work_order_id=?",
                (wo["id"],),
            ).fetchone()[0]
            == 20
        )


def test_split_five_old_fifteen_new_preserves_history_and_resets_readiness(
    workflow, monkeypatch
):
    from .test_execution import ready_for_trial

    p, wo, units, authority = ready_for_trial(
        workflow, quantity="20", trial_quantity="5"
    )
    old = workflow.object(p["id"], "work_order", wo["id"])
    workflow.command(
        p["id"],
        "order.allocate",
        actor_name="planner",
        order_line_id=old["order_line_id"],
        work_order_id=wo["id"],
        quantity="20",
        unit="piece",
    )
    start = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=units[:5],
        quantity="5",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=start["exchange_id"],
    )
    from datetime import UTC, datetime

    with workflow.db() as tx:
        lot = tx.execute(
            "SELECT id FROM material_lots WHERE project_id=?", (p["id"],)
        ).fetchone()[0]
    for n, uid in enumerate(units[:5]):
        workflow.command(
            p["id"],
            "execution.record",
            actor_name="production",
            source=workflow.source(f"old-five-{n}", object_type="execution"),
            work_order_id=wo["id"],
            sn=workflow.object(p["id"], "unit", uid)["sn"],
            station="assembly",
            route_version="S1",
            program_version="P1",
            firmware_version="F1",
            material_uses=[{"lot_id": lot, "quantity": "0.1", "unit": "kg"}],
            result="pass",
            occurred_at=datetime.now(UTC).isoformat(),
        )
    prior_events = workflow.object(p["id"], "work_order", wo["id"])["execution_events"]
    assert len(prior_events) == 5 and all(
        e["status"] == "accepted" for e in prior_events
    )
    new = workflow.revision(p["id"], internal_revision="M2")
    workflow.command(
        p["id"],
        "work_order.register",
        actor_name="planner",
        expected_status=409,
        order_line_id=old["order_line_id"],
        revision_id=new["id"],
        source=old["source"],
        quantity=old["quantity"],
        unit=old["unit"],
        purpose=old["purpose"],
        trial_quantity=old["trial_quantity"],
        planned_start=old["planned_start"],
        planned_end=old["planned_end"],
    )
    assert (
        workflow.object(p["id"], "work_order", wo["id"])["revision_id"]
        == old["revision_id"]
    )
    workflow.command(
        p["id"],
        "engineering.handoff",
        actor_name="engineering",
        revision_id=new["id"],
        to_system="MES",
        received_revision="M2",
        decision="accepted",
        evidence="MES M2",
    )
    workflow.command(
        p["id"],
        "engineering.customer_approval",
        revision_id=new["id"],
        customer_id="Customer 1",
        external_signatory="customer",
        decision="approved",
        evidence="M2 approval",
    )
    eco = workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=old["revision_id"],
        new_revision_id=new["id"],
        effective_work_order_ids=[wo["id"]],
        reason="M2 change",
    )
    switch = workflow.command(
        p["id"],
        "eco.switch",
        actor_name="engineering",
        eco_id=eco["object_id"],
        target_work_order_id=wo["id"],
        new_revision_id=new["id"],
        evidence="split unexecuted 15",
    )
    assert switch["object_type"] == "work_order" and switch["object_id"] != wo["id"]
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    original_submit = MockAuthorityAdapter.submit

    def missing_creation(adapter, request):
        receipt = original_submit(adapter, request)
        if request.action == "eco.switch":
            # Corrupt only delivery; both actual authority effects and the complete
            # authoritative stored receipt exist for subsequent safe query.
            receipt.details = receipt.details[:1]
        return receipt

    monkeypatch.setattr(MockAuthorityAdapter, "submit", missing_creation)
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="engineering",
        exchange_id=switch["exchange_id"],
    )
    assert (
        workflow.object(p["id"], "exchange", switch["exchange_id"])["phase"]
        == "rejected"
    )
    assert (
        workflow.object(p["id"], "work_order", wo["id"])["remaining_obligation"] == "20"
    )
    with workflow.db() as tx:
        assert not tx.execute(
            "SELECT 1 FROM work_orders WHERE id=?", (switch["object_id"],)
        ).fetchone()
    workflow.command(
        p["id"],
        "exchange.query",
        actor_name="engineering",
        exchange_id=switch["exchange_id"],
    )
    replacement = workflow.object(p["id"], "work_order", switch["object_id"])
    assert (
        replacement["quantity"],
        replacement["revision_id"],
        replacement["order_line_id"],
    ) == ("15", new["id"], old["order_line_id"])
    assert not replacement["trial_readiness"]["ready"]
    assert {
        c["kind"]
        for c in replacement["trial_readiness"]["checks"]
        if c["status"] == "blocked"
    } >= {"equipment", "people", "material", "plan"}
    workflow.command(
        p["id"],
        "unit.register",
        actor_name="production",
        work_order_id=switch["object_id"],
        sns=[f"NEW-M2-{n}" for n in range(15)],
    )
    with workflow.db() as tx:
        assert {
            (r["revision_id"], r["work_order_id"])
            for r in tx.execute(
                "SELECT * FROM units WHERE work_order_id=?", (switch["object_id"],)
            )
        } == {(new["id"], switch["object_id"])}
    retained = workflow.object(p["id"], "work_order", wo["id"])
    assert retained["execution_events"] == prior_events
    assert (
        retained["quantity"],
        retained["revision_id"],
        retained["remaining_obligation"],
    ) == ("20", old["revision_id"], "5")
    for uid in units[:5]:
        u = workflow.object(p["id"], "unit", uid)
        assert u["revision_id"] == old["revision_id"] and u["authority_start_accepted"]
    order = workflow.object(p["id"], "order_line", old["order_line_id"])
    assert (
        order["allocated"] == order["work_order_impact"]["registered_quantity"] == "20"
    )
    assert sorted(i["quantity"] for i in order["work_order_impact"]["items"]) == [
        "15",
        "5",
    ]
    with authority.store.transaction() as tx:
        scopes = tx.execute(
            "SELECT total_units,started_units FROM authority_work_orders WHERE project_id=? ORDER BY total_units",
            (p["id"],),
        ).fetchall()
        assert [tuple(r) for r in scopes] == [(5, 5), (15, 0)]
    blocked = workflow.command(
        p["id"],
        "eco.close",
        actor_name="engineering",
        eco_id=eco["object_id"],
        expected_status=409,
    )
    assert blocked["fields"]["unresolved_impact_ids"]


def test_cancel_then_resolve_order_change_without_fictitious_revision(workflow):
    p, order, wo, eco, switch = cancellation(workflow, allocated=True)
    change = workflow.command(
        p["id"],
        "order.change",
        order_line_id=order["id"],
        new_quantity="20",
        new_due_date="2026-12-01",
        cancel=True,
        reason="customer cancels",
        source=workflow.source(
            workflow.object(p["id"], "order_line", order["id"])["source"][
                "external_id"
            ],
            object_type="order_line",
            version=2,
        ),
    )
    fields = {
        "change_id": change["object_id"],
        "dispositions": [
            {
                "object_type": "work_order",
                "object_id": wo["id"],
                "decision": "cancel",
                "evidence": "authority cancellation",
            }
        ],
    }
    workflow.command(p["id"], "order.resolve_change", expected_status=409, **fields)
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="engineering",
        exchange_id=switch["exchange_id"],
    )
    workflow.command(p["id"], "order.resolve_change", **fields)
    value = workflow.object(p["id"], "order_line", order["id"])
    assert value["state"] == "cancelled" and value["current_quantity"] == "0"
    snapshot = workflow.object(p["id"], "eco", eco["object_id"])
    assert snapshot["new_revision_id"] is None
    for i in snapshot["impacts"]:
        workflow.command(
            p["id"],
            "eco.disposition",
            actor_name="engineering",
            eco_id=eco["object_id"],
            impact_id=i["id"],
            quantity=i["quantity"],
            decision="use_old",
            evidence="retained cancellation record; no physical stock",
        )
    workflow.command(
        p["id"], "eco.close", actor_name="engineering", eco_id=eco["object_id"]
    )
    assert workflow.object(p["id"], "eco", eco["object_id"])["state"] == "closed"


def test_unknown_start_cannot_be_cancelled_and_held_accepted_scope_is_retained(
    workflow,
):
    from datetime import UTC, datetime, timedelta

    from .test_execution import ready_for_trial

    p, wo, units, authority = ready_for_trial(workflow)
    start = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=units[:1],
        quantity="1",
    )
    authority.configure_fault("timeout_after_commit")
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=start["exchange_id"],
    )
    old = workflow.object(p["id"], "work_order", wo["id"])
    eco = workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=old["revision_id"],
        effective_work_order_ids=[wo["id"]],
        reason="cancel rest",
    )
    args = {
        "eco_id": eco["object_id"],
        "target_work_order_id": wo["id"],
        "boundary": "cancel_remaining",
        "evidence": "remaining only",
    }
    workflow.command(
        p["id"], "eco.switch", actor_name="engineering", expected_status=409, **args
    )
    workflow.command(
        p["id"],
        "readiness.record",
        actor_name="engineering",
        work_order_id=wo["id"],
        kind="equipment",
        reference="revoked",
        evidence="loss",
        decision="rejected",
        valid_until=(datetime.now(UTC) + timedelta(days=90)).isoformat(),
    )
    workflow.command(
        p["id"],
        "exchange.query",
        actor_name="production",
        exchange_id=start["exchange_id"],
    )
    assert workflow.object(p["id"], "unit", units[0])["state"] == "start_pending"
    switch = workflow.command(p["id"], "eco.switch", actor_name="engineering", **args)
    authority.configure_fault("none")
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="engineering",
        exchange_id=switch["exchange_id"],
    )
    assert (
        workflow.object(p["id"], "work_order", wo["id"])["remaining_obligation"] == "1"
    )
    assert workflow.object(p["id"], "unit", units[0])["state"] == "start_pending"
    with authority.store.transaction() as tx:
        row = tx.execute(
            "SELECT total_units,started_units FROM authority_work_orders WHERE work_order_id=?",
            (wo["id"],),
        ).fetchone()
        assert tuple(row) == (1, 1)
        assert (
            tx.execute(
                "SELECT state FROM authority_start_units WHERE unit_id=?", (units[0],)
            ).fetchone()[0]
            == "running"
        )


def test_new_revision_unknown_customer_blocks_split_but_not_cancellation(workflow):
    p, _order, wo, old = workflow.order_workorder()
    new = workflow.revision(p["id"], internal_revision="M2")
    workflow.command(
        p["id"],
        "engineering.handoff",
        actor_name="engineering",
        revision_id=new["id"],
        to_system="MES",
        received_revision="M2",
        decision="accepted",
        evidence="M2 handoff",
    )
    eco = workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=old["id"],
        new_revision_id=new["id"],
        effective_work_order_ids=[wo["id"]],
        reason="new product version",
    )
    blocked = workflow.command(
        p["id"],
        "eco.switch",
        actor_name="engineering",
        expected_status=409,
        eco_id=eco["object_id"],
        target_work_order_id=wo["id"],
        new_revision_id=new["id"],
        evidence="no approval",
    )
    assert "customer" in blocked["message"]


def test_growing_stock_requires_only_new_delta_and_dispositions_remain_immutable(
    workflow,
):
    p, eco, impact = workflow.open_eco_with_stock()
    workflow.command(
        p["id"],
        "eco.disposition",
        actor_name="engineering",
        eco_id=eco["id"],
        impact_id=impact["id"],
        decision="use_old",
        quantity="80",
        evidence="old 80 retained",
    )
    purchase = next(i for i in eco["impacts"] if i["type"] == "purchase")
    workflow.receive(
        p["id"], purchase["object_id"], quantity="10", lot_id=impact["object_id"]
    )
    current = workflow.object(p["id"], "eco", eco["id"])
    delta = next(
        i
        for i in current["impacts"]
        if i["type"] == "stock" and i["id"] != impact["id"]
    )
    assert delta["quantity"] == "10"
    workflow.command(
        p["id"],
        "eco.disposition",
        actor_name="engineering",
        eco_id=eco["id"],
        impact_id=delta["id"],
        decision="return",
        quantity="10",
        evidence="new arrival returned",
    )
    again = workflow.object(p["id"], "eco", eco["id"])
    assert len([i for i in again["impacts"] if i["type"] == "stock"]) == 2
    workflow.command(
        p["id"],
        "eco.disposition",
        actor_name="engineering",
        expected_status=409,
        eco_id=eco["id"],
        impact_id=impact["id"],
        decision="scrap",
        quantity="1",
        evidence="cannot double dispose",
    )
    with workflow.db() as tx:
        assert (
            tx.execute(
                "SELECT SUM(q_atoms) FROM supply_receipts WHERE material_lot_id=?",
                (impact["object_id"],),
            ).fetchone()[0]
            == 90000
        )


def test_split_dispatch_rechecks_new_revision_handoff_before_authority_effect(workflow):
    p, _order, wo, old = workflow.order_workorder(
        contract={
            "customer_approval_required": False,
            "customer_release_required": False,
            "acceptance_required": False,
            "customer_revision": "C1",
            "internal_revision": "M1",
            "material_ownership_rules": "internal",
        }
    )
    new = workflow.revision(p["id"], internal_revision="M2")
    handoff = {
        "actor_name": "engineering",
        "revision_id": new["id"],
        "to_system": "MES",
        "received_revision": "M2",
        "evidence": "MES package",
    }
    workflow.command(p["id"], "engineering.handoff", decision="accepted", **handoff)
    eco = workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=old["id"],
        new_revision_id=new["id"],
        effective_work_order_ids=[wo["id"]],
        reason="M2",
    )
    switch = workflow.command(
        p["id"],
        "eco.switch",
        actor_name="engineering",
        eco_id=eco["object_id"],
        target_work_order_id=wo["id"],
        new_revision_id=new["id"],
        evidence="approved at intent",
    )
    workflow.command(p["id"], "engineering.handoff", decision="rejected", **handoff)
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="engineering",
        exchange_id=switch["exchange_id"],
    )
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    authority = MockAuthorityAdapter(str(workflow.paths.authority), "workflow-test")
    assert authority.operation_count(switch["exchange_id"]) == 0
    workflow.command(p["id"], "engineering.handoff", decision="accepted", **handoff)
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="engineering",
        exchange_id=switch["exchange_id"],
    )
    assert authority.operation_count(switch["exchange_id"]) == 1


def test_remaining_cancellation_preserves_partial_recovery_and_superseding_stop(
    workflow,
):
    from .test_execution import r7_partial_with_full_resume_intent

    p, wo, units, authority, old_stop, _trial, _full = (
        r7_partial_with_full_resume_intent(workflow)
    )
    old = workflow.object(p["id"], "work_order", wo["id"])
    eco = workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=old["revision_id"],
        effective_work_order_ids=[wo["id"]],
        reason="cancel unstarted three",
    )
    switch = workflow.command(
        p["id"],
        "eco.switch",
        actor_name="engineering",
        eco_id=eco["object_id"],
        target_work_order_id=wo["id"],
        boundary="cancel_remaining",
        evidence="trial running, bulk stopped, three cancelled",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="engineering",
        exchange_id=switch["exchange_id"],
    )
    assert workflow.object(p["id"], "unit", units[0])["state"] == "running"
    assert workflow.object(p["id"], "unit", units[1])["state"] == "stopped"
    stop = workflow.command(
        p["id"],
        "production.interrupt",
        actor_name="production",
        work_order_id=wo["id"],
        reason="new safety event",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=stop["exchange_id"],
    )
    prior = workflow.object(p["id"], "interruption", old_stop["object_id"])
    assert (
        prior["superseded_by"] == stop["object_id"]
        and prior["trial_resumed_at"]
        and prior["resolved_at"] is None
    )
    assert (
        workflow.object(p["id"], "work_order", wo["id"])["remaining_obligation"] == "2"
    )
    with authority.store.transaction() as tx:
        assert tuple(
            tx.execute(
                "SELECT total_units,started_units,started_trial FROM authority_work_orders WHERE work_order_id=?",
                (wo["id"],),
            ).fetchone()
        ) == (2, 2, 1)
        assert {
            r[0]
            for r in tx.execute(
                "SELECT state FROM authority_start_units WHERE work_order_id=?",
                (wo["id"],),
            )
        } == {"stopped"}


def test_invalid_cancel_detail_cannot_release_obligation_or_retry_as_confirmed_rejection(
    workflow,
):
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    p, order, wo, eco, switch = cancellation(workflow, allocated=True)
    authority = MockAuthorityAdapter(str(workflow.paths.authority), "workflow-test")
    authority.configure_fault("changed_detail_same_total")
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="engineering",
        exchange_id=switch["exchange_id"],
    )
    assert workflow.object(p["id"], "order_line", order["id"])["allocated"] == "20"
    assert (
        workflow.object(p["id"], "work_order", wo["id"])["remaining_obligation"] == "20"
    )
    workflow.command(
        p["id"],
        "eco.switch",
        actor_name="engineering",
        expected_status=409,
        eco_id=eco["object_id"],
        target_work_order_id=wo["id"],
        boundary="cancel_remaining",
        evidence="not a true rejection",
    )
    with authority.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT total_units FROM authority_work_orders WHERE work_order_id=?",
                (wo["id"],),
            ).fetchone()[0]
            == 0
        )


def test_cancel_authority_effect_survives_cas_conflict_and_applies_once_on_query(
    workflow, monkeypatch
):
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    p, order, wo, _eco, switch = cancellation(workflow, allocated=True)
    original = MockAuthorityAdapter.submit

    def changed(adapter, request):
        receipt = original(adapter, request)
        if request.action == "eco.switch":
            workflow.revision(p["id"], internal_revision="M9")
        return receipt

    monkeypatch.setattr(MockAuthorityAdapter, "submit", changed)
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="engineering",
        expected_status=409,
        exchange_id=switch["exchange_id"],
    )
    assert workflow.object(p["id"], "order_line", order["id"])["allocated"] == "20"
    workflow.command(
        p["id"],
        "exchange.query",
        actor_name="engineering",
        exchange_id=switch["exchange_id"],
    )
    workflow.command(
        p["id"],
        "exchange.query",
        actor_name="engineering",
        exchange_id=switch["exchange_id"],
    )
    assert workflow.object(p["id"], "order_line", order["id"])["allocated"] == "0"
    with workflow.db() as tx:
        assert (
            tx.execute(
                "SELECT COUNT(*) FROM allocation_adjustments WHERE work_order_id=?",
                (wo["id"],),
            ).fetchone()[0]
            == 1
        )


def test_eco_scoped_permissions_and_cross_project_boundary_are_enforced(workflow):
    p, _order, _wo, _eco, switch = cancellation(workflow)
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="planner",
        expected_status=403,
        exchange_id=switch["exchange_id"],
    )
    _other, _, foreign, rev = workflow.order_workorder()
    workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        expected_status=404,
        old_revision_id=rev["id"],
        effective_work_order_ids=[foreign["id"]],
        reason="foreign",
    )
    workflow.grant(p["id"], "engineering", ["engineering"], active=False)
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="owner",
        expected_status=403,
        exchange_id=switch["exchange_id"],
    )


def test_v8_migration_preserves_original_registration_and_adds_empty_delta_projection(
    workflow,
):
    import sqlite3

    p, _order, wo, _rev = workflow.order_workorder()
    with workflow.db() as tx:
        original = dict(
            tx.execute("SELECT * FROM work_orders WHERE id=?", (wo["id"],)).fetchone()
        )
    # Isolated old-schema migration fixture; no business success facts are seeded.
    with sqlite3.connect(workflow.paths.domain) as tx:
        for view in ("effective_work_orders", "effective_allocations"):
            tx.execute(f"DROP VIEW {view}")
        for table in (
            "allocation_adjustments",
            "eco_switches",
            "eco_dispositions",
            "eco_impacts",
            "eco_changes",
        ):
            tx.execute(f"DROP TABLE {table}")
        tx.execute("UPDATE schema_version SET version=8")
    workflow.reopen()
    assert (
        workflow.object(p["id"], "work_order", wo["id"])["remaining_obligation"] == "5"
    )
    with workflow.db() as tx:
        assert (
            dict(
                tx.execute(
                    "SELECT * FROM work_orders WHERE id=?", (wo["id"],)
                ).fetchone()
            )
            == original
        )
        assert tx.execute("SELECT version FROM schema_version").fetchone()[0] == 14


def test_multiple_ecos_on_same_revision_have_independent_immutable_impact_evidence(
    workflow,
):
    p, first, stock = workflow.open_eco_with_stock()
    second = workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=first["old_revision_id"],
        effective_work_order_ids=first["effective_work_order_ids"],
        reason="independent cancellation review",
    )
    other = workflow.object(p["id"], "eco", second["object_id"])
    other_stock = next(i for i in other["impacts"] if i["type"] == "stock")
    assert stock["id"] != other_stock["id"]
    workflow.command(
        p["id"],
        "eco.disposition",
        actor_name="engineering",
        expected_status=404,
        eco_id=other["id"],
        impact_id=stock["id"],
        quantity="80",
        decision="return",
        evidence="foreign ECO",
    )


def test_source_start_after_cancel_intent_rejects_stale_boundary_and_local_new_starts_are_locked(
    workflow,
):
    from uuid import uuid4

    from manufacturing_platform.workflow.exchange_models import (
        ExternalRequest,
        StartPayload,
    )

    from .test_execution import ready_for_trial

    p, wo, units, authority = ready_for_trial(workflow)
    old = workflow.object(p["id"], "work_order", wo["id"])
    eco = workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=old["revision_id"],
        effective_work_order_ids=[wo["id"]],
        reason="cancel all unstarted",
    )
    switch = workflow.command(
        p["id"],
        "eco.switch",
        actor_name="engineering",
        eco_id=eco["object_id"],
        target_work_order_id=wo["id"],
        boundary="cancel_remaining",
        evidence="zero locally accepted starts",
    )
    workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        expected_status=409,
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=units[:1],
        quantity="1",
    )
    workflow.command(
        p["id"],
        "unit.register",
        actor_name="production",
        expected_status=409,
        work_order_id=wo["id"],
        sns=["MUST-NOT-REGISTER"],
    )
    workflow.command(
        p["id"],
        "order.allocate",
        actor_name="planner",
        expected_status=409,
        order_line_id=old["order_line_id"],
        work_order_id=wo["id"],
        quantity="1",
        unit="piece",
    )
    # A real independent MES start occurs after the cancellation intent. No local
    # success SQL or receipt is manufactured; authority executes its start handler.
    eid = uuid4()
    receipt = authority.submit(
        ExternalRequest(
            id=eid,
            system="erp",
            action="production.start",
            business_key=str(eid),
            source_version=1,
            project_id=p["id"],
            typed_payload=StartPayload(
                start_id=uuid4(),
                work_order_id=wo["id"],
                revision_id=old["revision_id"],
                mode="trial",
                work_order_quantity=5,
                trial_quantity=1,
                units=[(units[0], workflow.object(p["id"], "unit", units[0])["sn"])],
            ),
        )
    )
    assert receipt.phase == "accepted"
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="engineering",
        exchange_id=switch["exchange_id"],
    )
    assert (
        workflow.object(p["id"], "exchange", switch["exchange_id"])["phase"]
        == "rejected"
    )
    assert (
        workflow.object(p["id"], "work_order", wo["id"])["remaining_obligation"] == "5"
    )
    with authority.store.transaction() as tx:
        assert tuple(
            tx.execute(
                "SELECT total_units,started_units FROM authority_work_orders WHERE work_order_id=?",
                (wo["id"],),
            ).fetchone()
        ) == (5, 1)


def dispose_all(workflow, p, eco_id):
    value = workflow.object(p["id"], "eco", eco_id)
    for i in value["impacts"]:
        if i["resolved_quantity"] != i["quantity"]:
            workflow.command(
                p["id"],
                "eco.disposition",
                actor_name="engineering",
                eco_id=eco_id,
                impact_id=i["id"],
                quantity=i["quantity"],
                decision="use_old",
                evidence="explicit retained old-version use",
            )


def test_i1_distinct_replenishment_after_consumption_cannot_inherit_stock_disposition(
    workflow,
):
    from decimal import Decimal

    from .test_execution import running_execution

    p, wo, _units, _authority, event = running_execution(workflow)
    old = workflow.object(p["id"], "work_order", wo["id"])
    eco = workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=old["revision_id"],
        effective_work_order_ids=[wo["id"]],
        reason="review old material",
    )
    dispose_all(workflow, p, eco["object_id"])
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=workflow.source("i1-use", object_type="execution"),
        **event,
    )
    with workflow.db() as tx:
        req = tx.execute(
            "SELECT id FROM requirements WHERE work_order_id=? LIMIT 1", (wo["id"],)
        ).fetchone()[0]
    commitment = workflow.command(
        p["id"],
        "supply.commit",
        actor_name="supply",
        requirement_id=req,
        type="customer",
        owner_id="Customer 1",
        quantity="1",
        unit="kg",
        original_due="2026-12-01",
        current_due="2026-12-01",
        source=workflow.source("i1-promise", object_type="commitment"),
    )
    workflow.receive(
        p["id"],
        commitment["object_id"],
        quantity="0.1",
        lot_id=event["material_uses"][0]["lot_id"],
    )
    value = workflow.object(p["id"], "eco", eco["object_id"])
    unresolved = [
        i
        for i in value["impacts"]
        if i["type"] == "stock"
        and Decimal(i["quantity"]) > Decimal(i["resolved_quantity"])
    ]
    assert sum(Decimal(i["quantity"]) for i in unresolved) == Decimal("0.1")
    assert (
        workflow.object(p["id"], "eco", eco["object_id"])["impacts"] == value["impacts"]
    )
    rejected = workflow.command(
        p["id"],
        "eco.close",
        actor_name="engineering",
        eco_id=eco["object_id"],
        expected_status=409,
    )
    assert unresolved[0]["id"] in rejected["fields"]["unresolved_impact_ids"]


def test_i2_fully_started_old_scope_can_close_only_with_explicit_retained_proof(
    workflow,
):
    from .test_execution import ready_for_trial

    p, wo, units, authority = ready_for_trial(workflow, quantity="1")
    start = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=units,
        quantity="1",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=start["exchange_id"],
    )
    old = workflow.object(p["id"], "work_order", wo["id"])
    eco = workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=old["revision_id"],
        effective_work_order_ids=[wo["id"]],
        reason="retain all old WIP",
    )
    dispose_all(workflow, p, eco["object_id"])
    workflow.command(
        p["id"],
        "eco.close",
        actor_name="engineering",
        eco_id=eco["object_id"],
        expected_status=409,
    )
    before = authority.operation_count()
    result = workflow.command(
        p["id"],
        "eco.switch",
        actor_name="engineering",
        eco_id=eco["object_id"],
        target_work_order_id=wo["id"],
        boundary="retain_existing",
        retained_quantity="1",
        evidence="all accepted old units retained",
    )
    assert not result["exchange_id"] and result["object_type"] == "eco"
    workflow.command(
        p["id"], "eco.close", actor_name="engineering", eco_id=eco["object_id"]
    )
    value = workflow.object(p["id"], "eco", eco["object_id"])
    assert value["state"] == "closed" and value["implementation_outcome"] == "retained"
    assert value["retentions"][0]["unit_ids"] == units
    assert authority.operation_count() == before


@pytest.mark.parametrize("reserved,expected_delta", [("100", "0"), ("40", "60")])
def test_i1_late_receipt_import_deduplicates_exact_or_partial_authority_coverage(
    workflow, reserved, expected_delta
):
    from decimal import Decimal

    from .test_exchanges import act, reserve, stock

    p, _req, supply, intent = reserve(workflow, quantity=reserved)
    stock(workflow, p, supply)
    act(workflow, p, intent)
    eco = workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=supply["revision_id"],
        effective_work_order_ids=[supply["work_order_id"]],
        reason="receipt overlap",
    )
    dispose_all(workflow, p, eco["object_id"])
    workflow.command(
        p["id"],
        "source.pull",
        actor_name="supply",
        system="erp",
        object_type="receipt",
        external_id="delivery-1",
    )
    view = workflow.object(p["id"], "eco", eco["object_id"])
    assert sum(
        Decimal(i["quantity"]) - Decimal(i["resolved_quantity"])
        for i in view["impacts"]
        if i["type"] == "stock"
    ) == Decimal(expected_delta)
    assert not view["unresolved_stock_basis_ids"]
    workflow.command(
        p["id"],
        "source.pull",
        actor_name="supply",
        system="erp",
        object_type="receipt",
        external_id="delivery-1",
    )
    assert (
        workflow.object(p["id"], "eco", eco["object_id"])["impacts"] == view["impacts"]
    )


@pytest.mark.parametrize(
    "invalid",
    [
        "project",
        "lot",
        "owner",
        "unit",
        "duplicate",
        "coverage",
        "source_quantity",
        "foreign_identity",
    ],
)
def test_i1_invalid_reservation_basis_is_never_admitted_or_displayed(
    workflow, monkeypatch, invalid
):
    from decimal import Decimal
    from uuid import uuid4

    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    from .test_exchanges import act, reserve, stock

    p, _req, supply, intent = reserve(workflow)
    stock(workflow, p, supply)
    _foreign, _, foreign_supply = workflow.material_requirement(
        required="1", qualified="1"
    )
    with workflow.db() as tx:
        foreign = tx.execute(
            "SELECT source_external_id FROM supply_receipts WHERE material_lot_id=?",
            (foreign_supply["lot_id"],),
        ).fetchone()[0]
    original = MockAuthorityAdapter.submit

    def corrupt(adapter, request):
        receipt = original(adapter, request)
        basis = receipt.details[0].stock_basis[0]
        if invalid == "project":
            basis.project_id = uuid4()
        if invalid == "lot":
            basis.lot_id = uuid4()
        if invalid == "owner":
            basis.owner_id = "wrong-owner"
        if invalid == "unit":
            basis.unit = "piece"
        if invalid == "duplicate":
            receipt.details[0].stock_basis.append(basis.model_copy())
        if invalid == "coverage":
            basis.quantity = Decimal(79)
        if invalid == "source_quantity":
            basis.source_quantity = Decimal(1)
        if invalid == "foreign_identity":
            basis.external_id = foreign
        return receipt

    monkeypatch.setattr(MockAuthorityAdapter, "submit", corrupt)
    act(workflow, p, intent)
    value = workflow.object(p["id"], "exchange", intent["exchange_id"])
    assert value["phase"] == "rejected" and value["receipt"] is None
    with workflow.db() as tx:
        assert (
            tx.execute(
                "SELECT confirmed_atoms FROM reservations WHERE exchange_id=?",
                (intent["exchange_id"],),
            ).fetchone()[0]
            == 0
        )


def test_i1_legacy_basis_absence_preserves_bytes_and_blocks_ambiguous_stock_closure(
    workflow, monkeypatch
):
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter
    from manufacturing_platform.workflow.exchange_models import ExternalReceipt

    from .test_exchanges import act, reserve, stock

    p, _req, supply, intent = reserve(workflow)
    stock(workflow, p, supply)
    original = MockAuthorityAdapter.submit

    def legacy(adapter, request):
        receipt = original(adapter, request)
        receipt.details[0].stock_basis = None
        old = receipt.model_dump_json()
        assert "stock_basis" not in old
        assert ExternalReceipt.model_validate_json(old).model_dump_json() == old
        return receipt

    monkeypatch.setattr(MockAuthorityAdapter, "submit", legacy)
    act(workflow, p, intent)
    eco = workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=supply["revision_id"],
        effective_work_order_ids=[supply["work_order_id"]],
        reason="legacy overlap held",
    )
    dispose_all(workflow, p, eco["object_id"])
    assert workflow.object(p["id"], "eco", eco["object_id"])[
        "unresolved_stock_basis_ids"
    ]
    result = workflow.command(
        p["id"],
        "eco.close",
        actor_name="engineering",
        eco_id=eco["object_id"],
        expected_status=409,
    )
    assert result["fields"]["unresolved_stock_basis_ids"]


def test_i1_admitted_receipt_correction_appends_quantity_without_rewriting_prior_disposition(
    workflow,
):
    from decimal import Decimal

    from .test_exchanges import reserve, stock

    p, _req, supply, _intent = reserve(workflow)
    stock(workflow, p, supply)
    workflow.receive(
        p["id"],
        supply["id"],
        quantity="80",
        lot_id=supply["lot_id"],
        source=workflow.source("delivery-1", object_type="receipt"),
    )
    eco = workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=supply["revision_id"],
        effective_work_order_ids=[supply["work_order_id"]],
        reason="correct receipt",
    )
    dispose_all(workflow, p, eco["object_id"])
    pull = workflow.command(
        p["id"],
        "source.pull",
        actor_name="supply",
        system="erp",
        object_type="receipt",
        external_id="delivery-1",
    )
    workflow.command(
        p["id"],
        "exchange.reconcile",
        actor_name="supply",
        exchange_id=pull["exchange_id"],
        source=workflow.source("delivery-1", object_type="receipt"),
        object_type="receipt",
        source_version=1,
        details=[],
        resolution="accept_authority",
        evidence="actual 100kg confirmed",
    )
    view = workflow.object(p["id"], "eco", eco["object_id"])
    assert sum(
        Decimal(i["quantity"]) - Decimal(i["resolved_quantity"])
        for i in view["impacts"]
        if i["type"] == "stock"
    ) == Decimal(20)
    with workflow.db() as tx:
        assert (
            tx.execute(
                "SELECT q_atoms FROM supply_receipts WHERE material_lot_id=?",
                (supply["lot_id"],),
            ).fetchone()[0]
            == 80000
        )


@pytest.mark.parametrize(
    "state", ["unstarted", "unknown", "partial", "wrong_quantity", "foreign"]
)
def test_i2_retained_boundary_rejects_unproven_or_incomplete_membership(
    workflow, state
):
    from .test_execution import ready_for_trial

    p, wo, units, authority = ready_for_trial(
        workflow, quantity="2" if state == "partial" else "1"
    )
    if state not in {"unstarted", "foreign"}:
        start = workflow.command(
            p["id"],
            "production.start",
            actor_name="production",
            work_order_id=wo["id"],
            mode="trial",
            unit_ids=units[:1],
            quantity="1",
        )
        if state == "unknown":
            authority.configure_fault("timeout_after_commit")
        workflow.command(
            p["id"],
            "exchange.dispatch",
            actor_name="production",
            exchange_id=start["exchange_id"],
        )
    old = workflow.object(p["id"], "work_order", wo["id"])
    eco = workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=old["revision_id"],
        effective_work_order_ids=[wo["id"]],
        reason="retained scope guard",
    )
    dispose_all(workflow, p, eco["object_id"])
    if state == "foreign":
        _, _, wo, _ = workflow.order_workorder()
    workflow.command(
        p["id"],
        "eco.switch",
        actor_name="engineering",
        expected_status=404 if state == "foreign" else 409,
        eco_id=eco["object_id"],
        target_work_order_id=wo["id"],
        boundary="retain_existing",
        retained_quantity="2" if state in {"partial", "wrong_quantity"} else "1",
        evidence="must prove exact membership",
    )
    assert (
        workflow.object(p["id"], "eco", eco["object_id"])["implementation_outcome"]
        == "pending"
    )


def test_i1_arrival_consumed_before_review_still_needs_disposition(workflow):
    from decimal import Decimal

    from .test_execution import running_execution

    p, wo, _units, _authority, event = running_execution(workflow)
    old = workflow.object(p["id"], "work_order", wo["id"])
    eco = workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=old["revision_id"],
        effective_work_order_ids=[wo["id"]],
        reason="arrival consumed before review",
    )
    dispose_all(workflow, p, eco["object_id"])
    with workflow.db() as tx:
        req = tx.execute(
            "SELECT id FROM requirements WHERE work_order_id=? LIMIT 1", (wo["id"],)
        ).fetchone()[0]
    commitment = workflow.command(
        p["id"],
        "supply.commit",
        actor_name="supply",
        requirement_id=req,
        type="customer",
        owner_id="Customer 1",
        quantity="1",
        unit="kg",
        original_due="2026-12-01",
        current_due="2026-12-01",
        source=workflow.source("consumed-arrival-promise", object_type="commitment"),
    )
    workflow.receive(
        p["id"],
        commitment["object_id"],
        quantity="0.1",
        lot_id=event["material_uses"][0]["lot_id"],
    )
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=workflow.source("consumed-new-arrival", object_type="execution"),
        **event,
    )
    view = workflow.object(p["id"], "eco", eco["object_id"])
    assert sum(
        Decimal(i["quantity"]) - Decimal(i["resolved_quantity"])
        for i in view["impacts"]
        if i["type"] == "stock"
    ) == Decimal("0.1")


def test_i2_legacy_switch_command_hash_omits_new_retention_field():
    from uuid import uuid4

    from manufacturing_platform.workflow.eco_models import SwitchEco

    body = {
        "action": "eco.switch",
        "operation_id": str(uuid4()),
        "expected_version": 1,
        "eco_id": str(uuid4()),
        "target_work_order_id": str(uuid4()),
        "boundary": "cancel_remaining",
        "new_revision_id": None,
        "evidence": "original",
    }
    assert SwitchEco.model_validate(body).model_dump(mode="json") == body


def test_i1_zero_net_opening_keeps_receipt_basis_and_does_not_resurface_consumed_stock(
    workflow,
):
    from datetime import UTC, datetime
    from decimal import Decimal

    from .test_execution import review_article, running_execution

    p, wo, units, _authority, event = running_execution(workflow)
    review_article(workflow, p, wo, units[0])
    bulk = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="bulk",
        unit_ids=units[1:2],
        quantity="1",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=bulk["exchange_id"],
    )
    lot = event["material_uses"][0]["lot_id"]
    for n, uid in enumerate(units[:2]):
        workflow.command(
            p["id"],
            "execution.record",
            actor_name="production",
            source=workflow.source(f"zero-opening-{n}", object_type="execution"),
            **{
                **event,
                "sn": workflow.object(p["id"], "unit", uid)["sn"],
                "material_uses": [{"lot_id": lot, "quantity": "1", "unit": "kg"}],
                "occurred_at": datetime.now(UTC).isoformat(),
            },
        )
    old = workflow.object(p["id"], "work_order", wo["id"])
    eco = workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=old["revision_id"],
        effective_work_order_ids=[wo["id"]],
        reason="zero opening stock",
    )
    assert not [
        i
        for i in workflow.object(p["id"], "eco", eco["object_id"])["impacts"]
        if i["type"] == "stock"
    ]
    with workflow.db() as tx:
        req = tx.execute(
            "SELECT id FROM requirements WHERE work_order_id=? LIMIT 1", (wo["id"],)
        ).fetchone()[0]
        assert (
            tx.execute(
                "SELECT consumed_atoms FROM eco_stock_openings WHERE eco_id=?",
                (eco["object_id"],),
            ).fetchone()[0]
            == 2000
        )
    promise = workflow.command(
        p["id"],
        "supply.commit",
        actor_name="supply",
        requirement_id=req,
        type="customer",
        owner_id="Customer 1",
        quantity="1",
        unit="kg",
        original_due="2026-12-01",
        current_due="2026-12-01",
        source=workflow.source("zero-opening-promise", object_type="commitment"),
    )
    workflow.receive(p["id"], promise["object_id"], quantity="0.1", lot_id=lot)
    current = workflow.object(p["id"], "eco", eco["object_id"])
    assert sum(
        Decimal(i["quantity"]) for i in current["impacts"] if i["type"] == "stock"
    ) == Decimal("0.1")


def test_i1_stock_basis_read_contract_uses_decimal_strings(workflow):
    p, eco, _stock = workflow.open_eco_with_stock()
    view = workflow.object(p["id"], "eco", eco["id"])
    stock = next(i for i in view["impacts"] if i["type"] == "stock")
    assert set(stock["stock_basis"].values()) == {"80"}
    assert stock["opening_consumption"] == "0"


@pytest.mark.parametrize("boundary", ["cancel_remaining", "split_remaining"])
def test_i4_later_eco_retains_current_old_scope_after_confirmed_boundary(
    workflow, boundary
):
    from .test_execution import ready_for_trial

    p, wo, units, authority = ready_for_trial(workflow, quantity="5")
    pid, wid = p["id"], wo["id"]
    start = workflow.command(
        pid,
        "production.start",
        actor_name="production",
        work_order_id=wid,
        mode="trial",
        unit_ids=units[:1],
        quantity="1",
    )
    workflow.command(
        pid,
        "exchange.dispatch",
        actor_name="production",
        exchange_id=start["exchange_id"],
    )
    original = workflow.object(pid, "work_order", wid)
    target = {}
    if boundary == "split_remaining":
        new = workflow.revision(pid, internal_revision="M2")
        workflow.command(
            pid,
            "engineering.handoff",
            actor_name="engineering",
            revision_id=new["id"],
            to_system="MES",
            received_revision="M2",
            decision="accepted",
            evidence="MES M2",
        )
        workflow.command(
            pid,
            "engineering.customer_approval",
            revision_id=new["id"],
            customer_id="Customer 1",
            external_signatory="customer",
            decision="approved",
            evidence="M2 approval",
        )
        target = {"new_revision_id": new["id"]}
    first = workflow.command(
        pid,
        "eco.open",
        actor_name="engineering",
        old_revision_id=original["revision_id"],
        effective_work_order_ids=[wid],
        reason="first actual boundary",
        **target,
    )["object_id"]
    effect = workflow.command(
        pid,
        "eco.switch",
        actor_name="engineering",
        eco_id=first,
        target_work_order_id=wid,
        boundary=boundary,
        evidence="retain started one",
        **target,
    )
    authority.configure_fault("timeout_after_commit")
    workflow.command(
        pid,
        "exchange.dispatch",
        actor_name="engineering",
        exchange_id=effect["exchange_id"],
    )
    later = workflow.command(
        pid,
        "eco.open",
        actor_name="engineering",
        old_revision_id=original["revision_id"],
        effective_work_order_ids=[wid],
        reason="later old scope review",
    )["object_id"]
    dispose_all(workflow, p, later)
    # Actual source effect exists but local receipt is unknown: neither quantity may bypass the hold.
    for quantity in ("1", "5"):
        workflow.command(
            pid,
            "eco.switch",
            actor_name="engineering",
            eco_id=later,
            target_work_order_id=wid,
            boundary="retain_existing",
            retained_quantity=quantity,
            evidence="unknown effect cannot authorize retention",
            expected_status=409,
        )
    assert workflow.object(pid, "work_order", wid)["remaining_obligation"] == "5"
    workflow.command(
        pid,
        "exchange.query",
        actor_name="engineering",
        exchange_id=effect["exchange_id"],
    )
    dispose_all(workflow, p, first)
    workflow.command(pid, "eco.close", actor_name="engineering", eco_id=first)
    assert workflow.object(pid, "work_order", wid)["remaining_obligation"] == "1"
    later = workflow.command(
        pid,
        "eco.open",
        actor_name="engineering",
        old_revision_id=original["revision_id"],
        effective_work_order_ids=[wid],
        reason="review confirmed residual old scope",
    )["object_id"]
    dispose_all(workflow, p, later)
    later_value = workflow.object(pid, "eco", later)
    assert (
        next(
            i["quantity"]
            for i in later_value["impacts"]
            if i["type"] == "work_order" and i["object_id"] == wid
        )
        == "1"
    )
    prior_eco = workflow.object(pid, "eco", first)
    with workflow.db() as tx:
        prior_switches = [
            tuple(r)
            for r in tx.execute("SELECT * FROM eco_switches WHERE project_id=?", (pid,))
        ]
        prior_units = [
            tuple(r)
            for r in tx.execute(
                "SELECT * FROM units WHERE project_id=? ORDER BY id", (pid,)
            )
        ]
    with authority.store.transaction() as tx:
        prior_authority = [
            tuple(r)
            for r in tx.execute(
                "SELECT * FROM authority_work_orders WHERE project_id=? ORDER BY work_order_id",
                (pid,),
            )
        ]
    before = authority.operation_count()
    # Immutable original registration is no longer the current retention quantity.
    workflow.command(
        pid,
        "eco.switch",
        actor_name="engineering",
        eco_id=later,
        target_work_order_id=wid,
        boundary="retain_existing",
        retained_quantity="5",
        evidence="wrong original quantity",
        expected_status=409,
    )
    retained = workflow.command(
        pid,
        "eco.switch",
        actor_name="engineering",
        eco_id=later,
        target_work_order_id=wid,
        boundary="retain_existing",
        retained_quantity="1",
        evidence="current accepted old scope retained",
    )
    assert not retained["exchange_id"]
    workflow.command(pid, "eco.close", actor_name="engineering", eco_id=later)
    current = workflow.object(pid, "eco", later)
    assert (
        current["state"] == "closed" and current["implementation_outcome"] == "retained"
    )
    assert current["retentions"][0]["quantity"] == "1"
    assert current["retentions"][0]["unit_ids"] == units[:1]
    assert workflow.object(pid, "eco", first) == prior_eco
    current_wo = workflow.object(pid, "work_order", wid)
    assert current_wo["quantity"] == original["quantity"] == "5"
    assert current_wo["revision_id"] == original["revision_id"]
    assert current_wo["order_line_id"] == original["order_line_id"]
    assert authority.operation_count() == before
    with workflow.db() as tx:
        assert [
            tuple(r)
            for r in tx.execute("SELECT * FROM eco_switches WHERE project_id=?", (pid,))
        ] == prior_switches
        assert [
            tuple(r)
            for r in tx.execute(
                "SELECT * FROM units WHERE project_id=? ORDER BY id", (pid,)
            )
        ] == prior_units
    with authority.store.transaction() as tx:
        assert [
            tuple(r)
            for r in tx.execute(
                "SELECT * FROM authority_work_orders WHERE project_id=? ORDER BY work_order_id",
                (pid,),
            )
        ] == prior_authority
