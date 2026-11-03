from uuid import uuid4
import pytest
from manufacturing_platform.workflow.contracts import DomainError
from .support import MockRig


def test_intents_are_scoped_paginated_read_only_and_do_not_query_unknown(tmp_path):
    rig = MockRig(tmp_path, network=True)
    operation_id = uuid4()
    rig.registry.adapter('crm').store.configure_fault(rig.project_id, operation_id, 'timeout_after_commit')
    try:
        rig.execute('crm', dict(operation='crm.publish_demand', customer_id='C', product='P', demand_kind='firm', amount=dict(quantity='2',unit='piece',scale=0), due_date='2027-01-01'), operation_id=operation_id)
    except DomainError:
        pass
    version = rig.version()
    page = rig.workflow.integration_intents(rig.admin, rig.project_id, limit=1)
    assert page.project_id == rig.project_id
    assert page.limit == 1
    assert len(page.records) == 1
    assert page.records[0].intent_id == operation_id
    assert page.records[0].phase == "unknown"
    assert page.records[0].source_committed is None
    assert rig.version() == version
    assert rig.workflow.integration_intents(rig.admin, rig.other_project_id).records == []
    with pytest.raises(DomainError):
        rig.workflow.integration_intents(rig.admin, rig.project_id, limit=201)


def test_intents_exclude_foreign_project_and_reauthorize_without_source_io(tmp_path, monkeypatch):
    from manufacturing_platform.workflow.contracts import Actor
    rig = MockRig(tmp_path, network=True)
    rig.grant(['project_owner','planner','engineering','production'])
    for _ in range(2):
        rig.execute('hr_sap', dict(operation='hr_sap.publish_employee',employee_id=str(uuid4()),display_name='Operator',organization='Factory',position='Assembly',active=True))
    version = rig.version()
    for name in ('query', 'facts'):
        monkeypatch.setattr(rig.registry.adapter('hr_sap'), name, lambda *a, **kw: (_ for _ in ()).throw(AssertionError('read must not touch source')))
    first = rig.workflow.integration_intents(rig.actor, rig.project_id, limit=1)
    second = rig.workflow.integration_intents(rig.actor, rig.project_id, limit=1, offset=1)
    assert first.total == second.total == 2
    assert first.records[0].intent_id != second.records[0].intent_id
    assert first.records[0].source_committed is True
    assert not hasattr(first.records[0], 'payload_json')
    assert rig.version() == version
    stranger = Actor(user_id=uuid4(), display_name='stranger', configuration_admin=False, read_only=False)
    with pytest.raises(DomainError):
        rig.workflow.integration_intents(stranger, rig.project_id)
    from manufacturing_platform.workflow.contracts import GrantChange
    rig.workflow.change_grant(rig.admin, rig.project_id, rig.actor.user_id, GrantChange(operation_id=uuid4(),expected_version=rig.version(),scope=dict(kind='project',project_id=rig.project_id),roles=[],qualifications=[],active=False,evidence='Revoked fixture access'))
    with pytest.raises(DomainError):
        rig.workflow.integration_intents(rig.actor, rig.project_id)


def test_intent_browse_refuses_production_and_legacy_profiles(tmp_path):
    rig = MockRig(tmp_path, mode='production', network=True)
    with pytest.raises(DomainError, match='unavailable'):
        rig.workflow.integration_intents(rig.admin, rig.project_id)


def test_pull_intent_exposes_only_pinned_source_key_for_reload_recovery(tmp_path):
    rig = MockRig(tmp_path, network=True)
    result = rig.execute('crm', dict(operation='crm.publish_demand',customer_id='C',product='P',demand_kind='firm',amount=dict(quantity='1',unit='piece',scale=0),due_date='2027-01-01'))
    fact = rig.result_fact(result)
    rig.pull(fact.source_key)
    page = rig.workflow.integration_intents(rig.actor, rig.project_id)
    pull = next(r for r in page.records if r.operation == 'integration.pull')
    assert pull.source_key == fact.source_key
    assert all(r.source_key is None for r in page.records if r.operation != 'integration.pull')
