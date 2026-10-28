"""Bounded, allowlisted denial events routed to the host's existing logging sink.

No body, query, cookie, header, SQL, filesystem path or exception text is logged.
The host owns log rotation/retention; this library creates no file or service.
"""

import json
import logging
import re

logger = logging.getLogger("manufacturing_platform.workflow.security")


def log_denial(*, status: int, code: str, method: str, route: str, actor_id=None):
    event = {
        "event": "workflow_denied",
        "status": status,
        "code": re.sub(r"[^A-Z0-9_]", "_", code)[:64],
        "method": method
        if method in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
        else "OTHER",
        # route is the server-owned route template, never the raw request URL.
        "route": route[:200],
        "actor_id": str(actor_id) if actor_id is not None else None,
    }
    logger.warning(
        "%s",
        json.dumps(event, separators=(",", ":")),
        extra={"workflow_security": event},
    )
