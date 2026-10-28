"""C3 public trace and actual authority freeze acceptance."""

from uuid import uuid4

import pytest

from .conftest import BASE


def freeze(workflow, pid, *, units=(), lots=(), state="frozen"):
    return workflow.command(
        pid,
        "freeze.request",
        actor_name="quality",
        unit_ids=list(units),
        lot_ids=list(lots),
        state=state,
        reason="suspect material",
    )


def dispatch(workflow, pid, result, action="exchange.dispatch"):
    workflow.command(
        pid, action, actor_name="quality", exchange_id=result["exchange_id"]
    )
    return workflow.object(pid, "exchange", result["exchange_id"])


def test_pending_freeze_does_not_claim_authority_confirmation(workflow):
    p, order, units = workflow.released_order(quantity="2")
    result = freeze(workflow, p["id"], units=[units[0]["id"]])
    detail = workflow.object(p["id"], "unit", units[0]["id"])
    assert detail["freeze_requested"] == "frozen"
    assert detail["freeze_confirmed"] != "frozen"
    workflow.ship(p["id"], order["id"], [units[0]["id"]], expected_status=409)
    assert dispatch(workflow, p["id"], result)["phase"] == "accepted"
    assert (
        workflow.object(p["id"], "unit", units[0]["id"])["freeze_confirmed"] == "frozen"
    )
    release = freeze(workflow, p["id"], units=[units[0]["id"]], state="unfrozen")
    workflow.ship(p["id"], order["id"], [units[0]["id"]], expected_status=409)
    assert dispatch(workflow, p["id"], release)["phase"] == "accepted"
    assert workflow.ship(p["id"], order["id"], [units[0]["id"]])["shipped"] == "1"


def test_late_older_unfreeze_cannot_override_new_freeze(workflow):
    p, order, units = workflow.released_order(quantity="1")
    old = freeze(workflow, p["id"], units=[units[0]["id"]], state="unfrozen")
    newer = freeze(workflow, p["id"], units=[units[0]["id"]])
    assert dispatch(workflow, p["id"], newer)["phase"] == "accepted"
    assert dispatch(workflow, p["id"], old)["phase"] == "rejected"
    assert (
        workflow.object(p["id"], "unit", units[0]["id"])["freeze_confirmed"] == "frozen"
    )
    workflow.ship(p["id"], order["id"], [units[0]["id"]], expected_status=409)


def test_freeze_unknown_query_recovers_one_effect_and_retains_shipment(workflow):
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    p, order, units = workflow.released_order(quantity="1")
    shipment = workflow.ship(p["id"], order["id"], [units[0]["id"]])
    result = freeze(workflow, p["id"], units=[units[0]["id"]])
    authority = MockAuthorityAdapter(str(workflow.paths.authority), "workflow-test")
    authority.configure_fault("timeout_after_commit")
    assert dispatch(workflow, p["id"], result)["phase"] == "unknown"
    assert (
        workflow.object(p["id"], "unit", units[0]["id"])["freeze_confirmed"] != "frozen"
    )
    authority.configure_fault("none")
    assert dispatch(workflow, p["id"], result, "exchange.query")["phase"] == "accepted"
    assert (
        authority.operation_count(
            workflow.object(p["id"], "exchange", result["exchange_id"])["business_key"]
        )
        == 1
    )
    assert workflow.object(p["id"], "shipment", shipment["id"])["shipped"] == "1"
    workflow.ship(p["id"], order["id"], [units[0]["id"]], expected_status=409)


