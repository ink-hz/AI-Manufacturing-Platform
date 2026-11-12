"""Verification is local collaboration, never a material accounting event."""
from uuid import uuid4
import pytest
from .conftest import BASE, USERS
from .test_arrivals import fields


def business_snapshot(w):
    tables = ('requirements', 'supply_commitments', 'material_lots', 'supply_receipts',
              'iqc_results', 'material_handoffs', 'reservations', 'exchanges',
              'integration_projections', 'material_consumption')
    with w.db() as tx:
        return {t: [tuple(r) for r in tx.execute(f'SELECT * FROM {t} ORDER BY rowid')] for t in tables}


def observation(w):
    pid = w.create_project(mode='oem')['id']
    w.grant(pid, 'warehouse', ['warehouse'])
    w.grant(pid, 'supply', ['supply'])
    arrival = w.command(pid, 'arrival.record', **fields(w))['object_id']
    return pid, dict(kind='arrival', id=arrival, version=1)


def open_verify(w, pid, ref, **overrides):
    return w.command(pid, 'material_task.open', actor_name='supply', task_kind='verify',
                     reference=ref, assignee_id=str(USERS['warehouse']), note='核实标签与暂存位置', **overrides)['object_id']


@pytest.mark.parametrize('outcome', ['identity_verified', 'unable_to_verify', 'incorrect_observation', 'superseded'])
def test_empty_project_verification_lifecycle_never_changes_business_facts(workflow, outcome):
    w = workflow
    pid, ref = observation(w)
    before = business_snapshot(w)
    task = open_verify(w, pid, ref)
    assert business_snapshot(w) == before
    w.command(pid, 'material_task.close', actor_name='warehouse', task_id=task,
              outcome=outcome, evidence='已核对标签', expected_status=409)
    w.command(pid, 'material_task.accept', actor_name='warehouse', task_id=task)
    w.command(pid, 'material_task.progress', actor_name='warehouse', task_id=task, note='现场反馈')
    page = w.client('warehouse').get(f'{BASE}/projects/{pid}/material-tasks').json()
    assert 'material_task.verify' not in page['items'][0]['next_actions']
    assert business_snapshot(w) == before
    w.command(pid, 'material_task.close', actor_name='warehouse', task_id=task,
              outcome=outcome, evidence='已核对实物标签和当前观察记录')
    assert business_snapshot(w) == before
    w.reopen()
    value = w.object(pid, 'material_task', task)
    assert value['state'] == 'closed' and value['requirement_id'] is None
    assert value['reference']['reference'] == ref and value['reference_current'] is True
    assert value['closure']['outcome'] == outcome
    assert [h['action'] for h in value['history']] == ['open', 'accept', 'progress', 'close']


def test_verify_rejects_quantity_legacy_actions_and_invalid_conclusions(workflow):
    w = workflow
    pid, ref = observation(w)
    task = open_verify(w, pid, ref)
    w.command(pid, 'material_task.accept', actor_name='warehouse', task_id=task)
    before = business_snapshot(w)
    for fields_ in ({'found_quantity':'1'}, {'found_location':'shelf'}):
        w.command(pid, 'material_task.progress', actor_name='warehouse', task_id=task,
                  note='数量不能证明身份', expected_status=422, **fields_)
    w.command(pid, 'material_task.verify', actor_name='warehouse', task_id=task, evidence='核实', expected_status=422)
    for outcome in ('fulfilled', 'discrepancy', 'false_alarm'):
        w.command(pid, 'material_task.close', actor_name='warehouse', task_id=task, outcome=outcome, evidence='旧结论', expected_status=422)
    w.command(pid, 'material_task.close', actor_name='warehouse', task_id=task, outcome='identity_verified', evidence=' ', expected_status=422)
    w.command(pid, 'material_task.close', actor_name='warehouse', task_id=task, outcome='identity_verified', evidence='补签', handoff_ids=[str(uuid4())], expected_status=422)
    w.command(pid, 'material_task.open', actor_name='supply', task_kind='iqc', reference=ref,
              assignee_id=str(USERS['warehouse']), note='不能检验', expected_status=422)
    assert business_snapshot(w) == before


