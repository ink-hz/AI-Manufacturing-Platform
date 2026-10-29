"""Maintenance importer contracts, exercised against real domain services."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import UUID, uuid4

import pytest
from manufacturing_platform.workflow.contracts import Actor, GrantChange, ObjectKind, ProjectCreate
from manufacturing_platform.workflow.store import WorkflowStore

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'seed_workflow_demo.py'


def importer():
    assert SCRIPT.exists(), 'The production-only demo importer must exist'
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location('seed_workflow_demo', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def config(tmp_path, mode='demo'):
    return dict(workflow_db=str(tmp_path / 'workflow.db'), authority_db=str(tmp_path / 'authority.db'),
                dataset={'id': 'demo-contract', 'mode': mode, 'label': '模拟合同验收'},
                owner_ids=[str(uuid4())], manifest=str(tmp_path / 'private' / 'manifest.json'))


def snapshot(path):
    with sqlite3.connect(path) as db:
        return '\n'.join(db.iterdump())


def test_production_guard_precedes_database_creation(tmp_path):
    mod = importer()
    cfg = config(tmp_path, 'production')
    with pytest.raises(ValueError, match='demo'):
        mod.run(**cfg)
    assert not Path(cfg['workflow_db']).exists()


def test_portfolio_visible_actionable_and_completed_rerun_preserves_edit(tmp_path):
    mod = importer()
    cfg = config(tmp_path)
    receipt = mod.run(**cfg)
    assert receipt['status'] == 'complete'
    assert len(receipt['projects']) == 6
    assert len({p['line_id'] for p in receipt['projects']}) == 4
    seed = mod.Importer(**cfg)
    seed.run(verify_only=True)
    actor = Actor(user_id=cfg['owner_ids'][0], display_name='普通负责人', read_only=False, configuration_admin=False)
    for item in receipt['projects']:
        pid = UUID(item['id'])
        detail = seed.service.detail(actor, pid)
        assert detail.name.startswith('【模拟】')
        assert 'demand.record' in detail.allowed_actions
        member = seed.service.members(actor, pid, user_id=actor.user_id)[0]
        assert member.qualifications == []
        assert 'project_owner' in member.roles
        assert seed.service.objects(actor, pid, ObjectKind.order_line).total == 1
    by_key = {p['key']: p for p in receipt['projects']}
    assert by_key['aftercare']['summary']['accepted'] == '4'
    assert by_key['partial']['summary']['shipped'] == '3'
    assert by_key['partial']['summary']['remaining_to_ship'] == '3'
    assert by_key['quality']['counts']['nonconformance'] == 1
    assert by_key['quality']['counts']['rework'] == 1
    assert by_key['printer']['counts']['test'] == 1
    assert by_key['aftercare']['counts']['rma'] == 1
    assert by_key['aftercare']['counts']['capa'] == 1
    pid = UUID(by_key['shortage']['id'])
    seed.service.execute(actor, pid, {'action': 'demand.record', 'operation_id': str(uuid4()),
        'expected_version': seed.service.detail(actor, pid).version, 'kind': 'forecast',
        'product': seed.service.detail(actor, pid).product, 'quantity': '2', 'unit': '台', 'due_date': '2027-12-01',
        'source': seed.source('user-edit', 'demand')})
    before = snapshot(cfg['workflow_db']), snapshot(cfg['authority_db'])
    assert mod.run(**cfg)['status'] == 'complete'
    assert before == (snapshot(cfg['workflow_db']), snapshot(cfg['authority_db']))
    assert Path(cfg['manifest']).stat().st_mode & 0o077 == 0
    command = [sys.executable, str(SCRIPT), '--workflow-db', cfg['workflow_db'], '--authority-db', cfg['authority_db'],
        '--dataset-id', cfg['dataset']['id'], '--dataset-label', cfg['dataset']['label'], '--owner-id', cfg['owner_ids'][0],
        '--manifest', cfg['manifest'], '--verify-only']
    independent = subprocess.run(command, text=True, capture_output=True)
    assert independent.returncode == 0, independent.stderr
    assert len(json.loads(independent.stdout)['projects']) == 6


@pytest.mark.parametrize('crash_kind', ['project', 'command', 'receive', 'inspect', 'source.pull', 'exchange.dispatch'])
def test_committed_before_checkpoint_recovers_without_duplicate(tmp_path, monkeypatch, crash_kind):
    mod = importer()
    cfg = config(tmp_path)
    seed = mod.Importer(**cfg)
    original = seed.checkpoint
    failed = False
    def crash():
        nonlocal failed
        if not failed and seed.manifest['steps'] and ((latest := list(seed.manifest['steps'].values())[-1])['kind'] == crash_kind or latest['payload'].get('action') == crash_kind) and 'result' in latest:
            failed = True
            raise KeyboardInterrupt('simulated committed-before-checkpoint crash')
        original()
    monkeypatch.setattr(seed, 'checkpoint', crash)
    with pytest.raises(KeyboardInterrupt, match='committed-before'):
        seed.run()
    saved = json.loads(Path(cfg['manifest']).read_text())
    assert 'result' not in list(saved['steps'].values())[-1]
    result = mod.run(**cfg)
    assert len(result['projects']) == 6
    reopened = mod.Importer(**cfg)
    assert len(reopened.service.project_ids(reopened.actors['maintenance'])) == 6


def test_mismatch_and_lost_manifest_fail_without_mutation(tmp_path):
    mod = importer()
    cfg = config(tmp_path)
    mod.run(**cfg)
    before = snapshot(cfg['workflow_db'])
    with pytest.raises(ValueError, match='mismatch'):
        mod.run(**{**cfg, 'owner_ids': [str(uuid4())]})
    Path(cfg['manifest']).unlink()
    with pytest.raises(ValueError, match='manifest'):
        mod.run(**cfg)
    assert snapshot(cfg['workflow_db']) == before


def test_existing_sentinel_and_other_members_are_unchanged(tmp_path):
    mod = importer()
    cfg = config(tmp_path)
    seed = mod.Importer(**cfg)
    outsider = Actor(user_id=uuid4(), display_name='原有项目负责人', read_only=False, configuration_admin=True)
    from manufacturing_platform.workflow.contracts import ProjectCreate
    sentinel = seed.service.create_project(outsider, ProjectCreate.model_validate(dict(
        operation_id=str(uuid4()), name='原有项目，不属于模拟导入', line_id='原有业务线', product='旧产品', customer_id='原有客户',
        mode='internal', unit=dict(code='台', scale=0), quantity='2', contract=dict(customer_approval_required=False,
        customer_release_required=False, acceptance_required=True, customer_revision='C1', internal_revision='M1', material_ownership_rules='原有规则'))))
    before = seed.service.detail(outsider, sentinel.id).model_dump(mode='json')
    grants = [g.model_dump(mode='json') for g in seed.service.members(outsider, sentinel.id)]
    receipt = mod.run(**cfg)
    assert seed.service.detail(outsider, sentinel.id).model_dump(mode='json') == before
    assert [g.model_dump(mode='json') for g in seed.service.members(outsider, sentinel.id)] == grants
    # The creator's global privilege sees all projects; ordinary responsibility
    # remains confined to the unchanged sentinel grant.
    assert len(seed.service.project_ids(outsider)) == 7
    ordinary_owner = outsider.model_copy(update={'configuration_admin': False})
    assert seed.service.project_ids(ordinary_owner) == [str(sentinel.id)]
    with seed.store.transaction() as db:
        assert db.execute('SELECT COUNT(*) FROM projects').fetchone()[0] == 7
        assert {r[0] for r in db.execute('SELECT DISTINCT project_id FROM project_grants WHERE user_id=?', (cfg['owner_ids'][0],))} == {p['id'] for p in receipt['projects']}


def test_authority_provenance_is_required_on_completed_verification(tmp_path):
    mod = importer()
    cfg = config(tmp_path)
    mod.run(**cfg)
    # Failure injection only: corruption must not become a successful import/replay.
    with sqlite3.connect(cfg['authority_db']) as db:
        db.execute('DELETE FROM source_events WHERE seq=(SELECT MIN(seq) FROM source_events)')
    before = snapshot(cfg['workflow_db']), snapshot(cfg['authority_db'])
    with pytest.raises(ValueError, match='provenance'):
        mod.run(**cfg, verify_only=True)
    assert before == (snapshot(cfg['workflow_db']), snapshot(cfg['authority_db']))


def test_authority_dataset_mismatch_fails_before_project_creation(tmp_path):
    mod = importer()
    cfg = config(tmp_path)
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter
    MockAuthorityAdapter(cfg['authority_db'], 'different-dataset').snapshot('erp', 'receipt')
    with pytest.raises(ValueError, match='mismatch'):
        mod.run(**cfg)
    if Path(cfg['workflow_db']).exists():
        with sqlite3.connect(cfg['workflow_db']) as db:
            assert db.execute('SELECT COUNT(*) FROM projects').fetchone()[0] == 0


def test_incomplete_failure_keeps_original_error_and_rejects_concurrent_edit(tmp_path, monkeypatch):
    mod = importer()
    cfg = config(tmp_path)
    seed = mod.Importer(**cfg)
    original = seed.service.execute
    def fail_review(actor, pid, command):
        if command['action'] == 'demand.review':
            raise RuntimeError('first simulated outage')
        return original(actor, pid, command)
    monkeypatch.setattr(seed.service, 'execute', fail_review)
    with pytest.raises(RuntimeError, match='first simulated outage'):
        seed.run()
    failed = json.loads(Path(cfg['manifest']).read_text())
    assert not failed['complete']
    pid = UUID(next(iter(failed['project_versions'])))
    owner = Actor(user_id=cfg['owner_ids'][0], display_name='项目负责人', read_only=False, configuration_admin=False)
    detail = seed.service.detail(owner, pid)
    original(owner, pid, dict(action='demand.record', operation_id=str(uuid4()), expected_version=detail.version,
        kind='forecast', product=detail.product, quantity='1', unit='台', due_date='2027-12-01', source=seed.source('concurrent-edit', 'demand')))
    before = snapshot(cfg['workflow_db'])
    from manufacturing_platform.workflow.contracts import DomainError
    with pytest.raises(DomainError) as exc:
        mod.run(**cfg)
    assert exc.value.code == 'VERSION_CONFLICT'
    assert snapshot(cfg['workflow_db']) == before
    assert json.loads(Path(cfg['manifest']).read_text())['first_failure'] == failed['first_failure']


def test_recovered_command_does_not_adopt_concurrent_user_version(tmp_path, monkeypatch):
    mod = importer()
    cfg = config(tmp_path)
    seed = mod.Importer(**cfg)
    save = seed.checkpoint
    def crash_after_command():
        steps = list(seed.manifest['steps'].values())
        if steps and steps[-1]['kind'] == 'command' and 'result' in steps[-1]:
            raise KeyboardInterrupt('committed intent')
        save()
    monkeypatch.setattr(seed, 'checkpoint', crash_after_command)
    with pytest.raises(KeyboardInterrupt):
        seed.run()
    saved = json.loads(Path(cfg['manifest']).read_text())
    pending = list(saved['steps'].values())[-1]
    pid = UUID(pending['project_id'])
    owner = Actor(user_id=cfg['owner_ids'][0], display_name='项目负责人', read_only=False, configuration_admin=False)
    command = {**pending['payload'], 'operation_id': str(uuid4()), 'expected_version': seed.service.detail(owner, pid).version,
        'kind': 'forecast', 'source': {**pending['payload']['source'], 'external_id': 'USER-' + str(uuid4())}}
    seed.service.execute(owner, pid, command)
    before = snapshot(cfg['workflow_db'])
    with pytest.raises(ValueError, match='Incomplete recovery conflict'):
        mod.run(**cfg)
    assert snapshot(cfg['workflow_db']) == before


@pytest.mark.parametrize('active', [True, False])
def test_namespace_provenance_survives_maintenance_grant_revocation(tmp_path, active):
    mod = importer()
    cfg = config(tmp_path)
    seed = mod.Importer(**cfg)
    actor = seed.actors['maintenance']
    project = seed.service.create_project(actor, ProjectCreate.model_validate(dict(
        operation_id=str(uuid4()), name='Interrupted namespace', line_id='demo',
        product='Camera', customer_id='Customer', mode='internal',
        unit=dict(code='piece', scale=0), quantity='1',
        contract={key: 'unknown' for key in (
            'customer_approval_required', 'customer_release_required', 'acceptance_required',
            'customer_revision', 'internal_revision', 'material_ownership_rules')},
    )))
    if not active:
        seed.service.change_grant(actor, project.id, actor.user_id, GrantChange.model_validate(dict(
            operation_id=str(uuid4()), expected_version=project.version,
            scope=dict(kind='project', project_id=str(project.id)),
            roles=[], qualifications=[], active=False, evidence='Revoked responsibility',
        )))
    seed.service.exchange_service.adapter.snapshot('erp', 'receipt')
    before = snapshot(cfg['workflow_db']), snapshot(cfg['authority_db'])
    assert not Path(cfg['manifest']).exists()
    with pytest.raises(ValueError, match='original manifest'):
        mod.run(**cfg)
    assert before == (snapshot(cfg['workflow_db']), snapshot(cfg['authority_db']))
    assert not Path(cfg['manifest']).exists()
