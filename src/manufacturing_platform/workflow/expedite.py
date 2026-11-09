"""Expedite cases route urgency across roles; balances stay with requirements."""
import json
from uuid import uuid4

from .authority import register_reader
from .commands import COMMAND_REGISTRY
from .contracts import MutationResult, ObjectRelation, ObjectSummary
from .expedite_models import (
    CloseExpedite,
    MaterialExpedite,
    OpenExpedite,
    ProgressExpedite,
)
from .laboratory import business, canonical
from .material_handoffs import actor_fact, applicable, trusted_name
from .orders import own
from .quality import fail

OPEN_ROLES = {"supply", "project_owner"}
PROGRESS_ROLES = OPEN_ROLES | {"warehouse", "production"}


def authorize(tx, actor, pid, command):
    if not command.action.startswith("expedite."):
        return
    if not applicable(tx, pid):
        fail("Expedites require an OEM project", 422)


def open_case(tx, context, command):
    requirement = own(tx, "requirements", context.project_id, command.requirement_id)
    if tx.execute(
        "SELECT 1 FROM material_expedites WHERE project_id=? AND requirement_id=? "
        "AND state='open'",
        (str(context.project_id), str(command.requirement_id)),
    ).fetchone():
        fail("An open expedite already exists for this requirement")
    ident = str(uuid4())
    profiles = context.subject_profiles or {}
    payload = business(command)
    payload.update(
        id=ident,
        work_order_id=requirement["work_order_id"],
        material_id=requirement["material_id"],
        owner_id=requirement["owner_id"],
        recorded_at=context.now.isoformat(),
        opened_by=str(context.actor.user_id),
        opened_by_name=trusted_name(
            context.actor.user_id,
            profiles.get(str(context.actor.user_id)),
            context.actor.display_name,
        ),
        expedite_number="EX-" + ident.upper(),
        source=dict(
            system="manual",
            object_type="material_expedite",
            external_id=ident,
            version=1,
            mode="manual",
            occurred_at=context.now.isoformat(),
            collected_at=context.now.isoformat(),
            evidence="Manual expedite opened by " + str(context.actor.user_id),
        ),
    )
    tx.execute(
        "INSERT INTO material_expedites(id,project_id,requirement_id,work_order_id,"
        "opened_by,state,payload_json) VALUES (?,?,?,?,?,?,?)",
        (
            ident, str(context.project_id), str(command.requirement_id),
            requirement["work_order_id"], str(context.actor.user_id), "open",
            canonical(payload),
        ),
    )
    return MutationResult(object_type="material_expedite", object_id=ident)


def progress(tx, context, command):
    row = own(tx, "material_expedites", context.project_id, command.expedite_id)
    if row["state"] != "open":
        fail("Only open expedites accept progress")
    tx.execute(
        "INSERT INTO expedite_progress(project_id,expedite_id,payload_json) VALUES (?,?,?)",
        (
            str(context.project_id), str(command.expedite_id),
            canonical(dict(note=command.note, **actor_fact(context))),
        ),
    )
    return MutationResult(object_type="material_expedite", object_id=command.expedite_id)


def close(tx, context, command):
    row = own(tx, "material_expedites", context.project_id, command.expedite_id)
    if row["state"] != "open":
        fail("Only open expedites may be closed")
    tx.execute(
        "UPDATE material_expedites SET state='closed',closure_json=? WHERE project_id=? AND id=?",
        (
            canonical(dict(outcome=command.outcome, reason=command.reason, **actor_fact(context))),
            str(context.project_id), str(command.expedite_id),
        ),
    )
    return MutationResult(object_type="material_expedite", object_id=command.expedite_id)


