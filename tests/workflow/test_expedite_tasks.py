"""Current expedite evidence and responsibility tasks over the existing HTTP API."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from .conftest import BASE, USERS
from .test_expedites import detail, open_case, setup
from .test_material_handoffs import stock as stock_facts

GENERAL = "急料待跟进"
QUALIFIED = "急料已检验，待安排上线/关案"


def stock(w):
    facts = stock_facts(w)
    with w.db() as tx:
        facts["requirements"] = [tuple(row) for row in tx.execute("SELECT * FROM requirements ORDER BY rowid")]
    return facts


def tasks(w, pid, actor="supply", **params):
    response = w.client(actor).get(f"{BASE}/tasks", params={"project_id": pid, **params})
    assert response.status_code == 200, response.text
    return response.json()


def expedite_tasks(w, pid, actor="supply"):
    return [t for t in tasks(w, pid, actor)["items"]
            if t["target"]["kind"] == "material_expedite"]


def receipt(w, pid, commitment_id):
    with w.db() as tx:
        return tx.execute(
            "SELECT id FROM supply_receipts WHERE project_id=? AND commitment_id=? "
            "ORDER BY created_at,id LIMIT 1", (pid, commitment_id),
        ).fetchone()[0]


def requirements(w, pid, extras, count=1):
    if count > 1:
        return [requirements(w, pid, extras)[0] for _ in range(count)]
    now = datetime.now(UTC)
    source = w.source(str(uuid4()), object_type="plan")
    source.update(occurred_at=(now - timedelta(seconds=2)).isoformat(),
                  collected_at=(now - timedelta(seconds=1)).isoformat(),
                  cutoff=(now - timedelta(seconds=2)).isoformat())
    plan = w.command(
        pid, "plan.receive", actor_name="planner", source=source,
        input_revision_ids=[extras["revision_id"]],
        input_order_versions=[{"order_line_id": extras["order_id"], "version": 1}],
        requirements=[dict(work_order_id=extras["work_order_id"], execution_scope="bulk",
                           material_id="steel-1", owner_id="Customer 1", quantity="100", unit="kg")
                      for _ in range(count)],
    )
    return w.object(pid, "plan", plan["object_id"])["requirement_ids"]


def arrival(w, pid, receipt_id, happened):
    source = w.source(str(uuid4()), object_type="arrival")
    source.update(occurred_at=happened, collected_at="2026-10-29T12:00:00+00:00")
    ident = w.command(pid, "arrival.record", actor_name="warehouse", arrival_number="AR-1",
                      location="收货区", package_count=1, description="未拆箱", source=source)["object_id"]
    w.command(pid, "arrival.match", actor_name="warehouse", arrival_id=ident,
              receipt_id=receipt_id, evidence="核对收货单")
    return ident


def handoff(w, pid, extras, *, work_order_id="same", received="1", happened=None):
    ident = w.command(
        pid, "material_handoff.record", actor_name="warehouse",
        material_lot_id=extras["lot_id"],
        work_order_id=extras["work_order_id"] if work_order_id == "same" else work_order_id,
        quantity="1", unit="kg", from_location="仓库", to_location="产线",
        receiver_id=str(USERS["production"]), occurred_at="2026-10-28T00:00:00Z",
    )["object_id"]
    w.command(pid, "material_handoff.receive", actor_name="production", handoff_id=ident,
              received_quantity=received, received_location="产线", note="现场实收核对",
              **({"occurred_at": happened} if happened else {}))
    return ident


def test_rematched_arrival_stops_contributing_to_old_requirement(workflow):
    w = workflow
    pid, rid, extras = setup(w)
    ident = open_case(w, pid, rid)["object_id"]
    rid2 = requirements(w, pid, extras)[0]
    commitment = w.command(pid, "supply.commit", actor_name="supply", requirement_id=rid2,
                           type="customer", owner_id="Customer 1", quantity="100", unit="kg",
                           original_due="2026-12-01", current_due="2026-12-01",
                           source=w.source(str(uuid4()), object_type="commitment"))["object_id"]
    other = w.receive(pid, commitment, quantity="1", lot_id=extras["lot_id"])["object_id"]
    observation = arrival(w, pid, receipt(w, pid, extras["id"]), "2026-10-28T08:00:00+00:00")
    assert detail(w, pid, ident)["value"]["milestones"]["arrival_at"]
    before = stock(w)
    w.command(pid, "arrival.match", actor_name="warehouse", arrival_id=observation,
              receipt_id=other, evidence="更正收货身份", correction_reason="原需求选错")
    assert detail(w, pid, ident)["value"]["milestones"]["arrival_at"] is None
    other_case = open_case(w, pid, rid2)["object_id"]
    assert detail(w, pid, other_case)["value"]["milestones"]["arrival_at"]
    assert stock(w) == before


def test_arrival_milestone_uses_earliest_event_instant_not_match_order(workflow):
    w = workflow
    pid, rid, extras = setup(w)
    ident = open_case(w, pid, rid)["object_id"]
    arrival(w, pid, receipt(w, pid, extras["id"]), "2026-10-28T02:00:00+00:00")
    earliest = "2026-10-28T09:00:00+08:00"
    arrival(w, pid, receipt(w, pid, extras["id"]), earliest)
    actual = detail(w, pid, ident)["value"]["milestones"]["arrival_at"]
    assert datetime.fromisoformat(actual) == datetime.fromisoformat(earliest)


@pytest.mark.parametrize("kind", ["other_work_order", "no_work_order", "zero", "resolved_zero", "disputed"])
def test_handoff_milestone_excludes_unproven_requirement_receipts(workflow, kind):
    w = workflow
    pid, rid, extras = setup(w)
    ident = open_case(w, pid, rid)["object_id"]
    wo = "same"
    if kind == "no_work_order":
        wo = None
    elif kind == "other_work_order":
        demand = w.command(pid, "demand.record", kind="firm", product="Camera", quantity="1",
                           unit="piece", due_date="2026-12-01", source=w.source(str(uuid4())))["object_id"]
        for dimension in ("technical", "material", "capacity", "commercial", "quality"):
            w.command(pid, "demand.review", demand_id=demand, dimension=dimension,
                      decision="approved", evidence="已评审")
        order = w.command(pid, "order.register", demand_id=demand,
                          source=w.source(str(uuid4()), object_type="order_line"), quantity="1",
                          unit="piece", due_date="2026-12-01")["object_id"]
        wo = w.command(pid, "work_order.register", actor_name="planner",
                       order_line_id=order, revision_id=extras["revision_id"],
                       source=w.source(str(uuid4()), object_type="work_order"),
                       quantity="1", unit="piece", purpose="trial", trial_quantity="1",
                       planned_start="2026-12-01T00:00:00Z", planned_end="2026-12-02T00:00:00Z")["object_id"]
    before = stock(w)
    h = handoff(w, pid, extras, work_order_id=wo,
                received="0" if kind in {"zero", "resolved_zero"} else "0.5" if kind == "disputed" else "1")
    if kind == "resolved_zero":
        w.command(pid, "material_handoff.resolve", actor_name="warehouse",
                  handoff_id=h, resolution="确认零实收")
    assert detail(w, pid, ident)["value"]["milestones"]["handoff_at"] is None
    assert stock(w) == before


def test_handoff_milestone_accepts_resolved_positive_and_earliest_event_time(workflow):
    w = workflow
    pid, rid, extras = setup(w)
    ident = open_case(w, pid, rid)["object_id"]
    before = stock(w)
    handoff(w, pid, extras, happened="2026-10-28T02:00:00+00:00")
    earliest = "2026-10-28T09:00:00+08:00"
    h = handoff(w, pid, extras, received="0.5", happened=earliest)
    w.command(pid, "material_handoff.resolve", actor_name="warehouse", handoff_id=h,
              resolution="复核半数实收")
    actual = detail(w, pid, ident)["value"]["milestones"]["handoff_at"]
    assert datetime.fromisoformat(actual) == datetime.fromisoformat(earliest)
    assert stock(w) == before


def test_open_case_tasks_are_immediate_live_and_nonaccounting(workflow):
    w = workflow
    pid, rid, _ = setup(w, qualified="0")
    w.grant(pid, "engineering", ["project_owner"])
    assert expedite_tasks(w, pid) == []
    before = stock(w)
    ident = open_case(w, pid, rid)["object_id"]
    for actor in ("supply", "warehouse", "production", "engineering"):
        rows = expedite_tasks(w, pid, actor)
        assert len(rows) == 1 and rows[0]["target"]["id"] == ident
        assert rows[0]["title"] == GENERAL
        assert rows[0]["target"]["next_actions"] == (
            ["expedite.progress", "expedite.close"] if actor in {"supply", "engineering"}
            else ["expedite.progress"])
        project = w.client(actor).get(f"{BASE}/projects/{pid}").json()
        assert [t for t in project["tasks"] if t["target"]["kind"] == "material_expedite"] == rows
    assert expedite_tasks(w, pid, "quality") == []
    assert w.client("outsider").get(f"{BASE}/tasks", params={"project_id": pid}).status_code == 404
    assert w.client("outsider").get(f"{BASE}/tasks").json()["items"] == []
    w.read_only.add("production")
    assert expedite_tasks(w, pid, "production") == []
    w.read_only.clear()
    w.grant(pid, "production", ["engineering"])
    assert expedite_tasks(w, pid, "production") == []
    w.grant(pid, "production", [], active=False)
    assert w.client("production").get(f"{BASE}/tasks", params={"project_id": pid}).status_code == 404
    assert w.client("production").get(f"{BASE}/tasks").json()["items"] == []
    w.command(pid, "expedite.progress", actor_name="supply", expedite_id=ident, note="催料中")
    w.command(pid, "expedite.close", actor_name="supply", expedite_id=ident,
              outcome="fulfilled", reason="已完成")
    assert expedite_tasks(w, pid) == []
    assert stock(w) == before


def test_positive_effective_iqc_changes_same_task_title_for_supply_and_production(workflow):
    w = workflow
    pid, rid, extras = setup(w, qualified="0")
    w.grant(pid, "engineering", ["project_owner"])
    ident = open_case(w, pid, rid)["object_id"]
    assert expedite_tasks(w, pid)[0]["title"] == GENERAL
    received = w.receive(pid, extras["id"], quantity="10", lot_id=extras["lot_id"])["object_id"]
    assert expedite_tasks(w, pid)[0]["title"] == GENERAL
    w.inspect(pid, received, accepted="1", rejected="9")
    before = stock(w)
    for actor in ("supply", "production", "warehouse", "engineering"):
        rows = expedite_tasks(w, pid, actor)
        assert len(rows) == 1 and rows[0]["target"]["id"] == ident
        assert rows[0]["title"] == (QUALIFIED if actor in {"supply", "production"} else GENERAL)
        assert rows[0]["target"]["state"] == "open"
    w.command(pid, "expedite.close", actor_name="supply", expedite_id=ident,
              outcome="fulfilled", reason="已安排")
    assert expedite_tasks(w, pid) == []
    assert stock(w) == before


def test_rejected_only_iqc_keeps_general_task(workflow):
    w = workflow
    pid, rid, extras = setup(w, qualified="0")
    open_case(w, pid, rid)
    received = w.receive(pid, extras["id"], quantity="10", lot_id=extras["lot_id"])["object_id"]
    w.inspect(pid, received, accepted="0", rejected="10")
    before = stock(w)
    assert expedite_tasks(w, pid)[0]["title"] == GENERAL
    assert expedite_tasks(w, pid, "production")[0]["title"] == GENERAL
    assert stock(w) == before


def test_iqc_source_correction_to_zero_restores_general_task(workflow):
    from .test_imports import review_correct, review_import, review_iqc, review_pull, review_receipt

    w = workflow
    pid, rid, extras = setup(w, qualified="0")
    p = {"id": pid}
    received = review_receipt(w, p, extras, quantity="10")
    local = review_import(w, p, received, "supply")
    w.inspect(pid, local["object_id"], accepted="10", rejected="0")
    with w.db() as tx:
        iqc_id = tx.execute("SELECT id FROM iqc_results WHERE project_id=?", (pid,)).fetchone()[0]
    open_case(w, pid, rid)
    assert expedite_tasks(w, pid)[0]["title"] == QUALIFIED
    review_iqc(w, p, "correct-iqc", "0", rejected="10", manual_iqc_id=iqc_id)
    pulled = review_pull(w, p, "iqc", "correct-iqc", "quality")
    review_correct(w, p, pulled, "iqc", "correct-iqc")
    before = stock(w)
    assert expedite_tasks(w, pid)[0]["title"] == GENERAL
    assert expedite_tasks(w, pid, "production")[0]["title"] == GENERAL
    assert stock(w) == before


def test_task_page_keeps_50_row_boundary_and_existing_handoff_responsibilities(workflow):
    w = workflow
    pid, rid, extras = setup(w, qualified="0")
    ids = [rid, *requirements(w, pid, extras, count=50)]
    cases = {open_case(w, pid, r)["object_id"] for r in ids}
    before = stock(w)
    page = tasks(w, pid, "production")
    assert len(page["items"]) == page["total"] == 50
    assert page["truncated"] is True
    assert len({t["target"]["id"] for t in page["items"]}) == 50
    assert all(t["target"]["id"] in cases for t in page["items"])
    paged = tasks(w, pid, "production", limit=7, offset=43)
    assert paged["items"] == page["items"][43:50] and paged["total"] == 50
    for index, ident in enumerate(sorted(cases)):
        w.command(pid, "expedite.close", actor_name="supply", expedite_id=ident,
                  outcome="fulfilled", reason="清案")
        if index == 1:
            exact = tasks(w, pid, "production")
            assert len(exact["items"]) == exact["total"] == 50
            assert not exact["truncated"]
    pending = w.command(pid, "material_handoff.record", actor_name="warehouse",
                        material_lot_id=extras["lot_id"], work_order_id=extras["work_order_id"],
                        quantity="1", unit="kg", from_location="仓库", to_location="产线",
                        receiver_id=str(USERS["production"]))["object_id"]
    open_case(w, pid, rid)
    page = tasks(w, pid, "production")
    assert {"material_handoff", "material_expedite"} <= {t["target"]["kind"] for t in page["items"]}
    assert any(t["target"]["id"] == pending for t in page["items"])
    assert not page["truncated"]
    assert stock(w) == before


def test_task_sql_filters_project_and_uses_effective_iqc_inside_shared_limit(workflow, monkeypatch):
    from contextlib import contextmanager
    from manufacturing_platform.workflow.store import WorkflowStore

    w = workflow
    pid, rid, _ = setup(w, qualified="0")
    other, _, _ = setup(w)
    open_case(w, pid, rid)
    statements = []
    original = WorkflowStore.transaction

    @contextmanager
    def traced(store, **kwargs):
        with original(store, **kwargs) as tx:
            tx.set_trace_callback(statements.append)
            yield tx

    monkeypatch.setattr(WorkflowStore, "transaction", traced)
    page = tasks(w, pid, "production", limit=1)
    assert page["items"][0]["title"] == GENERAL
    query = next(q for q in statements if "FROM material_expedites e" in q)
    assert "ORDER BY category,id LIMIT 51" in query
    assert "FROM effective_iqc_results i" in query
    assert f"e.project_id='{pid}' AND e.state='open'" in query
    assert other not in query
