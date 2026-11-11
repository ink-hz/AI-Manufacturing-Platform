"""Configuration checks never contact SAP or expose future credentials."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module():
    path = ROOT / 'src/manufacturing_platform/sap_connection.py'
    assert path.exists(), 'SAP configuration loader has not been implemented'
    spec = importlib.util.spec_from_file_location('sap_connection', path)
    value = importlib.util.module_from_spec(spec)
    # dataclasses resolves the defining module while creating a class.
    import sys
    sys.modules[spec.name] = value
    spec.loader.exec_module(value)
    return value


def settings():
    return dict(version=1, transport='rfc', environment='test', application_server='10.10.16.247',
                system_number='10', system_id='S4D', client='300', username='', password='',
                enabled=False, read_only=True, allowed_functions=[])


def write_config(tmp_path, value=None):
    path = tmp_path / 'sap.json'
    path.write_text(json.dumps(settings() if value is None else value))
    path.chmod(0o600)
    return path


def test_user_parameters_load_without_credentials(tmp_path):
    config = module().load_sap_connection_config(str(write_config(tmp_path)))
    assert (config.application_server, config.system_number, config.system_id, config.client) == ('10.10.16.247', '10', 'S4D', '300')
    assert config.summary()['credentials_configured'] is False
    assert config.summary()['enabled'] is False
    assert config.summary()['authentication_verified'] is False


def test_credentials_are_preserved_but_not_printed(tmp_path):
    value = {**settings(), 'username': 'SYNTHETIC-USER', 'password': 'SYNTHETIC-SECRET-\"$&\\'}
    config = module().load_sap_connection_config(str(write_config(tmp_path, value)))
    assert config.password == value['password']
    assert config.summary()['credentials_configured'] is True
    text = repr(config) + json.dumps(config.summary())
    assert value['password'] not in text and value['username'] not in text
    assert config.summary()['authentication_verified'] is False


@pytest.mark.parametrize('change', [
    {'enabled': True}, {'read_only': False}, {'system_number': 10}, {'system_number': '1'},
    {'client': 300}, {'client': '30'}, {'application_server': 'https://10.10.16.247'},
    {'version': True}, {'password': 123}, {'unknown': 'SYNTHETIC-SECRET'},
    {'allowed_functions': ['*']}, {'allowed_functions': ['RFC_PING', 'RFC_PING']},
])
def test_invalid_settings_fail_with_a_safe_message(tmp_path, change):
    with pytest.raises(ValueError, match='^invalid SAP connection configuration$') as error:
        module().load_sap_connection_config(str(write_config(tmp_path, {**settings(), **change})))
    assert 'SYNTHETIC-SECRET' not in str(error.value)


def test_enabled_config_requires_credentials_and_explicit_functions(tmp_path):
    value = {**settings(), 'enabled': True, 'username': 'DEMO', 'password': 'SYNTHETIC-SECRET'}
    with pytest.raises(ValueError):
        module().load_sap_connection_config(str(write_config(tmp_path, value)))
    value['allowed_functions'] = ['Z_DEMO_READ']
    config = module().load_sap_connection_config(str(write_config(tmp_path, value)))
    assert config.enabled and config.summary()['authentication_verified'] is False


def test_private_file_permissions_and_symlinks_are_checked(tmp_path):
    path = write_config(tmp_path)
    path.chmod(0o644)
    with pytest.raises(ValueError): module().load_sap_connection_config(str(path))
    path.chmod(0o600)
    alias = tmp_path / 'alias.json'; alias.symlink_to(path)
    with pytest.raises(ValueError): module().load_sap_connection_config(str(alias))
    with pytest.raises(ValueError): module().load_sap_connection_config('relative.json')


def test_duplicate_keys_are_rejected(tmp_path):
    path = write_config(tmp_path)
    path.write_text('{"password":"SYNTHETIC-SECRET","password":"other"}')
    with pytest.raises(ValueError, match='^invalid SAP connection configuration$'):
        module().load_sap_connection_config(str(path))


def test_cli_reports_missing_credentials_without_network(tmp_path, capsys):
    module()
    path = ROOT / 'scripts/check_sap_config.py'
    assert path.exists(), 'SAP offline check command has not been implemented'
    spec = importlib.util.spec_from_file_location('check_sap_config', path)
    cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
    assert cli.main(['--config', str(write_config(tmp_path))]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['configuration_valid'] and not output['credentials_configured']
    assert output['authentication_verified'] is False
    assert cli.main(['--config', str(tmp_path / 'missing')]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output == {'configuration_valid': False, 'error': 'INVALID_SAP_CONFIGURATION'}
