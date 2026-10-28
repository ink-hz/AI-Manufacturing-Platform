"""Opt-in configuration is isolated from baseline and candidate-only inputs."""
import os
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).parents[1]))
import release
from test_release_upgrade import fixture

CONFIG = {'database_path':'/app/data/manufacturing/workflow-demo.sqlite3', 'authority_database_path':'/app/data/manufacturing/authority-demo.sqlite3', 'dataset_id':'workflow-demo-v1', 'dataset_mode':'demo', 'dataset_label':'全流程模拟环境'}
KEYS = {'PLATFORM_MANUFACTURING_' + k for k in ('WORKFLOW_DATABASE_PATH','AUTHORITY_DATABASE_PATH','DATASET_ID','DATASET_MODE','DATASET_LABEL')}

def request():
    return {'mode':'upgrade','platform_commit':'a'*40,'manufacturing_commit':'b'*40,'expected_old_platform_commit':'c'*40,'expected_old_manufacturing_commit':'d'*40}

def test_target_opt_in_does_not_contaminate_baseline():
    e={**request(),'target_workflow':CONFIG}
    assert set(release.environment_delta(e)) - set(release.environment_delta(request())) == KEYS
    assert not KEYS & release.baseline_environment(e).keys()
    assert release.workflow_configuration({**e,'baseline_workflow':CONFIG}, baseline=True)==CONFIG

def test_existing_workflow_is_preserved_and_cannot_be_repointed_or_disabled():
    e={**request(),'baseline_workflow':CONFIG}
    assert release.environment_delta(e)==release.environment_delta({**e,'target_workflow':CONFIG})
    for target in (None, {**CONFIG,'dataset_id':'new'}, {**CONFIG,'database_path':'/app/data/manufacturing/new.sqlite3'}):
        with pytest.raises(ValueError):release.environment_delta({**e,'target_workflow':target})

@pytest.mark.parametrize('change', [None, {}, {'unexpected':'value'}, {'dataset_mode':'test'}, {'dataset_mode':'production','dataset_label':'demo'}, {'dataset_id':'bad id'}, {'dataset_label':''}, {'database_path':'/tmp/file.db'}, {'database_path':'/app/data/manufacturing/../manufacturing/file.db'}, {'database_path':CONFIG['authority_database_path']}, {'database_path':'/app/data/manufacturing/workbench.sqlite3'}])
def test_partial_unknown_or_unsafe_config_is_rejected(change):
    target=change if change is None or not change else {**CONFIG,**change}
    with pytest.raises(ValueError):release.environment_delta({**request(),'target_workflow':target})

def test_paths_reject_symlinks_and_hardlinks_before_any_database_write(tmp_path):
    e={**request(),'target_workflow':CONFIG,'data_host':str(tmp_path)}
    legacy=tmp_path/'workbench.sqlite3';legacy.write_text('keep')
    domain=tmp_path/'workflow-demo.sqlite3';domain.symlink_to(legacy)
    with pytest.raises(ValueError):release.validate_workflow_storage(e)
    domain.unlink();os.link(legacy,domain)
    with pytest.raises(ValueError):release.validate_workflow_storage(e)
    assert legacy.read_text()=='keep'

def test_guard_checks_expected_absence_and_preserves_security():
    before,after,options=fixture()
    env={k:v for k,v in release.environment_delta({**request(),'target_workflow':CONFIG}).items() if k in KEYS}
    options['environment_delta'].update(env);after['services']['platform-api']['environment'].update(env)
    release.validate_upgrade_candidate(before,after,**options)
    before['services']['platform-api']['environment'].update(env)
    with pytest.raises(ValueError):release.validate_upgrade_candidate(before,after,**options)
    before,after,options=fixture()
    options['environment_delta']['WORKFLOW_E30_COMMAND']='private';after['services']['platform-api']['environment']['WORKFLOW_E30_COMMAND']='private'
    with pytest.raises(ValueError):release.validate_upgrade_candidate(before,after,**options)
