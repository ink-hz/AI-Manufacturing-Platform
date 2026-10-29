"""Live manufacturing permissions from trusted host identity and project grants."""

import json
from dataclasses import dataclass

from .commands import BUSINESS_QUALIFICATIONS, BUSINESS_ROLES, COMMAND_REGISTRY
from .contracts import DomainError


@dataclass(frozen=True)
class EffectivePermissions:
    roles: frozenset[str]
    qualifications: frozenset[str]


def effective_permissions(tx, actor, project_id):
    """Global administrators need no grant rows; ordinary grants remain live."""
    if actor.configuration_admin:
        return EffectivePermissions(BUSINESS_ROLES, BUSINESS_QUALIFICATIONS)
    grant = tx.execute(
        "SELECT roles_json, qualifications_json FROM project_grants WHERE project_id=? AND user_id=? AND active=1",
        (str(project_id), str(actor.user_id)),
    ).fetchone()
    return EffectivePermissions(
        frozenset(json.loads(grant["roles_json"])) if grant else frozenset(),
        frozenset(json.loads(grant["qualifications_json"])) if grant else frozenset(),
    )


def require_project(tx, actor, project_id):
    row = tx.execute("SELECT * FROM projects WHERE id=?", (str(project_id),)).fetchone()
    if row is None or not effective_permissions(tx, actor, project_id).roles:
        raise DomainError("NOT_FOUND", 404, "Workflow resource not found")
    return row


def project_ids(tx, actor):
    if actor.configuration_admin:
        return [r[0] for r in tx.execute("SELECT id FROM projects ORDER BY id")]
    return [
        r[0]
        for r in tx.execute(
            "SELECT project_id FROM project_grants WHERE user_id=? AND active=1 AND roles_json!='[]' ORDER BY project_id",
            (str(actor.user_id),),
        )
    ]


def responsible_member(tx, actor, project_id, user_id):
    """Only the authenticated admin's own membership can be implicit.

    Other target responsibility still requires a real active project grant.
    Callers must separately resolve a real named directory profile.
    """
    if actor.configuration_admin and str(user_id) == str(actor.user_id):
        return True
    return (
        tx.execute(
            "SELECT 1 FROM project_grants WHERE project_id=? AND user_id=? AND active=1 AND roles_json!='[]'",
            (str(project_id), str(user_id)),
        ).fetchone()
        is not None
    )


def require_action(tx, actor, project_id, action):
    """Live initiating policy, shared by command orchestration and inbound admission."""
    require_project(tx, actor, project_id)
    permissions = effective_permissions(tx, actor, project_id)
    entry = COMMAND_REGISTRY.registration(action)
    if actor.read_only or not COMMAND_REGISTRY.permits(
        entry, permissions.roles, permissions.qualifications
    ):
        raise DomainError(
            "FORBIDDEN", 403, "Initiating business action permission denied"
        )
