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

RELAY = {'config_path': '/app/data/manufacturing/sap-relay/config.json',
         'audit_path': '/app/data/manufacturing/sap-relay/audit.json'}


def request():
    return dict(platform_commit='d'*40, manufacturing_commit='b'*40,
                expected_old_platform_commit='c'*40, expected_old_manufacturing_commit='a'*40,
                target_sap_relay=copy.deepcopy(RELAY))


def test_exact_relay_paths_are_added_without_moving_existing_native_or_workflow():
    e = request()
    added = release.environment_delta(e)
    assert added['PLATFORM_MANUFACTURING_SAP_CONFIG_PATH'] == RELAY['config_path']
    assert added['PLATFORM_MANUFACTURING_SAP_AUDIT_PATH'] == RELAY['audit_path']
    assert not any('SAP_' in k for k in release.baseline_environment(e))
    e['baseline_sap_relay'] = copy.deepcopy(RELAY)
    assert release.baseline_environment(e)['PLATFORM_MANUFACTURING_SAP_CONFIG_PATH'] == RELAY['config_path']


@pytest.mark.parametrize('bad', [None, {}, {'config_path': RELAY['config_path']},
    {**RELAY, 'audit_path': RELAY['config_path']}, {**RELAY, 'config_path': '/tmp/config.json'},
    {**RELAY, 'token': 'must-not-be-in-release-request'}, {**RELAY, 'environment': 'production'}])
def test_release_request_cannot_expand_relay_paths_or_carry_credentials(bad):
    e = request(); e['target_sap_relay'] = bad
    with pytest.raises(ValueError):
        release.environment_delta(e)


def test_relay_upgrade_preserves_every_other_compose_field():
    before, after, options = fixture()
    env = {'PLATFORM_MANUFACTURING_SAP_CONFIG_PATH': RELAY['config_path'],
           'PLATFORM_MANUFACTURING_SAP_AUDIT_PATH': RELAY['audit_path']}
    options['environment_delta'].update(env)
    after['services']['platform-api']['environment'].update(env)
    saved = copy.deepcopy((before, after))
    guard.validate_upgrade_candidate(before, after, sap_relay_enabled=True, **options)
    assert saved == (before, after)
    with pytest.raises(ValueError):
        guard.validate_upgrade_candidate(before, after, **options)
    for mutate in (
        lambda x: x['services']['platform-api'].update(user='0'),
        lambda x: x['services']['platform-api']['volumes'].append({'type':'bind','source':'/tmp','target':'/extra'}),
        lambda x: x['services']['platform-api']['environment'].update(PLATFORM_MANUFACTURING_SAP_CONFIG_PATH='/other'),
        lambda x: x['services']['platform-api']['environment'].update(PLATFORM_MANUFACTURING_SAP_WRITE_ENABLED='1'),
        lambda x: x['services']['other'].update(image='changed'),
    ):
        changed = copy.deepcopy(after); mutate(changed)
        with pytest.raises(ValueError):
            guard.validate_upgrade_candidate(before, changed, sap_relay_enabled=True, **options)


def test_unchanged_existing_relay_cannot_be_silently_removed_or_reconfigured():
    e = request(); e['baseline_sap_relay'] = copy.deepcopy(RELAY)
    e['target_sap_relay'] = None
    with pytest.raises(ValueError):
        release.environment_delta(e)


@pytest.fixture
def private_state(monkeypatch):
    with tempfile.TemporaryDirectory(prefix='sr-', dir='/tmp') as name:
        root = Path(name).resolve(); directory = root/'sap-relay'; directory.mkdir(mode=0o700)
        bridge = directory/'bridge'; bridge.mkdir(mode=0o750)
        config = dict(version=1, transport='mac_read_relay', enabled=True, read_only=True,
            environment='test', socket_path='/app/data/manufacturing/sap-relay/bridge/active.sock',
            token_path='/app/data/manufacturing/sap-relay/token',
            expected_context={'source':{'system':'sap','origin':'native','fact_role':'observation',
                'environment':'test','system_id':'TST','client':'001','namespace':'c'*64},'fingerprint':'a'*64},
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
    pins = release.validate_sap_relay_storage(e)
    assert set(pins) == {'sap_relay_config', 'sap_relay_token'}
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
        release.validate_sap_relay_storage(e)
