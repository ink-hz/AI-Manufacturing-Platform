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
    control = workflow.client().get(f"{BASE}/projects/{p['id']}/material-control").json()['requirements'][0]
    assert any(i['object_kind'] == 'material_lot' and i['object_id'] == supply['lot_id'] and i['code'] == 'verification' for i in control['issues'])


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


def test_shortage_filter_and_counts_cover_all_requirements_before_paging(workflow):
    from uuid import uuid4
    p, req, _ = workflow.material_requirement()
    with sqlite3.connect(workflow.paths.domain) as db:
        db.row_factory = sqlite3.Row
        template = dict(db.execute('SELECT * FROM requirements WHERE id=?', (req['id'],)).fetchone())
        for i in range(51):
            row = dict(template, id=str(uuid4()), lineage_id=str(uuid4()), material_id=f'material-{i}')
            cols = list(row)
            db.execute(f"INSERT INTO requirements ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", [row[c] for c in cols])
    response = workflow.client().get(f"{BASE}/projects/{p['id']}/material-control", params={'problem': 'shortage', 'limit': 1, 'offset': 51}).json()
    assert response['scope_total'] == 52
    assert response['total'] == response['problem_counts']['shortage'] == 52
    assert response['requirements'][0]['confirmed_satisfied'] == '0'
    assert any(issue['code'] == 'shortage' for issue in response['requirements'][0]['issues'])


def test_independent_iqc_and_handoff_issues_show_real_assignees(workflow):
    from .conftest import USERS
    from .test_expedites import setup
    pid, rid, facts = setup(workflow, qualified='0')
    receipt = workflow.receive(pid, facts['id'], quantity='20', lot_id=facts['lot_id'])['object_id']
    workflow.grant(pid, 'warehouse', ['quality', 'warehouse'], ['inspection'])
    task = workflow.command(pid, 'material_task.open', actor_name='supply', requirement_id=rid, task_kind='iqc', receipt_id=receipt, assignee_id=str(USERS['quality']), note='inspect')['object_id']
    workflow.command(pid, 'material_task.accept', actor_name='quality', task_id=task)
    workflow.command(pid, 'material_task.reassign', actor_name='supply', task_id=task, assignee_id=str(USERS['warehouse']), reason='handover')
    hand = workflow.command(pid, 'material_handoff.record', actor_name='warehouse', material_lot_id=facts['lot_id'], work_order_id=facts['work_order_id'], quantity='20', unit='kg', from_location='warehouse', to_location='line', receiver_id=str(USERS['production']))['object_id']
    workflow.command(pid, 'material_handoff.receive', actor_name='production', handoff_id=hand, received_quantity='18', received_location='line', note='short')
    row = workflow.client('supply').get(f'{BASE}/projects/{pid}/material-control').json()['requirements'][0]
    iqc = next(i for i in row['issues'] if i['code'] == 'pending_iqc')
    assert iqc['task_id'] == task and iqc['assignee_id'] == str(USERS['quality'])
    assert iqc['assignee_name'] == 'Quality Engineer' and iqc['proposed_assignee_name'] == 'Warehouse'
    assert any(i['code'] == 'unreceived' and i['object_id'] == hand and i['quantity'] == '2' for i in row['issues'])


def test_linked_signed_supplement_clears_short_handoff_issue(workflow):
    from .conftest import USERS
    from .test_expedites import setup
    pid, rid, facts = setup(workflow)
    def sign(sent, received):
        ident = workflow.command(pid, 'material_handoff.record', actor_name='warehouse', material_lot_id=facts['lot_id'], work_order_id=facts['work_order_id'], quantity=sent, unit='kg', from_location='warehouse', to_location='line', receiver_id=str(USERS['production']))['object_id']
        workflow.command(pid, 'material_handoff.receive', actor_name='production', handoff_id=ident, received_quantity=received, received_location='line', note='count')
        return ident
    original, extra = sign('20', '18'), sign('2', '2')
    task = workflow.command(pid, 'material_task.open', actor_name='supply', requirement_id=rid, task_kind='trace', handoff_id=original, assignee_id=str(USERS['warehouse']), note='trace')['object_id']
    workflow.command(pid, 'material_task.accept', actor_name='warehouse', task_id=task)
    workflow.command(pid, 'material_task.close', actor_name='warehouse', task_id=task, outcome='fulfilled', evidence='signed', handoff_ids=[extra])
    row = workflow.client('supply').get(f'{BASE}/projects/{pid}/material-control').json()['requirements'][0]
    assert not any(i['code'] == 'unreceived' and i['object_id'] == original for i in row['issues'])


