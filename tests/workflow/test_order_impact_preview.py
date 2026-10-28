"""Selected-order impact totals and bounded references use real API-created facts."""

from uuid import UUID

from manufacturing_platform.workflow import orders

from .test_orders import approve, record, register


def test_order_impact_totals_scope_and_bounded_reference_query(workflow):
    p = workflow.create_project(unit={"code": "piece", "scale": 6})
    demand = record(workflow, p["id"])
    approve(workflow, p["id"], demand)
    order = register(workflow, p["id"], demand)
    other_demand = record(workflow, p["id"], external_id="other-demand")
    approve(workflow, p["id"], other_demand)
    other_order = register(workflow, p["id"], other_demand, external_id="other-order")
    assert workflow.object(p["id"], "order_line", order)["work_order_impact"] == {
        "registered_quantity": "0.000000",
        "total": 0,
        "shown": 0,
        "has_more": False,
        "items": [],
    }
    revision = workflow.revision(p["id"])
    workflow.grant(p["id"], "planner", ["planner"])

    def work(order_id, reference, quantity):
        return workflow.command(
            p["id"],
            "work_order.register",
            actor_name="planner",
            order_line_id=order_id,
            revision_id=revision["id"],
            source=workflow.source(reference, system="MES", object_type="work_order"),
            quantity=quantity,
            unit="piece",
            purpose="trial",
            trial_quantity="0.000001",
            planned_start="2026-12-01T00:00:00Z",
            planned_end="2026-12-02T00:00:00Z",
        )["object_id"]

    work(other_order, "UNRELATED", "90")
    ids = [work(order, f"TARGET-{i:03}", "0.100001") for i in reversed(range(53))]
    workflow.command(
        p["id"],
        "order.allocate",
        actor_name="planner",
        order_line_id=order,
        work_order_id=ids[0],
        quantity="0.100001",
        unit="piece",
    )
    workflow.order_workorder(
        quantity="5"
    )  # Another project must not enter the aggregate.
    detail = workflow.object(p["id"], "order_line", order)
    impact = detail["work_order_impact"]
    assert detail["allocated"] == "0.100001"
    assert impact["registered_quantity"] == "5.300053"
    assert (impact["total"], impact["shown"], impact["has_more"]) == (53, 50, True)
    assert len(impact["items"]) == 50
    assert [i["external_id"] for i in impact["items"]] == [
        f"TARGET-{i:03}" for i in range(50)
    ]
    assert all(
        i["source_system"] == "mes" and i["quantity"] == "0.100001"
        for i in impact["items"]
    )
    # Indexed identity is canonical; immutable source evidence keeps the submitted spelling.
    for item in impact["items"]:
        source = workflow.object(p["id"], "work_order", item["id"])["source"]
        assert source["system"] == "MES" and source["external_id"] == item["external_id"]
    assert (
        workflow.object(p["id"], "order_line", other_order)["work_order_impact"][
            "registered_quantity"
        ]
        == "90.000000"
    )
    statements = []
    with workflow.db() as tx:
        tx.set_trace_callback(statements.append)
        orders.order_detail(tx, UUID(p["id"]), UUID(order))
    aggregates = [
        sql for sql in statements if "COUNT(*)" in sql and "FROM effective_work_orders" in sql
    ]
    references = [
        sql
        for sql in statements
        if "FROM effective_work_orders" in sql and "ORDER BY source_system" in sql
    ]
    assert len(aggregates) == len(references) == 1
    assert (
        "SUM(obligation_atoms)" in aggregates[0]
        and order in aggregates[0]
        and p["id"] in aggregates[0]
    )
    assert (
        "LIMIT 50" in references[0]
        and order in references[0]
        and p["id"] in references[0]
    )
