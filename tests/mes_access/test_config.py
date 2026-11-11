from dataclasses import FrozenInstanceError
import json
import os
import pytest
from .conftest import implementation, SECRET


def load(path):
    return implementation('mes_connection').load_mes_connection_config(path)


def test_private_configuration_preserves_secret_and_hides_identity(config_file, raw_config):
    raw_config['password'] = '  ' + SECRET + '\n'
    config = load(config_file(raw_config))
    assert config.password == raw_config['password']
    assert config.username == 'test-user'
    assert SECRET not in repr(config) and 'test-user' not in repr(config)
    summary = json.dumps(config.summary())
    assert SECRET not in summary and 'test-user' not in summary
    assert config.summary()['credentials_configured'] is True
    with pytest.raises(FrozenInstanceError):
        config.enabled = False


@pytest.mark.parametrize('field,value', [
    ('system', 'sap'), ('version', True), ('version', 3), ('read_only', False),
    ('enabled', 'true'), ('allow_http_production', False), ('allow_http_production', 'true'),
    ('environment', 'other'), ('base_url', 'http://u:private@mes.example.test/'),
    ('base_url', 'http://mes.example.test/path'), ('base_url', 'http://mes.example.test/?q=1'),
    ('base_url', 'file:///tmp/secret'), ('base_url', 'http://mes.example.test/#x'),
    ('username', ' user'), ('username', ''), ('password', ''),
    ('connect_timeout_seconds', 0), ('read_timeout_seconds', 300),
    ('max_rows', True), ('max_rows', 0), ('max_rows', 6),
    ('max_response_bytes', 1), ('max_response_bytes', 3*1024*1024),
    ('site_code', '*'), ('site_code', ''),
    ('allowed_api_paths', ['https://evil.test/api']),
    ('allowed_api_paths', ['/../query.action']),
    ('allowed_api_paths', ['/a.action?x=1']),
])
def test_invalid_settings_fail_without_echoing_values(config_file, raw_config, field, value):
    raw_config[field] = value
    with pytest.raises(ValueError, match='^invalid MES connection configuration$') as caught:
        load(config_file(raw_config))
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize('mutation', ['extra', 'missing', 'duplicate', 'symlink', 'permissions', 'directory', 'hardlink'])
def test_configuration_file_boundary(config_file, raw_config, tmp_path, mutation):
    path = config_file()
    if mutation == 'extra':
        raw_config['url_override'] = 'secret'; path = config_file(raw_config)
    elif mutation == 'missing':
        del raw_config['password']; path = config_file(raw_config)
    elif mutation == 'duplicate':
        from pathlib import Path
        Path(path).write_text('{"version":2,"version":1}')
    elif mutation == 'symlink':
        link = tmp_path/'link.json'; link.symlink_to(path); path = str(link)
    elif mutation == 'permissions':os.chmod(path, 0o644)
    elif mutation == 'directory':path = str(tmp_path)
    elif mutation == 'hardlink':os.link(path, tmp_path/'other.json')
    with pytest.raises(ValueError, match='^invalid MES connection configuration$'):
        load(path)


def test_relative_path_is_rejected(config_file):
    config_file()
    with pytest.raises(ValueError):load('mes.json')


@pytest.mark.parametrize('key,value', [
    ('mode', 'none'), ('login_path', '/arbitrary'), ('username_field', 'x'),
    ('password_field', 'x'), ('session_cookie_name', 'other'), ('status', 'verified'),
    ('additional_form_fields', {'siteId': None, 'loginMode': 'other'}),
])
def test_login_contract_is_fixed(config_file, raw_config, key, value):
    raw_config['authentication'][key] = value
    with pytest.raises(ValueError):load(config_file(raw_config))


def test_legacy_configuration_loads_disabled_without_claiming_auth(config_file, raw_config):
    for key in ['allow_http_production','site_code','max_response_bytes','max_rows']:
        raw_config.pop(key)
    raw_config.update(version=1, enabled=False, allowed_api_paths=[])
    raw_config['authentication']['additional_form_fields'] = {'loginMode':None,'siteId':None}
    config = load(config_file(raw_config))
    assert config.version == 1 and not config.enabled
    assert config.summary()['authentication_verified'] is False


@pytest.mark.parametrize('origin', [
    'http://foreign.test/', 'https://foreign.test/', 'http://127.0.0.1/',
    'http://mes.orbbec.com:80/', 'https://mes.orbbec.com:443/',
    'http://mes.orbbec.com:8080/', 'ftp://mes.orbbec.com/',
])
def test_enabled_production_origin_is_user_authorized(config_file, raw_config, origin):
    raw_config['base_url'] = origin
    with pytest.raises(ValueError, match='^invalid MES connection configuration$'):
        load(config_file(raw_config))


@pytest.mark.parametrize('origin', ['http://mes.orbbec.com/', 'https://mes.orbbec.com/'])
def test_authorized_production_origin_loads(config_file, raw_config, origin):
    raw_config['base_url'] = origin
    assert load(config_file(raw_config)).base_url == origin


@pytest.mark.parametrize('environment', ['test', 'development'])
def test_offline_environment_accepts_custom_origin(config_file, raw_config, environment):
    raw_config.update(environment=environment, base_url='http://127.0.0.1:8765/')
    assert load(config_file(raw_config)).base_url == 'http://127.0.0.1:8765/'
