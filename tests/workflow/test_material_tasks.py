"""Material coordination never creates inventory or inspection results."""

from manufacturing_platform.workflow.schema import SCHEMA_VERSION
from uuid import uuid4
import pytest

from .conftest import BASE, USERS
from .test_expedites import setup, accounting


def test_iqc_closes_directly_after_all_received_units_inspected_including_rejects(workflow):
    w = workflow
    pid, rid, facts = setup(w, qualified="0")
    receipt = w.receive(pid, facts["id"], quantity="20", lot_id=facts["lot_id"])["object_id"]
    w.inspect(pid, receipt, accepted="12", rejected="8")
    before = accounting(w)
    task = w.command(pid, "material_task.open", actor_name="supply", requirement_id=rid,
                     task_kind="iqc", receipt_id=receipt, handoff_id=None,
                     assignee_id=str(USERS["quality"]), note="核对待检批次")["object_id"]
    w.command(pid, "material_task.accept", actor_name="quality", task_id=task)
    w.command(pid, "material_task.close", actor_name="quality", task_id=task,
              outcome="fulfilled", evidence="检验结果已登记")
    detail = w.client("quality").get(f"{BASE}/projects/{pid}/objects/material_task/{task}")
    assert detail.status_code == 200
    assert detail.json()["value"]["state"] == "closed"
    assert accounting(w) == before
    w.reopen()
    assert w.client("quality").get(f"{BASE}/projects/{pid}/objects/material_task/{task}").json()["value"]["state"] == "closed"


def test_trace_found_quantity_is_not_signed_receipt(workflow):
    w = workflow
    pid, rid, facts = setup(w)
    handoff = w.command(pid, "material_handoff.record", actor_name="warehouse", material_lot_id=facts["lot_id"],
                        work_order_id=facts["work_order_id"], quantity="20", unit="kg", from_location="仓库",
                        to_location="产线", receiver_id=str(USERS["production"]))["object_id"]
    w.command(pid, "material_handoff.receive", actor_name="production", handoff_id=handoff,
              received_quantity="18", received_location="产线", note="短少2")
    task = w.command(pid, "material_task.open", actor_name="supply", requirement_id=rid,
                     task_kind="trace", receipt_id=None, handoff_id=handoff,
                     assignee_id=str(USERS["warehouse"]), note="查找短少物料")["object_id"]
    w.command(pid, "material_task.accept", actor_name="warehouse", task_id=task)
    w.command(pid, "material_task.progress", actor_name="warehouse", task_id=task, note="发现2件",
              found_quantity="2", found_location="仓库")
    w.command(pid, "material_task.close", actor_name="warehouse", task_id=task,
              outcome="fulfilled", evidence="发现物料", expected_status=409)


@pytest.mark.parametrize("outcome", ["fulfilled", "discrepancy", "false_alarm", "superseded"])
def test_trace_direct_close_accepts_compatible_signed_supplement(workflow,outcome):
    w = workflow
    pid, rid, facts = setup(w)
    def handoff(q, actual):
        ident = w.command(pid, 'material_handoff.record', actor_name='warehouse', material_lot_id=facts['lot_id'],
                          work_order_id=facts['work_order_id'], quantity=q, unit='kg', from_location='仓库',
                          to_location='产线', receiver_id=str(USERS['production']))['object_id']
        w.command(pid,'material_handoff.receive',actor_name='production',handoff_id=ident,
                  received_quantity=actual,received_location='产线',note='实收核对')
        return ident
    original, supplement = handoff('20','18'), handoff('2','2')
    before=accounting(w)
    task=w.command(pid,'material_task.open',actor_name='supply',requirement_id=rid,task_kind='trace',
                   handoff_id=original,assignee_id=str(USERS['warehouse']),note='跟进短少')['object_id']
    w.command(pid,'material_task.accept',actor_name='warehouse',task_id=task)
    w.command(pid,'material_task.close',actor_name='warehouse',task_id=task,outcome=outcome,
              evidence='补交已签收',handoff_ids=[supplement])
    value=w.client('warehouse').get(f'{BASE}/projects/{pid}/objects/material_task/{task}').json()['value']
    assert value['evidence_handoff_ids']==[supplement]
    assert value['history'][-1]['outcome']==outcome
    assert accounting(w)==before


