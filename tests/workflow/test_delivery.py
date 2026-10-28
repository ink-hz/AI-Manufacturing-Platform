"""C2 delivery facts through the authorized public HTTP boundary."""

from uuid import uuid4

import pytest

from .conftest import BASE


def test_partial_delivery_keeps_order_open(workflow):
    p, order, units = workflow.released_order(quantity="100")
    shipment = workflow.ship(p["id"], order["id"], [u["id"] for u in units[:60]], boxes=[{"box_id":"BOX-60","unit_ids":[u["id"] for u in units[:60]]}])
    receipt=workflow.object(p["id"],"exchange",shipment["exchange_id"])["receipt"]
    assert len(receipt["details"])==60 and all(d["box_id"]=="BOX-60" for d in receipt["details"])
    workflow.sign_and_accept(p["id"], shipment["id"], quantity="60")
    summary = workflow.object(p["id"], "order_line", order["id"])
    assert summary["remaining_to_ship"] == "40"
    assert summary["remaining_to_accept"] == "40"
    assert summary["fulfillment_status"] != "closed"
    workflow.ship(p["id"], order["id"], [units[0]["id"]], expected_status=409)
    workflow.ship(
        p["id"],
        order["id"],
        [u["id"] for u in units[60:]],
        quantity="41",
        expected_status=409,
    )
    second = workflow.ship(p["id"], order["id"], [u["id"] for u in units[60:]])
    assert (
        workflow.object(p["id"], "order_line", order["id"])["remaining_to_accept"]
        == "40"
    )
    workflow.sign_and_accept(p["id"], second["id"], quantity="40")
    assert (
        workflow.object(p["id"], "order_line", order["id"])["remaining_to_accept"]
        == "0"
    )


def test_pending_claim_and_separate_signed_accepted(workflow):
    p, order, units = workflow.released_order(quantity="2")
    shipment = workflow.ship(p["id"], order["id"], [units[0]["id"]], dispatch=False)
    assert shipment["shipped"] == shipment["signed"] == shipment["accepted"] == "0"
    workflow.ship(p["id"], order["id"], [units[0]["id"]], expected_status=409)
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="warehouse",
        exchange_id=shipment["exchange_id"],
    )
    shipment = workflow.object(p["id"], "shipment", shipment["id"])
    assert shipment["shipped"] == "1"
    assert shipment["signed"] == shipment["accepted"] == "0"


def source_now(workflow, kind):
    from datetime import UTC, datetime

    source = workflow.source(str(uuid4()), object_type=kind)
    source.update(
        occurred_at=datetime.now(UTC).isoformat(),
        collected_at=datetime.now(UTC).isoformat(),
    )
    return source


def test_required_named_issue_and_independent_closures(workflow):
    from .conftest import USERS

    p, order, units = workflow.released_order(quantity="1")
    shipment = workflow.ship(p["id"], order["id"], [units[0]["id"]])
    workflow.command(
        p["id"],
        "delivery.sign",
        actor_name="warehouse",
        shipment_id=shipment["id"],
        quantity="1",
        source=source_now(workflow, "delivery_sign"),
        external_signatory="Customer receiver",
    )
    workflow.command(
        p["id"],
        "delivery.accept",
        actor_name="warehouse",
        shipment_id=shipment["id"],
        quantity="1",
        source=source_now(workflow, "delivery_accept"),
        external_signatory="Customer QE",
        issues=[
            dict(
                title="Missing packing report",
                owner_id=str(USERS["quality"]),
                required=True,
            )
        ],
    )
    shipment = workflow.object(p["id"], "shipment", shipment["id"])
    issue = shipment["issues"][0]
    assert issue["owner_name"] == "Quality Engineer"
    for kind in ("fulfillment", "quality"):
        workflow.command(
            p["id"],
            "closure.record",
            kind=kind,
            source=source_now(workflow, "closure"),
            evidence="review",
            expected_status=409,
        )
    closed = workflow.command(
        p["id"],
        "closure.record",
        kind="cost",
        source=source_now(workflow, "closure"),
        evidence="manual cost reconciliation signed",
    )
    assert (
        workflow.object(p["id"], "closure", closed["object_id"])["status"] == "closed"
    )
    workflow.command(
        p["id"],
        "delivery.resolve_issue",
        actor_name="production",
        issue_id=issue["id"],
        evidence="not owner",
        expected_status=403,
    )
    workflow.command(
        p["id"],
        "delivery.resolve_issue",
        actor_name="quality",
        issue_id=issue["id"],
        evidence="Packing report received",
    )
    for kind in ("fulfillment", "quality"):
        closed = workflow.command(
            p["id"],
            "closure.record",
            kind=kind,
            source=source_now(workflow, "closure"),
            evidence="all required evidence reviewed",
        )
        assert (
            workflow.object(p["id"], "closure", closed["object_id"])["status"]
            == "closed"
        )


