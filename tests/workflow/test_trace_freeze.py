"""C3 public trace and actual authority freeze acceptance."""

from uuid import uuid4

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
