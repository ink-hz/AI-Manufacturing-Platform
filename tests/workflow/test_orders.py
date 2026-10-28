"""A2 contract tests through the authorized workflow API."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from pydantic import ValidationError

from manufacturing_platform.workflow.contracts import (
    ObjectSummary,
    ProjectDetail,
    ProjectStageView,
)
from manufacturing_platform.workflow.order_models import ChangeImpact, OrderLineValue
from manufacturing_platform.workflow.store import WorkflowStore

from .conftest import BASE

DIMENSIONS = ("technical", "material", "capacity", "commercial", "quality")


def record(workflow, project_id, kind="firm", external_id="demand-1", **extra):
    return workflow.command(
        project_id,
        "demand.record",
        kind=kind,
        product="Camera",
        quantity="100",
        unit="piece",
        due_date="2026-12-01",
        source=workflow.source(external_id),
        **extra,
    )["object_id"]


def approve(workflow, project_id, demand_id):
    for dimension in DIMENSIONS:
        workflow.command(
            project_id,
            "demand.review",
            demand_id=demand_id,
            dimension=dimension,
            decision="approved",
            evidence=f"{dimension} reviewed",
        )


def register(workflow, project_id, demand_id, external_id="order-1", **extra):
    return workflow.command(
        project_id,
        "order.register",
        demand_id=demand_id,
        quantity="100",
        unit="piece",
        due_date="2026-12-01",
        source=workflow.source(external_id, object_type="order_line"),
        **extra,
    )["object_id"]


def test_forecast_cannot_become_order_without_firm_source(workflow):
    p = workflow.create_project()
    demand = record(workflow, p["id"], kind="forecast", external_id="forecast-1")
    approve(workflow, p["id"], demand)
    response = workflow.command(
        p["id"],
        "order.register",
        demand_id=demand,
        quantity="100",
        unit="piece",
        due_date="2026-12-01",
        source=workflow.source("order-1", object_type="order_line"),
        expected_status=409,
    )
    assert response["code"] == "PRECONDITION_FAILED"
    firm = record(workflow, p["id"], external_id="firm-1", supersedes_demand_id=demand)
    approve(workflow, p["id"], firm)
    order = register(workflow, p["id"], firm)
    detail = (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/order_line/{order}")
        .json()
    )
    assert detail["value"]["original_quantity"] == "100"
    assert detail["value"]["source"]["mode"] == "manual"
    assert {r["relation"] for r in detail["relations"]} == {"formal_demand"}
    assert detail["history"][0]["action"] == "order.register"


def test_five_reviews_are_independent_and_rejection_blocks(workflow):
    p = workflow.create_project()
    demand = record(workflow, p["id"])
    for dimension in DIMENSIONS[:-1]:
        workflow.command(
            p["id"],
            "demand.review",
            demand_id=demand,
            dimension=dimension,
            decision="approved",
            evidence="reviewed",
        )
    blocked = workflow.command(
        p["id"],
        "order.register",
        demand_id=demand,
        quantity="100",
        unit="piece",
        due_date="2026-12-01",
        source=workflow.source("order-2", object_type="order_line"),
        expected_status=409,
    )
    assert "quality" in blocked["blocking_reasons"]
    workflow.command(
        p["id"],
        "demand.review",
        demand_id=demand,
        dimension="quality",
        decision="rejected",
        evidence="defect",
    )
    assert (
        workflow.command(
            p["id"],
            "order.register",
            demand_id=demand,
            quantity="100",
            unit="piece",
            due_date="2026-12-01",
            source=workflow.source("order-2", object_type="order_line"),
            expected_status=409,
        )["code"]
        == "PRECONDITION_FAILED"
    )
    workflow.command(
        p["id"],
        "demand.review",
        demand_id=demand,
        dimension="quality",
        decision="approved",
        evidence="resolved",
    )
    assert (
        workflow.command(
            p["id"],
            "order.register",
            demand_id=demand,
            quantity="100",
            unit="piece",
            due_date="2027-01-01",
            source=workflow.source("order-wrong-due", object_type="order_line"),
            expected_status=409,
        )["code"]
        == "PRECONDITION_FAILED"
    )
    register(workflow, p["id"], demand, external_id="order-2")


def test_source_collision_cross_project_and_quantity_validation(workflow):
    p = workflow.create_project()
    other = workflow.create_project()
    demand = record(workflow, p["id"])
    assert (
        workflow.command(
            other["id"],
            "demand.record",
            kind="firm",
            product="Camera",
            quantity="100",
            unit="piece",
            due_date="2026-12-01",
            source=workflow.source("demand-1"),
            expected_status=409,
        )["code"]
        == "SOURCE_CONFLICT"
    )
    assert (
        workflow.command(
            other["id"],
            "demand.record",
            kind="firm",
            product="Camera",
            quantity="100",
            unit="piece",
            due_date="2026-12-01",
            source=workflow.source("new"),
            supersedes_demand_id=demand,
            expected_status=404,
        )["code"]
        == "NOT_FOUND"
    )
    for quantity in ("0", "-1", "1e2"):
        assert workflow.command(
            p["id"],
            "demand.record",
            kind="firm",
            product="Camera",
            quantity=quantity,
            unit="piece",
            due_date="2026-12-01",
            source=workflow.source(f"invalid-{quantity}"),
            expected_status=422,
        )
    assert (
        workflow.command(
            p["id"],
            "demand.record",
            kind="firm",
            product="Camera",
            quantity="1.5",
            unit="piece",
            due_date="2026-12-01",
            source=workflow.source("bad-precision"),
            expected_status=409,
        )["code"]
        == "PRECONDITION_FAILED"
    )
    assert (
        workflow.command(
            p["id"],
            "demand.record",
            kind="firm",
            product="Camera",
            quantity="1",
            unit="kg",
            due_date="2026-12-01",
            source=workflow.source("bad-unit"),
            expected_status=409,
        )["code"]
        == "PRECONDITION_FAILED"
    )


def test_order_change_keeps_original_and_pending_impacts(workflow):
    p = workflow.create_project()
    demand = record(workflow, p["id"])
    approve(workflow, p["id"], demand)
    order = register(workflow, p["id"], demand)
    change = workflow.command(
        p["id"],
        "order.change",
        order_line_id=order,
        new_quantity="120",
        new_due_date="2027-01-01",
        cancel=False,
        reason="customer requested",
        source=workflow.source("order-1", version=2, object_type="order_line"),
    )
    order_detail = (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/order_line/{order}")
        .json()
    )
    assert order_detail["value"]["original_quantity"] == "100"
    assert order_detail["value"]["current_quantity"] == "100"
    change_detail = (
        workflow.client()
        .get(
            f"{BASE}/projects/{p['id']}/objects/commitment_change/{change['object_id']}"
        )
        .json()
    )
    assert change_detail["value"]["state"] == "pending"
    assert change_detail["value"]["new_quantity"] == "120"
    workflow.command(
        p["id"], "order.resolve_change", change_id=change["object_id"], dispositions=[]
    )
    current = workflow.client().get(f"{BASE}/projects/{p['id']}").json()["summary"]
    assert current["original_order_quantity"] == "100"
    assert current["current_order_quantity"] == "120"
    assert current["remaining_to_ship"] == "120"
    assert current["remaining_to_accept"] == "120"
    order_history = (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/order_line/{order}")
        .json()["history"]
    )
    assert [event["action"] for event in order_history] == [
        "order.register",
        "order.change",
        "order.resolve_change",
    ]
    assert order_history[0]["evidence"][0]["source"]["version"] == 1
    assert order_history[1]["evidence"][0]["source"]["version"] == 2


def test_replay_content_conflict_readonly_revocation_and_cas(workflow):
    p = workflow.create_project()
    operation = str(uuid4())
    payload = {
        "operation_id": operation,
        "expected_version": 1,
        "kind": "firm",
        "product": "Camera",
        "quantity": "100",
        "unit": "piece",
        "due_date": "2026-12-01",
        "source": workflow.source("replay-1"),
    }
    first = workflow.command(p["id"], "demand.record", **payload)
    assert workflow.command(p["id"], "demand.record", **payload)["replayed"] is True
    assert (
        workflow.command(
            p["id"],
            "demand.record",
            **{**payload, "product": "Other"},
            expected_status=409,
        )["code"]
        == "IDEMPOTENCY_CONFLICT"
    )
    assert (
        workflow.command(
            p["id"],
            "demand.record",
            **{**payload, "operation_id": str(uuid4()), "expected_version": 1},
            expected_status=409,
        )["code"]
        == "VERSION_CONFLICT"
    )
    workflow.grant(p["id"], "planner", ["project_owner"])
    workflow.read_only.add("planner")
    assert (
        workflow.command(
            p["id"], "demand.record", actor_name="planner", expected_status=403
        )["detail"]
        == "Workflow is read-only"
    )
    workflow.read_only.clear()
    workflow.grant(p["id"], "planner", [], active=False)
    assert (
        workflow.client("planner")
        .get(f"{BASE}/projects/{p['id']}/objects/demand/{first['object_id']}")
        .status_code
        == 404
    )


def _isolated_work_order_row(workflow, project_id, quantity, unit="piece"):
    """A3 will replace this narrow SQL fixture with work_order.register in integration tests."""
    store = WorkflowStore(
        str(workflow.paths.domain),
        str(workflow.paths.authority),
        {"id": "workflow-test", "mode": "test", "label": "Workflow test"},
    )
    ident = str(uuid4())
    with store.transaction(write=True) as tx:
        tx.execute(
            "CREATE TABLE IF NOT EXISTS work_orders(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, q_atoms INTEGER NOT NULL, unit TEXT NOT NULL)"
        )
        tx.execute(
            "INSERT INTO work_orders VALUES (?,?,?,?)",
            (ident, project_id, quantity, unit),
        )
    return ident


def test_allocations_conserve_both_order_and_work_order_with_pending_change(workflow):
    p = workflow.create_project()
    other = workflow.create_project()
    demand = record(workflow, p["id"])
    approve(workflow, p["id"], demand)
    order = register(workflow, p["id"], demand)
    wo = _isolated_work_order_row(workflow, p["id"], 60)
    second_wo = _isolated_work_order_row(workflow, p["id"], 50)
    other_wo = _isolated_work_order_row(workflow, other["id"], 40)
    workflow.grant(p["id"], "planner", ["planner"])
    assert (
        workflow.command(
            p["id"],
            "order.allocate",
            actor_name="planner",
            order_line_id=order,
            work_order_id=other_wo,
            quantity="1",
            unit="piece",
            expected_status=404,
        )["code"]
        == "NOT_FOUND"
    )
    workflow.command(
        p["id"],
        "order.allocate",
        actor_name="planner",
        order_line_id=order,
        work_order_id=wo,
        quantity="60",
        unit="piece",
    )
    assert (
        workflow.command(
            p["id"],
            "order.allocate",
            actor_name="planner",
            order_line_id=order,
            work_order_id=wo,
            quantity="1",
            unit="piece",
            expected_status=409,
        )["code"]
        == "PRECONDITION_FAILED"
    )
    assert (
        workflow.command(
            p["id"],
            "order.allocate",
            actor_name="planner",
            order_line_id=order,
            work_order_id=second_wo,
            quantity="50",
            unit="piece",
            expected_status=409,
        )["code"]
        == "PRECONDITION_FAILED"
    )
    change = workflow.command(
        p["id"],
        "order.change",
        order_line_id=order,
        new_quantity="50",
        new_due_date="2026-12-02",
        cancel=False,
        reason="reduced",
        source=workflow.source("order-1", version=2, object_type="order_line"),
    )
    impact = (
        workflow.client()
        .get(
            f"{BASE}/projects/{p['id']}/objects/commitment_change/{change['object_id']}"
        )
        .json()["value"]["impacts"]
    )
    assert [(i["object_type"], i["object_id"], i["quantity"]) for i in impact] == [
        ("work_order", wo, "60")
    ]
    assert (
        workflow.command(
            p["id"],
            "order.allocate",
            actor_name="planner",
            order_line_id=order,
            work_order_id=wo,
            quantity="1",
            unit="piece",
            expected_status=409,
        )["code"]
        == "PRECONDITION_FAILED"
    )
    disposition = [
        {
            "object_type": "work_order",
            "object_id": wo,
            "decision": "cancel",
            "evidence": "requested cancellation",
        }
    ]
    assert (
        workflow.command(
            p["id"],
            "order.resolve_change",
            change_id=change["object_id"],
            dispositions=disposition,
            expected_status=409,
        )["code"]
        == "PRECONDITION_FAILED"
    )
    assert (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/order_line/{order}")
        .json()["value"]["current_quantity"]
        == "100"
    )


def test_two_concurrent_demand_writes_have_one_cas_winner(workflow):
    p = workflow.create_project()

    def submit(number):
        return workflow.client().post(
            f"{BASE}/projects/{p['id']}/commands",
            json={
                "operation_id": str(uuid4()),
                "expected_version": 1,
                "action": "demand.record",
                "kind": "firm",
                "product": "Camera",
                "quantity": "1",
                "unit": "piece",
                "due_date": "2026-12-01",
                "source": workflow.source(f"concurrent-{number}"),
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, (1, 2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert [r.json().get("code") for r in responses if r.status_code == 409] == [
        "VERSION_CONFLICT"
    ]
    assert (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/demand")
        .json()["total"]
        == 1
    )


def test_cancel_unallocated_order_preserves_original_and_zero_summary(workflow):
    p = workflow.create_project()
    assert p["stages"] == []
    assert ProjectDetail.model_validate(p).stages == []
    with pytest.raises(ValidationError):
        ProjectStageView.model_validate({"stage": "S10", "status": "complete"})
    demand = record(workflow, p["id"])
    approve(workflow, p["id"], demand)
    order = register(workflow, p["id"], demand)
    change = workflow.command(
        p["id"],
        "order.change",
        order_line_id=order,
        new_quantity="100",
        new_due_date="2026-12-01",
        cancel=True,
        reason="customer cancellation",
        source=workflow.source("order-1", version=2, object_type="order_line"),
    )
    workflow.command(
        p["id"], "order.resolve_change", change_id=change["object_id"], dispositions=[]
    )
    detail = (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/order_line/{order}")
        .json()
    )
    value = detail["value"]
    assert (value["original_quantity"], value["current_quantity"], value["state"]) == (
        "100",
        "0",
        "cancelled",
    )
    assert (value["original_due"], value["current_due"]) == ("2026-12-01", "2026-12-01")
    assert value["remaining_to_ship"] == value["remaining_to_accept"] == "0"
    assert [event["action"] for event in detail["history"]] == [
        "order.register",
        "order.change",
        "order.resolve_change",
    ]
    page = workflow.client().get(f"{BASE}/projects/{p['id']}/objects/order_line").json()
    assert page["items"][0]["quantity"] == "0"
    assert page["items"][0]["state"] == "cancelled"
    board = (
        workflow.client()
        .get(f"{BASE}/dashboard", params={"project_id": p["id"]})
        .json()
    )
    assert board["counts"]["order_line"] == 1
    assert (
        next(card for card in board["cards"] if card["id"] == order)["quantity"] == "0"
    )
    assert (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}")
        .json()["summary"]["current_order_quantity"]
        == "0"
    )


def test_cancel_with_allocation_remains_pending(workflow):
    p = workflow.create_project()
    demand = record(workflow, p["id"])
    approve(workflow, p["id"], demand)
    order = register(workflow, p["id"], demand)
    wo = _isolated_work_order_row(workflow, p["id"], 20)
    workflow.grant(p["id"], "planner", ["planner"])
    workflow.command(
        p["id"],
        "order.allocate",
        actor_name="planner",
        order_line_id=order,
        work_order_id=wo,
        quantity="20",
        unit="piece",
    )
    change = workflow.command(
        p["id"],
        "order.change",
        order_line_id=order,
        new_quantity="100",
        new_due_date="2026-12-01",
        cancel=True,
        reason="customer cancellation",
        source=workflow.source("order-1", version=2, object_type="order_line"),
    )
    disposition = [
        {
            "object_type": "work_order",
            "object_id": wo,
            "decision": "cancel",
            "evidence": "requested",
        }
    ]
    assert (
        workflow.command(
            p["id"],
            "order.resolve_change",
            change_id=change["object_id"],
            dispositions=disposition,
            expected_status=409,
        )["code"]
        == "PRECONDITION_FAILED"
    )
    assert (
        workflow.client()
        .get(
            f"{BASE}/projects/{p['id']}/objects/commitment_change/{change['object_id']}"
        )
        .json()["value"]["state"]
        == "pending"
    )


def test_read_quantity_models_reject_noncanonical_or_nonfinite_values(workflow):
    p = workflow.create_project()
    demand = record(workflow, p["id"])
    approve(workflow, p["id"], demand)
    order = register(workflow, p["id"], demand)
    detail = (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/order_line/{order}")
        .json()
    )
    value = detail["value"]
    for field in (
        "allocated",
        "produced_good",
        "shipped",
        "signed",
        "accepted",
        "remaining_to_ship",
        "remaining_to_accept",
        "current_quantity",
    ):
        for bad in ("junk", "-1", "NaN", "Infinity", "1e2"):
            with pytest.raises(ValidationError):
                OrderLineValue.model_validate({**value, field: bad})
    impact = {
        "object_type": "work_order",
        "object_id": str(uuid4()),
        "quantity": "0",
        "unit": "piece",
        "decision": None,
        "evidence": None,
    }
    assert (
        ChangeImpact.model_validate(impact).model_dump(mode="json")["quantity"] == "0"
    )
    for bad in ("junk", "-1", "NaN", "Infinity", "1e2"):
        with pytest.raises(ValidationError):
            ChangeImpact.model_validate({**impact, "quantity": bad})
    summary = detail["summary"]
    assert (
        ObjectSummary.model_validate({**summary, "quantity": "0"}).model_dump(
            mode="json"
        )["quantity"]
        == "0"
    )
    for bad in ("junk", "-1", "NaN", "Infinity"):
        with pytest.raises(ValidationError):
            ObjectSummary.model_validate({**summary, "quantity": bad})
