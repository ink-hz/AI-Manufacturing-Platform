"""Attributable manual handoffs exercise real HTTP and preserve accounting facts."""
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
from uuid import uuid4

import pytest

from .conftest import BASE, USERS


def setup(w, *, mode="oem"):
    p, _, wo, _ = w.order_workorder(mode=mode)
    w.grant(p["id"], "warehouse", ["warehouse"])
    w.grant(p["id"], "production", ["production"])
    lot = w.command(p["id"], "material.define", material_id="OEM-001", lot_id="LOT-001",
                    owner_id="Customer 1", unit="kg", scale=3, expiry="2027-12-31",
                    source=w.source(str(uuid4()), object_type="material_lot"))["object_id"]
    return p["id"], dict(material_lot_id=lot, work_order_id=wo["id"], quantity="1.250",
                         unit="kg", from_location="仓库 A", to_location="产线 B",
                         receiver_id=str(USERS["production"]), occurred_at="2026-10-28T08:00:00+00:00")


def record(w, pid, fields, **overrides):
    return w.command(pid, "material_handoff.record", actor_name="warehouse", **{**fields, **overrides})


def receive(w, pid, ident, **overrides):
    return w.command(pid, "material_handoff.receive", actor_name="production",
                     **{ "handoff_id":ident, "received_quantity":"1.250", "received_location":"产线 B", **overrides })


