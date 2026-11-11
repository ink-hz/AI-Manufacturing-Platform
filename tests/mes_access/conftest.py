import json
import os
import importlib
from pathlib import Path
import pytest

PATHS = [
    '/venken/prodcpdb/prodcpdbAction!queryMshoporderresb.action',
    '/venken/prodcpdb/prodcpdbAction!queryMshoporderafvc.action',
    '/orbbec/orderItemGrade/orderItemGradeAction!query.action',
    '/venken/iqcTestInput/iqcTestInputAction!getList.action',
    '/venken/prodcpdb/prodcpdbAction!query.action',
    '/orbbec/wmsInventoryCheck/wmsInventoryCheckAction!query.action',
]
SECRET = 'TEST-PRIVATE-PASSWORD-DO-NOT-EXPOSE'


def implementation(name):
    try:
        return importlib.import_module('manufacturing_platform.' + name)
    except ModuleNotFoundError as exc:
        pytest.fail('MES implementation is missing: ' + str(exc.name))


@pytest.fixture
def raw_config():
    return {
        'version': 2, 'system': 'mes', 'base_url': 'http://mes.orbbec.com/',
        'environment': 'production', 'username': 'test-user', 'password': SECRET,
        'authentication': {
            'mode': 'form_session', 'status': 'not_verified',
            'login_path': '/j_spring_security_check', 'username_field': 'username',
            'password_field': 'password', 'additional_form_fields': {'loginMode': 'default', 'siteId': None},
            'session_cookie_name': 'JSESSIONID',
        },
        'connect_timeout_seconds': 5, 'read_timeout_seconds': 10,
        'enabled': True, 'read_only': True, 'allowed_api_paths': list(PATHS),
        'allow_http_production': True, 'site_code': '1000',
        'max_response_bytes': 65536, 'max_rows': 5,
    }


@pytest.fixture
def config_file(tmp_path, raw_config):
    def write(value=None):
        path = tmp_path / 'mes.json'
        path.write_text(json.dumps(raw_config if value is None else value))
        os.chmod(path, 0o600)
        return str(path)
    return write


@pytest.fixture
def config(config_file):
    return implementation('mes_connection').load_mes_connection_config(config_file())
