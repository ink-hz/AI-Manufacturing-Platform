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


def test_replacement_rejects_reusing_dependencies_and_view_range_preserves_independent_logs(investigation):
    service, actor, source, _, draft, selection = investigation
    source.rows = [{'id':1, 'projuectid':1, 'csn':'SN-1', 'createtime':1794186000000}]
    updated = service.update(actor, '1', draft['id'], {'expected_version':1, 'logs':['1']})
    assert updated['logs']
    with pytest.raises(DomainError) as caught:
        service.update(actor, '1', draft['id'], {'expected_version':2, 'primary':None, 'logs':['1']})
    assert caught.value.status == 422
    changed = service.update(actor, '1', draft['id'], {'expected_version':2, 'context':{**PARAMS,'view':'anomalies','evidence_range':{'start':'2026-11-09T03:00:00Z','end':PARAMS['end']}}})
    assert changed['logs'] == updated['logs']


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
    retained = service.update(actor, '1', draft['id'], {'expected_version':2, 'logs':['1']})
    assert retained['logs'] == draft['logs']
    with pytest.raises(DomainError) as caught:
        service.create(actor, '1', {'context':draft['context'], 'logs':['1']})
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


def test_native_descriptor_fields_validate_actual_stage_and_versions(investigation):
    from manufacturing_platform.production_tools.contracts import ProductionQuery
    service, actor, source, _, _, _ = investigation
    source.rows = [{'timestamp':'2026-11-09T01:00:00Z', 'projuectid':'1', 'sn':'EVENT', 'workstagesid':'10', 'softwareid':'20', 'version':'3.1', 'configlogsid':'30', 'cversion':'4.2', 'workselectid':'40'}]
    page = service.production.query(actor, '1', ProductionQuery(kind='production', **PARAMS))
    selection = {'snapshot_id':page['snapshot_id'], 'offset':0}
    context = {**PARAMS,'view':'anomalies','stage_id':'10','software_id':'20','software_version':'3.1','config_log_id':'30','config_version':'4.2'}
    draft = service.create(actor, '1', {'context':context,'primary':selection})
    assert {key: draft['primary']['descriptor'][key] for key in ('workstagesid','version','configlogsid','cversion','workselectid')} == {key:source.rows[0][key] for key in ('workstagesid','version','configlogsid','cversion','workselectid')}
    for key, value in [('stage_id','11'),('software_version','3.2'),('config_log_id','31'),('config_version','4.3')]:
        with pytest.raises(DomainError) as caught:
            service.update(actor, '1', draft['id'], {'expected_version':1,'context':{**context,key:value}})
        assert caught.value.status == 422


def test_log_candidate_csn_is_explicit_and_never_inferred_from_event_sn(investigation):
    service, actor, source, _, _, _ = investigation
    source.rows = [{'id':1,'projuectid':1,'csn':'DIFFERENT-CSN','createtime':1794186000000,'toolsname':'Tool A','state':'ready'}]
    draft = service.create(actor, '1', {'context':{**PARAMS,'view':'anomalies','sn':'EVENT-SN'}, 'logs':['1']})
    evidence_query = next(query for query in reversed(source.calls) if query.kind == 'evidence')
    assert evidence_query.sn is None
    assert draft['logs'][0]['match_basis'] == 'project_and_time'
    assert draft['logs'][0]['descriptor']['toolsname'] == 'Tool A'
    assert draft['logs'][0]['descriptor']['state'] == 'ready'
    explicit = service.create(actor, '1', {'context':{**PARAMS,'view':'anomalies','sn':'EVENT-SN','candidate_csn':'DIFFERENT-CSN'}, 'logs':['1']})
    evidence_query = next(query for query in reversed(source.calls) if query.kind == 'evidence')
    assert evidence_query.sn == 'DIFFERENT-CSN'
    assert explicit['logs'][0]['match_basis'] == 'project_time_and_explicit_csn'
    with pytest.raises(DomainError) as caught:
        service.create(actor, '1', {'context':{**PARAMS,'view':'anomalies','candidate_csn':'WRONG'}, 'logs':['1']})
    assert caught.value.status == 422