def stock(w):
    with w.db() as tx:
        rows = {t: [tuple(r) for r in tx.execute(f"SELECT * FROM {t} ORDER BY rowid")]
                for t in ("material_lots", "supply_receipts", "iqc_results", "reservations",
                          "material_consumption", "source_corrections", "source_confirmations", "handoffs")}
    with sqlite3.connect(w.paths.authority) as tx:
        rows["authority"] = {r[0]: tx.execute(f'SELECT * FROM "{r[0]}" ORDER BY rowid').fetchall()
                             for r in tx.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    return rows


def detail(w, pid, ident, actor="owner"):
    response = w.client(actor).get(f"{BASE}/projects/{pid}/objects/material_handoff/{ident}")
    assert response.status_code == 200, response.text
    return response.json()


def test_handoff_real_api_receipt_and_nonaccounting(workflow):
    w = workflow
    pid, fields = setup(w)
    before = stock(w)
    ident = record(w, pid, fields)["object_id"]
    v = detail(w, pid, ident)["value"]
    assert v["state"] == "pending" and v["receipt"] is None
    assert v["sender_name"] == "Warehouse" and v["receiver_name"] == "Production"
    assert v["sender_id"] == str(USERS["warehouse"])
    assert v["source"]["mode"] == "manual" and v["source"]["object_type"] == "material_handoff"
    assert v["source"]["external_id"] == ident and v["handoff_number"]
    assert stock(w) == before
    receive(w, pid, ident)
    v = detail(w, pid, ident)["value"]
    assert v["state"] == "received"
    assert v["receipt"]["actor_id"] == str(USERS["production"])
    assert v["receipt"]["actor_name"] == "production"
    assert v["receipt"]["received_quantity"] == "1.250"
    assert len(detail(w, pid, ident)["history"]) == 2
    assert stock(w) == before


@pytest.mark.parametrize("quantity,location", [("1.000", "产线 B"), ("2.000", "产线 B"), ("0", "产线 B"), ("1.250", "产线 C")])
def test_handoff_discrepancy_requires_note_and_preserves_facts(workflow, quantity, location):
    w = workflow
    pid, fields = setup(w)
    ident = record(w, pid, fields)["object_id"]
    before = stock(w)
    receive(w, pid, ident, received_quantity=quantity, received_location=location, expected_status=422)
    receive(w, pid, ident, received_quantity=quantity, received_location=location, note="现场差异")
    original = detail(w, pid, ident)["value"]
    assert original["state"] == "disputed"
    assert "material_handoff.resolve" in detail(w, pid, ident, "warehouse")["summary"]["next_actions"]
    w.command(pid, "material_handoff.resolve", actor_name="warehouse", handoff_id=ident, resolution="已联系现场复核")
    v = detail(w, pid, ident)["value"]
    assert v["state"] == "resolved" and v["receipt"] == original["receipt"]
    assert v["quantity"] == "1.250" and v["to_location"] == "产线 B"
    assert v["resolution"]["resolution"] == "已联系现场复核"
    assert stock(w) == before
    w.command(pid, "material_handoff.cancel", handoff_id=ident, reason="cannot erase", expected_status=409)
    receive(w, pid, ident, expected_status=409)


def test_handoff_cancellation_and_invalid_transitions(workflow):
    w = workflow
    pid, fields = setup(w)
    ident = record(w, pid, fields)["object_id"]
    w.command(pid, "material_handoff.resolve", handoff_id=ident, resolution="invalid", expected_status=409)
    w.command(pid, "material_handoff.cancel", actor_name="warehouse", handoff_id=ident, reason="重复登记")
    v = detail(w, pid, ident)["value"]
    assert v["state"] == "cancelled" and v["cancellation"]["reason"] == "重复登记"
    assert v["quantity"] == "1.250" and v["receipt"] is None
    receive(w, pid, ident, expected_status=409)
    w.command(pid, "material_handoff.cancel", handoff_id=ident, reason="again", expected_status=409)


@pytest.mark.parametrize("overrides,status", [
    ({"unit": "piece"},409), ({"quantity":"1.0001"},409), ({"quantity":"9223372036854775.808"},409),
    ({"quantity":"0"},422), ({"quantity":"1e1"},422), ({"quantity":1},422),
    ({"from_location":" "},422), ({"to_location":"仓库 A"},422),
    ({"receiver_id":str(USERS["warehouse"])},422), ({"receiver_id":str(USERS["outsider"])},422),
    ({"sender_name":"forged"},422), ({"receiver_name":"forged"},422),
    ({"occurred_at":"2099-01-01T00:00:00Z"},422), ({"occurred_at":"2026-10-28T08:00:00"},422),
])
def test_handoff_rejects_invalid_record(workflow, overrides, status):
    w = workflow
    pid, fields = setup(w)
    record(w, pid, fields, expected_status=status, **overrides)


def test_handoff_receiver_membership_roles_and_relations(workflow):
    w = workflow
    pid, fields = setup(w)
    w.grant(pid, "quality", ["quality"])
    record(w, pid, fields, receiver_id=str(USERS["quality"]), expected_status=422)
    w.grant(pid, "production", ["production"], active=False)
    record(w, pid, fields, expected_status=422)
    w.grant(pid, "production", ["production"])
    other, other_fields = setup(w)
    record(w, pid, fields, material_lot_id=other_fields["material_lot_id"], expected_status=404)
    record(w, pid, fields, work_order_id=other_fields["work_order_id"], expected_status=404)
    ident = record(w, pid, fields)["object_id"]
    receive(w, other, ident, expected_status=404)
    assert w.client("outsider").get(f"{BASE}/projects/{pid}/objects/material_handoff/{ident}").status_code == 404


def test_handoff_receiver_only_live_policy_cas_csrf_and_replay(workflow):
    w = workflow
    pid, fields = setup(w)
    result = record(w, pid, fields)
    ident = result["object_id"]
    url = f"{BASE}/projects/{pid}/commands"
    version = w.client().get(f"{BASE}/projects/{pid}").json()["version"]
    body = dict(action="material_handoff.receive", operation_id=str(uuid4()), expected_version=version,
                handoff_id=ident, received_quantity="1.250", received_location="产线 B")
    for actor in ("owner", "admin", "warehouse"):
        assert w.client(actor).post(url,json=body).status_code == 403
        assert "material_handoff.receive" not in detail(w,pid,ident,actor)["summary"]["next_actions"]
    assert "material_handoff.receive" in detail(w,pid,ident,"production")["summary"]["next_actions"]
    assert w.client("production").post(url,json={**body,"expected_version":version-1}).status_code == 409
    assert w.client("production").post(url,json=body,headers={"x-csrf-token":"bad"}).status_code == 403
    first = w.client("production").post(url,json=body)
    assert first.status_code == 200, first.text
    assert w.client("production").post(url,json=body).json()["replayed"]
    assert w.client("production").post(url,json={**body,"note":"changed"}).status_code == 409
    w.read_only.add("production")
    assert w.client("production").post(url,json=body).status_code == 403
    w.read_only.clear()
    w.grant(pid,"production",["engineering"])
    assert w.client("production").post(url,json=body).status_code == 403
    w.grant(pid,"production",[],active=False)
    assert w.client("production").post(url,json=body).status_code == 404


def test_handoff_receive_time_precision_and_non_sender_cannot_handle(workflow):
    w = workflow
    pid, fields = setup(w)
    ident = record(w,pid,fields)["object_id"]
    for changes,status in [({"occurred_at":"2026-10-27T00:00:00Z"},422),
                           ({"occurred_at":"2099-01-01T00:00:00Z"},422),
                           ({"received_quantity":"0.0001","note":"difference"},409),
                           ({"received_quantity":"9223372036854775.808","note":"difference"},409)]:
        receive(w,pid,ident,expected_status=status,**changes)
    w.command(pid,"material_handoff.cancel",actor_name="production",handoff_id=ident,reason="other",expected_status=403)
    receive(w,pid,ident,received_quantity="0",note="missing")
    w.command(pid,"material_handoff.resolve",actor_name="production",handoff_id=ident,resolution="other",expected_status=403)
    w.grant(pid,"warehouse",["engineering"])
    w.command(pid,"material_handoff.resolve",actor_name="warehouse",handoff_id=ident,resolution="revoked",expected_status=403)
    w.grant(pid,"planner",["project_owner"])
    w.command(pid,"material_handoff.resolve",actor_name="planner",handoff_id=ident,resolution="owner handled")


def test_handoff_record_replay_after_state_change_and_non_oem(workflow):
    w=workflow
    pid,fields=setup(w)
    result=record(w,pid,fields)
    receive(w,pid,result["object_id"])
    body=dict(action="material_handoff.record",operation_id=result["operation_id"],expected_version=result["project_version"]-1,**fields)
    assert w.client("warehouse").post(f"{BASE}/projects/{pid}/commands",json=body).json()["replayed"]
    pid,fields=setup(w,mode="internal")
    record(w,pid,fields,expected_status=422)
    actions=w.client().get(f"{BASE}/projects/{pid}").json()["allowed_actions"]
    assert not any(a.startswith("material_handoff.") for a in actions)


def test_handoff_splits_restart_task_and_object_pagination(workflow):
    w=workflow
    pid,fields=setup(w)
    ids=[record(w,pid,fields,to_location=f"产线 {n}")["object_id"] for n in range(3)]
    w.reopen()
    tasks=w.client("production").get(f"{BASE}/tasks?limit=2").json()
    handoffs=[t for t in tasks["items"] if t["target"]["kind"]=="material_handoff"]
    assert len(handoffs)==2 and all(t["category"]=="business" for t in handoffs)
    page=w.client("production").get(f"{BASE}/projects/{pid}/objects/material_handoff?limit=1&offset=1").json()
    assert page["total"]==3 and [i["id"] for i in page["items"]]==ids[1:2]
    global_page=w.client("production").get(f"{BASE}/objects/material_handoff?limit=2").json()
    assert global_page["total"]==3 and len(global_page["items"])==2
    receive(w,pid,ids[0],received_location="产线 0")
    receive(w,pid,ids[1],received_quantity="0",received_location="产线 1",note="missing")
    assert detail(w,pid,ids[2])["value"]["state"]=="pending"
    tasks=w.client("warehouse").get(f"{BASE}/tasks").json()["items"]
    assert [t["target"]["id"] for t in tasks if t["target"]["kind"]=="material_handoff"]==ids[1:2]
    w.grant(pid,"production",["engineering"])
    assert not [t for t in w.client("production").get(f"{BASE}/tasks").json()["items"] if t["target"]["kind"]=="material_handoff"]


def test_handoff_schema21_upgrade_preserves_previous_rows(workflow):
    w=workflow
    pid,fields=setup(w)
    before=stock(w)
    # Rebuild from the actual archived schema21 boundary, including all existing rows.
    w._client.close()
    previous=w.paths.domain.with_suffix(".v21")
    with sqlite3.connect(previous) as dst, sqlite3.connect(w.paths.domain) as src:
        dst.executescript((Path(__file__).parent/"fixtures/schema21.sql").read_text())
        dst.execute("PRAGMA foreign_keys=OFF")
        for (table,) in src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'material_handoff%' AND name!='sqlite_sequence'"):
            rows=src.execute(f'SELECT * FROM "{table}"').fetchall()
            if rows:
                dst.executemany(f'INSERT INTO "{table}" VALUES ({",".join("?" for _ in rows[0])})',rows)
        dst.execute("UPDATE schema_version SET version=21")
        assert not dst.execute("SELECT name FROM sqlite_master WHERE name='material_handoffs'").fetchall()
    previous.replace(w.paths.domain)
    w.reopen()
    assert w.client().get(f"{BASE}/projects/{pid}").status_code==200
    with w.db() as tx:
        assert tx.execute("SELECT version FROM schema_version").fetchone()[0]==23
    assert stock(w)==before
    ident=record(w,pid,fields)["object_id"]
    receive(w,pid,ident)
    assert detail(w,pid,ident)["value"]["state"]=="received"


def test_handoff_project_receive_capability_is_designated_and_current(workflow):
    w=workflow
    pid,fields=setup(w)
    ident=record(w,pid,fields)["object_id"]
    def actions(actor):
        return w.client(actor).get(f"{BASE}/projects/{pid}").json()["allowed_actions"]
    assert "material_handoff.receive" not in actions("admin")
    assert "material_handoff.receive" not in actions("warehouse")
    assert "material_handoff.receive" in actions("production")
    receive(w,pid,ident)
    assert "material_handoff.receive" not in actions("production")


def test_handoff_concurrent_receipts_and_immutable_cancel_replay(workflow):
    from concurrent.futures import ThreadPoolExecutor
    w=workflow
    pid,fields=setup(w)
    ident=record(w,pid,fields)["object_id"]
    version=w.client().get(f"{BASE}/projects/{pid}").json()["version"]
    body=dict(action="material_handoff.receive",expected_version=version,handoff_id=ident,
              received_quantity="1.250",received_location="产线 B")
    def post(_):
        return w.client("production").post(f"{BASE}/projects/{pid}/commands",json={**body,"operation_id":str(uuid4())})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(post,range(2)))
    assert sorted(r.status_code for r in responses)==[200,409]
    assert len(detail(w,pid,ident)["history"])==2
    ident=record(w,pid,fields)["object_id"]
    result=w.command(pid,"material_handoff.cancel",actor_name="warehouse",handoff_id=ident,reason="错录")
    body=dict(action="material_handoff.cancel",expected_version=result["project_version"]-1,
              operation_id=result["operation_id"],handoff_id=ident,reason="错录")
    before=detail(w,pid,ident)["value"]
    assert w.client("warehouse").post(f"{BASE}/projects/{pid}/commands",json=body).json()["replayed"]
    assert detail(w,pid,ident)["value"]==before