def test_trace_exact_forward_reverse_and_bounded_scope(workflow):
    p, order, units = workflow.released_order(quantity="2")
    shipment = workflow.ship(p["id"], order["id"], [units[0]["id"]])
    unit = workflow.object(p["id"], "unit", units[0]["id"])
    lot = unit["execution_events"][0]["material_uses"][0]["lot_id"]
    url = f"{BASE}/projects/{p['id']}/trace"
    forward = workflow.client().get(url, params={"material_lot_id": lot})
    assert forward.status_code == 200, forward.text
    graph = forward.json()
    assert {n["id"] for n in graph["nodes"] if n["kind"] == "unit"} == {
        u["id"] for u in units
    }
    assert {n["customer_id"] for n in graph["nodes"] if n["kind"] == "order_line"} == {
        "Customer 1"
    }
    reverse = workflow.client().get(url, params={"sn": unit["sn"]}).json()
    assert {n["id"] for n in reverse["nodes"] if n["kind"] == "unit"} == {unit["id"]}
    assert {n["kind"] for n in reverse["nodes"]} >= {
        "revision",
        "material_lot",
        "test",
        "shipment",
        "order_line",
    }
    assert shipment["id"] in {n["id"] for n in reverse["nodes"]}
    capped = (
        workflow.client().get(url, params={"material_lot_id": lot, "limit": 2}).json()
    )
    assert len(capped["nodes"]) <= 2 and capped["truncated"] is True
    assert all(
        e["source_id"] in {n["id"] for n in capped["nodes"]}
        and e["target_id"] in {n["id"] for n in capped["nodes"]}
        for e in capped["edges"]
    )
    other = workflow.create_project(customer_id="Other customer")
    for foreign_url, params in [
        (url, {"sn": "unknown"}),
        (url, {"material_lot_id": str(uuid4())}),
        (f"{BASE}/projects/{other['id']}/trace", {"sn": unit["sn"]}),
        (f"{BASE}/projects/{other['id']}/trace", {"material_lot_id": lot}),
    ]:
        response = workflow.client().get(foreign_url, params=params)
        assert response.status_code == 404 and "nodes" not in response.json()


def test_continuing_lot_hold_blocks_authority_shipment_and_future_material_use(
    workflow,
):
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter
    from manufacturing_platform.workflow.exchange_models import ExternalRequest

    p, order, units = workflow.released_order(quantity="2")
    unit = workflow.object(p["id"], "unit", units[0]["id"])
    lot = unit["execution_events"][0]["material_uses"][0]["lot_id"]
    pending = workflow.ship(p["id"], order["id"], [units[1]["id"]], dispatch=False)
    result = freeze(workflow, p["id"], lots=[lot])
    assert workflow.object(p["id"], "material_lot", lot)["freeze_requested"] == "frozen"
    assert dispatch(workflow, p["id"], result)["phase"] == "accepted"
    authority = MockAuthorityAdapter(str(workflow.paths.authority), "workflow-test")
    with workflow.db() as db:
        raw = db.execute(
            "SELECT request_json FROM exchanges WHERE id=?", (pending["exchange_id"],)
        ).fetchone()[0]
    receipt = authority.submit(ExternalRequest.model_validate_json(raw))
    assert receipt.phase == "rejected"  # source order, after actual lot hold
    workflow.command(
        p["id"],
        "exchange.query",
        actor_name="warehouse",
        exchange_id=pending["exchange_id"],
    )
    assert workflow.object(p["id"], "shipment", pending["id"])["shipped"] == "0"
    workflow.ship(p["id"], order["id"], [units[0]["id"]], expected_status=409)
    assert (
        "containment"
        in workflow.object(p["id"], "material_lot", lot)["ownership_balance"][
            "hold_reason"
        ]
    )


def test_unit_containment_blocks_new_execution_and_release_without_claiming_physical_stop(
    workflow,
):
    from datetime import UTC, datetime

    p, _, units = workflow.released_order(quantity="1")
    unit = workflow.object(p["id"], "unit", units[0]["id"])
    freeze(workflow, p["id"], units=[unit["id"]])
    event = unit["execution_events"][0]
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
        material_uses=[
            {k: event["material_uses"][0][k] for k in ("lot_id", "quantity", "unit")}
        ],
        result="pass",
        occurred_at=datetime.now(UTC).isoformat(),
        source=workflow.source(str(uuid4()), object_type="execution"),
    )
    now = workflow.object(p["id"], "unit", unit["id"])
    assert now["execution_events"][-1]["status"] == "rejected"
    assert now["state"] == "running"
    workflow.command(
        p["id"],
        "release.decide",
        actor_name="quality",
        kind="quality",
        unit_ids=[unit["id"]],
        decision="approved",
        evidence="Cannot release under containment",
        expected_status=409,
    )


