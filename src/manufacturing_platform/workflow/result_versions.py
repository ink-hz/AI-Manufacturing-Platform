"""Explicit adapters for immutable operation-result schema versions.

A1 project.create persisted an untagged v1 creation snapshot. It atomically
created only the project and creator grant, so its child quantities and stage
hints were empty at that instant. These are creation facts, never current state.
"""

import json
import hashlib
from decimal import Decimal

from .contracts import ProjectCreate, ProjectDetail, ProjectQuantitySummary
from .authorization import require_project

V1_FIELDS = frozenset({"id", "version", "name", "line_id", "product", "customer_id", "mode", "unit", "quantity", "contract", "legacy_project_id"})


def authorize_creation_replay(tx, actor, operation_id, operation_row, result):
    """Authorize original audit target before comparing the caller's new payload.

The historical operations schema has no target/action columns. Its original
canonical hash therefore binds the immutable creation audit, which supplies
the authoritative target. Caller fields and unvalidated result IDs cannot
select the authorization target.
    """
    rows = tx.execute(
        "SELECT project_id,object_id,action,typed_payload FROM audit_events "
        "WHERE actor_id=? "
        "AND json_extract(typed_payload,'$.operation_id')=?",
        (str(actor.user_id), str(operation_id)),
    ).fetchall()
    if len(rows) != 1:
        raise ValueError("Creation replay lacks unique original audit binding")
    audit = rows[0]
    original = json.loads(audit["typed_payload"])
    original_hash = hashlib.sha256(
        json.dumps(original, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    if (
        original.get("action") != audit["action"]
        or original_hash != operation_row["payload_hash"]
    ):
        raise ValueError("Creation replay does not match original target")
    if audit["action"] == "project.create":
        if audit["project_id"] != audit["object_id"] or result.get("id") != audit["project_id"]:
            raise ValueError("Creation replay does not match original target")
    elif original.get("project_id") != audit["project_id"]:
        raise ValueError("Conflicting operation does not match original target")
    require_project(tx, actor, audit["project_id"])


def project_creation_result(tx, actor, payload, result):
    if set(result) != V1_FIELDS:
        return ProjectDetail.model_validate(result)
    if payload.get("action") != "project.create" or result["version"] != 1:
        raise ValueError("Unrecognized historical creation result")
    request = ProjectCreate.model_validate({k: v for k, v in payload.items() if k != "action"})
    expected = request.model_dump(mode="json", exclude={"operation_id"})
    # A1 formats result quantities at unit scale ("100" -> "100.00").
    # Both values must pass the same finite, positive, exact-scale parser;
    # the caller's original string/hash is still checked unchanged by _replay.
    saved_quantity = ProjectCreate.model_validate({
        **request.model_dump(mode="json"), "quantity": result["quantity"]
    }).quantity
    expected.pop("quantity")
    if {k: result[k] for k in expected} != expected or saved_quantity != request.quantity:
        raise ValueError("Historical creation result does not match original request")
    history = tx.execute(
        "SELECT typed_payload FROM audit_events WHERE project_id=? AND object_id=? AND actor_id=? AND action='project.create'",
        (result["id"], result["id"], str(actor.user_id)),
    ).fetchall()
    if len(history) != 1 or json.loads(history[0][0]) != payload:
        raise ValueError("Historical creation result lacks original audit binding")
    return ProjectDetail.model_validate({
        **result,
        "stages": [],
        "summary": {
            key: format(Decimal(0).scaleb(-request.unit.scale), "f")
            for key in ProjectQuantitySummary.model_fields
        },
    })
