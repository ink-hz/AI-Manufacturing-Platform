"""Fail-closed allowlist for the manufacturing-only Compose overlay."""
import copy
import re

from native_release import NATIVE_FIELDS, native_environment


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


WORKFLOW_FIELDS = {
    'database_path': 'PLATFORM_MANUFACTURING_WORKFLOW_DATABASE_PATH',
    'authority_database_path': 'PLATFORM_MANUFACTURING_AUTHORITY_DATABASE_PATH',
    'dataset_id': 'PLATFORM_MANUFACTURING_DATASET_ID',
    'dataset_mode': 'PLATFORM_MANUFACTURING_DATASET_MODE',
    'dataset_label': 'PLATFORM_MANUFACTURING_DATASET_LABEL',
}


def workflow_environment(config):
    _require(isinstance(config,dict) and set(config)==set(WORKFLOW_FIELDS),'workflow_exact_fields_required')
    _require(all(isinstance(v,str) and v==v.strip() and v and len(v)<=160 and not any(ord(c)<32 for c in v) for v in config.values()),'workflow_invalid_value')
    for key in ['database_path','authority_database_path']:
        _require(re.fullmatch(r'/app/data/manufacturing/[A-Za-z0-9][A-Za-z0-9_-]*\.sqlite3',config[key]) is not None,'workflow_database_path')
    _require(len({config['database_path'],config['authority_database_path'],'/app/data/manufacturing/workbench.sqlite3'})==3,'workflow_database_alias')
    _require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,95}',config['dataset_id']) is not None,'workflow_dataset_id')
    _require(config['dataset_mode'] in {'demo','production'},'workflow_dataset_mode')
    simulation=any(marker in config['dataset_label'].lower() for marker in ['demo','simulat','模拟'])
    _require(simulation == (config['dataset_mode']=='demo'),'workflow_mode_label')
    return {env:config[key] for key,env in WORKFLOW_FIELDS.items()}


def validate_workflow_environment(env):
    selected={key:env[value] for key,value in WORKFLOW_FIELDS.items() if value in env}
    if selected:workflow_environment(selected)


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
                               baseline_environment, new_code_mount, data_mount, native_enabled=False):
    """Replace one immutable source; preserve the existing data and all other state."""
    before,after=copy.deepcopy(baseline),copy.deepcopy(candidate)
    old,new=before['services']['platform-api'],after['services']['platform-api']
    _require(new.get('image')==target_image,'candidate_image_drift')
    old.pop('image');new.pop('image')
    fixed={'PLATFORM_MANUFACTURING_ROOT':'/opt/manufacturing',
           'PLATFORM_MANUFACTURING_DATABASE_PATH':'/app/data/manufacturing/workbench.sqlite3'}
    releases={'PLATFORM_RELEASE_SHA','PLATFORM_MANUFACTURING_RELEASE'}
    workflow_keys=set(WORKFLOW_FIELDS.values())
    native_keys=set(NATIVE_FIELDS.values()) if native_enabled else set()
    for row in [baseline_environment,environment_delta]:
        _require(set(fixed)|releases <= set(row) <= set(fixed)|releases|workflow_keys|native_keys,'upgrade_environment_keys')
        validate_workflow_environment(row)
        selected={key:row[value] for key,value in NATIVE_FIELDS.items() if value in row}
        if selected:native_environment(selected)
    old_workflow={k:v for k,v in baseline_environment.items() if k in workflow_keys}
    new_workflow={k:v for k,v in environment_delta.items() if k in workflow_keys}
    _require(not old_workflow or old_workflow==new_workflow,'existing_workflow_configuration_changed')
    old_native={k:v for k,v in baseline_environment.items() if k in native_keys}
    new_native={k:v for k,v in environment_delta.items() if k in native_keys}
    _require(not old_native or old_native==new_native,'existing_native_configuration_changed')
    for key in releases:
        _require(all(isinstance(row[key],str) and re.fullmatch('[0-9a-f]{40}',row[key]) for row in [baseline_environment,environment_delta]),'upgrade_release_pin')
    old_env,new_env=old.get('environment',{}),new.get('environment',{})
    for key in (workflow_keys|native_keys)-set(baseline_environment):
        _require(key not in old_env,'upgrade_baseline_workflow_expected_absent')
    for key,value in environment_delta.items():
        if key not in baseline_environment:
            _require(new_env.get(key)==value,'candidate_environment_mismatch')
            new_env.pop(key)
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