@pytest.fixture
def impact_source(investigation):
    from manufacturing_platform.production_tools.contracts import SourceResult
    service, actor, source, now, _, _ = investigation
    original = source.query
    source.statistics_count = 10000000000000000001
    source.statistics_complete = True
    def query(scope, query):
        if query.kind != 'production_statistics':
            return original(scope, query)
        source.calls.append(query)
        if source.failure:
            raise source.failure
        total = source.statistics_count
        failed = query.status == '2'
        row = {'records':3 if failed else total,'distinct_sn':2 if failed else 5,'pass_records':0 if failed else total-4,'fail_records':3,'raw_payload':{'must_not_persist':True}}
        return SourceResult(query.kind, [row], now[0], query.model_dump(mode='json',exclude_none=True), source.statistics_complete, None if source.statistics_complete else 'row_limit', None)
    source.query = query
    return service, actor, source, now


def test_impact_is_server_derived_exact_frozen_and_does_not_create_snapshots(impact_source):
    import sqlite3
    service, actor, source, now = impact_source
    with sqlite3.connect(service.production.config.snapshot_path) as db:
        before = db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0]
    context = {**PARAMS,'view':'anomalies','device':'D','sn':'EVENT'}
    draft = service.create(actor, '1', {'context':context})
    impact = draft['impact']
    assert impact['state'] == 'available'
    assert impact['baseline']['counts']['records'] == '10000000000000000001'
    assert impact['baseline']['counts']['unknown_records'] == '1'
    assert impact['failure']['filters']['status'] == '2'
    assert impact['failed_involved_sn']['numerator'] == '2'
    assert impact['failed_involved_sn']['denominator'] == '5'
    assert impact['failure_records']['denominator'] == '10000000000000000001'
    assert all(query.kind == 'production_statistics' for query in source.calls[-3:])
    with sqlite3.connect(service.production.config.snapshot_path) as db:
        assert db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0] == before
    assert 'must_not_persist' not in str(draft)
    handoff = service.create_handoff(actor,'1',draft['id'],{'expected_version':1})
    source.statistics_count = 999
    calls = len(source.calls)
    note_update = service.update(actor,'1',draft['id'],{'expected_version':1,'note':'later'})
    assert note_update['impact'] == impact and len(source.calls) == calls
    view_update = service.update(actor,'1',draft['id'],{'expected_version':2,'context':{**context,'view':'records'}})
    assert view_update['impact'] == impact and len(source.calls) == calls
    scope_update = service.update(actor,'1',draft['id'],{'expected_version':3,'context':{**context,'device':'NEW'}})
    assert scope_update['impact']['baseline']['counts']['records'] == '999'
    assert service.get_handoff(actor,handoff['id'])['impact'] == impact
    assert service.fork(actor,handoff['id'],{})['impact'] == impact


def test_impact_marks_unsupported_filters_without_broadening_and_source_failure(impact_source, monkeypatch):
    from manufacturing_platform.production_tools import investigation_statistics
    from manufacturing_platform.production_tools.contracts import ProductionQuery
    class LegacyQueryContract:
        model_fields = {key: field for key, field in ProductionQuery.model_fields.items() if key != 'error_code'}
        model_validate = ProductionQuery.model_validate
    monkeypatch.setattr(investigation_statistics, 'ProductionQuery', LegacyQueryContract)
    service, actor, source, _ = impact_source
    draft = service.create(actor,'1',{'context':{**PARAMS,'view':'anomalies','error_code':'E-1','status':'1'}})
    impact = draft['impact']
    assert impact['state'] == 'unsupported_scope'
    assert impact['baseline']['state'] == 'available'
    assert 'status' not in impact['baseline']['filters'] and 'error_code' not in impact['baseline']['filters']
    assert impact['selected']['state'] == 'unsupported_scope'
    assert impact['selected']['filters']['error_code'] == 'E-1'
    assert impact['failure']['filters']['error_code'] == 'E-1'
    assert impact['failure']['filters']['status'] == '2'
    assert impact['selected']['unsupported_filters'] == ['error_code']
    source.failure = RuntimeError('private connection password')
    updated = service.update(actor,'1',draft['id'],{'expected_version':1,'context':{**PARAMS,'view':'anomalies','device':'NEW'}})
    assert updated['impact']['state'] == 'unavailable'
    assert updated['impact']['baseline']['counts'] is None
    assert 'password' not in str(updated)
    assert updated['impact']['baseline']['filters']['device'] == 'NEW'


def test_impact_preserves_partial_coverage_and_rejects_invalid_aggregates(impact_source):
    service, actor, source, _ = impact_source
    source.statistics_complete = False
    draft = service.create(actor,'1',{'context':{**PARAMS,'view':'anomalies'}})
    assert draft['impact']['state'] == 'partial'
    assert draft['impact']['selected']['complete'] is False
    source.statistics_complete = True
    source.statistics_count = -1
    draft = service.create(actor,'1',{'context':{**PARAMS,'view':'anomalies'}})
    assert draft['impact']['state'] == 'partial'
    assert draft['impact']['baseline']['state'] == 'unavailable'
    assert draft['impact']['baseline']['counts'] is None


