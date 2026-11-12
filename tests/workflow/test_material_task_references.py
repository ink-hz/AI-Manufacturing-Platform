from .conftest import BASE
from .test_arrivals import fields, stock


def test_arrival_reference_requires_no_requirement_or_receipt(workflow):
    p = workflow.create_project(mode='oem')
    arrival = workflow.command(p['id'], 'arrival.record', **fields(workflow))['object_id']
    before = stock(workflow)
    response = workflow.client().get(f"{BASE}/projects/{p['id']}/material-task-references", params={'task_kind': 'verify', 'kind': 'arrival'})
    assert response.status_code == 200
    item = response.json()['items'][0]
    assert item['reference'] == {'kind': 'arrival', 'id': arrival, 'version': 1}
    assert item['evidence']['receipt_id'] is None
    assert stock(workflow) == before


def test_persisted_mes_reference_is_scoped_current_and_never_collects(workflow):
    from uuid import UUID, uuid4
    import pytest
    from manufacturing_platform.workflow.contracts import Actor, DomainError
    from manufacturing_platform.workflow.material_task_reference_models import MesComponentTaskReference, TaskReferenceEvidence
    from manufacturing_platform.workflow.material_task_references import resolve_reference, reference_status
    from .conftest import USERS
    from .test_native_materials import FakeMes, make_service, bind_command
    p, _, related = workflow.material_requirement()
    other = workflow.create_project(mode='oem')
    source = FakeMes()
    service = make_service(workflow, source)
    actor = Actor(user_id=USERS['owner'], display_name='owner', read_only=False, configuration_admin=True)
    pid, wid = UUID(p['id']), UUID(related['work_order_id'])
    service.execute(actor, pid, bind_command(service, actor, p['id'], str(wid)))
    snapshot = service.mes_materials(actor, pid, wid)
    ref = MesComponentTaskReference(kind='mes_component', binding_id=snapshot['binding']['id'], snapshot_id=snapshot['snapshot']['id'], component_key='R:1')
    with service.store.transaction() as tx:
        result = resolve_reference(tx, pid, ref)
        assert result.work_order_id == wid and result.material_id == 'M' and result.environment == 'test'
        with pytest.raises(DomainError): resolve_reference(tx, UUID(other['id']), ref)
        with pytest.raises(DomainError): resolve_reference(tx, pid, ref.model_copy(update={'snapshot_id': uuid4()}))
    assert source.calls == 1
    evidence = TaskReferenceEvidence.model_validate(result.model_dump(exclude={'requirement_id','task_kinds'}))
    refresh = {'action':'mes_order.refresh', 'operation_id':str(uuid4()), 'expected_version':service.detail(actor, pid).version,
               'work_order_id':str(wid), 'binding_id':str(ref.binding_id)}
    service.execute(actor, pid, refresh)
    with service.store.transaction() as tx:
        with pytest.raises(DomainError): resolve_reference(tx, pid, ref)
        current, new_ref, issue = reference_status(tx, pid, evidence)
        assert not current and issue and new_ref.snapshot_id != ref.snapshot_id
        assert resolve_reference(tx, pid, new_ref).scope_key == result.scope_key
        assert evidence.reference.snapshot_id == ref.snapshot_id
    assert source.calls == 2


def test_pagination_filters_before_count_and_has_no_mutation(workflow):
    p = workflow.create_project(mode='oem')
    for i in range(52):
        workflow.command(p['id'], 'arrival.record', **{**fields(workflow), 'arrival_number': f'item-{i:02d}'})
    url = f"{BASE}/projects/{p['id']}/material-task-references"
    with workflow.db() as tx:
        before = list(tx.iterdump())
    response = workflow.client().get(url, params={'kind':'arrival', 'limit': 10, 'offset': 50})
    assert response.status_code == 200
    assert response.json()['total'] == 52 and len(response.json()['items']) == 2
    filtered = workflow.client().get(url, params={'kind':'arrival', 'search':'item-5', 'limit': 1})
    assert filtered.json()['total'] == 2 and len(filtered.json()['items']) == 1
    with workflow.db() as tx:
        assert list(tx.iterdump()) == before


