"""Install a pinned private payload and build a COPY-only image; never cut over."""
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

TOP={'business','build','release.py','release_support.py','release_guard.py','candidate_verify.py','candidate_fixture.py','sqlite_backup.py','native_release.py','request-template.json'}


def require(condition,reason):
    if not condition:raise ValueError(reason)


def extract_payload(archive_path,stage):
    with tarfile.open(archive_path) as archive:
        entries=archive.getmembers();seen=set()
        for entry in entries:
            name=Path(entry.name)
            require(not name.is_absolute() and '..' not in name.parts and name.parts and name.parts[0] in TOP,'unsafe_payload_path')
            require(entry.isfile() or entry.isdir(),'payload_nonregular')
            require(name.as_posix() not in seen,'duplicate_payload_entry');seen.add(name.as_posix())
            require(not (stage/name).exists() and not (stage/name).is_symlink(),'payload_target_exists')
        for entry in entries:
            destination=stage/entry.name
            if entry.isdir():destination.mkdir(parents=True,exist_ok=True,mode=0o700)
            else:
                destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                with destination.open('xb') as output:output.write(archive.extractfile(entry).read())


def run_json(args):return json.loads(subprocess.check_output(args))[0]


def install(stage,archive_sha256):
    require(os.getuid()==0,'installer_root_required')
    require(stage.parent==Path('/opt/orbbec-agent-platform/staging') and re.fullmatch('[a-z0-9][a-z0-9-]+',stage.name),'unapproved_stage')
    require(not stage.is_symlink() and stage.is_dir() and stage.stat().st_uid==0 and stat.S_IMODE(stage.stat().st_mode)==0o700,'private_root_stage_required')
    archive=stage/'payload.tar.gz'
    require(not archive.is_symlink() and hashlib.sha256(archive.read_bytes()).hexdigest()==archive_sha256,'payload_hash_mismatch')
    extract_payload(archive,stage)
    sys.path.insert(0,str(stage))
    import release
    e=json.loads((stage/'request-template.json').read_text());release.validate_paths(e)
    release.validate_backend_manifest(e)
    require(release.tree_hashes(stage/'build/backend')==e['backend_hashes'],'backend_payload_mismatch')
    require(not any(p.is_symlink() for p in (stage/'build/backend').rglob('*')),'backend_payload_symlink')
    require(e.get('mode')=='upgrade','upgrade_payload_required')
    for key in ['platform_commit','manufacturing_commit','expected_old_platform_commit','expected_old_manufacturing_commit']:
        require(isinstance(e.get(key),str) and re.fullmatch('[0-9a-f]{40}',e[key]),'invalid_release_commit')
    require(e['target_image']=='orbbec-agent-platform:manufacturing-v2-'+e['platform_commit'][:8]+'-'+e['manufacturing_commit'][:8],'unapproved_candidate_tag')
    release.ops.configure(stage,e['platform_commit'],e['lock_tool'])
    require(release.ops.digest(release.ops.LOCK_TOOL)==e['lock_tool_sha256'],'lock_tool_changed')
    old=run_json(['docker','inspect',release.ops.API])
    require(old['Image']==e['expected_old_image'] and old['State']['Health']['Status']=='healthy','baseline_image_or_health_drift')
    release.validate_baseline(e,old)
    release.validate_backend_baseline(e,release.ops.maps(release.ops.API)['source'])
    release.validate_workflow_storage(e)
    release.native_release.validate_native_storage(e)
    release.validate_sap_relay_storage(e)
    sdk=release.native_release.validate_sdk(stage,e)
    if sdk is not None:release.native_release.check_container_sdk(release.ops.run,release.ops.API,sdk,baseline=True)
    require(len(release.ops.discover_files(old))==e['expected_chain_length'],'baseline_chain_length_drift')
    require(e['target_image']!=old['Config']['Image'],'candidate_tag_must_not_retag_rollback')
    require(run_json(['docker','image','inspect',old['Config']['Image']])['Id']==old['Image'],'baseline_tag_drift')
    release.native_release.validate_dockerfile((stage/'build/Dockerfile').read_text(),old['Config']['Image'],e)
    data=release.ops.safe_path(e['data_host'],directory=True);info=data.stat()
    require(info.st_uid==10001 and info.st_gid==10001 and stat.S_IMODE(info.st_mode)==0o700,'existing_state_metadata')
    root=Path(e['manufacturing_host']);release.ops.safe_path(root.parent,directory=True)
    manifest=json.loads((stage/'business/manifest.json').read_text())
    require(manifest['commit']==e['manufacturing_commit'],'business_commit_mismatch')
    observed=release.tree_hashes(stage/'business');observed.pop('manifest.json')
    require(observed==manifest['files'],'business_payload_mismatch')
    if root.exists():
        require(not root.is_symlink(),'business_release_symlink')
        release.validate_release_metadata(root)
        require(release.tree_hashes(root)==release.tree_hashes(stage/'business'),'existing_release_drift')
    else:
        shutil.copytree(stage/'business',root)
        for path in sorted(root.rglob('*'),reverse=True):
            require(not path.is_symlink() and (path.is_file() or path.is_dir()),'business_nonregular')
            path.chmod(0o555 if path.is_dir() else 0o444)
        root.chmod(0o555)
        release.validate_release_metadata(root)
    release.native_release.normalize_sdk_copy(stage,e)
    with (stage/'image-build.private.log').open('xb') as log:
        built=subprocess.run(['docker','build','--network','none','--pull=false','--tag',e['target_image'],str(stage/'build')],stdout=log,stderr=subprocess.STDOUT)
    require(built.returncode==0,'image_build_failed_see_private_log')
    require(run_json(['docker','image','inspect',old['Config']['Image']])['Id']==old['Image'],'baseline_tag_drift_after_build')
    image=run_json(['docker','image','inspect',e['target_image']]);baseline=run_json(['docker','image','inspect',old['Image']])
    release.validate_image_defaults(baseline,image)
    require(run_json(['docker','inspect',release.ops.API])['Id']==old['Id'],'live_container_changed_during_build')
    e['target_image_id']=image['Id']
    with (stage/'request.json').open('x') as output:json.dump(e,output,sort_keys=True,indent=2);output.write('\n')
    return {'image_built':True,'image':image['Id'],'platform_commit':e['platform_commit'],'manufacturing_commit':e['manufacturing_commit'],'live_container_unchanged':True}


if __name__=='__main__':
    os.umask(0o077)
    require(len(sys.argv)==3,'usage_install_payload_stage_archive_sha256')
    print(json.dumps(install(Path(sys.argv[1]),sys.argv[2])))
