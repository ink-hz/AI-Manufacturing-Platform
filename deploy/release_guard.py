"""Fail-closed allowlist for the manufacturing-only Compose overlay."""
import copy
import re


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _mount(value):
    result=copy.deepcopy(value)
    if result.get('type')=='bind':
        result.setdefault('read_only',False)
        result.setdefault('bind',{}).setdefault('create_host_path',False)
    return result


def validate_candidate(baseline, candidate, *, target_image, environment_delta, new_mounts):
    before,after=copy.deepcopy(baseline),copy.deepcopy(candidate)
    old=before['services']['platform-api'];new=after['services']['platform-api']
    _require(new.get('image')==target_image,'candidate_image_drift')
    old.pop('image');new.pop('image')
    old_env=old.get('environment',{});new_env=new.get('environment',{})
    for key,value in environment_delta.items():
        _require(new_env.get(key)==value,'candidate_environment_mismatch')
        if key!='PLATFORM_RELEASE_SHA':
            _require(key not in old_env,'manufacturing_environment_preexists')
        new_env.pop(key,None);old_env.pop(key,None)
    targets=[m['target'] for m in new_mounts]
    _require(len(set(targets))==len(targets),'duplicate_approved_mount')
    old_volumes=old.get('volumes',[]);new_volumes=new.get('volumes',[])
    _require(not any(m.get('target') in targets for m in old_volumes),'manufacturing_mount_preexists')
    _require(len({m.get('target') for m in new_volumes})==len(new_volumes),'duplicate_candidate_mount')
    for expected in new_mounts:
        found=[m for m in new_volumes if m.get('target')==expected['target']]
        _require(len(found)==1 and _mount(found[0])==_mount(expected),'candidate_mount_mismatch')
        new_volumes.remove(found[0])
    _require(before==after,'unrelated_compose_change')


def validate_upgrade_candidate(baseline, candidate, *, target_image, environment_delta,
                               baseline_environment, new_code_mount, data_mount):
    """Replace one immutable source; preserve the existing data and all other state."""
    before,after=copy.deepcopy(baseline),copy.deepcopy(candidate)
    old,new=before['services']['platform-api'],after['services']['platform-api']
    _require(new.get('image')==target_image,'candidate_image_drift')
    old.pop('image');new.pop('image')
    fixed={'PLATFORM_MANUFACTURING_ROOT':'/opt/manufacturing',
           'PLATFORM_MANUFACTURING_DATABASE_PATH':'/app/data/manufacturing/workbench.sqlite3'}
    releases={'PLATFORM_RELEASE_SHA','PLATFORM_MANUFACTURING_RELEASE'}
    _require(set(baseline_environment)==set(environment_delta)==set(fixed)|releases,'upgrade_environment_keys')
    for key in releases:
        _require(all(isinstance(row[key],str) and re.fullmatch('[0-9a-f]{40}',row[key]) for row in [baseline_environment,environment_delta]),'upgrade_release_pin')
    old_env,new_env=old.get('environment',{}),new.get('environment',{})
    for key,value in baseline_environment.items():
        _require(old_env.get(key)==value,'upgrade_baseline_environment_drift')
        _require(new_env.get(key)==environment_delta[key],'candidate_environment_mismatch')
        if key in fixed:_require(value==environment_delta[key]==fixed[key],'upgrade_fixed_environment_changed')
        old_env.pop(key);new_env.pop(key)
    base='/data/orbbec-agent-platform/manufacturing'
    expected_code={'type':'bind','source':base+'/releases/'+environment_delta['PLATFORM_MANUFACTURING_RELEASE'],
                   'target':'/opt/manufacturing','read_only':True,'bind':{'create_host_path':False}}
    expected_data={'type':'bind','source':base+'/data','target':'/app/data/manufacturing',
                   'read_only':False,'bind':{'create_host_path':False}}
    _require(_mount(new_code_mount)==expected_code and _mount(data_mount)==expected_data,'upgrade_unapproved_mount')
    old_code={**copy.deepcopy(expected_code),'source':base+'/releases/'+baseline_environment['PLATFORM_MANUFACTURING_RELEASE']}
    for volumes,code in [(old.get('volumes',[]),old_code),(new.get('volumes',[]),expected_code)]:
        _require(len({m.get('target') for m in volumes})==len(volumes),'duplicate_upgrade_mount')
        selected=[m for m in volumes if m.get('target')=='/opt/manufacturing']
        state=[m for m in volumes if m.get('target')=='/app/data/manufacturing']
        _require(len(selected)==len(state)==1 and _mount(selected[0])==code and _mount(state[0])==expected_data,'upgrade_mount_mismatch')
        volumes.remove(selected[0])
    _require(before==after,'unrelated_compose_change')
