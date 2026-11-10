from datetime import UTC, datetime
from uuid import uuid4

import pytest

from manufacturing_platform.production_tools.investigations import InvestigationService
from manufacturing_platform.production_tools.service import ProductionToolsService
from manufacturing_platform.production_tools.contracts import ProductionToolsConfig
from manufacturing_platform.workflow.contracts import Actor, DomainError
from .test_api import FakeSource, PARAMS


def test_service_enforces_actor_and_read_only_before_io(tmp_path):
    source = FakeSource()
    production = ProductionToolsService(ProductionToolsConfig(source, 'native', 'v1', {'1':'p/'}, str(tmp_path / 's.db')), clock=lambda: datetime.now(UTC))
    service = InvestigationService(production, path=str(tmp_path / 'i.db'), clock=lambda: datetime.now(UTC))
    for admin, readonly in ((False, False), (True, True)):
        actor = Actor(user_id=uuid4(), display_name='A', configuration_admin=admin, read_only=readonly)
        with pytest.raises(DomainError) as exc:
            service.create(actor, '1', {'context': {**PARAMS, 'view':'anomalies'}})
        assert exc.value.status == 403
    assert source.calls == []


@pytest.fixture
def investigation(tmp_path):
    from manufacturing_platform.production_tools.contracts import SourceResult, SourceScope
    class Source(FakeSource):
        def __init__(self):
            super().__init__()
            self.rows = [{'timestamp': '2026-11-09T01:02:03.123456Z', 'sn': 'SN-1', 'projuectid':'1', 'dynamic': {'value': 12345678901234567890}}]
            self.complete = True
        def query(self, scope, query):
            self.calls.append(query)
            if self.failure:
                raise self.failure
            return SourceResult(query.kind, self.rows, now[0], query.model_dump(mode='json', exclude_none=True), self.complete, None if self.complete else 'row_limit', None)
    now = [datetime(2026, 11, 10, tzinfo=UTC)]
    source = Source()
    production = ProductionToolsService(ProductionToolsConfig(source, 'native', 'v1', {'1':'p/'}, str(tmp_path / 'snap.db')), clock=lambda: now[0])
    service = InvestigationService(production, path=str(tmp_path / 'investigations.db'), clock=lambda: now[0])
    actor = Actor(user_id=uuid4(), display_name='Admin', configuration_admin=True, read_only=False)
    page = production.query(actor, '1', __import__('manufacturing_platform.production_tools.contracts', fromlist=['ProductionQuery']).ProductionQuery(kind='production', **PARAMS))
    selection = {'snapshot_id':page['snapshot_id'], 'offset':0}
    draft = service.create(actor, '1', {'context': {**PARAMS, 'view':'anomalies'}, 'primary':selection})
    return service, actor, source, now, draft, selection


@pytest.mark.parametrize('case,expected', [('same','verified'), ('duplicate','ambiguous'), ('changed','changed'), ('missing','not_found'), ('truncated','partial'), ('offline','unavailable')])
def test_expired_snapshot_queries_exact_locator_and_never_picks_duplicates(investigation, case, expected):
    service, actor, source, now, draft, _ = investigation
    from datetime import timedelta
    now[0] += timedelta(hours=25)
    if case == 'duplicate':
        source.rows *= 2
    elif case == 'changed':
        source.rows[0]['dynamic'] = {'value': 'different'}
    elif case == 'missing':
        source.rows = []
    elif case == 'truncated':
        source.complete = False
    elif case == 'offline':
        source.failure = RuntimeError('mysql://private-password')
    resolved = service.resolve(actor, '1', draft['id'])['primary']
    assert resolved['state'] == expected
    query = source.calls[-1]
    assert query.sn == 'SN-1'
    assert query.start == datetime(2026,11,9,1,2,3,123456,tzinfo=UTC)
    assert (query.end-query.start).total_seconds() == .000001
    assert 'private-password' not in str(resolved)
    if case == 'duplicate':
        assert len(resolved['candidates']) == 2