def test_source_shipment_before_freeze_retains_actual_effect_on_late_query(workflow):
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    p, order, units = workflow.released_order(quantity="1")
    authority = MockAuthorityAdapter(str(workflow.paths.authority), "workflow-test")
    authority.configure_fault("timeout_after_commit")
    pending = workflow.ship(p["id"], order["id"], [units[0]["id"]])
    assert pending["shipped"] == "0"
    authority.configure_fault("none")
    f = freeze(workflow, p["id"], units=[units[0]["id"]])
    dispatch(workflow, p["id"], f)
    workflow.command(
        p["id"],
        "exchange.query",
        actor_name="warehouse",
        exchange_id=pending["exchange_id"],
    )
    physical = workflow.object(p["id"], "shipment", pending["id"])
    assert physical["shipped"] == "1" and physical["state"] == "held"


def test_trace_preserves_failure_retest_causal_edges_and_omits_rejected_claims(
    workflow,
):
    from datetime import UTC, datetime

    p, unit = workflow.executed_unit()
    failed = workflow.test(p["id"], unit["id"], measured="7")
    rework = workflow.rework(p["id"], failed["id"])
    retest = workflow.test(
        p["id"], unit["id"], measured="5", rework_order_id=rework["id"]
    )
    _other, _, scope = workflow.material_requirement(required="1", qualified="1")
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
        material_uses=[{"lot_id": scope["lot_id"], "quantity": "0.001", "unit": "kg"}],
        result="pass",
        occurred_at=datetime.now(UTC).isoformat(),
        source=workflow.source(str(uuid4()), object_type="execution"),
    )
    response = workflow.client().get(
        f"{BASE}/projects/{p['id']}/trace", params={"sn": unit["sn"]}
    )
    assert response.status_code == 200, response.text
    graph = response.json()
    assert {failed["id"], retest["id"], rework["id"]} <= {
        n["id"] for n in graph["nodes"]
    }
    assert scope["lot_id"] not in {n["id"] for n in graph["nodes"]}
    assert {
        "source_kind": "test",
        "source_id": failed["id"],
        "target_kind": "test",
        "target_id": retest["id"],
        "relation": "prior_test",
    } in graph["edges"]


def test_pending_lot_prevents_new_unstarted_scope_and_authority_respects_order(
    workflow,
):
    from manufacturing_platform.workflow.exchange_models import ExternalRequest

    from .test_execution import ready_for_trial

    p, wo, units, authority = ready_for_trial(
        workflow, quantity="2", trial_quantity="2"
    )
    workflow.grant(p["id"], "quality", ["quality"], ["disposition"])
    start = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        unit_ids=units[:1],
        mode="trial",
        quantity="1",
    )
    lot = (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/material_lot")
        .json()["items"][0]["id"]
    )
    result = freeze(workflow, p["id"], lots=[lot])
    assert (
        workflow.object(p["id"], "work_order", wo["id"])["trial_readiness"]["ready"]
        is False
    )
    workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        unit_ids=units[1:],
        mode="trial",
        quantity="1",
        expected_status=409,
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=start["exchange_id"],
    )
    assert authority.operation_count(start["exchange_id"]) == 0
    dispatch(workflow, p["id"], result)
    with workflow.db() as db:
        raw = db.execute(
            "SELECT request_json FROM exchanges WHERE id=?", (start["exchange_id"],)
        ).fetchone()[0]
    assert (
        authority.submit(ExternalRequest.model_validate_json(raw)).phase == "rejected"
    )
    workflow.command(
        p["id"],
        "exchange.query",
        actor_name="production",
        exchange_id=start["exchange_id"],
    )
    assert (
        workflow.object(p["id"], "unit", units[0])["authority_start_accepted"] is False
    )


