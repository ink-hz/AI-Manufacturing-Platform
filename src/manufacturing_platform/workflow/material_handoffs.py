"""Manual physical handoff transitions; no inventory or authority writes."""
import json
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from .authorization import effective_permissions, require_project
from .commands import COMMAND_REGISTRY
from .contracts import DomainError, MutationResult
from .laboratory import business, canonical
from .material_handoff_models import (
    CancelMaterialHandoff,
    ConfirmMaterialReceiptUse,
    ReceiveMaterialHandoff,
    RecordMaterialHandoff,
    ResolveMaterialHandoff,
)
from .orders import own
from .quality import fail
from .supply import atoms

CREATE_ROLES = {"warehouse", "supply", "production"}
RECEIVE_ROLES = CREATE_ROLES | {"project_owner"}


def receiver_member(tx, actor, pid, uid):
    if actor.configuration_admin and str(uid) == str(actor.user_id):
        return True
    row = tx.execute(
        "SELECT roles_json FROM project_grants WHERE project_id=? AND user_id=? AND active=1",
        (str(pid), str(uid)),
    ).fetchone()
    return bool(row and RECEIVE_ROLES.intersection(json.loads(row[0])))


def applicable(tx, pid):
    return tx.execute(
        "SELECT mode FROM projects WHERE id=?", (str(pid),),
    ).fetchone()[0] == "oem"


def party_permits(tx, actor, pid, action, row):
    roles = effective_permissions(tx, actor, pid).roles
    if actor.read_only or not applicable(tx, pid):
        return False
    if action in {"material_handoff.receive", "material_handoff.confirm_use"}:
        return str(actor.user_id) == row["receiver_id"] and bool(roles & RECEIVE_ROLES)
    return bool(roles & RECEIVE_ROLES) and (
        str(actor.user_id) == row["sender_id"]
        or "project_owner" in roles
        or actor.configuration_admin
    )


def authorize(tx, actor, pid, command):
    """Live party authorization before replay; transitions are checked afterward."""
    if not command.action.startswith("material_handoff."):
        return
    require_project(tx, actor, pid)
    if not applicable(tx, pid):
        fail("Material handoffs require an OEM project", 422)
    if command.action == "material_handoff.record":
        return
    row = own(tx, "material_handoffs", pid, command.handoff_id)
    if not party_permits(tx, actor, pid, command.action, row):
        raise DomainError("FORBIDDEN", 403, "Handoff responsibility permission denied")


def read_actions(tx, actor, pid, row):
    candidates = {
        "pending": ["material_handoff.receive", "material_handoff.cancel"],
        "disputed": ["material_handoff.resolve"],
    }.get(row["state"], [])
    if row["receipt_json"] and row["state"] != "cancelled":
        receipt = json.loads(row["receipt_json"])
        if receipt.get("receipt_use", "unspecified") == "unspecified":
            candidates.append("material_handoff.confirm_use")
    return [a for a in candidates if party_permits(tx, actor, pid, a, row)]


def project_receive_capable(tx, actor, pid):
    """A project-wide receive capability still requires a designated pending fact."""
    return bool(
        not actor.read_only
        and effective_permissions(tx, actor, pid).roles & RECEIVE_ROLES
        and applicable(tx, pid)
        and tx.execute(
            "SELECT 1 FROM material_handoffs WHERE project_id=? "
            "AND receiver_id=? AND state='pending' LIMIT 1",
            (str(pid), str(actor.user_id)),
        ).fetchone()
    )


def trusted_name(user_id, *names):
    """Keep a usable trusted name, or retain the real identity when unnamed."""
    for name in names:
        if name and name.strip():
            return name.strip()
    return str(user_id)


def actor_fact(context):
    actor = context.actor
    return dict(
        actor_id=str(actor.user_id),
        actor_name=trusted_name(
            actor.user_id,
            (context.subject_profiles or {}).get(str(actor.user_id)),
            actor.display_name,
        ),
        recorded_at=context.now.isoformat(),
    )


def occurred(context, value, *, earliest=None):
    value = value or context.now
    if value > context.now or (earliest is not None and value < earliest):
        fail("Handoff time must be no later than now and receipt no earlier than handoff", 422)
    return value.isoformat()


def record(tx, context, command):
    lot = own(tx, "material_lots", context.project_id, command.material_lot_id)
    if command.work_order_id:
        own(tx, "work_orders", context.project_id, command.work_order_id)
    atoms(command.quantity, command.unit, lot["unit"], lot["scale"])
    if command.from_location == command.to_location:
        fail("Handoff locations must differ", 422)
    if command.receiver_id == context.actor.user_id:
        fail("Sender and receiver must differ", 422)
    # Resolve directory profiles outside the transaction, then recheck the live
    # target member and role here before creating a new fact.
    if not receiver_member(tx, context.actor, context.project_id, command.receiver_id):
        fail("Receiver must be an active authorized project member", 422)
    happened = occurred(context, command.occurred_at)
    ident = str(uuid4())
    profiles = context.subject_profiles or {}
    payload = business(command)
    payload.update(
        id=ident,
        occurred_at=happened,
        recorded_at=context.now.isoformat(),
        sender_id=str(context.actor.user_id),
        sender_name=trusted_name(
            context.actor.user_id,
            profiles.get(str(context.actor.user_id)),
            context.actor.display_name,
        ),
        receiver_name=trusted_name(command.receiver_id, profiles.get(str(command.receiver_id))),
        handoff_number="MH-" + ident.upper(),
        source=dict(
            system="manual",
            object_type="material_handoff",
            external_id=ident,
            version=1,
            mode="manual",
            occurred_at=happened,
            collected_at=context.now.isoformat(),
            evidence="Manual material handoff recorded by " + str(context.actor.user_id),
        ),
    )
    tx.execute(
        "INSERT INTO material_handoffs(id,project_id,material_lot_id,work_order_id,"
        "sender_id,receiver_id,state,payload_json) VALUES (?,?,?,?,?,?,?,?)",
        (
            ident, str(context.project_id), str(command.material_lot_id),
            str(command.work_order_id) if command.work_order_id else None,
            str(context.actor.user_id), str(command.receiver_id), "pending", canonical(payload),
        ),
    )
    return MutationResult(object_type="material_handoff", object_id=ident)


