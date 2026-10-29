"""Real HTTP observations must never manufacture accounting facts."""
from uuid import uuid4

from .conftest import BASE


def fields(w):
    return dict(arrival_number="SCAN-001", location="receiving shelf", package_count=2,
                description="sealed package; material identity unknown",
                source=w.source(str(uuid4()), object_type="arrival"))


def stock(w):
    with w.db() as tx:
        return {t: [tuple(r) for r in tx.execute(f"SELECT * FROM {t} ORDER BY rowid")]
                for t in ("material_lots", "supply_receipts", "iqc_results", "reservations", "material_consumption", "source_corrections", "source_confirmations")}


def test_arrival_unidentified_match_and_correction_are_nonaccounting(workflow):
    w = workflow
    p, _, c = w.material_requirement(qualified="0")
    receipt = w.receive(p["id"], c["id"], quantity="1", lot_id=c["lot_id"])["object_id"]
    receipt2 = w.receive(p["id"], c["id"], quantity="1", lot_id=c["lot_id"])["object_id"]
    w.grant(p["id"], "warehouse", ["warehouse"])
    before = stock(w)
    arrival = w.command(p["id"], "arrival.record", actor_name="warehouse", **fields(w))["object_id"]
    value = w.object(p["id"], "arrival", arrival)
    assert value["state"] == "unlinked" and value["receipt_id"] is None
    assert value["package_count"] == 2 and value["matches"] == []
    assert stock(w) == before
    w.command(p["id"], "arrival.match", arrival_id=arrival, receipt_id=receipt, evidence="label and receipt checked")
    w.command(p["id"], "arrival.match", arrival_id=arrival, receipt_id=receipt2, evidence="correction", expected_status=409)
    w.command(p["id"], "arrival.match", arrival_id=arrival, receipt_id=receipt2, evidence="checked second label", correction_reason="first receipt selected incorrectly")
    value = w.object(p["id"], "arrival", arrival)
    assert value["receipt_id"] == receipt2
    assert [m["receipt_id"] for m in value["matches"]] == [receipt, receipt2]
    assert value["matches"][1]["previous_receipt_id"] == receipt
    assert stock(w) == before
    detail = w.client().get(f"{BASE}/projects/{p['id']}/objects/arrival/{arrival}").json()
    assert len(detail["history"]) == 3
    assert detail["summary"]["state"] == "matched"


def test_arrival_project_identity_and_strict_manual_fields(workflow):
    w = workflow
    p = w.create_project()
    a = w.command(p["id"], "arrival.record", **fields(w))["object_id"]
    p2, _, c = w.material_requirement(qualified="0")
    receipt = w.receive(p2["id"], c["id"], quantity="1", lot_id=c["lot_id"])["object_id"]
    w.command(p["id"], "arrival.match", arrival_id=a, receipt_id=receipt, evidence="foreign", expected_status=404)
    w.command(p2["id"], "arrival.match", arrival_id=a, receipt_id=receipt, evidence="foreign", expected_status=404)
    for overrides in ({"package_count": True}, {"package_count": 0}, {"material_id": "invented"}, {"arrival_number": "  "}):
        w.command(p["id"], "arrival.record", expected_status=422, **{**fields(w), **overrides})
    source = fields(w)
    source["source"]["mode"] = "imported"
    w.command(p["id"], "arrival.record", expected_status=422, **source)
    assert w.client("outsider").get(f"{BASE}/projects/{p['id']}/objects/arrival/{a}").status_code == 404


def test_arrival_cas_replay_csrf_readonly_and_live_roles(workflow):
    w = workflow
    p, _, c = w.material_requirement(qualified="0")
    r = w.receive(p["id"], c["id"], quantity="1", lot_id=c["lot_id"])["object_id"]
    w.grant(p["id"], "warehouse", ["warehouse"])
    w.grant(p["id"], "production", ["production"])
    url = f"{BASE}/projects/{p['id']}/commands"
    for action, data in [("arrival.record", fields(w)), ("arrival.match", None)]:
        if data is None:
            data = dict(arrival_id=a, receipt_id=r, evidence="checked label")
        version = w.client().get(f"{BASE}/projects/{p['id']}").json()["version"]
        body = dict(action=action, operation_id=str(uuid4()), expected_version=version, **data)
        assert w.client("production").post(url, json=body).status_code == 403
        assert w.client("warehouse").post(url, json={**body,"expected_version":version-1}).status_code == 409
        assert w.client("warehouse").post(url, json=body, headers={"x-csrf-token":"bad"}).status_code == 403
        before = stock(w)
        result = w.client("warehouse").post(url, json=body)
        assert result.status_code == 200, result.text
        a = result.json()["object_id"]
        assert w.client("warehouse").post(url, json=body).json()["replayed"]
        assert stock(w) == before
        w.read_only.add("warehouse")
        assert w.client("warehouse").post(url, json=body).status_code == 403
        w.read_only.clear()
        w.grant(p["id"], "warehouse", ["production"])
        assert w.client("warehouse").post(url, json=body).status_code == 403
        w.grant(p["id"], "warehouse", ["warehouse"])
    w.grant(p["id"], "warehouse", [], active=False)
    assert w.client("warehouse").post(url,json=body).status_code == 404


def test_arrival_replay_conflict_history_and_live_summary(workflow):
    w=workflow
    p,_,c=w.material_requirement(qualified="0")
    receipt=w.receive(p["id"],c["id"],quantity="1",lot_id=c["lot_id"])["object_id"]
    result=w.command(p["id"],"arrival.record",**fields(w))
    ident=result["object_id"]
    w.reopen()
    detail=w.client().get(f"{BASE}/projects/{p['id']}/objects/arrival/{ident}").json()
    assert detail["summary"]["next_actions"]==["arrival.match"]
    w.grant(p["id"],"production",["production"])
    detail=w.client("production").get(f"{BASE}/projects/{p['id']}/objects/arrival/{ident}").json()
    assert detail["summary"]["next_actions"]==[]
    match=w.command(p["id"],"arrival.match",arrival_id=ident,receipt_id=receipt,evidence="actual receipt label")
    body=dict(action="arrival.match",operation_id=match["operation_id"],expected_version=match["project_version"]-1,arrival_id=ident,receipt_id=receipt,evidence="different intent")
    assert w.client().post(f"{BASE}/projects/{p['id']}/commands",json=body).status_code==409
    assert len(w.object(p["id"],"arrival",ident)["matches"])==1
