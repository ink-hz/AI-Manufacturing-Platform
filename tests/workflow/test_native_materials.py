from uuid import UUID, uuid4

from manufacturing_platform.workflow.contracts import Actor
from manufacturing_platform.workflow.service import WorkflowService
from manufacturing_platform.workflow.store import WorkflowStore
from .conftest import USERS


class FakeMes:
    def __init__(self):
        self.calls = 0
    def collect_order_materials(self, order, actor):
        self.calls += 1
        return {'namespace': 'namespace', 'fingerprint': 'fingerprint', 'environment': 'test', 'site_code': '1000',
                'request_ids': ['request'], 'total': 1, 'components': [{'component_key': 'R:1', 'material_id': 'M',
                'required_quantity': '1.00000000000000001', 'withdrawn_quantity': '0', 'unit': 'EA', 'storage_location': None}]}
    def order_materials_configuration(self):
        return {'namespace': 'namespace', 'fingerprint': 'fingerprint'}
    def configuration_matches(self, fingerprint):
        return fingerprint == 'fingerprint'


def test_bind_replay_and_stored_read_without_source_io(workflow):
    p, _, related = workflow.material_requirement()
    source = FakeMes()
    store = WorkflowStore(str(workflow.paths.domain), str(workflow.paths.authority), {'id':'workflow-test', 'mode':'test', 'label':'Workflow test'})
    service = WorkflowService(store, lambda uid: True, mes_access_service=source)
    actor = Actor(user_id=USERS['owner'], display_name='owner', read_only=False, configuration_admin=True)
    work_order_id = UUID(related['work_order_id'])
    version = service.detail(actor, UUID(p['id'])).version
    command = {'action':'mes_order.bind', 'operation_id':str(uuid4()), 'expected_version':version,
               'work_order_id':str(work_order_id), 'shop_order':'ORDER-1', 'replace_binding_id':None, 'reason':None}
    result = service.execute(actor, UUID(p['id']), command)
    assert result.object_type == 'work_order'
    assert service.execute(actor, UUID(p['id']), command).replayed
    page = service.mes_materials(actor, UUID(p['id']), work_order_id)
    assert page['binding']['shop_order'] == 'ORDER-1'
    assert page['snapshot']['components'][0]['required_quantity'] == '1.00000000000000001'
    assert source.calls == 1


def make_service(workflow, source, resolver=lambda uid: True):
    store = WorkflowStore(str(workflow.paths.domain), str(workflow.paths.authority), {'id':'workflow-test', 'mode':'test', 'label':'Workflow test'})
    return WorkflowService(store, resolver, mes_access_service=source)


def bind_command(service, actor, project, work_order, **kwargs):
    return {'action':'mes_order.bind', 'operation_id':str(uuid4()), 'expected_version':service.detail(actor, UUID(project)).version,
            'work_order_id':work_order, 'shop_order':'ORDER-1', 'replace_binding_id':None, 'reason':None, **kwargs}


def test_permissions_replay_conflict_and_configuration_guard(workflow):
    import pytest
    from manufacturing_platform.workflow.contracts import DomainError
    p, _, related = workflow.material_requirement()
    source = FakeMes()
    service = make_service(workflow, source)
    owner = Actor(user_id=USERS['owner'], display_name='owner', read_only=False, configuration_admin=True)
    no_admin = Actor(user_id=USERS['owner'], display_name='owner', read_only=False, configuration_admin=False)
    admin_no_grant = Actor(user_id=USERS['admin'], display_name='admin', read_only=False, configuration_admin=True)
    command = bind_command(service, owner, p['id'], related['work_order_id'])
    for actor in (no_admin, admin_no_grant, owner.model_copy(update={'read_only': True})):
        with pytest.raises(DomainError): service.execute(actor, UUID(p['id']), command)
    inactive = make_service(workflow, source, lambda uid: False)
    with pytest.raises(DomainError): inactive.execute(owner, UUID(p['id']), command)
    assert source.calls == 0
    source.configuration_matches = lambda fingerprint: False
    with pytest.raises(DomainError) as exc: service.execute(owner, UUID(p['id']), command)
    assert exc.value.code == 'MES_CONFIGURATION_CHANGED'
    assert service.mes_materials(owner, UUID(p['id']), UUID(related['work_order_id']))['binding'] is None
    source.configuration_matches = lambda fingerprint: True
    service.execute(owner, UUID(p['id']), command)
    with pytest.raises(DomainError) as exc: service.execute(owner, UUID(p['id']), {**command, 'shop_order':'OTHER'})
    assert exc.value.code == 'IDEMPOTENCY_CONFLICT'
    assert source.calls == 2


