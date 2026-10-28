import importlib
import io
from pathlib import Path
import sys
import tarfile
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]))


def archive(path,names):
    with tarfile.open(path,'w:gz') as tar:
        for name in names:
            entry=tarfile.TarInfo(name);data=b'content';entry.size=len(data);tar.addfile(entry,io.BytesIO(data))


def test_payload_extraction_never_writes_outside_private_stage(tmp_path):
    packed=tmp_path/'payload.tar.gz';archive(packed,['build/Dockerfile','../escaped'])
    stage=tmp_path/'stage';stage.mkdir()
    with pytest.raises(ValueError):importlib.import_module('install_payload').extract_payload(packed,stage)
    assert not (tmp_path/'escaped').exists() and not list(stage.iterdir())


def test_payload_rejects_duplicates_and_does_not_overwrite_existing_controller(tmp_path):
    packed=tmp_path/'payload.tar.gz';archive(packed,['release.py','release.py'])
    stage=tmp_path/'stage';stage.mkdir()
    with pytest.raises(ValueError):importlib.import_module('install_payload').extract_payload(packed,stage)
    archive(packed,['release.py']);(stage/'release.py').write_text('keep')
    with pytest.raises(ValueError):importlib.import_module('install_payload').extract_payload(packed,stage)
    assert (stage/'release.py').read_text()=='keep'


def test_regular_payload_is_extracted_with_build_paths(tmp_path):
    packed=tmp_path/'payload.tar.gz';archive(packed,['build/Dockerfile','business/manifest.json','release.py'])
    stage=tmp_path/'stage';stage.mkdir()
    importlib.import_module('install_payload').extract_payload(packed,stage)
    assert (stage/'build/Dockerfile').read_bytes()==b'content'


