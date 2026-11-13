"""Isolated SAP observations: no production connector or source I/O."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import sqlite3
import pytest
from .conftest import BASE

URL = BASE + '/material-control/sap'
SOURCE = dict(system='sap', origin='native', fact_role='observation', environment='test', system_id='TST', client='001', namespace='isolated')

class Sap:
    def __init__(self):
        self.binding = 'one'
        self.calls = []
        self.context_calls = 0
        self.error = False
        self.hook = None
    def read_context(self):
        self.context_calls += 1
        return dict(source=SOURCE, fingerprint=self.binding)
    def configuration_matches(self, value):
        return value == self.binding
    def production_order(self, number, plant, actor_id, *, expected_fingerprint=None):
        self.calls.append((number, plant, actor_id))
        if self.hook: self.hook()
        if self.error: raise RuntimeError('secret source payload')
        return dict(number=number, plant=plant, material='MAT', description='Order', quantity='1.2300', unit='EA', components=[], total=0, request_id='isolated-request', source=SOURCE, function='BAPI_PRODORD_GET_DETAIL')
    def stock_requirements(self, material, plant, actor_id, *, expected_fingerprint=None):
        self.calls.append((material, plant, actor_id))
        return dict(mrp_list=dict(MATERIAL='000000000000000123', PLANT=plant), items=[dict(AVAIL_QTY1='1.2300-')], request_id='isolated-mrp')

@pytest.fixture
def h(workflow):
    return workflow

@pytest.fixture
def sap_h(h):
    h.sap_access_service = Sap()
    h.reopen()
    return h, h.sap_access_service

def test_status_without_connector(h):
    assert h.client().get(URL+'/status').json() == dict(configured=False, source=None, can_refresh=False)

def test_refresh_get_and_native_quantities(sap_h):
    h, sap = sap_h
    path = URL+'/production-order?number=123&plant=T001'
    assert h.client().get(path).json() == dict(snapshot=None, refresh_error=None)
    assert not sap.calls
    response = h.client().post(path)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['snapshot']['scope'] == dict(number='000000000123', plant='T001')
    assert result['snapshot']['data']['quantity'] == '1.2300'
    assert result['snapshot']['source'] == SOURCE
    assert 'fingerprint' not in response.text
    assert h.client().get(path).json() == result
    assert len(sap.calls) == 1

@pytest.mark.parametrize('actor', ['outsider', 'planner'])
def test_authorization_before_config(sap_h, actor):
    h, sap = sap_h
    for method, route in [('get','/status'), ('get','/production-order?number=123&plant=T001'), ('post','/production-order?number=123&plant=T001')]:
        assert getattr(h.client(actor), method)(URL+route).status_code == 403
    assert sap.context_calls == 0

@pytest.mark.parametrize('suffix,body', [('?number=123&plant=T001&extra=x',None), ('?number=123&number=456&plant=T001',None), ('?number=*&plant=T001',None), ('?number=123&plant=T001','{}'), ('?number=123&plant=T001',' ')])
def test_invalid_request_before_config(sap_h, suffix, body):
    h, sap = sap_h
    assert h.client().post(URL+'/production-order'+suffix, content=body).status_code == 422
    assert sap.context_calls == 0

def test_readonly_and_inactive(sap_h):
    h, sap = sap_h
    h.read_only.add('owner')
    assert h.client().get(URL+'/status').json()['can_refresh'] is False
    assert h.client().post(URL+'/production-order?number=123&plant=T001').status_code == 403
    h.inactive.add('owner')
    before = sap.context_calls
    assert h.client().get(URL+'/status').status_code == 403
    assert sap.context_calls == before

def test_failure_preserves_snapshot_and_configuration_isolates(sap_h):
    h, sap = sap_h
    path = URL+'/production-order?number=123&plant=T001'
    original = h.client().post(path).json()['snapshot']
    sap.error = True
    failed = h.client().post(path).json()
    assert failed['snapshot'] == original
    assert failed['refresh_error']['code'] == 'SAP_REFRESH_FAILED'
    assert 'secret' not in str(failed)
    assert h.client().get(path).json() == failed
    sap.binding = 'two'
    assert h.client().get(path).json()['snapshot'] is None
    sap.hook = lambda: setattr(sap, 'binding', 'three')
    assert h.client().post(path).json()['snapshot'] is None

def test_mrp_identity_and_retention(sap_h):
    h, sap = sap_h
    good = h.client().post(URL+'/stock-requirements?material=123&plant=T001').json()
    assert good['snapshot']['data']['items'][0]['AVAIL_QTY1'] == '1.2300-'
    bad = h.client().post(URL+'/stock-requirements?material=OTHER&plant=T001').json()
    assert bad['snapshot'] is None
    assert bad['refresh_error']['code'] == 'SAP_SCOPE_MISMATCH'

def test_concurrent_refresh_old_request_cannot_overwrite(sap_h):
    h, sap = sap_h
    entered, release = Event(), Event()
    def hook():
        if len(sap.calls) == 1:
            entered.set()
            assert release.wait(10)
    sap.hook = hook
    path = URL+'/production-order?number=123&plant=T001'
    with ThreadPoolExecutor(2) as pool:
        old = pool.submit(lambda: h.client().post(path).json())
        assert entered.wait(10)
        newer = h.client().post(path).json()
        release.set()
        result = old.result()
    assert result['snapshot'] == newer['snapshot']
    assert result['refresh_error']['code'] == 'SAP_REFRESH_SUPERSEDED'
    assert h.client().get(path).json() == newer

def test_schema28_upgrade_preserves_metadata_and_existing_records(h):
    h.create_project()
    with sqlite3.connect(h.paths.domain) as db:
        before = db.execute('SELECT * FROM projects').fetchall()
        metadata = db.execute('SELECT * FROM dataset_metadata').fetchall()
        db.execute('DROP TABLE sap_material_observations')
        db.execute('UPDATE schema_version SET version=28')
    h.sap_access_service = Sap()
    h.reopen()
    assert h.client().get(URL+'/production-order?number=123&plant=T001').status_code == 200
    with sqlite3.connect(h.paths.domain) as db:
        assert db.execute('SELECT version FROM schema_version').fetchone()[0] == 29
        assert db.execute('SELECT * FROM projects').fetchall() == before
        assert db.execute('SELECT * FROM dataset_metadata').fetchall() == metadata

def test_bad_configuration_is_explicit_and_sanitized(sap_h):
    h, sap = sap_h
    def broken():
        raise RuntimeError('secret config path')
    sap.read_context = broken
    result = h.client().get(URL+'/status').json()
    assert result['configured'] is False
    assert result['refresh_error']['code'] == 'SAP_CONFIGURATION_ERROR'
    assert 'secret' not in str(result)
    assert h.client().post(URL+'/production-order?number=123&plant=T001').json()['snapshot'] is None
    assert not sap.calls

def test_configuration_switch_after_success_does_not_persist_old_result(sap_h):
    h, sap = sap_h
    path = URL+'/production-order?number=123&plant=T001'
    sap.hook = lambda: setattr(sap, 'binding', 'two')
    result = h.client().post(path).json()
    assert result['snapshot'] is None
    assert result['refresh_error']['code'] == 'SAP_CONFIGURATION_CHANGED'
    sap.binding = 'one'
    assert h.client().get(path).json()['snapshot'] is None

def test_source_io_has_no_open_workflow_transaction(sap_h):
    h, sap = sap_h
    import sqlite3
    def independent_writer():
        with sqlite3.connect(h.paths.domain, timeout=0.1) as db:
            db.execute('UPDATE sap_material_observations SET refresh_seq=refresh_seq')
    sap.hook = independent_writer
    assert h.client().post(URL+'/production-order?number=123&plant=T001').json()['snapshot']

def test_storage_failure_returns_503_not_unsaved_success(sap_h):
    h, sap = sap_h
    h.client().post(URL+'/production-order?number=123&plant=T001')
    with sqlite3.connect(h.paths.domain) as db:
        db.execute("CREATE TRIGGER deny_sap_success BEFORE UPDATE OF snapshot_json ON sap_material_observations BEGIN SELECT RAISE(ABORT,'isolated failure'); END")
    response = h.client().post(URL+'/production-order?number=123&plant=T001')
    assert response.status_code == 503
    assert response.json() == {'detail': 'Workflow storage unavailable'}

@pytest.mark.parametrize('header', [{}, {'PLANT':'T001'}, {'MATERIAL':'123', 'PLANT':'WRNG'}])
def test_mrp_missing_or_wrong_identity_rejected(sap_h, header):
    h, sap = sap_h
    sap.stock_requirements = lambda *args, **kwargs: dict(mrp_list=header, items=[])
    result = h.client().post(URL+'/stock-requirements?material=123&plant=T001').json()
    assert result['snapshot'] is None
    assert result['refresh_error']['code'] == 'SAP_SCOPE_MISMATCH'

def test_disabled_source_is_explicit(sap_h):
    from manufacturing_platform.sap_access.errors import SapAccessError
    h, sap = sap_h
    def disabled():
        raise SapAccessError('SAP_DISABLED')
    sap.read_context = disabled
    result = h.client().get(URL+'/status').json()
    assert result['configured'] is False
    assert result['can_refresh'] is False
    assert result['refresh_error']['code'] == 'SAP_DISABLED'
    assert not sap.calls

def test_refresh_requires_csrf_and_only_five_fixed_routes(sap_h):
    h, sap = sap_h
    assert h.client().post(URL+'/production-order?number=123&plant=T001', headers={'x-csrf-token':''}).status_code == 403
    assert sap.context_calls == 0
    routes = [(path, method.upper()) for path, methods in h.app.openapi()['paths'].items() if path.startswith(URL) for method in methods]
    assert sorted(routes) == sorted([(URL+'/status','GET'), *[(URL+'/'+kind,method) for kind in ['production-order','stock-requirements'] for method in ['GET','POST']]])

def test_completion_uses_trusted_business_clock(sap_h):
    from datetime import UTC, datetime
    h, sap = sap_h
    h.business_clock = lambda: datetime(2026, 11, 13, tzinfo=UTC)
    h.reopen()
    result = h.client().post(URL+'/production-order?number=123&plant=T001').json()
    assert result['snapshot']['collected_at'] == '2026-11-13T00:00:00+00:00'

def test_deactivated_actor_during_source_read_cannot_publish(sap_h):
    h, sap = sap_h
    sap.hook = lambda: h.inactive.add('owner')
    response = h.client().post(URL+'/production-order?number=123&plant=T001')
    assert response.status_code == 403
    h.inactive.clear()
    assert h.client().get(URL+'/production-order?number=123&plant=T001').json()['snapshot'] is None

@pytest.mark.parametrize('code', ['SAP_FUNCTION_NOT_ALLOWED', 'SAP_AUTHENTICATION_FAILED', 'SAP_BUSINESS_FAILURE', 'SAP_RESULT_LIMIT_EXCEEDED'])
def test_known_source_errors_have_safe_specific_codes(sap_h, code):
    from manufacturing_platform.sap_access.errors import SapAccessError
    h, sap = sap_h
    def denied():
        raise SapAccessError(code)
    sap.hook = denied
    result = h.client().post(URL+'/production-order?number=123&plant=T001').json()
    assert result['snapshot'] is None
    assert result['refresh_error']['code'] == code

def test_post_body_rejects_first_chunk_without_reading_rest(sap_h):
    import asyncio
    from starlette.requests import Request
    h, sap = sap_h
    # Exercise the actual registered endpoint with a receive function that refuses a second read.
    from manufacturing_platform.workflow.sap_materials import register_sap_material_routes
    from manufacturing_platform.workflow.contracts import Actor
    from fastapi import APIRouter
    from types import SimpleNamespace
    router = APIRouter()
    actor = Actor(user_id=__import__('uuid').UUID('00000000-0000-4000-8000-000000000001'), display_name='owner', configuration_admin=True, read_only=False)
    service = SimpleNamespace(resolve_subject=lambda _: True, sap_access_service=sap)
    register_sap_material_routes(router, service, lambda _: actor)
    reads = []
    async def receive():
        reads.append(True)
        assert len(reads) == 1, 'must reject before accumulating the body'
        return dict(type='http.request', body=b'x', more_body=True)
    request = Request(dict(type='http', method='POST', path='/', query_string=b'number=123&plant=T001', headers=[]), receive)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as caught:
        asyncio.run(router.routes[2].endpoint(request))
    assert caught.value.status_code == 422
    assert sap.context_calls == 0

def test_config_change_while_waiting_for_final_write_keeps_previous_snapshot(sap_h, monkeypatch):
    from contextlib import contextmanager
    from manufacturing_platform.workflow.store import WorkflowStore
    h, sap = sap_h
    path = URL+'/production-order?number=123&plant=T001'
    previous = h.client().post(path).json()['snapshot']
    original_transaction = WorkflowStore.transaction
    writes = []
    @contextmanager
    def changing_transaction(store, *, write=False):
        with original_transaction(store, write=write) as tx:
            if write:
                writes.append(True)
                if len(writes) == 2:
                    sap.binding = 'changed-while-acquiring-lock'
            yield tx
    monkeypatch.setattr(WorkflowStore, 'transaction', changing_transaction)
    result = h.client().post(path).json()
    assert result['snapshot'] is None
    assert result['refresh_error']['code'] == 'SAP_CONFIGURATION_CHANGED'
    sap.binding = 'one'
    assert h.client().get(path).json()['snapshot'] == previous

@pytest.mark.parametrize('kind,query', [('production-order','number=123&plant=T001'), ('stock-requirements','material=123&plant=T001')])
def test_workflow_pins_native_read_to_observed_configuration(sap_h, kind, query):
    h, sap = sap_h
    observed = []
    original = getattr(sap, kind.replace('-', '_'))
    def pinned(*args, expected_fingerprint=None):
        observed.append(expected_fingerprint)
        return original(*args)
    setattr(sap, kind.replace('-', '_'), pinned)
    assert h.client().post(URL+'/'+kind+'?'+query).json()['snapshot']
    assert observed == ['one']

@pytest.mark.parametrize('has_previous', [False, True])
def test_postaccept_config_change_keeps_valid_source_observation(sap_h, monkeypatch, has_previous):
    from contextlib import contextmanager
    from manufacturing_platform.workflow.store import WorkflowStore
    h, sap = sap_h
    path = URL+'/production-order?number=123&plant=T001'
    previous = h.client().post(path).json()['snapshot'] if has_previous else None
    original = WorkflowStore.transaction
    writes = []
    @contextmanager
    def changing_transaction(store, *, write=False):
        with original(store, write=write) as tx:
            if write: writes.append(True)
            yield tx
            if write and len(writes) == 2:
                sap.binding = 'B-after-acceptance'
    monkeypatch.setattr(WorkflowStore, 'transaction', changing_transaction)
    result = h.client().post(path).json()
    assert result['refresh_error'] is None
    assert result['snapshot']['source'] == SOURCE
    assert result['snapshot'] != previous
    assert h.client().get(path).json()['snapshot'] is None
    sap.binding = 'one'
    assert h.client().get(path).json() == result
    assert len(writes) == 2


def test_overlapping_accepted_refreshes_keep_latest_without_retraction_chain(sap_h, monkeypatch):
    from contextlib import contextmanager
    from manufacturing_platform.workflow.store import WorkflowStore
    h, sap = sap_h
    path = URL+'/production-order?number=123&plant=T001'
    previous = h.client().post(path).json()['snapshot']
    original = WorkflowStore.transaction
    writes, later = [], []
    @contextmanager
    def interleaved_transaction(store, *, write=False):
        with original(store, write=write) as tx:
            if write: writes.append(True)
            index = len(writes)
            yield tx
        # R1 has committed S1; R2 commits S2 before R1 can finish its response.
        if write and index == 2:
            later.append(h.client().post(path).json())
        elif write and index == 4:
            sap.binding = 'B-after-both-accepted'
    monkeypatch.setattr(WorkflowStore, 'transaction', interleaved_transaction)
    first = h.client().post(path).json()
    assert first['refresh_error'] is None
    assert later[0]['refresh_error'] is None
    assert first['snapshot']['source'] == later[0]['snapshot']['source'] == SOURCE
    assert first['snapshot']['id'] != later[0]['snapshot']['id']
    assert previous['id'] not in {first['snapshot']['id'], later[0]['snapshot']['id']}
    assert h.client().get(path).json()['snapshot'] is None
    sap.binding = 'one'
    assert h.client().get(path).json() == later[0]
    assert len(writes) == 4


def test_postaccept_configuration_switch_needs_no_compensating_write(sap_h, monkeypatch):
    from contextlib import contextmanager
    from manufacturing_platform.workflow.store import WorkflowStore
    h, sap = sap_h
    original = WorkflowStore.transaction
    writes = []
    @contextmanager
    def reject_extra_writes(store, *, write=False):
        if write:
            writes.append(True)
            assert len(writes) <= 2, 'accepted observations must not trigger compensation'
        with original(store, write=write) as tx:
            yield tx
            if write and len(writes) == 2:
                sap.binding = 'B-after-acceptance'
    monkeypatch.setattr(WorkflowStore, 'transaction', reject_extra_writes)
    response = h.client().post(URL+'/production-order?number=123&plant=T001')
    assert response.status_code == 200
    assert response.json()['refresh_error'] is None
    assert response.json()['snapshot']['source'] == SOURCE


def test_mac_relay_offline_preserves_snapshot_and_read_time(sap_h):
    from manufacturing_platform.sap_access.errors import SapAccessError
    h, sap = sap_h
    path=URL+'/production-order?number=123&plant=T001'
    saved=h.client().post(path).json()['snapshot']
    def offline(*args, **kwargs):
        raise SapAccessError('SAP_RELAY_UNAVAILABLE')
    sap.production_order=offline
    result=h.client().post(path).json()
    assert result['snapshot']==saved
    assert result['refresh_error']['code']=='SAP_RELAY_UNAVAILABLE'
    assert 'Mac' in result['refresh_error']['message']
    assert h.client().get(path).json()==result