def test_late_earlier_actual_freeze_reply_is_audited_without_replacing_newer_state(
    workflow,
):
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter
    from manufacturing_platform.workflow.exchange_models import ExternalRequest

    p, _, units = workflow.released_order(quantity="1")
    old = freeze(workflow, p["id"], units=[units[0]["id"]])
    authority = MockAuthorityAdapter(str(workflow.paths.authority), "workflow-test")
    with workflow.db() as db:
        raw = db.execute(
            "SELECT request_json FROM exchanges WHERE id=?", (old["exchange_id"],)
        ).fetchone()[0]
    assert (
        authority.submit(ExternalRequest.model_validate_json(raw)).phase == "accepted"
    )
    newer = freeze(workflow, p["id"], units=[units[0]["id"]], state="unfrozen")
    assert dispatch(workflow, p["id"], newer)["phase"] == "accepted"
    assert dispatch(workflow, p["id"], old, "exchange.query")["phase"] == "rejected"
    unit = workflow.object(p["id"], "unit", units[0]["id"])
    assert (
        unit["freeze_confirmed"] == "unfrozen"
        and unit["freeze_requested"] == "unfrozen"
    )
    assert workflow.object(p["id"], "exchange", old["exchange_id"])["events"]


def test_foreign_freeze_receipt_detail_never_becomes_visible_and_query_recovers(
    workflow, monkeypatch
):
    from uuid import UUID

    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    p, _, units = workflow.released_order(quantity="1")
    _other, _, other_units = workflow.released_order(quantity="1")
    original = MockAuthorityAdapter.submit

    def corrupt(adapter, request):
        receipt = original(adapter, request)
        if request.action == "freeze.request":
            receipt.details[0].object_id = UUID(other_units[0]["id"])
            receipt.details[0].key = "foreign-secret"
        return receipt

    monkeypatch.setattr(MockAuthorityAdapter, "submit", corrupt)
    f = freeze(workflow, p["id"], units=[units[0]["id"]])
    denied = dispatch(workflow, p["id"], f)
    assert denied["phase"] == "rejected" and denied["receipt"] is None
    read = workflow.client().get(
        f"{BASE}/projects/{p['id']}/objects/exchange/{f['exchange_id']}"
    )
    assert other_units[0]["id"] not in read.text and "foreign-secret" not in read.text
    assert dispatch(workflow, p["id"], f, "exchange.query")["phase"] == "accepted"
    assert (
        workflow.object(p["id"], "unit", units[0]["id"])["freeze_confirmed"] == "frozen"
    )


def test_trace_exact_node_budget_retains_shared_edges_without_false_truncation(
    workflow,
):
    p, _, units = workflow.released_order(quantity="2")
    unit = workflow.object(p["id"], "unit", units[0]["id"])
    lot = unit["execution_events"][0]["material_uses"][0]["lot_id"]
    url = f"{BASE}/projects/{p['id']}/trace"
    full = workflow.client().get(url, params={"material_lot_id": lot}).json()
    exact = (
        workflow.client()
        .get(url, params={"material_lot_id": lot, "limit": len(full["nodes"])})
        .json()
    )
    assert exact["truncated"] is False
    assert exact["edges"] == full["edges"]