def test_shared_lot_does_not_become_unambiguous_when_search_filters_one_requirement(workflow):
    from uuid import uuid4
    from .conftest import USERS
    from .test_expedites import setup
    pid, rid, facts = setup(workflow)
    with sqlite3.connect(workflow.paths.domain) as db:
        db.row_factory = sqlite3.Row
        def clone(table, ident, **updates):
            row = dict(db.execute(f'SELECT * FROM {table} WHERE id=?', (ident,)).fetchone())
            row.update(updates); cols = list(row)
            db.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", [row[c] for c in cols])
        second, commitment, receipt = str(uuid4()), str(uuid4()), str(uuid4())
        clone('requirements', rid, id=second, lineage_id=str(uuid4()), material_id='steel-1')
        clone('supply_commitments', facts['id'], id=commitment, requirement_id=second)
        orig = db.execute('SELECT id FROM supply_receipts WHERE commitment_id=? LIMIT 1', (facts['id'],)).fetchone()[0]
        clone('supply_receipts', orig, id=receipt, commitment_id=commitment, source_external_id=str(uuid4()))
    hand = workflow.command(pid, 'material_handoff.record', actor_name='warehouse', material_lot_id=facts['lot_id'], work_order_id=facts['work_order_id'], quantity='20', unit='kg', from_location='warehouse', to_location='line', receiver_id=str(USERS['production']))['object_id']
    page = workflow.client('supply').get(f'{BASE}/projects/{pid}/material-control', params={'requirement_id': rid}).json()
    issues = page['requirements'][0]['issues']
    assert any(i['code'] == 'verification' and i['object_id'] == hand for i in issues)
    assert not any(i['code'] == 'unreceived' and i['object_id'] == hand for i in issues)


def test_missing_confirmed_need_time_is_verification_until_override(workflow):
    p, req, _ = workflow.material_requirement()
    path = f"{BASE}/projects/{p['id']}/material-control"
    row = workflow.client().get(path, params={'problem': 'verification'}).json()['requirements'][0]
    assert any(i['code'] == 'verification' and i['next_action'] == 'confirm_time' for i in row['issues'])
    workflow.command(p['id'], 'material.need_time', requirement_id=req['id'], need_at='2027-01-10T12:00:00+08:00', evidence='schedule')
    page = workflow.client().get(path, params={'problem': 'verification'}).json()
    assert page['total'] == 0


def test_external_reservation_without_local_quality_is_unknown_not_zero(workflow):
    p, req, supply, result = reserve(workflow)
    stock(workflow, p, supply)
    act(workflow, p, result)
    assert workflow.balance(p['id'], req['id'])['shortage'] == '20'
    row = workflow.client().get(f"{BASE}/projects/{p['id']}/material-control").json()['requirements'][0]
    assert row['reserved'] == '80' and row['shortage'] == '20'
    assert row['confirmed_satisfied'] is None
    assert any(i['code'] == 'verification' and '合格' in i['title'] for i in row['issues'])


