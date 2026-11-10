"""Build a reviewed, versioned manufacturing payload from committed sources only."""
from pathlib import Path
from datetime import datetime,timezone
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import tarfile

DOCUMENTS=['docs/manufacturing-system-handbook.md','docs/workflows/manufacturing-process-overview.md']
TOOLS=['release.py','release_support.py','release_guard.py','candidate_verify.py','candidate_fixture.py','sqlite_backup.py','native_release.py']


def require(condition,reason):
    if not condition:raise ValueError(reason)


def git(repo,*args):
    return subprocess.check_output(['git','-C',str(repo),*args])


def digest(value):return hashlib.sha256(value).hexdigest()


def export_paths(repo,sha,target,paths):
    data=git(repo,'archive','--format=tar',sha,*paths)
    with tarfile.open(fileobj=io.BytesIO(data),mode='r:') as archive:
        for member in archive.getmembers():
            relative=Path(member.name)
            require(not relative.is_absolute() and '..' not in relative.parts and (member.isdir() or member.isfile()),'unsafe_git_archive_member')
            destination=target/relative
            if member.isdir():destination.mkdir(parents=True,exist_ok=True)
            else:
                destination.parent.mkdir(parents=True,exist_ok=True)
                destination.write_bytes(archive.extractfile(member).read())


def write_business_release(repo,sha,assets,target):
    repo,assets,target=Path(repo),Path(assets),Path(target)
    require(not target.exists(),'release_target_exists');target.mkdir(parents=True)
    export_paths(repo,sha,target,['src',*DOCUMENTS])
    files={}
    for name in ['manufacturing.js','manufacturing.css']:
        source=assets/name;require(source.is_file() and not source.is_symlink(),'missing_business_asset')
        path=target/'webui/dist'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(source.read_bytes())
    metadata={}
    for name in DOCUMENTS:
        committed=git(repo,'show',sha+':'+name)
        require((target/name).read_bytes()==committed,'document_export_mismatch')
        stamp=git(repo,'log','-1','--format=%cI',sha,'--',name).decode().strip()
        metadata[name]={'sha256':digest(committed),'updated_at':datetime.fromisoformat(stamp).astimezone(timezone.utc).isoformat()}
    (target/'handbook-metadata.json').write_text(json.dumps({'files':metadata},sort_keys=True,indent=2)+'\n')
    for path in sorted(target.rglob('*')):
        if path.is_file():files[path.relative_to(target).as_posix()]=digest(path.read_bytes())
    (target/'manifest.json').write_text(json.dumps({'commit':sha,'files':files},sort_keys=True,indent=2)+'\n')


def build_frontend(repo,sha,target,log):
    export_paths(repo,sha,target,['webui'])
    installed=Path(repo)/'webui/node_modules'
    require(installed.is_dir(),'install_locked_node_dependencies_first')
    require(git(repo,'show',sha+':webui/package-lock.json')==(Path(repo)/'webui/package-lock.json').read_bytes(),'installed_lockfile_drift')
    (target/'webui/node_modules').symlink_to(installed.resolve(),target_is_directory=True)
    env={k:v for k,v in os.environ.items() if not k.startswith(('VITE_','PLATFORM_','COMPOSE_','SDK_'))}
    with log.open('wb') as output:
        subprocess.run(['npm','run','build'],cwd=target/'webui',env=env,stdout=output,stderr=subprocess.STDOUT,check=True)
    return target/'webui/dist'


def backend_overlay(repo, base, target, output, approved_files, added_files):
    approved=set(approved_files);added=set(added_files)
    require(len(approved)==len(approved_files) and added<=approved,'invalid_backend_inventory')
    for name in approved:
        require(isinstance(name,str) and re.fullmatch(r'[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)*\.py',name),'invalid_backend_path')
    statuses={}
    for row in git(repo,'diff','--no-renames','--name-status',base,target,'--','backend/app').decode().splitlines():
        status,name=row.split('\t');statuses[name.removeprefix('backend/app/')]=status
    require(set(statuses)==approved,'unreviewed_backend_delta')
    require({n for n,status in statuses.items() if status=='A'}==added,'unreviewed_backend_creation')
    require(all(v in {'A','M'} for v in statuses.values()),'backend_deletion_or_type_change')
    old={};new={};contents={}
    for name in sorted(approved):
        path='backend/app/'+name
        for sha in ([target] if name in added else [base,target]):
            entry=git(repo,'ls-tree',sha,'--',path).decode().split()
            require(len(entry)>=3 and entry[0]=='100644' and entry[1]=='blob','backend_nonregular_file')
        contents[name]=git(repo,'show',target+':'+path)
        new[name]=digest(contents[name]);old[name]=None if name in added else digest(git(repo,'show',base+':'+path))
    for name,value in contents.items():
        destination=output/name;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(value)
    return old,new


