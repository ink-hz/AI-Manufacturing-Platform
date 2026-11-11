from uuid import uuid4

from .conftest import BASE


def test_material_projection_keeps_inspection_and_reservation_separate(workflow):
    p, req, _ = workflow.material_requirement(mode="oem", qualified="80")
    r = workflow.client().get(f"{BASE}/projects/{p['id']}/material-control")
    assert r.status_code == 200
    row = next(x for x in r.json()["requirements"] if x["id"] == req["id"])
    assert (row["qualified"], row["reserved"], row["shortage"]) == ("80", "0", "100")
    assert r.json()["coverage_issues"]
    assert row["need_at"] and row["need_at_basis"] == "work_order_planned_start_proxy"
    assert row["timing_risk"] == "unknown"
    assert "manual" in r.json()["source_modes"]
    assert r.json()["receipts"][0]["qualified"] == "80"


def test_authorization_filters_pagination_and_no_mutation(workflow):
    p, req, related = workflow.material_requirement()
    path = f"{BASE}/projects/{p['id']}/material-control"
    assert workflow.client("outsider").get(path).status_code == 404
    assert workflow.client("outsider").get(f"{BASE}/material-control/overview").json()["total"] == 0
    workflow.read_only.add("owner")
    with workflow.db() as db:
        snapshot = list(db.iterdump())
    assert workflow.client().get(path, params={"work_order_id": related["work_order_id"], "requirement_id": req["id"]}).status_code == 200
    assert workflow.client().get(path, params={"work_order_id": str(uuid4())}).status_code == 404
    assert workflow.client().get(path, params={"requirement_id": str(uuid4())}).status_code == 404
    for params in ({"limit": 0}, {"limit": 501}, {"offset": -1}):
        assert workflow.client().get(path, params=params).status_code == 422
    overview = workflow.client().get(f"{BASE}/material-control/overview", params={"limit": 1}).json()
    assert overview["total"] == 1 and overview["items"][0]["requirement_count"] == 1
    assert workflow.client().get(f"{BASE}/material-control/overview", params={"limit": 1, "offset": 1}).json()["total"] == 1
    with workflow.db() as db:
        assert list(db.iterdump()) == snapshot
    workflow.read_only.remove("owner")
    workflow.grant(p["id"], "supply", ["supply"], active=False)
    assert workflow.client("supply").get(path).status_code == 404


def test_overview_pages_preserve_counts_and_mock_provenance(workflow):
    import sqlite3
    first, req, _ = workflow.material_requirement(qualified='0')
    # Simulate a persisted mock-source fact; command registration only accepts manual sources.
    with sqlite3.connect(workflow.paths.domain) as db:
        db.execute("UPDATE work_orders SET source_json=json_set(source_json, '$.mode', 'mock') WHERE project_id=?", (first['id'],))
    workflow.create_project(name='Other project')
    path = f'{BASE}/material-control/overview'
    pages = [workflow.client().get(path, params={'limit': 1, 'offset': offset}).json() for offset in (0, 1)]
    assert all(page['total'] == 2 for page in pages)
    assert [page['items'][0]['project_id'] for page in pages] == sorted([first['id'], next(page['items'][0]['project_id'] for page in pages if page['items'][0]['project_id'] != first['id'])])
    first_item = next(page['items'][0] for page in pages if page['items'][0]['project_id'] == first['id'])
    assert first_item['requirement_count'] == 1 and 'mock' in first_item['source_modes']
    project = workflow.client().get(f"{BASE}/projects/{first['id']}/material-control", params={'limit': 1, 'offset': 1}).json()
    assert project['total'] == 1 and not project['requirements'] and project['coverage_issues']


def test_linked_expedite_and_handoff_preserve_details(workflow):
    from .conftest import USERS
    p, req, related = workflow.material_requirement(mode='oem')
    workflow.grant(p['id'], 'warehouse', ['warehouse'])
    workflow.grant(p['id'], 'production', ['production'])
    expedite = workflow.command(p['id'], 'expedite.open', actor_name='supply', requirement_id=req['id'], reason='late', impact='delay')['object_id']
    handoff = workflow.command(p['id'], 'material_handoff.record', actor_name='warehouse', material_lot_id=related['lot_id'], work_order_id=related['work_order_id'], quantity='1', unit='kg', from_location='Warehouse', to_location='Line', receiver_id=str(USERS['production']))['object_id']
    response = workflow.client().get(f"{BASE}/projects/{p['id']}/material-control").json()
    assert response['requirements'][0]['expedite_ids'] == [expedite]
    assert response['requirements'][0]['handoff_ids'] == [handoff]
    assert response['expedites'][0]['source']['mode'] == 'manual'
    assert response['handoffs'][0]['to_location'] == 'Line'
    overview = workflow.client().get(f'{BASE}/material-control/overview').json()['items'][0]
    assert (overview['open_expedite_count'], overview['unreceived_handoff_count']) == (1, 1)