def test_current_quality_correction_makes_reservation_coverage_unknown(workflow):
    p, req, supply, result = reserve(workflow)
    receipt = workflow.receive(p['id'], supply['id'], quantity='100', lot_id=supply['lot_id'])['object_id']
    workflow.inspect(p['id'], receipt, accepted='100', rejected='0')
    stock(workflow, p, supply)
    act(workflow, p, result)
    path = f"{BASE}/projects/{p['id']}/material-control"
    assert workflow.client().get(path).json()['requirements'][0]['confirmed_satisfied'] == '80'
    with sqlite3.connect(workflow.paths.domain) as db:
        iqc = db.execute('SELECT id FROM iqc_results WHERE receipt_id=?', (receipt,)).fetchone()[0]
        db.execute('INSERT INTO source_corrections(project_id,receipt_id,iqc_id,accepted_delta,rejected_delta,exchange_id,evidence) VALUES (?,?,?,?,?,?,?)', (p['id'], receipt, iqc, -30000, 30000, result['exchange_id'], 'corrected inspection'))
    row = workflow.client().get(path).json()['requirements'][0]
    assert row['qualified'] == '70' and row['reserved'] == '80'
    assert row['confirmed_satisfied'] is None
    assert any(i['code'] == 'verification' and '合格' in i['title'] for i in row['issues'])


def test_shared_lineage_reservation_is_not_credited_twice(workflow):
    from uuid import uuid4
    p, req, supply, result = reserve(workflow)
    receipt = workflow.receive(p['id'], supply['id'], quantity='100', lot_id=supply['lot_id'])['object_id']
    workflow.inspect(p['id'], receipt, accepted='100', rejected='0')
    stock(workflow, p, supply); act(workflow, p, result)
    with sqlite3.connect(workflow.paths.domain) as db:
        db.row_factory = sqlite3.Row
        row = dict(db.execute('SELECT * FROM requirements WHERE id=?', (req['id'],)).fetchone())
        row['id'] = str(uuid4()); cols = list(row)
        db.execute(f"INSERT INTO requirements ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", [row[c] for c in cols])
    page = workflow.client().get(f"{BASE}/projects/{p['id']}/material-control", params={'requirement_id': req['id']}).json()
    row = page['requirements'][0]
    assert row['confirmed_satisfied'] is None
    assert any(i['code'] == 'verification' and i['next_action'] == 'check_allocation' for i in row['issues'])


def test_balance_isolates_commitments_and_inspections_by_work_order(workflow):
    from uuid import uuid4
    p, req, related = workflow.material_requirement(qualified='80')
    with sqlite3.connect(workflow.paths.domain) as db:
        db.row_factory = sqlite3.Row
        def clone(table, ident, **updates):
            row = dict(db.execute(f'SELECT * FROM {table} WHERE id=?', (ident,)).fetchone()); row.update(updates)
            cols = list(row); db.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", [row[c] for c in cols])
        new_wo, second = str(uuid4()), str(uuid4())
        clone('work_orders', related['work_order_id'], id=new_wo, source_external_id=str(uuid4()))
        clone('requirements', req['id'], id=second, work_order_id=new_wo)
    balance = workflow.balance(p['id'], second)
    assert balance['received'] == balance['qualified'] == balance['in_transit'] == '0'
    page = workflow.client().get(f"{BASE}/projects/{p['id']}/objects/requirement").json()
    summary = next(x for x in page['items'] if x['id'] == second)['material_balance']
    assert summary['received'] == summary['qualified'] == summary['in_transit'] == '0'


def test_balance_does_not_mix_incompatible_lineage_metadata(workflow):
    from uuid import uuid4
    p, req, related = workflow.material_requirement(qualified='80')
    with sqlite3.connect(workflow.paths.domain) as db:
        db.row_factory = sqlite3.Row
        row = dict(db.execute('SELECT * FROM requirements WHERE id=?', (req['id'],)).fetchone())
        row.update(id=str(uuid4()), material_id='other material'); cols = list(row)
        db.execute(f"INSERT INTO requirements ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", [row[c] for c in cols])
    balance = workflow.balance(p['id'], row['id'])
    assert balance['received'] == balance['qualified'] == balance['in_transit'] == '0'
    page = workflow.client().get(f"{BASE}/projects/{p['id']}/objects/requirement").json()
    summary = next(x for x in page['items'] if x['id'] == row['id'])['material_balance']
    assert summary['received'] == summary['qualified'] == summary['in_transit'] == '0'