def test_reassignment_retains_responsibility_until_new_assignee_accepts(workflow):
    w=workflow
    pid,rid,facts=setup(w,qualified='0')
    receipt=w.receive(pid,facts['id'],quantity='20',lot_id=facts['lot_id'])['object_id']
    w.grant(pid,'warehouse',['quality'],['inspection'])
    task=w.command(pid,'material_task.open',actor_name='supply',requirement_id=rid,task_kind='iqc',
                   receipt_id=receipt,assignee_id=str(USERS['quality']),note='待检')['object_id']
    w.command(pid,'material_task.accept',actor_name='quality',task_id=task)
    w.command(pid,'material_task.reassign',actor_name='supply',task_id=task,assignee_id=str(USERS['warehouse']),reason='调整责任人')
    v=w.client('supply').get(f'{BASE}/projects/{pid}/objects/material_task/{task}').json()['value']
    assert v['assignee_id']==str(USERS['quality']) and v['proposed_assignee_id']==str(USERS['warehouse'])
    page=w.client('warehouse').get(f'{BASE}/projects/{pid}/material-tasks').json()
    summary=next(item for item in page['items'] if item['id']==task)
    assert summary['assignee_id']==str(USERS['quality']) and summary['proposed_assignee_id']==str(USERS['warehouse'])
    own_tasks=w.client('warehouse').get(f'{BASE}/tasks',params={'project_id':pid}).json()['items']
    own=next(item['target'] for item in own_tasks if item['target']['id']==task)
    assert own['assignee_id']==str(USERS['quality']) and own['proposed_assignee_id']==str(USERS['warehouse'])
    assert 'material_task.accept' in own['next_actions'] and 'material_task.progress' not in own['next_actions']
    w.command(pid,'material_task.accept',actor_name='quality',task_id=task,expected_status=403)
    w.command(pid,'material_task.accept',actor_name='warehouse',task_id=task)
    v=w.client('supply').get(f'{BASE}/projects/{pid}/objects/material_task/{task}').json()['value']
    assert v['assignee_id']==str(USERS['warehouse']) and v['proposed_assignee_id'] is None
    assert [h['action'] for h in v['history']]==['open','accept','reassign','accept']


def test_live_eligibility_replay_cas_and_duplicate_scope(workflow):
    w=workflow
    pid,rid,facts=setup(w,qualified='0')
    receipt=w.receive(pid,facts['id'],quantity='20',lot_id=facts['lot_id'])['object_id']
    version=w.client('supply').get(f'{BASE}/projects/{pid}').json()['version']
    body=dict(action='material_task.open',operation_id=str(uuid4()),expected_version=version,
              requirement_id=rid,task_kind='iqc',receipt_id=receipt,
              assignee_id=str(USERS['quality']),note='待检')
    url=f'{BASE}/projects/{pid}/commands'
    first=w.client('supply').post(url,json=body)
    assert first.status_code==200
    replay=w.client('supply').post(url,json=body)
    assert replay.status_code==200 and replay.json()['replayed']
    stale={**body,'operation_id':str(uuid4())}
    assert w.client('supply').post(url,json=stale).status_code==409
    w.command(pid,'material_task.open',actor_name='supply',requirement_id=rid,task_kind='iqc',receipt_id=receipt,
              assignee_id=str(USERS['quality']),note='重复',expected_status=409)
    w.inactive.add('quality')
    assert w.client('supply').post(url,json=body).status_code==422
    w.inactive.clear()
    w.grant(pid,'quality',['quality'],[])
    assert w.client('supply').post(url,json=body).status_code==422
    task=first.json()['object_id']
    w.command(pid,'material_task.accept',actor_name='quality',task_id=task,expected_status=403)


