import sqlite3

from .conftest import BASE
from .test_exchanges import reserve, stock, act


def test_expired_or_frozen_lot_is_not_usable_in_single_or_batch_balance(workflow):
    p, req, supply, result = reserve(workflow)
    stock(workflow, p, supply)
    act(workflow, p, result)
    assert workflow.balance(p['id'], req['id'])['shortage'] == '20'
    with sqlite3.connect(workflow.paths.domain) as db:
        db.execute("UPDATE material_lots SET expiry='2000-01-01' WHERE id=?", (supply['lot_id'],))
    assert workflow.balance(p['id'], req['id'])['shortage'] == '100'
    page = workflow.client().get(f"{BASE}/projects/{p['id']}/objects/requirement").json()
    row = next(x for x in page['items'] if x['id'] == req['id'])
    assert row['material_balance']['shortage'] == '100'


def test_need_time_override_and_reset_are_requirement_specific(workflow):
    p, req, _ = workflow.material_requirement()
    path = f"{BASE}/projects/{p['id']}/material-control"
    workflow.command(p['id'], 'material.need_time', requirement_id=req['id'], need_at='2027-01-10T12:00:00+08:00', evidence='assembly schedule')
    row = workflow.client().get(path).json()['requirements'][0]
    assert row['need_at'] == '2027-01-10T12:00:00+08:00'
    assert row['need_at_basis'] == 'manual_requirement'
    assert row['need_time_history_count'] == 1
    workflow.command(p['id'], 'material.need_time', requirement_id=req['id'], need_at=None, evidence='use work order')
    row = workflow.client().get(path).json()['requirements'][0]
    assert row['need_at_basis'] == 'work_order_planned_start_proxy'
    assert row['need_time_history_count'] == 2
    detail = workflow.object(p['id'], 'requirement', req['id'])
    assert len(detail['need_time_events']) == 2


def test_need_time_rejects_naive_time_and_read_only(workflow):
    p, req, _ = workflow.material_requirement()
    workflow.command(p['id'], 'material.need_time', requirement_id=req['id'], need_at='2027-01-10T12:00:00', evidence='schedule', expected_status=422)
    workflow.read_only.add('owner')
    workflow.command(p['id'], 'material.need_time', requirement_id=req['id'], need_at=None, evidence='schedule', expected_status=403)
    assert workflow.object(p['id'], 'requirement', req['id'])['need_time_events'] == []


def test_need_time_replay_and_project_version_conflict(workflow):
    from uuid import uuid4
    p, req, _ = workflow.material_requirement()
    client = workflow.client()
    url = f"{BASE}/projects/{p['id']}/commands"
    version = client.get(f"{BASE}/projects/{p['id']}").json()['version']
    body = dict(action='material.need_time', operation_id=str(uuid4()), expected_version=version, requirement_id=req['id'], need_at=None, evidence='schedule')
    first = client.post(url, json=body)
    assert first.status_code == 200
    replay = client.post(url, json=body).json()
    assert replay['replayed'] and replay['object_id'] == first.json()['object_id']
    body['operation_id'] = str(uuid4())
    assert client.post(url, json=body).status_code == 409
    assert len(workflow.object(p['id'], 'requirement', req['id'])['need_time_events']) == 1


def test_need_time_migrates_v26_and_rejects_superseded_requirement(workflow):
    from uuid import uuid4
    p, req, _ = workflow.material_requirement()
    with sqlite3.connect(workflow.paths.domain) as db:
        db.execute('DROP TABLE material_need_time_events')
        db.execute('UPDATE schema_version SET version=26')
    workflow.reopen()
    assert workflow.client().get(f"{BASE}/projects/{p['id']}").status_code == 200
    with workflow.db() as db:
        assert db.execute('SELECT version FROM schema_version').fetchone()[0] == 27
    # A newer confirmed plan for this work order supersedes the old requirement.
    with sqlite3.connect(workflow.paths.domain) as db:
        db.row_factory = sqlite3.Row
        old = dict(db.execute('SELECT * FROM requirements WHERE id=?', (req['id'],)).fetchone())
        plan = dict(db.execute('SELECT * FROM plans WHERE id=?', (old['plan_id'],)).fetchone())
        plan['id'] = str(uuid4())
        plan['source_external_id'] = str(uuid4())
        plan['accepted_seq'] += 1
        cols = list(plan)
        db.execute(f"INSERT INTO plans ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", [plan[c] for c in cols])
        old.update(id=str(uuid4()), plan_id=plan['id'], supersedes_requirement_id=req['id'])
        cols = list(old)
        db.execute(f"INSERT INTO requirements ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", [old[c] for c in cols])
    workflow.command(p['id'], 'material.need_time', requirement_id=req['id'], need_at=None, evidence='schedule', expected_status=409)


def test_need_time_rejects_inactive_actor(workflow):
    p, req, _ = workflow.material_requirement()
    workflow.inactive.add('owner')
    workflow.command(p['id'], 'material.need_time', requirement_id=req['id'], need_at=None, evidence='schedule', expected_status=403)