def test_current_arrival_resolution_is_explicit_and_cannot_cross_observations(workflow):
    w = workflow
    from .test_expedites import setup
    pid, rid, c = setup(w, qualified='0')
    req = {'id':rid}
    w.grant(pid, 'warehouse', ['warehouse'])
    w.grant(pid, 'supply', ['supply'])
    arrival = w.command(pid, 'arrival.record', **fields(w))['object_id']
    ref = dict(kind='arrival', id=arrival, version=1)
    task = open_verify(w, pid, ref, requirement_id=req['id'])
    w.command(pid, 'material_task.accept', actor_name='warehouse', task_id=task)
    receipt = w.receive(pid, c['id'], quantity='1', lot_id=c['lot_id'])['object_id']
    unrelated = w.receive(pid, c['id'], quantity='1', lot_id=c['lot_id'])['object_id']
    w.command(pid, 'arrival.match', arrival_id=arrival, receipt_id=receipt, evidence='标签准确匹配')
    before = business_snapshot(w)
    close = dict(actor_name='warehouse', task_id=task, outcome='identity_verified', evidence='重新核对')
    w.command(pid, 'material_task.close', **close, expected_status=409)
    w.command(pid, 'material_task.close', **close, resolved_reference={'kind':'receipt','id':unrelated}, expected_status=422)
    w.command(pid, 'material_task.close', **close, resolved_reference={'kind':'receipt','id':receipt})
    value = w.object(pid, 'material_task', task)
    assert value['reference']['reference'] == ref and value['reference_current'] is False
    assert value['closure']['resolved_reference'] == {'kind':'receipt','id':receipt}
    assert value['context_requirement_ids'] == [req['id']]
    assert business_snapshot(w) == before


def test_reuse_and_replay_keep_initial_evidence_and_responsibility(workflow):
    w = workflow
    pid, ref = observation(w)
    version = w.client('supply').get(f'{BASE}/projects/{pid}').json()['version']
    body = dict(action='material_task.open', operation_id=str(uuid4()), expected_version=version,
                task_kind='verify', reference=ref, assignee_id=str(USERS['warehouse']), note='核对')
    url = f'{BASE}/projects/{pid}/commands'
    first = w.client('supply').post(url, json=body)
    assert first.status_code == 200, first.text
    task = first.json()['object_id']
    assert w.client('supply').post(url, json=body).json()['replayed']
    assert w.client('supply').post(url, json={**body,'operation_id':str(uuid4())}).status_code == 409
    reused = w.command(pid, 'material_task.open', actor_name='supply', task_kind='verify', reference=ref,
                       assignee_id=str(USERS['supply']), note='再次提醒')['object_id']
    assert reused == task
    value = w.object(pid, 'material_task', task)
    assert value['assignee_id'] == str(USERS['warehouse'])
    assert [h['action'] for h in value['history']] == ['open', 'reuse']
    w.inactive.add('warehouse')
    assert w.client('supply').post(url, json=body).status_code == 422
    w.inactive.clear()
    w.read_only.add('supply')
    assert w.client('supply').post(url, json=body).status_code == 403


def test_live_verify_eligibility_and_directory_actions(workflow):
    w = workflow
    pid, ref = observation(w)
    task = open_verify(w, pid, ref)
    w.command(pid, 'material_task.accept', actor_name='warehouse', task_id=task)
    w.command(pid, 'material_task.reassign', actor_name='supply', task_id=task, assignee_id=str(USERS['supply']), reason='轮班')
    w.command(pid, 'material_task.progress', actor_name='warehouse', task_id=task, note='原负责人仍负责')
    w.command(pid, 'material_task.accept', actor_name='supply', task_id=task)
    w.command(pid, 'material_task.close', actor_name='warehouse', task_id=task, outcome='unable_to_verify', evidence='撤责', expected_status=403)
    w.inactive.add('supply')
    summary = w.client('supply').get(f'{BASE}/projects/{pid}/material-tasks').json()['items'][0]
    assert summary['next_actions'] == []
    page = w.client('supply').get(f'{BASE}/projects/{pid}/material-task-references').json()
    assert all(not i['can_open'] for i in page['items'])
    w.command(pid, 'material_task.close', actor_name='supply', task_id=task, outcome='unable_to_verify', evidence='失效', expected_status=403)
    w.inactive.clear()
    w.grant(pid, 'supply', ['engineering'])
    w.command(pid, 'material_task.close', actor_name='supply', task_id=task, outcome='unable_to_verify', evidence='撤权', expected_status=403)