def test_scoped_routes_and_schema24_migration(workflow):
    w=workflow
    pid,rid,facts=setup(w,qualified='0')
    receipt=w.receive(pid,facts['id'],quantity='2',lot_id=facts['lot_id'])['object_id']
    import sqlite3
    with sqlite3.connect(w.paths.domain) as tx:
        tx.execute('DROP TABLE material_task_evidence')
        tx.execute('DROP TABLE material_task_history')
        tx.execute('DROP TABLE material_tasks')
        tx.execute('UPDATE schema_version SET version=24')
    w.reopen()
    assert w.client('supply').get(f'{BASE}/projects/{pid}').status_code == 200
    with w.db() as tx:
        assert tx.execute('SELECT version FROM schema_version').fetchone()[0]==SCHEMA_VERSION
    task=w.command(pid,'material_task.open',actor_name='supply',requirement_id=rid,task_kind='iqc',receipt_id=receipt,
                   assignee_id=str(USERS['quality']),note='待检')['object_id']
    page=w.client('quality').get(f'{BASE}/projects/{pid}/material-tasks').json()
    assert page['total']==1 and page['items'][0]['id']==task
    assert w.client('quality').get(f'{BASE}/material-control/tasks',params={'project_id':pid}).json()['total']==1
    assignees=w.client('supply').get(f'{BASE}/projects/{pid}/material-control/assignees',params={'task_kind':'iqc'}).json()['items']
    assert str(USERS['quality']) in [x['id'] for x in assignees]
    assert w.client('outsider').get(f'{BASE}/projects/{pid}/material-tasks').status_code==404
    assert w.client('quality').get(f'{BASE}/projects/{pid}/material-control').json()['material_task_counts']=={'pending':1}
    assert any(t['target']['id']==task for t in w.client('quality').get(f'{BASE}/tasks',params={'project_id':pid}).json()['items'])


def test_trace_rejects_unrelated_and_previously_allocated_evidence(workflow):
    w=workflow
    pid,rid,facts=setup(w)
    def hand(q, actual, *, receiver='production', wo=None):
        ident=w.command(pid,'material_handoff.record',actor_name='warehouse',material_lot_id=facts['lot_id'],
                        work_order_id=facts['work_order_id'] if wo is None else wo,quantity=q,unit='kg',
                        from_location='仓库',to_location='产线',receiver_id=str(USERS[receiver]))['object_id']
        w.command(pid,'material_handoff.receive',actor_name=receiver,handoff_id=ident,
                  received_quantity=actual,received_location='产线',note='核对')
        return ident
    original1=hand('20','18')
    original2=hand('20','18')
    supplement=hand('2','2')
    wrong=hand('2','2',receiver='supply')
    def task(original):
        ident=w.command(pid,'material_task.open',actor_name='supply',requirement_id=rid,task_kind='trace',
                        handoff_id=original,assignee_id=str(USERS['warehouse']),note='追踪')['object_id']
        w.command(pid,'material_task.accept',actor_name='warehouse',task_id=ident)
        return ident
    first, second=task(original1),task(original2)
    w.command(pid,'material_task.close',actor_name='warehouse',task_id=first,outcome='fulfilled',evidence='补交',
              handoff_ids=[wrong],expected_status=422)
    w.command(pid,'material_task.close',actor_name='warehouse',task_id=first,outcome='fulfilled',evidence='补交',
              handoff_ids=[supplement])
    w.command(pid,'material_task.close',actor_name='warehouse',task_id=second,outcome='fulfilled',evidence='重复',
              handoff_ids=[supplement],expected_status=422)
    w.command(pid,'material_task.close',actor_name='warehouse',task_id=second,outcome='discrepancy',evidence='短少待处理',expected_status=409)
    v=w.client('warehouse').get(f'{BASE}/projects/{pid}/objects/material_task/{second}').json()['value']
    assert v['state']=='processing' and v['history'][-1]['action']=='accept'


