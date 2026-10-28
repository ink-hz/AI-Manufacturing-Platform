import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]))


def module():
    import candidate_fixture
    return candidate_fixture


def test_runtime_input_rejects_host_node_unsupported_version_lock_and_tampering(tmp_path):
    m=module();root=tmp_path/'runtime';(root/'bin').mkdir(parents=True);(root/'node_modules/vitest').mkdir(parents=True)
    (root/'bin/node').write_bytes(b'ELF-fixture');(root/'node_modules/vitest/vitest.mjs').write_text('test fixture')
    data={'version':1,'platform':'linux-x64-glibc','node_version':'v24.7.0','lock_sha256':'a'*64,'files':m.file_hashes(root)}
    path=tmp_path/'runtime.json';path.write_text(json.dumps(data));pin=m.digest(path)
    assert m.validate_runtime(root,path,pin,'a'*64)==data
    for key,value in [('platform','darwin-arm64'),('node_version','v18.19.1'),('lock_sha256','b'*64)]:
        changed={**data,key:value};path.write_text(json.dumps(changed))
        with pytest.raises(ValueError):m.validate_runtime(root,path,m.digest(path),'a'*64)
    path.write_text(json.dumps(data));(root/'bin/node').write_text('drift')
    with pytest.raises(ValueError):m.validate_runtime(root,path,pin,'a'*64)


def test_exact_file_inventory_refuses_injected_and_symlink_files(tmp_path):
    m=module();(tmp_path/'a').write_text('safe');expected=m.file_hashes(tmp_path)
    (tmp_path/'extra').write_text('injected')
    with pytest.raises(ValueError):m.verify_files(tmp_path,expected)
    (tmp_path/'extra').unlink();(tmp_path/'alias').symlink_to(tmp_path/'a')
    with pytest.raises(ValueError):m.file_hashes(tmp_path)


def test_evidence_requires_owned_separate_bounded_mount_and_inode_headroom(tmp_path,monkeypatch):
    m=module();root=tmp_path/'candidate-evidence';root.mkdir(mode=0o700)
    monkeypatch.setattr(m,'mountpoint',lambda p:True)
    monkeypatch.setattr(m,'path_stat',lambda p: SimpleNamespace(st_uid=10001,st_gid=10001,st_mode=0o40700,st_dev=2) if p==root else SimpleNamespace(st_dev=1))
    stat=SimpleNamespace(f_frsize=4096,f_blocks=125000,f_bavail=120000,f_files=65536,f_favail=60000)
    monkeypatch.setattr(m.os,'statvfs',lambda p:stat)
    assert m.evidence_storage(tmp_path)['free_inodes']==60000
    stat.f_favail=30000
    with pytest.raises(ValueError):m.evidence_storage(tmp_path)
    stat.f_favail=60000;stat.f_blocks=300000
    with pytest.raises(ValueError):m.evidence_storage(tmp_path)
    stat.f_blocks=125000;monkeypatch.setattr(m,'mountpoint',lambda p:False)
    with pytest.raises(ValueError):m.evidence_storage(tmp_path)


def test_candidate_environment_commands_and_mounts_are_private_and_complete(tmp_path):
    m=module();e={'manufacturing_commit':'a'*40,'platform_commit':'b'*40,'target_image_id':'sha256:'+'c'*64}
    spec={'source_manifest_sha256':'d'*64,'a1_manifest_sha256':'e'*64,'legacy_manifest_sha256':'f'*64,'runtime_manifest_sha256':'1'*64,'fixture_sha256':'2'*64}
    args,env=m.candidate_arguments(tmp_path,e,spec)
    assert env['WORKFLOW_PLATFORM_RUNTIME_ROOT']=='/app'
    assert json.loads(env['WORKFLOW_D3_PROOF_COMMAND'])==['/usr/local/bin/python','/candidate-fixture/source/tests/workflow/d3/run_proof.py']
    assert json.loads(env['WORKFLOW_E30_COMMAND'])[0]=='/candidate-runtime/bin/node'
    assert not any(k.startswith('PLATFORM_') for k in env)
    mounts=[args[i+1] for i,v in enumerate(args) if v=='--mount']
    assert sum(not x.endswith(',readonly') for x in mounts)==1
    assert any('target=/candidate-evidence' in x for x in mounts)
    assert not any('source=/data/' in x for x in mounts)
    command=m.acceptance_command()
    assert command[-4:]==['--cases','all','--output','/candidate-evidence/runs']


