"""B3 execution through the public API and the independent authority boundary."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Event, Thread
from uuid import uuid4

import pytest

from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter
from manufacturing_platform.workflow.exchange_models import StartPayload


def test_authority_start_payload_rejects_duplicate_normalized_serials():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        StartPayload(
            start_id=uuid4(),
            work_order_id=uuid4(),
            revision_id=uuid4(),
            mode="trial",
            work_order_quantity=5,
            trial_quantity=2,
            units=[(uuid4(), "ＡＢＣ"), (uuid4(), "ABC")],
        )


def ready_for_trial(workflow, *, quantity="5", trial_quantity="1"):
    contract = {
        "customer_approval_required": True,
        "customer_release_required": "unknown",
        "acceptance_required": "unknown",
        "customer_revision": "C1",
        "internal_revision": "M1",
        "material_ownership_rules": "Customer 1 owns steel-1",
    }
    p, order, wo, rev = workflow.order_workorder(quantity=quantity, trial_quantity=trial_quantity, contract=contract)
    workflow.command(
        p["id"],
        "engineering.customer_approval",
        revision_id=rev["id"],
        customer_id="Customer 1",
        external_signatory="Customer QE",
        decision="approved",
        evidence="signed C1 approval",
    )
    workflow.grant(p["id"], "production", ["production"])
    workflow.grant(p["id"], "supply", ["supply"])
    now = datetime.now(UTC)
    for kind in ("equipment", "people"):
        workflow.command(
            p["id"],
            "readiness.record",
            actor_name="engineering",
            work_order_id=wo["id"],
            kind=kind,
            reference=f"{kind}-1",
            evidence=f"{kind} verified",
            decision="verified",
            valid_until=(now + timedelta(days=90)).isoformat(),
        )
    lot = workflow.command(
        p["id"],
        "material.define",
        actor_name="supply",
        material_id="steel-1",
        lot_id="lot-1",
        owner_id="Customer 1",
        unit="kg",
        scale=3,
        expiry=(now + timedelta(days=120)).date().isoformat(),
        source=workflow.source(f"lot-{uuid4()}", object_type="material_lot"),
    )["object_id"]
    source = workflow.source(f"plan-{uuid4()}", object_type="plan")
    source.update(
        occurred_at=(now - timedelta(minutes=2)).isoformat(),
        collected_at=(now - timedelta(minutes=1)).isoformat(),
        cutoff=(now - timedelta(minutes=2)).isoformat(),
    )
    with workflow.db() as db:
        order_version = db.execute(
            "SELECT source_version FROM order_lines WHERE id=?", (order["id"],)
        ).fetchone()[0]
    plan = workflow.command(
        p["id"],
        "plan.receive",
        actor_name="planner",
        source=source,
        input_revision_ids=[rev["id"]],
        input_order_versions=[{"order_line_id": order["id"], "version": order_version}],
        requirements=[
            {
                "work_order_id": wo["id"],
                "execution_scope": scope,
                "material_id": "steel-1",
                "owner_id": "Customer 1",
                "quantity": "1",
                "unit": "kg",
            }
            for scope in ("trial", "bulk")
        ],
    )
    reqs = workflow.object(p["id"], "plan", plan["object_id"])["requirement_ids"]
    authority = MockAuthorityAdapter(str(workflow.paths.authority), "workflow-test")
    authority.receive(
        project_id=p["id"],
        external_id=f"receipt-{uuid4()}",
        commitment_id=str(uuid4()),
        lot_id=lot,
        material_id="steel-1",
        owner_id="Customer 1",
        quantity="2",
        unit="kg",
        scale=3,
        expiry=(now + timedelta(days=120)).date().isoformat(),
        external_actor="WMS",
        signature="signed delivery",
    )
    # IQC references the actual external receipt identity above.
    with authority.store.transaction() as tx:
        receipt_external = tx.execute(
            "SELECT external_id FROM source_events WHERE object_type='receipt' ORDER BY seq DESC LIMIT 1"
        ).fetchone()[0]
    authority.inspect(
        project_id=p["id"],
        external_id=f"iqc-{uuid4()}",
        receipt_external_id=receipt_external,
        accepted="2",
        rejected="0",
        external_actor="QMS",
        signature="signed inspection",
    )
    for req in reqs:
        intent = workflow.command(
            p["id"],
            "reservation.request",
            actor_name="planner",
            work_order_id=wo["id"],
            requirement_id=req,
            lot_id=lot,
            quantity="1",
            unit="kg",
        )
        workflow.command(
            p["id"],
            "exchange.dispatch",
            actor_name="planner",
            exchange_id=intent["exchange_id"],
        )
        assert (
            workflow.object(p["id"], "exchange", intent["exchange_id"])["phase"]
            == "accepted"
        )
    workflow.command(
        p["id"],
        "unit.register",
        actor_name="production",
        work_order_id=wo["id"],
        sns=[f"B3-{uuid4()}" for _ in range(int(quantity))],
    )
    units = (
        workflow.client()
        .get(
            f"/api/v1/manufacturing/workflow/projects/{p['id']}/objects/unit?limit=50&offset=0"
        )
        .json()["items"]
    )
    return p, wo, [u["id"] for u in units], authority


def test_trial_starts_without_first_article_and_bulk_waits(workflow):
    p, wo, unit_ids, authority = ready_for_trial(workflow)
    trial = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=unit_ids[:1],
        quantity="1",
    )
    assert trial["exchange_id"]
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=trial["exchange_id"],
    )
    assert (
        workflow.object(p["id"], "exchange", trial["exchange_id"])["phase"]
        == "accepted"
    )
    blocked = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        expected_status=409,
        work_order_id=wo["id"],
        mode="bulk",
        unit_ids=unit_ids[1:],
        quantity="4",
    )
    assert "first_article" in str(blocked["blocking_reasons"])
    assert authority.operation_count(trial["exchange_id"]) == 1


def test_pending_start_holds_sn_and_trial_budget(workflow):
    p, wo, units, _ = ready_for_trial(workflow)
    uid = units[0]
    workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=[uid],
        quantity="1",
    )
    blocked = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        expected_status=409,
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=[uid],
        quantity="1",
    )
    assert blocked["blocking_reasons"]


def test_serial_identity_is_dataset_unique_and_registration_is_whole_work_order_bounded(
    workflow,
):
    p, wo, units, _ = ready_for_trial(workflow)
    sn = workflow.object(p["id"], "unit", units[0])["sn"]
    assert workflow.command(
        p["id"],
        "unit.register",
        actor_name="production",
        expected_status=409,
        work_order_id=wo["id"],
        sns=["SN-extra"],
    )["blocking_reasons"]
    p2, _, wo2, _ = workflow.order_workorder(quantity="5")
    workflow.grant(p2["id"], "production", ["production"])
    assert workflow.command(
        p2["id"],
        "unit.register",
        actor_name="production",
        expected_status=409,
        work_order_id=wo2["id"],
        sns=[sn.lower()],
    )["blocking_reasons"]
    assert (
        workflow.client()
        .get(
            f"/api/v1/manufacturing/workflow/projects/{p2['id']}/objects/unit?limit=50&offset=0"
        )
        .json()["total"]
        == 0
    )


def test_serial_normalization_rejects_compatibility_alias_across_projects(workflow):
    p1, _, wo1, _ = workflow.order_workorder(quantity="5")
    p2, _, wo2, _ = workflow.order_workorder(quantity="5")
    for p in (p1, p2):
        workflow.grant(p["id"], "production", ["production"])
    workflow.command(
        p1["id"],
        "unit.register",
        actor_name="production",
        work_order_id=wo1["id"],
        sns=["ＡＢＣ-001"],
    )
    assert workflow.command(
        p2["id"],
        "unit.register",
        actor_name="production",
        expected_status=409,
        work_order_id=wo2["id"],
        sns=["ABC-001"],
    )["blocking_reasons"]


def test_start_apply_rechecks_live_readiness_after_authority_commits(
    workflow, monkeypatch
):
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
    entered, release = Event(), Event()
    original_submit = MockAuthorityAdapter.submit

    def held_submit(adapter, request):
        if request.action == "production.start":
            entered.set()
            assert release.wait(5), "MES release barrier timed out"
        return original_submit(adapter, request)

    monkeypatch.setattr(MockAuthorityAdapter, "submit", held_submit)
    outcomes = []
    dispatch = Thread(
        target=lambda: outcomes.append(
            workflow.command(
                p["id"],
                "exchange.dispatch",
                actor_name="production",
                expected_status=409,
                exchange_id=start["exchange_id"],
            )
        )
    )
    dispatch.start()
    assert entered.wait(5), "MES submit barrier was not reached"
    workflow.command(
        p["id"],
        "readiness.record",
        actor_name="engineering",
        work_order_id=wo["id"],
        kind="equipment",
        reference="cal-1",
        evidence="calibration revoked",
        valid_until=(datetime.now(UTC) + timedelta(days=90)).isoformat(),
        decision="rejected",
    )
    release.set()
    dispatch.join(5)
    assert not dispatch.is_alive()
    assert outcomes and outcomes[0]["code"] == "VERSION_CONFLICT"
    assert authority.operation_count(start["exchange_id"]) == 1
    workflow.command(
        p["id"],
        "exchange.query",
        actor_name="production",
        exchange_id=start["exchange_id"],
    )
    held = workflow.object(p["id"], "unit", units[0])
    assert held["state"] == "start_pending"
    assert held["accepted_start_id"]
    assert held["authority_start_accepted"] is True
    unit_page = (
        workflow.client()
        .get(
            f"/api/v1/manufacturing/workflow/projects/{p['id']}/objects/unit?limit=50&offset=0"
        )
        .json()
    )
    assert (
        next(u for u in unit_page["items"] if u["id"] == units[0])["state"]
        == "mes_accepted_held"
    )
    assert (
        workflow.object(p["id"], "exchange", start["exchange_id"])["phase"]
        == "accepted"
    )
    assert (
        workflow.object(p["id"], "work_order", wo["id"])["held_start_scopes"][0]["id"]
        == held["accepted_start_id"]
    )
    workflow.command(
        p["id"],
        "exchange.query",
        actor_name="production",
        exchange_id=start["exchange_id"],
    )
    assert workflow.object(p["id"], "unit", units[0])["state"] == "start_pending"
    assert authority.operation_count(start["exchange_id"]) == 1

    assert workflow.command(
        p["id"],
        "production.interrupt",
        actor_name="production",
        expected_status=409,
        work_order_id=wo["id"],
        start_id=str(uuid4()),
        kind="S4",
        reason="wrong held scope",
    )["blocking_reasons"]

    stop = workflow.command(
        p["id"],
        "production.interrupt",
        actor_name="production",
        work_order_id=wo["id"],
        start_id=held["accepted_start_id"],
        kind="S4",
        reason="MES accepted while calibration revoked",
    )
    assert (
        workflow.object(p["id"], "interruption", stop["object_id"])["recovery_start_id"]
        == held["accepted_start_id"]
    )
    assert workflow.object(p["id"], "unit", units[0])["state"] == "start_pending"
    authority.configure_fault("reject")
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=stop["exchange_id"],
    )
    assert workflow.object(p["id"], "unit", units[0])["state"] == "start_pending"
    assert (
        workflow.object(p["id"], "interruption", stop["object_id"])[
            "authority_stopped_at"
        ]
        is None
    )
    assert authority.operation_count(stop["exchange_id"]) == 1
    authority.configure_fault("none")
    stop = workflow.command(
        p["id"],
        "production.interrupt",
        actor_name="production",
        work_order_id=wo["id"],
        start_id=held["accepted_start_id"],
        interruption_id=stop["object_id"],
        kind="S4",
        reason="MES accepted while calibration revoked",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=stop["exchange_id"],
    )
    assert workflow.object(p["id"], "unit", units[0])["state"] == "stopped"
    assert authority.operation_count(stop["exchange_id"]) == 1
    with authority.store.transaction() as tx:
        actual = tx.execute(
            "SELECT started_units,started_trial,state FROM authority_work_orders WHERE project_id=? AND work_order_id=?",
            (p["id"], wo["id"]),
        ).fetchone()
        assert tuple(actual) == (1, 1, "stopped")
    assert workflow.command(
        p["id"],
        "production.resume",
        actor_name="production",
        expected_status=409,
        interruption_id=stop["object_id"],
        plan_id=workflow.object(p["id"], "work_order", wo["id"])["trial_readiness"][
            "input_versions"
        ]["plan_id"],
        evidence="old plan",
    )["blocking_reasons"]
    workflow.command(
        p["id"],
        "readiness.record",
        actor_name="engineering",
        work_order_id=wo["id"],
        kind="equipment",
        reference="cal-2",
        evidence="new calibration",
        valid_until=(datetime.now(UTC) + timedelta(days=90)).isoformat(),
        decision="verified",
    )
    now = datetime.now(UTC)
    with workflow.db() as db:
        basis = db.execute(
            "SELECT order_line_id,revision_id FROM work_orders WHERE id=?", (wo["id"],)
        ).fetchone()
        order_version = db.execute(
            "SELECT source_version FROM order_lines WHERE id=?", (basis[0],)
        ).fetchone()[0]
        lot_id = db.execute(
            "SELECT id FROM material_lots WHERE project_id=? LIMIT 1", (p["id"],)
        ).fetchone()[0]
    source = workflow.source(f"held-replan-{uuid4()}", object_type="plan")
    source.update(
        occurred_at=(now - timedelta(minutes=2)).isoformat(),
        collected_at=(now - timedelta(minutes=1)).isoformat(),
        cutoff=(now - timedelta(minutes=2)).isoformat(),
    )
    plan = workflow.command(
        p["id"],
        "plan.receive",
        actor_name="planner",
        source=source,
        input_revision_ids=[basis[1]],
        input_order_versions=[{"order_line_id": basis[0], "version": order_version}],
        requirements=[
            {
                "work_order_id": wo["id"],
                "execution_scope": scope,
                "material_id": "steel-1",
                "owner_id": "Customer 1",
                "quantity": qty,
                "unit": "kg",
            }
            for scope, qty in (("trial", "2"), ("bulk", "1"))
        ],
    )
    assert workflow.command(
        p["id"],
        "production.resume",
        actor_name="production",
        expected_status=409,
        interruption_id=stop["object_id"],
        plan_id=plan["object_id"],
        evidence="stock short",
    )["blocking_reasons"]
    ext = f"held-topup-{uuid4()}"
    authority.receive(
        project_id=p["id"],
        external_id=ext,
        commitment_id=str(uuid4()),
        lot_id=lot_id,
        material_id="steel-1",
        owner_id="Customer 1",
        quantity="1",
        unit="kg",
        scale=3,
        expiry=(now + timedelta(days=120)).date().isoformat(),
        external_actor="WMS",
        signature="signed topup",
    )
    authority.inspect(
        project_id=p["id"],
        external_id=f"held-iqc-{uuid4()}",
        receipt_external_id=ext,
        accepted="1",
        rejected="0",
        external_actor="QMS",
        signature="signed inspection",
    )
    with workflow.db() as db:
        trial_req = db.execute(
            "SELECT id FROM requirements WHERE plan_id=? AND execution_scope='trial'",
            (plan["object_id"],),
        ).fetchone()[0]
    reserve = workflow.command(
        p["id"],
        "reservation.request",
        actor_name="planner",
        work_order_id=wo["id"],
        requirement_id=trial_req,
        lot_id=lot_id,
        quantity="1",
        unit="kg",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="planner",
        exchange_id=reserve["exchange_id"],
    )
    resume = workflow.command(
        p["id"],
        "production.resume",
        actor_name="production",
        interruption_id=stop["object_id"],
        plan_id=plan["object_id"],
        evidence="new plan, calibration and stock verified",
    )
    assert workflow.object(p["id"], "unit", units[0])["state"] == "stopped"
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=resume["exchange_id"],
    )
    assert workflow.object(p["id"], "unit", units[0])["state"] == "running"
    assert (
        workflow.object(p["id"], "unit", units[0])["accepted_start_id"]
        == held["accepted_start_id"]
    )
    assert authority.operation_count(resume["exchange_id"]) == 1
    with authority.store.transaction() as tx:
        actual = tx.execute(
            "SELECT started_units,started_trial,state FROM authority_work_orders WHERE project_id=? AND work_order_id=?",
            (p["id"], wo["id"]),
        ).fetchone()
        assert tuple(actual) == (1, 1, "running")
    assert authority.operation_count(start["exchange_id"]) == 1


def test_known_unready_start_is_not_submitted_after_authority_query(workflow):
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
    workflow.command(
        p["id"],
        "readiness.record",
        actor_name="engineering",
        work_order_id=wo["id"],
        kind="equipment",
        reference="cal-revoked",
        evidence="calibration revoked",
        valid_until=(datetime.now(UTC) + timedelta(days=90)).isoformat(),
        decision="rejected",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=start["exchange_id"],
    )
    assert authority.operation_count(start["exchange_id"]) == 0
    assert workflow.object(p["id"], "unit", units[0])["state"] == "start_pending"
    assert workflow.object(p["id"], "unit", units[0])["accepted_start_id"] is None
    workflow.command(
        p["id"],
        "readiness.record",
        actor_name="engineering",
        work_order_id=wo["id"],
        kind="equipment",
        reference="cal-restored",
        evidence="calibration restored",
        valid_until=(datetime.now(UTC) + timedelta(days=90)).isoformat(),
        decision="verified",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=start["exchange_id"],
    )
    assert authority.operation_count(start["exchange_id"]) == 1
    assert workflow.object(p["id"], "unit", units[0])["state"] == "running"


def test_lost_start_reply_keeps_trial_budget_until_query_recovers_one_authority_start(
    workflow,
):
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
    assert (
        workflow.object(p["id"], "exchange", start["exchange_id"])["phase"] == "unknown"
    )
    assert workflow.object(p["id"], "unit", units[0])["state"] == "start_pending"
    assert workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        expected_status=409,
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=units[1:2],
        quantity="1",
    )["blocking_reasons"]
    workflow.reopen()
    workflow.command(
        p["id"],
        "exchange.query",
        actor_name="production",
        exchange_id=start["exchange_id"],
    )
    assert workflow.object(p["id"], "unit", units[0])["state"] == "running"
    assert authority.operation_count(start["exchange_id"]) == 1


@pytest.mark.parametrize(
    "fault", ["stale_sequence", "wrong_unit", "changed_detail_same_total"]
)
def test_invalid_start_receipt_keeps_source_scope_unknown_and_budget_held(
    workflow, fault
):
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
    authority.configure_fault(fault)
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=start["exchange_id"],
    )
    assert workflow.object(p["id"], "unit", units[0])["state"] == "start_pending"
    assert (
        workflow.object(p["id"], "exchange", start["exchange_id"])["phase"]
        == "rejected"
    )
    assert workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        expected_status=409,
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=units[1:2],
        quantity="1",
    )["blocking_reasons"]
    assert authority.operation_count(start["exchange_id"]) == 1


def test_rejected_mes_stop_can_be_reattempted_on_same_interruption(workflow):
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
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=start["exchange_id"],
    )
    authority.configure_fault("reject")
    stop = workflow.command(
        p["id"],
        "production.interrupt",
        actor_name="production",
        work_order_id=wo["id"],
        kind="S3",
        reason="material shortage",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=stop["exchange_id"],
    )
    assert (
        workflow.object(p["id"], "interruption", stop["object_id"])[
            "authority_stopped_at"
        ]
        is None
    )
    authority.configure_fault("none")
    retry = workflow.command(
        p["id"],
        "production.interrupt",
        actor_name="production",
        work_order_id=wo["id"],
        interruption_id=stop["object_id"],
        kind="S3",
        reason="material shortage",
    )
    assert (
        retry["object_id"] == stop["object_id"]
        and retry["exchange_id"] != stop["exchange_id"]
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=retry["exchange_id"],
    )
    detail = workflow.object(p["id"], "interruption", stop["object_id"])
    assert detail["authority_stopped_at"] and detail["stop_exchange_ids"] == [
        stop["exchange_id"],
        retry["exchange_id"],
    ]


def test_execution_rejects_wrong_source_route_and_duplicate_without_consumption(
    workflow,
):
    p, wo, units, _ = ready_for_trial(workflow)
    trial = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=units[:1],
        quantity="1",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=trial["exchange_id"],
    )
    unit = workflow.object(p["id"], "unit", units[0])
    base = {
        "work_order_id": wo["id"],
        "sn": unit["sn"],
        "station": "assembly",
        "route_version": "S1",
        "program_version": "P1",
        "firmware_version": "F1",
        "material_uses": [
            {
                "lot_id": workflow.client()
                .get(
                    f"/api/v1/manufacturing/workflow/projects/{p['id']}/objects/material_lot?limit=50&offset=0"
                )
                .json()["items"][0]["id"],
                "quantity": "0.1",
                "unit": "kg",
            }
        ],
        "result": "pass",
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    bad = workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=workflow.source(f"bad-{uuid4()}", object_type="execution"),
        **{**base, "program_version": "wrong"},
    )
    good_source = workflow.source(f"good-{uuid4()}", object_type="execution")
    good = workflow.command(
        p["id"], "execution.record", actor_name="production", source=good_source, **base
    )
    duplicate = workflow.command(
        p["id"], "execution.record", actor_name="production", source=good_source, **base
    )
    unknown_source = workflow.source(f"unknown-{uuid4()}", object_type="execution")
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=unknown_source,
        **{**base, "sn": "MISSING-SN"},
    )
    with workflow.db() as db:
        assert [
            r[0]
            for r in db.execute(
                "SELECT status FROM execution_events WHERE project_id=? ORDER BY accepted_seq",
                (p["id"],),
            )
        ] == ["rejected", "accepted", "rejected", "rejected"]
        assert (
            db.execute(
                "SELECT COUNT(*) FROM material_consumption WHERE project_id=?",
                (p["id"],),
            ).fetchone()[0]
            == 1
        )
    history = workflow.object(p["id"], "unit", units[0])["execution_events"]
    assert [event["status"] for event in history] == [
        "rejected",
        "accepted",
        "rejected",
    ]
    assert history[1]["material_uses"][0]["owner_id"] == "Customer 1"
    assert history[1]["source"]["external_id"] == good_source["external_id"]
    assert any(
        e["claimed_sn"] == "MISSING-SN" and e["status"] == "rejected"
        for e in workflow.object(p["id"], "work_order", wo["id"])["execution_events"]
    )
    assert bad["object_id"] == good["object_id"] == duplicate["object_id"] == units[0]


def test_execution_aggregate_material_overreport_is_rejected(workflow):
    p, wo, units, _ = ready_for_trial(workflow)
    trial = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=units[:1],
        quantity="1",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=trial["exchange_id"],
    )
    with workflow.db() as db:
        sn = db.execute("SELECT sn FROM units WHERE id=?", (units[0],)).fetchone()[0]
        lot_id = db.execute(
            "SELECT id FROM material_lots WHERE project_id=? LIMIT 1", (p["id"],)
        ).fetchone()[0]
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=workflow.source(f"over-{uuid4()}", object_type="execution"),
        work_order_id=wo["id"],
        sn=sn,
        station="assembly",
        route_version="S1",
        program_version="P1",
        firmware_version="F1",
        material_uses=[
            {"lot_id": lot_id, "quantity": "0.6", "unit": "kg"},
            {"lot_id": lot_id, "quantity": "0.6", "unit": "kg"},
        ],
        result="pass",
        occurred_at=datetime.now(UTC).isoformat(),
    )
    with workflow.db() as db:
        assert (
            db.execute(
                "SELECT status FROM execution_events WHERE project_id=? ORDER BY accepted_seq DESC LIMIT 1",
                (p["id"],),
            ).fetchone()[0]
            == "rejected"
        )
        assert (
            db.execute(
                "SELECT COUNT(*) FROM material_consumption WHERE project_id=?",
                (p["id"],),
            ).fetchone()[0]
            == 0
        )


def test_execution_material_precision_failure_retains_source_event(workflow):
    p, wo, units, _ = ready_for_trial(workflow)
    trial = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=units[:1],
        quantity="1",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=trial["exchange_id"],
    )
    with workflow.db() as db:
        sn = db.execute("SELECT sn FROM units WHERE id=?", (units[0],)).fetchone()[0]
        lot = db.execute(
            "SELECT id FROM material_lots WHERE project_id=? LIMIT 1", (p["id"],)
        ).fetchone()[0]
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=workflow.source(f"precision-{uuid4()}", object_type="execution"),
        work_order_id=wo["id"],
        sn=sn,
        station="assembly",
        route_version="S1",
        program_version="P1",
        firmware_version="F1",
        material_uses=[{"lot_id": lot, "quantity": "0.0001", "unit": "kg"}],
        result="pass",
        occurred_at=datetime.now(UTC).isoformat(),
    )
    history = workflow.object(p["id"], "unit", units[0])["execution_events"]
    assert history[0]["status"] == "rejected" and not history[0]["material_uses"]


def test_wrong_station_firmware_owner_and_source_are_retained_then_corrected(workflow):
    p, wo, units, _ = ready_for_trial(workflow)
    trial = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=units[:1],
        quantity="1",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=trial["exchange_id"],
    )
    with workflow.db() as db:
        sn = db.execute("SELECT sn FROM units WHERE id=?", (units[0],)).fetchone()[0]
        lot = db.execute(
            "SELECT id FROM material_lots WHERE project_id=? LIMIT 1", (p["id"],)
        ).fetchone()[0]
    other = workflow.command(
        p["id"],
        "material.define",
        actor_name="supply",
        material_id="copper",
        lot_id="other-owner",
        owner_id="Other",
        unit="kg",
        scale=3,
        expiry=(datetime.now(UTC) + timedelta(days=90)).date().isoformat(),
        source=workflow.source(f"other-{uuid4()}", object_type="material_lot"),
    )["object_id"]
    base = {
        "work_order_id": wo["id"],
        "sn": sn,
        "station": "assembly",
        "route_version": "S1",
        "program_version": "P1",
        "firmware_version": "F1",
        "material_uses": [{"lot_id": lot, "quantity": "0.1", "unit": "kg"}],
        "result": "pass",
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    attempts = [
        ({"station": "wrong"}, "manual"),
        ({"firmware_version": "wrong"}, "manual"),
        (
            {"material_uses": [{"lot_id": other, "quantity": "0.1", "unit": "kg"}]},
            "manual",
        ),
        ({}, "mock"),
    ]
    for change, mode in attempts:
        workflow.command(
            p["id"],
            "execution.record",
            actor_name="production",
            source=workflow.source(
                f"bad-{uuid4()}", object_type="execution", mode=mode
            ),
            **{**base, **change},
        )
    bad = workflow.object(p["id"], "unit", units[0])["execution_events"]
    assert [e["status"] for e in bad] == ["rejected"] * 4
    assert all(not e["material_uses"] for e in bad)
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=workflow.source(f"corrected-{uuid4()}", object_type="execution"),
        supersedes_event_id=bad[0]["id"],
        **base,
    )
    history = workflow.object(p["id"], "unit", units[0])["execution_events"]
    assert (
        history[-1]["status"] == "accepted"
        and history[-1]["supersedes_event_id"] == bad[0]["id"]
    )
    assert [e["status"] for e in history[:4]] == ["rejected"] * 4


def test_execution_source_cannot_claim_future_or_precollection_event(workflow):
    p, wo, units, _ = ready_for_trial(workflow)
    trial = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=units[:1],
        quantity="1",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=trial["exchange_id"],
    )
    with workflow.db() as db:
        sn = db.execute("SELECT sn FROM units WHERE id=?", (units[0],)).fetchone()[0]
        lot = db.execute(
            "SELECT id FROM material_lots WHERE project_id=? LIMIT 1", (p["id"],)
        ).fetchone()[0]
    source = workflow.source(f"future-{uuid4()}", object_type="execution")
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=source,
        work_order_id=wo["id"],
        sn=sn,
        station="assembly",
        route_version="S1",
        program_version="P1",
        firmware_version="F1",
        material_uses=[{"lot_id": lot, "quantity": "0.1", "unit": "kg"}],
        result="pass",
        occurred_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
    )
    assert (
        workflow.object(p["id"], "unit", units[0])["execution_events"][0]["status"]
        == "rejected"
    )


def test_common_material_reservation_cannot_be_consumed_twice_across_trial_and_bulk(
    workflow,
):
    p, wo, units, authority = ready_for_trial(workflow)
    now = datetime.now(UTC)
    with workflow.db() as db:
        order_id, revision_id = db.execute(
            "SELECT order_line_id,revision_id FROM work_orders WHERE id=?", (wo["id"],)
        ).fetchone()
        order_version = db.execute(
            "SELECT source_version FROM order_lines WHERE id=?", (order_id,)
        ).fetchone()[0]
        lot = db.execute(
            "SELECT id FROM material_lots WHERE project_id=? LIMIT 1", (p["id"],)
        ).fetchone()[0]
    source = workflow.source(f"common-plan-{uuid4()}", object_type="plan")
    source.update(
        occurred_at=(now - timedelta(minutes=2)).isoformat(),
        collected_at=(now - timedelta(minutes=1)).isoformat(),
        cutoff=(now - timedelta(minutes=2)).isoformat(),
    )
    plan = workflow.command(
        p["id"],
        "plan.receive",
        actor_name="planner",
        source=source,
        input_revision_ids=[revision_id],
        input_order_versions=[{"order_line_id": order_id, "version": order_version}],
        requirements=[
            {
                "work_order_id": wo["id"],
                "execution_scope": "common",
                "material_id": "steel-1",
                "owner_id": "Customer 1",
                "quantity": "1",
                "unit": "kg",
            }
        ],
    )
    req = workflow.object(p["id"], "plan", plan["object_id"])["requirement_ids"][0]
    ext = f"common-topup-{uuid4()}"
    authority.receive(
        project_id=p["id"],
        external_id=ext,
        commitment_id=str(uuid4()),
        lot_id=lot,
        material_id="steel-1",
        owner_id="Customer 1",
        quantity="1",
        unit="kg",
        scale=3,
        expiry=(now + timedelta(days=120)).date().isoformat(),
        external_actor="WMS",
        signature="signed topup",
    )
    authority.inspect(
        project_id=p["id"],
        external_id=f"iqc-{uuid4()}",
        receipt_external_id=ext,
        accepted="1",
        rejected="0",
        external_actor="QMS",
        signature="signed inspection",
    )
    reserve = workflow.command(
        p["id"],
        "reservation.request",
        actor_name="planner",
        work_order_id=wo["id"],
        requirement_id=req,
        lot_id=lot,
        quantity="1",
        unit="kg",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="planner",
        exchange_id=reserve["exchange_id"],
    )
    workflow.grant(p["id"], "quality", ["quality"], ["inspection"])
    trial = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=units[:1],
        quantity="1",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=trial["exchange_id"],
    )
    test_id = str(uuid4())
    workflow.test_evidence_reader = ProvisionalCompleteTest(
        workflow, test_id, units[0], revision_id
    )
    workflow.reopen()
    workflow.command(
        p["id"],
        "first_article.record",
        actor_name="quality",
        work_order_id=wo["id"],
        unit_ids=units[:1],
        test_ids=[test_id],
        inspection_id="FAI-common",
    )
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
    for uid in units[:2]:
        sn = workflow.object(p["id"], "unit", uid)["sn"]
        workflow.command(
            p["id"],
            "execution.record",
            actor_name="production",
            source=workflow.source(f"common-exec-{uuid4()}", object_type="execution"),
            work_order_id=wo["id"],
            sn=sn,
            station="assembly",
            route_version="S1",
            program_version="P1",
            firmware_version="F1",
            material_uses=[{"lot_id": lot, "quantity": "0.6", "unit": "kg"}],
            result="pass",
            occurred_at=datetime.now(UTC).isoformat(),
        )
    with workflow.db() as db:
        assert [
            r[0]
            for r in db.execute(
                "SELECT status FROM execution_events WHERE project_id=? ORDER BY accepted_seq",
                (p["id"],),
            )
        ] == ["accepted", "rejected"]
        assert (
            db.execute(
                "SELECT SUM(q_atoms) FROM material_consumption WHERE project_id=?",
                (p["id"],),
            ).fetchone()[0]
            == 600
        )


def test_first_article_needs_complete_test_reader_and_same_scope(workflow):
    p, wo, units, _ = ready_for_trial(workflow)
    workflow.grant(p["id"], "quality", ["quality"], ["inspection"])
    trial = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=units[:1],
        quantity="1",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=trial["exchange_id"],
    )
    test_id = str(uuid4())
    blocked = workflow.command(
        p["id"],
        "first_article.record",
        actor_name="quality",
        expected_status=409,
        work_order_id=wo["id"],
        unit_ids=units[:1],
        test_ids=[test_id],
        inspection_id="FAI-1",
    )
    assert "first_article" in str(blocked["blocking_reasons"])
    with workflow.db() as db:
        revision_id = db.execute(
            "SELECT revision_id FROM work_orders WHERE id=?", (wo["id"],)
        ).fetchone()[0]
    workflow.test_evidence_reader = ProvisionalCompleteTest(
        workflow, test_id, units[0], revision_id
    )
    workflow.reopen()
    workflow.command(
        p["id"],
        "first_article.record",
        actor_name="quality",
        work_order_id=wo["id"],
        unit_ids=units[:1],
        test_ids=[test_id],
        inspection_id="FAI-1",
    )
    assert workflow.object(p["id"], "work_order", wo["id"])["bulk_readiness"]["ready"]
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
        "production.interrupt",
        actor_name="production",
        work_order_id=wo["id"],
        kind="S4",
        reason="safety stop before bulk dispatch",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=bulk["exchange_id"],
    )
    assert workflow.object(p["id"], "unit", units[1])["state"] == "start_pending"


def test_trial_one_and_bulk_four_consume_exact_five_unit_authority_budget(workflow):
    p, wo, units, authority = ready_for_trial(workflow)
    workflow.grant(p["id"], "quality", ["quality"], ["inspection"])
    trial = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=units[:1],
        quantity="1",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=trial["exchange_id"],
    )
    with workflow.db() as db:
        revision_id = db.execute(
            "SELECT revision_id FROM work_orders WHERE id=?", (wo["id"],)
        ).fetchone()[0]
    test_id = str(uuid4())
    workflow.test_evidence_reader = ProvisionalCompleteTest(
        workflow, test_id, units[0], revision_id
    )
    workflow.reopen()
    workflow.command(
        p["id"],
        "first_article.record",
        actor_name="quality",
        work_order_id=wo["id"],
        unit_ids=units[:1],
        test_ids=[test_id],
        inspection_id="FAI-5",
    )
    bulk = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="bulk",
        unit_ids=units[1:],
        quantity="4",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=bulk["exchange_id"],
    )
    assert all(
        workflow.object(p["id"], "unit", uid)["state"] == "running" for uid in units
    )
    with authority.store.transaction() as tx:
        row = tx.execute(
            "SELECT started_units,started_trial FROM authority_work_orders WHERE project_id=? AND work_order_id=?",
            (p["id"], wo["id"]),
        ).fetchone()
        assert tuple(row) == (5, 1)
    assert workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        expected_status=409,
        work_order_id=wo["id"],
        mode="bulk",
        unit_ids=units[0:1],
        quantity="1",
    )["blocking_reasons"]


def test_interruption_requires_authority_stop_and_accepted_replan_before_resume(
    workflow,
    monkeypatch,
):
    p, wo, units, authority = ready_for_trial(workflow)
    trial = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=units[:1],
        quantity="1",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=trial["exchange_id"],
    )
    old_plan = workflow.object(p["id"], "work_order", wo["id"])["trial_readiness"][
        "input_versions"
    ]["plan_id"]
    stop = workflow.command(
        p["id"],
        "production.interrupt",
        actor_name="production",
        work_order_id=wo["id"],
        kind="S3",
        reason="S3 material shortage",
    )
    interruption = workflow.object(p["id"], "interruption", stop["object_id"])
    assert interruption["authority_stopped_at"] is None
    assert interruption["reason"] == "S3 material shortage"
    with workflow.db() as db:
        assert (
            db.execute(
                "SELECT kind FROM execution_exceptions WHERE id=? AND project_id=?",
                (interruption["exception_id"], p["id"]),
            ).fetchone()[0]
            == "S3"
        )
    assert workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        expected_status=409,
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=units[1:2],
        quantity="1",
    )["blocking_reasons"]
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=stop["exchange_id"],
    )
    assert workflow.object(p["id"], "interruption", stop["object_id"])[
        "authority_stopped_at"
    ]
    assert workflow.command(
        p["id"],
        "production.resume",
        actor_name="production",
        expected_status=409,
        interruption_id=stop["object_id"],
        plan_id=old_plan,
        evidence="same plan",
    )["blocking_reasons"]
    now = datetime.now(UTC)
    with workflow.db() as db:
        row = db.execute(
            "SELECT order_line_id,revision_id FROM work_orders WHERE id=?", (wo["id"],)
        ).fetchone()
        order_id, revision_id = row
        order_version = db.execute(
            "SELECT source_version FROM order_lines WHERE id=?", (order_id,)
        ).fetchone()[0]
        lot_id = db.execute(
            "SELECT id FROM material_lots WHERE project_id=? LIMIT 1", (p["id"],)
        ).fetchone()[0]
    source = workflow.source(f"replan-{uuid4()}", object_type="plan")
    source.update(
        occurred_at=(now - timedelta(minutes=2)).isoformat(),
        collected_at=(now - timedelta(minutes=1)).isoformat(),
        cutoff=(now - timedelta(minutes=2)).isoformat(),
    )
    plan = workflow.command(
        p["id"],
        "plan.receive",
        actor_name="planner",
        source=source,
        input_revision_ids=[revision_id],
        input_order_versions=[{"order_line_id": order_id, "version": order_version}],
        requirements=[
            {
                "work_order_id": wo["id"],
                "execution_scope": scope,
                "material_id": "steel-1",
                "owner_id": "Customer 1",
                "quantity": qty,
                "unit": "kg",
            }
            for scope, qty in (("trial", "2"), ("bulk", "1"))
        ],
    )
    reqs = workflow.object(p["id"], "plan", plan["object_id"])["requirement_ids"]
    assert workflow.command(
        p["id"],
        "production.resume",
        actor_name="production",
        expected_status=409,
        interruption_id=stop["object_id"],
        plan_id=plan["object_id"],
        evidence="stock short",
    )["blocking_reasons"]
    ext = f"topup-{uuid4()}"
    authority.receive(
        project_id=p["id"],
        external_id=ext,
        commitment_id=str(uuid4()),
        lot_id=lot_id,
        material_id="steel-1",
        owner_id="Customer 1",
        quantity="1",
        unit="kg",
        scale=3,
        expiry=(now + timedelta(days=120)).date().isoformat(),
        external_actor="WMS",
        signature="signed topup",
    )
    authority.inspect(
        project_id=p["id"],
        external_id=f"iqc-{uuid4()}",
        receipt_external_id=ext,
        accepted="1",
        rejected="0",
        external_actor="QMS",
        signature="signed inspection",
    )
    with workflow.db() as db:
        trial_req = db.execute(
            "SELECT id FROM requirements WHERE plan_id=? AND execution_scope='trial'",
            (plan["object_id"],),
        ).fetchone()[0]
    assert trial_req in reqs
    reserve = workflow.command(
        p["id"],
        "reservation.request",
        actor_name="planner",
        work_order_id=wo["id"],
        requirement_id=trial_req,
        lot_id=lot_id,
        quantity="1",
        unit="kg",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="planner",
        exchange_id=reserve["exchange_id"],
    )
    resumed = workflow.command(
        p["id"],
        "production.resume",
        actor_name="production",
        interruption_id=stop["object_id"],
        plan_id=plan["object_id"],
        evidence="replan and reserve accepted",
    )
    assert (
        workflow.object(p["id"], "interruption", stop["object_id"])["resolved_at"]
        is None
    )
    workflow.command(
        p["id"],
        "readiness.record",
        actor_name="engineering",
        work_order_id=wo["id"],
        kind="equipment",
        reference="resume-cal-revoked",
        evidence="calibration revoked before MES resume",
        valid_until=(datetime.now(UTC) + timedelta(days=90)).isoformat(),
        decision="rejected",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=resumed["exchange_id"],
    )
    assert authority.operation_count(resumed["exchange_id"]) == 0
    assert workflow.object(p["id"], "unit", units[0])["state"] == "stopped"
    workflow.command(
        p["id"],
        "readiness.record",
        actor_name="engineering",
        work_order_id=wo["id"],
        kind="equipment",
        reference="resume-cal-restored",
        evidence="calibration restored before MES resume",
        valid_until=(datetime.now(UTC) + timedelta(days=90)).isoformat(),
        decision="verified",
    )
    authority.configure_fault("reject")
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=resumed["exchange_id"],
    )
    assert (
        workflow.object(p["id"], "interruption", stop["object_id"])["resolved_at"]
        is None
    )
    authority.configure_fault("none")
    retry = workflow.command(
        p["id"],
        "production.resume",
        actor_name="production",
        interruption_id=stop["object_id"],
        plan_id=plan["object_id"],
        evidence="MES retry after rejection",
    )
    entered, release = Event(), Event()
    original_submit = MockAuthorityAdapter.submit

    def paused_resume(adapter, request):
        if request.action == "production.resume":
            entered.set()
            assert release.wait(5), "MES resume release barrier timed out"
        return original_submit(adapter, request)

    monkeypatch.setattr(MockAuthorityAdapter, "submit", paused_resume)
    outcomes = []
    dispatch = Thread(
        target=lambda: outcomes.append(
            workflow.command(
                p["id"],
                "exchange.dispatch",
                actor_name="production",
                expected_status=409,
                exchange_id=retry["exchange_id"],
            )
        )
    )
    dispatch.start()
    assert entered.wait(5), "MES resume barrier was not reached"
    workflow.command(
        p["id"],
        "readiness.record",
        actor_name="engineering",
        work_order_id=wo["id"],
        kind="equipment",
        reference="resume-race-revoked",
        evidence="calibration revoked in flight",
        valid_until=(datetime.now(UTC) + timedelta(days=90)).isoformat(),
        decision="rejected",
    )
    release.set()
    dispatch.join(5)
    assert outcomes and outcomes[0]["code"] == "VERSION_CONFLICT"
    assert authority.operation_count(retry["exchange_id"]) == 1
    workflow.command(
        p["id"],
        "exchange.query",
        actor_name="production",
        exchange_id=retry["exchange_id"],
    )
    assert workflow.object(p["id"], "interruption", stop["object_id"])["resolved_at"]
    assert workflow.object(p["id"], "interruption", stop["object_id"])[
        "resume_exchange_ids"
    ] == [resumed["exchange_id"], retry["exchange_id"]]
    held = workflow.object(p["id"], "unit", units[0])
    assert held["state"] == "start_pending" and held["authority_start_accepted"]
    assert (
        workflow.object(p["id"], "exchange", retry["exchange_id"])["phase"]
        == "accepted"
    )
    assert workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        expected_status=409,
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=units[1:2],
        quantity="1",
    )["blocking_reasons"]
    safety_stop = workflow.command(
        p["id"],
        "production.interrupt",
        actor_name="production",
        work_order_id=wo["id"],
        start_id=held["accepted_start_id"],
        kind="S4",
        reason="MES resumed during calibration loss",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=safety_stop["exchange_id"],
    )
    assert workflow.object(p["id"], "unit", units[0])["state"] == "stopped"
    with authority.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT state FROM authority_work_orders WHERE project_id=? AND work_order_id=?",
                (p["id"], wo["id"]),
            ).fetchone()[0]
            == "stopped"
        )


class ProvisionalCompleteTest:
    """B-level protocol fixture; C1 replaces it with persisted test.record queries."""

    def __init__(self, workflow, test_id, unit_id, revision_id):
        from uuid import UUID

        from manufacturing_platform.workflow.engineering import fixed_revision
        from manufacturing_platform.workflow.execution_models import TestEvidenceScope

        with workflow.db() as tx:
            unit = tx.execute("SELECT * FROM units WHERE id=?", (unit_id,)).fetchone()
            equipment = tx.execute(
                "SELECT id FROM readiness_checks WHERE work_order_id=? AND kind='equipment' ORDER BY rowid DESC LIMIT 1",
                (unit["work_order_id"],),
            ).fetchone()
            revision = fixed_revision(tx, UUID(unit["project_id"]), UUID(revision_id))
            self.scope = TestEvidenceScope(
                route_fingerprint=revision.content_hash,
                test_version=revision.test_spec.version,
                program_version=revision.test_spec.program_version,
                firmware_version=revision.firmware_version,
                equipment_check_id=UUID(equipment["id"]),
            )
        self.test_id, self.unit_id, self.revision_id = test_id, unit_id, revision_id

    def complete_pass(self, tx, project_id, test_id, unit_id, revision_id, *, scope):
        if scope != self.scope:
            return False
        if (str(test_id), str(unit_id), str(revision_id)) != (
            self.test_id,
            self.unit_id,
            self.revision_id,
        ):
            return False
        rev = tx.execute(
            "SELECT test_spec_json FROM engineering_revisions WHERE id=? AND project_id=?",
            (str(revision_id), str(project_id)),
        ).fetchone()
        if not rev:
            return False
        spec = __import__("json").loads(rev[0])
        return (
            spec["version"] == "T1"
            and spec["program_version"] == "P1"
            and spec["measurements"]
            == [{"name": "voltage", "unit": "V", "lower": "4", "upper": "6"}]
        )


def running_execution(workflow):
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
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=start["exchange_id"],
    )
    with workflow.db() as db:
        lot = db.execute(
            "SELECT id FROM material_lots WHERE project_id=?", (p["id"],)
        ).fetchone()[0]
    base = {
        "work_order_id": wo["id"],
        "sn": workflow.object(p["id"], "unit", units[0])["sn"],
        "station": "assembly",
        "route_version": "S1",
        "program_version": "P1",
        "firmware_version": "F1",
        "material_uses": [{"lot_id": lot, "quantity": "0.1", "unit": "kg"}],
        "result": "pass",
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    return p, wo, units, authority, base


@pytest.mark.parametrize("invalid", ["equipment", "people", "customer", "stale_plan"])
def test_review_execution_rechecks_use_readiness(workflow, monkeypatch, invalid):
    p, wo, units, _, base = running_execution(workflow)
    if invalid in {"equipment", "people"}:
        workflow.command(
            p["id"],
            "readiness.record",
            actor_name="engineering",
            work_order_id=wo["id"],
            kind=invalid,
            reference="revoked",
            evidence="revoked before attempted use",
            decision="rejected",
            valid_until=(datetime.now(UTC) + timedelta(days=90)).isoformat(),
        )
    elif invalid == "customer":
        revision = workflow.object(p["id"], "unit", units[0])["revision_id"]
        workflow.command(
            p["id"],
            "engineering.customer_approval",
            revision_id=revision,
            customer_id="Customer 1",
            external_signatory="Customer QE",
            decision="rejected",
            evidence="approval revoked",
        )
    else:
        # Advance the actual admission clock; do not alter persisted plan evidence.
        from manufacturing_platform.workflow import service

        class Later(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(UTC) + timedelta(days=3)

        monkeypatch.setattr(service, "datetime", Later)
    base["occurred_at"] = datetime.now(UTC).isoformat()
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=workflow.source(str(uuid4()), object_type="execution"),
        **base,
    )
    event = workflow.object(p["id"], "unit", units[0])["execution_events"][-1]
    assert event["status"] == "rejected"
    assert invalid.split("_")[-1] in event["reason"]
    assert not event["material_uses"]


@pytest.mark.parametrize(
    "invalid", ["future_occurred", "future_collected", "file", "api", "wrong_type"]
)
def test_review_execution_uses_common_source_admission(workflow, invalid):
    p, _, units, _, base = running_execution(workflow)
    source = workflow.source(str(uuid4()), object_type="execution")
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    if invalid == "future_occurred":
        source.update(occurred_at=future, collected_at=future)
    elif invalid == "future_collected":
        source["collected_at"] = future
    elif invalid == "wrong_type":
        source["object_type"] = "receipt"
    else:
        source["mode"] = invalid
    workflow.command(
        p["id"], "execution.record", actor_name="production", source=source, **base
    )
    event = workflow.object(p["id"], "unit", units[0])["execution_events"][-1]
    assert event["status"] == "rejected"
    assert not event["material_uses"]
    assert event["source"] is None  # unadmitted claim is not visible source evidence


@pytest.mark.parametrize("target", ["missing", "foreign", "accepted"])
def test_review_invalid_correction_claim_is_durable_without_foreign_edge(
    workflow, target
):
    p, _, units, _, base = running_execution(workflow)
    target_id = str(uuid4())
    if target != "missing":
        other_p, _, other_units, _, other = (
            running_execution(workflow)
            if target == "foreign"
            else (p, None, units, None, base)
        )
        workflow.command(
            other_p["id"],
            "execution.record",
            actor_name="production",
            source=workflow.source(str(uuid4()), object_type="execution"),
            **other,
        )
        target_id = workflow.object(other_p["id"], "unit", other_units[0])[
            "execution_events"
        ][-1]["id"]
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=workflow.source(str(uuid4()), object_type="execution"),
        supersedes_event_id=target_id,
        **base,
    )
    event = workflow.object(p["id"], "unit", units[0])["execution_events"][-1]
    assert event["status"] == "rejected"
    assert event["supersedes_event_id"] is None
    assert not event["material_uses"]


def review_replan(workflow, p, wo):
    import json

    with workflow.db() as db:
        plan = db.execute(
            "SELECT p.* FROM plans p JOIN requirements r ON r.plan_id=p.id WHERE r.work_order_id=? ORDER BY p.accepted_seq DESC LIMIT 1",
            (wo["id"],),
        ).fetchone()
        inputs = json.loads(plan["inputs_json"])
        reqs = db.execute(
            "SELECT * FROM requirements WHERE plan_id=?", (plan["id"],)
        ).fetchall()
    source = workflow.source(str(uuid4()), object_type="plan")
    now = datetime.now(UTC)
    source.update(
        occurred_at=(now - timedelta(minutes=2)).isoformat(),
        collected_at=(now - timedelta(minutes=1)).isoformat(),
        cutoff=(now - timedelta(minutes=2)).isoformat(),
    )
    return workflow.command(
        p["id"],
        "plan.receive",
        actor_name="planner",
        source=source,
        **inputs,
        requirements=[
            {
                "work_order_id": r["work_order_id"],
                "execution_scope": r["execution_scope"],
                "material_id": r["material_id"],
                "owner_id": r["owner_id"],
                "quantity": str(Decimal(r["q_atoms"]) / 10 ** r["scale"]),
                "unit": r["unit"],
            }
            for r in reqs
        ],
    )["object_id"]


def review_article(workflow, p, wo, uid):
    workflow.grant(p["id"], "quality", ["quality"], ["inspection"])
    test_id = str(uuid4())
    revision = workflow.object(p["id"], "unit", uid)["revision_id"]
    workflow.test_evidence_reader = ProvisionalCompleteTest(
        workflow, test_id, uid, revision
    )
    workflow.reopen()
    workflow.command(
        p["id"],
        "first_article.record",
        actor_name="quality",
        work_order_id=wo["id"],
        unit_ids=[uid],
        test_ids=[test_id],
        inspection_id="provisional-B3",
    )
    return test_id


@pytest.mark.parametrize("query_after_resume", [False, True, "restop"])
def test_review_delayed_start_projects_later_work_order_controls(
    workflow, query_after_resume
):
    p, wo, units, authority, _ = running_execution(workflow)
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
    never_sent = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="bulk",
        unit_ids=units[2:3],
        quantity="1",
    )
    authority.configure_fault("timeout_after_commit")
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=bulk["exchange_id"],
    )
    authority.configure_fault("none")
    stop = workflow.command(
        p["id"],
        "production.interrupt",
        actor_name="production",
        work_order_id=wo["id"],
        reason="controlled stop",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=stop["exchange_id"],
    )
    if not query_after_resume:
        workflow.command(
            p["id"],
            "exchange.query",
            actor_name="production",
            exchange_id=bulk["exchange_id"],
        )
        assert [workflow.object(p["id"], "unit", u)["state"] for u in units[:2]] == [
            "stopped",
            "stopped",
        ]
    plan = review_replan(workflow, p, wo)
    resume = workflow.command(
        p["id"],
        "production.resume",
        actor_name="production",
        interruption_id=stop["object_id"],
        plan_id=plan,
        evidence="verified unchanged basis",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=resume["exchange_id"],
    )
    if query_after_resume == "restop":
        stop2 = workflow.command(
            p["id"],
            "production.interrupt",
            actor_name="production",
            work_order_id=wo["id"],
            reason="later safety stop",
        )
        workflow.command(
            p["id"],
            "exchange.dispatch",
            actor_name="production",
            exchange_id=stop2["exchange_id"],
        )
    workflow.command(
        p["id"],
        "exchange.query",
        actor_name="production",
        exchange_id=bulk["exchange_id"],
    )
    expected_state = "stopped" if query_after_resume == "restop" else "running"
    assert [workflow.object(p["id"], "unit", u)["state"] for u in units[:2]] == [
        expected_state,
        expected_state,
    ]
    assert workflow.object(p["id"], "unit", units[2])["state"] == "start_pending"
    assert workflow.object(p["id"], "unit", units[2])["accepted_start_id"] is None
    assert authority.operation_count(never_sent["exchange_id"]) == 0
    with workflow.db() as tx:
        start_row = tx.execute(
            "SELECT source_sequence,receipt_json FROM exchanges WHERE id=?",
            (bulk["exchange_id"],),
        ).fetchone()
        latest = tx.execute(
            "SELECT MAX(source_sequence) FROM production_controls WHERE work_order_id=?",
            (wo["id"],),
        ).fetchone()[0]
        assert start_row["source_sequence"] < latest
    workflow.command(
        p["id"],
        "exchange.query",
        actor_name="production",
        exchange_id=bulk["exchange_id"],
    )
    with workflow.db() as tx:
        assert (
            tx.execute(
                "SELECT receipt_json FROM exchanges WHERE id=?", (bulk["exchange_id"],)
            ).fetchone()[0]
            == start_row["receipt_json"]
        )
    with authority.store.transaction() as tx:
        assert tuple(
            tx.execute(
                "SELECT started_units,state FROM authority_work_orders WHERE work_order_id=?",
                (wo["id"],),
            ).fetchone()
        ) == (2, expected_state)
    assert authority.operation_count(bulk["exchange_id"]) == 1


@pytest.mark.parametrize("restop", [False, True, "held"])
def test_review_mixed_calibration_recovery_resumes_trial_then_bulk(
    workflow, restop, monkeypatch
):
    p, wo, units, authority, base = running_execution(workflow)
    old_test = review_article(workflow, p, wo, units[0])
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
    stop = workflow.command(
        p["id"],
        "production.interrupt",
        actor_name="production",
        work_order_id=wo["id"],
        reason="renew calibration",
        kind="S4",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=stop["exchange_id"],
    )
    workflow.command(
        p["id"],
        "readiness.record",
        actor_name="engineering",
        work_order_id=wo["id"],
        kind="equipment",
        reference="new-calibration",
        evidence="renewed calibration",
        decision="verified",
        valid_until=(datetime.now(UTC) + timedelta(days=90)).isoformat(),
    )
    plan = review_replan(workflow, p, wo)
    resume_args = {
        "actor_name": "production",
        "interruption_id": stop["object_id"],
        "plan_id": plan,
        "evidence": "requalification",
    }
    assert "first_article" in str(
        workflow.command(
            p["id"], "production.resume", expected_status=409, **resume_args
        )["blocking_reasons"]
    )
    trial = workflow.command(p["id"], "production.resume", scope="trial", **resume_args)
    if restop == "held":
        entered, release = Event(), Event()
        original_submit = MockAuthorityAdapter.submit

        def paused_trial(adapter, request):
            if request.business_key == trial["exchange_id"]:
                entered.set()
                assert release.wait(5)
            return original_submit(adapter, request)

        monkeypatch.setattr(MockAuthorityAdapter, "submit", paused_trial)
        outcomes = []
        worker = Thread(
            target=lambda: outcomes.append(
                workflow.command(
                    p["id"],
                    "exchange.dispatch",
                    actor_name="production",
                    expected_status=409,
                    exchange_id=trial["exchange_id"],
                )
            )
        )
        worker.start()
        assert entered.wait(5)
        workflow.command(
            p["id"],
            "readiness.record",
            actor_name="engineering",
            work_order_id=wo["id"],
            kind="equipment",
            reference="trial-resume-race",
            evidence="revoked while trial recovery in flight",
            decision="rejected",
            valid_until=(datetime.now(UTC) + timedelta(days=90)).isoformat(),
        )
        release.set()
        worker.join(5)
        assert outcomes and outcomes[0]["code"] == "VERSION_CONFLICT"
        workflow.command(
            p["id"],
            "exchange.query",
            actor_name="production",
            exchange_id=trial["exchange_id"],
        )
    else:
        workflow.command(
            p["id"],
            "exchange.dispatch",
            actor_name="production",
            exchange_id=trial["exchange_id"],
        )

    assert [workflow.object(p["id"], "unit", u)["state"] for u in units[:2]] == [
        "start_pending" if restop == "held" else "running",
        "stopped",
    ]
    assert (
        workflow.object(p["id"], "exchange", trial["exchange_id"])["receipt"][
            "details"
        ][0]["scope"]
        == "trial"
    )
    assert (
        workflow.object(p["id"], "interruption", stop["object_id"])["resolved_at"]
        is None
    )
    with authority.store.transaction() as tx:
        assert tuple(
            tx.execute(
                "SELECT started_units,state FROM authority_work_orders WHERE work_order_id=?",
                (wo["id"],),
            ).fetchone()
        ) == (2, "partial")
        assert [
            r[0]
            for r in tx.execute(
                "SELECT state FROM authority_start_units WHERE work_order_id=? ORDER BY mode DESC",
                (wo["id"],),
            )
        ] == ["running", "stopped"]
    workflow.command(
        p["id"],
        "first_article.record",
        actor_name="quality",
        expected_status=409,
        work_order_id=wo["id"],
        unit_ids=units[:1],
        test_ids=[old_test],
        inspection_id="old-calibration-test",
    )
    if restop:
        old_stop = stop
        stop = workflow.command(
            p["id"],
            "production.interrupt",
            actor_name="production",
            work_order_id=wo["id"],
            reason="stop partial recovery",
            kind="S4",
            start_id=workflow.object(p["id"], "unit", units[0])["accepted_start_id"]
            if restop == "held"
            else None,
        )
        workflow.command(
            p["id"],
            "exchange.dispatch",
            actor_name="production",
            exchange_id=stop["exchange_id"],
        )
        previous = workflow.object(p["id"], "interruption", old_stop["object_id"])
        assert previous["resolved_at"] is None
        assert previous["superseded_by"] == stop["object_id"]
        assert [workflow.object(p["id"], "unit", u)["state"] for u in units[:2]] == [
            "stopped",
            "stopped",
        ]
        if restop == "held":
            workflow.command(
                p["id"],
                "readiness.record",
                actor_name="engineering",
                work_order_id=wo["id"],
                kind="equipment",
                reference="trial-recovery-restored",
                evidence="restored after real safety stop",
                decision="verified",
                valid_until=(datetime.now(UTC) + timedelta(days=90)).isoformat(),
            )
        plan = review_replan(workflow, p, wo)
        resume_args.update(interruption_id=stop["object_id"], plan_id=plan)
        trial = workflow.command(
            p["id"], "production.resume", scope="trial", **resume_args
        )
        workflow.command(
            p["id"],
            "exchange.dispatch",
            actor_name="production",
            exchange_id=trial["exchange_id"],
        )
    base["occurred_at"] = datetime.now(UTC).isoformat()
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=workflow.source(str(uuid4()), object_type="execution"),
        **base,
    )
    assert (
        workflow.object(p["id"], "unit", units[0])["execution_events"][-1]["status"]
        == "accepted"
    )
    review_article(workflow, p, wo, units[0])
    resume = workflow.command(p["id"], "production.resume", **resume_args)
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=resume["exchange_id"],
    )
    assert [workflow.object(p["id"], "unit", u)["state"] for u in units[:2]] == [
        "running",
        "running",
    ]
    assert workflow.object(p["id"], "interruption", stop["object_id"])["resolved_at"]
    with authority.store.transaction() as tx:
        assert tuple(
            tx.execute(
                "SELECT started_units,started_trial,state FROM authority_work_orders WHERE work_order_id=?",
                (wo["id"],),
            ).fetchone()
        ) == (2, 1, "running")


def test_review_historical_execution_requires_explicit_reassessment_after_renewal(
    workflow,
):
    p, wo, units, _, base = running_execution(workflow)
    source = workflow.source(str(uuid4()), object_type="execution")
    workflow.command(
        p["id"], "execution.record", actor_name="production", source=source, **base
    )
    workflow.command(
        p["id"],
        "readiness.record",
        actor_name="engineering",
        work_order_id=wo["id"],
        kind="equipment",
        reference="renewed",
        evidence="new basis after original physical event",
        decision="verified",
        valid_until=(datetime.now(UTC) + timedelta(days=90)).isoformat(),
    )
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=workflow.source(str(uuid4()), object_type="execution"),
        **base,
    )
    history = workflow.object(p["id"], "unit", units[0])["execution_events"]
    assert history[0]["status"] == "accepted" and history[0]["material_uses"]
    assert history[1]["status"] == "rejected" and not history[1]["material_uses"]
    assert (
        "historical" in history[1]["reason"] and "reassessment" in history[1]["reason"]
    )


def test_review_unadmitted_source_cannot_create_a_correction_edge(workflow):
    p, _, units, _, base = running_execution(workflow)
    invalid = {**base, "route_version": "wrong"}
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=workflow.source(str(uuid4()), object_type="execution"),
        **invalid,
    )
    target = workflow.object(p["id"], "unit", units[0])["execution_events"][-1]["id"]
    source = workflow.source(str(uuid4()), object_type="execution")
    source["mode"] = "file"
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=source,
        supersedes_event_id=target,
        **base,
    )
    event = workflow.object(p["id"], "unit", units[0])["execution_events"][-1]
    assert event["status"] == "rejected" and event["supersedes_event_id"] is None


@pytest.mark.parametrize("phase", ["pending", "unknown", "accepted"])
def test_review_v7_resume_envelope_survives_additive_migration(
    workflow, monkeypatch, phase
):
    import json
    import sqlite3

    from manufacturing_platform.workflow.exchange_models import ResumePayload

    original = MockAuthorityAdapter._submit_execution

    def v7_reply(self, tx, request, h, sequence, fault_name):
        receipt = original(self, tx, request, h, sequence, fault_name)
        if isinstance(request.typed_payload, ResumePayload):
            receipt.details = []  # the real v7 authority response shape
        return receipt

    monkeypatch.setattr(MockAuthorityAdapter, "_submit_execution", v7_reply)
    p, wo, units, authority, _ = running_execution(workflow)
    stop = workflow.command(
        p["id"],
        "production.interrupt",
        actor_name="production",
        work_order_id=wo["id"],
        reason="migration stop",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=stop["exchange_id"],
    )
    plan = review_replan(workflow, p, wo)
    resume = workflow.command(
        p["id"],
        "production.resume",
        actor_name="production",
        interruption_id=stop["object_id"],
        plan_id=plan,
        evidence="legacy whole work order resume",
    )
    legacy_command = {
        "action": "production.resume",
        "operation_id": resume["operation_id"],
        "expected_version": resume["project_version"] - 1,
        "interruption_id": stop["object_id"],
        "plan_id": plan,
        "evidence": "legacy whole work order resume",
    }
    from manufacturing_platform.workflow.adapters.mock import digest

    with workflow.db() as tx:
        operation = dict(
            tx.execute(
                "SELECT * FROM operations WHERE operation_id=?",
                (resume["operation_id"],),
            ).fetchone()
        )
        assert operation["payload_hash"] == digest(
            {"project_id": p["id"], **legacy_command}
        )
    if phase != "pending":
        if phase == "unknown":
            authority.configure_fault("timeout_after_commit")
        workflow.command(
            p["id"],
            "exchange.dispatch",
            actor_name="production",
            exchange_id=resume["exchange_id"],
        )
        authority.configure_fault("none")
    with workflow.db() as db:
        row = dict(
            db.execute(
                "SELECT * FROM exchanges WHERE id=?", (resume["exchange_id"],)
            ).fetchone()
        )
        assert "scope" not in json.loads(row["request_json"])["typed_payload"]
        assert row["phase"] == ("requested" if phase == "pending" else phase)
    # Migration fixture changes schema only. Every domain fact was created above by API.
    workflow._client.close()
    with sqlite3.connect(workflow.paths.domain) as tx:
        tx.execute("DROP TABLE execution_admissions")
        tx.execute("DROP TABLE production_controls")
        tx.execute("ALTER TABLE interruptions DROP COLUMN trial_resumed_at")
        tx.execute("ALTER TABLE interruptions DROP COLUMN superseded_by")
        tx.execute("UPDATE schema_version SET version=7")
    with sqlite3.connect(workflow.paths.authority) as tx:
        tx.execute("ALTER TABLE authority_start_units DROP COLUMN state")
        tx.execute("DROP INDEX authority_stop_lineage")
    workflow.reopen()
    workflow.command(
        p["id"],
        "exchange.dispatch" if phase == "pending" else "exchange.query",
        actor_name="production",
        exchange_id=resume["exchange_id"],
    )
    assert (
        workflow.object(p["id"], "exchange", resume["exchange_id"])["phase"]
        == "accepted"
    )
    assert workflow.object(p["id"], "unit", units[0])["state"] == "running"
    assert authority.operation_count(resume["exchange_id"]) == 1
    replay = workflow.client("production").post(
        f"/api/v1/manufacturing/workflow/projects/{p['id']}/commands",
        json=legacy_command,
    )
    assert replay.status_code == 200 and replay.json()["replayed"]
    assert replay.json()["exchange_id"] == resume["exchange_id"]
    assert replay.json()["project_version"] == resume["project_version"]
    assert replay.json()["current_project_version"] > resume["project_version"]
    with workflow.db() as tx:
        assert (
            dict(
                tx.execute(
                    "SELECT * FROM operations WHERE operation_id=?",
                    (resume["operation_id"],),
                ).fetchone()
            )
            == operation
        )
    with workflow.db() as db:
        after = dict(
            db.execute(
                "SELECT * FROM exchanges WHERE id=?", (resume["exchange_id"],)
            ).fetchone()
        )
        for key in ("request_json", "request_hash", "business_key"):
            assert after[key] == row[key]
        assert db.execute("SELECT version FROM schema_version").fetchone()[0] == 9
    with authority.store.transaction() as tx:
        assert tx.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='authority_stop_lineage'"
        ).fetchone()
        assert (
            tx.execute(
                "SELECT state FROM authority_start_units WHERE unit_id=?", (units[0],)
            ).fetchone()[0]
            == "running"
        )


def test_review_wrong_work_order_serial_has_no_foreign_genealogy_edge(workflow):
    p, wo, units, _, base = running_execution(workflow)
    demand = workflow.command(
        p["id"],
        "demand.record",
        kind="firm",
        product=p["product"],
        quantity="1",
        unit="piece",
        due_date="2026-12-01",
        source=workflow.source(str(uuid4()), object_type="demand"),
    )["object_id"]
    for dimension in ("technical", "material", "capacity", "commercial", "quality"):
        workflow.command(
            p["id"],
            "demand.review",
            demand_id=demand,
            dimension=dimension,
            decision="approved",
            evidence="approved",
        )
    order = workflow.command(
        p["id"],
        "order.register",
        demand_id=demand,
        source=workflow.source(str(uuid4()), object_type="order_line"),
        quantity="1",
        unit="piece",
        due_date="2026-12-01",
    )["object_id"]
    revision = workflow.object(p["id"], "unit", units[0])["revision_id"]
    other_wo = workflow.command(
        p["id"],
        "work_order.register",
        actor_name="planner",
        order_line_id=order,
        revision_id=revision,
        source=workflow.source(str(uuid4()), object_type="work_order"),
        quantity="1",
        unit="piece",
        purpose="trial",
        trial_quantity="1",
        planned_start="2026-12-01T00:00:00+00:00",
        planned_end="2026-12-02T00:00:00+00:00",
    )["object_id"]
    other_unit = workflow.command(
        p["id"],
        "unit.register",
        actor_name="production",
        work_order_id=other_wo,
        sns=["OTHER-WO-SN"],
    )["object_id"]
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=workflow.source(str(uuid4()), object_type="execution"),
        **{**base, "sn": "OTHER-WO-SN"},
    )
    with workflow.db() as tx:
        e = tx.execute(
            "SELECT * FROM execution_events WHERE work_order_id=?", (wo["id"],)
        ).fetchone()
        assert e["status"] == "rejected" and e["unit_id"] is None
    assert not workflow.object(p["id"], "unit", other_unit)["execution_events"]


def test_review_v7_resume_command_fingerprint_is_unchanged():
    from manufacturing_platform.workflow.execution_models import ResumeProduction

    legacy = {
        "action": "production.resume",
        "operation_id": str(uuid4()),
        "expected_version": 7,
        "interruption_id": str(uuid4()),
        "plan_id": str(uuid4()),
        "evidence": "original evidence",
    }
    assert ResumeProduction.model_validate(legacy).model_dump(mode="json") == legacy


def test_review_foreign_rejected_source_claim_cannot_hide_admitted_evidence(workflow):
    p, _, units, _, base = running_execution(workflow)
    source = workflow.source(str(uuid4()), object_type="execution")
    workflow.command(
        p["id"], "execution.record", actor_name="production", source=source, **base
    )
    other, _, other_units, _, other_base = running_execution(workflow)
    workflow.command(
        other["id"],
        "execution.record",
        actor_name="production",
        source=source,
        **other_base,
    )
    rejected = workflow.object(other["id"], "unit", other_units[0])["execution_events"][
        -1
    ]
    assert rejected["status"] == "rejected" and rejected["source"] is None
    original = workflow.object(p["id"], "unit", units[0])["execution_events"][-1]
    assert original["source"]["external_id"] == source["external_id"]


def r7_partial_with_full_resume_intent(workflow):
    p, wo, units, authority, _ = running_execution(workflow)
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
    stop = workflow.command(
        p["id"],
        "production.interrupt",
        actor_name="production",
        work_order_id=wo["id"],
        reason="initial mixed stop",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=stop["exchange_id"],
    )
    plan = review_replan(workflow, p, wo)
    args = {
        "actor_name": "production",
        "interruption_id": stop["object_id"],
        "plan_id": plan,
        "evidence": "same valid basis",
    }
    trial = workflow.command(p["id"], "production.resume", scope="trial", **args)
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=trial["exchange_id"],
    )
    full = workflow.command(p["id"], "production.resume", **args)
    return p, wo, units, authority, stop, trial, full


@pytest.mark.parametrize("attempt", ["pending", "rejected"])
def test_r7_full_resume_attempt_does_not_remove_trial_safety_stop(workflow, attempt):
    p, wo, units, authority, old, trial, full = r7_partial_with_full_resume_intent(
        workflow
    )
    with workflow.db() as tx:
        original_request = tx.execute(
            "SELECT request_json FROM exchanges WHERE id=?", (full["exchange_id"],)
        ).fetchone()[0]
    if attempt == "rejected":
        authority.configure_fault("reject")
        workflow.command(
            p["id"],
            "exchange.dispatch",
            actor_name="production",
            exchange_id=full["exchange_id"],
        )
        authority.configure_fault("none")
    with authority.store.transaction() as tx:
        assert [
            tuple(r)
            for r in tx.execute(
                "SELECT mode,state FROM authority_start_units WHERE work_order_id=? ORDER BY mode DESC",
                (wo["id"],),
            )
        ] == [("trial", "running"), ("bulk", "stopped")]
    new = workflow.command(
        p["id"],
        "production.interrupt",
        actor_name="production",
        work_order_id=wo["id"],
        reason="safety stop while full recovery is uncertain",
    )
    previous = workflow.object(p["id"], "interruption", old["object_id"])
    assert previous["superseded_by"] == new["object_id"]
    assert previous["resolved_at"] is None
    assert previous["resume_exchange_ids"] == [
        trial["exchange_id"],
        full["exchange_id"],
    ]
    # An old unsent intent must fail its fresh gate before an authority effect.
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=full["exchange_id"],
    )
    assert authority.operation_count(full["exchange_id"]) == (
        1 if attempt == "rejected" else 0
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=new["exchange_id"],
    )
    assert [workflow.object(p["id"], "unit", u)["state"] for u in units[:2]] == [
        "stopped",
        "stopped",
    ]
    with authority.store.transaction() as tx:
        assert tuple(
            tx.execute(
                "SELECT started_units,started_trial,state FROM authority_work_orders WHERE work_order_id=?",
                (wo["id"],),
            ).fetchone()
        ) == (2, 1, "stopped")
    assert authority.operation_count(new["exchange_id"]) == 1

    with workflow.db() as tx:
        assert (
            tx.execute(
                "SELECT request_json FROM exchanges WHERE id=?", (full["exchange_id"],)
            ).fetchone()[0]
            == original_request
        )


@pytest.mark.parametrize(
    "boundary",
    ["stop_before_effect", "effect_before_stop_delivery_late", "request_before_effect"],
)
def test_r7_inflight_full_resume_obeys_newer_safety_stop(
    workflow, monkeypatch, boundary
):
    p, wo, units, authority, old, _trial, full = r7_partial_with_full_resume_intent(
        workflow
    )
    entered, release = Event(), Event()
    original = MockAuthorityAdapter.submit

    def paused(adapter, request):
        if request.business_key != full["exchange_id"]:
            return original(adapter, request)
        receipt = (
            original(adapter, request)
            if boundary == "effect_before_stop_delivery_late"
            else None
        )
        entered.set()
        assert release.wait(5)
        return receipt if receipt is not None else original(adapter, request)

    monkeypatch.setattr(MockAuthorityAdapter, "submit", paused)
    outcomes = []

    def dispatch_inflight():
        try:
            outcomes.append(
                workflow.command(
                    p["id"],
                    "exchange.dispatch",
                    actor_name="production",
                    expected_status=409,
                    exchange_id=full["exchange_id"],
                )
            )
        except AssertionError as exc:
            outcomes.append(exc)

    worker = Thread(target=dispatch_inflight)
    worker.start()
    assert entered.wait(5)
    try:
        new = workflow.command(
            p["id"],
            "production.interrupt",
            actor_name="production",
            work_order_id=wo["id"],
            reason="inflight full resume safety stop",
        )
        if boundary != "request_before_effect":
            workflow.command(
                p["id"],
                "exchange.dispatch",
                actor_name="production",
                exchange_id=new["exchange_id"],
            )
    finally:
        release.set()
        worker.join(5)
    assert (
        outcomes
        and isinstance(outcomes[0], dict)
        and outcomes[0]["code"] == "VERSION_CONFLICT"
    ), outcomes
    workflow.command(
        p["id"],
        "exchange.query",
        actor_name="production",
        exchange_id=full["exchange_id"],
    )
    full_view = workflow.object(p["id"], "exchange", full["exchange_id"])
    assert full_view["phase"] == (
        "rejected" if boundary == "stop_before_effect" else "accepted"
    )
    assert (
        workflow.object(p["id"], "interruption", old["object_id"])["superseded_by"]
        == new["object_id"]
    )
    if boundary == "request_before_effect":
        assert [workflow.object(p["id"], "unit", u)["state"] for u in units[:2]] == [
            "start_pending",
            "start_pending",
        ]
        with authority.store.transaction() as tx:
            assert (
                tx.execute(
                    "SELECT state FROM authority_work_orders WHERE work_order_id=?",
                    (wo["id"],),
                ).fetchone()[0]
                == "running"
            )
        workflow.command(
            p["id"],
            "exchange.dispatch",
            actor_name="production",
            exchange_id=new["exchange_id"],
        )
    assert [workflow.object(p["id"], "unit", u)["state"] for u in units[:2]] == [
        "stopped",
        "stopped",
    ]
    with authority.store.transaction() as tx:
        assert tuple(
            tx.execute(
                "SELECT started_units,started_trial,state FROM authority_work_orders WHERE work_order_id=?",
                (wo["id"],),
            ).fetchone()
        ) == (2, 1, "stopped")
        effect = tx.execute(
            "SELECT seq FROM authority_operations WHERE business_key=?",
            (full["exchange_id"],),
        ).fetchone()[0]
        stop_seq = tx.execute(
            "SELECT seq FROM authority_operations WHERE business_key=?",
            (new["exchange_id"],),
        ).fetchone()[0]
        assert (effect > stop_seq) == (boundary == "stop_before_effect")
    assert authority.operation_count(full["exchange_id"]) == 1
    assert authority.operation_count(new["exchange_id"]) == 1
    workflow.command(
        p["id"],
        "production.interrupt",
        actor_name="production",
        expected_status=409,
        work_order_id=wo["id"],
        reason="already stopped; historical resume cannot reopen control",
    )
