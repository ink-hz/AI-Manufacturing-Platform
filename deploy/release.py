"""Manufacturing-only API rollout; private receipts and exact runtime preservation."""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import time
import uuid
from release_guard import validate_candidate
import release_support as ops


def require(value, reason):
    if not value:
        raise ValueError(reason)


def tree_hashes(root):
    return {p.relative_to(root).as_posix():ops.digest(p) for p in sorted(root.rglob('*')) if p.is_file()}


def request_data(stage):
    value=json.loads((stage/'request.json').read_text())
    for key in ['platform_commit','manufacturing_commit']:
        require(re.fullmatch(r'[0-9a-f]{40}',value[key]) is not None,'invalid_release_commit')
    return value


def environment_delta(e):
    return {'PLATFORM_RELEASE_SHA':e['platform_commit'],
            'PLATFORM_MANUFACTURING_ROOT':'/opt/manufacturing',
            'PLATFORM_MANUFACTURING_DATABASE_PATH':'/app/data/manufacturing/workbench.sqlite3',
            'PLATFORM_MANUFACTURING_RELEASE':e['manufacturing_commit']}


def added_mounts(e):
    return [{'type':'bind','source':e['manufacturing_host'],'target':'/opt/manufacturing','read_only':True,'bind':{'create_host_path':False}},
            {'type':'bind','source':e['data_host'],'target':'/app/data/manufacturing','read_only':False,'bind':{'create_host_path':False}}]


def snapshot_files(e):
    names=['request.json','release.py','release_support.py','release_guard.py','candidate_verify.py']
    result={name:ops.digest(ops.STAGE/name) for name in names}
    release=ops.safe_path(e['manufacturing_host'],directory=True)
    result['business_manifest']=ops.digest(release/'manifest.json')
    manifest=json.loads((release/'manifest.json').read_text())
    require(manifest['commit']==e['manufacturing_commit'],'business_commit_mismatch')
    observed=tree_hashes(release);observed.pop('manifest.json')
    require(observed==manifest['files'],'business_tree_mismatch')
    require(not any(p.is_symlink() for p in release.rglob('*')),'business_symlink')
    return result


def compare_runtime(old, new, e):
    require(new['Image']==e['target_image_id'],'deployed_image_mismatch')
    require(ops.actual_environment(new)=={**ops.actual_environment(old),**environment_delta(e)},'runtime_environment_changed')
    old_mounts={v['Destination']:v for v in old['Mounts']}
    new_mounts={v['Destination']:v for v in new['Mounts']}
    require(len(new_mounts)==len(new['Mounts']),'runtime_duplicate_mounts')
    for mount in added_mounts(e):
        row=new_mounts.pop(mount['target'],None)
        require(row and row['Type']=='bind' and row['Source']==mount['source'] and row['RW'] is (not mount['read_only']) and row.get('Propagation')=='rprivate','runtime_manufacturing_mount_mismatch')
    require(old_mounts==new_mounts,'existing_mount_changed')
    for field in ['Config','HostConfig']:
        before,after=copy.deepcopy(old[field]),copy.deepcopy(new[field])
        for row in [before,after]:
            for key in (['Hostname','Image','Env','Labels'] if field=='Config' else ['Binds','Mounts']):row.pop(key,None)
        require(before==after,'runtime_'+field+'_changed')
    for item in [old,new]:
        require(item['Config'].get('Hostname')==item['Id'][:12],'custom_hostname_changed')
    before,after=copy.deepcopy(old['Config']['Labels']),copy.deepcopy(new['Config']['Labels'])
    for row in [before,after]:
        for key in ['com.docker.compose.config-hash','com.docker.compose.image','com.docker.compose.project.config_files']:row.pop(key,None)
    require(before==after,'runtime_labels_changed')
    before,after=old['NetworkSettings']['Networks'],new['NetworkSettings']['Networks']
    require(set(before)==set(after),'runtime_network_set_changed')
    for name in before:
        for key in ['IPAMConfig','GwPriority','Aliases','DriverOpts','Links']:
            require(before[name].get(key)==after[name].get(key),'runtime_network_option_changed')
        if (before[name].get('IPAMConfig') or {}).get('IPv4Address'):
            require(before[name]['IPAddress']==after[name]['IPAddress'],'runtime_fixed_ip_changed')