def test_registry_result_must_be_exact_all36_no_skipped_or_forged_pass(tmp_path):
    m=module();ids=['F%02d'%i for i in range(1,5)]+['E%02d'%i for i in range(1,33)]
    result={'selected':ids,'statuses':{k:'passed' for k in ids},'results':[{'id':k,'status':'passed'} for k in ids]}
    assert m.validate_result(result,ids)==36
    result['statuses']['E30']='blocked'
    with pytest.raises(ValueError):m.validate_result(result,ids)
    result['statuses']['E30']='passed';result['results'].pop()
    with pytest.raises(ValueError):m.validate_result(result,ids)


def test_archive_preserves_failure_and_cleanup_requires_unchanged_receipt(tmp_path,monkeypatch):
    m=module();root=tmp_path/'candidate-evidence';root.mkdir();(root/'first-failure.json').write_text('{"failed":true}')
    monkeypatch.setattr(m,'evidence_storage',lambda *a,**kw:{'free_bytes':123,'free_inodes':456})
    receipt=m.archive_evidence(tmp_path)
    assert (root/'first-failure.json').exists() and receipt['files']['first-failure.json']==m.digest(root/'first-failure.json')
    pin=m.digest(tmp_path/'candidate-evidence-receipt.json')
    (root/'foreign').write_text('keep')
    with pytest.raises(ValueError):m.cleanup_evidence(tmp_path,pin)
    assert (root/'foreign').read_text()=='keep'
    (root/'foreign').unlink();m.cleanup_evidence(tmp_path,pin)
    assert root.is_dir() and not list(root.iterdir())


def test_workflow_candidate_requires_fixture_and_archives_failures(tmp_path,monkeypatch):
    import release
    from contextlib import nullcontext
    from test_workflow_release import CONFIG
    e={'target_workflow':CONFIG,'manufacturing_commit':'a'*40,'platform_commit':'b'*40,'manufacturing_host':'/private/business','target_image_id':'sha256:'+'c'*64,'candidate_fixture_sha256':'d'*64}
    pre={'old':{'Id':'running'},'expected_source':{},'expected_static':{}}
    (tmp_path/'candidate_verify.py').write_text('pass');(tmp_path/'candidate_fixture.py').write_text('pass')
    monkeypatch.setattr(release.ops,'STAGE',tmp_path);monkeypatch.setattr(release.ops,'Locks',lambda:nullcontext())
    monkeypatch.setattr(release.ops,'read',lambda _:pre);monkeypatch.setattr(release.ops,'inspect',lambda _:{'Id':'running'})
    monkeypatch.setattr(release,'unchanged',lambda *a:None);monkeypatch.setattr(release,'check_images',lambda *a:None)
    m=module();spec={'source_manifest_sha256':'a'*64,'a1_manifest_sha256':'b'*64,'legacy_manifest_sha256':'c'*64}
    monkeypatch.setattr(m,'validate_fixture',lambda *a:spec)
    archived=[];monkeypatch.setattr(m,'archive_evidence',lambda *a:archived.append(True) or {})
    monkeypatch.setattr(m,'evidence_storage',lambda *a,**kw:{})
    calls=[]
    def failed(args,**kw):
        calls.append((args,kw))
        if args[:3]==['docker','rm','-f']:return b''
        raise RuntimeError('first failure')
    monkeypatch.setattr(release.ops,'run',failed)
    with pytest.raises(RuntimeError):release.candidate(e)
    assert archived==[True]
    assert calls[-1][0][:3]==['docker','rm','-f']
    args=calls[0][0]
    assert 'PLATFORM_MANUFACTURING_DATASET_MODE=test' in args
    assert '/tmp:rw,noexec,nosuid,size=32m' in args
    assert 'PLATFORM_MANUFACTURING_DATASET_MODE=demo' not in args
    assert '--network' in args and args[args.index('--network')+1]=='none'