@pytest.fixture
def cold_installer(tmp_path, monkeypatch):
    """Use real extracted controllers, with root/stage identity confined to tmp_path."""
    import hashlib
    import json
    import os
    import subprocess

    installer=importlib.import_module('install_payload')
    stage=tmp_path/'staging'/'cold-install';stage.mkdir(parents=True,mode=0o700)
    lock=tmp_path/'lock.py';lock.write_text('# pinned lock tool\n')
    sha='a'*40;old_sha='b'*40
    backend=b'# candidate backend\n';baseline_hash=hashlib.sha256(b'# baseline backend\n').hexdigest()
    request={'mode':'upgrade','platform_commit':sha,'manufacturing_commit':sha,
             'expected_old_platform_commit':old_sha,'expected_old_manufacturing_commit':old_sha,
             'manufacturing_host':'/data/orbbec-agent-platform/manufacturing/releases/'+sha,
             'data_host':'/data/orbbec-agent-platform/manufacturing/data',
             'target_image':'orbbec-agent-platform:manufacturing-v2-'+sha[:8]+'-'+sha[:8],
             'expected_old_image':'sha256:baseline','backend_base_hashes':{'app.py':baseline_hash},
             'backend_hashes':{'app.py':hashlib.sha256(backend).hexdigest()},
             'lock_tool':str(lock),'lock_tool_sha256':hashlib.sha256(lock.read_bytes()).hexdigest()}
    saved={name:sys.modules.get(name) for name in ['release','release_support','release_guard']}
    monkeypatch.setattr(sys,'path',sys.path.copy())
    for name in saved:sys.modules.pop(name,None)
    real_stat=os.stat
    def root_stage_stat(path,*args,**kwargs):
        info=real_stat(path,*args,**kwargs)
        if os.fspath(path)==str(stage):
            fields=list(info);fields[4]=0;return os.stat_result(fields)
        return info
    monkeypatch.setattr(os,'stat',root_stage_stat)
    monkeypatch.setattr(os,'getuid',lambda:0)
    monkeypatch.setattr(installer,'Path',lambda value:stage.parent if value=='/opt/orbbec-agent-platform/staging' else Path(value))
    calls=[]
    old={'Image':request['expected_old_image'],'State':{'Health':{'Status':'healthy'}},
         'Config':{'Env':['PLATFORM_RELEASE_SHA='+old_sha,'PLATFORM_MANUFACTURING_RELEASE='+old_sha,
                          'PLATFORM_MANUFACTURING_ROOT=/opt/manufacturing',
                          'PLATFORM_MANUFACTURING_DATABASE_PATH=/app/data/manufacturing/workbench.sqlite3']},
         'Mounts':[{'Destination':'/opt/manufacturing','Type':'bind',
                    'Source':'/data/orbbec-agent-platform/manufacturing/releases/'+old_sha,'RW':False,'Propagation':'rprivate'},
                   {'Destination':'/app/data/manufacturing','Type':'bind','Source':request['data_host'],'RW':True,'Propagation':'rprivate'}],
         'HostConfig':{'Mounts':[{'Target':'/opt/manufacturing','Source':'/data/orbbec-agent-platform/manufacturing/releases/'+old_sha}]}}
    def check_output(args):
        calls.append(args)
        assert args==['docker','inspect','orbbec-agent-platform-platform-api-1']
        return json.dumps([old]).encode()
    map_output=json.dumps({'source':{'app.py':baseline_hash},'static':{}}).encode()+b'\n'
    def run(args,**kwargs):
        calls.append(args)
        assert args[:4]==['docker','exec','orbbec-agent-platform-platform-api-1','python']
        return subprocess.CompletedProcess(args,0,map_output,b'private diagnostic\n')
    monkeypatch.setattr(subprocess,'check_output',check_output)
    monkeypatch.setattr(subprocess,'run',run)
    def invoke(**overrides):
        request.update(overrides)
        packed=stage/'payload.tar.gz'
        with tarfile.open(packed,'w:gz') as tar:
            for name in ['release.py','release_support.py','release_guard.py']:
                tar.add(Path(__file__).parents[1]/name,arcname=name)
            entry=tarfile.TarInfo('build/backend/app.py');entry.size=len(backend);tar.addfile(entry,io.BytesIO(backend))
            raw=json.dumps(request).encode();entry=tarfile.TarInfo('request-template.json');entry.size=len(raw);tar.addfile(entry,io.BytesIO(raw))
        extract=installer.extract_payload
        def extract_and_observe(archive,destination):
            extract(archive,destination)
            sys.path.insert(0,str(destination))
            release=importlib.import_module('release')
            assert release.ops.STAGE is None and release.ops.SHA is None and release.ops.LOCK_TOOL is None
            def after_source_map(e):
                raise RuntimeError('source_map_validated_stop')
            monkeypatch.setattr(release,'validate_workflow_storage',after_source_map)
        monkeypatch.setattr(installer,'extract_payload',extract_and_observe)
        return installer.install(stage,hashlib.sha256(packed.read_bytes()).hexdigest())
    try:
        yield invoke,stage,request,calls,map_output
    finally:
        for name,module in saved.items():
            sys.modules.pop(name,None)
            if module is not None:sys.modules[name]=module


def test_cold_install_logs_first_source_map_privately_in_validated_stage(cold_installer):
    import stat
    invoke,stage,request,calls,map_output=cold_installer
    with pytest.raises(RuntimeError,match='^source_map_validated_stop$'):
        invoke()
    ops=sys.modules['release_support']
    assert ops.STAGE==stage and ops.SHA==request['platform_commit'] and ops.LOCK_TOOL==Path(request['lock_tool'])
    assert len(calls)==2
    stdout=list(stage.glob('operation-*.stdout.private'));stderr=list(stage.glob('operation-*.stderr.private'))
    assert len(stdout)==len(stderr)==1
    assert stdout[0].read_bytes()==map_output and stderr[0].read_bytes()==b'private diagnostic\n'
    assert all(p.parent==stage and stat.S_IMODE(p.stat().st_mode)==0o600 for p in [*stdout,*stderr])


@pytest.mark.parametrize('overrides,reason',[
    ({'platform_commit':'malformed'},'invalid_release_commit'),
    ({'target_image':'unapproved'},'unapproved_candidate_tag'),
    ({'lock_tool_sha256':'0'*64},'lock_tool_changed'),
    ({'lock_tool':'relative-lock.py'},'unsafe_path'),
])
def test_cold_install_rejects_invalid_context_before_docker(cold_installer,overrides,reason):
    invoke,stage,request,calls,map_output=cold_installer
    with pytest.raises(ValueError,match='^'+reason+'$'):
        invoke(**overrides)
    assert calls==[]
    assert not list(stage.glob('operation-*'))
