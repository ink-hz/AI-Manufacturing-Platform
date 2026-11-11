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
    assert response['expedites'][0]['progress_total'] == 0
    assert response['expedites'][0]['progress_truncated'] is False
    assert response['expedites'][0]['milestones'] == workflow.object(p['id'], 'material_expedite', expedite)['milestones']
    assert response['handoffs'][0]['to_location'] == 'Line'
    overview = workflow.client().get(f'{BASE}/material-control/overview').json()['items'][0]
    assert (overview['open_expedite_count'], overview['unreceived_handoff_count']) == (1, 1)


def test_expedite_progress_is_a_bounded_preview(workflow):
    import sqlite3
    p, req, _ = workflow.material_requirement(mode='oem')
    case = workflow.command(p['id'], 'expedite.open', actor_name='supply', requirement_id=req['id'], reason='late', impact='delay')['object_id']
    workflow.command(p['id'], 'expedite.progress', actor_name='supply', expedite_id=case, note='first')
    with sqlite3.connect(workflow.paths.domain) as db:
        payload = db.execute('SELECT payload_json FROM expedite_progress WHERE expedite_id=?', (case,)).fetchone()[0]
        db.executemany('INSERT INTO expedite_progress(project_id,expedite_id,payload_json) VALUES (?,?,?)', [(p['id'], case, payload)] * 25)
    page = workflow.client().get(f"{BASE}/projects/{p['id']}/material-control").json()
    item = page['expedites'][0]
    assert len(item['progress']) == 20
    assert item['progress_total'] == 26 and item['progress_truncated'] is True
    assert item['source']['mode'] == 'manual' and item['milestones']['receipt_at']
    assert any('progress' in issue for issue in page['coverage_issues'])


def test_requirement_paging_and_filter_scope(workflow):
    import sqlite3
    first, req, related = workflow.material_requirement()
    other, other_req, other_related = workflow.material_requirement()
    # Two extra persisted requirements, one on a second work order in the same project.
    extra_req, third_req, second_wo = str(uuid4()), str(uuid4()), str(uuid4())
    with sqlite3.connect(workflow.paths.domain) as db:
        db.row_factory = sqlite3.Row
        def clone(table, ident, **updates):
            row = dict(db.execute(f'SELECT * FROM {table} WHERE id=?', (ident,)).fetchone())
            row.update(updates)
            columns = list(row)
            db.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", [row[c] for c in columns])
        clone('work_orders', related['work_order_id'], id=second_wo, source_external_id=str(uuid4()))
        clone('requirements', req['id'], id=extra_req, lineage_id=str(uuid4()))
        clone('requirements', req['id'], id=third_req, lineage_id=str(uuid4()), work_order_id=second_wo)
    path = f"{BASE}/projects/{first['id']}/material-control"
    pages = [workflow.client().get(path, params={'limit': 1, 'offset': i}).json() for i in range(3)]
    assert all(p['total'] == 3 for p in pages)
    assert len({p['requirements'][0]['id'] for p in pages}) == 3
    assert [p['requirements'][0]['id'] for p in pages] == sorted([req['id'], extra_req, third_req])
    filtered = workflow.client().get(path, params={'work_order_id': second_wo}).json()
    assert filtered['total'] == 1 and filtered['requirements'][0]['id'] == third_req
    assert workflow.client().get(path, params={'work_order_id': second_wo, 'requirement_id': req['id']}).status_code == 404
    assert workflow.client().get(path, params={'work_order_id': other_related['work_order_id']}).status_code == 404
    assert workflow.client().get(path, params={'requirement_id': other_req['id']}).status_code == 404
    assert workflow.client('outsider').get(path, params={'requirement_id': other_req['id']}).status_code == 404


def test_projection_does_not_materialize_object_history(workflow, monkeypatch):
    import sqlite3
    from manufacturing_platform.workflow.queries import ObjectRegistry
    p, req, _ = workflow.material_requirement(mode='oem')
    with sqlite3.connect(workflow.paths.domain) as db:
        columns = [row[1] for row in db.execute('PRAGMA table_info(audit_events)') if row[1] != 'id']
        names = ','.join(columns)
        audit = db.execute(f'SELECT {names} FROM audit_events WHERE project_id=? LIMIT 1', (p['id'],)).fetchone()
        db.executemany(f"INSERT INTO audit_events ({names}) VALUES ({','.join('?' for _ in columns)})", [audit] * 600)
    def no_detail(*args, **kwargs):
        raise AssertionError('projection must not invoke history-bearing object detail readers')
    monkeypatch.setattr(ObjectRegistry, 'detail', no_detail)
    response = workflow.client().get(f"{BASE}/projects/{p['id']}/material-control")
    assert response.status_code == 200
    assert response.json()['receipts'][0]['qualified'] == '80'
    assert response.json()['requirements'][0]['id'] == req['id']


def test_overview_uses_sql_pagination_with_grant_scope(workflow, monkeypatch):
    from manufacturing_platform.workflow import material_control
    first = workflow.create_project(name='First')
    second = workflow.create_project(name='Second')
    workflow.grant(first['id'], 'supply', ['supply'])
    workflow.grant(second['id'], 'supply', ['supply'])
    def no_unbounded_project_ids(*args, **kwargs):
        raise AssertionError('overview must page authorized projects in SQL')
    monkeypatch.setattr(material_control, 'project_ids', no_unbounded_project_ids, raising=False)
    pages = [workflow.client('supply').get(f'{BASE}/material-control/overview', params={'limit': 1, 'offset': i}).json() for i in (0, 1)]
    assert all(page['total'] == 2 for page in pages)
    assert [page['items'][0]['project_id'] for page in pages] == sorted([first['id'], second['id']])
    workflow.grant(second['id'], 'supply', ['supply'], active=False)
    page = workflow.client('supply').get(f'{BASE}/material-control/overview').json()
    assert page['total'] == 1 and page['items'][0]['project_id'] == first['id']


