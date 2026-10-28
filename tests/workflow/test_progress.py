"""D1: collaboration hints never manufacture business completion."""

from .conftest import BASE


def test_stage_hint_cannot_complete_unshipped_order(workflow):
    p, order, _, _ = workflow.order_workorder(quantity="5")
    before = workflow.client().get(f"{BASE}/projects/{p['id']}").json()
    assert "progress" in before
    result = workflow.command(
        p["id"],
        "project.stage",
        stage="S8",
        status="complete",
        reason="Collaboration review complete",
    )
    after = workflow.client().get(f"{BASE}/projects/{p['id']}").json()
    assert after["stages"] == [
        {"stage": "S8", "status": "complete", "reason": "Collaboration review complete"}
    ]
    assert after["progress"]["fulfillment"]["status"] == "blocked"
    assert after["summary"]["remaining_to_ship"] == "5"
    assert after["progress"]["stages"][7]["status"] != "complete"
    assert any(
        str(b["id"]) == order["id"] for b in after["progress"]["blocking_objects"]
    )
    assert result["object_type"] == "project"


def test_progress_independent_closures_and_later_feedback(workflow):
    p = workflow.create_project()
    detail = workflow.client().get(f"{BASE}/projects/{p['id']}").json()
    assert "progress" in detail
    assert detail["progress"]["fulfillment"]["status"] == "blocked"
    assert detail["progress"]["cost"]["status"] == "ready"
    assert detail["progress"]["quality"]["status"] == "ready"
    assert detail["progress"]["cost"]["recorded_count"] == 0


def test_object_next_actions_are_filtered_by_current_actor_policy(workflow):
    p, _, _, _ = workflow.order_workorder()
    workflow.grant(p["id"], "quality", ["quality"], ["inspection"])
    demand = (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/demand")
        .json()["items"][0]
    )
    owner = (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/demand/{demand['id']}")
        .json()
    )
    reader = (
        workflow.client("quality")
        .get(f"{BASE}/projects/{p['id']}/objects/demand/{demand['id']}")
        .json()
    )
    assert "demand.review" in owner["summary"]["next_actions"]
    assert "demand.review" not in reader["summary"]["next_actions"]
    workflow.read_only.add("owner")
    assert (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/demand/{demand['id']}")
        .json()["summary"]["next_actions"]
        == []
    )


def test_progress_is_selected_project_only_and_does_not_run_for_lists(
    workflow, monkeypatch
):
    from manufacturing_platform.workflow import progress

    p = workflow.create_project()
    calls = []
    original = progress.aggregate

    def aggregate(tx, pid):
        calls.append(str(pid))
        return original(tx, pid)

    monkeypatch.setattr(progress, "aggregate", aggregate)
    assert workflow.client().get(BASE + "/projects").status_code == 200
    assert calls == []
    assert workflow.client().get(BASE + "/dashboard").status_code == 200
    assert calls == []
    assert workflow.client().get(f"{BASE}/projects/{p['id']}").status_code == 200
    assert calls == [p["id"]]


def test_progress_reopens_current_quality_without_erasing_closure(workflow):
    p, order, unit_rows = workflow.released_order(quantity="1")
    units = [u["id"] for u in unit_rows]
    ship = workflow.command(
        p["id"],
        "shipment.request",
        actor_name="warehouse",
        order_line_id=order["id"],
        unit_ids=units,
        quantity="1",
        unit="piece",
        boxes=[],
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="warehouse",
        exchange_id=ship["exchange_id"],
    )
    workflow.command(
        p["id"],
        "closure.record",
        actor_name="owner",
        kind="quality",
        source=workflow.source("quality-close", object_type="closure"),
        evidence="Current conditions checked",
    )
    before = workflow.client().get(f"{BASE}/projects/{p['id']}").json()["progress"]
    assert before["quality"]["status"] == "closed"
    rma = workflow.command(
        p["id"],
        "rma.open",
        actor_name="quality",
        unit_id=units[0],
        shipment_id=ship["object_id"],
        reason="New field failure",
        source=workflow.source("feedback-after-close", object_type="rma"),
    )
    after = workflow.client().get(f"{BASE}/projects/{p['id']}").json()["progress"]
    assert after["quality"]["status"] == "blocked"
    assert after["quality"]["recorded_count"] == 1
    assert any(b["id"] == rma["object_id"] for b in after["blocking_objects"])


def test_owned_tasks_have_real_owners_and_exact_targets(workflow):
    p, _, wo, _ = workflow.order_workorder()
    owner = workflow.client().get(f"{BASE}/projects/{p['id']}").json()
    assert "tasks" in owner
    engineer = workflow.client("engineering").get(f"{BASE}/projects/{p['id']}").json()
    assert any(
        t["target"]["id"] == wo["id"] and t["category"] == "readiness"
        for t in engineer["tasks"]
    )
    workflow.read_only.add("engineering")
    assert (
        workflow.client("engineering").get(f"{BASE}/projects/{p['id']}").json()["tasks"]
        == []
    )