def test_iqc_reference_derives_requirement_reuses_legacy_and_requires_all_inspections(workflow):
    from .test_expedites import setup
    w = workflow
    pid, rid, facts = setup(w, qualified='0')
    receipt = w.receive(pid, facts['id'], quantity='20', lot_id=facts['lot_id'])['object_id']
    task = w.command(pid, 'material_task.open', actor_name='supply', task_kind='iqc',
                     reference={'kind':'receipt','id':receipt}, assignee_id=str(USERS['quality']), note='准确收货检验')['object_id']
    assert w.object(pid, 'material_task', task)['requirement_id'] == rid
    before = business_snapshot(w)
    assert w.command(pid, 'material_task.open', actor_name='supply', task_kind='iqc', requirement_id=rid,
                     receipt_id=receipt, assignee_id=str(USERS['quality']), note='旧入口提醒')['object_id'] == task
    assert business_snapshot(w) == before
    w.command(pid, 'material_task.accept', actor_name='quality', task_id=task)
    w.inspect(pid, receipt, accepted='12', rejected='0')
    w.command(pid, 'material_task.close', actor_name='quality', task_id=task, outcome='fulfilled', evidence='仍有8待检', expected_status=409)
    w.command(pid, 'material_task.close', actor_name='quality', task_id=task, outcome='identity_verified', evidence='错误结论', expected_status=422)
    w.inspect(pid, receipt, accepted='0', rejected='8')
    w.command(pid, 'material_task.close', actor_name='quality', task_id=task, outcome='fulfilled', evidence='本次检验完成')


def test_discovery_requires_available_eligible_directory_assignee_and_admin_verify_membership(workflow):
    w = workflow
    pid = w.create_project(mode='oem')['id']
    ref = dict(kind='arrival', id=w.command(pid,'arrival.record',**fields(w))['object_id'], version=1)
    url = f'{BASE}/projects/{pid}/material-task-references'
    # An implicit configuration administrator is not a verification assignee.
    w.command(pid,'material_task.open',task_kind='verify',reference=ref,
              assignee_id=str(USERS['admin']),note='无项目资格',expected_status=422)
    members = w.client('admin').get(f'{BASE}/projects/{pid}/material-control/assignees',params={'task_kind':'verify'}).json()['items']
    assert str(USERS['admin']) not in [m['id'] for m in members]
    w.inactive.add('owner')
    assert not w.client('admin').get(url).json()['items'][0]['can_open']
    w.grant(pid,'warehouse',['warehouse'])
    assert w.client('admin').get(url).json()['items'][0]['can_open']
    w.inactive.add('warehouse')
    assert not w.client('admin').get(url).json()['items'][0]['can_open']