def legacy_intent(workflow, monkeypatch, action, scope=None):
    """Run public preparation with the pre-C3 optional-field serialization only."""
    import json

    from manufacturing_platform.workflow.adapters.mock import (
        MockAuthorityAdapter,
        digest,
    )
    from manufacturing_platform.workflow.exchange_models import ExternalRequest
    from manufacturing_platform.workflow.exchanges import ExchangeService

    from .test_execution import ready_for_trial, review_replan, running_execution

    original = ExchangeService.prepare

    def prepare(self, tx, context, request):
        if request.action == action:
            request = request.model_copy(
                update={
                    "typed_payload": request.typed_payload.model_copy(
                        update={"material_lot_ids": scope}
                    )
                }
            )
        return original(self, tx, context, request)

    if action == "shipment.request":
        p, order, units = workflow.released_order(quantity="1")
        uid = units[0]["id"]
        authority = MockAuthorityAdapter(str(workflow.paths.authority), "workflow-test")
    elif action == "production.resume":
        p, wo, units, authority, _ = running_execution(workflow)
        uid = units[0]
        stop = workflow.command(
            p["id"],
            "production.interrupt",
            actor_name="production",
            work_order_id=wo["id"],
            reason="legacy resume containment test",
        )
        workflow.command(
            p["id"],
            "exchange.dispatch",
            actor_name="production",
            exchange_id=stop["exchange_id"],
        )
        plan = review_replan(workflow, p, wo)
    else:
        p, wo, units, authority = ready_for_trial(
            workflow, quantity="2", trial_quantity="2"
        )
        uid = units[0]
    workflow.grant(p["id"], "quality", ["quality"])
    with monkeypatch.context() as patch:
        patch.setattr(ExchangeService, "prepare", prepare)
        if action == "shipment.request":
            intent = workflow.ship(p["id"], order["id"], [uid], dispatch=False)
        elif action == "production.resume":
            intent = workflow.command(
                p["id"],
                action,
                actor_name="production",
                interruption_id=stop["object_id"],
                plan_id=plan,
                evidence="resume with original legacy protocol",
            )
        else:
            intent = workflow.command(
                p["id"],
                action,
                actor_name="production",
                work_order_id=wo["id"],
                mode="trial",
                unit_ids=[uid],
                quantity="1",
            )
    with workflow.db() as tx:
        row = dict(
            tx.execute(
                "SELECT * FROM exchanges WHERE id=?", (intent["exchange_id"],)
            ).fetchone()
        )
        lot = tx.execute(
            "SELECT material_lot_id FROM reservations WHERE project_id=? LIMIT 1",
            (p["id"],),
        ).fetchone()[0]
    request = ExternalRequest.model_validate_json(row["request_json"])
    assert ("material_lot_ids" in json.loads(row["request_json"])["typed_payload"]) == (
        scope is not None
    )
    assert request.model_dump_json() == row["request_json"]
    assert digest(request.model_dump(mode="json")) == row["request_hash"]
    return p["id"], uid, lot, intent, authority, request, row


@pytest.mark.parametrize(
    "action", ["production.start", "production.resume", "shipment.request"]
)
@pytest.mark.parametrize("scope", [None, []], ids=["omitted", "explicit-empty"])
def test_review_legacy_first_effect_after_lot_freeze_is_rejected(
    workflow, monkeypatch, action, scope
):
    pid, uid, lot, intent, authority, request, row = legacy_intent(
        workflow, monkeypatch, action, scope
    )
    assert (
        dispatch(workflow, pid, freeze(workflow, pid, lots=[lot]))["phase"]
        == "accepted"
    )
    # Actual source first submission, after containment: bypass local preflight deliberately.
    receipt = authority.submit(request)
    assert receipt.phase == "rejected"
    assert str(receipt.accepted_quantity) == "0"
    assert receipt.request_hash == row["request_hash"]
    assert (
        receipt.error
        == "Applicable material is frozen; source owner must confirm containment release"
    )
    assert authority.operation_count(request.business_key) == 1
    assert authority.query("erp", request.business_key) == receipt
    workflow.command(
        pid,
        "exchange.query",
        actor_name="warehouse" if action == "shipment.request" else "production",
        exchange_id=intent["exchange_id"],
    )
    exchange = workflow.object(pid, "exchange", intent["exchange_id"])
    assert exchange["phase"] == "rejected"
    assert exchange["reason"] == receipt.error
    if action == "production.start":
        # Rejected starts release their pending local membership; the existing
        # projection then suppresses the receipt, but retains the owned reason.
        assert exchange["receipt"] is None
        assert exchange["discrepancies"][0]["reason"] == "Authority rejected request"
    else:
        assert exchange["receipt"]["error"] == receipt.error
    with workflow.db() as tx:
        final = tx.execute(
            "SELECT request_json,request_hash FROM exchanges WHERE id=?",
            (intent["exchange_id"],),
        ).fetchone()
    assert tuple(final) == (row["request_json"], row["request_hash"])
    unit = workflow.object(pid, "unit", uid)
    if action == "production.start":
        assert unit["authority_start_accepted"] is False
    elif action == "production.resume":
        assert unit["state"] == "stopped"
    else:
        assert workflow.object(pid, "shipment", intent["id"])["shipped"] == "0"


