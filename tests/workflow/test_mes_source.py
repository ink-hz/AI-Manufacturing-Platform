"""Source-only observations through the real private workflow router."""
import sqlite3
import pytest
from . import conftest
from .conftest import BASE
from .test_sap_materials import Sap

URL = BASE + '/material-control/mes-source'
SOURCE = dict(system='mes', origin='native', environment='test', site_code='TEST', namespace='isolated')

class Mes(Sap):
    def read_context(self):
        self.context_calls += 1
        return dict(source=SOURCE, fingerprint=self.binding)
    def source_orders(self, prefix, after, actor_id, *, expected_fingerprint=None):
        self.calls.append((prefix, after, actor_id, expected_fingerprint))
        if self.hook: self.hook()
        if self.error: raise RuntimeError('private secret')
        return dict(items=[dict(shop_order='ORDER1', description='Order')], next_cursor=None, total=None, page_size=5)
    def collect_order_materials(self, shop_order, actor_id, *, expected_fingerprint=None):
        return dict(components=[dict(material_id='MAT1', required_quantity='1.2300')], total=1)
    def query(self, interface, filters, page, page_size, actor_id, *, expected_fingerprint=None):
        self.calls.append((interface, filters, page, page_size, actor_id, expected_fingerprint))
        return dict(rows=[dict(SHOP_ORDER='ORDER1', MATNR='MAT1')] if interface=='material_priority' else [dict(ITEM_NO='MAT1')], total_items=1)

@pytest.fixture
def mes_h(workflow, monkeypatch):
    mes = Mes()
    original = conftest.build_workflow_router
    monkeypatch.setattr(conftest, 'build_workflow_router', lambda **kw: original(**kw, mes_access_service=mes))
    workflow.reopen()
    return workflow, mes

def test_status_no_source(workflow):
    assert workflow.client().get(URL+'/status').json() == dict(configured=False,source=None,can_refresh=False)

@pytest.mark.parametrize('route', ['/orders?prefix=&after=', '/order-materials?shop_order=ORDER1', '/priority?shop_order=ORDER1&material=MAT1&page=1', '/iqc?material=MAT1&page=1'])
def test_zero_projects_refresh_cache(mes_h, route):
    h, mes = mes_h
    assert h.client().get(URL+route).json() == dict(snapshot=None, refresh_error=None)
    assert not mes.calls
    response = h.client().post(URL+route)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['snapshot']['source'] == SOURCE
    assert result['refresh_error'] is None
    assert h.client().get(URL+route).json() == result
    assert 'fingerprint' not in response.text
    with sqlite3.connect(h.paths.domain) as db:
        assert db.execute('select count(*) from projects').fetchone()[0] == 0
        assert db.execute('select count(*) from work_orders').fetchone()[0] == 0
        assert db.execute('select count(*) from requirements').fetchone()[0] == 0

def test_failure_binding_and_authority(mes_h):
    h, mes = mes_h
    path = URL+'/orders?prefix=&after='
    original = h.client().post(path).json()['snapshot']
    mes.error = True
    failed = h.client().post(path).json()
    assert failed['snapshot'] == original
    assert failed['refresh_error']['code'] == 'MES_REFRESH_FAILED'
    assert 'secret' not in str(failed)
    mes.binding='two'
    assert h.client().get(path).json()['snapshot'] is None
    mes.hook=lambda: setattr(mes,'binding','three')
    assert h.client().post(path).json()['snapshot'] is None
    for actor in ['outsider','planner']:
        assert h.client(actor).get(URL+'/status').status_code == 403
    h.read_only.add('owner')
    assert h.client().get(URL+'/status').json()['can_refresh'] is False
    assert h.client().post(path).status_code == 403
    h.inactive.add('owner')
    assert h.client().get(URL+'/status').status_code == 403

@pytest.mark.parametrize('route', ['/orders?prefix=', '/orders?prefix=&after=&extra=x', '/orders?prefix=&prefix=&after=', '/orders?prefix=*&after=', '/priority?shop_order=A&material=B&page=0', '/iqc?material=B&page=01', '/order-materials?shop_order=', '/status?x=1'])
def test_exact_scope(mes_h, route):
    h, mes = mes_h
    assert h.client().post(URL+route).status_code in (422,405)
    assert not mes.calls

