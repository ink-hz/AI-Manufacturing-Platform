import importlib.util
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from manufacturing_platform import build_sap_access_router, build_sap_access_service


def test_public_host_mount_does_not_read_config_until_authorized(tmp_path):
    service = build_sap_access_service(str(tmp_path/'absent.json'), str(tmp_path/'audit.json'))
    app = FastAPI()
    app.include_router(build_sap_access_router(service=service, authorize=lambda request, write: {
        'user_id': 'operator', 'read_only': False, 'configuration_admin': False}))
    with TestClient(app) as http:
        response = http.post('/api/v1/manufacturing/sap/diagnostics/ping', content=b'bad-json')
        assert response.status_code == 403
        assert response.json() == {'code': 'SAP_FORBIDDEN'}
        assert response.headers['cache-control'] == 'private, no-store'
    assert not (tmp_path/'audit.json').exists()


def test_cli_requires_explicit_live_flag_before_any_config_access(tmp_path):
    script = Path(__file__).parents[2]/'scripts'/'verify_sap_access.py'
    spec = importlib.util.spec_from_file_location('sap_cli', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import pytest
    with pytest.raises(SystemExit) as error:
        module.main(['ping', '--config', str(tmp_path/'absent'), '--audit', str(tmp_path/'audit')])
    assert error.value.code == 2
    assert not (tmp_path/'audit.lock').exists()


def test_platform_factory_places_optional_sap_before_legacy_catchall(tmp_path):
    from manufacturing_platform import build_router

    class Service:
        def status(self):
            return {'source': 'native_sap', 'business_data_verified': False}

    app = FastAPI()
    app.include_router(build_router(database_path=str(tmp_path/'db'), assets_dir=str(tmp_path/'assets'),
        authorize=lambda request, write: {'user_id': 'admin', 'display_name': 'Admin',
            'read_only': False, 'configuration_admin': True}, sap_access=Service()))
    with TestClient(app) as http:
        response = http.get('/api/v1/manufacturing/sap/status')
        assert response.status_code == 200
        assert response.json()['source'] == 'native_sap'
        assert http.get('/api/v1/manufacturing/access').status_code == 200