@pytest.mark.parametrize(
    "action", ["production.start", "production.resume", "shipment.request"]
)
def test_review_legacy_prior_commit_survives_lot_freeze_and_lost_reply(
    workflow, monkeypatch, action
):
    pid, uid, lot, intent, authority, request, row = legacy_intent(
        workflow, monkeypatch, action
    )
    authority.configure_fault("timeout_after_commit")
    actor = "warehouse" if action == "shipment.request" else "production"
    workflow.command(
        pid, "exchange.dispatch", actor_name=actor, exchange_id=intent["exchange_id"]
    )
    assert workflow.object(pid, "exchange", intent["exchange_id"])["phase"] == "unknown"
    authority.configure_fault("none")
    original = authority.query("erp", request.business_key)
    assert original.phase == "accepted" and str(original.accepted_quantity) == "1"
    assert original.request_hash == row["request_hash"]
    assert (
        dispatch(workflow, pid, freeze(workflow, pid, lots=[lot]))["phase"]
        == "accepted"
    )
    assert authority.submit(request) == original
    workflow.command(
        pid, "exchange.query", actor_name=actor, exchange_id=intent["exchange_id"]
    )
    assert (
        workflow.object(pid, "exchange", intent["exchange_id"])["phase"] == "accepted"
    )
    assert authority.operation_count(request.business_key) == 1
    with workflow.db() as tx:
        final = tx.execute(
            "SELECT request_json,request_hash FROM exchanges WHERE id=?",
            (intent["exchange_id"],),
        ).fetchone()
    assert tuple(final) == (row["request_json"], row["request_hash"])
    if action == "shipment.request":
        assert workflow.object(pid, "shipment", intent["id"])["shipped"] == "1"
        with authority.store.transaction() as tx:
            assert (
                tx.execute(
                    "SELECT COUNT(*) FROM authority_shipments WHERE unit_id=?", (uid,)
                ).fetchone()[0]
                == 1
            )
    else:
        unit = workflow.object(pid, "unit", uid)
        assert unit["authority_start_accepted"] is True
        assert unit["state"] == "start_pending"  # Existing B3 local safety recovery.
        with authority.store.transaction() as tx:
            assert (
                tx.execute(
                    "SELECT state FROM authority_start_units WHERE unit_id=?", (uid,)
                ).fetchone()[0]
                == "running"
            )
            assert (
                tx.execute(
                    "SELECT w.started_units FROM authority_work_orders w JOIN authority_start_units u ON u.project_id=w.project_id AND u.work_order_id=w.work_order_id WHERE u.unit_id=?",
                    (uid,),
                ).fetchone()[0]
                == 1
            )


