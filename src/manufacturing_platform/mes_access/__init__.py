"""Native MES access, isolated from demonstration business workflows."""
from .api import build_mes_access_router
from .service import MesAccessService


def build_mes_access_service(config_path: str, audit_path: str):
    """Construct without configuration, storage or network access."""
    return MesAccessService(config_path, audit_path)


__all__ = ['build_mes_access_router', 'build_mes_access_service', 'MesAccessService']
