import copy
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]))
import release_guard as guard


def fixture():
    oldsha='a'*40;newsha='b'*40
    before_env={'PLATFORM_RELEASE_SHA':'c'*40,'PLATFORM_MANUFACTURING_RELEASE':oldsha,'PLATFORM_MANUFACTURING_ROOT':'/opt/manufacturing','PLATFORM_MANUFACTURING_DATABASE_PATH':'/app/data/manufacturing/workbench.sqlite3'}
    env={**before_env,'PLATFORM_RELEASE_SHA':'d'*40,'PLATFORM_MANUFACTURING_RELEASE':newsha}
    base='/data/orbbec-agent-platform/manufacturing'
    code={'type':'bind','source':base+'/releases/'+oldsha,'target':'/opt/manufacturing','read_only':True,'bind':{'create_host_path':False}}
    data={'type':'bind','source':base+'/data','target':'/app/data/manufacturing','read_only':False,'bind':{'create_host_path':False}}
    before={'services':{'platform-api':{'image':'old:live','environment':{**before_env,'KEEP':'private'},'volumes':[{'type':'bind','source':'/keep','target':'/existing','read_only':True},code,copy.deepcopy(data)],'read_only':True,'user':'10001:10001','networks':{'sdk':{'ipv4_address':''}}},'other':{'image':'keep:exact'}}}
    after=copy.deepcopy(before);api=after['services']['platform-api'];api['image']='new:fixed';api['environment'].update(env)
    new_code={**copy.deepcopy(code),'source':base+'/releases/'+newsha};api['volumes'][1]=copy.deepcopy(new_code)
    options={'target_image':'new:fixed','environment_delta':env,'baseline_environment':before_env,'new_code_mount':new_code,'data_mount':data}
    return before,after,options


def test_only_existing_code_source_and_two_release_values_change_without_input_mutation():
    before,after,options=fixture();saved=copy.deepcopy((before,after))
    guard.validate_upgrade_candidate(before,after,**options)
    assert (before,after)==saved


@pytest.mark.parametrize('mutate',[
 lambda c:c['services']['platform-api']['volumes'][0].update(read_only=False),
 lambda c:c['services']['platform-api']['volumes'][2].update(source='/wrong-data'),
 lambda c:c['services']['platform-api']['volumes'][2].update(read_only=True),
 lambda c:c['services']['platform-api']['volumes'][1]['bind'].update(create_host_path=True),
 lambda c:c['services']['platform-api']['volumes'].append({'type':'bind','source':'/new','target':'/new'}),
 lambda c:c['services']['platform-api']['volumes'].append(copy.deepcopy(c['services']['platform-api']['volumes'][1])),
 lambda c:c['services']['platform-api']['environment'].update(PLATFORM_MANUFACTURING_ROOT='/tmp'),
 lambda c:c['services']['platform-api']['environment'].update(PLATFORM_MANUFACTURING_DATABASE_PATH='/tmp/other.db'),
 lambda c:c['services']['platform-api']['environment'].update(KEEP='wrong'),
 lambda c:c['services']['platform-api'].update(user='0'),
 lambda c:c['services']['platform-api']['networks']['sdk'].update(ipv4_address='172.23.0.3'),
 lambda c:c['services']['other'].update(image='changed'),
])
def test_every_other_upgrade_delta_is_rejected(mutate):
    before,after,options=fixture();mutate(after)
    with pytest.raises(ValueError):guard.validate_upgrade_candidate(before,after,**options)


def test_baseline_release_pins_and_source_path_are_required():
    for mutate in [lambda b:b['services']['platform-api']['environment'].update(PLATFORM_MANUFACTURING_RELEASE='e'*40),lambda b:b['services']['platform-api']['volumes'][1].update(source='/wrong-baseline'),lambda b:b['services']['platform-api']['volumes'].append(copy.deepcopy(b['services']['platform-api']['volumes'][0]))]:
        before,after,options=fixture();mutate(before)
        with pytest.raises(ValueError):guard.validate_upgrade_candidate(before,after,**options)


def test_caller_cannot_authorize_arbitrary_code_path_or_root_database_change():
    before,after,options=fixture();options['new_code_mount']['source']='/arbitrary';after['services']['platform-api']['volumes'][1]['source']='/arbitrary'
    with pytest.raises(ValueError):guard.validate_upgrade_candidate(before,after,**options)
    before,after,options=fixture();options['environment_delta']['PLATFORM_MANUFACTURING_ROOT']='/tmp';after['services']['platform-api']['environment']['PLATFORM_MANUFACTURING_ROOT']='/tmp'
    with pytest.raises(ValueError):guard.validate_upgrade_candidate(before,after,**options)