@pytest.mark.parametrize('bad_value', [True, 1.5, '9', -1])
def test_impact_rejects_coerced_counts_from_source(impact_source, bad_value):
    from dataclasses import replace
    service, actor, source, _ = impact_source
    original = source.query
    def invalid(scope, query):
        result = original(scope, query)
        return replace(result, items=[result.items[0] | {'records':bad_value}])
    source.query = invalid
    draft = service.create(actor,'1',{'context':{**PARAMS,'view':'anomalies'}})
    assert draft['impact']['state'] == 'unavailable'
    assert draft['impact']['selected']['error'] == 'SOURCE_SCHEMA_INVALID'
    assert draft['impact']['selected']['counts'] is None


def test_impact_rejects_counts_contradicting_requested_failure_status(impact_source):
    from dataclasses import replace
    service, actor, source, _ = impact_source
    original = source.query
    def inconsistent(scope, query):
        result = original(scope, query)
        if query.status == '2':
            return replace(result, items=[{'records':3,'distinct_sn':2,'pass_records':1,'fail_records':2}])
        return result
    source.query = inconsistent
    draft = service.create(actor,'1',{'context':{**PARAMS,'view':'anomalies'}})
    assert draft['impact']['failure']['state'] == 'unavailable'
    assert draft['impact']['failed_involved_sn']['numerator'] is None


@pytest.mark.parametrize("missing", [False, True])
def test_comparison_retains_different_versions_but_same_stage_tool(
    investigation, missing
):
    from manufacturing_platform.production_tools.contracts import ProductionQuery

    service, actor, source, _, _, _ = investigation
    row = {
        "timestamp": "2026-11-09T01:00:00Z",
        "projuectid": "1",
        "sn": "SN",
        "workstagesid": "10",
        "softwareid": "20",
    }
    source.rows = [
        row
        | {
            "version": None if missing else "A",
            "configlogsid": None if missing else "30",
            "cversion": None if missing else "A",
        },
        row | {"version": "B", "configlogsid": "31", "cversion": "B"},
        row | {"workstagesid": "99"},
        row | {"softwareid": "99"},
    ]
    page = service.production.query(
        actor, "1", ProductionQuery(kind="production", **PARAMS)
    )
    context = {**PARAMS, "stage_id": "10", "software_id": "20"}
    context.update(
        {"missing_fields": ["software_version", "config_log_id", "config_version"]}
        if missing
        else {"software_version": "A", "config_log_id": "30", "config_version": "A"}
    )
    select = lambda offset: {"snapshot_id": page["snapshot_id"], "offset": offset}
    draft = service.create(
        actor, "1", {"context": context, "primary": select(0), "comparison": select(1)}
    )
    assert draft["context"]["stage_id"] == "10"
    assert draft["comparison"]["descriptor"]["version"] == "B"
    assert (
        service.update(
            actor, "1", draft["id"], {"expected_version": 1, "note": "retained"}
        )["comparison"]
        == draft["comparison"]
    )
    with pytest.raises(DomainError) as exc:
        service.create(actor, "1", {"context": context, "primary": select(1)})
    assert exc.value.status == 422
    for offset in (2, 3):
        with pytest.raises(DomainError) as exc:
            service.create(
                actor,
                "1",
                {
                    "context": context,
                    "primary": select(0),
                    "comparison": select(offset),
                },
            )
        assert exc.value.status == 422


def test_history_subject_is_bounded_independent_and_survives_handoff_fork(
    impact_source,
):
    service, actor, source, _ = impact_source
    context = {
        **PARAMS,
        "sn": "ORIGINAL",
        "view": "history",
        "history_sn": "VIEWED",
        "history_range": PARAMS,
    }
    draft = service.create(actor, "1", {"context": context})
    impact = draft["impact"]
    calls = len(source.calls)
    changed = service.update(
        actor,
        "1",
        draft["id"],
        {
            "expected_version": 1,
            "context": {**context, "history_sn": "OTHER"},
            "note": "note",
        },
    )
    assert changed["context"]["sn"] == "ORIGINAL"
    assert changed["impact"] == impact and len(source.calls) == calls
    handoff = service.create_handoff(actor, "1", draft["id"], {"expected_version": 2})
    fork = service.fork(
        actor.model_copy(update={"user_id": uuid4()}), handoff["id"], {}
    )
    assert service.get(actor, "1", draft["id"])["context"]["history_sn"] == "OTHER"
    assert handoff["context"] == fork["context"] == changed["context"]
    assert fork["impact"] == impact
    for value in ("", "X" * 201, 12):
        with pytest.raises(DomainError) as exc:
            service.create(actor, "1", {"context": {**context, "history_sn": value}})
        assert exc.value.status == 422