def test_verify_is_not_stale_authority_to_close(workflow):
    import sqlite3
    w=workflow
    pid,rid,facts=setup(w,qualified='0')
    receipt=w.receive(pid,facts['id'],quantity='20',lot_id=facts['lot_id'])['object_id']
    w.inspect(pid,receipt,accepted='12',rejected='8')
    task=w.command(pid,'material_task.open',actor_name='supply',requirement_id=rid,task_kind='iqc',receipt_id=receipt,
                   assignee_id=str(USERS['quality']),note='待检')['object_id']
    w.command(pid,'material_task.accept',actor_name='quality',task_id=task)
    w.command(pid,'material_task.verify',actor_name='quality',task_id=task,evidence='检验完成',handoff_ids=[])
    # Emulate a subsequently corrected effective result to prove close re-reads facts.
    with sqlite3.connect(w.paths.domain) as tx:
        tx.execute('UPDATE iqc_results SET rejected_atoms=0 WHERE receipt_id=?',(receipt,))
    w.command(pid,'material_task.close',actor_name='quality',task_id=task,outcome='fulfilled',evidence='完成',expected_status=409)


def test_accept_replay_rechecks_current_designation(workflow):
    w=workflow
    pid,rid,facts=setup(w,qualified='0')
    receipt=w.receive(pid,facts['id'],quantity='2',lot_id=facts['lot_id'])['object_id']
    w.grant(pid,'warehouse',['quality'],['inspection'])
    task=w.command(pid,'material_task.open',actor_name='supply',requirement_id=rid,task_kind='iqc',receipt_id=receipt,
                   assignee_id=str(USERS['quality']),note='待检')['object_id']
    version=w.client('quality').get(f'{BASE}/projects/{pid}').json()['version']
    body=dict(action='material_task.accept',operation_id=str(uuid4()),expected_version=version,task_id=task)
    url=f'{BASE}/projects/{pid}/commands'
    assert w.client('quality').post(url,json=body).status_code==200
    w.command(pid,'material_task.reassign',actor_name='supply',task_id=task,assignee_id=str(USERS['warehouse']),reason='轮班')
    w.command(pid,'material_task.accept',actor_name='warehouse',task_id=task)
    assert w.client('quality').post(url,json=body).status_code==403


def test_cross_project_and_invalid_assignee_are_rejected(workflow):
    w=workflow
    pid,rid,facts=setup(w,qualified='0')
    other,_,other_facts=setup(w,qualified='0')
    other_receipt=w.receive(other,other_facts['id'],quantity='2',lot_id=other_facts['lot_id'])['object_id']
    w.command(pid,'material_task.open',actor_name='supply',requirement_id=rid,task_kind='iqc',receipt_id=other_receipt,
              assignee_id=str(USERS['quality']),note='跨项目',expected_status=404)
    receipt=w.receive(pid,facts['id'],quantity='2',lot_id=facts['lot_id'])['object_id']
    w.command(pid,'material_task.open',actor_name='supply',requirement_id=rid,task_kind='iqc',receipt_id=receipt,
              assignee_id=str(USERS['warehouse']),note='资质不符',expected_status=422)
    w.command(pid,'material_task.open',actor_name='production',requirement_id=rid,task_kind='iqc',receipt_id=receipt,
              assignee_id=str(USERS['quality']),note='越权',expected_status=403)


def test_iqc_all_close_outcomes_require_inspected_scope(workflow):
    w = workflow
    pid, rid, facts = setup(w, qualified='0')
    receipt = w.receive(pid, facts['id'], quantity='20', lot_id=facts['lot_id'])['object_id']
    task = w.command(pid, 'material_task.open', actor_name='supply', requirement_id=rid,
                     task_kind='iqc', receipt_id=receipt, assignee_id=str(USERS['quality']), note='待检')['object_id']
    w.command(pid, 'material_task.accept', actor_name='quality', task_id=task)
    for outcome in ('fulfilled', 'discrepancy', 'false_alarm', 'superseded'):
        w.command(pid, 'material_task.close', actor_name='quality', task_id=task,
                  outcome=outcome, evidence='处理结果', expected_status=409)
    w.inspect(pid, receipt, accepted='12', rejected='8')
    w.command(pid, 'material_task.close', actor_name='quality', task_id=task,
              outcome='discrepancy', evidence='检验完成，另行处理不合格')


