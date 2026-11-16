"""Relay rollout adds only two fixed private settings to the existing data mount."""
import copy
import sys
import os
import json
import socket
import tempfile
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import release
import release_guard as guard
from test_release_upgrade import fixture

RELAY = {'config_path': '/app/data/manufacturing/mes-relay/config.json',
         'audit_path': '/app/data/manufacturing/mes-relay/audit.json'}


def request():
    return dict(platform_commit='d'*40, manufacturing_commit='b'*40,
                expected_old_platform_commit='c'*40, expected_old_manufacturing_commit='a'*40,
                target_mes_relay=copy.deepcopy(RELAY))


def test_exact_relay_paths_are_added_without_moving_existing_native_or_workflow():
    e = request()
    added = release.environment_delta(e)
    assert added['PLATFORM_MANUFACTURING_MES_CONFIG_PATH'] == RELAY['config_path']
    assert added['PLATFORM_MANUFACTURING_MES_AUDIT_PATH'] == RELAY['audit_path']
    assert not any('MES_' in k for k in release.baseline_environment(e))
    e['baseline_mes_relay'] = copy.deepcopy(RELAY)
    assert release.baseline_environment(e)['PLATFORM_MANUFACTURING_MES_CONFIG_PATH'] == RELAY['config_path']


@pytest.mark.parametrize('bad', [None, {}, {'config_path': RELAY['config_path']},
    {**RELAY, 'audit_path': RELAY['config_path']}, {**RELAY, 'config_path': '/tmp/config.json'},
    {**RELAY, 'token': 'must-not-be-in-release-request'}, {**RELAY, 'environment': 'production'}])
def test_release_request_cannot_expand_relay_paths_or_carry_credentials(bad):
    e = request(); e['target_mes_relay'] = bad
    with pytest.raises(ValueError):
        release.environment_delta(e)


def test_relay_upgrade_preserves_every_other_compose_field():
    before, after, options = fixture()
    env = {'PLATFORM_MANUFACTURING_MES_CONFIG_PATH': RELAY['config_path'],
           'PLATFORM_MANUFACTURING_MES_AUDIT_PATH': RELAY['audit_path']}
    options['environment_delta'].update(env)
    after['services']['platform-api']['environment'].update(env)
    saved = copy.deepcopy((before, after))
    guard.validate_upgrade_candidate(before, after, mes_relay_enabled=True, **options)
    assert saved == (before, after)
    with pytest.raises(ValueError):
        guard.validate_upgrade_candidate(before, after, **options)
    for mutate in (
        lambda x: x['services']['platform-api'].update(user='0'),
        lambda x: x['services']['platform-api']['volumes'].append({'type':'bind','source':'/tmp','target':'/extra'}),
        lambda x: x['services']['platform-api']['environment'].update(PLATFORM_MANUFACTURING_MES_CONFIG_PATH='/other'),
        lambda x: x['services']['platform-api']['environment'].update(PLATFORM_MANUFACTURING_MES_WRITE_ENABLED='1'),
        lambda x: x['services']['other'].update(image='changed'),
    ):
        changed = copy.deepcopy(after); mutate(changed)
        with pytest.raises(ValueError):
            guard.validate_upgrade_candidate(before, changed, mes_relay_enabled=True, **options)


def test_unchanged_existing_relay_cannot_be_silently_removed_or_reconfigured():
    e = request(); e['baseline_mes_relay'] = copy.deepcopy(RELAY)
    e['target_mes_relay'] = None
    with pytest.raises(ValueError):
        release.environment_delta(e)