def ready(image):
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        row=ops.inspect(ops.API)
        if row['State'].get('Health',{}).get('Status')=='healthy':
            require(row['Image']==image,'healthy_image_mismatch')
            return row
        time.sleep(2)
    raise ValueError('health_timeout')


def others_unchanged(before):
    observed=ops.identities()
    require({k:v for k,v in observed.items() if k!=ops.API}=={k:v for k,v in before.items() if k!=ops.API},'other_container_changed')


def prepare(e):
    with ops.Locks():
        require(not (ops.STAGE/'preflight.json').exists(),'prepare_already_done')
        old=ops.inspect(ops.API)
        require(old['State'].get('Health',{}).get('Status')=='healthy','baseline_unhealthy')
        require(old['Image']==e['expected_old_image'],'baseline_image_drift')
        files=ops.discover_files(old)
        require(len(files)==e['expected_chain_length'],'compose_chain_length_drift')
        env=ops.environment(old)
        baseline=json.loads(ops.run(ops.compose(files)+['config','--format','json'],env=env))
        image=json.loads(ops.run(['docker','image','inspect',old['Image']]))[0]
        probe_id=ops.run(['docker','create','--network','none',old['Image']]).decode().strip()
        try:probe=ops.inspect(probe_id)
        finally:ops.run(['docker','rm',probe_id])
        volumes={}
        for mount in baseline['services']['platform-api'].get('volumes',[]):
            if mount['type']=='volume':
                name=baseline['volumes'][mount['source']]['name']
                volumes[name]=json.loads(ops.run(['docker','volume','inspect',name]))[0]
        replay=ops.replay_equivalence(baseline,old,image,probe,volumes)
        overlay={'services':{'platform-api':{'image':e['target_image'],'environment':environment_delta(e),'volumes':added_mounts(e)}}}
        ops.write('overlay.json',overlay)
        candidate=json.loads(ops.run(ops.compose(files,True)+['config','--format','json'],env=env))
        validate_candidate(baseline,candidate,target_image=e['target_image'],environment_delta=environment_delta(e),new_mounts=added_mounts(e))
        current=ops.maps(ops.API)
        for path,expected in e['backend_base_hashes'].items():
            require(current['source'].get(path)==expected,'baseline_source_drift:'+path)
        expected_source={**current['source'],**e['backend_hashes']}
        expected_static={**current['static'],**e['static_hashes']}
        require(json.loads(ops.run(['docker','image','inspect',e['target_image']]))[0]['Id']==e['target_image_id'],'target_tag_drift')
        (ops.STAGE/'backup').mkdir(mode=0o700)
        ops.write('backup/api-inspect.private.json',old)
        config_hashes={}
        for number,name in enumerate(dict.fromkeys(files+[ops.ENV_FILE,e['nginx_path']])):
            data=ops.safe_path(name).read_bytes();ops.private_bytes('backup/'+str(number)+'.private',data);config_hashes[name]=hashlib.sha256(data).hexdigest()
        resources=ops.resource_snapshot(e['resource_urls'])
        pre={'old':old,'files':files,'config_hashes':config_hashes,'artifact_hashes':snapshot_files(e),'containers':ops.identities(),'resources':resources,'baseline_content':current,'expected_source':expected_source,'expected_static':expected_static,'replay':replay,'overlay_sha256':ops.digest(ops.STAGE/'overlay.json')}
        ops.write('baseline-compose.private.json',baseline);ops.write('candidate-compose.private.json',candidate);ops.write('preflight.json',pre)
        print(json.dumps({'prepared':True,'compose_files':len(files),'runtime_replay':True,'unchanged_non_api':len(pre['containers'])-1}))


def unchanged(e,pre):
    require(snapshot_files(e)==pre['artifact_hashes'],'release_artifact_changed')
    require(ops.digest(ops.STAGE/'overlay.json')==pre['overlay_sha256'],'overlay_changed')
    for path,digest in pre['config_hashes'].items():require(ops.digest(path)==digest,'baseline_config_changed')
    others_unchanged(pre['containers'])


