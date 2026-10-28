"""Private, pinned exact-registry candidate inputs and durable bounded evidence.

No installers, mount creation, Docker calls, or production configuration here.
The controller separately verifies OCI identity; inside checks verify loaded files.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile

MAX_BYTES = 512 * 1024 * 1024
MIN_FREE_BYTES = 448 * 1024 * 1024
MIN_INODES = 65536
MIN_FREE_INODES = 50000
PF_OVERLAY = {'control_plane/auth.py','control_plane/authorization.py','control_plane/middleware.py','control_plane/routes_auth.py','main.py','manufacturing.py','manufacturing_paths.py','manufacturing_security.py'}
HISTORY = {'a1':'b7397b4c0acd2bb9d32cafade8e885e4b9e7c732','legacy':'ec41b39bdf8c0b5cc6b0193ed646a44050106ca3'}
path_stat = lambda p: p.lstat()
mountpoint = os.path.ismount


def require(value, reason):
    if not value:raise ValueError(reason)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def safe(path):
    path=Path(path)
    require(path.is_absolute() and '..' not in path.parts and not any(p.is_symlink() for p in [path,*path.parents]),'private_path_symlink_or_relative')
    return path


def file_hashes(root):
    root=safe(root);result={}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink() and (path.is_dir() or path.is_file()),'private_nonregular_input')
        if path.is_file():result[path.relative_to(root).as_posix()]=digest(path)
    return result


def verify_files(root, expected):
    require(isinstance(expected,dict) and bool(expected),'empty_private_file_map')
    require(file_hashes(root)==expected,'private_file_inventory_or_hash_mismatch')


def pinned_json(path, expected):
    path=safe(path)
    require(isinstance(expected,str) and re.fullmatch('[0-9a-f]{64}',expected) and path.stat().st_size<=16*1024*1024 and digest(path)==expected,'private_manifest_pin')
    return json.loads(path.read_text())


def validate_runtime(root, manifest, expected, lock):
    value=pinned_json(manifest,expected)
    require(set(value)=={'version','platform','node_version','lock_sha256','files'} and value['version']==1,'private_runtime_schema')
    require(value['platform']=='linux-x64-glibc' and value['lock_sha256']==lock,'private_runtime_platform_or_lock')
    match=re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)',value['node_version'])
    require(match is not None and ((int(match[1])==22 and int(match[2])>=12) or int(match[1])==24 or int(match[1])>=26),'private_node_engine')
    require({'bin/node','node_modules/vitest/vitest.mjs'}<=set(value['files']),'private_node_or_vitest_missing')
    verify_files(root,value['files'])
    return value


def evidence_storage(stage, *, fresh=True):
    root=safe(Path(stage)/'candidate-evidence');info=path_stat(root)
    require(root.is_dir() and info.st_uid==info.st_gid==10001 and stat.S_IMODE(info.st_mode)==0o700,'private_evidence_metadata')
    require(mountpoint(root) and info.st_dev!=path_stat(root.parent).st_dev,'private_evidence_dedicated_mount')
    v=os.statvfs(root)
    require(MIN_FREE_BYTES<=v.f_blocks*v.f_frsize<=MAX_BYTES and v.f_files>=MIN_INODES,'private_evidence_capacity')
    require(not fresh or (v.f_bavail*v.f_frsize>=MIN_FREE_BYTES and v.f_favail>=MIN_FREE_INODES),'private_evidence_headroom')
    require(not fresh or not any(root.iterdir()),'private_evidence_must_be_empty')
    return {'capacity_bytes':v.f_blocks*v.f_frsize,'free_bytes':v.f_bavail*v.f_frsize,'total_inodes':v.f_files,'free_inodes':v.f_favail,'device':info.st_dev,'root_inode':info.st_ino}


def archive_headroom(stage):
    value=os.statvfs(stage)
    require(value.f_bavail*value.f_frsize>=MAX_BYTES+8*1024*1024 and value.f_favail>=16,'private_archive_headroom')


def candidate_arguments(stage,e,spec):
    stage=Path(stage)
    args=[]
    for source,target,readonly in [('candidate-fixture','/candidate-fixture',True),('candidate-runtime','/candidate-runtime',True),('candidate-runtime/node_modules','/candidate-fixture/source/webui/node_modules',True),('candidate-evidence','/candidate-evidence',False)]:
        args+=['--mount',f'type=bind,source={stage/source},target={target}'+(',readonly' if readonly else '')]
    env={'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':'/app/backend:/opt/manufacturing/src',
         'HOME':'/candidate-evidence/home','XDG_CACHE_HOME':'/candidate-evidence/cache',
         'WORKFLOW_SOURCE_MANIFEST':'/candidate-fixture/source-manifest.json',
         'WORKFLOW_SOURCE_MANIFEST_SHA256':spec['source_manifest_sha256'],
         'WORKFLOW_MANUFACTURING_RUNTIME_ROOT':'/opt/manufacturing','WORKFLOW_PLATFORM_RUNTIME_ROOT':'/app',
         'WORKFLOW_E30_COMMAND':json.dumps(['/candidate-runtime/bin/node','/candidate-fixture/source/webui/node_modules/vitest/vitest.mjs','--config','/candidate-evidence/vitest.config.mjs']),
         'WORKFLOW_D3_PROOF_COMMAND':json.dumps(['/usr/local/bin/python','/candidate-fixture/source/tests/workflow/d3/run_proof.py'])}
    for name in HISTORY:
        prefix='WORKFLOW_'+name.upper()+'_SOURCE'
        env.update({prefix+'_ROOT':'/candidate-fixture/'+name,prefix+'_MANIFEST':'/candidate-fixture/'+name+'-manifest.json',prefix+'_MANIFEST_SHA256':spec[name+'_manifest_sha256']})
    return args,env


def acceptance_command():
    return ['/usr/local/bin/python','/candidate-fixture/source/scripts/run_workflow_acceptance.py','--cases','all','--output','/candidate-evidence/runs']


def validate_result(value, ids):
    require(len(ids)==36 and len(set(ids))==36,'private_registry_size')
    require(value['selected']==list(ids) and value['statuses']=={k:'passed' for k in ids},'private_all36_required')
    require(len(value['results'])==36 and {row['id']:row['status'] for row in value['results']}==value['statuses'],'private_all36_results')
    return 36


def export_fixture(repo, sha, platform_sha, business, preflight, runtime, runtime_manifest, runtime_pin, output):
    """Local exact-commit export. Runtime/dependencies are prepared separately, never installed."""
    from build_artifact import export_paths,git
    output=safe(output);require(not output.exists(),'private_export_exists')
    require(all(re.fullmatch('[0-9a-f]{40}',s) for s in [sha,platform_sha]),'private_export_commit')
    lock=hashlib.sha256(git(repo,'show',sha+':webui/package-lock.json')).hexdigest()
    validate_runtime(runtime,runtime_manifest,runtime_pin,lock)
    source_map=preflight['expected_source']
    require(PF_OVERLAY<=set(source_map),'private_complete_pf_overlay_required')
    output.mkdir(mode=0o700);source=output/'source';source.mkdir()
    export_paths(repo,sha,source,['src','webui','tests/workflow','scripts/run_workflow_acceptance.py','docs/manufacturing-system-handbook.md','docs/testing/manufacturing-full-workflow-acceptance.md'])
    require(not (source/'webui/node_modules').exists(),'private_dependency_tree_in_source')
    (source/'webui/node_modules').mkdir()
    published=json.loads((Path(business)/'manifest.json').read_text())
    require(published['commit']==sha,'private_business_commit')
    for name in ['webui/dist/manufacturing.js','webui/dist/manufacturing.css']:
        path=Path(business)/name;require(digest(path)==published['files'][name],'private_business_asset_hash')
        target=source/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    files=file_hashes(source);build={k:files.pop(k) for k in ['webui/dist/manufacturing.js','webui/dist/manufacturing.css']}
    mf={k:v for k,v in files.items() if k.startswith('src/') or k=='docs/manufacturing-system-handbook.md'};mf.update(build)
    require(all(published['files'].get(k)==v and digest(Path(business)/k)==v for k,v in mf.items()),'private_business_runtime_mismatch')
    provenance={'provenance_kind':'live_git','manufacturing_commit':sha,'platform_commit':platform_sha,
                'manufacturing_tree':'Exact committed export; no live-worktree cleanliness assertion',
                'platform_tree':'Applicable runtime files only; unrelated baseline image patches retained',
                'dependency_symlink':None,'release_hash':hashlib.sha256(json.dumps({'files':files,'build_files':build},sort_keys=True).encode()).hexdigest(),
                'files':files,'build_files':build,'roots':{'manufacturing':str(Path(repo).resolve()),'platform':'/app'},'business_source_root':'/opt/manufacturing/src'}
    envelope={'version':1,'source':provenance,'manufacturing_runtime':{'files':mf},'platform_runtime':{'target_commit':platform_sha,'baseline_image':preflight['old']['Image'],'approved_overlay':platform_sha,'files':{'backend/app/'+k:v for k,v in source_map.items()}}}
    (output/'source-manifest.json').write_text(json.dumps(envelope,sort_keys=True))
    for name,commit in HISTORY.items():
        root=output/name;root.mkdir();export_paths(repo,commit,root,['src'])
        (output/(name+'-manifest.json')).write_text(json.dumps({'version':1,'commit':commit,'files':file_hashes(root)},sort_keys=True))
    shutil.copyfile(runtime_manifest,output/'runtime-manifest.json')
    controller=output/'controller.py'
    controller.write_bytes(git(repo,'show',sha+':deploy/candidate_fixture.py'))
    controller.chmod(0o444)
    spec={'version':1,'manufacturing_commit':sha,'platform_commit':platform_sha,'baseline_image':preflight['old']['Image'],
          'source_manifest_sha256':digest(output/'source-manifest.json'),'runtime_manifest_sha256':runtime_pin,
          **{name+'_manifest_sha256':digest(output/(name+'-manifest.json')) for name in HISTORY},'files':file_hashes(output)}
    (output/'fixture.json').write_text(json.dumps(spec,sort_keys=True))
    return {'fixture_sha256':digest(output/'fixture.json')}


def validate_input_metadata(tree):
    for path in [tree,*tree.rglob('*')]:
        info=path_stat(path)
        required=0o005 if path.is_dir() else 0o004
        require(info.st_uid==0 and not info.st_mode&0o022 and info.st_mode&required==required,'private_input_trusted_readable_metadata')


def validate_controller(stage,files):
    stage=Path(stage);controller=safe(stage/'candidate-fixture/controller.py')
    require(controller.is_file() and files.get('controller.py')==digest(controller)==digest(safe(stage/'candidate_fixture.py')),'private_controller_hash')
    validate_input_metadata(controller)
    return controller


def validate_fixture(stage,e,pre):
    stage=Path(stage);root=safe(stage/'candidate-fixture')
    spec=pinned_json(root/'fixture.json',e['candidate_fixture_sha256'])
    require(set(spec)=={'version','manufacturing_commit','platform_commit','baseline_image','source_manifest_sha256','runtime_manifest_sha256','a1_manifest_sha256','legacy_manifest_sha256','files'} and spec['version']==1,'private_fixture_schema')
    require(spec['manufacturing_commit']==e['manufacturing_commit'] and spec['platform_commit']==e['platform_commit'] and spec['baseline_image']==pre['old']['Image'],'private_fixture_release_binding')
    observed=file_hashes(root);observed.pop('fixture.json')
    require(observed==spec['files'],'private_fixture_inventory')
    validate_controller(stage,spec['files'])
    envelope=pinned_json(root/'source-manifest.json',spec['source_manifest_sha256'])
    require(envelope['platform_runtime']['files']=={'backend/app/'+k:v for k,v in pre['expected_source'].items()} and PF_OVERLAY<=set(pre['expected_source']),'private_fixture_runtime_binding')
    require(envelope['source']['manufacturing_commit']==e['manufacturing_commit'] and envelope['source']['platform_commit']==e['platform_commit'],'private_fixture_source_binding')
    validate_runtime(stage/'candidate-runtime',root/'runtime-manifest.json',spec['runtime_manifest_sha256'],digest(root/'source/webui/package-lock.json'))
    for name,commit in HISTORY.items():
        historical=pinned_json(root/(name+'-manifest.json'),spec[name+'_manifest_sha256'])
        require(historical['commit']==commit,'private_historical_commit')
        verify_files(root/name,historical['files'])
    for tree in [root,stage/'candidate-runtime']:validate_input_metadata(tree)
    require((stage/'candidate-runtime/bin/node').stat().st_mode&0o001,'private_node_executable')
    evidence_storage(stage)
    archive_headroom(stage)
    spec['fixture_sha256']=e['candidate_fixture_sha256']
    return spec


def verify_workflow_bootstrap(client,check):
    require(bool(check(client.get('/manufacturing'),200).content),'private_actual_shell_missing')
    access=check(client.get('/api/v1/manufacturing/workflow/access'),200).json()
    require(access['workflow_available'] is True and access['dataset']=={'id':'isolated-candidate-smoke','mode':'test','label':'Synthetic candidate test'},'private_actual_workflow_bootstrap')


def run_acceptance():
    """Inside the isolated candidate after the existing app/assets/legacy smoke."""
    require(os.getuid()==os.getgid()==10001,'private_candidate_uid')
    for path in ['/candidate-fixture','/candidate-runtime','/candidate-fixture/source/webui/node_modules','/opt/manufacturing']:
        require(os.statvfs(path).f_flag & os.ST_RDONLY,'private_fixture_mount_must_be_readonly')
    root=Path('/candidate-evidence');require(not (root/'runs').exists(),'private_candidate_must_be_fresh')
    for name in ['home','cache','vite-cache']: (root/name).mkdir()
    (root/'vitest.config.mjs').write_text("import original from '/candidate-fixture/source/webui/vite.config.ts';\nexport default (ctx) => {const config=original(ctx);return {...config,cacheDir:'/candidate-evidence/vite-cache',test:{...config.test,fsModuleCachePath:'/candidate-evidence/vitest-module-cache'}};};\n")
    runtime=json.loads(Path('/candidate-fixture/runtime-manifest.json').read_text())
    require(subprocess.check_output(['/candidate-runtime/bin/node','--version'],text=True).strip()==runtime['node_version'],'private_actual_node_version')
    sys.path.insert(0,'/candidate-fixture/source/tests')
    from workflow.scenarios import CASE_IDS
    from workflow.scenarios.provenance import source_manifest
    source_manifest(Path('/candidate-fixture/source'))
    import platform,sqlite3,importlib.metadata
    versions={'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,**{n:importlib.metadata.version(n) for n in ['starlette','fastapi','pydantic','httpx','uvicorn','cryptography']},'node':runtime['node_version']}
    (root/'runtime.json').write_text(json.dumps(versions,sort_keys=True))
    # Actual overlaid member-profile method, with only its database transport synthetic.
    from app.control_plane.auth import WebSessionRepository
    from uuid import UUID
    uid=UUID('11111111-1111-4111-8111-111111111111');calls=[]
    class Connection:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def execute(self,sql,args):calls.append((sql,args));return self
        def fetchall(self):return [{'internal_user_id':uid,'display_name':'Synthetic candidate member'}]
    repository=object.__new__(WebSessionRepository);repository._connection=lambda:Connection()
    require(repository.active_internal_user_profiles([uid])==[{'user_id':str(uid),'display_name':'Synthetic candidate member'}] and len(calls)==1,'private_actual_profile_repository')
    with (root/'all36.stdout.log').open('xb') as out,(root/'all36.stderr.log').open('xb') as err:
        completed=subprocess.run(acceptance_command(),stdout=out,stderr=err,timeout=3600)
    reports=list((root/'runs').glob('*/run.json'))
    require(completed.returncode==0 and len(reports)==1,'private_exact36_failed_see_durable_evidence')
    count=validate_result(json.loads(reports[0].read_text()),CASE_IDS)
    return {'passed':True,'cases':count,'scope':'Synthetic identity, stateful mock authority, actual candidate dependencies; not production business acceptance','runtime':versions}


def archive_evidence(stage):
    """Preserve failure evidence; no cleanup is implicit, including on failed runs."""
    stage=Path(stage);root=stage/'candidate-evidence';usage=evidence_storage(stage,fresh=False)
    files=file_hashes(root);usage.update(logical_bytes=sum(p.stat().st_size for p in root.rglob('*') if p.is_file()),allocated_bytes=sum(p.stat().st_blocks*512 for p in root.rglob('*')),files=len(files))
    archive=stage/'candidate-evidence.tar.gz'
    require(not archive.exists(),'private_evidence_archive_exists')
    with tarfile.open(archive,'x:gz') as output:
        for name in files:output.add(root/name,arcname=name,recursive=False)
    archive.chmod(0o600)
    receipt={'archive':archive.name,'sha256':digest(archive),'files':files,'usage':usage}
    with (stage/'candidate-evidence-receipt.json').open('x') as out:json.dump(receipt,out,sort_keys=True)
    (stage/'candidate-evidence-receipt.json').chmod(0o600)
    return receipt


def cleanup_evidence(stage, receipt_sha256):
    """Explicit operator action only; retain mount and ownership, remove verified contents."""
    stage=Path(stage);receipt=pinned_json(stage/'candidate-evidence-receipt.json',receipt_sha256)
    require(receipt['archive']=='candidate-evidence.tar.gz' and digest(safe(stage/receipt['archive']))==receipt['sha256'],'private_archive_changed')
    current=evidence_storage(stage,fresh=False);root=stage/'candidate-evidence'
    require(all(current[key]==receipt['usage'].get(key) for key in ['device','root_inode']),'private_evidence_root_changed')
    # An early candidate failure can legitimately leave no files. This exception
    # applies only to pinned evidence cleanup, never source/runtime validation.
    require(isinstance(receipt['files'],dict) and file_hashes(root)==receipt['files'],'private_evidence_inventory_changed')
    for path in sorted(root.rglob('*'),key=lambda p:len(p.parts),reverse=True):
        if path.is_dir():path.chmod(0o700);path.rmdir()
        else:path.unlink()
