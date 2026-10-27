from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from manufacturing_platform.api import build_router

BASE = '/api/v1/manufacturing'
STAGE = BASE + '/lines/cameras/stages/S1'


def make_client(tmp_path, *, mode='edit', database_path=None, asynchronous=False):
    calls = []
    def authorize(request, write=False):
        calls.append(write)
        if mode == 'anonymous':
            raise HTTPException(401, 'Sign in')
        if mode == 'denied':
            raise HTTPException(403, 'Forbidden')
        if mode == 'stale' and write:
            raise HTTPException(503, 'Directory unavailable')
        return {'user_id':'trusted-id', 'display_name':'可信用户', 'read_only':mode=='read'}
    async def async_authorize(request, write=False):
        return authorize(request, write=write)
    assets = tmp_path / 'assets'
    assets.mkdir(exist_ok=True)
    (assets / 'manufacturing.js').write_text('window.OrbbecManufacturing={};')
    (assets / 'manufacturing.css').write_text('.mf-root {}')
    app = FastAPI()
    app.include_router(build_router(database_path=str(database_path or tmp_path / 'db' / 'workbench.sqlite3'), assets_dir=str(assets), authorize=async_authorize if asynchronous else authorize, release='release-123'))
    return TestClient(app), calls


def payload(**changes):
    return {'expected_version':0, 'practice':'待核实', 'participants':[], 'handoffs':[], 'systems':[], **changes}


def test_exact_access_catalog_empty_line_and_health_contract(tmp_path):
    client, calls = make_client(tmp_path, asynchronous=True)
    access = client.get(BASE + '/access')
    assert access.json() == {'allowed':True,'can_edit':True,'available':True,'release':'release-123'}
    catalog = client.get(BASE + '/catalog').json()
    assert set(catalog) == {'groups','lines','stages','can_edit','release'}
    stage = client.get(STAGE).json()
    assert set(stage) == {'line','stage','record','tasks','can_edit'}
    assert stage['record']['version'] == 0 and stage['tasks'] == []
    line = client.get(BASE + '/lines/cameras').json()
    assert len(line['stages']) == 9
    assert all(not s['recorded'] and s['open_tasks'] == 0 for s in line['stages'])
    assert client.get(BASE + '/health').json() == {'ready':True,'release':'release-123'}
    assert all(write is False for write in calls)
    assert access.headers['cache-control'] == 'private, no-store'


def test_stage_relationship_save_conflict_task_and_truthful_overview(tmp_path):
    client, calls = make_client(tmp_path)
    body = payload(participants=[{'name':'供应商','role':'供料','responsibility':'待访谈'}], handoffs=[{'name':'工程 BOM','from_party':'客户','to_party':'工程','version_reference':'待确认','notes':''}], systems=[{'name':'已有系统','kind':'ERP','objects':'物料','maintainer':'待确认','method':'api','notes':'关系登记'}])
    saved = client.put(STAGE,json=body)
    assert saved.status_code == 200
    assert saved.json()['systems'] == body['systems']
    assert saved.json()['updated_by'] == '可信用户'
    assert client.put(STAGE,json=body).status_code == 409
    task = client.post(STAGE+'/tasks',json={'title':'  访谈  ','operation_id':str(uuid4())}).json()
    assert task['title'] == '访谈' and set(task) == {'id','title','completed','version','created_at','updated_at','updated_by'}
    assert client.patch(STAGE+'/tasks/'+task['id'],json={'title':'访谈','completed':True,'expected_version':1}).json()['completed'] is True
    assert client.patch(STAGE+'/tasks/'+task['id'],json={'title':'访谈','completed':False,'expected_version':1}).status_code == 409
    assert client.patch(BASE+'/lines/oem/stages/S1/tasks/'+task['id'],json={'title':'访谈','completed':False,'expected_version':2}).status_code == 404
    assert client.put(STAGE,json=payload(practice='',expected_version=1,systems=body['systems'])).status_code == 200
    assert client.get(BASE+'/lines/cameras').json()['stages'][0]['recorded'] is False
    assert client.get(BASE+'/lines/oem/stages/S1').json()['record']['version'] == 0
    assert True in calls


