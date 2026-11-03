"""Server-only profile initialization; never reinterpret persisted intent routing."""

from uuid import UUID

from ..contracts import DomainError
from .core_models import ProfileId

_ROUTES = {
    "reservation.request": "wms",
    "stock.proof": "wms",
    "stock_basis.reconcile": "wms",
    "shipment.request": "wms",
    "production.start": "mes",
    "production.interrupt": "mes",
    "production.resume": "mes",
    "eco.switch": "mes",
    "freeze.request": "mes",
}


def profile_for(tx, project_id: UUID) -> ProfileId:
    row = tx.execute(
        "SELECT profile FROM project_integration_profiles WHERE project_id=?",
        (str(project_id),),
    ).fetchone()
    return row[0] if row else "legacy-erp-v1"


def assign_profile(tx, project_id: UUID, profile: ProfileId) -> None:
    if profile not in {"legacy-erp-v1", "oem-network-v1"}:
        raise ValueError("unknown integration profile")
    metadata = tx.execute("SELECT mode FROM dataset_metadata").fetchone()
    if not metadata or metadata[0] not in {"demo", "test"}:
        raise DomainError(
            "MOCK_UNAVAILABLE",
            403,
            "profile initialization is demo/test maintenance only",
        )
    pid = str(project_id)
    if not tx.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone():
        raise DomainError("NOT_FOUND", 404, "project not found")
    previous = tx.execute(
        "SELECT profile FROM project_integration_profiles WHERE project_id=?", (pid,)
    ).fetchone()
    if previous:
        if previous[0] == profile:
            return
        raise DomainError(
            "PROFILE_IMMUTABLE", 409, "project integration profile is immutable"
        )
    used = tx.execute(
        "SELECT 1 FROM audit_events WHERE project_id=? AND action!='project.create' LIMIT 1",
        (pid,),
    ).fetchone()
    used = (
        used
        or tx.execute(
            "SELECT 1 FROM exchanges WHERE project_id=? LIMIT 1", (pid,)
        ).fetchone()
    )
    used = (
        used
        or tx.execute(
            "SELECT 1 FROM integration_intents WHERE project_id=? LIMIT 1", (pid,)
        ).fetchone()
    )
    if used:
        raise DomainError("PROFILE_IMMUTABLE", 409, "project already has domain intent")
    tx.execute(
        "INSERT INTO project_integration_profiles(project_id,profile) VALUES (?,?)",
        (pid, profile),
    )


def route(profile: ProfileId, action: str) -> str:
    if profile == "legacy-erp-v1":
        return "erp"
    if profile != "oem-network-v1" or action not in _ROUTES:
        raise ValueError("unsupported profile or routed action")
    return _ROUTES[action]
