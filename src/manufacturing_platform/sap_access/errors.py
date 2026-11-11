"""Safe failures shared by the standalone SAP access layer and its host API."""
import re


class SapAccessError(Exception):
    """Carry a symbolic code and HTTP status, never an upstream message or body."""

    def __init__(self, code: str, status: int = 503):
        self.code = (
            code if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code)
            else "SAP_ACCESS_ERROR"
        )
        self.status = status if type(status) is int and 400 <= status <= 599 else 503
        super().__init__(self.code)
