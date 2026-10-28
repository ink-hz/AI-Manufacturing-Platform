"""Synthetic identity provider at the host's real authentication boundary."""

from datetime import UTC, datetime, timedelta
import json
import secrets
from uuid import NAMESPACE_URL, uuid4, uuid5

from app.control_plane.auth import AuthenticationError
from app.control_plane.models import AuthContext, IdentityMode, IssuedWebSession, Role

PREFIX = "/_preview/dingtalk-r1"


class SyntheticIdentity:
    mode = IdentityMode.PREVIEW
    route_prefix = PREFIX + "/"
    cookie_name = "platform_preview_session"
    csrf_cookie_name = "platform_preview_csrf"
    app_key = "isolated-synthetic-provider"
    corp_id = "isolated-no-employee-directory"

    def __init__(self, root, config, origin):
        self.root, self.config, self.public_base_url = root, config, origin
        self.repository = self
        self.sessions = {}

    def state(self):
        return json.loads((self.root / "identity-control.json").read_text())

    def identity(self, name):
        return uuid5(NAMESPACE_URL, f"fixture:{self.config['seed']}:{name}")

    def is_active_internal_user(self, uid):
        state = self.state()
        return any(self.identity(name) == uid and not details.get("revoked") for name, details in state.items())

    def active_internal_user_profiles(self, ids):
        return [{"user_id": str(self.identity(name)), "display_name": name} for name, details in self.state().items() if not details.get("revoked") and self.identity(name) in ids]

    async def complete_in_client(self, code, *, app_id="platform"):
        secret, _, name = code.partition(":")
        if not secrets.compare_digest(secret, self.config["secret"]) or name not in self.state() or self.state()[name].get("revoked") or app_id != "platform":
            raise AuthenticationError("Synthetic fixture credentials rejected")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        session = IssuedWebSession(uuid4(), token, csrf, now + timedelta(minutes=10), now + timedelta(minutes=15))
        self.sessions[token] = (name, session)
        return session

    def authenticate(self, token):
        current = self.sessions.get(token)
        if current is None:
            return None
        name, session = current
        details = self.state()[name]
        if details.get("revoked") or datetime.now(UTC) >= session.idle_expires_at:
            return None
        return AuthContext(self.identity(name), Role(details["role"]), session.session_id, details.get("hard_stale", False)), session.csrf_token

    def logout(self, context):
        self.sessions = {token: value for token, value in self.sessions.items() if value[1].session_id != context.session_id}

    def hard_stale_audit(self, *args):
        # Only the synthetic provider's bounded security audit boundary.
        with (self.root / "hard-stale-audit.jsonl").open("a") as stream:
            stream.write(json.dumps({"at": datetime.now(UTC).isoformat(), "args": list(map(str, args))}) + "\n")

    def account_snapshot(self, context):
        return {"display_name": "Synthetic fixture", "departments": [], "observation_agent_ids": [], "directory_freshness": "hard_stale" if context.hard_stale_read_only else "fresh"}


class NoObservationGrants:
    def permits(self, *args):
        return False