@pytest.mark.parametrize(
    "action", ["production.start", "production.resume", "shipment.request"]
)
def test_review_legacy_unknown_material_scope_fails_closed(
    workflow, monkeypatch, action
):
    pid, _, _, intent, authority, request, row = legacy_intent(
        workflow, monkeypatch, action
    )
    # External source fault only: reservation physical quantities remain, but
    # accepted receipt proof is unavailable. No local/business success is seeded.
    with authority.store.transaction(write=True) as tx:
        physical_before = [
            tuple(r)
            for r in tx.execute(
                "SELECT id,lot_id,q_atoms FROM authority_reservations WHERE project_id=? ORDER BY id",
                (pid,),
            )
        ]
        tx.execute(
            "UPDATE authority_operations SET receipt_json=NULL WHERE business_key IN (SELECT business_key FROM authority_reservations WHERE project_id=?)",
            (pid,),
        )
    receipt = authority.submit(request)
    assert receipt.phase == "rejected"
    assert (
        receipt.error
        == "Material scope unproven; source owner must reconcile work-order reservation evidence"
    )
    assert authority.operation_count(request.business_key) == 1
    workflow.command(
        pid,
        "exchange.query",
        actor_name="warehouse" if action == "shipment.request" else "production",
        exchange_id=intent["exchange_id"],
    )
    exchange = workflow.object(pid, "exchange", intent["exchange_id"])
    assert exchange["phase"] == "rejected" and exchange["reason"] == receipt.error
    with workflow.db() as tx:
        final = tx.execute(
            "SELECT request_json,request_hash FROM exchanges WHERE id=?",
            (intent["exchange_id"],),
        ).fetchone()
    assert tuple(final) == (row["request_json"], row["request_hash"])
    with authority.store.transaction() as tx:
        assert [
            tuple(r)
            for r in tx.execute(
                "SELECT id,lot_id,q_atoms FROM authority_reservations WHERE project_id=? ORDER BY id",
                (pid,),
            )
        ] == physical_before


@pytest.mark.parametrize(
    "action", ["production.start", "production.resume", "shipment.request"]
)
def test_review_legacy_proven_scope_ignores_unrelated_frozen_lot(
    workflow, monkeypatch, action
):
    pid, _, _, _, authority, request, _ = legacy_intent(workflow, monkeypatch, action)
    from datetime import UTC, datetime, timedelta

    unrelated = workflow.command(
        pid,
        "material.define",
        actor_name="supply",
        material_id="unrelated-material",
        lot_id="unrelated-lot",
        owner_id="Customer 1",
        unit="kg",
        scale=3,
        expiry=(datetime.now(UTC) + timedelta(days=120)).date().isoformat(),
        source=workflow.source(str(uuid4()), object_type="material_lot"),
    )["object_id"]
    assert (
        dispatch(workflow, pid, freeze(workflow, pid, lots=[unrelated]))["phase"]
        == "accepted"
    )
    assert authority.submit(request).phase == "accepted"
    assert authority.operation_count(request.business_key) == 1


def test_reserved_lot_without_movements_has_same_freeze_balance_in_list_and_detail(workflow):
    from .test_execution import ready_for_trial

    p, _, _, _ = ready_for_trial(workflow, quantity="1", trial_quantity="1")
    workflow.grant(p["id"], "quality", ["quality"], ["inspection", "disposition", "quality_release"])
    with workflow.db() as db:
        lot = db.execute("SELECT id FROM material_lots WHERE project_id=?", (p["id"],)).fetchone()[0]
        assert db.execute("SELECT COUNT(*) FROM material_movements").fetchone()[0] == 0
    pending = freeze(workflow, p["id"], lots=[lot])
    for phase in ("pending", "confirmed", "unfreeze_pending"):
        if phase == "confirmed":
            dispatch(workflow, p["id"], pending)
        if phase == "unfreeze_pending":
            freeze(workflow, p["id"], lots=[lot], state="unfrozen")
        response = workflow.client().get(f"{BASE}/projects/{p['id']}/objects/requirement?limit=1&offset=0")
        assert response.status_code == 200
        page = response.json()
        assert len(page["items"]) == 1 and page["total"] == 2
        item = page["items"][0]
        detail = workflow.balance(p["id"], item["id"])
        assert item["material_balance"] == detail, phase
        assert detail["reserved"] == "1" and detail["shortage"] == "1"
        assert "containment" in detail["blocking_reasons"][0]
