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