def assemble(manufacturing_repo,platform_repo,output,baseline,manufacturing_sha,platform_sha,platform_base_sha):
    require(output.is_absolute() and not output.exists(),'new_absolute_output_required')
    for value in [manufacturing_sha,platform_sha,platform_base_sha]:require(re.fullmatch('[0-9a-f]{40}',value) is not None,'invalid_source_commit')
    for repo,sha,branch in [(manufacturing_repo,manufacturing_sha,'main'),(platform_repo,platform_sha,'master')]:
        subprocess.run(['git','-C',str(repo),'merge-base','--is-ancestor',sha,branch],check=True)
    require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_./:@-]*',baseline['old_image_tag']) is not None,'invalid_base_image')
    output.mkdir(mode=0o700)
    clean=output/'clean';clean.mkdir()
    business_dist=build_frontend(manufacturing_repo,manufacturing_sha,clean/'manufacturing',output/'business-build.private.log')
    platform_dist=build_frontend(platform_repo,platform_sha,clean/'platform',output/'platform-build.private.log')
    payload=output/'payload';payload.mkdir()
    # A handbook-only release has no backend delta but keeps the COPY source.
    (payload/'build/backend').mkdir(parents=True)
    write_business_release(manufacturing_repo,manufacturing_sha,business_dist,payload/'business')
    base_hashes,new_hashes=backend_overlay(platform_repo,platform_base_sha,platform_sha,payload/'build/backend',baseline['approved_backend_files'],baseline.get('approved_backend_additions',[]))
    static={}
    for source in sorted(platform_dist.rglob('*')):
        require(not source.is_symlink(),'static_symlink')
        if source.is_file():
            name=source.relative_to(platform_dist).as_posix();value=source.read_bytes();destination=payload/'build/static'/name
            destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(value);static[name]=digest(value)
    tag='orbbec-agent-platform:manufacturing-v2-'+platform_sha[:8]+'-'+manufacturing_sha[:8]
    (payload/'build/Dockerfile').write_text('FROM '+baseline['old_image_tag']+'\nCOPY --chown=10001:10001 backend/ /app/backend/app/\nCOPY --chown=10001:10001 static/ /app/backend/app/static/\n')
    for name in TOOLS:(payload/name).write_bytes(git(manufacturing_repo,'show',manufacturing_sha+':deploy/'+name))
    request={'mode':'upgrade','platform_commit':platform_sha,'manufacturing_commit':manufacturing_sha,
             'target_image':tag,'expected_old_image':baseline['old_image_id'],'expected_chain_length':baseline['chain_length'],
             'expected_old_platform_commit':baseline['old_platform_commit'],'expected_old_manufacturing_commit':baseline['old_manufacturing_commit'],
             'manufacturing_host':'/data/orbbec-agent-platform/manufacturing/releases/'+manufacturing_sha,
             'data_host':'/data/orbbec-agent-platform/manufacturing/data','nginx_path':'/etc/nginx/sites-available/agent-domain.conf',
             'previous_manifest':baseline['previous_manifest'],'lock_tool':baseline['lock_tool'],'lock_tool_sha256':baseline['lock_tool_sha256'],
             'resource_urls':['https://agent.orbbec.com.cn/office/','https://fae.orbbec.com.cn/partner/login'],
             'backend_base_hashes':base_hashes,'backend_hashes':new_hashes,'backend_added_files':baseline.get('approved_backend_additions',[]),'static_hashes':static}
    from release import workflow_configuration
    for key in ['baseline_workflow','target_workflow','baseline_native','target_native']:
        if key in baseline:request[key]=baseline[key]
    workflow_configuration(request)
    from native_release import native_configuration
    native_configuration(request)
    (payload/'request-template.json').write_text(json.dumps(request,sort_keys=True,indent=2)+'\n')
    archive=output/'payload.tar.gz'
    def metadata(member):
        member.uid=member.gid=0;member.uname=member.gname='root';member.mtime=0
        member.mode=(0o555 if member.isdir() else 0o444) if Path(member.name).parts[0]=='business' else (0o755 if member.isdir() else 0o644) if Path(member.name).parts[0]=='build' else (0o700 if member.isdir() else 0o600)
        return member
    with tarfile.open(archive,'w:gz') as tar:
        for path in sorted(payload.iterdir()):tar.add(path,arcname=path.name,filter=metadata)
    info={'archive':str(archive),'sha256':digest(archive.read_bytes()),'platform_commit':platform_sha,'manufacturing_commit':manufacturing_sha,'backend_files':len(new_hashes),'static_files':len(static)}
    (output/'build-info.json').write_text(json.dumps(info,sort_keys=True,indent=2)+'\n')
    return info


if __name__=='__main__':
    os.umask(0o077)
    parser=argparse.ArgumentParser()
    parser.add_argument('--manufacturing-repo',type=Path,required=True);parser.add_argument('--platform-repo',type=Path,required=True)
    parser.add_argument('--manufacturing-sha',required=True);parser.add_argument('--platform-sha',required=True);parser.add_argument('--platform-base-sha',required=True)
    parser.add_argument('--baseline',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(assemble(args.manufacturing_repo,args.platform_repo,args.output,json.loads(args.baseline.read_text()),args.manufacturing_sha,args.platform_sha,args.platform_base_sha)))