def milestones(tx, pid, payload):
    """Earliest linked fact per segment, same requirement chain only."""
    scope = (str(pid), payload["requirement_id"])
    result = dict(
        opened_at=payload["recorded_at"], arrival_at=None,
        receipt_at=None, inspection_at=None, handoff_at=None,
    )
    receipt = tx.execute(
        "SELECT r.created_at FROM supply_receipts r JOIN supply_commitments c "
        "ON c.id=r.commitment_id AND c.project_id=r.project_id "
        "WHERE r.project_id=? AND c.requirement_id=? ORDER BY r.created_at,r.id LIMIT 1",
        scope,
    ).fetchone()
    if not receipt:
        return result
    result["receipt_at"] = receipt["created_at"]
    arrival = tx.execute(
        "SELECT a.payload_json FROM arrivals a JOIN arrival_matches m "
        "ON m.arrival_id=a.id AND m.project_id=a.project_id "
        "JOIN supply_receipts r ON r.id=m.receipt_id AND r.project_id=m.project_id "
        "JOIN supply_commitments c ON c.id=r.commitment_id AND c.project_id=r.project_id "
        "WHERE m.project_id=? AND c.requirement_id=? ORDER BY m.seq LIMIT 1",
        scope,
    ).fetchone()
    if arrival:
        result["arrival_at"] = json.loads(arrival["payload_json"])["source"]["occurred_at"]
    inspection = tx.execute(
        "SELECT i.created_at FROM iqc_results i JOIN supply_receipts r "
        "ON r.id=i.receipt_id AND r.project_id=i.project_id "
        "JOIN supply_commitments c ON c.id=r.commitment_id AND c.project_id=r.project_id "
        "WHERE i.project_id=? AND c.requirement_id=? ORDER BY i.created_at,i.id LIMIT 1",
        scope,
    ).fetchone()
    if inspection:
        result["inspection_at"] = inspection["created_at"]
    handoff = tx.execute(
        "SELECT h.receipt_json FROM material_handoffs h JOIN supply_receipts r "
        "ON r.material_lot_id=h.material_lot_id AND r.project_id=h.project_id "
        "JOIN supply_commitments c ON c.id=r.commitment_id AND c.project_id=r.project_id "
        "WHERE h.project_id=? AND c.requirement_id=? AND h.receipt_json IS NOT NULL "
        "ORDER BY h.seq LIMIT 1",
        scope,
    ).fetchone()
    if handoff:
        result["handoff_at"] = json.loads(handoff["receipt_json"])["occurred_at"]
    return result


def value(tx, pid, row):
    payload = json.loads(row["payload_json"])
    return MaterialExpedite(
        **payload,
        state=row["state"],
        milestones=milestones(tx, pid, payload),
        progress=[
            json.loads(entry[0])
            for entry in tx.execute(
                "SELECT payload_json FROM expedite_progress WHERE project_id=? "
                "AND expedite_id=? ORDER BY seq",
                (str(pid), row["id"]),
            )
        ],
        closure=json.loads(row["closure_json"]) if row["closure_json"] else None,
    )


def summary(tx, pid, row):
    payload = json.loads(row["payload_json"])
    return ObjectSummary(
        id=row["id"],
        project_id=pid,
        kind="material_expedite",
        title=f"{payload['expedite_number']} · {payload['material_id']} · manual",
        state=row["state"],
        version=1 + bool(row["closure_json"]),
        source=payload["source"],
        blocking_reasons=[
            "Urgency routing only; availability stays with the requirement balance"
        ] if row["state"] == "open" else [],
        next_actions=(
            ["expedite.progress", "expedite.close"] if row["state"] == "open" else []
        ),
    )


def relations(item, pid):
    return [
        ObjectRelation(
            relation="requirement", project_id=pid, kind="requirement", id=item.requirement_id,
        ),
        ObjectRelation(
            relation="work_order", project_id=pid, kind="work_order", id=item.work_order_id,
        ),
    ]


for model, handler, roles in [
    (OpenExpedite, open_case, OPEN_ROLES),
    (ProgressExpedite, progress, PROGRESS_ROLES),
    (CloseExpedite, close, OPEN_ROLES),
]:
    COMMAND_REGISTRY.register(model, roles=roles, qualifications=set(), handler=handler)
register_reader("material_expedite", "material_expedites", MaterialExpedite, value, summary, relations)