def test_handoff_tasks_are_bounded_and_truncated(workflow):
    w=workflow
    pid,fields=setup(w)
    for _ in range(51):
        record(w,pid,fields)
    page=w.client("production").get(f"{BASE}/tasks?project_id={pid}&limit=50").json()
    assert len(page["items"])==50 and page["truncated"]
    assert not [t for t in w.client("warehouse").get(f"{BASE}/tasks?project_id={pid}").json()["items"] if t["target"]["kind"]=="material_handoff"]
    w.read_only.add("production")
    assert w.client("production").get(f"{BASE}/tasks?project_id={pid}").json()["items"]==[]


def test_handoff_business_clock_source_and_audit(workflow):
    w=workflow
    now=datetime(2026,11,1,8,tzinfo=UTC)
    w.business_clock=lambda: now
    w.reopen()
    pid,fields=setup(w)
    fields.pop("occurred_at")
    ident=record(w,pid,fields)["object_id"]
    d=detail(w,pid,ident)
    assert datetime.fromisoformat(d["value"]["occurred_at"].replace("Z","+00:00"))==now
    assert datetime.fromisoformat(d["history"][0]["occurred_at"].replace("Z","+00:00"))==now
    assert datetime.fromisoformat(d["history"][0]["recorded_at"].replace("Z","+00:00"))==now
    assert d["value"]["source"]["occurred_at"]==d["value"]["occurred_at"]