def candidate(e):
    with ops.Locks():
        pre=ops.read('preflight.json');unchanged(e,pre)
        require(ops.inspect(ops.API)['Id']==pre['old']['Id'],'running_container_drift')
        args=['docker','run','--rm','-i','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','10001:10001','--tmpfs','/tmp:rw,noexec,nosuid,size=32m']
        args+=['--mount',f"type=bind,source={e['manufacturing_host']},target=/opt/manufacturing,readonly"]
        args+=['-e','PLATFORM_MANUFACTURING_ROOT=/opt/manufacturing','-e','PLATFORM_MANUFACTURING_DATABASE_PATH=/tmp/manufacturing-candidate.sqlite3','-e','PLATFORM_MANUFACTURING_RELEASE='+e['manufacturing_commit']]
        args+=['--entrypoint','python',e['target_image_id'],'-c',(ops.STAGE/'candidate_verify.py').read_text()]
        checked=json.loads(ops.run(args,data=ops.canonical({'expected_source':pre['expected_source'],'expected_static':pre['expected_static'],'business_commit':e['manufacturing_commit']}),timeout=180))
        require(checked['passed'] is True,'candidate_not_passed')
        checked.update(preflight_sha256=ops.digest(ops.STAGE/'preflight.json'),request_sha256=ops.digest(ops.STAGE/'request.json'),image=e['target_image_id'])
        ops.write('candidate-validation.json',checked)
        print(json.dumps({'candidate_passed':True,'authenticated_identity':'synthetic_candidate_only','production_business_writes':0}))


def http_checks(e,pre):
    statuses={}
    for path,expected in [('/api/health',200),('/manufacturing',200),('/api/v1/manufacturing/access',401),('/api/v1/manufacturing/catalog',401),('/api/v1/manufacturing/health',401),('/api/v1/manufacturing/assets/manufacturing.js',401),('/sdk-admin',200),('/sdk/api.php/v1/users',403)]:
        status,body,headers=ops.http(ops.DOMAIN+path);require(status==expected,'http_status:'+path)
        require('no-store' in headers.get('cache-control',''),'http_cache:'+path)
        statuses[path]=status
    for path,expected_hash in e['static_hashes'].items():
        if not path.startswith('assets/'):continue
        status,body,headers=ops.http(ops.DOMAIN+'/'+path)
        if status==200:require(hashlib.sha256(body).hexdigest()==expected_hash,'public_asset_hash:'+path)
        else:require(status in {401,403} and 'no-store' in headers.get('cache-control',''),'public_asset_policy:'+path)
    require(ops.resource_snapshot(e['resource_urls'])==pre['resources'],'other_app_resource_changed')
    return statuses