@pytest.mark.parametrize('mode,status',[('anonymous',401),('denied',403)])
def test_auth_precedes_malformed_validation_database_and_assets(tmp_path,mode,status):
    client, _ = make_client(tmp_path, mode=mode, database_path=tmp_path / 'forbidden' / 'db')
    for response in [client.get(STAGE),client.put(STAGE,content='{sensitive invalid',headers={'content-type':'application/json'}),client.get(BASE+'/assets/manufacturing.js'),client.get(BASE+'/health')]:
        assert response.status_code == status
        assert 'sensitive' not in response.text
        assert response.headers['cache-control'] == 'private, no-store'
    assert not (tmp_path / 'forbidden').exists()


@pytest.mark.parametrize('mode,status',[('read',403),('stale',503)])
def test_read_only_and_hard_stale_allow_reads_prevent_writes(tmp_path,mode,status):
    client, _ = make_client(tmp_path, mode=mode)
    assert client.get(STAGE).status_code == 200
    if mode == 'read':
        assert client.get(BASE+'/access').json()['can_edit'] is False
    assert client.put(STAGE,json=payload()).status_code == status
    assert client.post(STAGE+'/tasks',json={'title':'x','operation_id':str(uuid4())}).status_code == status


@pytest.mark.parametrize('changes', [ {'practice':'x'*12001}, {'practice':['secret']}, {'expected_version':-1}, {'expected_version':True}, {'extra':'secret'}, {'participants':[{'name':' '} ]}, {'participants':[{'name':'secret','extra':'x'}]}, {'participants':[{'name':'x'}]*21}, {'participants':[{'name':'x','role':'a'*501}]}, {'handoffs':[{'name':'x','notes':['secret']}]}, {'systems':[{'name':'x','method':'connected'}]}, {'systems':None} ])
def test_validation_is_fixed_and_never_echoes_business_input(tmp_path,changes):
    client, _ = make_client(tmp_path)
    response = client.put(STAGE,json=payload(**changes))
    assert response.status_code == 422
    assert response.json() == {'detail':'Invalid request'}
    assert response.headers['cache-control'] == 'private, no-store'


@pytest.mark.parametrize('body',[{'title':' ','operation_id':str(uuid4())},{'title':'x'*301,'operation_id':str(uuid4())},{'title':'secret','operation_id':'bad'},{'title':'secret','operation_id':str(uuid4()),'extra':'x'}])
def test_task_validation(tmp_path,body):
    client, _ = make_client(tmp_path)
    assert client.post(STAGE+'/tasks',json=body).json() == {'detail':'Invalid request'}


def test_unknown_scope_assets_and_database_failure_are_safe(tmp_path):
    client, _ = make_client(tmp_path)
    for path in ['/lines/missing','/lines/cameras/stages/missing','/assets/index.html','/assets/no.js']:
        response = client.get(BASE+path)
        assert response.status_code == 404 and response.headers['cache-control'] == 'private, no-store'
    for name, mime in [('manufacturing.js','text/javascript'),('manufacturing.css','text/css')]:
        response = client.get(BASE+'/assets/'+name)
        assert response.status_code == 200 and response.headers['content-type'].startswith(mime)
        assert response.headers['cache-control'] == 'private, no-store'
    (tmp_path/'assets'/'manufacturing.js').unlink()
    assert client.get(BASE+'/assets/manufacturing.js').status_code == 404
    corrupt = tmp_path / 'corrupt.sqlite3'
    corrupt.write_text('sensitive database path or business data')
    broken, _ = make_client(tmp_path,database_path=corrupt)
    for response in [broken.get(STAGE),broken.put(STAGE,json=payload()),broken.get(BASE+'/health')]:
        assert response.status_code == 503
        assert response.json() == {'detail':'Manufacturing storage unavailable'}
        assert 'sensitive' not in response.text and str(tmp_path) not in response.text


