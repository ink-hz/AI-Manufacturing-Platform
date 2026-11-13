"""Urgency annotates linked receipts without reordering or widening a SQL page."""
from uuid import uuid4

from .conftest import BASE
from .test_expedite_tasks import requirements, stock
from .test_expedites import open_case, setup

FLAG = "Expedited: open expedite on linked requirement"


def page(w, pid, **params):
    response = w.client().get(f"{BASE}/projects/{pid}/objects/receipt", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_open_and_closed_expedite_flags_preserve_receipt_order_pages_and_accounting(workflow):
    w = workflow
    pid, rid, extras = setup(w, qualified="0")
    other = requirements(w, pid, extras)[0]
    commitment = w.command(pid, "supply.commit", actor_name="supply", requirement_id=other,
                           type="customer", owner_id="Customer 1", quantity="100", unit="kg",
                           original_due="2026-12-01", current_due="2026-12-01",
                           source=w.source(str(uuid4()), object_type="commitment"))["object_id"]
    urgent = []
    for _ in range(3):
        w.receive(pid, commitment, quantity="1", lot_id=extras["lot_id"])
        urgent.append(w.receive(pid, extras["id"], quantity="1", lot_id=extras["lot_id"])["object_id"])
    before_page = page(w, pid)
    before_pages = [page(w, pid, limit=2, offset=o) for o in (0, 2, 4, 6)]
    before = stock(w)
    ident = open_case(w, pid, rid)["object_id"]
    for offset, previous in zip((0, 2, 4, 6), before_pages):
        current = page(w, pid, limit=2, offset=offset)
        assert (current["total"], current["limit"], current["offset"]) == (6, 2, offset)
        assert [i["id"] for i in current["items"]] == [i["id"] for i in previous["items"]]
        for item in current["items"]:
            expected = [FLAG] if item["id"] in urgent else []
            assert item["blocking_reasons"] == expected
            detail = w.client().get(f"{BASE}/projects/{pid}/objects/receipt/{item['id']}")
            assert detail.status_code == 200
            assert detail.json()["summary"]["blocking_reasons"] == expected
    assert stock(w) == before
    # The second plan superseded the original requirement. Its unqualified
    # receipts cannot prove fulfillment; closing the annotation uses that real
    # plan replacement rather than bypassing the fulfillment guard.
    w.command(pid, "expedite.close", actor_name="supply", expedite_id=ident,
              outcome="fulfilled", reason="核对满足条件", expected_status=409)
    assert any(FLAG in row["blocking_reasons"] for row in page(w, pid)["items"])
    w.command(pid, "expedite.close", actor_name="supply", expedite_id=ident,
              outcome="superseded", reason="计划已替换，结束原需求急料跟进")
    assert page(w, pid) == before_page
    for receipt_id in urgent:
        assert FLAG not in w.client().get(f"{BASE}/projects/{pid}/objects/receipt/{receipt_id}").json()["summary"]["blocking_reasons"]
    assert stock(w) == before
    p2, r2, _ = w.material_requirement(mode="oem")
    open_case(w, p2["id"], r2["id"])
    assert page(w, pid) == before_page


def test_urgency_lookup_is_one_scoped_query_for_only_the_current_receipt_page(workflow):
    from uuid import UUID
    from manufacturing_platform.workflow.contracts import ObjectKind
    from manufacturing_platform.workflow.queries import OBJECT_REGISTRY

    w = workflow
    pid, rid, extras = setup(w, qualified="0")
    for _ in range(5):
        w.receive(pid, extras["id"], quantity="1", lot_id=extras["lot_id"])
    open_case(w, pid, rid)
    expected = page(w, pid, limit=2, offset=2)["items"]
    with w.db() as tx:
        statements = []
        tx.set_trace_callback(statements.append)
        values = OBJECT_REGISTRY.summaries(tx, UUID(pid), ObjectKind.receipt, limit=2, offset=2)
        urgency_queries = [q for q in statements if "material_expedites" in q]
    assert [str(item.id) for item in values] == [item["id"] for item in expected]
    assert len(urgency_queries) == 1
    query = urgency_queries[0]
    assert "r.project_id=" in query and pid in query and "r.id IN (" in query
    for item in page(w, pid)["items"]:
        assert (item["id"] in query) == (item["id"] in {i["id"] for i in expected})
    with w.db() as tx:
        statements = []
        tx.set_trace_callback(statements.append)
        assert OBJECT_REGISTRY.summaries(tx, UUID(pid), ObjectKind.receipt, limit=2, offset=20) == []
    assert not [q for q in statements if "material_expedites" in q]