def test_trace_task_follows_same_lineage_after_replan(workflow):
    from uuid import uuid4
    from .conftest import USERS
    from .test_expedites import setup
    pid, rid, facts = setup(workflow)
    hand = workflow.command(pid, 'material_handoff.record', actor_name='warehouse', material_lot_id=facts['lot_id'], work_order_id=facts['work_order_id'], quantity='20', unit='kg', from_location='warehouse', to_location='line', receiver_id=str(USERS['production']))['object_id']
    workflow.command(pid, 'material_task.open', actor_name='supply', requirement_id=rid, task_kind='trace', handoff_id=hand, assignee_id=str(USERS['warehouse']), note='trace')
    with sqlite3.connect(workflow.paths.domain) as db:
        db.row_factory = sqlite3.Row
        old = dict(db.execute('SELECT * FROM requirements WHERE id=?', (rid,)).fetchone())
        plan = dict(db.execute('SELECT * FROM plans WHERE id=?', (old['plan_id'],)).fetchone())
        plan.update(id=str(uuid4()), source_external_id=str(uuid4()), accepted_seq=plan['accepted_seq'] + 1)
        cols = list(plan)
        db.execute(f"INSERT INTO plans ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", [plan[c] for c in cols])
        old.update(id=str(uuid4()), plan_id=plan['id'], supersedes_requirement_id=rid)
        cols = list(old)
        db.execute(f"INSERT INTO requirements ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", [old[c] for c in cols])
    row = workflow.client('supply').get(f'{BASE}/projects/{pid}/material-control').json()['requirements'][0]
    assert row['id'] == old['id']
    assert any(i['code'] == 'unreceived' and i['object_id'] == hand for i in row['issues'])


def test_past_need_time_is_advisory_without_urgent_classification(workflow):
    p, req, _ = workflow.material_requirement()
    path = f"{BASE}/projects/{p['id']}/material-control"
    workflow.command(p['id'], 'material.need_time', requirement_id=req['id'], need_at='2000-01-01T00:00:00+08:00', evidence='schedule')
    page = workflow.client().get(path).json()
    row = page['requirements'][0]
    assert row['timing_risk'] == 'need_time_passed'
    assert row['need_at_basis'] == 'manual_requirement'
    assert page['problem_counts']['urgent'] == 0
    workflow.command(p['id'], 'material.need_time', requirement_id=req['id'], need_at='2099-01-01T00:00:00+08:00', evidence='updated schedule')
    assert workflow.client().get(path).json()['requirements'][0]['timing_risk'] == 'unknown'
    workflow.command(p['id'], 'material.need_time', requirement_id=req['id'], need_at=None, evidence='reset')
    row = workflow.client().get(path).json()['requirements'][0]
    assert row['need_at_basis'] == 'work_order_planned_start_proxy'
    assert row['timing_risk'] == 'unknown'


def test_open_expedite_follows_compatible_api_replan_in_urgent_page(workflow):
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4
    from .test_expedites import setup, open_case
    pid, rid, facts = setup(workflow)
    case = open_case(workflow, pid, rid)['object_id']
    now = datetime.now(UTC)
    source = workflow.source(str(uuid4()), object_type='plan')
    source.update(occurred_at=(now - timedelta(seconds=2)).isoformat(),
                  collected_at=(now - timedelta(seconds=1)).isoformat(),
                  cutoff=(now - timedelta(seconds=2)).isoformat())
    plan = workflow.command(pid, 'plan.receive', actor_name='planner', source=source,
        input_revision_ids=[facts['revision_id']],
        input_order_versions=[{'order_line_id': facts['order_id'], 'version': 1}],
        requirements=[dict(work_order_id=facts['work_order_id'], execution_scope='trial',
                           material_id='steel-1', owner_id='Customer 1', quantity='100', unit='kg')])
    current = workflow.object(pid, 'plan', plan['object_id'])['requirement_ids'][0]
    page = workflow.client('supply').get(f'{BASE}/projects/{pid}/material-control', params={'problem': 'urgent'}).json()
    assert page['total'] == page['problem_counts']['urgent'] == 1
    row = page['requirements'][0]
    assert row['id'] == current and case in row['expedite_ids']
    assert any(i['code'] == 'urgent' and i['object_id'] == case for i in row['issues'])
    assert any(x['id'] == case for x in page['expedites'])
    historical = workflow.client('supply').get(f'{BASE}/projects/{pid}/material-control', params={'requirement_id': rid}).json()
    assert case in historical['requirements'][0]['expedite_ids']
    # An incompatible requirement and an ambiguous duplicate cannot inherit the case,
    # even when the request filters all other requirements out.
    with sqlite3.connect(workflow.paths.domain) as db:
        db.row_factory = sqlite3.Row
        template = dict(db.execute('SELECT * FROM requirements WHERE id=?', (current,)).fetchone())
        def clone(**updates):
            row = dict(template, id=str(uuid4()), **updates)
            cols = list(row)
            db.execute(f"INSERT INTO requirements ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", [row[c] for c in cols])
            return row['id']
        incompatible = clone(material_id='other material')
        duplicate = clone()
    for other in (incompatible, duplicate, current):
        filtered = workflow.client('supply').get(f'{BASE}/projects/{pid}/material-control', params={'requirement_id': other, 'problem': 'urgent'}).json()
        assert filtered['total'] == 0