@pytest.mark.parametrize("retire", ["production", "warehouse"])
def test_handoff_competing_creation_replay_precedes_profile_error(workflow, monkeypatch, retire):
    from manufacturing_platform.workflow.contracts import DomainError
    from manufacturing_platform.workflow.service import WorkflowService
    w=workflow
    pid,fields=setup(w)
    body=dict(action="material_handoff.record",operation_id=str(uuid4()),
              expected_version=w.client().get(f"{BASE}/projects/{pid}").json()["version"],**fields)
    url=f"{BASE}/projects/{pid}/commands"
    original=WorkflowService.member_profiles
    entered=False
    committed=[]
    def lookup(service,actor,project_id,ids):
        nonlocal entered
        if entered:
            return original(service,actor,project_id,ids)
        entered=True
        assert set(map(str,ids))=={str(USERS["warehouse"]),str(USERS["production"])}
        other=w.client("warehouse").post(url,json=body)
        assert other.status_code==200,other.text
        committed.append(other.json())
        w.grant(pid,retire,[retire],active=False)
        raise DomainError("INVALID_SUBJECT",422,"Profile unavailable after competing commit")
    monkeypatch.setattr(WorkflowService,"member_profiles",lookup)
    response=w.client("warehouse").post(url,json=body)
    assert response.status_code==(200 if retire=="production" else 404),response.text
    if retire=="production":
        assert response.json()["replayed"] and response.json()["object_id"]==committed[0]["object_id"]
    with w.db() as tx:
        assert tx.execute("SELECT COUNT(*) FROM material_handoffs WHERE project_id=?",(pid,)).fetchone()[0]==1