def test_native_refresh_reuses_scope_explicit_close_and_replacement_does_not_rebind(workflow):
    from uuid import UUID
    from manufacturing_platform.workflow.contracts import Actor
    from .test_expedites import setup
    from .test_native_materials import FakeMes, make_service, bind_command
    w = workflow
    pid, rid, facts = setup(w,qualified='0')
    source = FakeMes()
    service = make_service(w,source)
    owner = Actor(user_id=USERS['owner'],display_name='owner',configuration_admin=True,read_only=False)
    service.execute(owner,UUID(pid),bind_command(service,owner,pid,facts['work_order_id']))
    snapshot = service.mes_materials(owner,UUID(pid),UUID(facts['work_order_id']))
    ref = dict(kind='mes_component',binding_id=snapshot['binding']['id'],snapshot_id=snapshot['snapshot']['id'],component_key='R:1')
    version = w.client('supply').get(f'{BASE}/projects/{pid}').json()['version']
    opened = dict(action='material_task.open',operation_id=str(uuid4()),expected_version=version,task_kind='verify',reference=ref,
                  requirement_id=rid,assignee_id=str(USERS['warehouse']),note='原生观察核实')
    url = f'{BASE}/projects/{pid}/commands'
    response = w.client('supply').post(url,json=opened)
    assert response.status_code == 200,response.text
    task = response.json()['object_id']
    w.command(pid,'material_task.accept',actor_name='warehouse',task_id=task)
    service.execute(owner,UUID(pid),dict(action='mes_order.refresh',operation_id=str(uuid4()),expected_version=service.detail(owner,UUID(pid)).version,
                    work_order_id=facts['work_order_id'],binding_id=ref['binding_id']))
    assert w.client('supply').post(url,json=opened).json()['replayed']
    value = w.object(pid,'material_task',task)
    current = value['current_reference']
    assert current['snapshot_id'] != ref['snapshot_id'] and value['reference']['reference'] == ref
    assert open_verify(w,pid,current) == task
    w.command(pid,'material_task.close',actor_name='warehouse',task_id=task,outcome='identity_verified',evidence='旧快照',expected_status=409)
    receipt = w.receive(pid,facts['id'],quantity='1',lot_id=facts['lot_id'])['object_id']
    w.command(pid,'material_task.close',actor_name='warehouse',task_id=task,outcome='identity_verified',evidence='物料名不能证明收货',resolved_reference={'kind':'receipt','id':receipt},expected_status=422)
    w.command(pid,'material_task.close',actor_name='warehouse',task_id=task,outcome='identity_verified',evidence='当前快照',resolved_reference=current)
    replacement_task = open_verify(w,pid,current)
    w.command(pid,'material_task.accept',actor_name='warehouse',task_id=replacement_task)
    service.execute(owner,UUID(pid),bind_command(service,owner,pid,facts['work_order_id'],shop_order='ORDER-2',replace_binding_id=ref['binding_id'],reason='纠正绑定'))
    replacement = service.mes_materials(owner,UUID(pid),UUID(facts['work_order_id']))
    new_ref = dict(kind='mes_component',binding_id=replacement['binding']['id'],snapshot_id=replacement['snapshot']['id'],component_key='R:1')
    w.command(pid,'material_task.close',actor_name='warehouse',task_id=replacement_task,outcome='identity_verified',evidence='不能跨绑定',resolved_reference=new_ref,expected_status=422)
    w.command(pid,'material_task.close',actor_name='warehouse',task_id=replacement_task,outcome='superseded',evidence='原绑定已经替换')
    assert source.calls == 3