@pytest.fixture
def private_state(monkeypatch):
    with tempfile.TemporaryDirectory(prefix='sr-', dir='/tmp') as name:
        root = Path(name).resolve(); directory = root/'mes-relay'; directory.mkdir(mode=0o700)
        bridge = directory/'bridge'; bridge.mkdir(mode=0o750)
        config = dict(version=1, transport='mac_read_relay', enabled=True, read_only=True,
            environment='production', socket_path='/app/data/manufacturing/mes-relay/bridge/active.sock',
            token_path='/app/data/manufacturing/mes-relay/token',
            expected_context={'source':{'system':'mes','origin':'native','fact_role':'observation',
                'environment':'production','site_code':'SITE-A','namespace':'c'*64},'fingerprint':'a'*64},
            timeout_seconds=70, max_response_bytes=2097152)
        (directory/'config.json').write_text(json.dumps(config)); (directory/'config.json').chmod(0o600)
        (directory/'token').write_text('b'*64); (directory/'token').chmod(0o600)
        endpoint = bridge/'r-0123456789abcdef.sock'
        listener = socket.socket(socket.AF_UNIX); listener.bind(str(endpoint)); endpoint.chmod(0o660)
        (bridge/'active.sock').symlink_to(endpoint.name)
        def metadata(path):
            info = path.lstat(); values = list(info)
            values[4] = 0 if path == bridge or path.parent == bridge else 10001
            values[5] = 10001
            return os.stat_result(values)
        monkeypatch.setattr(release, 'trusted_stat', metadata)
        try:
            yield {**request(), 'data_host': str(root)}, directory
        finally:
            listener.close()


def test_relay_storage_pins_only_private_config_and_token(private_state):
    e, directory = private_state
    pins = release.validate_mes_relay_storage(e)
    assert set(pins) == {'mes_relay_config', 'mes_relay_token'}
    assert all(len(value) == 64 for value in pins.values())
    # A reconnect may change a socket; it cannot change the registered token/config pins.
    assert 'active.sock' not in str(pins)


@pytest.mark.parametrize('change', [
    lambda d:(d/'token').chmod(0o644),
    lambda d:(d/'config.json').write_text('{"transport":"soap_http","password":"forbidden"}'),
    lambda d:(d/'token').write_text('not-a-token'),
    lambda d:(d/'bridge/active.sock').unlink(),
])
def test_invalid_private_state_cannot_be_deployed(private_state, change):
    e, directory = private_state; change(directory)
    with pytest.raises(ValueError):
        release.validate_mes_relay_storage(e)


def change_config(directory, mutate):
    path=directory/'config.json'; config=json.loads(path.read_text()); mutate(config)
    path.write_text(json.dumps(config))


@pytest.mark.parametrize('mutate', [
    lambda c:c.update(version=True), lambda c:c.update(enabled=False),
    lambda c:c.update(read_only=False), lambda c:c.update(environment='unknown'),
    lambda c:c.update(url='https://source.invalid',password='secret'),
    lambda c:c.update(token_path='/app/data/manufacturing/sap-relay/token'),
    lambda c:c.update(socket_path='/tmp/active.sock'),
    lambda c:c.update(timeout_seconds=True), lambda c:c.update(max_response_bytes=2097153),
    lambda c:c['expected_context'].update(fingerprint='z'*64),
    lambda c:c['expected_context']['source'].update(system='sap'),
    lambda c:c['expected_context']['source'].update(origin='cache'),
    lambda c:c['expected_context']['source'].update(fact_role='authority'),
    lambda c:c['expected_context']['source'].update(environment='test'),
    lambda c:c['expected_context']['source'].update(namespace='bad'),
    lambda c:c['expected_context']['source'].update(site_code='https://source.invalid'),
    lambda c:c['expected_context']['source'].update(password='secret'),
])
def test_private_config_rejects_source_scope_and_transport_expansion(private_state,mutate):
    e,directory=private_state; change_config(directory,mutate)
    with pytest.raises(ValueError):release.validate_mes_relay_storage(e)


def test_audit_storage_is_bounded(private_state):
    e,directory=private_state; audit=directory/'audit.json'
    with audit.open('wb') as stream:stream.truncate(5*1024*1024+1)
    audit.chmod(0o600)
    with pytest.raises(ValueError):release.validate_mes_relay_storage(e)


def test_socket_inode_cannot_be_aliased(private_state):
    e,directory=private_state
    os.link(directory/'bridge/r-0123456789abcdef.sock',directory/'bridge/alias.sock')
    with pytest.raises(ValueError):release.validate_mes_relay_storage(e)


