import copy
import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('release_guard',Path(__file__).parents[1]/'release_guard.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    before={'name':'orbbec-agent-platform','services':{'platform-api':{'image':'old:live','environment':{'KEEP':'private-value','PLATFORM_RELEASE_SHA':'old'},'volumes':[{'type':'bind','source':'/old','target':'/existing','read_only':True}],'user':'10001:10001','read_only':True,'networks':{'internal':{'ipv4_address':'172.30.0.4'}}},'platform-loopback':{'image':'proxy:unchanged'}}}
    env={'PLATFORM_RELEASE_SHA':'new','PLATFORM_MANUFACTURING_ROOT':'/opt/manufacturing','PLATFORM_MANUFACTURING_DATABASE_PATH':'/app/data/manufacturing/workbench.sqlite3','PLATFORM_MANUFACTURING_RELEASE':'business'}
    mounts=[{'type':'bind','source':'/release/business','target':'/opt/manufacturing','read_only':True,'bind':{'create_host_path':False}}, {'type':'bind','source':'/data/manufacturing','target':'/app/data/manufacturing','read_only':False,'bind':{'create_host_path':False}}]
    after=copy.deepcopy(before);api=after['services']['platform-api'];api['image']='new:pin';api['environment'].update(env);api['volumes']+=copy.deepcopy(mounts)
    return before,after,env,mounts


def test_only_declared_delta_is_accepted_without_mutating_inputs():
    before,after,env,mounts=fixture();saved=copy.deepcopy((before,after))
    module.validate_candidate(before,after,target_image='new:pin',environment_delta=env,new_mounts=mounts)
    assert (before,after)==saved


@pytest.mark.parametrize('mutate',[lambda c:c['services']['platform-api']['environment'].update(KEEP='changed'), lambda c:c['services']['platform-api'].update(user='root'),lambda c:c['services']['platform-loopback'].update(image='other'),lambda c:c['services']['platform-api']['networks']['internal'].update(ipv4_address='172.30.0.9'),lambda c:c['services']['platform-api']['volumes'][0].update(read_only=False)])
def test_unrelated_runtime_changes_are_rejected(mutate):
    before,after,env,mounts=fixture();mutate(after)
    with pytest.raises(ValueError):module.validate_candidate(before,after,target_image='new:pin',environment_delta=env,new_mounts=mounts)


def test_missing_mount_or_writable_source_is_rejected():
    for change in ['missing','writable']:
        before,after,env,mounts=fixture()
        if change=='missing':after['services']['platform-api']['volumes'].pop()
        else:after['services']['platform-api']['volumes'][1]['read_only']=False
        with pytest.raises(ValueError):module.validate_candidate(before,after,target_image='new:pin',environment_delta=env,new_mounts=mounts)


def test_compose_omitted_false_bind_flag_is_only_allowed_normalization():
    before,after,env,mounts=fixture()
    after['services']['platform-api']['volumes'][1]['bind']={}
    module.validate_candidate(before,after,target_image='new:pin',environment_delta=env,new_mounts=mounts)


def test_existing_manufacturing_environment_or_target_cannot_be_overwritten():
    before,after,env,mounts=fixture();before['services']['platform-api']['environment']['PLATFORM_MANUFACTURING_ROOT']='/unexpected'
    with pytest.raises(ValueError):module.validate_candidate(before,after,target_image='new:pin',environment_delta=env,new_mounts=mounts)


def test_image_tag_drift_is_rejected():
    before,after,env,mounts=fixture();after['services']['platform-api']['image']='new:other'
    with pytest.raises(ValueError):module.validate_candidate(before,after,target_image='new:pin',environment_delta=env,new_mounts=mounts)
