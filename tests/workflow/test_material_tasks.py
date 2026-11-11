"""Material coordination never creates inventory or inspection results."""
from uuid import uuid4

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


def test_trace_direct_close_accepts_compatible_signed_supplement(workflow):
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
    w.command(pid,'material_task.close',actor_name='warehouse',task_id=task,outcome='fulfilled',
              evidence='补交已签收',handoff_ids=[supplement])
    value=w.client('warehouse').get(f'{BASE}/projects/{pid}/objects/material_task/{task}').json()['value']
    assert value['evidence_handoff_ids']==[supplement]
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
        assert tx.execute('SELECT version FROM schema_version').fetchone()[0]==25
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
    w.command(pid,'material_task.close',actor_name='warehouse',task_id=second,outcome='discrepancy',evidence='短少待处理')
    v=w.client('warehouse').get(f'{BASE}/projects/{pid}/objects/material_task/{second}').json()['value']
    assert v['history'][-1]['outcome']=='discrepancy'


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