def test_project_totals_and_order_closure_follow_real_delivery(workflow):
    p, order, units = workflow.released_order(quantity="1")
    shipment = workflow.ship(p["id"], order["id"], [units[0]["id"]])
    workflow.sign_and_accept(p["id"], shipment["id"], quantity="1")
    summary = workflow.client().get(f"{BASE}/projects/{p['id']}").json()["summary"]
    assert summary["signed"] == summary["accepted"] == "1"
    assert summary["remaining_to_accept"] == "0"
    workflow.command(
        p["id"],
        "closure.record",
        kind="fulfillment",
        source=source_now(workflow, "closure"),
        evidence="Complete actual delivery",
    )
    assert (
        workflow.object(p["id"], "order_line", order["id"])["fulfillment_status"]
        == "closed"
    )


def test_named_member_profiles_are_bounded_and_project_scoped(workflow):
    p, _, _ = workflow.released_order(quantity="1")
    response = workflow.client("warehouse").get(
        f"{BASE}/projects/{p['id']}/members?limit=2&offset=0"
    )
    assert response.status_code == 200
    assert len(response.json()["items"]) == 2
    assert all(item["display_name"] for item in response.json()["items"])
    assert (
        workflow.client("outsider")
        .get(f"{BASE}/projects/{p['id']}/members")
        .status_code
        == 404
    )


def test_ownership_compares_actual_material_movements_not_caller_totals(workflow):
    p, _, _ = workflow.released_order(quantity="1", mode="oem")
    assert p["mode"] == "oem"
    lot = (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/material_lot?limit=1")
        .json()["items"][0]["id"]
    )
    base = dict(
        material_lot_id=lot, material_id="steel-1", owner_id="Customer 1", unit="kg"
    )
    for kind in ("return", "raw_loss"):
        workflow.command(
            p["id"],
            "ownership.movement",
            actor_name="supply",
            **base,
            movement=kind,
            quantity="0.500",
            source=source_now(workflow, "material_movement"),
            external_signatory="Material custodian",
            evidence="Actual weighed movement",
        )
    result = workflow.command(
        p["id"],
        "ownership.reconcile",
        actor_name="supply",
        **base,
        received="2.000",
        consumed="0.001",
        scrapped="0.500",
        returned="0.500",
        balance="0.999",
        source=source_now(workflow, "ownership"),
    )
    assert result["object_type"] == "material_lot"
    workflow.command(
        p["id"],
        "ownership.reconcile",
        actor_name="supply",
        **base,
        received="2.000",
        consumed="0.001",
        scrapped="0.000",
        returned="0.000",
        balance="1.999",
        source=source_now(workflow, "ownership"),
        expected_status=409,
    )
    workflow.command(
        p["id"],
        "ownership.movement",
        actor_name="supply",
        **base,
        movement="raw_loss",
        quantity="1.000",
        source=source_now(workflow, "material_movement"),
        external_signatory="Material custodian",
        evidence="Would double count consumed material",
        expected_status=409,
    )
    detail = workflow.object(p["id"], "material_lot", lot)
    assert detail["ownership_balance"]["returned"] == "0.500"
    assert detail["ownership_balance"]["scrapped"] == "0.500"