def test_test_detail_separates_immutable_outcome_from_current_qualification(workflow):
    p, unit = workflow.executed_unit()
    measured = workflow.test(p["id"], unit["id"], measured="5")
    assert measured["outcome"] == "pass"
    assert measured["current_qualified"] is True
    # A subsequent failed measurement keeps the historical PASS immutable.
    workflow.test(p["id"], unit["id"], measured="7")
    historical = workflow.object(p["id"], "test", measured["id"])
    assert historical["outcome"] == "pass"
    assert historical["current_qualified"] is False
    assert historical["current_blocking_reasons"]


def test_work_order_capabilities_use_current_command_readiness_variants(workflow):
    p, _, wo, _ = workflow.order_workorder()
    workflow.grant(p["id"], "production", ["production"])
    d = (
        workflow.client("production")
        .get(f"{BASE}/projects/{p['id']}/objects/work_order/{wo['id']}")
        .json()
    )
    capability = next(
        c
        for c in d["summary"]["action_capabilities"]
        if c["action"] == "production.start"
    )
    for mode in ("trial", "bulk"):
        assert (
            capability["variants"][mode]["ready"]
            == d["value"][mode + "_readiness"]["ready"]
        )
        assert capability["variants"][mode]["blocking_reasons"]


def test_selected_100_unit_project_and_list_read_cost(workflow, monkeypatch):
    from contextlib import contextmanager
    from time import perf_counter

    from manufacturing_platform.workflow import progress
    from manufacturing_platform.workflow.store import WorkflowStore

    p, _, _ = workflow.released_order(quantity="100")
    statements = []
    original = WorkflowStore.transaction

    @contextmanager
    def observed(store, **kwargs):
        with original(store, **kwargs) as tx:
            tx.set_trace_callback(statements.append)
            yield tx

    monkeypatch.setattr(WorkflowStore, "transaction", observed)
    start = perf_counter()
    detail = workflow.client().get(f"{BASE}/projects/{p['id']}")
    selected_elapsed = perf_counter() - start
    assert detail.status_code == 200, detail.text
    assert detail.json()["quality_summary"]["final_good"] == 100
    selected_queries = len(statements)
    statements.clear()

    def forbidden(*args):
        raise AssertionError("List must not evaluate closure/progress")

    monkeypatch.setattr(progress, "aggregate", forbidden)
    start = perf_counter()
    page = workflow.client().get(BASE + "/projects")
    list_elapsed = perf_counter() - start
    assert page.status_code == 200, page.text
    assert page.json()["items"][0]["progress"] is None
    print(
        f"100-unit current detail: {selected_queries} SQL statements, {selected_elapsed:.3f}s; project list: {len(statements)} SQL statements, {list_elapsed:.3f}s; no progress/closure calls on list"
    )


def test_exact_work_order_outside_readiness_window_is_not_missing_or_denied(workflow):
    p = workflow.create_project(quantity="21")
    demand = workflow.command(
        p["id"],
        "demand.record",
        kind="firm",
        product="Camera",
        quantity="21",
        unit="piece",
        due_date="2026-12-01",
        source=workflow.source("many-demand"),
    )["object_id"]
    for dimension in ("technical", "material", "capacity", "commercial", "quality"):
        workflow.command(
            p["id"],
            "demand.review",
            demand_id=demand,
            dimension=dimension,
            decision="approved",
            evidence="Current approved review",
        )
    order = workflow.command(
        p["id"],
        "order.register",
        demand_id=demand,
        quantity="21",
        unit="piece",
        due_date="2026-12-01",
        source=workflow.source("many-order", object_type="order_line"),
    )["object_id"]
    revision = workflow.revision(p["id"])["id"]
    workflow.grant(p["id"], "planner", ["planner"])
    workflow.grant(p["id"], "production", ["production"])
    for n in range(21):
        workflow.command(
            p["id"],
            "work_order.register",
            actor_name="planner",
            order_line_id=order,
            revision_id=revision,
            quantity="1",
            unit="piece",
            purpose="trial",
            trial_quantity="1",
            planned_start="2026-12-01T00:00:00Z",
            planned_end="2026-12-02T00:00:00Z",
            source=workflow.source(f"WO-{n}", object_type="work_order"),
        )
    page = (
        workflow.client("production")
        .get(f"{BASE}/projects/{p['id']}/objects/work_order?limit=50")
        .json()
    )
    last = page["items"][-1]
    progress = (
        workflow.client("production")
        .get(f"{BASE}/projects/{p['id']}")
        .json()["progress"]
    )
    assert progress["blockers_truncated"] is True
    assert last["id"] not in {i["id"] for i in progress["blocking_objects"]}
    exact = (
        workflow.client("production")
        .get(f"{BASE}/projects/{p['id']}/objects/work_order/{last['id']}")
        .json()
    )
    cap = next(
        c
        for c in exact["summary"]["action_capabilities"]
        if c["action"] == "production.start"
    )
    assert cap["variants"]["trial"]["ready"] is False
    assert cap["variants"]["trial"]["blocking_reasons"]
