"""Manufacturing business package; the host supplies identity and CSRF enforcement."""

from .api import build_router
from .production_tools.store import validate_snapshot_path
from .workflow import WORKFLOW_API_VERSION, build_workflow_router

NATIVE_PRODUCTION_PROTOCOL = 2


def build_native_config(config_path: str, snapshot_path: str):
    """Construct optional native readers only when trusted host settings request them."""
    from .production_tools.transports import build_native_config as factory

    return factory(config_path, snapshot_path)


def build_sap_access_service(config_path: str, audit_path: str):
    from .sap_access import build_sap_access_service as factory

    return factory(config_path, audit_path)


def build_sap_access_router(*, service, authorize):
    from .sap_access import build_sap_access_router as factory

    return factory(service=service, authorize=authorize)


def build_mes_access_service(config_path: str, audit_path: str):
    from .mes_access import build_mes_access_service as factory

    return factory(config_path, audit_path)


def build_mes_access_router(*, service, authorize):
    from .mes_access import build_mes_access_router as factory

    return factory(service=service, authorize=authorize)


__all__ = [
    "NATIVE_PRODUCTION_PROTOCOL",
    "WORKFLOW_API_VERSION",
    "build_native_config",
    "build_mes_access_router",
    "build_mes_access_service",
    "build_router",
    "build_sap_access_router",
    "build_sap_access_service",
    "build_workflow_router",
    "validate_snapshot_path",
]