def test_progress_deadline_preserves_aware_time_and_rejects_naive(workflow):
    w=workflow
    pid,rid,facts=setup(w,qualified='0')
    receipt=w.receive(pid,facts['id'],quantity='2',lot_id=facts['lot_id'])['object_id']
    task=w.command(pid,'material_task.open',actor_name='supply',requirement_id=rid,task_kind='iqc',receipt_id=receipt,
                   assignee_id=str(USERS['quality']),note='待检')['object_id']
    w.command(pid,'material_task.accept',actor_name='quality',task_id=task)
    w.command(pid,'material_task.progress',actor_name='quality',task_id=task,note='预计下午',
              expected_completion='2026-12-01T14:00:00+08:00')
    w.command(pid,'material_task.progress',actor_name='quality',task_id=task,note='未确定',expected_completion=None)
    w.command(pid,'material_task.progress',actor_name='quality',task_id=task,note='没有时区',
              expected_completion='2026-12-01T14:00:00',expected_status=422)
    v=w.client('quality').get(f'{BASE}/projects/{pid}/objects/material_task/{task}').json()['value']
    assert v['history'][-2]['expected_completion']=='2026-12-01T14:00:00+08:00'
    assert v['history'][-1]['expected_completion'] is None


def test_task_page_summary_does_not_load_history_or_evidence(workflow, monkeypatch):
    from contextlib import contextmanager
    from manufacturing_platform.workflow.store import WorkflowStore
    w=workflow
    pid,rid,facts=setup(w,qualified='0')
    receipt=w.receive(pid,facts['id'],quantity='2',lot_id=facts['lot_id'])['object_id']
    task=w.command(pid,'material_task.open',actor_name='supply',requirement_id=rid,task_kind='iqc',receipt_id=receipt,
                   assignee_id=str(USERS['quality']),note='待检')['object_id']
    w.command(pid,'material_task.accept',actor_name='quality',task_id=task)
    for i in range(3):
        w.command(pid,'material_task.progress',actor_name='quality',task_id=task,note=f'记录{i}')
    statements=[]
    original=WorkflowStore.transaction
    @contextmanager
    def traced(store, **kwargs):
        with original(store, **kwargs) as tx:
            tx.set_trace_callback(statements.append)
            yield tx
    monkeypatch.setattr(WorkflowStore,'transaction',traced)
    page=w.client('quality').get(f'{BASE}/projects/{pid}/material-tasks',params={'limit':1,'offset':0})
    assert page.status_code==200 and page.json()['items'][0]['version']==5
    assert page.json()['items'][0]['assignee_id']==str(USERS['quality'])
    assert page.json()['items'][0]['proposed_assignee_id'] is None
    assert not any('SELECT payload_json FROM material_task_history' in q for q in statements)
    assert not any('SELECT handoff_id FROM material_task_evidence' in q for q in statements)
    assert any('COUNT(*) FROM material_task_history' in q for q in statements)