def test_existing_mes_configuration_carries_forward_with_other_profiles():
    from test_sap_relay_release import RELAY as SAP
    import native_release
    e=request();e.pop('target_mes_relay');e['baseline_mes_relay']=copy.deepcopy(RELAY)
    e['baseline_sap_relay']=copy.deepcopy(SAP)
    e['baseline_native']=copy.deepcopy(native_release.NATIVE_PATHS)
    new=release.environment_delta(e);old=release.baseline_environment(e)
    for key in ('PLATFORM_MANUFACTURING_MES_CONFIG_PATH','PLATFORM_MANUFACTURING_MES_AUDIT_PATH',
                *guard.SAP_RELAY_FIELDS.values(),*native_release.NATIVE_FIELDS.values()):
        assert new[key]==old[key]


def test_legacy_request_has_no_mes_settings_or_storage_reads():
    e=request();e.pop('target_mes_relay')
    assert not set(guard.MES_RELAY_FIELDS.values()) & set(release.environment_delta(e))
    assert release.validate_mes_relay_storage(e)=={}


def test_existing_mes_upgrade_cannot_drop_routing():
    before,after,options=fixture()
    env=guard.mes_relay_environment(RELAY)
    before['services']['platform-api']['environment'].update(env)
    options['baseline_environment'].update(env)
    with pytest.raises(ValueError):guard.validate_upgrade_candidate(before,after,mes_relay_enabled=True,**options)


@pytest.mark.parametrize('name', ['config.json','token','audit.json','audit.json.lock'])
def test_private_files_cannot_be_symlinks_or_hardlinks(private_state,name):
    e,directory=private_state; path=directory/name
    if not path.exists():path.write_text('{}');path.chmod(0o600)
    saved=directory/(name+'.saved');path.rename(saved);path.symlink_to(saved.name)
    with pytest.raises(ValueError):release.validate_mes_relay_storage(e)
    path.unlink();os.link(saved,path)
    with pytest.raises(ValueError):release.validate_mes_relay_storage(e)


@pytest.mark.parametrize('target', ['../token','/tmp/r-0123456789abcdef.sock','r-short.sock'])
def test_bridge_target_is_one_relative_session_socket(private_state,target):
    e,directory=private_state; active=directory/'bridge/active.sock';active.unlink();active.symlink_to(target)
    with pytest.raises(ValueError):release.validate_mes_relay_storage(e)


def test_reconnect_rotates_socket_without_changing_private_identity(private_state):
    e,directory=private_state; pins=release.validate_mes_relay_storage(e)
    endpoint=directory/'bridge/r-fedcba9876543210.sock'
    listener=socket.socket(socket.AF_UNIX)
    try:
        listener.bind(str(endpoint));endpoint.chmod(0o660)
        active=directory/'bridge/active.sock';active.unlink();active.symlink_to(endpoint.name)
        assert release.validate_mes_relay_storage(e)==pins
        (directory/'token').write_text('e'*64)
        assert release.validate_mes_relay_storage(e)['mes_relay_token']!=pins['mes_relay_token']
    finally:listener.close()



def test_adding_mes_preserves_existing_sap_relay():
    before,after,options=fixture()
    sap=guard.sap_relay_environment(guard.SAP_RELAY_PATHS)
    mes=guard.mes_relay_environment(RELAY)
    for row in (options['baseline_environment'],options['environment_delta'],
                before['services']['platform-api']['environment'],after['services']['platform-api']['environment']):row.update(sap)
    options['environment_delta'].update(mes);after['services']['platform-api']['environment'].update(mes)
    guard.validate_upgrade_candidate(before,after,sap_relay_enabled=True,mes_relay_enabled=True,**options)


from test_sap_relay_release import private_state as sap_private_state


def test_sap_production_remains_rejected(sap_private_state):
    e,directory=sap_private_state
    change_config(directory,lambda c:(c.update(environment='production'),
        c['expected_context']['source'].update(environment='production')))
    with pytest.raises(ValueError,match='sap_relay_config_mode'):release.validate_sap_relay_storage(e)


def test_invalid_environment_type_is_rejected_as_policy_error(private_state):
    e,directory=private_state;change_config(directory,lambda c:c.update(environment=[]))
    with pytest.raises(ValueError):release.validate_mes_relay_storage(e)
