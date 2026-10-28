"""B3 execution through the public API and the independent authority boundary."""

from datetime import UTC, datetime, timedelta
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


def ready_for_trial(workflow):
    contract = {
        "customer_approval_required": True,
        "customer_release_required": "unknown",
        "acceptance_required": "unknown",
        "customer_revision": "C1",
        "internal_revision": "M1",
        "material_ownership_rules": "Customer 1 owns steel-1",
    }
    p, order, wo, rev = workflow.order_workorder(quantity="5", contract=contract)
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
        sns=[f"B3-{uuid4()}" for _ in range(5)],
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
        test_id, units[0], revision_id
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
        test_id, units[0], revision_id
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
        test_id, units[0], revision_id
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

    def __init__(self, test_id, unit_id, revision_id):
        self.test_id, self.unit_id, self.revision_id = test_id, unit_id, revision_id

    def complete_pass(self, tx, project_id, test_id, unit_id, revision_id):
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
