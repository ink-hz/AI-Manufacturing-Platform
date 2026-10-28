"""Continuing local safety holds and independent ordered authority confirmation."""

import json
from uuid import UUID, uuid4

from .commands import COMMAND_REGISTRY
from .contracts import DomainError, MutationResult
from .delivery import fail
from .feedback_models import (
    FreezePayload,
    FreezeProjection,
    FreezeReceiptDetail,
    FreezeRequest,
)
from .orders import own


def projection(tx, pid, kind, ident):
    column = "unit_id" if kind == "unit" else "lot_id"
    latest = tx.execute(
        f"SELECT r.* FROM freeze_requests r JOIN freeze_members m ON m.request_id=r.id WHERE m.project_id=? AND m.{column}=? ORDER BY r.seq DESC LIMIT 1",
        (str(pid), str(ident)),
    ).fetchone()
    confirmed = tx.execute(
        "SELECT * FROM freeze_confirmations WHERE project_id=? AND object_kind=? AND object_id=?",
        (str(pid), kind, str(ident)),
    ).fetchone()
    return FreezeProjection(
        freeze_requested=latest["requested_state"] if latest else None,
        freeze_confirmed=confirmed["state"] if confirmed else None,
        freeze_pending=bool(
            latest
            and (
                not confirmed or confirmed["source_version"] < latest["source_version"]
            )
        ),
    )


def held(tx, pid, kind, ident):
    state = projection(tx, pid, kind, ident)
    return state.freeze_pending or state.freeze_confirmed == "frozen"


def lot_hold(tx, pid, ident):
    return (
        "Material lot containment pending or frozen"
        if held(tx, pid, "material_lot", ident)
        else None
    )


def unit_reasons(tx, pid, ident):
    reasons = (
        ["Serial containment pending or frozen"] if held(tx, pid, "unit", ident) else []
    )
    if tx.execute(
        """SELECT 1 FROM material_consumption c JOIN freeze_members m ON m.lot_id=c.lot_id AND m.project_id=c.project_id JOIN freeze_requests r ON r.id=m.request_id LEFT JOIN freeze_confirmations f ON f.project_id=m.project_id AND f.object_kind='material_lot' AND f.object_id=m.lot_id WHERE c.project_id=? AND c.unit_id=? AND r.seq=(SELECT MAX(x.seq) FROM freeze_requests x JOIN freeze_members y ON y.request_id=x.id WHERE y.project_id=m.project_id AND y.lot_id=m.lot_id) AND (f.request_id IS NULL OR f.source_version<r.source_version OR f.state='frozen') LIMIT 1""",
        (str(pid), str(ident)),
    ).fetchone():
        reasons.append("Consumed material lot containment pending or frozen")
    return reasons


def request(tx, context, command):
    from .exchange_models import ExternalRequest

    pid = context.project_id
    for table, ids in [("units", command.unit_ids), ("material_lots", command.lot_ids)]:
        for ident in ids:
            own(tx, table, pid, ident)
    fid, eid = uuid4(), uuid4()
    payload = FreezePayload(
        freeze_id=fid,
        unit_ids=command.unit_ids,
        lot_ids=command.lot_ids,
        state=command.state,
    )
    external = ExternalRequest(
        id=eid,
        system="erp",
        action=command.action,
        business_key=str(fid),
        source_version=context.project_version + 1,
        project_id=pid,
        typed_payload=payload,
    )
    context.exchange_service.prepare(tx, context, external)
    tx.execute(
        "INSERT INTO freeze_requests(id,project_id,exchange_id,requested_state,source_version,reason,created_at) VALUES (?,?,?,?,?,?,?)",
        (
            str(fid),
            str(pid),
            str(eid),
            command.state,
            external.source_version,
            command.reason,
            context.now.isoformat(),
        ),
    )
    tx.executemany(
        "INSERT INTO freeze_members VALUES (?,?,?,?)",
        [(str(fid), str(pid), str(uid), None) for uid in command.unit_ids]
        + [(str(fid), str(pid), None, str(lid)) for lid in command.lot_ids],
    )
    tx.executemany(
        "INSERT INTO shipment_freeze_events(project_id,unit_id,state,reference) VALUES (?,?,'pending',?)",
        [(str(pid), str(uid), str(fid)) for uid in command.unit_ids],
    )
    return MutationResult(object_type="exchange", object_id=eid, exchange_id=eid)


