from .contracts import DomainError


def require_project(tx, actor, project_id):
    row = tx.execute("SELECT * FROM projects WHERE id=?", (str(project_id),)).fetchone()
    grant = tx.execute(
        "SELECT * FROM project_grants WHERE project_id=? AND user_id=? AND active=1 AND roles_json!='[]'",
        (str(project_id), str(actor.user_id)),
    ).fetchone()
    if row is None or grant is None:
        raise DomainError("NOT_FOUND", 404, "Workflow resource not found")
    return row


def require_action(tx, actor, project_id, action):
    """Live initiating policy, shared by command orchestration and inbound admission."""
    import json

    from .commands import COMMAND_REGISTRY

    require_project(tx, actor, project_id)
    grant = tx.execute(
        "SELECT * FROM project_grants WHERE project_id=? AND user_id=? AND active=1",
        (str(project_id), str(actor.user_id)),
    ).fetchone()
    entry = COMMAND_REGISTRY.registration(action)
    if actor.read_only or not COMMAND_REGISTRY.permits(
        entry, json.loads(grant["roles_json"]), json.loads(grant["qualifications_json"])
    ):
        raise DomainError(
            "FORBIDDEN", 403, "Initiating business action permission denied"
        )
