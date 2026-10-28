"""ECO boundaries exercised through public commands and two durable stores."""

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
        assert tx.execute("SELECT version FROM schema_version").fetchone()[0] == 9


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