def test_refresh_replacement_and_restart_preserve_history(workflow):
    import pytest
    from manufacturing_platform.workflow.contracts import DomainError
    p, _, related = workflow.material_requirement()
    source = FakeMes(); service = make_service(workflow, source)
    actor = Actor(user_id=USERS['owner'], display_name='owner', read_only=False, configuration_admin=True)
    pid, wid = UUID(p['id']), UUID(related['work_order_id'])
    service.execute(actor, pid, bind_command(service, actor, p['id'], str(wid)))
    original = service.mes_materials(actor, pid, wid)
    command = bind_command(service, actor, p['id'], str(wid), shop_order='ORDER-2')
    with pytest.raises(DomainError): service.execute(actor, pid, command)
    assert source.calls == 1
    command.update(replace_binding_id=original['binding']['id'], reason='Correction')
    service.execute(actor, pid, command)
    replacement = make_service(workflow, source).mes_materials(actor, pid, wid)
    assert replacement['binding']['shop_order'] == 'ORDER-2'
    refresh = {'action':'mes_order.refresh', 'operation_id':str(uuid4()), 'expected_version':service.detail(actor, pid).version, 'work_order_id':str(wid), 'binding_id':replacement['binding']['id']}
    source.configuration_matches = lambda fingerprint: False
    with pytest.raises(DomainError): service.execute(actor, pid, refresh)
    assert service.mes_materials(actor, pid, wid) == replacement
    with workflow.db() as db:
        rows = db.execute('SELECT active,superseded_by,reason FROM mes_order_bindings ORDER BY rowid').fetchall()
        assert tuple(rows[0]) == (0, replacement['binding']['id'], 'Correction')
        assert rows[1][0] == 1


def test_version_and_permission_races_fail_after_collection(workflow):
    import pytest
    import sqlite3
    from manufacturing_platform.workflow.contracts import DomainError
    p, _, related = workflow.material_requirement()
    source = FakeMes(); service = make_service(workflow, source)
    actor = Actor(user_id=USERS['owner'], display_name='owner', read_only=False, configuration_admin=True)
    pid = UUID(p['id']); wid = UUID(related['work_order_id'])
    original = source.collect_order_materials
    def change_version(*args):
        data = original(*args)
        with sqlite3.connect(workflow.paths.domain) as db: db.execute('UPDATE projects SET version=version+1 WHERE id=?', (str(pid),))
        return data
    source.collect_order_materials = change_version
    with pytest.raises(DomainError) as exc: service.execute(actor, pid, bind_command(service, actor, str(pid), str(wid)))
    assert exc.value.code == 'VERSION_CONFLICT'
    assert service.mes_materials(actor, pid, wid)['binding'] is None
    def revoke(*args):
        data = original(*args)
        with sqlite3.connect(workflow.paths.domain) as db: db.execute('UPDATE project_grants SET active=0 WHERE project_id=? AND user_id=?', (str(pid), str(actor.user_id)))
        return data
    source.collect_order_materials = revoke
    with pytest.raises(DomainError) as exc: service.execute(actor, pid, bind_command(service, actor, str(pid), str(wid)))
    assert exc.value.code == 'FORBIDDEN'
    assert service.mes_materials(actor, pid, wid)['binding'] is None