def test_accepted_mock_source_receipt_resolves_exact_project_and_hash(tmp_path):
    from datetime import timedelta
    from uuid import uuid4
    import pytest
    from manufacturing_platform.workflow.contracts import DomainError
    from manufacturing_platform.workflow.material_task_reference_models import ReceiptTaskReference, SourceReceiptTaskReference
    from manufacturing_platform.workflow.material_task_references import resolve_reference, reference_page
    from .integrations.support import MockRig, NOW
    rig = MockRig(tmp_path, core=True)
    refs = rig.core_ready()
    fact = rig.result_fact(rig.execute('wms', dict(operation='wms.receive', commitment_id=str(refs.commitment),
        material_lot_id=str(refs.lot), lot_id='LOT', material_id='M', owner_id='C',
        amount=dict(quantity='4',unit='piece',scale=0), location='receiving', custodian='warehouse',
        supplier_batch='B2', expiry=(NOW + timedelta(days=30)).date().isoformat())))
    receipt = rig.target(fact, 'receipt')
    ref = SourceReceiptTaskReference(kind='source_receipt', source_key=fact.source_key)
    with rig.workflow.store.transaction() as tx:
        source = resolve_reference(tx, rig.project_id, ref)
        direct = resolve_reference(tx, rig.project_id, ReceiptTaskReference(kind='receipt', id=receipt))
        assert source.receipt_id == receipt and source.requirement_id == refs.requirement
        assert source.scope_key == direct.scope_key and source.origin == 'mock' and source.environment == 'mock'
        with pytest.raises(DomainError): resolve_reference(tx, rig.other_project_id, ref)
        with pytest.raises(DomainError): resolve_reference(tx, rig.project_id, ref.model_copy(update={'source_key': fact.source_key.model_copy(update={'external_id': str(uuid4())})}))
    page = reference_page(rig.workflow, rig.actor, rig.project_id, task_kind='iqc', kind='all')
    selected = [item for item in page['items'] if item['evidence']['receipt_id'] == str(receipt)]
    assert len(selected) == 1 and selected[0]['reference']['kind'] == 'source_receipt'
    with rig.workflow.store.transaction(write=True) as tx:
        tx.execute('UPDATE integration_projections SET payload_hash=? WHERE project_id=? AND system=? AND object_type=? AND external_id=? AND version=?', ('0'*64, str(rig.project_id), fact.source_key.system, fact.source_key.object_type, fact.source_key.external_id, fact.source_key.version))
    with rig.workflow.store.transaction() as tx:
        with pytest.raises(DomainError): resolve_reference(tx, rig.project_id, ref)


def test_historical_task_reader_does_not_invent_pinned_reference(workflow):
    from .test_expedites import setup
    from .conftest import USERS
    pid, rid, facts = setup(workflow, qualified='0')
    receipt = workflow.receive(pid, facts['id'], quantity='1', lot_id=facts['lot_id'])['object_id']
    task = workflow.command(pid, 'material_task.open', actor_name='supply', requirement_id=rid, task_kind='iqc',
        receipt_id=receipt, assignee_id=str(USERS['quality']), note='inspection')['object_id']
    value = workflow.object(pid, 'material_task', task)
    assert value['reference'] is None and value['reference_pinned'] is False
    assert value['reference_current'] is None and value['current_reference'] is None
    assert value['context_requirement_ids'] == [rid]


def test_arrival_version_detects_corrected_match_without_mutating_pinned_evidence(workflow):
    import pytest
    from uuid import UUID
    from manufacturing_platform.workflow.contracts import DomainError
    from manufacturing_platform.workflow.material_task_reference_models import ArrivalTaskReference, TaskReferenceEvidence
    from manufacturing_platform.workflow.material_task_references import resolve_reference, reference_status
    p, _, commitment = workflow.material_requirement(qualified='0')
    arrival = workflow.command(p['id'], 'arrival.record', **fields(workflow))['object_id']
    receipt = workflow.receive(p['id'], commitment['id'], quantity='1', lot_id=commitment['lot_id'])['object_id']
    ref = ArrivalTaskReference(kind='arrival', id=arrival, version=1)
    with workflow.db() as tx:
        evidence = TaskReferenceEvidence.model_validate(resolve_reference(tx, UUID(p['id']), ref).model_dump(exclude={'requirement_id','task_kinds'}))
    workflow.command(p['id'], 'arrival.match', arrival_id=arrival, receipt_id=receipt, evidence='actual label')
    with workflow.db() as tx:
        with pytest.raises(DomainError): resolve_reference(tx, UUID(p['id']), ref)
        current, updated, issue = reference_status(tx, UUID(p['id']), evidence)
        assert current is False and updated.version == 2 and issue
        assert evidence.receipt_id is None
        assert resolve_reference(tx, UUID(p['id']), ref, require_current=False).receipt_id is None
        with pytest.raises(DomainError): resolve_reference(tx, UUID(p['id']), ref.model_copy(update={'version': 99}), require_current=False)