@pytest.mark.parametrize('mismatch', ['lot', 'work_order', 'unit', 'project'])
def test_trace_supplement_rejects_incompatible_signed_handoff(workflow, mismatch):
    w = workflow
    pid, rid, facts = setup(w)
    def signed(project, lot, work_order, unit, quantity, received):
        ident = w.command(project, 'material_handoff.record', actor_name='warehouse',
                          material_lot_id=lot, work_order_id=work_order, quantity=quantity,
                          unit=unit, from_location='仓库', to_location='产线',
                          receiver_id=str(USERS['production']))['object_id']
        w.command(project, 'material_handoff.receive', actor_name='production', handoff_id=ident,
                  received_quantity=received, received_location='产线', note='签收核对')
        return ident
    original = signed(pid, facts['lot_id'], facts['work_order_id'], 'kg', '20', '18')
    lot, work_order, unit, project = facts['lot_id'], facts['work_order_id'], 'kg', pid
    if mismatch in ('lot', 'unit'):
        unit = 'piece' if mismatch == 'unit' else 'kg'
        lot = w.command(pid, 'material.define', actor_name='supply', material_id='other-material' if mismatch == 'unit' else 'steel-1',
                        lot_id='alternate-lot', owner_id='Customer 1', unit=unit,
                        scale=0 if unit == 'piece' else 3, expiry='2030-01-01',
                        source=w.source(str(uuid4()), object_type='material_lot'))['object_id']
    elif mismatch == 'work_order':
        demand = w.command(pid, 'demand.record', kind='firm', product='Camera', quantity='1',
                           unit='piece', due_date='2026-12-01', source=w.source(str(uuid4())))['object_id']
        for dimension in ('technical', 'material', 'capacity', 'commercial', 'quality'):
            w.command(pid, 'demand.review', demand_id=demand, dimension=dimension,
                      decision='approved', evidence='已评审')
        order = w.command(pid, 'order.register', demand_id=demand,
                          source=w.source(str(uuid4()), object_type='order_line'), quantity='1',
                          unit='piece', due_date='2026-12-01')['object_id']
        work_order = w.command(pid, 'work_order.register', actor_name='planner', order_line_id=order,
                               revision_id=facts['revision_id'], source=w.source(str(uuid4()), object_type='work_order'),
                               quantity='1', unit='piece', purpose='trial', trial_quantity='1',
                               planned_start='2026-12-01T00:00:00Z', planned_end='2026-12-02T00:00:00Z')['object_id']
    elif mismatch == 'project':
        project, _, other = setup(w)
        lot, work_order = other['lot_id'], other['work_order_id']
    supplement = signed(project, lot, work_order, unit, '2', '2')
    task = w.command(pid, 'material_task.open', actor_name='supply', requirement_id=rid, task_kind='trace',
                     handoff_id=original, assignee_id=str(USERS['warehouse']), note='查料')['object_id']
    w.command(pid, 'material_task.accept', actor_name='warehouse', task_id=task)
    w.command(pid, 'material_task.close', actor_name='warehouse', task_id=task, outcome='fulfilled',
              evidence='核对补交', handoff_ids=[supplement], expected_status=404 if mismatch == 'project' else 422)
    value = w.client('warehouse').get(f'{BASE}/projects/{pid}/objects/material_task/{task}').json()['value']
    assert value['state'] == 'processing' and value['evidence_handoff_ids'] == []


def test_legacy_date_only_progress_history_remains_readable(workflow):
    import sqlite3
    w=workflow
    pid,rid,facts=setup(w,qualified='0')
    receipt=w.receive(pid,facts['id'],quantity='2',lot_id=facts['lot_id'])['object_id']
    task=w.command(pid,'material_task.open',actor_name='supply',requirement_id=rid,task_kind='iqc',receipt_id=receipt,
                   assignee_id=str(USERS['quality']),note='待检')['object_id']
    w.command(pid,'material_task.accept',actor_name='quality',task_id=task)
    w.command(pid,'material_task.progress',actor_name='quality',task_id=task,note='旧日期')
    with sqlite3.connect(w.paths.domain) as tx:
        tx.execute("UPDATE material_task_history SET payload_json=json_set(payload_json,'$.expected_completion','2026-12-01') WHERE task_id=? AND json_extract(payload_json,'$.action')='progress'", (task,))
    response=w.client('quality').get(f'{BASE}/projects/{pid}/objects/material_task/{task}')
    assert response.status_code==200
    assert response.json()['value']['history'][-1]['expected_completion']=='2026-12-01'