def test_source_commit_quality_race_retains_physical_shipments(workflow, monkeypatch):
    from threading import Event, Thread

    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    p, order, units = workflow.released_order(quantity="2")
    sid = workflow.ship(p["id"], order["id"], [units[0]["id"]], dispatch=False)
    original = MockAuthorityAdapter.submit
    entered, released = Event(), Event()

    def barrier(adapter, request):
        receipt = original(adapter, request)
        if request.action == "shipment.request":
            entered.set()
            assert released.wait(5)
        return receipt

    monkeypatch.setattr(MockAuthorityAdapter, "submit", barrier)
    outcomes = []
    thread = Thread(
        target=lambda: outcomes.append(
            workflow.command(
                p["id"],
                "exchange.dispatch",
                actor_name="warehouse",
                exchange_id=sid["exchange_id"],
                expected_status=409,
            )
        )
    )
    thread.start()
    assert entered.wait(5)
    workflow.command(
        p["id"],
        "release.decide",
        actor_name="quality",
        kind="quality",
        unit_ids=[units[0]["id"]],
        decision="rejected",
        evidence="Quality hold during physical shipment",
    )
    released.set()
    thread.join(5)
    assert not thread.is_alive() and outcomes
    workflow.command(
        p["id"],
        "exchange.query",
        actor_name="warehouse",
        exchange_id=sid["exchange_id"],
    )
    current = workflow.object(p["id"], "shipment", sid["id"])
    assert current["state"] == "held" and current["shipped"] == "1"
    assert current["signed"] == current["accepted"] == "0"
    workflow.ship(p["id"], order["id"], [units[0]["id"]], expected_status=409)
    authority = MockAuthorityAdapter(str(workflow.paths.authority), "workflow-test")
    assert authority.operation_count(sid["id"]) == 1
    workflow.command(
        p["id"],
        "release.decide",
        actor_name="quality",
        kind="quality",
        unit_ids=[units[0]["id"]],
        decision="approved",
        evidence="Current measured quality release restored",
    )
    assert workflow.object(p["id"], "shipment", sid["id"])["state"] == "accepted"


def test_known_quality_hold_prevents_dispatch_and_rejected_claim_is_reusable(workflow):
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    p, order, units = workflow.released_order(quantity="1")
    sid = workflow.ship(p["id"], order["id"], [units[0]["id"]], dispatch=False)
    workflow.command(
        p["id"],
        "release.decide",
        actor_name="quality",
        kind="quality",
        unit_ids=[units[0]["id"]],
        decision="rejected",
        evidence="Known before send",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="warehouse",
        exchange_id=sid["exchange_id"],
    )
    authority = MockAuthorityAdapter(str(workflow.paths.authority), "workflow-test")
    assert authority.operation_count(sid["id"]) == 0
    workflow.command(
        p["id"],
        "release.decide",
        actor_name="quality",
        kind="quality",
        unit_ids=[units[0]["id"]],
        decision="approved",
        evidence="Verified release restored",
    )
    authority.configure_fault("reject")
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="warehouse",
        exchange_id=sid["exchange_id"],
    )
    assert workflow.object(p["id"], "shipment", sid["id"])["state"] == "rejected"
    authority.configure_fault("none")
    replacement = workflow.ship(p["id"], order["id"], [units[0]["id"]])
    assert replacement["shipped"] == "1"


def test_returned_raw_material_cannot_be_consumed_again(workflow):
    from datetime import UTC, datetime

    p, _, units = workflow.released_order(quantity="1")
    unit = workflow.object(p["id"], "unit", units[0]["id"])
    lot = unit["execution_events"][0]["material_uses"][0]["lot_id"]
    workflow.command(
        p["id"],
        "ownership.movement",
        actor_name="supply",
        material_lot_id=lot,
        material_id="steel-1",
        owner_id="Customer 1",
        unit="kg",
        movement="return",
        quantity="1.999",
        source=source_now(workflow, "material_movement"),
        external_signatory="Customer custodian",
        evidence="Returned actual remaining raw stock",
    )
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        work_order_id=unit["work_order_id"],
        sn=unit["sn"],
        station="assembly",
        route_version="S1",
        program_version="P1",
        firmware_version="F1",
        material_uses=[dict(lot_id=lot, quantity="0.001", unit="kg")],
        result="pass",
        occurred_at=datetime.now(UTC).isoformat(),
        source=source_now(workflow, "execution"),
    )
    with workflow.db() as tx:
        assert (
            tx.execute(
                "SELECT SUM(q_atoms) FROM material_consumption WHERE lot_id=?", (lot,)
            ).fetchone()[0]
            == 1
        )