def test_resolution_binding_uses_exact_resolved_revision_and_kind(
    investigation, monkeypatch
):
    service, actor, _, _, draft, _ = investigation
    handoff = service.create_handoff(actor, "1", draft["id"], {"expected_version": 1})
    old_metadata = service.get(actor, "1", draft["id"])
    service.update(
        actor, "1", draft["id"], {"expected_version": 1, "note": "another tab"}
    )
    binding = service.resolve(actor, "1", draft["id"])["binding"]
    assert binding == {
        "kind": "draft",
        "id": draft["id"],
        "version": 2,
        "primary_selection_id": draft["primary"]["selection_id"],
        "comparison_selection_id": None,
    }
    assert old_metadata["version"] == 1
    with pytest.raises(DomainError) as exc:
        service.update(
            actor, "1", draft["id"], {"expected_version": 2, "binding": binding}
        )
    assert exc.value.status == 422
    # An update during source resolution must not label the resolved payload with a later revision.
    original = service._resolve_selection
    updated = False

    def resolve_selection(*args):
        nonlocal updated
        if not updated:
            updated = True
            service.update(
                actor, "1", draft["id"], {"expected_version": 2, "primary": None}
            )
        return original(*args)

    monkeypatch.setattr(service, "_resolve_selection", resolve_selection)
    assert service.resolve(actor, "1", draft["id"])["binding"] == binding
    assert service.resolve(actor, "1", draft["id"])["binding"] == {
        **binding,
        "version": 3,
        "primary_selection_id": None,
    }
    frozen = service.resolve_handoff(actor, handoff["id"])["binding"]
    assert frozen == {
        **binding,
        "kind": "handoff",
        "id": handoff["id"],
        "version": handoff["version"],
    }


def test_history_subject_does_not_replace_primary_consistency(investigation):
    service, actor, _, _, draft, _ = investigation
    context = {**draft["context"], "history_sn": "DIFFERENT-SN"}
    changed = service.update(
        actor, "1", draft["id"], {"expected_version": 1, "context": context}
    )
    assert changed["primary"] == draft["primary"]
    with pytest.raises(DomainError) as exc:
        service.update(
            actor,
            "1",
            draft["id"],
            {"expected_version": 2, "context": {**context, "sn": "CONTRADICTORY"}},
        )
    assert exc.value.status == 422

@pytest.mark.parametrize('continued', [False, True])
def test_captured_log_uses_actual_narrowed_or_continued_query_and_bounded_own_revalidation(investigation, continued):
    from datetime import timedelta
    from manufacturing_platform.production_tools.contracts import ProductionQuery, SourceResult
    service, actor, source, now, draft, _ = investigation
    row = {'id':'42', 'projuectid':'1', 'csn':'LOG-CSN', 'createtime':1794186000000, 'devicename':'PC-NARROW', 'orderid':'19', 'url':'NEVER-PERSIST', 'content':'NEVER-PERSIST'}
    queries = []
    def query(scope, q):
        queries.append(q)
        narrow = q.device == 'PC-NARROW' and (not continued or q.before_id == 100)
        rows = [row] if narrow else [{'id':str(2000-i),'projuectid':'1','createtime':1794186000000} for i in range(1000)]
        return SourceResult(q.kind, rows, now[0], q.model_dump(mode='json',exclude_none=True), narrow, None if narrow else 'row_limit', None if narrow else 100)
    source.query = query
    q = ProductionQuery(kind='evidence', **PARAMS, device='PC-NARROW', order_id='19', tool_name='Tool', before_id=100 if continued else None)
    broad = service.production.query(actor, '1', ProductionQuery(kind='evidence', **PARAMS))
    assert broad['captured_count'] == 1000 and broad['complete'] is False
    assert all(str(item['id']) != '42' for item in broad['items'])
    if continued:
        first = service.production.query(actor, '1', q.model_copy(update={'before_id':None}))
        assert first['next_before_id'] == '100' and first['captured_count'] == 1000
        q = q.model_copy(update={'before_id':int(first['next_before_id'])})
    page = service.production.query(actor, '1', q)
    captured = {'snapshot_id':page['snapshot_id'], 'offset':0, 'source_log_id':'42'}
    count = len(queries)
    saved = service.update(actor,'1',draft['id'],{'expected_version':1,'logs':[captured]})
    assert len(queries) == count  # Save consumes the authorized immutable capture, never a broader scan.
    log = saved['logs'][0]
    assert log['filters'] == (q.model_dump(mode='json',exclude_none=True) | ({'before_id':'100'} if continued else {}))
    assert log['state'] == 'unverified' and 'NEVER-PERSIST' not in str(saved)
    assert log['snapshot_id'] == page['snapshot_id'] and log['offset'] == 0
    changed_context = {**saved['context'], 'candidate_csn':'OTHER', 'evidence_range':{'start':'2026-11-09T03:00:00Z','end':PARAMS['end']}}
    saved = service.update(actor,'1',draft['id'],{'expected_version':2,'context':changed_context,'logs':['42']})
    assert saved['logs'][0] == log and len(queries) == count
    assert service.resolve(actor,'1',draft['id'])['logs'][0]['state'] == 'verified'
    assert len(queries) == count
    now[0] += timedelta(hours=25)
    resolved = service.resolve(actor,'1',draft['id'])['logs'][0]
    assert resolved['state'] == 'verified'
    log_queries = [query for query in queries[count:] if query.kind == 'evidence']
    assert len(log_queries) == 1 and log_queries[0] == q
    source.query = lambda scope, q: SourceResult(q.kind, [], now[0], q.model_dump(mode='json',exclude_none=True), False, 'row_limit', None)
    assert service.resolve(actor,'1',draft['id'])['logs'][0]['state'] == 'partial'

