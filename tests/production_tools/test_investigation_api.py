from datetime import UTC, datetime, timedelta
from dataclasses import replace
import sqlite3

import pytest

from .test_api import configure, PARAMS

ROOT = '/api/v1/manufacturing/workflow/production-tools'
PATH = ROOT + '/projects/1/investigations'
CONTEXT = {**PARAMS, 'view': 'anomalies'}


def create(workflow, **extra):
    response = workflow.client('admin').post(PATH, json={'context': CONTEXT, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_private_drafts_immutable_handoff_and_fork(workflow):
    configure(workflow)
    draft = create(workflow, note='Investigate')
    path = PATH + '/' + draft['id']
    assert workflow.client('owner').get(path).status_code == 404
    assert workflow.client('owner').get(PATH).json()['items'] == []
    updated = workflow.client('admin').put(path, json={'expected_version': 1, 'note': 'New'})
    assert updated.status_code == 200, updated.text
    assert updated.json()['version'] == 2
    assert workflow.client('admin').put(path, json={'expected_version': 1}).status_code == 409
    assert workflow.client('admin').post(path + '/handoffs', json={'expected_version': 1}).status_code == 409
    handoff = workflow.client('admin').post(path + '/handoffs', json={'expected_version': 2})
    assert handoff.status_code == 200, handoff.text
    hp = ROOT + '/handoffs/' + handoff.json()['id']
    assert workflow.client('owner').get(hp).json()['note'] == 'New'
    fork = workflow.client('owner').post(hp + '/fork', json={})
    assert fork.status_code == 200, fork.text
    assert fork.json()['version'] == 1 and fork.json()['owner_id'] != draft['owner_id']
    workflow.client('admin').put(path, json={'expected_version': 2, 'note': 'Later'})
    assert workflow.client('owner').get(hp).json()['note'] == 'New'
    workflow.reopen()
    assert workflow.client('admin').get(path).json()['note'] == 'Later'


def test_authorization_and_strict_body(workflow):
    source = configure(workflow)
    assert workflow.client('outsider').post(PATH, json={'context': CONTEXT}).status_code == 403
    workflow.read_only.add('admin')
    assert workflow.client('admin').post(PATH, json={'context': CONTEXT}).status_code == 403
    assert source.calls == []
    workflow.read_only.clear()
    for extra in ({'owner_id': 'bad'}, {'logs': ['1'] * 6}, {'logs': [True]}, {'note': 'a' * 4001}, {'context': {**CONTEXT, 'unknown': {}}}):
        assert workflow.client('admin').post(PATH, json={'context': CONTEXT, **extra}).status_code == 422


def test_expiry_scope_and_offline_metadata(workflow):
    now = [datetime(2026, 11, 10, tzinfo=UTC)]
    workflow.business_clock = lambda: now[0]
    source = configure(workflow)
    draft = create(workflow)
    path = PATH + '/' + draft['id']
    source.failure = RuntimeError('secret connection')
    assert workflow.client('admin').get(path).status_code == 200
    now[0] += timedelta(days=30)
    assert workflow.client('admin').get(path).status_code == 410
    now[0] -= timedelta(days=30)
    workflow.production_tools = replace(workflow.production_tools, revision='v2')
    workflow.reopen()
    assert workflow.client('admin').get(path).status_code == 404


def test_selection_metadata_and_replacement(workflow):
    configure(workflow)
    from manufacturing_platform.production_tools.store import SnapshotStore
    from manufacturing_platform.production_tools.contracts import SourceScope, SourceResult
    store = SnapshotStore(workflow.production_tools.snapshot_path, clock=lambda: datetime.now(UTC))
    sid = str(store.put(SourceScope('native', '1', 'v1', 'project/'), SourceResult('production', [
        {'sn': 'A', 'timestamp': '2026-11-09T01:00:00Z', 'huge_payload': 'DO_NOT_PERSIST'},
        {'sn': 'B', 'timestamp': '2026-11-09T02:00:00Z'}], datetime.now(UTC), PARAMS | {'kind': 'production'}, True, None, None)))
    draft = create(workflow, primary={'snapshot_id': sid, 'offset': 0}, comparison={'snapshot_id': sid, 'offset': 1})
    assert draft['primary']['fingerprint_version'] == 1
    path = PATH + '/' + draft['id']
    same = workflow.client('admin').put(path, json={'expected_version': 1, 'primary': {'snapshot_id': sid, 'offset': 0}, 'note': 'same'})
    assert same.status_code == 200, same.text
    assert same.json()['comparison'] is not None
    changed = workflow.client('admin').put(path, json={'expected_version': 2, 'primary': {'snapshot_id': sid, 'offset': 1}})
    assert changed.status_code == 200, changed.text
    assert changed.json()['comparison'] is None and changed.json()['logs'] == []
    with sqlite3.connect(workflow.production_tools.snapshot_path + '.investigations.sqlite3') as db:
        assert 'DO_NOT_PERSIST' not in str(db.execute('SELECT payload_json FROM investigations').fetchall())
    bad = workflow.client('admin').put(path, json={'expected_version': 3, 'context': {**CONTEXT, 'start': '2026-11-09T03:00:00Z'}})
    assert bad.status_code == 422


@pytest.mark.parametrize('body', [
    {'context': {**CONTEXT, 'view':'arbitrary'}},
    {'context': {**CONTEXT, 'start':0}},
    {'context': {**CONTEXT, 'start':'2026-11-09T00:00:00'}},
    {'context': {**CONTEXT, 'history_range':{**PARAMS,'extra':1}}},
    {'context': {**CONTEXT, 'stage_id':123}},
    {'context': {**CONTEXT, 'status':1}},
    {'context': CONTEXT, 'primary':{'snapshot_id':'not-a-uuid','offset':0}},
    {'context': CONTEXT, 'primary':{'snapshot_id':'00000000-0000-0000-0000-000000000000','offset':True}},
    {'context': CONTEXT, 'primary':{'snapshot_id':'00000000-0000-0000-0000-000000000000','offset':0,'descriptor':{}}},
])
def test_rejects_unsafe_or_coerced_context_and_selection(workflow, body):
    source = configure(workflow)
    response = workflow.client('admin').post(PATH, json=body)
    assert response.status_code == 422, response.text
    assert source.calls == []


def test_duplicate_json_fields_and_oversize_body_are_rejected(workflow):
    configure(workflow)
    client = workflow.client('admin')
    assert client.post(PATH, content='{"context":{},"context":{}}', headers={'content-type':'application/json'}).status_code == 422
    assert client.post(PATH, content=' ' * 32769).status_code == 422


def test_expired_draft_does_not_expire_independently_created_handoff(workflow):
    now = [datetime(2026,11,10,tzinfo=UTC)]
    workflow.business_clock = lambda: now[0]
    configure(workflow)
    draft = create(workflow)
    path = PATH + '/' + draft['id']
    now[0] += timedelta(days=29)
    handoff = workflow.client('admin').post(path+'/handoffs', json={'expected_version':1}).json()
    now[0] += timedelta(days=2)
    assert workflow.client('admin').get(path).status_code == 410
    assert workflow.client('owner').get(ROOT+'/handoffs/'+handoff['id']).status_code == 200
    now[0] += timedelta(days=28)
    assert workflow.client('owner').get(ROOT+'/handoffs/'+handoff['id']).status_code == 410


def test_reads_do_not_extend_draft_ttl_but_successful_save_does(workflow):
    now = [datetime(2026,11,10,tzinfo=UTC)]
    workflow.business_clock = lambda: now[0]
    configure(workflow)
    draft = create(workflow)
    path = PATH + '/' + draft['id']
    now[0] += timedelta(days=29)
    assert workflow.client('admin').get(path).json()['expires_at'] == draft['expires_at']
    saved = workflow.client('admin').put(path, json={'expected_version':1, 'note':'retain'})
    assert saved.status_code == 200
    assert saved.json()['expires_at'] != draft['expires_at']
    now[0] += timedelta(days=2)
    assert workflow.client('admin').get(path).status_code == 200


def test_store_failure_is_sanitized_without_traceback(workflow, capsys):
    from pathlib import Path
    configure(workflow)
    draft = create(workflow)
    store_path = Path(workflow.production_tools.snapshot_path + '.investigations.sqlite3')
    store_path.write_bytes(b'private-connection-secret')
    response = workflow.client('admin').get(PATH+'/'+draft['id'])
    assert response.status_code == 503
    assert 'private-connection-secret' not in response.text
    assert 'Traceback' not in capsys.readouterr().err
    assert workflow.client('admin').get(ROOT+'/status').json()['configured'] is True