def receipt_details(payload):
    return [
        FreezeReceiptDetail(
            key=f"{kind}:{ident}",
            object_kind=kind,
            object_id=ident,
            state=payload.state,
        )
        for kind, ids in [("unit", payload.unit_ids), ("material_lot", payload.lot_ids)]
        for ident in ids
    ]


def receipt_scope(tx, row, receipt):
    from .exchange_models import ExternalRequest

    request = ExternalRequest.model_validate_json(row["request_json"])
    payload = request.typed_payload
    if not isinstance(payload, FreezePayload):
        return False
    expected = receipt_details(payload)
    return (
        receipt.business_key == request.business_key
        and receipt.request_hash == row["request_hash"]
        and receipt.source_object_id == str(payload.freeze_id)
        and receipt.source_version == request.source_version
        and len(receipt.details) == len(expected)
        and {d.key: d.model_dump(mode="json") for d in receipt.details}
        == {d.key: d.model_dump(mode="json") for d in expected}
        and bool(
            tx.execute(
                "SELECT 1 FROM freeze_requests WHERE id=? AND project_id=? AND exchange_id=? AND source_version=? AND requested_state=?",
                (
                    str(payload.freeze_id),
                    row["project_id"],
                    row["id"],
                    request.source_version,
                    payload.state,
                ),
            ).fetchone()
        )
        and all(
            tx.execute(
                f"SELECT 1 FROM freeze_members m JOIN {table} o ON o.id=m.{column} AND o.project_id=m.project_id WHERE m.project_id=? AND m.request_id=? AND m.{column}=?",
                (row["project_id"], str(payload.freeze_id), str(ident)),
            ).fetchone()
            for table, column, ids in [
                ("units", "unit_id", payload.unit_ids),
                ("material_lots", "lot_id", payload.lot_ids),
            ]
            for ident in ids
        )
    )


def apply(service, tx, context, row, request, receipt):
    from .exchanges import event

    result = MutationResult(
        object_type="exchange", object_id=UUID(row["id"]), exchange_id=UUID(row["id"])
    )
    if row["receipt_json"] == receipt.model_dump_json():
        return result
    if (
        receipt.sequence < 1
        or receipt.sequence <= row["source_sequence"]
        or (receipt.occurred_at - context.now).total_seconds() > 300
        or receipt.accepted_quantity != 0
        or receipt.rejected_quantity != 0
    ):
        service._reject(tx, context, row, "Stale or invalid freeze receipt")
        return result
    payload = request.typed_payload
    members = receipt_details(payload)
    stale = any(
        tx.execute(
            "SELECT 1 FROM freeze_confirmations WHERE project_id=? AND object_kind=? AND object_id=? AND (source_version>? OR source_sequence>=?)",
            (
                str(context.project_id),
                d.object_kind,
                str(d.object_id),
                request.source_version,
                receipt.sequence,
            ),
        ).fetchone()
        for d in members
    )
    if stale:
        service._reject(tx, context, row, "Stale freeze source version or sequence")
        return result
    tx.execute(
        "INSERT INTO exchange_receipts(exchange_id,project_id,receipt_id,payload_json,valid,reason) VALUES (?,?,?,?,1,'')",
        (
            row["id"],
            row["project_id"],
            str(receipt.receipt_id),
            receipt.model_dump_json(),
        ),
    )
    tx.execute(
        "UPDATE exchanges SET receipt_json=?,source_sequence=? WHERE id=?",
        (receipt.model_dump_json(), receipt.sequence, row["id"]),
    )
    if receipt.phase in {"accepted", "posted"}:
        for d in members:
            tx.execute(
                "INSERT INTO freeze_confirmations VALUES (?,?,?,?,?,?,?) ON CONFLICT(project_id,object_kind,object_id) DO UPDATE SET request_id=excluded.request_id,state=excluded.state,source_version=excluded.source_version,source_sequence=excluded.source_sequence",
                (
                    row["project_id"],
                    d.object_kind,
                    str(d.object_id),
                    str(payload.freeze_id),
                    payload.state,
                    request.source_version,
                    receipt.sequence,
                ),
            )
            if d.object_kind == "unit":
                state = projection(tx, context.project_id, "unit", d.object_id)
                event_state = (
                    "pending"
                    if state.freeze_pending
                    else "frozen"
                    if state.freeze_confirmed == "frozen"
                    else "released"
                )
                tx.execute(
                    "INSERT INTO shipment_freeze_events(project_id,unit_id,state,source_sequence,reference) VALUES (?,?,?,?,?)",
                    (
                        row["project_id"],
                        str(d.object_id),
                        event_state,
                        receipt.sequence,
                        str(payload.freeze_id),
                    ),
                )
    event(
        tx,
        row,
        receipt.phase,
        "Authority confirmed containment state"
        if receipt.phase in {"accepted", "posted"}
        else "Authority rejected request"
        if receipt.phase == "rejected"
        else "Awaiting authoritative containment",
    )
    return result


