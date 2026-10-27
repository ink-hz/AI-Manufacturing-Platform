"""Manufacturing business package; the host supplies identity and CSRF enforcement."""

from .api import build_router

__all__ = ["build_router"]