def test_handoff_missing_directory_name_preserves_real_identity(workflow,monkeypatch):
    from manufacturing_platform.workflow.service import WorkflowService
    w=workflow
    pid,fields=setup(w)
    original=WorkflowService.member_profiles
    def unnamed(service,actor,project_id,ids):
        original(service,actor,project_id,ids)
        return {}
    monkeypatch.setattr(WorkflowService,"member_profiles",unnamed)
    ident=record(w,pid,fields)["object_id"]
    value=detail(w,pid,ident)["value"]
    assert value["receiver_name"]==str(USERS["production"])
    assert value["receiver_id"]==str(USERS["production"])
    assert value["sender_name"]=="warehouse"


def test_handoff_profile_lookup_race_rechecks_cas_and_policy(workflow,monkeypatch):
    from manufacturing_platform.workflow.service import WorkflowService
    w=workflow
    pid,fields=setup(w)
    original=WorkflowService.member_profiles
    def revoke(service,actor,project_id,ids):
        profiles=original(service,actor,project_id,ids)
        w.grant(pid,"production",[],active=False)
        return profiles
    monkeypatch.setattr(WorkflowService,"member_profiles",revoke)
    record(w,pid,fields,expected_status=409)
    with w.db() as tx:
        assert tx.execute("SELECT COUNT(*) FROM material_handoffs WHERE project_id=?",(pid,)).fetchone()[0]==0


