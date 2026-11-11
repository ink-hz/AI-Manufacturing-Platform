"""Host mounting order and lazy public exports."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from .test_api import ADMIN, BASE, Service, private


def test_public_builders_are_lazy(tmp_path, monkeypatch):
    import manufacturing_platform as package
    import manufacturing_platform.mes_connection as connection
    import manufacturing_platform.mes_access as mes
    def fail(*args, **kwargs): raise AssertionError('builder read configuration')
    monkeypatch.setattr(connection, 'load_mes_connection_config', fail)
    assert callable(getattr(package, 'build_mes_access_service', None))
    assert callable(getattr(package, 'build_mes_access_router', None))
    for owner in (package, mes):
        service = owner.build_mes_access_service(str(tmp_path/'missing'), str(tmp_path/'audit'))
        assert service.config_path == str(tmp_path/'missing')
        assert owner.build_mes_access_router(service=service, authorize=lambda request, write: ADMIN)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('with_sap', [False, True])
def test_mes_mount_precedes_legacy_fallback_and_preserves_sap(tmp_path, with_sap):
    from manufacturing_platform import build_router
    mes, sap, calls = Service(), Service(), []
    def authorize(request, *, write):
        calls.append(request.url.path)
        return ADMIN.copy()
    app = FastAPI()
    app.include_router(build_router(database_path=str(tmp_path/'absent-db'), assets_dir=str(tmp_path/'absent-assets'),
        authorize=authorize, mes_access=mes, sap_access=sap if with_sap else None))
    client = TestClient(app)
    for path, status in [('/status', 200), ('/config',404), ('',404)]:
        assert private(client.get(BASE + path)).status_code == status
    assert mes.calls == [('status',)]
    assert len(calls) == 3
    if with_sap:
        assert private(client.get('/api/v1/manufacturing/sap/status')).status_code == 200
        assert sap.calls == [('status',)]
    assert client.get('/api/v1/manufacturing/access').status_code == 200
    assert not list(tmp_path.iterdir())


def test_unauthorized_real_service_never_reads_configuration_or_audit(tmp_path, monkeypatch):
    from manufacturing_platform import build_mes_access_service, build_mes_access_router
    import manufacturing_platform.mes_access.service as service_module
    io_calls = []
    def fail(*args, **kwargs):
        io_calls.append(args)
        raise AssertionError('authorization must precede configuration and audit access')
    monkeypatch.setattr(service_module, 'load_mes_connection_config', fail)
    monkeypatch.setattr(service_module, 'MesAuditStore', fail)
    service = build_mes_access_service(str(tmp_path/'missing'), str(tmp_path/'audit'))
    app = FastAPI()
    app.include_router(build_mes_access_router(service=service,
        authorize=lambda request, write: {**ADMIN, 'configuration_admin':False}))
    response = private(TestClient(app).post(BASE + '/interfaces/order_materials/query', content=b'bad-json'))
    assert response.status_code == 403
    assert not io_calls
    assert not list(tmp_path.iterdir())