def legacy_stock_opening(workflow, monkeypatch):
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    from .test_exchanges import act, reserve, stock

    p, req, supply, intent = reserve(workflow)
    stock(workflow, p, supply)
    original = MockAuthorityAdapter.submit

    def legacy(adapter, request):
        receipt = original(adapter, request)
        if request.action == "reservation.request":
            receipt.details[0].stock_basis = None
        return receipt

    monkeypatch.setattr(MockAuthorityAdapter, "submit", legacy)
    act(workflow, p, intent)
    eco = workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=supply["revision_id"],
        effective_work_order_ids=[supply["work_order_id"]],
        reason="Historical basis requires actual source proof",
    )
    return p, supply, intent, eco


def test_historical_stock_basis_recovers_only_from_original_source_proof(
    workflow, monkeypatch
):
    p, supply, intent, eco = legacy_stock_opening(workflow, monkeypatch)
    workflow.command(
        p["id"],
        "closure.record",
        kind="quality",
        source=source_now(workflow, "closure"),
        evidence="Must first repair historical source ambiguity",
        expected_status=409,
    )
    assert workflow.object(p["id"], "eco", eco["object_id"])[
        "unresolved_stock_basis_ids"
    ]
    with workflow.db() as tx:
        opening = tx.execute(
            "SELECT basis_json,complete FROM eco_stock_openings WHERE eco_id=?",
            (eco["object_id"],),
        ).fetchall()
        receipt = tx.execute(
            "SELECT receipt_json,request_json FROM exchanges WHERE id=?",
            (intent["exchange_id"],),
        ).fetchone()
        before = [tuple(r) for r in opening], tuple(receipt)
    proof = workflow.command(
        p["id"],
        "stock_basis.reconcile",
        actor_name="engineering",
        eco_id=eco["object_id"],
        reservation_id=intent["object_id"],
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="engineering",
        exchange_id=proof["exchange_id"],
    )
    assert (
        workflow.object(p["id"], "eco", eco["object_id"])["unresolved_stock_basis_ids"]
        == []
    )
    with workflow.db() as tx:
        assert before == (
            [
                tuple(r)
                for r in tx.execute(
                    "SELECT basis_json,complete FROM eco_stock_openings WHERE eco_id=?",
                    (eco["object_id"],),
                )
            ],
            tuple(
                tx.execute(
                    "SELECT receipt_json,request_json FROM exchanges WHERE id=?",
                    (intent["exchange_id"],),
                ).fetchone()
            ),
        )

    from .test_eco import dispose_all

    dispose_all(workflow, p, eco["object_id"])
    boundary = workflow.command(
        p["id"],
        "eco.switch",
        actor_name="engineering",
        eco_id=eco["object_id"],
        target_work_order_id=supply["work_order_id"],
        boundary="cancel_remaining",
        evidence="Authoritative remaining obligation cancellation",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="engineering",
        exchange_id=boundary["exchange_id"],
    )
    workflow.command(
        p["id"], "eco.close", actor_name="engineering", eco_id=eco["object_id"]
    )
    assert workflow.object(p["id"], "eco", eco["object_id"])["state"] == "closed"