def cutover(e):
    with ops.Locks(input_lock=True) as locks:
        pre=ops.read('preflight.json');checked=ops.read('candidate-validation.json');unchanged(e,pre)
        require(not (ops.STAGE/'cutover.json').exists(),'cutover_already_done')
        require(checked['preflight_sha256']==ops.digest(ops.STAGE/'preflight.json') and checked['request_sha256']==ops.digest(ops.STAGE/'request.json') and checked['image']==e['target_image_id'],'candidate_receipt_changed')
        old=ops.inspect(ops.API);require(old['Id']==pre['old']['Id'] and old['Image']==pre['old']['Image'],'baseline_drift')
        require(ops.discover_files(old)==pre['files'],'compose_chain_drift')
        env=ops.environment(old)
        baseline=json.loads(ops.run(ops.compose(pre['files'])+['config','--format','json'],env=env))
        candidate_config=json.loads(ops.run(ops.compose(pre['files'],True)+['config','--format','json'],env=env))
        validate_candidate(baseline,candidate_config,target_image=e['target_image'],environment_delta=environment_delta(e),new_mounts=added_mounts(e))
        require(json.loads(ops.run(['docker','image','inspect',e['target_image']]))[0]['Id']==e['target_image_id'],'target_tag_drift')
        try:
            ops.run(ops.compose(pre['files'],True)+['up','-d','--no-build','--no-deps','--force-recreate','platform-api'],env=env,timeout=180)
            new=ready(e['target_image_id']);compare_runtime(old,new,e)
            require(ops.discover_files(new)==pre['files']+[str(ops.STAGE/'overlay.json')],'new_chain_mismatch')
            require(ops.maps(ops.API)=={'source':pre['expected_source'],'static':pre['expected_static']},'deployed_content_mismatch')
            # Initializes new SQLite schema under the actual UID; writes no business records.
            verify="import os,sys,json; from pathlib import Path; assert os.getuid()==10001; sys.path.insert(0,'/opt/manufacturing/src'); from manufacturing_platform.repository import Repository; r=Repository(os.environ['PLATFORM_MANUFACTURING_DATABASE_PATH']); r.health(); assert os.statvfs('/opt/manufacturing').f_flag & os.ST_RDONLY; print(json.dumps({'schema_ready':True,'source_read_only':True,'business_records_written':0}))"
            readiness=json.loads(ops.run(['docker','exec',ops.API,'python','-c',verify]))
            statuses=http_checks(e,pre);unchanged(e,pre)
            receipt={'status':'healthy','platform_commit':e['platform_commit'],'manufacturing_commit':e['manufacturing_commit'],'image':new['Image'],'container':new['Id'],'compose_files':pre['files']+[str(ops.STAGE/'overlay.json')],'readiness':readiness,'http_statuses':statuses,'browser_acceptance':'not_run','production_erp_connections':'unverified'}
            ops.write('cutover.json',receipt)
            ops.write('future-maintenance.json',{'compose_files_in_order':receipt['compose_files'],'platform_commit':e['platform_commit'],'manufacturing_commit':e['manufacturing_commit'],'image':new['Image'],'previous_manifest':e['previous_manifest'],'preservation':'All prior ordered overlays, mounts, networks, runtime security and Git capability retained.'})
            print(json.dumps({'deployed':True,'platform_commit':e['platform_commit'],'manufacturing_commit':e['manufacturing_commit'],'image':new['Image'],'compose_files':len(receipt['compose_files'])}))
        except BaseException as error:
            try:
                ops.write('cutover-failure.private.json',{'type':type(error).__name__,'reason':str(error)})
            except OSError:
                pass  # A full receipt disk must not block the rollback attempt.
            try:
                require(json.loads(ops.run(['docker','image','inspect',old['Config']['Image']]))[0]['Id']==old['Image'],'rollback_tag_drift')
                ops.run(ops.compose(pre['files'])+['up','-d','--no-build','--no-deps','--force-recreate','platform-api'],env=env)
                restored=ready(old['Image'])
                require(ops.actual_environment(restored)==ops.actual_environment(old),'rollback_environment_mismatch')
                require(sorted(restored['Mounts'],key=lambda m:m['Destination'])==sorted(old['Mounts'],key=lambda m:m['Destination']),'rollback_mount_mismatch')
                require(ops.discover_files(restored)==pre['files'],'rollback_chain_mismatch')
                require(ops.maps(ops.API)==pre['baseline_content'],'rollback_content_mismatch')
                ops.runtime_values(old,restored)
                others_unchanged(pre['containers'])
                ops.write('rollback.json',{'restored':True,'image':restored['Image'],'manufacturing_data_retained':True})
            except BaseException as rollback_error:
                locks.retained=True;ops.write('rollback-failure.private.json',{'type':type(rollback_error).__name__,'reason':str(rollback_error)})
            raise


if __name__=='__main__':
    os.umask(0o077)
    require(len(sys.argv)==3 and sys.argv[2] in {'prepare','candidate','cutover'},'usage_release_stage_action')
    stage=Path(sys.argv[1]);e=request_data(stage)
    ops.configure(stage,e['platform_commit'],e['lock_tool'])
    require(ops.digest(ops.LOCK_TOOL)==e['lock_tool_sha256'],'lock_tool_changed')
    def interrupted(number, frame):
        raise SystemExit('release_signal:'+str(number))
    for number in [signal.SIGTERM,signal.SIGHUP]:
        signal.signal(number,interrupted)
    try:globals()[sys.argv[2]](e)
    except BaseException as error:
        ops.write('failure-'+uuid.uuid4().hex+'.private.json',{'type':type(error).__name__,'reason':str(error)})
        print('MANUFACTURING_RELEASE_FAILED private_receipt_written',file=sys.stderr)
        raise SystemExit(1)