def test_live_snapshot_is_verified_without_source_io(investigation):
    service, actor, source, _, draft, _ = investigation
    source.failure = RuntimeError('offline')
    count = len(source.calls)
    resolved = service.resolve(actor, '1', draft['id'])['primary']
    assert resolved['state'] == 'verified'
    assert len(source.calls) == count
    assert resolved['candidates'][0]['row']['dynamic']['value'] == '12345678901234567890'


def test_scope_replacement_requires_clearing_incompatible_saved_event(investigation):
    service, actor, _, _, draft, _ = investigation
    with pytest.raises(DomainError) as caught:
        service.update(actor, '1', draft['id'], {'expected_version':1, 'context':{**PARAMS,'view':'history','sn':'OTHER'}})
    assert caught.value.status == 422
    assert service.get(actor, '1', draft['id'])['version'] == 1
    result = service.update(actor, '1', draft['id'], {'expected_version':1, 'primary':None, 'context':{**PARAMS,'view':'history','sn':'OTHER'}})
    assert result['primary'] is None


def test_log_references_require_current_source_metadata_and_keep_only_allowlist(investigation):
    service, actor, source, _, draft, _ = investigation
    source.rows = [{'id': 99999999999999999999, 'projuectid':1, 'csn':'SN-1', 'createtime':1794186000000, 'url':'https://do-not-save', 'content':{'private':'do-not-save'}}]
    updated = service.update(actor, '1', draft['id'], {'expected_version':1, 'logs':['99999999999999999999']})
    assert updated['logs'][0]['source_log_id'] == '99999999999999999999'
    assert 'do-not-save' not in str(updated)
    source.rows = []
    with pytest.raises(DomainError) as caught:
        service.update(actor, '1', draft['id'], {'expected_version':2, 'logs':['1']})
    assert caught.value.status == 422


def test_protected_paths_reject_hardlink_and_symlink_aliases(tmp_path):
    source = FakeSource()
    protected = tmp_path/'private.json'
    protected.write_text('secrets')
    candidate = tmp_path/'candidate.db'
    candidate.hardlink_to(protected)
    config = ProductionToolsConfig(source, 'native', 'v1', {}, str(candidate), protected_paths=(str(protected),))
    with pytest.raises(ValueError):
        ProductionToolsService(config, clock=lambda: datetime.now(UTC))
    assert protected.read_text() == 'secrets'


def test_path_alias_changes_after_start_are_rejected_without_mutation(investigation, tmp_path):
    service, actor, _, _, draft, _ = investigation
    from pathlib import Path
    path = Path(service.store.path)
    path.unlink()
    path.hardlink_to(Path(service.production.config.snapshot_path))
    with pytest.raises(DomainError) as caught:
        service.get(actor, '1', draft['id'])
    assert caught.value.status == 503


def test_read_only_handoff_access_and_mutations(investigation):
    service, actor, _, _, draft, _ = investigation
    handoff = service.create_handoff(actor, '1', draft['id'], {'expected_version':1})
    readonly = actor.model_copy(update={'user_id':uuid4(), 'read_only':True})
    assert service.get_handoff(readonly, handoff['id'])['id'] == handoff['id']
    assert service.resolve_handoff(readonly, handoff['id'])['primary']['state'] == 'verified'
    with pytest.raises(DomainError) as caught:
        service.fork(readonly, handoff['id'], {})
    assert caught.value.status == 403