def test_recovery_preserves_new_arrival_disposition_and_rejects_changed_source(
    workflow, monkeypatch
):
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    from .test_eco import dispose_all

    p, supply, intent, eco = legacy_stock_opening(workflow, monkeypatch)
    dispose_all(workflow, p, eco["object_id"])
    workflow.receive(
        p["id"],
        supply["id"],
        quantity="5",
        lot_id=supply["lot_id"],
        source=source_now(workflow, "receipt"),
    )
    original = MockAuthorityAdapter.stock_basis

    def changed(adapter, request):
        proof = original(adapter, request)
        proof.sources[0].source.version += 1
        return proof

    monkeypatch.setattr(MockAuthorityAdapter, "stock_basis", changed)
    bad = workflow.command(
        p["id"],
        "stock_basis.reconcile",
        actor_name="engineering",
        eco_id=eco["object_id"],
        reservation_id=intent["object_id"],
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="engineering",
        exchange_id=bad["exchange_id"],
    )
    assert (
        workflow.object(p["id"], "exchange", bad["exchange_id"])["phase"] == "rejected"
    )
    assert workflow.object(p["id"], "eco", eco["object_id"])[
        "unresolved_stock_basis_ids"
    ]
    monkeypatch.setattr(MockAuthorityAdapter, "stock_basis", original)
    workflow.command(
        p["id"],
        "exchange.query",
        actor_name="engineering",
        exchange_id=bad["exchange_id"],
    )
    current = workflow.object(p["id"], "eco", eco["object_id"])
    assert not current["unresolved_stock_basis_ids"]
    assert any(
        i["type"] == "stock" and i["quantity"] == "5" and i["resolved_quantity"] == "0"
        for i in current["impacts"]
    )
    workflow.command(
        p["id"],
        "eco.close",
        actor_name="engineering",
        eco_id=eco["object_id"],
        expected_status=409,
    )


def test_actual_return_before_unsent_start_blocks_readiness_and_submission(workflow):
    from .test_execution import ready_for_trial

    p, wo, units, authority = ready_for_trial(
        workflow,
        quantity="2",
        trial_quantity="2",
        contract_override={
            "customer_release_required": False,
            "acceptance_required": True,
        },
    )
    start = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=units,
        quantity="2",
    )
    lot = (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/material_lot?limit=1")
        .json()["items"][0]["id"]
    )
    workflow.command(
        p["id"],
        "ownership.movement",
        actor_name="supply",
        material_lot_id=lot,
        material_id="steel-1",
        owner_id="Customer 1",
        unit="kg",
        movement="return",
        quantity="1.000",
        source=source_now(workflow, "material_movement"),
        external_signatory="Customer custodian",
        evidence="Actual return conflicts with still-held WMS reservation",
    )
    wo_detail = workflow.object(p["id"], "work_order", wo["id"])
    assert not wo_detail["trial_readiness"]["ready"]
    requirements = (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/requirement?limit=50")
        .json()["items"]
    )
    assert all(
        r["material_balance"]["shortage"] == "1"
        and r["material_balance"]["blocking_reasons"]
        for r in requirements
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=start["exchange_id"],
    )
    assert authority.operation_count(start["exchange_id"]) == 0


def test_mandatory_owned_source_discrepancy_blocks_quality_not_cost(workflow):
    from .test_exchanges import act, reserve, stock

    p, _, supply, intent = reserve(workflow)
    authority = stock(workflow, p, supply)
    authority.configure_fault("wrong_unit")
    act(workflow, p, intent)
    workflow.command(
        p["id"],
        "closure.record",
        kind="quality",
        source=source_now(workflow, "closure"),
        evidence="Cannot ignore malformed source",
        expected_status=409,
    )
    workflow.command(
        p["id"],
        "closure.record",
        kind="cost",
        source=source_now(workflow, "closure"),
        evidence="Independent manual cost reconciliation",
    )