def receive(tx, context, command):
    row = own(tx, "material_handoffs", context.project_id, command.handoff_id)
    if row["state"] != "pending":
        fail("Only pending handoffs may be received")
    payload = json.loads(row["payload_json"])
    lot = own(tx, "material_lots", context.project_id, row["material_lot_id"])
    atoms(command.received_quantity, payload["unit"], lot["unit"], lot["scale"])
    happened = occurred(
        context, command.occurred_at,
        earliest=datetime.fromisoformat(payload["occurred_at"]),
    )
    disputed = (
        command.received_quantity != Decimal(payload["quantity"])
        or command.received_location != payload["to_location"]
    )
    if disputed and not command.note:
        fail("Discrepancy explanation is required", 422)
    receipt = dict(**business(command), **actor_fact(context))
    receipt.pop("handoff_id")
    receipt.update(occurred_at=happened)
    if command.receipt_use != "unspecified":
        validate_receipt_use(tx, context.project_id, row, command)
        receipt.update(scope_actor_id=str(context.actor.user_id),
                       scope_recorded_at=context.now.isoformat(), scope_evidence=command.note)
    tx.execute(
        "UPDATE material_handoffs SET state=?,receipt_json=? WHERE project_id=? AND id=?",
        (
            "disputed" if disputed else "received", canonical(receipt),
            str(context.project_id), str(command.handoff_id),
        ),
    )
    return MutationResult(object_type="material_handoff", object_id=command.handoff_id)


def validate_receipt_use(tx, pid, row, command):
    if command.receipt_use != "line_side":
        return
    from .supply import current_plan_id

    req = own(tx, "requirements", pid, command.requirement_id)
    lot = own(tx, "material_lots", pid, row["material_lot_id"])
    payload = json.loads(row["payload_json"])
    if (req["plan_id"] != current_plan_id(tx, str(pid), req["work_order_id"])
            or row["work_order_id"] != req["work_order_id"]
            or lot["material_id"] != req["material_id"]
            or lot["owner_id"] != req["owner_id"]
            or lot["unit"] != req["unit"] or payload["unit"] != req["unit"]):
        fail("Receipt use must match the current work-order material requirement", 422)


def confirm_use(tx, context, command):
    row = own(tx, "material_handoffs", context.project_id, command.handoff_id)
    if row["state"] == "cancelled" or not row["receipt_json"]:
        fail("Only an actual signed receipt can have its use confirmed")
    receipt = json.loads(row["receipt_json"])
    if receipt.get("receipt_use", "unspecified") != "unspecified":
        fail("Receipt use is already confirmed")
    validate_receipt_use(tx, context.project_id, row, command)
    receipt.update(receipt_use=command.receipt_use,
                   requirement_id=str(command.requirement_id) if command.requirement_id else None,
                   scope_actor_id=str(context.actor.user_id),
                   scope_recorded_at=context.now.isoformat(), scope_evidence=command.evidence)
    tx.execute("UPDATE material_handoffs SET receipt_json=? WHERE project_id=? AND id=?",
               (canonical(receipt), str(context.project_id), str(command.handoff_id)))
    return MutationResult(object_type="material_handoff", object_id=command.handoff_id)


def resolve(tx, context, command):
    return finish(
        tx, context, command, "disputed", "resolved", "resolution_json",
        dict(resolution=command.resolution),
    )


def cancel(tx, context, command):
    return finish(
        tx, context, command, "pending", "cancelled", "cancellation_json",
        dict(reason=command.reason),
    )


def finish(tx, context, command, expected, state, column, payload):
    row = own(tx, "material_handoffs", context.project_id, command.handoff_id)
    if row["state"] != expected:
        fail("Handoff state does not permit this transition")
    tx.execute(
        f"UPDATE material_handoffs SET state=?,{column}=? WHERE project_id=? AND id=?",
        (
            state, canonical(dict(**payload, **actor_fact(context))),
            str(context.project_id), str(command.handoff_id),
        ),
    )
    return MutationResult(object_type="material_handoff", object_id=command.handoff_id)


for model, handler, roles in [
    (RecordMaterialHandoff, record, CREATE_ROLES),
    (ReceiveMaterialHandoff, receive, RECEIVE_ROLES),
    (ConfirmMaterialReceiptUse, confirm_use, RECEIVE_ROLES),
    (ResolveMaterialHandoff, resolve, RECEIVE_ROLES),
    (CancelMaterialHandoff, cancel, RECEIVE_ROLES),
]:
    COMMAND_REGISTRY.register(model, roles=roles, qualifications=set(), handler=handler)