def test_boundary_lengths_and_missing_optional_relation_fields_round_trip(tmp_path):
    client, _ = make_client(tmp_path)
    body = payload(practice='x'*12000, participants=[{'name':'x'*500}]*20, handoffs=[{'name':'BOM'}],systems=[{'name':'ERP'}])
    response = client.put(STAGE,json=body)
    assert response.status_code == 200
    saved = response.json()
    assert len(saved['participants']) == 20
    assert saved['participants'][0] == {'name':'x'*500,'role':'','responsibility':''}
    assert saved['handoffs'][0] == {'name':'BOM','from_party':'','to_party':'','version_reference':'','notes':''}
    assert saved['systems'][0] == {'name':'ERP','kind':'','objects':'','maintainer':'','method':'unknown','notes':''}
    assert client.get(STAGE).json()['record'] == saved


def test_config_rename_preserves_record_and_disabled_scopes_return_404(tmp_path,monkeypatch):
    from manufacturing_platform import api
    from manufacturing_platform.catalog import Catalog, load_catalog
    client, _ = make_client(tmp_path)
    saved = client.put(STAGE,json=payload()).json()
    data = load_catalog().definition.model_dump()
    data['lines'][0].update(name='相机新名称',order=99,group_id='external')
    data['lines'][1]['enabled'] = False
    data['stages'][1]['enabled'] = False
    monkeypatch.setattr(api,'load_catalog',lambda:Catalog(data))
    reconfigured, _ = make_client(tmp_path)
    response = reconfigured.get(STAGE).json()
    assert response['line']['name'] == '相机新名称'
    assert response['record'] == saved
    for path in ['/lines/3d-printers','/lines/3d-printers/stages/S1','/lines/cameras/stages/S2']:
        assert reconfigured.get(BASE+path).status_code == 404
    assert 'S2' not in [s['id'] for s in reconfigured.get(BASE+'/lines/cameras').json()['stages']]


def test_asset_symlinks_cannot_escape_assets_directory(tmp_path):
    client, _ = make_client(tmp_path)
    target = tmp_path/'assets'/'manufacturing.js'
    target.unlink()
    secret = tmp_path/'outside.js'
    secret.write_text('secret')
    target.symlink_to(secret)
    response = client.get(BASE+'/assets/manufacturing.js')
    assert response.status_code == 404 and 'secret' not in response.text


def test_corrupted_persisted_read_model_fails_safely(tmp_path):
    import sqlite3
    client, _ = make_client(tmp_path)
    client.put(STAGE,json=payload())
    with sqlite3.connect(tmp_path/'db'/'workbench.sqlite3') as db:
        db.execute("UPDATE stage_records SET body=?", ('{"practice":["sensitive"]}',))
    response = client.get(STAGE)
    assert response.status_code == 503
    assert response.json() == {'detail':'Manufacturing storage unavailable'}


def test_unknown_scope_never_initializes_database_and_no_delete_endpoint(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.get(BASE+'/lines/missing/stages/S1').status_code == 404
    assert not (tmp_path/'db').exists()
    assert client.delete(STAGE).status_code == 405


@pytest.mark.parametrize('body', [ {'title':'secret','completed':'true','expected_version':1}, {'title':'secret','completed':True,'expected_version':0}, {'title':'secret','completed':True,'expected_version':1,'extra':'x'} ])
def test_patch_validation_is_fixed(tmp_path,body):
    client, _ = make_client(tmp_path)
    response = client.patch(STAGE+'/tasks/unknown',json=body)
    assert response.status_code == 422
    assert response.json() == {'detail':'Invalid request'}