def authority_apply(tx, request, h, sequence, fault_name):
    from datetime import UTC, datetime

    from .exchange_models import ExternalReceipt

    details = receipt_details(request.typed_payload)
    stale = any(
        tx.execute(
            "SELECT 1 FROM authority_freeze_versions WHERE project_id=? AND object_kind=? AND object_id=? AND source_version>=?",
            (
                str(request.project_id),
                d.object_kind,
                str(d.object_id),
                request.source_version,
            ),
        ).fetchone()
        for d in details
    )
    rejected = stale or fault_name == "reject"
    if not rejected:
        for d in details:
            tx.execute(
                "INSERT INTO authority_freeze_versions VALUES (?,?,?,?,?,?) ON CONFLICT(project_id,object_kind,object_id) DO UPDATE SET source_version=excluded.source_version,sequence=excluded.sequence,state=excluded.state",
                (
                    str(request.project_id),
                    d.object_kind,
                    str(d.object_id),
                    request.source_version,
                    sequence,
                    d.state,
                ),
            )
            if d.object_kind == "unit":
                tx.execute(
                    "INSERT INTO authority_shipment_freezes VALUES (?,?,?,?) ON CONFLICT(project_id,unit_id) DO UPDATE SET state=excluded.state,sequence=excluded.sequence",
                    (
                        str(request.project_id),
                        str(d.object_id),
                        "frozen" if d.state == "frozen" else "released",
                        sequence,
                    ),
                )
    return ExternalReceipt(
        receipt_id=uuid4(),
        business_key=request.business_key,
        request_hash=h,
        source_object_id=str(request.typed_payload.freeze_id),
        source_version=request.source_version,
        sequence=sequence,
        phase="rejected" if rejected else "accepted",
        accepted_quantity="0",
        rejected_quantity="0",
        details=details,
        occurred_at=datetime.now(UTC),
        error="Stale freeze version"
        if stale
        else "Authority rejected request"
        if rejected
        else None,
    )


COMMAND_REGISTRY.register(
    FreezeRequest,
    roles={"quality", "project_owner"},
    qualifications=set(),
    handler=request,
)


def consumed_lots(tx, pid, unit_ids):
    rows = tx.execute(
        "SELECT DISTINCT lot_id FROM material_consumption WHERE project_id=? AND unit_id IN (SELECT value FROM json_each(?)) ORDER BY lot_id LIMIT 501",
        (str(pid), json.dumps(list(map(str, unit_ids)))),
    ).fetchall()
    if len(rows) > 500:
        fail(
            "Shipment material scope exceeds bounded authority request; split shipment"
        )
    return [UUID(r[0]) for r in rows]