def test_migration_from_25_keeps_data_and_installs_tables(workflow):
    import sqlite3
    p, _, related = workflow.material_requirement()
    with sqlite3.connect(workflow.paths.domain) as db:
        db.execute('DROP TABLE mes_material_components')
        db.execute('DROP TABLE mes_material_snapshots')
        db.execute('DROP TABLE mes_order_bindings')
        db.execute('UPDATE schema_version SET version=25')
    actor = Actor(user_id=USERS['owner'], display_name='owner', read_only=False, configuration_admin=True)
    source = FakeMes()
    original = source.collect_order_materials
    def collect(*args):
        result = original(*args)
        result['components'][0]['withdrawn_quantity'] = None
        return result
    source.collect_order_materials = collect
    service = make_service(workflow, source)
    assert service.mes_materials(actor, UUID(p['id']), UUID(related['work_order_id']))['binding'] is None
    service.execute(actor, UUID(p['id']), bind_command(service, actor, p['id'], related['work_order_id']))
    assert make_service(workflow, source).mes_materials(actor, UUID(p['id']), UUID(related['work_order_id']))['snapshot']['components'][0]['withdrawn_quantity'] is None
    with workflow.db() as db:
        assert db.execute('SELECT version FROM schema_version').fetchone()[0] == 27
        columns = {row[1]: row for row in db.execute('PRAGMA table_info(mes_material_components)')}
        assert columns['withdrawn_quantity'][3] == 0
        assert columns['required_quantity'][3] == 1
        assert db.execute('SELECT count(*) FROM work_orders WHERE project_id=?', (p['id'],)).fetchone()[0] > 0


def test_cross_project_scope_and_source_uniqueness(workflow):
    import pytest
    from manufacturing_platform.workflow.contracts import DomainError
    first, _, one = workflow.material_requirement()
    second, _, two = workflow.material_requirement()
    source = FakeMes(); service = make_service(workflow, source)
    actor = Actor(user_id=USERS['owner'], display_name='owner', read_only=False, configuration_admin=True)
    first_id, second_id = UUID(first['id']), UUID(second['id'])
    with pytest.raises(DomainError):
        service.execute(actor, first_id, bind_command(service, actor, first['id'], two['work_order_id']))
    assert source.calls == 0
    service.execute(actor, first_id, bind_command(service, actor, first['id'], one['work_order_id']))
    with pytest.raises(DomainError) as exc:
        service.execute(actor, second_id, bind_command(service, actor, second['id'], two['work_order_id']))
    assert exc.value.code == 'MES_BINDING_CONFLICT'
    assert service.mes_materials(actor, second_id, UUID(two['work_order_id']))['binding'] is None


def test_http_bind_and_read_endpoint(workflow):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from manufacturing_platform.workflow.api import build_workflow_router
    from .conftest import BASE
    p, _, related = workflow.material_requirement()
    source = FakeMes()
    actor = {'user_id': USERS['owner'], 'display_name':'owner', 'read_only':False, 'configuration_admin':True}
    app = FastAPI()
    app.include_router(build_workflow_router(database_path=str(workflow.paths.domain), authority_database_path=str(workflow.paths.authority), assets_dir=str(workflow.paths.domain.parent), authenticate=lambda request, write: actor, resolve_subject=lambda uid: True, release='test', dataset={'id':'workflow-test', 'mode':'test', 'label':'Workflow test'}, mes_access_service=source))
    client = TestClient(app)
    path = f"{BASE}/projects/{p['id']}/work-orders/{related['work_order_id']}/mes-materials"
    initial = client.get(path)
    assert initial.status_code == 200 and initial.json()['binding'] is None
    assert initial.headers['cache-control'] == 'private, no-store'
    service = make_service(workflow, source)
    command = bind_command(service, Actor.model_validate(actor), p['id'], related['work_order_id'])
    response = client.post(f"{BASE}/projects/{p['id']}/commands", json=command)
    assert response.status_code == 200
    page = client.get(path)
    assert page.json()['binding']['shop_order'] == 'ORDER-1'
    assert source.calls == 1


def test_refresh_rejects_changed_namespace_before_query(workflow):
    import pytest
    from manufacturing_platform.workflow.contracts import DomainError
    p, _, related = workflow.material_requirement()
    source = FakeMes(); service = make_service(workflow, source)
    actor = Actor(user_id=USERS['owner'], display_name='owner', read_only=False, configuration_admin=True)
    pid, wid = UUID(p['id']), UUID(related['work_order_id'])
    service.execute(actor, pid, bind_command(service, actor, str(pid), str(wid)))
    binding = service.mes_materials(actor, pid, wid)['binding']
    source.order_materials_configuration = lambda: {'namespace':'different', 'fingerprint':'other'}
    command = {'action':'mes_order.refresh', 'operation_id':str(uuid4()), 'expected_version':service.detail(actor, pid).version, 'work_order_id':str(wid), 'binding_id':binding['id']}
    with pytest.raises(DomainError) as exc: service.execute(actor, pid, command)
    assert exc.value.code == 'MES_SOURCE_CHANGED'
    assert source.calls == 1


