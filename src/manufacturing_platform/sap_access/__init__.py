"""Native SAP access, mounted separately from demonstration business workflows."""
from .api import build_sap_access_router
from .service import SapAccessService


def build_sap_access_service(config_path: str, audit_path: str):
    """No I/O until an authenticated host request invokes a service method."""
    from .selector import SapAccessSelector
    return SapAccessSelector(config_path, audit_path)


__all__ = ['build_sap_access_router', 'build_sap_access_service', 'SapAccessService']