def test_iqc_task_accepts_replanned_requirement_and_prior_lineage_receipt(workflow):
    from datetime import UTC, datetime, timedelta

    w = workflow
    pid, old_id, facts = setup(w, qualified='0')
    receipt = w.receive(pid, facts['id'], quantity='20', lot_id=facts['lot_id'])['object_id']
    old = w.object(pid, 'requirement', old_id)
    plan = w.object(pid, 'plan', old['plan_id'])
    now = datetime.now(UTC)
    source = w.source(plan['source']['external_id'], object_type='plan', version=2)
    source.update(occurred_at=(now-timedelta(minutes=2)).isoformat(), collected_at=(now-timedelta(minutes=1)).isoformat(), cutoff=(now-timedelta(minutes=2)).isoformat())
    revised = w.command(pid, 'plan.receive', actor_name='planner', source=source,
        input_revision_ids=[facts['revision_id']], input_order_versions=[{'order_line_id': facts['order_id'], 'version': 1}],
        requirements=[{'work_order_id': facts['work_order_id'], 'execution_scope': 'trial', 'material_id': 'steel-1', 'owner_id': 'Customer 1', 'quantity': '50', 'unit': 'kg'}])
    new_id = w.object(pid, 'plan', revised['object_id'])['requirement_ids'][0]
    assert w.object(pid, 'requirement', new_id)['lineage_id'] == old['lineage_id']
    page = w.client('supply').get(f'{BASE}/projects/{pid}/material-control').json()
    assert page['requirements'][0]['id'] == new_id and receipt in page['requirements'][0]['receipt_ids']
    before = accounting(w)
    task = w.command(pid, 'material_task.open', actor_name='supply', requirement_id=new_id,
        task_kind='iqc', receipt_id=receipt, assignee_id=str(USERS['quality']), note='Inspect prior receipt')['object_id']
    value = w.client('quality').get(f'{BASE}/projects/{pid}/objects/material_task/{task}').json()['value']
    assert value['requirement_id'] == new_id and value['receipt_id'] == receipt
    assert accounting(w) == before
    w.command(pid, 'material_task.accept', actor_name='quality', task_id=task)
    w.inspect(pid, receipt, accepted='20', rejected='0')
    w.command(pid, 'material_task.close', actor_name='quality', task_id=task, outcome='fulfilled', evidence='Inspected')


def test_iqc_receipt_requires_matching_lineage_and_scope(workflow):
    import sqlite3

    w = workflow
    pid, rid, facts = setup(w, qualified='0')
    receipt = w.receive(pid, facts['id'], quantity='2', lot_id=facts['lot_id'])['object_id']
    with sqlite3.connect(w.paths.domain) as db:
        db.row_factory = sqlite3.Row
        original = dict(db.execute('SELECT * FROM requirements WHERE id=?', (rid,)).fetchone())
        variants = []
        for field, value in [('lineage_id', str(uuid4())), ('work_order_id', str(uuid4())), ('material_id', 'other'), ('owner_id', 'other'), ('unit', 'other')]:
            row = {**original, 'id': str(uuid4()), field: value}
            columns = list(row)
            db.execute(f"INSERT INTO requirements ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", [row[c] for c in columns])
            variants.append(row['id'])
    for other_id in variants:
        w.command(pid, 'material_task.open', actor_name='supply', requirement_id=other_id, task_kind='iqc',
                  receipt_id=receipt, assignee_id=str(USERS['quality']), note='Wrong scope', expected_status=422)


def test_iqc_receipt_rejects_incompatible_actual_lot_or_receipt_unit(workflow):
    import sqlite3

    w = workflow
    pid, rid, facts = setup(w, qualified='0')
    receipt = w.receive(pid, facts['id'], quantity='2', lot_id=facts['lot_id'])['object_id']
    # Simulate inconsistent persisted facts; normal receipt commands enforce these fields.
    for table, ident, field in [('material_lots', facts['lot_id'], 'material_id'),
                                 ('material_lots', facts['lot_id'], 'owner_id'),
                                 ('material_lots', facts['lot_id'], 'unit'),
                                 ('supply_receipts', receipt, 'unit')]:
        with sqlite3.connect(w.paths.domain) as db:
            old = db.execute(f'SELECT {field} FROM {table} WHERE id=?', (ident,)).fetchone()[0]
            db.execute(f'UPDATE {table} SET {field}=? WHERE id=?', ('other', ident))
        w.command(pid, 'material_task.open', actor_name='supply', requirement_id=rid, task_kind='iqc',
                  receipt_id=receipt, assignee_id=str(USERS['quality']), note='Wrong batch', expected_status=422)
        with sqlite3.connect(w.paths.domain) as db:
            db.execute(f'UPDATE {table} SET {field}=? WHERE id=?', (old, ident))