def test_configuration_change_after_precommit_check_is_rejected(workflow):
    import pytest
    from manufacturing_platform.workflow.contracts import DomainError
    p, _, related = workflow.material_requirement()
    source = FakeMes(); service = make_service(workflow, source)
    actor = Actor(user_id=USERS['owner'], display_name='owner', read_only=False, configuration_admin=True)
    checks = []
    def matches(fingerprint):
        checks.append(fingerprint)
        return len(checks) == 1
    source.configuration_matches = matches
    with pytest.raises(DomainError) as exc:
        service.execute(actor, UUID(p['id']), bind_command(service, actor, p['id'], related['work_order_id']))
    assert exc.value.code == 'MES_CONFIGURATION_CHANGED'
    assert service.mes_materials(actor, UUID(p['id']), UUID(related['work_order_id']))['binding'] is None


def test_null_withdrawn_survives_bind_refresh_restart_and_http(workflow):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from manufacturing_platform.workflow.api import build_workflow_router
    from .conftest import BASE
    p, _, related = workflow.material_requirement()
    source = FakeMes()
    original = source.collect_order_materials
    def collect(*args):
        result = original(*args)
        result['components'][0]['withdrawn_quantity'] = None
        return result
    source.collect_order_materials = collect
    actor_data = {'user_id': USERS['owner'], 'display_name': 'owner', 'read_only': False, 'configuration_admin': True}
    actor = Actor.model_validate(actor_data)
    service = make_service(workflow, source)
    pid, wid = UUID(p['id']), UUID(related['work_order_id'])
    service.execute(actor, pid, bind_command(service, actor, str(pid), str(wid)))
    first = service.mes_materials(actor, pid, wid)
    assert first['snapshot']['components'][0]['withdrawn_quantity'] is None
    refresh = {'action': 'mes_order.refresh', 'operation_id': str(uuid4()), 'expected_version': service.detail(actor, pid).version, 'work_order_id': str(wid), 'binding_id': first['binding']['id']}
    service.execute(actor, pid, refresh)
    restarted = make_service(workflow, source).mes_materials(actor, pid, wid)
    assert restarted['snapshot']['id'] != first['snapshot']['id']
    assert restarted['snapshot']['components'][0]['withdrawn_quantity'] is None
    with workflow.db() as db:
        assert [r[0] for r in db.execute('SELECT withdrawn_quantity FROM mes_material_components ORDER BY rowid')] == [None, None]
    app = FastAPI()
    app.include_router(build_workflow_router(database_path=str(workflow.paths.domain), authority_database_path=str(workflow.paths.authority), assets_dir=str(workflow.paths.domain.parent), authenticate=lambda request, write: actor_data, resolve_subject=lambda uid: True, release='test', dataset={'id': 'workflow-test', 'mode': 'test', 'label': 'Workflow test'}, mes_access_service=source))
    response = TestClient(app).get(f"{BASE}/projects/{pid}/work-orders/{wid}/mes-materials")
    assert response.status_code == 200
    assert response.json()['snapshot']['components'][0]['withdrawn_quantity'] is None
    assert source.calls == 2