def test_export_is_exact_committed_private_source_separate_from_production(tmp_path,monkeypatch):
    import build_artifact
    from test_build_artifact import repo
    import subprocess
    m=module();repository,_,assets=repo(tmp_path)
    for name,value in {'webui/package-lock.json':'{}','webui/vite.config.ts':'export default {}','tests/workflow/private.py':'SYNTHETIC = True','scripts/run_workflow_acceptance.py':'pass','docs/testing/manufacturing-full-workflow-acceptance.md':'# Private'}.items():
        p=repository/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
    for args in [['add','.'],['commit','-qm','private fixture']]:subprocess.run(['git','-C',str(repository),*args],check=True)
    sha=subprocess.check_output(['git','-C',str(repository),'rev-parse','HEAD'],text=True).strip()
    monkeypatch.setattr(m,'HISTORY',{'a1':sha,'legacy':sha})
    business=tmp_path/'business';build_artifact.write_business_release(repository,sha,assets,business)
    runtime=tmp_path/'runtime';(runtime/'bin').mkdir(parents=True);(runtime/'node_modules/vitest').mkdir(parents=True)
    (runtime/'bin/node').write_bytes(b'fixture');(runtime/'node_modules/vitest/vitest.mjs').write_text('fixture')
    manifest=tmp_path/'runtime.json';manifest.write_text(json.dumps({'version':1,'platform':'linux-x64-glibc','node_version':'v26.5.0','lock_sha256':m.digest(repository/'webui/package-lock.json'),'files':m.file_hashes(runtime)}))
    pre={'expected_source':{k:'a'*64 for k in m.PF_OVERLAY},'old':{'Image':'sha256:'+'b'*64}}
    # An uncommitted test edit cannot enter either exported source or its hashes.
    (repository/'tests/workflow/private.py').write_text('UNREVIEWED')
    output=tmp_path/'private';pin=m.export_fixture(repository,sha,'c'*40,business,pre,runtime,manifest,m.digest(manifest),output)
    assert (output/'source/tests/workflow/private.py').read_text()=='SYNTHETIC = True'
    assert not (business/'tests').exists() and not (business/'webui/node_modules').exists()
    spec=m.pinned_json(output/'fixture.json',pin['fixture_sha256'])
    envelope=m.pinned_json(output/'source-manifest.json',spec['source_manifest_sha256'])
    assert set(envelope['platform_runtime']['files'])=={'backend/app/'+k for k in m.PF_OVERLAY}
    assert envelope['manufacturing_runtime']['files']['webui/dist/manufacturing.js']==m.digest(business/'webui/dist/manufacturing.js')
    assert not any('.git' in p.parts for p in output.rglob('*'))


def test_private_input_modes_must_allow_candidate_read_but_not_untrusted_writes(tmp_path,monkeypatch):
    m=module();root=tmp_path/'source';root.mkdir();file=root/'x';file.write_text('x')
    monkeypatch.setattr(m,'path_stat',lambda p:SimpleNamespace(st_uid=0,st_mode=p.stat().st_mode))
    root.chmod(0o555);file.chmod(0o444)
    m.validate_input_metadata(root)
    root.chmod(0o700)
    with pytest.raises(ValueError):m.validate_input_metadata(root)
    root.chmod(0o555);file.chmod(0o666)
    with pytest.raises(ValueError):m.validate_input_metadata(root)


def test_actual_workflow_bootstrap_contract_cannot_accept_unavailable_or_wrong_mode():
    m=module();calls=[]
    class Client:
        mode='test';available=True
        def get(self,path):
            calls.append(path)
            if path=='/manufacturing':return SimpleNamespace(content=b'<html>shell</html>')
            return SimpleNamespace(json=lambda:{'workflow_available':self.available,'dataset':{'id':'isolated-candidate-smoke','mode':self.mode,'label':'Synthetic candidate test'}})
    client=Client();check=lambda response,status:response
    m.verify_workflow_bootstrap(client,check)
    assert calls==['/manufacturing','/api/v1/manufacturing/workflow/access']
    client.mode='production'
    with pytest.raises(ValueError):m.verify_workflow_bootstrap(client,check)
    client.mode='test';client.available=False
    with pytest.raises(ValueError):m.verify_workflow_bootstrap(client,check)


def test_archive_headroom_is_checked_before_candidate_writes(tmp_path,monkeypatch):
    m=module();stats=SimpleNamespace(f_frsize=4096,f_bavail=1000,f_favail=20)
    monkeypatch.setattr(m.os,'statvfs',lambda p:stats)
    with pytest.raises(ValueError):m.archive_headroom(tmp_path)
    stats.f_bavail=140000
    m.archive_headroom(tmp_path)
    stats.f_favail=1
    with pytest.raises(ValueError):m.archive_headroom(tmp_path)