@pytest.mark.parametrize('outcome', ['discrepancy', 'false_alarm', 'superseded'])
def test_trace_close_requires_signed_completion_for_every_outcome(workflow, outcome):
    w=workflow
    pid,rid,facts=setup(w)
    handoff=w.command(pid,'material_handoff.record',actor_name='warehouse',material_lot_id=facts['lot_id'],
        work_order_id=facts['work_order_id'],quantity='20',unit='kg',from_location='仓库',to_location='产线',
        receiver_id=str(USERS['production']))['object_id']
    w.command(pid,'material_handoff.receive',actor_name='production',handoff_id=handoff,received_quantity='18',
        received_location='产线',note='短收')
    w.command(pid,'material_handoff.resolve',actor_name='warehouse',handoff_id=handoff,resolution='短少待处理')
    task=w.command(pid,'material_task.open',actor_name='supply',requirement_id=rid,task_kind='trace',handoff_id=handoff,
        assignee_id=str(USERS['warehouse']),note='追踪')['object_id']
    w.command(pid,'material_task.accept',actor_name='warehouse',task_id=task)
    w.command(pid,'material_task.progress',actor_name='warehouse',task_id=task,note='找到两件',found_quantity='2',found_location='仓库')
    partial=w.command(pid,'material_handoff.record',actor_name='warehouse',material_lot_id=facts['lot_id'],
        work_order_id=facts['work_order_id'],quantity='1',unit='kg',from_location='仓库',to_location='产线',
        receiver_id=str(USERS['production']))['object_id']
    w.command(pid,'material_handoff.receive',actor_name='production',handoff_id=partial,received_quantity='1',
        received_location='产线',note='部分签收')
    detail_url=f'{BASE}/projects/{pid}/objects/material_task/{task}'
    project_url=f'{BASE}/projects/{pid}/material-control'
    before=w.client('warehouse').get(detail_url).json()['value']
    counts=w.client('warehouse').get(project_url).json()['material_task_counts']
    balance=accounting(w)
    w.command(pid,'material_task.close',actor_name='warehouse',task_id=task,outcome=outcome,evidence='文本说明',handoff_ids=[partial],expected_status=409)
    assert w.client('warehouse').get(detail_url).json()['value']==before
    assert w.client('warehouse').get(project_url).json()['material_task_counts']==counts
    assert any(item['target']['id']==task for item in w.client('warehouse').get(f'{BASE}/tasks',params={'project_id':pid}).json()['items'])
    assert accounting(w)==balance

@pytest.mark.parametrize('outcome', ['discrepancy', 'false_alarm', 'superseded'])
@pytest.mark.parametrize('receipt_kind', ['unsigned', 'wrong_location'])
def test_trace_close_rejects_unsigned_or_wrong_destination(workflow, outcome, receipt_kind):
    w=workflow
    pid,rid,facts=setup(w)
    handoff=w.command(pid,'material_handoff.record',actor_name='warehouse',material_lot_id=facts['lot_id'],
        work_order_id=facts['work_order_id'],quantity='20',unit='kg',from_location='仓库',to_location='产线',
        receiver_id=str(USERS['production']))['object_id']
    if receipt_kind=='wrong_location':
        w.command(pid,'material_handoff.receive',actor_name='production',handoff_id=handoff,
            received_quantity='20',received_location='暂存',note='位置不符')
        w.command(pid,'material_handoff.resolve',actor_name='warehouse',handoff_id=handoff,resolution='待核对')
    task=w.command(pid,'material_task.open',actor_name='supply',requirement_id=rid,task_kind='trace',handoff_id=handoff,
        assignee_id=str(USERS['warehouse']),note='核对交料')['object_id']
    w.command(pid,'material_task.accept',actor_name='warehouse',task_id=task)
    before=w.client('warehouse').get(f'{BASE}/projects/{pid}/objects/material_task/{task}').json()['value']
    w.command(pid,'material_task.close',actor_name='warehouse',task_id=task,outcome=outcome,evidence='待处理',expected_status=409)
    assert w.client('warehouse').get(f'{BASE}/projects/{pid}/objects/material_task/{task}').json()['value']==before
