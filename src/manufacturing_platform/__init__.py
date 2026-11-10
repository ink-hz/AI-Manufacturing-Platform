"""Manufacturing business package; the host supplies identity and CSRF enforcement."""

from .api import build_router
from .production_tools.store import validate_snapshot_path
from .workflow import WORKFLOW_API_VERSION, build_workflow_router


def build_native_config(config_path: str, snapshot_path: str, dataset: dict[str, str]):
    """Construct optional native readers only when trusted host settings request them."""
    from .production_tools.transports import build_native_config as factory

    return factory(config_path, snapshot_path, dataset)


__all__ = [
    "WORKFLOW_API_VERSION",
    "build_native_config",
    "build_router",
    "build_workflow_router",
    "validate_snapshot_path",
]