def test_native_quantity_provenance_is_stored_observation_and_keeps_platform_balance(workflow):
    from .conftest import BASE
    p, _, related = workflow.material_requirement()
    before = workflow.client().get(f"{BASE}/projects/{p['id']}/material-control").json()['requirements'][0]
    source = FakeMes()
    service = make_service(workflow, source)
    actor = Actor(user_id=USERS['owner'], display_name='owner', read_only=False, configuration_admin=True)
    pid, wid = UUID(p['id']), UUID(related['work_order_id'])
    service.execute(actor, pid, bind_command(service, actor, str(pid), str(wid)))
    source.order_materials_configuration = lambda: (_ for _ in ()).throw(AssertionError('No source IO on read'))
    with workflow.db() as db:
        snapshot = list(db.iterdump())
    result = make_service(workflow, source).mes_materials(actor, pid, wid)
    for key, q in result['snapshot']['components'][0]['quantities'].items():
        assert q['value'] == result['snapshot']['components'][0][key]
        assert q['fact_role'] == 'observation'
        assert q['origins'] == ['native'] and q['environments'] == ['test']
        assert q['observed_at'] is None and q['collected_at'] == result['snapshot']['collected_at'].replace('+00:00', 'Z')
        assert q['source_refs'][0]['namespace'] == 'namespace'
        assert result['snapshot']['id'] in q['input_refs'][0]
    with workflow.db() as db:
        assert list(db.iterdump()) == snapshot
    after = workflow.client().get(f"{BASE}/projects/{p['id']}/material-control").json()['requirements'][0]
    assert before == after
    assert source.calls == 1


def test_scientific_quantities_preserve_raw_storage_across_refresh_and_restart(workflow):
    from manufacturing_platform.mes_access.order_materials import _amount
    p, _, related = workflow.material_requirement()
    source = FakeMes()
    original = source.collect_order_materials
    values = [('1e3', '1.2300e-3'), ('1e999999999999999999', '1e-999999999999999999')]
    def collect(*args):
        result = original(*args)
        required, withdrawn = values[source.calls - 1]
        result['components'][0].update(required_quantity=_amount(required), withdrawn_quantity=_amount(withdrawn))
        return result
    source.collect_order_materials = collect
    actor = Actor(user_id=USERS['owner'], display_name='owner', read_only=False, configuration_admin=True)
    service = make_service(workflow, source)
    pid, wid = UUID(p['id']), UUID(related['work_order_id'])
    service.execute(actor, pid, bind_command(service, actor, str(pid), str(wid)))
    first = service.mes_materials(actor, pid, wid)
    component = first['snapshot']['components'][0]
    assert component['required_quantity'] == '1e3' and component['withdrawn_quantity'] == '1.2300e-3'
    assert component['quantities']['required_quantity']['value'] == '1000'
    assert component['quantities']['withdrawn_quantity']['value'] == '0.0012300'
    refresh = {'action':'mes_order.refresh', 'operation_id':str(uuid4()), 'expected_version':service.detail(actor, pid).version, 'work_order_id':str(wid), 'binding_id':first['binding']['id']}
    service.execute(actor, pid, refresh)
    restarted = make_service(workflow, source).mes_materials(actor, pid, wid)
    component = restarted['snapshot']['components'][0]
    for name, raw in zip(('required_quantity', 'withdrawn_quantity'), values[1]):
        assert component[name] == raw
        q = component['quantities'][name]
        assert q['value'] is None and q['coverage'] == 'unknown'
        assert q['source_refs'][0]['value'] is None and 'verification' in q['source_refs'][0]['meaning']
        assert q['source_refs'][0]['collected_at'] and q['source_refs'][0]['namespace'] == 'namespace'
    with workflow.db() as db:
        assert [tuple(row) for row in db.execute('SELECT required_quantity,withdrawn_quantity FROM mes_material_components ORDER BY rowid')] == values
    assert source.calls == 2


def test_plain_quantity_expansion_bounds_and_null():
    from manufacturing_platform.workflow.native_material_service import plain_quantity
    assert plain_quantity(None) == (None, True)
    assert plain_quantity('1.00000000000000001') == ('1.00000000000000001', True)
    assert plain_quantity('1e4095') == ('1' + '0' * 4095, True)
    assert plain_quantity('1e4096') == (None, False)
    assert plain_quantity('1e-4094') == ('0.' + '0' * 4093 + '1', True)
    assert plain_quantity('1e-4095') == (None, False)
    assert plain_quantity('1e' + '9' * 125) == (None, False)


def test_mes_unicode_decimal_digits_project_as_plain_ascii():
    from manufacturing_platform.mes_access.order_materials import _amount
    from manufacturing_platform.workflow.native_material_service import plain_quantity
    assert _amount('١.٢e٢') == '١.٢e٢'
    assert plain_quantity('١.٢e٢') == ('120', True)
    assert plain_quantity('١.٢') == ('1.2', True)