def test_explicit_trace_on_authority_stock_without_local_receipt(workflow):
    from .conftest import USERS
    p, req, facts = workflow.material_requirement(mode='oem', qualified='0')
    reservation = workflow.command(p['id'], 'reservation.request', actor_name='planner', work_order_id=facts['work_order_id'], requirement_id=req['id'], lot_id=facts['lot_id'], quantity='80', unit='kg')
    workflow.grant(p['id'], 'warehouse', ['warehouse'])
    workflow.grant(p['id'], 'production', ['production'])
    stock(workflow, p, facts)
    act(workflow, p, reservation)
    hand = workflow.command(p['id'], 'material_handoff.record', actor_name='warehouse', material_lot_id=facts['lot_id'], work_order_id=facts['work_order_id'], quantity='20', unit='kg', from_location='warehouse', to_location='line', receiver_id=str(USERS['production']))['object_id']
    task = workflow.command(p['id'], 'material_task.open', actor_name='supply', requirement_id=req['id'], task_kind='trace', handoff_id=hand, assignee_id=str(USERS['warehouse']), note='trace')['object_id']
    page = workflow.client('supply').get(f"{BASE}/projects/{p['id']}/material-control", params={'problem': 'unreceived'}).json()
    assert page['total'] == page['problem_counts']['unreceived'] == 1
    row = page['requirements'][0]
    assert hand in row['handoff_ids'] and any(x['id'] == hand for x in page['handoffs'])
    assert any(i['code'] == 'unreceived' and i['object_id'] == hand and i['task_id'] == task and i['quantity'] == '20' for i in row['issues'])
    signed = workflow.command(p['id'], 'material_handoff.record', actor_name='warehouse', material_lot_id=facts['lot_id'], work_order_id=facts['work_order_id'], quantity='20', unit='kg', from_location='warehouse', to_location='line', receiver_id=str(USERS['production']))['object_id']
    workflow.command(p['id'], 'material_handoff.receive', actor_name='production', handoff_id=signed, received_quantity='18', received_location='line', note='short', receipt_use='line_side', requirement_id=req['id'])
    unscoped = workflow.command(p['id'], 'material_handoff.record', actor_name='warehouse', material_lot_id=facts['lot_id'], work_order_id=facts['work_order_id'], quantity='5', unit='kg', from_location='warehouse', to_location='line', receiver_id=str(USERS['production']))['object_id']
    page = workflow.client('supply').get(f"{BASE}/projects/{p['id']}/material-control").json()
    row = page['requirements'][0]
    assert signed in row['handoff_ids'] and any(x['id'] == signed for x in page['handoffs'])
    assert any(i['code'] == 'unreceived' and i['object_id'] == signed and i['quantity'] == '2' for i in row['issues'])
    assert unscoped not in row['handoff_ids'] and not any(i['object_id'] == unscoped for i in row['issues'])