def test_no_body_csrf_and_migration(mes_h):
    h, mes = mes_h
    path=URL+'/orders?prefix=&after='
    assert h.client().post(path, content='{}').status_code == 422
    assert h.client().post(path, headers={'x-csrf-token':''}).status_code == 403
    assert h.client().post(path).status_code == 200
    with sqlite3.connect(h.paths.domain) as db:
        db.execute('drop table if exists mes_source_observations')
        db.execute('update schema_version set version=29')
    h.reopen()
    assert h.client().post(path).status_code == 200
    with sqlite3.connect(h.paths.domain) as db:
        assert db.execute('select version from schema_version').fetchone()[0] == 30

def test_native_scope_contract_preserved(mes_h):
    h, mes=mes_h
    assert h.client().get(URL+'/orders',params={'prefix':'ORDER 1','after':''}).status_code==200
    assert h.client().get(URL+'/iqc',params={'material':'M'*128,'page':1000000}).status_code==200


def test_concurrent_sequence_and_network_outside_transaction(mes_h):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    h,mes=mes_h
    entered,release=Event(),Event()
    def hook():
        with sqlite3.connect(h.paths.domain,timeout=0.1) as db:
            db.execute('UPDATE mes_source_observations SET refresh_seq=refresh_seq')
        if len(mes.calls)==1:
            entered.set()
            assert release.wait(10)
    mes.hook=hook
    path=URL+'/orders?prefix=&after='
    with ThreadPoolExecutor(2) as pool:
        old=pool.submit(lambda:h.client().post(path).json())
        assert entered.wait(10)
        newer=h.client().post(path).json()
        release.set()
        result=old.result()
    assert result['snapshot']==newer['snapshot']
    assert result['refresh_error']['code']=='MES_REFRESH_SUPERSEDED'
    assert h.client().get(path).json()==newer


def test_wrong_query_identity_rejected(mes_h):
    h,mes=mes_h
    mes.query=lambda *a,**k:dict(rows=[dict(SHOP_ORDER='OTHER',MATNR='MAT1')])
    result=h.client().post(URL+'/priority?shop_order=ORDER1&material=MAT1&page=1').json()
    assert result['snapshot'] is None
    assert result['refresh_error']['code']=='MES_SCOPE_MISMATCH'


def test_offline_and_configuration_errors_are_safe(mes_h):
    from manufacturing_platform.mes_access.errors import MesAccessError
    h,mes=mes_h
    path=URL+'/orders?prefix=&after='
    original=h.client().post(path).json()['snapshot']
    def offline(*args,**kwargs):
        raise MesAccessError('MES_RELAY_UNAVAILABLE')
    mes.source_orders=offline
    result=h.client().post(path).json()
    assert result['snapshot']==original
    assert result['refresh_error']['code']=='MES_RELAY_UNAVAILABLE'
    assert '离线' in result['refresh_error']['message']
    assert h.client().get(path).json()==result
    def broken(): raise RuntimeError('/private/secret/config')
    mes.read_context=broken
    status=h.client().get(URL+'/status').json()
    assert status['configured'] is False
    assert status['can_refresh'] is False
    assert status['refresh_error']['code']=='MES_CONFIGURATION_ERROR'
    assert 'secret' not in str(status)


def test_configuration_change_during_success_never_accepts_old_binding(mes_h):
    h,mes=mes_h
    path=URL+'/orders?prefix=&after='
    mes.hook=lambda:setattr(mes,'binding','two')
    result=h.client().post(path).json()
    assert result['snapshot'] is None
    assert result['refresh_error']['code']=='MES_CONFIGURATION_CHANGED'
    mes.binding='one'
    assert h.client().get(path).json()==dict(snapshot=None,refresh_error=None)


@pytest.mark.parametrize('route,params', [
    ('orders', {'prefix':'WO','after':'WO_5'}),
    ('order-materials', {'shop_order':'WO_5'}),
    ('priority', {'shop_order':'WO_5','material':'MAT1','page':1}),
])
def test_exact_order_cursor_scope_accepts_underscore(mes_h, route, params):
    h, mes = mes_h
    assert h.client().get(URL+'/'+route, params=params).status_code == 200


@pytest.mark.parametrize('route,params', [
    ('orders', {'prefix':'WO_','after':''}),
    ('orders', {'prefix':'','after':'W'*65}),
    ('order-materials', {'shop_order':'W'*65}),
])
def test_prefix_underscore_and_overlong_order_denied(mes_h, route, params):
    h, mes = mes_h
    assert h.client().get(URL+'/'+route, params=params).status_code == 422
