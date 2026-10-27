"""Fail-closed allowlist for the manufacturing-only Compose overlay."""
import copy


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