def test_overview_counts_quantity_not_handoff_resolution_state(workflow):
    from .conftest import USERS
    p, _, related = workflow.material_requirement(mode='oem')
    workflow.grant(p['id'], 'warehouse', ['warehouse'])
    workflow.grant(p['id'], 'production', ['production'])
    pid = p['id']
    def record(quantity):
        return workflow.command(pid, 'material_handoff.record', actor_name='warehouse', material_lot_id=related['lot_id'], work_order_id=related['work_order_id'], quantity=quantity, unit='kg', from_location='Warehouse', to_location='Line', receiver_id=str(USERS['production']))['object_id']
    def count():
        return workflow.client().get(f'{BASE}/material-control/overview').json()['items'][0]['unreceived_handoff_count']
    short = record('20')
    assert count() == 1
    workflow.command(pid, 'material_handoff.receive', actor_name='production', handoff_id=short, received_quantity='18', received_location='Line', note='short')
    assert count() == 1
    workflow.command(pid, 'material_handoff.resolve', actor_name='warehouse', handoff_id=short, resolution='noted')
    assert count() == 1
    full = record('1')
    workflow.command(pid, 'material_handoff.receive', actor_name='production', handoff_id=full, received_quantity='1', received_location='Line')
    cancelled = record('1')
    workflow.command(pid, 'material_handoff.cancel', actor_name='warehouse', handoff_id=cancelled, reason='duplicate')
    misplaced = record('1')
    workflow.command(pid, 'material_handoff.receive', actor_name='production', handoff_id=misplaced, received_quantity='1', received_location='Other', note='wrong location')
    over = record('1')
    workflow.command(pid, 'material_handoff.receive', actor_name='production', handoff_id=over, received_quantity='1.001', received_location='Other', note='over and wrong location')
    assert count() == 1


def test_current_plans_filter_demand_but_explicit_history_remains_accessible(workflow):
    import sqlite3
    from datetime import UTC, datetime, timedelta

    p, old, related = workflow.material_requirement(mode='oem', qualified='0')
    pid, wid = p['id'], related['work_order_id']
    removed, other_req, other_wo = (str(uuid4()) for _ in range(3))
    with sqlite3.connect(workflow.paths.domain) as db:
        db.row_factory = sqlite3.Row
        def clone(table, ident, **updates):
            row = dict(db.execute(f'SELECT * FROM {table} WHERE id=?', (ident,)).fetchone())
            row.update(updates)
            columns = list(row)
            db.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", [row[c] for c in columns])
        clone('work_orders', wid, id=other_wo, source_external_id=str(uuid4()))
        clone('requirements', old['id'], id=removed, lineage_id=str(uuid4()), material_id='removed')
        clone('requirements', old['id'], id=other_req, lineage_id=str(uuid4()), work_order_id=other_wo)
    case = workflow.command(pid, 'expedite.open', actor_name='supply', requirement_id=old['id'], reason='late', impact='delay')['object_id']
    original = workflow.object(pid, 'plan', workflow.object(pid, 'requirement', old['id'])['plan_id'])
    now = datetime.now(UTC)
    source = workflow.source(original['source']['external_id'], object_type='plan', version=2)
    source.update(occurred_at=(now-timedelta(minutes=2)).isoformat(), collected_at=(now-timedelta(minutes=1)).isoformat(), cutoff=(now-timedelta(minutes=2)).isoformat())
    details = dict(input_revision_ids=[related['revision_id']], input_order_versions=[{'order_line_id': related['order_id'], 'version': 1}], requirements=[{'work_order_id': wid, 'execution_scope': 'trial', 'material_id': 'steel-1', 'owner_id': 'Customer 1', 'quantity': '50', 'unit': 'kg'}])
    revised = workflow.command(pid, 'plan.receive', actor_name='planner', source=source, **details)
    plan = workflow.object(pid, 'plan', revised['object_id'])
    assert plan['state'] == 'confirmed'
    new_id = plan['requirement_ids'][0]
    rejected_source = workflow.source(original['source']['external_id'], object_type='plan', version=3)
    rejected_source.update(source, version=3, cutoff=None)
    rejected = workflow.command(pid, 'plan.receive', actor_name='planner', source=rejected_source, **details)
    assert workflow.object(pid, 'plan', rejected['object_id'])['state'] == 'rejected'

    path = f'{BASE}/projects/{pid}/material-control'
    pages = [workflow.client().get(path, params={'limit': 1, 'offset': i}).json() for i in range(3)]
    assert all(page['total'] == 2 for page in pages)
    assert {page['requirements'][0]['id'] for page in pages[:2]} == {new_id, other_req}
    assert pages[2]['requirements'] == []
    assert all(page['requirements'][0]['state'] == 'required' for page in pages[:2])
    filtered = workflow.client().get(path, params={'work_order_id': wid}).json()
    assert filtered['total'] == 1 and filtered['requirements'][0]['id'] == new_id
    historical = workflow.client().get(path, params={'requirement_id': old['id']}).json()
    assert historical['total'] == 1 and historical['requirements'][0]['state'] == 'superseded'
    assert historical['requirements'][0]['expedite_ids'] == [case]
    assert historical['expedites'][0]['id'] == case
    removed_view = workflow.client().get(path, params={'requirement_id': removed}).json()
    assert removed_view['requirements'][0]['state'] == 'superseded'
    overview = workflow.client().get(f'{BASE}/material-control/overview').json()['items'][0]
    assert overview['requirement_count'] == 2 and overview['open_expedite_count'] == 1
