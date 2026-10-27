import copy
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]))
import release


def fixture():
    e={'mode':'upgrade','platform_commit':'d'*40,'manufacturing_commit':'b'*40,'expected_old_platform_commit':'c'*40,'expected_old_manufacturing_commit':'a'*40,'manufacturing_host':'/data/orbbec-agent-platform/manufacturing/releases/'+'b'*40,'data_host':'/data/orbbec-agent-platform/manufacturing/data','target_image_id':'sha256:new'}
    old_env={**release.environment_delta(e),'PLATFORM_RELEASE_SHA':'c'*40,'PLATFORM_MANUFACTURING_RELEASE':'a'*40,'KEEP':'same'}
    source='/data/orbbec-agent-platform/manufacturing/releases/'+'a'*40
    mounts=[{'Type':'bind','Source':source,'Destination':'/opt/manufacturing','Mode':'','RW':False,'Propagation':'rprivate'},{'Type':'bind','Source':e['data_host'],'Destination':'/app/data/manufacturing','Mode':'','RW':True,'Propagation':'rprivate'},{'Type':'bind','Source':'/keep','Destination':'/existing','Mode':'ro','RW':False,'Propagation':'rprivate'}]
    old={'Id':'1'*64,'Image':'sha256:old','Config':{'Hostname':'1'*12,'Image':'old:tag','Env':[k+'='+v for k,v in old_env.items()],'Labels':{'KEEP':'same'},'User':'10001:10001','Cmd':['serve']},'HostConfig':{'ReadonlyRootfs':True,'Binds':['/keep:/existing:ro'],'Mounts':[{'Type':'bind','Source':source,'Target':'/opt/manufacturing','ReadOnly':True,'BindOptions':{}},{'Type':'bind','Source':e['data_host'],'Target':'/app/data/manufacturing','BindOptions':{}}]},'Mounts':mounts,'NetworkSettings':{'Networks':{'sdk':{'IPAMConfig':{'IPv4Address':''},'GwPriority':0,'Aliases':['platform-api'],'DriverOpts':None,'Links':None}}}}
    new=copy.deepcopy(old);new.update(Id='2'*64,Image='sha256:new');new['Config'].update(Hostname='2'*12,Image='new:tag',Env=[k+'='+v for k,v in {**old_env,**release.environment_delta(e)}.items()]);new['Mounts'][0]['Source']=e['manufacturing_host'];new['HostConfig']['Mounts'][0]['Source']=e['manufacturing_host']
    return e,old,new


def test_upgrade_overlay_contains_only_code_mount_and_runtime_accepts_source_replacement():
    e,old,new=fixture()
    assert [row['target'] for row in release.overlay_mounts(e)]==['/opt/manufacturing']
    release.validate_baseline(e,old)
    release.compare_runtime(old,new,e)


@pytest.mark.parametrize('mutate',[
 lambda r:r['HostConfig']['Mounts'][0]['BindOptions'].update(NonRecursive=True),
 lambda r:r['HostConfig']['Mounts'][1]['BindOptions'].update(ReadOnlyNonRecursive=True),
 lambda r:r['Mounts'][1].update(Source='/changed-data'),
 lambda r:r['Mounts'][2].update(RW=True),
 lambda r:r['Mounts'].append(copy.deepcopy(r['Mounts'][0])),
])
def test_upgrade_runtime_preserves_host_mount_options_and_all_data(mutate):
    e,old,new=fixture();mutate(new)
    with pytest.raises(ValueError):release.compare_runtime(old,new,e)


def test_upgrade_baseline_requires_exact_old_release_values():
    e,old,new=fixture();old['Config']['Env']=[v for v in old['Config']['Env'] if not v.startswith('PLATFORM_MANUFACTURING_RELEASE=')]+['PLATFORM_MANUFACTURING_RELEASE='+'e'*40]
    with pytest.raises(ValueError):release.validate_baseline(e,old)
