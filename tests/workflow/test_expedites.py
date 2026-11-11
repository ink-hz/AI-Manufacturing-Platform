"""Expedite cases route urgency over real HTTP without touching accounting facts."""
from uuid import uuid4

from .conftest import BASE, USERS


def setup(w, *, qualified="80"):
    p, requirement, extras = w.material_requirement(mode="oem", qualified=qualified)
    w.grant(p["id"], "warehouse", ["warehouse"])
    w.grant(p["id"], "production", ["production"])
    return p["id"], requirement["id"], extras


def open_case(w, pid, requirement_id, **overrides):
    return w.command(
        pid, "expedite.open", actor_name="supply", requirement_id=requirement_id,
        reason="工单缺口，供应商延期", impact="交付延误风险", **overrides,
    )


def detail(w, pid, ident, actor="owner"):
    response = w.client(actor).get(f"{BASE}/projects/{pid}/objects/material_expedite/{ident}")
    assert response.status_code == 200, response.text
    return response.json()


def accounting(w):
    with w.db() as tx:
        return {
            t: [tuple(r) for r in tx.execute(f"SELECT * FROM {t} ORDER BY rowid")]
            for t in ("material_lots", "supply_receipts", "iqc_results",
                      "reservations", "requirements")
        }


def test_expedite_lifecycle_and_derived_milestones(workflow):
    w = workflow
    pid, rid, _ = setup(w)
    before = accounting(w)
    ident = open_case(w, pid, rid)["object_id"]
    v = detail(w, pid, ident)["value"]
    assert v["state"] == "open" and v["closure"] is None and v["progress"] == []
    assert v["opened_by"] == str(USERS["supply"])
    assert v["expedite_number"].startswith("EX-")
    assert v["source"]["mode"] == "manual" and v["source"]["object_type"] == "material_expedite"
    marks = v["milestones"]
    assert marks["opened_at"] and marks["receipt_at"] and marks["inspection_at"]
    assert marks["arrival_at"] is None and marks["handoff_at"] is None
    assert accounting(w) == before
    # one open case per requirement
    open_case(w, pid, rid, expected_status=409)
    # cross-role progress stays append-only
    w.command(pid, "expedite.progress", actor_name="warehouse",
              expedite_id=ident, note="已联系供应商，运单在途")
    v = detail(w, pid, ident)["value"]
    assert [p["note"] for p in v["progress"]] == ["已联系供应商，运单在途"]
    assert v["progress"][0]["actor_id"] == str(USERS["warehouse"])
    # close keeps history and frees the requirement for a new case
    w.command(pid, "expedite.close", actor_name="supply",
              expedite_id=ident, outcome="false_alarm", reason="协调员核对为重复误报")
    v = detail(w, pid, ident)["value"]
    assert v["state"] == "closed" and v["closure"]["outcome"] == "false_alarm"
    assert [p["note"] for p in v["progress"]] == ["已联系供应商，运单在途"]
    w.command(pid, "expedite.progress", actor_name="warehouse",
              expedite_id=ident, note="late", expected_status=409)
    open_case(w, pid, rid)
    assert accounting(w) == before


def test_expedite_requires_oem_project_and_opening_role(workflow):
    w = workflow
    p, requirement, _ = w.material_requirement(mode="internal")
    open_case(w, p["id"], requirement["id"], expected_status=422)
    pid, rid, _ = setup(w)
    w.command(pid, "expedite.open", actor_name="production", requirement_id=rid,
              reason="r", impact="i", expected_status=403)
    ident = open_case(w, pid, rid)["object_id"]
    w.command(pid, "expedite.close", actor_name="warehouse", expedite_id=ident,
              outcome="fulfilled", reason="done", expected_status=403)


def test_expedite_milestones_report_missing_facts_as_absent(workflow):
    w = workflow
    pid, rid, _ = setup(w, qualified="0")
    ident = open_case(w, pid, rid)["object_id"]
    marks = detail(w, pid, ident)["value"]["milestones"]
    assert marks["opened_at"]
    assert marks["arrival_at"] is None and marks["receipt_at"] is None
    assert marks["inspection_at"] is None and marks["handoff_at"] is None


def test_expedite_milestones_follow_arrival_and_handoff_facts(workflow):
    w = workflow
    pid, rid, extras = setup(w)
    ident = open_case(w, pid, rid)["object_id"]
    with w.db() as tx:
        receipt_id = tx.execute(
            "SELECT id FROM supply_receipts WHERE project_id=?", (pid,),
        ).fetchone()[0]
    source = w.source(str(uuid4()), object_type="arrival")
    source["evidence"] = "现场卸货观察"
    arrival = w.command(pid, "arrival.record", actor_name="warehouse",
                        arrival_number="AR-1", location="收货暂存区",
                        package_count=3, description="三箱未贴码来料", source=source)
    w.command(pid, "arrival.match", actor_name="warehouse",
              arrival_id=arrival["object_id"], receipt_id=receipt_id,
              evidence="箱单与收货单核对一致")
    handoff = w.command(
        pid, "material_handoff.record", actor_name="warehouse",
        material_lot_id=extras["lot_id"], work_order_id=extras["work_order_id"],
        quantity="1.000", unit="kg", from_location="仓库 A", to_location="产线 B",
        receiver_id=str(USERS["production"]),
    )
    w.command(pid, "material_handoff.receive", actor_name="production",
              handoff_id=handoff["object_id"], received_quantity="1.000",
              received_location="产线 B")
    marks = detail(w, pid, ident)["value"]["milestones"]
    assert marks["arrival_at"] and marks["receipt_at"]
    assert marks["inspection_at"] and marks["handoff_at"]


def test_expedite_listing_and_outsider_isolation(workflow):
    w = workflow
    pid, rid, _ = setup(w)
    ident = open_case(w, pid, rid)["object_id"]
    page = w.client("owner").get(
        f"{BASE}/projects/{pid}/objects/material_expedite"
    )
    assert page.status_code == 200, page.text
    items = page.json()["items"]
    assert [i["id"] for i in items] == [ident]
    assert items[0]["state"] == "open"
    assert "expedite.progress" in items[0]["next_actions"]
    outsider = w.client("outsider").get(
        f"{BASE}/projects/{pid}/objects/material_expedite/{ident}"
    )
    assert outsider.status_code in (403, 404)
