"""Manual issue marks are immutable, scoped coordination facts, never postings."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from .conftest import BASE, USERS
from .test_expedites import setup
from .test_expedite_tasks import requirements, stock


def mark(w, pid, rid, stage="printed", **fields):
    return w.command(pid, "issue.mark", actor_name=fields.pop("actor_name", "warehouse"),
                     requirement_id=rid, stage=stage, **fields)


def detail(w, pid, ident):
    response = w.client().get(f"{BASE}/projects/{pid}/objects/issue_mark/{ident}")
    assert response.status_code == 200, response.text
    return response.json()


def page(w, pid, **params):
    response = w.client().get(f"{BASE}/projects/{pid}/objects/issue_mark", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_four_stages_allow_out_of_order_historical_repeats_and_survive_restart(workflow):
    w = workflow
    pid, rid, extras = setup(w)
    before = stock(w)
    w.configuration_admins.discard("owner")  # Exercise the actual project_owner grant.
    ids = []
    snapshots = []
    for stage, actor in [("posted", "warehouse"), ("receipted", "production"),
                         ("printed", "owner"), ("picked", "supply")]:
        ident = mark(w, pid, rid, stage, actor_name=actor)["object_id"]
        ids.append(ident)
        item = detail(w, pid, ident)
        value = item["value"]
        assert value["stage"] == stage and value["requirement_id"] == rid
        assert value["note"] is None
        assert value["work_order_id"] == extras["work_order_id"]
        assert value["actor_id"] == str(USERS[actor])
        assert value["actor_name"] == actor
        assert value["occurred_at"] == value["recorded_at"]
        source = value["source"]
        assert (source["system"], source["mode"], source["object_type"]) == ("manual", "manual", "issue_mark")
        assert source["external_id"] == ident and source["version"] == 1
        assert source["occurred_at"] == value["occurred_at"]
        assert source["collected_at"] == value["recorded_at"]
        assert str(USERS[actor]) in source["evidence"]
        assert stage in item["summary"]["title"] and "steel-1" in item["summary"]["title"]
        assert item["summary"]["next_actions"] == []
        assert {(r["kind"], r["id"]) for r in item["relations"]} == {
            ("requirement", rid), ("work_order", extras["work_order_id"])}
        snapshots.append(item)
        assert stock(w) == before
    historical = "2026-10-28T09:30:00+08:00"
    ident = mark(w, pid, rid, "printed", note="补录纸单", occurred_at=historical)["object_id"]
    ids.append(ident)
    value = detail(w, pid, ident)["value"]
    assert value["note"] == "补录纸单"
    assert datetime.fromisoformat(value["occurred_at"]) == datetime.fromisoformat(historical)
    assert datetime.fromisoformat(value["occurred_at"]) < datetime.fromisoformat(value["recorded_at"])
    assert [i["id"] for i in page(w, pid)["items"]] == ids
    w.reopen()
    assert [detail(w, pid, ident) for ident in ids[:4]] == snapshots
    assert stock(w) == before


@pytest.mark.parametrize("fields", [
    {"stage": "shipped"}, {"occurred_at": "2026-10-28T08:00:00"},
    {"occurred_at": (datetime.now(UTC) + timedelta(days=2)).isoformat()},
    {"actor_id": str(USERS["quality"])}, {"actor_name": "Spoofed"},
    {"source": {"system": "sap", "mode": "live"}},
    {"recorded_at": "2026-10-28T08:00:00Z"},
])
def test_invalid_stage_time_and_untrusted_fact_fields_are_rejected(workflow, fields):
    w = workflow
    pid, rid, _ = setup(w)
    before = stock(w)
    response = w.client("warehouse").post(f"{BASE}/projects/{pid}/commands", json={
        "operation_id": str(uuid4()),
        "expected_version": w.client().get(f"{BASE}/projects/{pid}").json()["version"],
        "action": "issue.mark", "requirement_id": rid, "stage": "printed", **fields})
    assert response.status_code == 422, response.text
    assert page(w, pid)["total"] == 0
    assert stock(w) == before


def test_role_oem_and_project_boundaries(workflow):
    w = workflow
    p, r, _ = w.material_requirement(mode="internal")
    mark(w, p["id"], r["id"], actor_name="supply", expected_status=422)
    assert "issue.mark" not in w.client().get(f"{BASE}/projects/{p['id']}").json()["allowed_actions"]
    pid, rid, _ = setup(w)
    for actor in ("quality", "planner", "engineering"):
        mark(w, pid, rid, actor_name=actor, expected_status=403)
    mark(w, pid, r["id"], expected_status=404)
    mark(w, pid, str(uuid4()), expected_status=404)
    ident = mark(w, pid, rid)["object_id"]
    assert w.client("outsider").get(f"{BASE}/projects/{pid}/objects/issue_mark/{ident}").status_code == 404
    w.read_only.add("warehouse")
    mark(w, pid, rid, expected_status=403)
    w.read_only.clear()
    w.grant(pid, "warehouse", [], active=False)
    # A revoked member cannot access the project version needed by command().
    response = w.client("warehouse").post(f"{BASE}/projects/{pid}/commands", json={
        "action": "issue.mark", "operation_id": str(uuid4()), "expected_version": 1,
        "requirement_id": rid, "stage": "printed"})
    assert response.status_code == 404


def test_requirement_filter_counts_and_paginates_after_sql_scope(workflow):
    w = workflow
    pid, rid, extras = setup(w)
    other = requirements(w, pid, extras)[0]
    empty = requirements(w, pid, extras)[0]
    wanted = []
    for _ in range(5):
        mark(w, pid, other)
        wanted.append(mark(w, pid, rid)["object_id"])
    assert page(w, pid)["total"] == 10
    for offset in (0, 2, 4, 6):
        result = page(w, pid, requirement_id=rid, limit=2, offset=offset)
        assert result["total"] == 5
        assert [v["id"] for v in result["items"]] == wanted[offset:offset + 2]
    assert page(w, pid, requirement_id=empty)["items"] == []
    p2, r2, _ = w.material_requirement(mode="oem", qualified="0")
    mark(w, p2["id"], r2["id"], actor_name="supply")
    assert w.client().get(f"{BASE}/projects/{pid}/objects/issue_mark", params={"requirement_id": r2["id"]}).status_code == 404
    for kind in ("receipt", "requirement", "material_expedite"):
        response = w.client().get(f"{BASE}/projects/{pid}/objects/{kind}", params={"requirement_id": rid})
        assert response.status_code == 422
    assert w.client().get(f"{BASE}/projects/{pid}/objects/issue_mark?requirement_id=bad").status_code == 422


def test_issue_mark_uses_business_clock_for_default_future_validation_and_audit(workflow):
    w = workflow
    pid, rid, _ = setup(w)
    now = datetime(2026, 11, 1, 8, tzinfo=UTC)
    w.business_clock = lambda: now
    w.reopen()
    ident = mark(w, pid, rid)["object_id"]
    item = detail(w, pid, ident)
    assert datetime.fromisoformat(item["value"]["recorded_at"]) == now
    assert datetime.fromisoformat(item["value"]["occurred_at"]) == now
    assert datetime.fromisoformat(item["history"][0]["recorded_at"]) == now
    assert datetime.fromisoformat(item["history"][0]["occurred_at"]) == now
    mark(w, pid, rid, occurred_at=(now + timedelta(seconds=1)).isoformat(), expected_status=422)
    happened = now - timedelta(days=2)
    ident = mark(w, pid, rid, occurred_at=happened.isoformat())["object_id"]
    item = detail(w, pid, ident)
    assert datetime.fromisoformat(item["history"][0]["occurred_at"]) == happened
    assert datetime.fromisoformat(item["history"][0]["recorded_at"]) == now


def test_command_replay_preserves_original_fact_and_conflicting_replay_cannot_overwrite(workflow):
    w = workflow
    pid, rid, _ = setup(w)
    before = stock(w)
    body = dict(action="issue.mark", requirement_id=rid, stage="posted", note="纸单凭证",
                operation_id=str(uuid4()),
                expected_version=w.client().get(f"{BASE}/projects/{pid}").json()["version"])
    url = f"{BASE}/projects/{pid}/commands"
    first = w.client("warehouse").post(url, json=body)
    assert first.status_code == 200, first.text
    ident = first.json()["object_id"]
    original = detail(w, pid, ident)
    replay = w.client("warehouse").post(url, json=body)
    assert replay.status_code == 200 and replay.json()["replayed"]
    assert replay.json()["object_id"] == ident
    conflict = w.client("warehouse").post(url, json={**body, "note": "覆盖"})
    assert conflict.status_code == 409
    assert page(w, pid)["total"] == 1
    assert detail(w, pid, ident) == original
    assert stock(w) == before