def test_page_filters_are_project_scoped_and_authorized(workflow):
    p, _, related = workflow.material_requirement()
    other, other_req, other_related = workflow.material_requirement()
    workflow.command(p['id'], 'arrival.record', **fields(workflow))
    url = f"{BASE}/projects/{p['id']}/material-task-references"
    assert workflow.client('outsider').get(url).status_code == 404
    assert workflow.client().get(url, params={'work_order_id': other_related['work_order_id']}).status_code == 404
    assert workflow.client().get(url, params={'requirement_id': other_req['id']}).status_code == 404
    page = workflow.client().get(url, params={'work_order_id': related['work_order_id'], 'kind':'arrival'}).json()
    assert page['total'] == 1 and page['items'][0]['evidence']['work_order_id'] is None


def test_typed_reference_cannot_be_mixed_with_legacy_target():
    from uuid import uuid4
    import pytest
    from pydantic import ValidationError
    from manufacturing_platform.workflow.material_task_models import OpenMaterialTask
    with pytest.raises(ValidationError):
        OpenMaterialTask(action='material_task.open', operation_id=uuid4(), expected_version=1,
            task_kind='iqc', assignee_id=uuid4(), note='inspect', receipt_id=uuid4(),
            reference={'kind':'receipt', 'id':str(uuid4())})


def test_verification_conclusion_is_structurally_valid_for_kind_dispatch():
    from uuid import uuid4
    from manufacturing_platform.workflow.material_task_models import CloseMaterialTask
    command = CloseMaterialTask(action='material_task.close', operation_id=uuid4(), expected_version=1,
        task_id=uuid4(), outcome='identity_verified', evidence='checked')
    assert command.outcome == 'identity_verified'


def test_verify_requirement_context_keeps_arrival_and_scopes_native_components(workflow):
    from uuid import UUID
    from manufacturing_platform.workflow.contracts import Actor
    from .conftest import USERS
    from .test_native_materials import FakeMes, make_service, bind_command
    p, req, related = workflow.material_requirement()
    other, other_req, other_related = workflow.material_requirement()
    arrival = workflow.command(p['id'], 'arrival.record', **fields(workflow))['object_id']
    service = make_service(workflow, FakeMes())
    actor = Actor(user_id=USERS['owner'], display_name='owner', read_only=False, configuration_admin=True)
    service.execute(actor, UUID(p['id']), bind_command(service, actor, p['id'], related['work_order_id']))
    service.mes_materials(actor, UUID(p['id']), UUID(related['work_order_id']))
    from manufacturing_platform.workflow.material_task_references import reference_page
    page = reference_page(service, actor, UUID(p['id']), requirement_id=UUID(req['id']))
    assert {i['reference']['kind'] for i in page['items']} >= {'arrival', 'mes_component'}
    observation = next(i for i in page['items'] if i['reference']['kind'] == 'arrival')
    assert observation['reference']['id'] == arrival and observation['evidence']['work_order_id'] is None
    assert all(i['evidence']['work_order_id'] == related['work_order_id'] for i in page['items'] if i['reference']['kind'] == 'mes_component')
    # A component belonging to another order must not leak into this context.
    import sqlite3
    with sqlite3.connect(workflow.paths.domain) as tx:
        tx.execute('UPDATE mes_order_bindings SET work_order_id=? WHERE project_id=?', (other_related['work_order_id'], p['id']))
    filtered = reference_page(service, actor, UUID(p['id']), requirement_id=UUID(req['id']))
    assert all(i['reference']['kind'] != 'mes_component' for i in filtered['items'])
    assert any(i['reference']['kind'] == 'arrival' for i in filtered['items'])
    import pytest
    from manufacturing_platform.workflow.contracts import DomainError
    with pytest.raises(DomainError):
        reference_page(service, actor, UUID(p['id']), requirement_id=UUID(other_req['id']))


def test_iqc_discovery_rejects_receipt_with_mismatched_scale(workflow):
    import sqlite3
    p, req, related = workflow.material_requirement(qualified='0')
    receipt = workflow.receive(p['id'], related['id'], quantity='1', lot_id=related['lot_id'])['object_id']
    url = f"{BASE}/projects/{p['id']}/material-task-references"
    params = {'task_kind': 'iqc', 'kind': 'receipt', 'requirement_id': req['id']}
    assert any(i['reference']['id'] == receipt for i in workflow.client().get(url, params=params).json()['items'])
    with sqlite3.connect(workflow.paths.domain) as tx:
        tx.execute('UPDATE material_lots SET scale=scale+1 WHERE id=?', (related['lot_id'],))
    assert all(i['reference']['id'] != receipt for i in workflow.client().get(url, params=params).json()['items'])