def test_handoff_list_and_task_sql_boundaries(workflow,monkeypatch):
    from contextlib import contextmanager
    from manufacturing_platform.workflow.store import WorkflowStore
    w=workflow
    pid,fields=setup(w)
    other,other_fields=setup(w)
    for _ in range(3):
        record(w,pid,fields)
        record(w,other,other_fields)
    statements=[]
    original=WorkflowStore.transaction
    @contextmanager
    def traced(store,**kwargs):
        with original(store,**kwargs) as tx:
            tx.set_trace_callback(statements.append)
            yield tx
    monkeypatch.setattr(WorkflowStore,"transaction",traced)
    response=w.client("production").get(f"{BASE}/projects/{pid}/objects/material_handoff?limit=1&offset=1")
    assert response.status_code==200,response.text
    pages=[q for q in statements if "SELECT * FROM material_handoffs" in q and "ORDER BY seq" in q]
    assert len(pages)==1
    assert f"project_id='{pid}' ORDER BY seq LIMIT 1 OFFSET 1" in pages[0]
    statements.clear()
    response=w.client("production").get(f"{BASE}/tasks?project_id={pid}&limit=1")
    assert response.status_code==200,response.text
    query=next(q for q in statements if "UNION ALL SELECT 'Awaiting designated receiver'" in q)
    assert "ORDER BY category,id LIMIT 51" in query
    assert other not in query
    assert f"h.project_id='{pid}' AND h.receiver_id='{USERS['production']}'" in query


@pytest.mark.parametrize("blank_name", ["", " \t "])
@pytest.mark.parametrize("phase", ["record", "receive", "resolve", "cancel"])
def test_handoff_blank_trusted_actor_names_preserve_readable_identity(
    workflow, monkeypatch, blank_name, phase,
):
    from . import conftest

    w = workflow
    pid, fields = setup(w)
    if phase != "record":
        ident = record(w, pid, fields)["object_id"]
    if phase == "resolve":
        receive(w, pid, ident, received_quantity="0", note="现场缺料")

    actor_name = "production" if phase == "receive" else "warehouse"
    original_router = conftest.build_workflow_router

    def with_blank_trusted_name(**options):
        authenticate = options["authenticate"]

        def trusted_actor(request, write=False):
            identity = authenticate(request, write=write)
            if request.headers.get("x-test-actor") == actor_name:
                identity["display_name"] = blank_name
            return identity

        options["authenticate"] = trusted_actor
        if phase == "record":
            options["resolve_subject_profiles"] = lambda ids: []
        return original_router(**options)

    monkeypatch.setattr(conftest, "build_workflow_router", with_blank_trusted_name)
    w.reopen()
    if phase == "record":
        ident = record(w, pid, fields)["object_id"]
    elif phase == "receive":
        receive(w, pid, ident, received_quantity="0", note="现场缺料")
    elif phase == "resolve":
        w.command(pid, "material_handoff.resolve", actor_name="warehouse",
                  handoff_id=ident, resolution="缺料已补送")
    else:
        w.command(pid, "material_handoff.cancel", actor_name="warehouse",
                  handoff_id=ident, reason="交接错录")

    value = detail(w, pid, ident)["value"]
    if phase == "record":
        assert value["sender_name"] == str(USERS["warehouse"])
        assert value["receiver_name"] == str(USERS["production"])
    else:
        fact = value[{"receive": "receipt", "resolve": "resolution", "cancel": "cancellation"}[phase]]
        assert fact["actor_name"] == str(USERS[actor_name])
        assert fact["actor_id"] == str(USERS[actor_name])
    assert value["state"] == {
        "record": "pending", "receive": "disputed", "resolve": "resolved", "cancel": "cancelled",
    }[phase]
    for actor in ("owner", "warehouse", "production"):
        for route in (f"/projects/{pid}/objects/material_handoff", "/objects/material_handoff",
                      f"/tasks?project_id={pid}"):
            response = w.client(actor).get(BASE + route)
            assert response.status_code == 200, response.text
    tasks = w.client("production" if phase == "record" else "warehouse").get(
        f"{BASE}/tasks?project_id={pid}"
    ).json()["items"]
    handoff_tasks = [t for t in tasks if t["target"]["kind"] == "material_handoff"]
    assert len(handoff_tasks) == (1 if phase in {"record", "receive"} else 0)