@pytest.mark.parametrize('fault', ['kind','id','offset','expired','duplicate','extra','bool','string_offset','project','snapshot_project','source_revision'])
def test_captured_log_rejects_wrong_or_untrusted_capture(investigation, fault):
    from datetime import timedelta
    from manufacturing_platform.production_tools.contracts import ProductionQuery
    service, actor, source, now, draft, _ = investigation
    source.rows = [{'id':'42','projuectid':'2' if fault == 'project' else '1','createtime':1794186000000}]
    page = service.production.query(actor,'2' if fault == 'snapshot_project' else '1',ProductionQuery(kind='production' if fault == 'kind' else 'evidence',**PARAMS))
    if fault == 'source_revision':
        from dataclasses import replace
        service.production.config = replace(service.production.config, revision='changed')
    candidate = {'snapshot_id':page['snapshot_id'],'offset':0,'source_log_id':'42'}
    if fault == 'id': candidate['source_log_id'] = '43'
    if fault == 'offset': candidate['offset'] = 1
    if fault == 'extra': candidate['filters'] = PARAMS
    if fault == 'bool': candidate['offset'] = True
    if fault == 'string_offset': candidate['offset'] = '0'
    if fault == 'expired': now[0] += timedelta(hours=25)
    with pytest.raises(DomainError) as caught:
        service.update(actor,'1',draft['id'],{'expected_version':1,'logs':[candidate,'42'] if fault == 'duplicate' else [candidate]})
    assert caught.value.status in {404,422,410}
    if fault != 'source_revision':
        assert service.get(actor,'1',draft['id'])['logs'] == []


def test_new_capture_never_revalidates_retained_log_against_different_sidebar_query(investigation):
    from manufacturing_platform.production_tools.contracts import ProductionQuery
    service, actor, source, _, draft, _ = investigation
    def capture(identifier, device, csn):
        source.rows = [{'id':identifier,'projuectid':'1','devicename':device,'csn':csn,'createtime':1794186000000}]
        page = service.production.query(actor,'1',ProductionQuery(kind='evidence',device=device,sn=csn,**PARAMS))
        return {'snapshot_id':page['snapshot_id'],'offset':0,'source_log_id':identifier}
    first = capture('41','PC-FIRST','CSN-FIRST')
    saved = service.update(actor,'1',draft['id'],{'expected_version':1,'logs':[first]})
    second = capture('42','PC-SECOND','CSN-SECOND')
    source.failure = RuntimeError('source offline after authorized captures')
    saved_next = service.update(actor,'1',draft['id'],{'expected_version':2,'context':{**saved['context'],'candidate_csn':'CSN-SECOND'},'logs':['41',second]})
    assert saved_next['logs'][0] == saved['logs'][0]
    assert [log['filters']['sn'] for log in saved_next['logs']] == ['CSN-FIRST','CSN-SECOND']
    assert [log['state'] for log in service.resolve(actor,'1',draft['id'])['logs']] == ['verified','verified']