def test_foreign_shipment_receipt_is_not_visible_and_query_recovers_same_operation(
    workflow, monkeypatch
):
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    p, order, units = workflow.released_order(quantity="1")
    original = MockAuthorityAdapter.submit
    foreign = uuid4()

    def changed(adapter, request):
        result = original(adapter, request)
        if request.action == "shipment.request":
            result.details[0].order_line_id = foreign
        return result

    monkeypatch.setattr(MockAuthorityAdapter, "submit", changed)
    shipment = workflow.ship(p["id"], order["id"], [units[0]["id"]])
    exchange = workflow.object(p["id"], "exchange", shipment["exchange_id"])
    assert exchange["phase"] == "rejected" and exchange["receipt"] is None
    assert str(foreign) not in str(exchange)
    workflow.ship(p["id"], order["id"], [units[0]["id"]], expected_status=409)
    workflow.command(
        p["id"],
        "exchange.query",
        actor_name="warehouse",
        exchange_id=shipment["exchange_id"],
    )
    assert workflow.object(p["id"], "shipment", shipment["id"])["shipped"] == "1"
    assert (
        MockAuthorityAdapter(
            str(workflow.paths.authority), "workflow-test"
        ).operation_count(shipment["id"])
        == 1
    )


def test_material_movement_corrections_preserve_identity_and_prior_facts(workflow):
    p, _, _ = workflow.released_order(quantity="1")
    lot = (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/material_lot?limit=1")
        .json()["items"][0]["id"]
    )
    base = dict(
        material_lot_id=lot,
        material_id="steel-1",
        owner_id="Customer 1",
        unit="kg",
        movement="return",
        external_signatory="Named material custodian",
        evidence="Actual scale correction",
    )
    workflow.command(
        p["id"],
        "ownership.movement",
        actor_name="supply",
        **base,
        quantity="0.500",
        source=source_now(workflow, "material_movement"),
    )
    original = workflow.object(p["id"], "material_lot", lot)["material_movements"][0]
    workflow.command(
        p["id"],
        "ownership.movement",
        actor_name="supply",
        **base,
        quantity="0.250",
        supersedes_id=original["id"],
        source=source_now(workflow, "material_movement"),
    )
    detail = workflow.object(p["id"], "material_lot", lot)
    assert detail["ownership_balance"]["returned"] == "0.250"
    assert len(detail["material_movements"]) == 2
    assert (
        next(m for m in detail["material_movements"] if m["id"] == original["id"])[
            "quantity"
        ]
        == "0.500"
    )
    workflow.command(
        p["id"],
        "ownership.movement",
        actor_name="supply",
        **base,
        quantity="0.200",
        supersedes_id=original["id"],
        source=source_now(workflow, "material_movement"),
        expected_status=409,
    )


@pytest.mark.parametrize("fault", ["foreign", "stale", "later_arrival"])
def test_original_stock_proof_rejects_foreign_stale_or_later_evidence(
    workflow, monkeypatch, fault
):
    from datetime import timedelta
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    p, _, intent, eco = legacy_stock_opening(workflow, monkeypatch)
    original = MockAuthorityAdapter.stock_basis

    def corrupt(adapter, request):
        proof = original(adapter, request)
        if fault == "foreign":
            proof.sources[0].project_id = uuid4()
        elif fault == "stale":
            proof.receipt.sequence = 0
        else:
            proof.sources[0].source.collected_at = (
                proof.receipt.occurred_at + timedelta(seconds=1)
            )
        return proof

    monkeypatch.setattr(MockAuthorityAdapter, "stock_basis", corrupt)
    request = workflow.command(
        p["id"],
        "stock_basis.reconcile",
        actor_name="engineering",
        eco_id=eco["object_id"],
        reservation_id=intent["object_id"],
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="engineering",
        exchange_id=request["exchange_id"],
    )
    view = workflow.object(p["id"], "exchange", request["exchange_id"])
    assert view["phase"] == "rejected" and view["stock_basis_proof"] is None
    assert workflow.object(p["id"], "eco", eco["object_id"])[
        "unresolved_stock_basis_ids"
    ]


def test_quality_closure_cannot_ignore_failed_measured_output_without_nc(workflow):
    p, unit = workflow.executed_unit()
    workflow.test(p["id"], unit["id"], measured="12")
    workflow.command(
        p["id"],
        "closure.record",
        kind="quality",
        source=source_now(workflow, "closure"),
        evidence="Measured failure needs qualified disposition",
        expected_status=409,
    )
