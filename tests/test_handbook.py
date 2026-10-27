import hashlib
import json
from pathlib import Path
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from manufacturing_platform.api import build_router

BASE='/api/v1/manufacturing/handbook'
PATHS={'handbook':'docs/manufacturing-system-handbook.md','workflow':'docs/workflows/manufacturing-process-overview.md'}


def setup(tmp_path,mode='edit'):
    assets=tmp_path/'webui'/'dist'; assets.mkdir(parents=True,exist_ok=True)
    metadata={'files':{}}
    for document,path in PATHS.items():
        target=tmp_path/path; target.parent.mkdir(parents=True,exist_ok=True)
        data=('标题 '+document+'\r\n\n正文\n').encode(); target.write_bytes(data)
        metadata['files'][path]={'updated_at':'2026-10-27T00:00:00+00:00','sha256':hashlib.sha256(data).hexdigest()}
    (tmp_path/'handbook-metadata.json').write_text(json.dumps(metadata))
    def authorize(request,write=False):
        if mode=='anonymous': raise HTTPException(401,'Sign in')
        return {'user_id':'id','display_name':'可信用户','read_only':True}
    app=FastAPI(); app.include_router(build_router(database_path=str(tmp_path/'db.sqlite3'),assets_dir=str(assets),authorize=authorize,release='release-123'))
    return TestClient(app),metadata


@pytest.mark.parametrize('document',PATHS)
def test_handbook_exact_bytes_digest_fixed_metadata_and_release(tmp_path,document):
    client,metadata=setup(tmp_path)
    response=client.get(BASE,params={'document':document,'release':'release-123'})
    assert response.status_code==200,response.text
    value=response.json(); path=PATHS[document]
    assert value['markdown'].encode()==(tmp_path/path).read_bytes()
    assert value['sha256']==metadata['files'][path]['sha256'] and value['updated_at']==metadata['files'][path]['updated_at']
    assert value['source_path']==path and value['release']=='release-123' and value['title']
    assert response.headers['cache-control']=='private, no-store'
    assert not (tmp_path/'db.sqlite3').exists()


def test_handbook_release_and_auth_precede_content_io(tmp_path,monkeypatch):
    from manufacturing_platform import handbook
    client,_=setup(tmp_path)
    anonymous,_=setup(tmp_path,mode='anonymous')
    def forbidden(*args,**kwargs): raise AssertionError('content I/O occurred')
    monkeypatch.setattr(handbook,'Path',forbidden)
    for params in [{'release':'old'},[('release','release-123'),('release','old')]]:
        assert client.get(BASE,params=params).status_code==409
        assert anonymous.get(BASE,params=params).status_code==401


@pytest.mark.parametrize('corrupt',['missing-metadata','bad-json','digest','missing-file','symlink','metadata-symlink'])
def test_handbook_corruption_and_escape_are_safe503(tmp_path,corrupt):
    client,metadata=setup(tmp_path); target=tmp_path/PATHS['handbook']; meta=tmp_path/'handbook-metadata.json'
    outside=tmp_path.parent/(tmp_path.name+'-secret'); outside.write_text('private secret')
    if corrupt=='missing-metadata': meta.unlink()
    elif corrupt=='bad-json': meta.write_text('{sensitive')
    elif corrupt=='digest': target.write_text('tampered secret')
    elif corrupt=='missing-file': target.unlink()
    elif corrupt=='symlink': target.unlink(); target.symlink_to(outside)
    elif corrupt=='metadata-symlink': meta.unlink(); meta.symlink_to(outside)
    response=client.get(BASE)
    assert response.status_code==503 and response.json()=={'detail':'Manufacturing storage unavailable'}
    assert response.headers['cache-control']=='private, no-store'


@pytest.mark.parametrize('document',['../../secret','unknown','/etc/passwd'])
def test_handbook_only_fixed_documents(tmp_path,document):
    client,_=setup(tmp_path)
    assert client.get(BASE,params={'document':document}).status_code==422


def test_router_construction_no_content_or_database_io(tmp_path,monkeypatch):
    from manufacturing_platform import api
    def forbidden(*args,**kwargs): raise AssertionError('router content I/O')
    # Existing catalog construction is allowed; the new handbook must be lazy.
    monkeypatch.setattr(Path,'resolve',forbidden)
    api.build_router(database_path=str(tmp_path/'uncreated'/'db'),assets_dir=str(tmp_path/'absent'),authorize=lambda request,write=False:None)
    assert not (tmp_path/'uncreated').exists()


@pytest.mark.parametrize('loop',['document','metadata','assets-root'])
@pytest.mark.parametrize('mode,expected',[('edit',503),('anonymous',401)])
def test_handbook_symlink_loops_fail_privately_after_auth(tmp_path,loop,mode,expected):
    client,_=setup(tmp_path,mode=mode)
    target={'document':tmp_path/PATHS['handbook'], 'metadata':tmp_path/'handbook-metadata.json', 'assets-root':tmp_path/'webui'/'dist'}[loop]
    if target.is_dir(): target.rmdir()
    else: target.unlink()
    target.symlink_to(target.name)
    response=TestClient(client.app,raise_server_exceptions=False).get(BASE)
    assert response.status_code==expected
    assert response.json()=={'detail':'Sign in' if expected==401 else 'Manufacturing storage unavailable'}
    assert response.headers['cache-control']=='private, no-store'