def execution_lots(tx, pid, wid, modes):
    from .supply import current_plan_id

    plan = current_plan_id(tx, pid, wid)
    rows = tx.execute(
        """SELECT DISTINCT r.material_lot_id FROM reservations r JOIN requirements old ON old.id=r.requirement_id AND old.project_id=r.project_id JOIN requirements current ON current.lineage_id=old.lineage_id AND current.project_id=old.project_id WHERE r.project_id=? AND r.work_order_id=? AND current.plan_id=? AND (current.execution_scope='common' OR current.execution_scope IN (SELECT value FROM json_each(?))) AND r.authority_receipt_id IS NOT NULL AND r.confirmed_atoms>0 ORDER BY r.material_lot_id LIMIT 501""",
        (str(pid), str(wid), str(plan), json.dumps(modes)),
    ).fetchall()
    if len(rows) > 500:
        fail("Production material scope exceeds bounded authority request")
    from .ownership import material_hold

    return [
        UUID(r[0])
        for r in rows
        if not material_hold(tx, pid, own(tx, "material_lots", pid, r[0]))
    ]


def resume_held(tx, pid, wid, scope):
    # Cursor iteration is a bounded existence test; no materialized directory.
    return any(
        unit_reasons(tx, pid, r[0])
        for r in tx.execute(
            "SELECT id FROM units WHERE project_id=? AND work_order_id=? AND accepted_start_id IS NOT NULL AND (?='all' OR mode='trial')",
            (str(pid), str(wid), scope),
        )
    )


def authority_execution_held(tx, request):
    from .exchange_models import StartPayload

    payload = request.typed_payload
    if any(
        tx.execute(
            "SELECT 1 FROM authority_freeze_versions WHERE project_id=? AND object_kind='material_lot' AND object_id=? AND state='frozen'",
            (str(request.project_id), str(lid)),
        ).fetchone()
        for lid in (payload.material_lot_ids or [])
    ):
        return True
    if isinstance(payload, StartPayload):
        return any(
            tx.execute(
                "SELECT 1 FROM authority_shipment_freezes WHERE project_id=? AND unit_id=? AND state='frozen'",
                (str(request.project_id), str(uid)),
            ).fetchone()
            for uid, _ in payload.units
        )
    return bool(
        tx.execute(
            "SELECT 1 FROM authority_shipment_freezes f JOIN authority_start_units u ON u.unit_id=f.unit_id AND u.project_id=f.project_id WHERE f.project_id=? AND u.work_order_id=? AND (?='all' OR u.mode='trial') AND f.state='frozen' LIMIT 1",
            (str(request.project_id), str(payload.work_order_id), payload.scope),
        ).fetchone()
    )


def audit_evidence(tx, pid, row, payload):
    """Freeze-owned history never falls back to arbitrary payload source fields."""
    from pydantic import ValidationError

    from .contracts import ObjectEvidence

    try:
        if payload.get("project_id") != str(pid) or row["action"] != "freeze.request":
            return []
        command = FreezeRequest.model_validate(
            {k: v for k, v in payload.items() if k != "project_id"}
        )
        fact = tx.execute(
            "SELECT * FROM freeze_requests WHERE project_id=? AND exchange_id=?",
            (str(pid), row["object_id"]),
        ).fetchone()
        if (
            not fact
            or fact["reason"] != command.reason
            or fact["requested_state"] != command.state
        ):
            return []
        members = tx.execute(
            "SELECT * FROM freeze_members WHERE project_id=? AND request_id=? LIMIT 501",
            (str(pid), fact["id"]),
        ).fetchall()
        if {m["unit_id"] for m in members if m["unit_id"]} != set(
            map(str, command.unit_ids)
        ) or {m["lot_id"] for m in members if m["lot_id"]} != set(
            map(str, command.lot_ids)
        ):
            return []
        for table, ids in [
            ("units", command.unit_ids),
            ("material_lots", command.lot_ids),
        ]:
            for ident in ids:
                own(tx, table, pid, ident)
        return [ObjectEvidence(reference=command.reason)]
    except (DomainError, ValidationError, ValueError, TypeError):
        return []