def test_replacement_rejects_reusing_dependencies_and_context_rejects_out_of_range_logs(investigation):
    service, actor, source, _, draft, selection = investigation
    source.rows = [{'id':1, 'projuectid':1, 'csn':'SN-1', 'createtime':1794186000000}]
    updated = service.update(actor, '1', draft['id'], {'expected_version':1, 'logs':['1']})
    assert updated['logs']
    with pytest.raises(DomainError) as caught:
        service.update(actor, '1', draft['id'], {'expected_version':2, 'primary':None, 'logs':['1']})
    assert caught.value.status == 422
    with pytest.raises(DomainError) as caught:
        service.update(actor, '1', draft['id'], {'expected_version':2, 'context':{**PARAMS,'view':'anomalies','evidence_range':{'start':'2026-11-09T03:00:00Z','end':PARAMS['end']}}})
    assert caught.value.status == 422


def test_log_revalidation_reports_missing_and_ambiguous_without_picking(investigation):
    service, actor, source, _, draft, _ = investigation
    row = {'id':1, 'projuectid':1, 'csn':'SN-1', 'createtime':1794186000000}
    source.rows = [row]
    draft = service.update(actor, '1', draft['id'], {'expected_version':1, 'logs':['1']})
    source.rows = []
    assert service.resolve(actor, '1', draft['id'])['logs'][0]['state'] == 'not_found'
    source.rows = [row, row]
    resolved = service.resolve(actor, '1', draft['id'])['logs'][0]
    assert resolved['state'] == 'ambiguous' and len(resolved['candidates']) == 2
    with pytest.raises(DomainError) as caught:
        service.update(actor, '1', draft['id'], {'expected_version':2, 'logs':['1']})
    assert caught.value.status == 422


def test_new_draft_ttl_starts_after_source_validation(investigation):
    from datetime import timedelta
    service, actor, source, now, _, _ = investigation
    original = source.query
    source.rows = [{'id':1, 'projuectid':1, 'csn':'SN-1', 'createtime':1794186000000}]
    def delayed_query(scope, query):
        now[0] += timedelta(days=2)
        return original(scope, query)
    source.query = delayed_query
    draft = service.create(actor, '1', {'context':{**PARAMS, 'view':'anomalies'}, 'logs':['1']})
    assert datetime.fromisoformat(draft['expires_at']) == now[0] + timedelta(days=30)


def test_writes_physically_remove_expired_metadata_in_bounded_batches(investigation):
    from datetime import timedelta
    import sqlite3
    service, actor, _, now, draft, _ = investigation
    # 102 drafts and one handoff will expire together; one cleanup must delete at most100.
    for _ in range(101):
        service.create(actor, '1', {'context':{**PARAMS, 'view':'anomalies'}})
    expired_handoff = service.create_handoff(actor, '1', draft['id'], {'expected_version':1})
    now[0] += timedelta(days=29)
    retained_handoff = service.create_handoff(actor, '1', draft['id'], {'expected_version':1})
    with sqlite3.connect(service.production.config.snapshot_path) as db:
        snapshots_before = db.execute('SELECT * FROM snapshots').fetchall()
    now[0] += timedelta(days=2)
    with pytest.raises(DomainError) as caught:
        service.get(actor, '1', draft['id'])
    assert caught.value.status == 410
    def expired_count():
        with sqlite3.connect(service.store.path) as db:
            return db.execute('SELECT COUNT(*) FROM investigations WHERE expires_at<=?', (now[0].isoformat(),)).fetchone()[0]
    assert expired_count() == 103
    service.create(actor, '1', {'context':{**PARAMS, 'view':'anomalies'}})
    assert expired_count() == 3
    assert service.get_handoff(actor, retained_handoff['id'])['id'] == retained_handoff['id']
    service.create(actor, '1', {'context':{**PARAMS, 'view':'anomalies'}})
    assert expired_count() == 0
    for identifier, get in ((draft['id'], lambda ident: service.get(actor, '1', ident)), (expired_handoff['id'], lambda ident: service.get_handoff(actor, ident))):
        with pytest.raises(DomainError) as caught:
            get(identifier)
        assert caught.value.status == 404
    with sqlite3.connect(service.production.config.snapshot_path) as db:
        assert db.execute('SELECT * FROM snapshots').fetchall() == snapshots_before