def test_source_receipt_iqc_alias_and_legacy_target_reuse(tmp_path):
    from datetime import timedelta
    from .integrations.support import MockRig, NOW
    rig = MockRig(tmp_path,core=True)
    refs = rig.core_ready()
    rig.workflow.resolve_subject_profiles = lambda ids: [dict(user_id=str(i),display_name='Fixture member') for i in set(ids)]
    rig.grant(['project_owner','quality','supply','warehouse'],['inspection'])
    fact = rig.result_fact(rig.execute('wms',dict(operation='wms.receive',commitment_id=str(refs.commitment),material_lot_id=str(refs.lot),
        lot_id='LOT',material_id='M',owner_id='C',amount=dict(quantity='4',unit='piece',scale=0),location='receiving',custodian='warehouse',
        supplier_batch='B2',expiry=(NOW+timedelta(days=30)).date().isoformat())))
    receipt = rig.target(fact,'receipt')
    def command(**data):
        return rig.workflow.execute(rig.actor,rig.project_id,dict(operation_id=str(uuid4()),expected_version=rig.workflow.detail(rig.actor,rig.project_id).version,**data))
    common = dict(action='material_task.open',task_kind='iqc',assignee_id=str(rig.actor.user_id),note='已有准确收货')
    legacy = command(**common,requirement_id=str(refs.requirement),receipt_id=str(receipt))
    opened = command(**common,reference=dict(kind='source_receipt',source_key=fact.source_key.model_dump(mode='json')))
    direct = command(**common,reference=dict(kind='receipt',id=str(receipt)))
    assert legacy.object_id == opened.object_id == direct.object_id
    with rig.workflow.store.transaction() as tx:
        task = tx.execute('SELECT * FROM material_tasks WHERE id=?',(str(opened.object_id),)).fetchone()
        assert task['receipt_id'] == str(receipt) and task['requirement_id'] == str(refs.requirement)
        assert task['reference_json'] is None  # Initial legacy evidence remains unchanged.

    command(action='material_task.cancel',task_id=str(legacy.object_id),reason='结束旧任务')
    pinned = command(**common,reference=dict(kind='source_receipt',source_key=fact.source_key.model_dump(mode='json')))
    with rig.workflow.store.transaction() as tx:
        import json
        saved = json.loads(tx.execute('SELECT reference_json FROM material_tasks WHERE id=?',(str(pinned.object_id),)).fetchone()[0])
        assert saved['origin'] == 'mock' and saved['environment'] == 'mock'
        assert saved['reference']['kind'] == 'source_receipt'


def test_unmatched_arrival_current_match_and_correction_offer_exact_iqc_without_rewriting_evidence(workflow):
    w = workflow
    from .test_expedites import setup
    pid, _, c = setup(w, qualified='0')
    w.grant(pid, 'warehouse', ['warehouse'])
    w.grant(pid, 'supply', ['supply'])
    w.grant(pid, 'quality', ['quality'], ['inspection'])
    arrival = w.command(pid, 'arrival.record', **fields(w))['object_id']
    ref = dict(kind='arrival', id=arrival, version=1)
    task = open_verify(w, pid, ref)
    w.command(pid, 'material_task.accept', actor_name='warehouse', task_id=task)
    receipts = [w.receive(pid, c['id'], quantity='1', lot_id=c['lot_id'])['object_id'] for _ in range(2)]
    for version, receipt in enumerate(receipts, start=2):
        correction = {'correction_reason': '重新核对标签'} if version == 3 else {}
        w.command(pid, 'arrival.match', arrival_id=arrival, receipt_id=receipt, evidence='当前标签匹配', **correction)
        value = w.object(pid, 'material_task', task)
        assert value['reference']['receipt_id'] is None
        assert value['reference']['reference'] == ref
        assert value['current_reference'] == {**ref, 'version': version}
        current = w.object(pid, 'arrival', arrival)
        assert current['receipt_id'] == receipt == current['matches'][-1]['receipt_id']
        page = w.client('supply').get(f'{BASE}/projects/{pid}/material-task-references',
            params={'task_kind': 'iqc', 'receipt_id': current['receipt_id'], 'limit': 1}).json()
        assert page['total'] == 1
        item = page['items'][0]
        assert item['can_open']
        iqc = w.command(pid, 'material_task.open', actor_name='supply', task_kind='iqc',
            reference=item['reference'], assignee_id=str(USERS['quality']), note='按当前准确收货安排')['object_id']
        assert w.object(pid, 'material_task', iqc)['receipt_id'] == receipt
        reused = w.client('supply').get(f'{BASE}/projects/{pid}/material-task-references',
            params={'task_kind': 'iqc', 'receipt_id': receipt}).json()['items'][0]
        assert reused['existing_task_id'] == iqc and not reused['can_open']
    w.read_only.add('supply')
    w.command(pid, 'material_task.open', actor_name='supply', task_kind='iqc',
        reference=item['reference'], assignee_id=str(USERS['quality']), note='撤权后不能创建', expected_status=403)
