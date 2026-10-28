"""Manufacturing business package; the host supplies identity and CSRF enforcement."""

from .api import build_router
from .workflow import WORKFLOW_API_VERSION, build_workflow_router

__all__ = ["build_router", "WORKFLOW_API_VERSION", "build_workflow_router"]
