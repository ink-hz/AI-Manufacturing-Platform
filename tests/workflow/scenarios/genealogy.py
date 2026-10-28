"""Composite acceptance proof over actual graph, typed records and read-only facts."""

from decimal import Decimal
from urllib.parse import quote


def assert_trace(flow, uid, *, completed=False, feedback_ids=None):
    api, p = flow.api, flow.project
    unit = api.object(p, "unit", uid)
    wid, rid = unit["work_order_id"], unit["revision_id"]
    wo = api.object(p, "work_order", wid)
    revision = api.object(p, "revision", rid)
    assert wo["revision_id"] == rid and wo["order_line_id"] == flow.order, (
        "Unit/WO/revision/order binding"
    )
    assert unit["final_good"] and not unit["scrapped"], (
        "Completed genealogy requires a non-scrapped qualified unit"
    )
    assert unit["authority_start_accepted"] and unit["accepted_start_id"], (
        "Missing authoritative start"
    )
    trace = api.get("/projects/" + p + "/trace?sn=" + quote(unit["sn"]))
    assert trace["truncated"] is False, "Truncated genealogy is not proof"
    nodes = {(n["kind"], n["id"]) for n in trace["nodes"]}
    edges = {
        (
            e["source_kind"],
            e["source_id"],
            e["target_kind"],
            e["target_id"],
            e["relation"],
        )
        for e in trace["edges"]
    }
    assert all(n["project_id"] == p for n in trace["nodes"]), "Foreign graph node"
    expected_nodes = {
        ("unit", uid),
        ("work_order", wid),
        ("revision", rid),
        ("order_line", flow.order),
    }
    expected_edges = {
        ("unit", uid, "work_order", wid, "work_order"),
        ("unit", uid, "revision", rid, "revision"),
        ("work_order", wid, "order_line", flow.order, "order"),
    }

    def link(sk, sid, tk, tid, relation):
        expected_nodes.update(((sk, sid), (tk, tid)))
        expected_edges.add((sk, sid, tk, tid, relation))

    with api.db() as db:

        def rows(sql, *args):
            return [dict(r) for r in db.execute(sql, args)]

        tests = rows(
            "SELECT t.*,b.prior_test_id FROM quality_tests t LEFT JOIN quality_test_bases b ON b.test_id=t.id AND b.project_id=t.project_id WHERE t.project_id=? AND t.unit_id=? ORDER BY t.seq",
            p,
            uid,
        )
        reworks = rows(
            "SELECT * FROM rework_orders WHERE project_id=? AND unit_id=? ORDER BY seq",
            p,
            uid,
        )
        releases = rows(
            "SELECT r.*,u.test_id FROM quality_release_units u JOIN quality_releases r ON r.id=u.release_id AND r.project_id=u.project_id WHERE u.project_id=? AND u.unit_id=? ORDER BY r.seq",
            p,
            uid,
        )
        shipments = rows(
            "SELECT * FROM shipment_items WHERE project_id=? AND unit_id=?", p, uid
        )
        rmas = rows(
            "SELECT * FROM rmas WHERE project_id=? AND unit_id=? ORDER BY seq", p, uid
        )
        capas = rows(
            "SELECT c.* FROM capas c JOIN rmas r ON r.id=c.rma_id AND r.project_id=c.project_id WHERE r.project_id=? AND r.unit_id=? ORDER BY c.seq",
            p,
            uid,
        )
        events = rows(
            "SELECT e.id,e.source_external_id,e.work_order_id,u.revision_id,e.status,a.admitted FROM execution_events e JOIN units u ON u.id=e.unit_id AND u.project_id=e.project_id JOIN execution_admissions a ON a.event_id=e.id AND a.project_id=e.project_id WHERE e.project_id=? AND e.unit_id=? ORDER BY e.accepted_seq",
            p,
            uid,
        )
        start = rows(
            "SELECT s.* FROM start_requests s JOIN start_units u ON u.start_id=s.id AND u.project_id=s.project_id WHERE u.project_id=? AND u.unit_id=?",
            p,
            uid,
        )
        consumption = rows(
            "SELECT c.* FROM material_consumption c JOIN execution_events e ON e.id=c.execution_event_id AND e.project_id=c.project_id AND e.unit_id=c.unit_id JOIN execution_admissions a ON a.event_id=e.id AND a.project_id=e.project_id WHERE c.project_id=? AND c.unit_id=? AND e.status='accepted' AND a.admitted=1",
            p,
            uid,
        )
    assert (
        len(start) == 1
        and start[0]["id"] == unit["accepted_start_id"]
        and start[0]["work_order_id"] == wid
        and start[0]["accepted_receipt_id"]
    ), "Start receipt must belong to this unit and WO"
    start_exchange = api.object(p, "exchange", start[0]["exchange_id"])
    assert start_exchange["receipt"]["receipt_id"] == start[0]["accepted_receipt_id"], (
        "Start receipt linkage"
    )
    assert {e["source_external_id"] for e in events} == {
        ident for ident, _ in flow.executions[uid]
    }, "Execution sources differ from submitted commands"
    expected_event_ids = {e["id"] for e in events}
    assert (
        {e["id"] for e in events}
        == expected_event_ids
        == set(unit["execution_event_ids"])
    ), "Execution history missing or foreign"
    assert (
        len(unit["execution_events"]) == unit["execution_event_total"] == len(events)
    ), "Execution history truncated"
    assert all(
        e["admitted"] == 1
        and e["status"] == "accepted"
        and e["work_order_id"] == wid
        and e["revision_id"] == rid
        for e in events
    ), "Rejected or misbound execution"
    initial_route = {
        (s["station"], s["instruction_version"]) for s in revision["route_steps"]
    }
    actual_route = {
        (e["station"], e["route_version"])
        for e in unit["execution_events"]
        if e["route_kind"] == "initial"
    }
    assert actual_route == initial_route, (
        "Executed initial route does not match fixed revision"
    )
    for event in unit["execution_events"]:
        assert (
            event["status"] == "accepted"
            and event["source"]
            and event["claimed_sn"] == unit["sn"]
        ), "Execution source/SN admission"
    lots = {c["lot_id"] for c in consumption}
    expected_lots = {
        use["lot_id"]
        for _, command in flow.executions[uid]
        for use in command["material_uses"]
    }
    assert lots == expected_lots and lots, (
        "Consumed lots differ from actual execution commands"
    )
    for lid in lots:
        lot = api.object(p, "material_lot", lid)
        assert all(
            c["material_id"] == lot["material_id"]
            and c["owner_id"] == lot["owner_id"]
            and c["unit"] == lot["unit"]
            and c["q_atoms"] > 0
            for c in consumption
            if c["lot_id"] == lid
        ), "Consumed lot ownership/material mismatch"
        link("material_lot", lid, "unit", uid, "consumed")
    expected_tests = flow.test_history[uid]
    assert (
        [t["id"] for t in tests] == expected_tests == [t["id"] for t in unit["tests"]]
    ), "First/retest history must remain complete and ordered"
    assert (
        unit["test_total"] == len(expected_tests)
        and expected_tests[-1] == flow.tests[uid]
    ), "Test history truncated/latest identity changed"
    for row in tests:
        tid = row["id"]
        value = api.object(p, "test", tid)
        assert (
            value["id"] == tid
            and value["unit_id"] == uid
            and value["revision_id"] == rid
        ), "Test binding differs from unit/revision"
        assert (
            value["attempt"] == row["attempt"]
            and value["outcome"] == row["outcome"]
            and value["source"]
        ), "Immutable test result/source mismatch"
        assert (
            value["execution_event_ids"]
            and set(value["execution_event_ids"]) <= expected_event_ids
        ), "Test execution basis missing/foreign"
        link("unit", uid, "test", tid, "test")
        if row["prior_test_id"]:
            link("test", row["prior_test_id"], "test", tid, "prior_test")
        if row["rework_order_id"]:
            link("rework", row["rework_order_id"], "test", tid, "test")
    for row in reworks:
        value = api.object(p, "rework", row["id"])
        assert (
            value["unit_id"] == uid
            and value["revision_id"] == rid
            and value["state"] == "complete"
        ), "Rework binding/completion"
        assert value["test_ids"] and set(value["test_ids"]) <= set(expected_tests), (
            "Rework must retain actual retest basis"
        )
        link("unit", uid, "rework", row["id"], "rework")
    actors = {}
    for row in releases:
        value = api.object(p, "release", row["id"])
        assert (
            uid in value["unit_ids"]
            and value["decision"] == row["decision"] == "approved"
        ), "Independent release must cover this unit"
        assert (
            row["test_id"] == expected_tests[-1] and row["test_id"] in value["test_ids"]
        ), "Release must use this unit's latest test"
        actors[row["kind"]] = value["actor_id"]
        link("unit", uid, "release", row["id"], "release")
    assert {"manufacturing", "quality"} <= actors.keys() and actors[
        "manufacturing"
    ] != actors["quality"], "Independent manufacturing/quality releases required"
    if api.get("/projects/" + p)["contract"]["customer_release_required"]:
        assert "customer" in actors, "Required customer release missing"
    if completed:
        assert len(shipments) == 1, "Completed unit needs exactly one accepted shipment"
    for row in shipments:
        sid = row["shipment_id"]
        value = api.object(p, "shipment", sid)
        assert (
            value["order_line_id"] == row["order_line_id"] == flow.order
            and uid in value["unit_ids"]
            and value["state"] == "accepted"
        ), "Shipment unit/order/accepted binding"
        exchange = api.object(p, "exchange", value["exchange_id"])
        assert exchange["receipt"]["receipt_id"] == row["receipt_id"], (
            "Shipment authority receipt mismatch"
        )
        if completed or rmas:
            assert (
                value["shipped"]
                == value["signed"]
                == value["accepted"]
                == value["quantity"]
            ), "Full shipment sign/accept required"
            for action in ("sign", "accept"):
                facts = [f for f in value["facts"] if f["action"] == action]
                assert facts and sum(Decimal(f["quantity"]) for f in facts) == Decimal(
                    value["quantity"]
                ), "Delivery fact quantity reconciliation"
                assert all(f["source"] and f["external_signatory"] for f in facts), (
                    "Delivery accepted source/signatory evidence"
                )
        link("unit", uid, "shipment", sid, "shipment")
        link("shipment", sid, "order_line", flow.order, "order")
    for row in rmas:
        value = api.object(p, "rma", row["id"])
        assert (
            value["unit_id"] == uid
            and value["revision_id"] == rid
            and value["order_line_id"] == flow.order
            and value["shipment_id"] == row["shipment_id"]
        ), "RMA must bind this delivered unit/revision/order"
        assert (
            value["test_ids"] == expected_tests
            and value["tests_truncated"] is False
            and value["source"]
        ), "RMA original test/source history incomplete"
        assert value["state"] == "closed", "Feedback chain must be closed"
        link("shipment", row["shipment_id"], "rma", row["id"], "rma")
    for row in capas:
        value = api.object(p, "capa", row["id"])
        assert (
            value["rma_id"] == row["rma_id"]
            and value["state"] == "closed"
            and not value["steps_truncated"]
        ), "CAPA binding/completion"
        assert [s["step"] for s in value["steps"]] == [
            "containment",
            "root_cause",
            "correction",
            "verification",
        ] and value["steps"][-1]["effective"] is True, (
            "Complete effective CAPA history required"
        )
        link("rma", row["rma_id"], "capa", row["id"], "capa")
    if feedback_ids:
        assert feedback_ids[0] in {r["id"] for r in rmas} and feedback_ids[1] in {
            c["id"] for c in capas
        }, "Expected completed feedback chain missing"
        assert (
            next(c for c in capas if c["id"] == feedback_ids[1])["rma_id"]
            == feedback_ids[0]
        ), "Expected CAPA must belong to expected RMA"
    assert nodes == expected_nodes and len(nodes) == len(trace["nodes"]), (
        "Exact typed genealogy nodes differ from persisted identities"
    )
    assert edges == expected_edges and len(edges) == len(trace["edges"]), (
        "Exact typed genealogy edges missing/disconnected/foreign"
    )
    if completed:
        balance = api.object(p, "order_line", flow.order)
        assert (
            balance["accepted"] == balance["original_quantity"] == str(flow.quantity)
            and balance["remaining_to_ship"] == "0"
        ), "Completed order quantities/remaining obligations"
    api.context.evidence.record(
        "genealogy-proof",
        {
            "unit_id": uid,
            "work_order_id": wid,
            "revision_id": rid,
            "test_ids": expected_tests,
            "execution_ids": sorted(expected_event_ids),
            "lot_ids": sorted(lots),
            "shipment_ids": [s["shipment_id"] for s in shipments],
            "feedback_ids": feedback_ids,
            "typed_nodes": sorted(expected_nodes),
            "typed_edges": sorted(expected_edges),
            "complete": completed,
        },
    )
    return trace
