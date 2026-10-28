"""Physical shipment authority and independent cumulative delivery facts."""

import json
from uuid import UUID, uuid4

from .commands import COMMAND_REGISTRY
from .contracts import (
    DomainError,
    MutationResult,
    ObjectDetail,
    ObjectRelation,
    ObjectSummary,
    SourceRef,
)
from .delivery_models import (
    DeliveryAccept,
    DeliveryBalance,
    DeliverySign,
    FreezeEligibility,
    RequestShipment,
    ShipmentValue,
)
from .exchange_models import ExternalRequest, ShipmentReceiptDetail, ShipPayload
from .orders import _history_rows, allocated, amount, own, project, source_key
from .quality import shipment_eligibility
from .queries import OBJECT_REGISTRY
from .supply import atoms


def fail(reason):
    raise DomainError("PRECONDITION_FAILED", 409, reason, blocking_reasons=[reason])


def freeze_eligibility(tx, project_id, unit_ids) -> FreezeEligibility:
    from .freeze import unit_reasons

    reasons = []
    for uid in unit_ids:
        reasons.extend(unit_reasons(tx, project_id, uid))
        row = tx.execute(
            "SELECT state FROM shipment_freeze_events WHERE project_id=? AND unit_id=? ORDER BY seq DESC LIMIT 1",
            (str(project_id), str(uid)),
        ).fetchone()
        if row and row[0] != "released":
            reasons.append(f"{uid}: shipment freeze {row[0]}")
    return FreezeEligibility(allowed=not reasons, reasons=reasons)


def safety_reasons(tx, pid, unit_ids):
    return (
        shipment_eligibility(tx, pid, unit_ids).reasons
        + freeze_eligibility(tx, pid, unit_ids).reasons
    )


def totals(tx, pid, shipment_id=None, order_id=None):
    where, args = "f.project_id=?", [str(pid)]
    if shipment_id:
        where += " AND f.shipment_id=?"
        args.append(str(shipment_id))
    if order_id:
        where += " AND s.order_line_id=?"
        args.append(str(order_id))
    return {
        r[0]: r[1]
        for r in tx.execute(
            f"SELECT f.action,SUM(f.q_atoms) FROM delivery_facts f JOIN shipments s ON s.id=f.shipment_id WHERE {where} GROUP BY f.action",
            args,
        )
    }


def remaining(tx, project_id, order_line_id) -> DeliveryBalance:
    p = project(tx, project_id)
    order = own(tx, "order_lines", project_id, order_line_id)
    factor = 10 ** p["unit_scale"]
    shipped = (
        tx.execute(
            "SELECT COUNT(*) FROM shipment_items WHERE project_id=? AND order_line_id=?",
            (str(project_id), str(order_line_id)),
        ).fetchone()[0]
        * factor
    )
    pending = (
        tx.execute(
            "SELECT COUNT(*) FROM shipment_claims WHERE project_id=? AND order_line_id=?",
            (str(project_id), str(order_line_id)),
        ).fetchone()[0]
        * factor
    )
    from .quality import final_good_count

    facts = totals(tx, project_id, order_id=order_line_id)
    values = dict(
        ordered=order["current_q_atoms"],
        allocated=allocated(tx, project_id, order_id=order_line_id),
        qualified=final_good_count(tx, project_id, order_line_id) * factor,
        pending_shipment=pending,
        shipped=shipped,
        signed=facts.get("sign", 0),
        accepted=facts.get("accept", 0),
        remaining_to_ship=max(0, order["current_q_atoms"] - shipped),
        remaining_to_accept=max(0, order["current_q_atoms"] - facts.get("accept", 0)),
    )
    return DeliveryBalance(
        **{key: amount(value, p) for key, value in values.items()}, unit=order["unit"]
    )


def request_shipment(tx, context, command):
    pid = context.project_id
    p, order = project(tx, pid), own(tx, "order_lines", pid, command.order_line_id)
    ids = list(map(str, command.unit_ids))
    quantity = atoms(command.quantity, command.unit, p["unit_code"], p["unit_scale"])
    if len(set(ids)) != len(ids) or quantity != len(ids) * 10 ** p["unit_scale"]:
        fail("Shipment quantity must equal unique explicit serial membership")
    box_ids = [b.box_id.strip() for b in command.boxes]
    boxed = [str(uid) for b in command.boxes for uid in b.unit_ids]
    if (
        any(not b for b in box_ids)
        or len(set(box_ids)) != len(box_ids)
        or len(set(boxed)) != len(boxed)
        or (boxed and set(boxed) != set(ids))
    ):
        fail("Boxes must cover the shipment serials exactly once")
    for box_id in box_ids:
        if tx.execute(
            "SELECT 1 FROM shipment_box_claims WHERE box_id=?", (box_id,)
        ).fetchone():
            fail("Box already belongs to another shipment")
    units = [own(tx, "units", pid, uid) for uid in ids]
    per_wo = {}
    for u in units:
        if tx.execute(
            "SELECT 1 FROM shipment_claims WHERE unit_id=? UNION ALL SELECT 1 FROM shipment_items WHERE unit_id=?",
            (u["id"], u["id"]),
        ).fetchone():
            fail("Serial already pending or shipped")
        wo = own(tx, "effective_work_orders", pid, u["work_order_id"])
        if wo["order_line_id"] != order["id"] or wo["obligation_atoms"] <= 0:
            fail("Serial does not belong to this effective order obligation")
        per_wo[wo["id"]] = per_wo.get(wo["id"], 0) + 10 ** p["unit_scale"]
    for wid, selected in per_wo.items():
        allocated_atoms = tx.execute(
            "SELECT COALESCE(SUM(q_atoms),0) FROM effective_allocations WHERE project_id=? AND order_line_id=? AND work_order_id=?",
            (str(pid), order["id"], wid),
        ).fetchone()[0]
        used = (
            tx.execute(
                "SELECT COUNT(*) FROM (SELECT unit_id FROM shipment_claims UNION ALL SELECT unit_id FROM shipment_items) c JOIN units u ON u.id=c.unit_id WHERE u.project_id=? AND u.work_order_id=?",
                (str(pid), wid),
            ).fetchone()[0]
            * 10 ** p["unit_scale"]
        )
        if used + selected > min(
            allocated_atoms,
            own(tx, "effective_work_orders", pid, wid)["obligation_atoms"],
        ):
            fail("Shipment exceeds effective work-order allocation")
    balance = remaining(tx, pid, order["id"])
    if balance.shipped + balance.pending_shipment + command.quantity > balance.ordered:
        fail("Shipment exceeds remaining order quantity")
    reasons = safety_reasons(tx, pid, ids)
    if reasons:
        fail("; ".join(reasons))
    sid, eid = uuid4(), uuid4()
    from .freeze import consumed_lots

    payload = ShipPayload(
        material_lot_ids=consumed_lots(tx, pid, ids),
        shipment_id=sid,
        order_line_id=command.order_line_id,
        quantity=str(command.quantity),
        unit=command.unit,
        scale=p["unit_scale"],
        order_quantity=str(balance.ordered),
        units=[(u["id"], u["sn"], u["work_order_id"]) for u in units],
        boxes=command.boxes,
    )
    request = ExternalRequest(
        id=eid,
        system="erp",
        action=command.action,
        business_key=str(sid),
        source_version=1,
        project_id=pid,
        typed_payload=payload,
    )
    context.exchange_service.prepare(tx, context, request)
    tx.execute(
        "INSERT INTO shipments VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            str(sid),
            str(pid),
            order["id"],
            str(eid),
            quantity,
            command.unit,
            json.dumps(ids),
            json.dumps([b.model_dump(mode="json") for b in command.boxes]),
            "pending",
            context.now.isoformat(),
        ),
    )
    tx.executemany(
        "INSERT INTO shipment_claims VALUES (?,?,?,?)",
        [(uid, str(pid), order["id"], str(sid)) for uid in ids],
    )
    tx.executemany(
        "INSERT INTO shipment_box_claims VALUES (?,?,?)",
        [(bid, str(pid), str(sid)) for bid in box_ids],
    )
    return MutationResult(object_type="shipment", object_id=sid, exchange_id=eid)


def current_shipment_reasons(tx, pid, shipment_id):
    row = own(tx, "shipments", pid, shipment_id)
    ids = json.loads(row["units_json"])
    reasons = safety_reasons(tx, pid, ids)
    p = project(tx, pid)
    balance = remaining(tx, pid, row["order_line_id"])
    if balance.shipped + balance.pending_shipment > balance.ordered:
        reasons.append("Current order quantity is below pending/physical shipments")
    work_orders = {own(tx, "units", pid, uid)["work_order_id"] for uid in ids}
    for wid in work_orders:
        wo = own(tx, "effective_work_orders", pid, wid)
        allocation = tx.execute(
            "SELECT COALESCE(SUM(q_atoms),0) FROM effective_allocations WHERE project_id=? AND order_line_id=? AND work_order_id=?",
            (str(pid), row["order_line_id"], wid),
        ).fetchone()[0]
        used = tx.execute(
            "SELECT COUNT(*) FROM (SELECT unit_id FROM shipment_claims UNION ALL SELECT unit_id FROM shipment_items) c JOIN units u ON u.id=c.unit_id WHERE u.project_id=? AND u.work_order_id=?",
            (str(pid), wid),
        ).fetchone()[0] * (10 ** p["unit_scale"])
        if used > min(allocation, wo["obligation_atoms"]):
            reasons.append(
                "Current effective allocation no longer covers physical/pending shipment"
            )
    return reasons


def receipt_details(payload):
    boxes = {
        str(uid): box.box_id.strip() for box in payload.boxes for uid in box.unit_ids
    }
    return [
        ShipmentReceiptDetail(
            key=str(uid),
            unit_id=uid,
            sn=sn,
            work_order_id=wid,
            order_line_id=payload.order_line_id,
            box_id=boxes.get(str(uid)),
        )
        for uid, sn, wid in payload.units
    ]


def receipt_scope(tx, row, receipt):
    request = ExternalRequest.model_validate_json(row["request_json"])
    payload = request.typed_payload
    if not isinstance(payload, ShipPayload):
        return False
    expected = {d.key: d.model_dump(mode="json") for d in receipt_details(payload)}
    actual = {d.key: d.model_dump(mode="json") for d in receipt.details}
    return (
        receipt.business_key == row["business_key"]
        and receipt.request_hash == row["request_hash"]
        and receipt.source_object_id == str(payload.shipment_id)
        and receipt.source_version == request.source_version
        and len(receipt.details) == len(expected)
        and actual == expected
        and all(
            tx.execute(
                "SELECT 1 FROM units WHERE id=? AND project_id=? AND work_order_id=?",
                (str(uid), row["project_id"], str(wid)),
            ).fetchone()
            for uid, _, wid in payload.units
        )
    )


def apply_shipment(service, tx, context, row, request, receipt):
    from .exchanges import event

    payload = request.typed_payload
    result = MutationResult(
        object_type="exchange", object_id=UUID(row["id"]), exchange_id=UUID(row["id"])
    )
    if row["receipt_json"] == receipt.model_dump_json():
        return result
    if (
        receipt.sequence < 1
        or receipt.sequence <= row["source_sequence"]
        or (receipt.occurred_at - context.now).total_seconds() > 300
    ):
        service._reject(tx, context, row, "Stale receipt sequence")
        return result
    accepted = receipt.phase in {"accepted", "posted"}
    rejected = receipt.phase == "rejected"
    if (
        accepted
        and (
            receipt.accepted_quantity != payload.quantity
            or receipt.rejected_quantity != 0
        )
    ) or (
        rejected
        and (
            receipt.accepted_quantity != 0
            or receipt.rejected_quantity != payload.quantity
        )
    ):
        service._reject(
            tx, context, row, "Receipt detail quantity differs from requested total"
        )
        return result
    sid = str(payload.shipment_id)
    # Receipt identity/scope admission runs before any visible evidence write.
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
    if accepted:
        for uid, _, _ in payload.units:
            tx.execute(
                "INSERT INTO shipment_items VALUES (?,?,?,?,?)",
                (
                    str(uid),
                    row["project_id"],
                    str(payload.order_line_id),
                    sid,
                    str(receipt.receipt_id),
                ),
            )
        tx.execute("DELETE FROM shipment_claims WHERE shipment_id=?", (sid,))
        held = bool(current_shipment_reasons(tx, context.project_id, sid))
        tx.execute(
            "UPDATE shipments SET state=? WHERE id=?",
            ("held" if held else "accepted", sid),
        )
    elif rejected:
        tx.execute("DELETE FROM shipment_claims WHERE shipment_id=?", (sid,))
        tx.execute("DELETE FROM shipment_box_claims WHERE shipment_id=?", (sid,))
        tx.execute("UPDATE shipments SET state='rejected' WHERE id=?", (sid,))
    event(
        tx,
        row,
        receipt.phase,
        "Authority accepted physical shipment"
        if accepted
        else receipt.error or "Authority rejected request"
        if rejected
        else "Awaiting authoritative acceptance",
    )
    return result


def record_fact(tx, context, command):
    from .delivery_models import DeliverySourceRecord
    from .imports import admit_records

    kind = (
        "sign"
        if isinstance(command, DeliverySign) and not isinstance(command, DeliveryAccept)
        else "accept"
    )
    row = own(tx, "shipments", context.project_id, command.shipment_id)
    p = project(tx, context.project_id)
    record = DeliverySourceRecord(
        project_id=context.project_id,
        object_type="delivery_" + kind,
        shipment_id=command.shipment_id,
        source=command.source,
    )
    admit_records(tx, context, [record], object_type=record.object_type, trusted=False)
    if command.source.mode != "manual":
        fail("Delivery facts require explicit manual recording provenance")
    q = atoms(command.quantity, row["unit"], row["unit"], p["unit_scale"])
    shipped = (
        tx.execute(
            "SELECT COUNT(*) FROM shipment_items WHERE shipment_id=?", (row["id"],)
        ).fetchone()[0]
        * 10 ** p["unit_scale"]
    )
    facts = totals(tx, context.project_id, shipment_id=row["id"])
    limit = shipped if kind == "sign" else facts.get("sign", 0)
    if facts.get(kind, 0) + q > limit:
        fail(
            "Cumulative delivery fact exceeds authoritative shipped or signed quantity"
        )
    key = source_key(command.source)
    if tx.execute(
        "SELECT 1 FROM delivery_facts WHERE source_system=? AND source_type=? AND source_external_id=?",
        key,
    ).fetchone():
        fail("Delivery source identity already recorded")
    owners = {}
    if kind == "accept":
        for issue in command.issues:
            grant = tx.execute(
                "SELECT 1 FROM project_grants WHERE project_id=? AND user_id=? AND active=1 AND roles_json!='[]'",
                (str(context.project_id), str(issue.owner_id)),
            ).fetchone()
            name = (context.subject_profiles or {}).get(str(issue.owner_id))
            if not grant or not name:
                fail(
                    "Active named project member profile unavailable for responsible owner"
                )
            owners[str(issue.owner_id)] = name
    ident = uuid4()
    tx.execute(
        "INSERT INTO delivery_facts(id,project_id,shipment_id,action,q_atoms,source_system,source_type,source_external_id,source_json,external_signatory,actor_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            str(ident),
            str(context.project_id),
            row["id"],
            kind,
            q,
            *key,
            command.source.model_dump_json(),
            command.external_signatory,
            str(context.actor.user_id),
            context.now.isoformat(),
        ),
    )
    if kind == "accept":
        for issue in command.issues:
            tx.execute(
                "INSERT INTO acceptance_issues VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    str(context.project_id),
                    row["id"],
                    str(ident),
                    issue.title,
                    str(issue.owner_id),
                    owners[str(issue.owner_id)],
                    int(issue.required),
                ),
            )
    return MutationResult(object_type="shipment", object_id=UUID(row["id"]))


def admitted_source(tx, pid, row, kind):
    from pydantic import ValidationError

    from .delivery_models import ClosureSourceRecord, DeliverySourceRecord
    from .imports import record_scope

    try:
        source = SourceRef.model_validate_json(row["source_json"])
        if source.mode != "manual" or source_key(source) != (
            row["source_system"],
            row["source_type"],
            row["source_external_id"],
        ):
            return None
        record = (
            ClosureSourceRecord(project_id=pid, source=source)
            if kind == "closure"
            else DeliverySourceRecord(
                project_id=pid,
                source=source,
                shipment_id=row["shipment_id"],
                object_type=kind,
            )
        )
        record_scope(tx, pid, record, object_type=kind)
        return source
    except (DomainError, ValidationError, ValueError):
        return None


def history(tx, pid, ident):
    rows = []
    for original in tx.execute(
        "SELECT * FROM audit_events WHERE project_id=? AND object_id=? ORDER BY id DESC LIMIT 100",
        (str(pid), str(ident)),
    ):
        row = dict(original)
        payload = json.loads(row["typed_payload"])
        if "source" in payload:
            safe = False
            try:
                source = SourceRef.model_validate(payload["source"])
                table = (
                    "closures"
                    if payload.get("action") == "closure.record"
                    else "delivery_facts"
                )
                fact = tx.execute(
                    f"SELECT * FROM {table} WHERE project_id=? AND source_system=? AND source_type=? AND source_external_id=?",
                    (str(pid), *source_key(source)),
                ).fetchone()
                safe = (
                    fact is not None
                    and admitted_source(tx, pid, fact, source.object_type) is not None
                )
            except (ValueError, TypeError):
                pass
            if not safe:
                payload.pop("source", None)
                payload.pop("evidence", None)
        row["typed_payload"] = json.dumps(payload)
        rows.append(row)
    return _history_rows(rows)


def value(tx, pid, row):
    p = project(tx, pid)
    ids = json.loads(row["units_json"])
    facts = totals(tx, pid, shipment_id=row["id"])
    shipped = (
        tx.execute(
            "SELECT COUNT(*) FROM shipment_items WHERE shipment_id=?", (row["id"],)
        ).fetchone()[0]
        * 10 ** p["unit_scale"]
    )
    reasons = (
        current_shipment_reasons(tx, pid, row["id"])
        if row["state"] in {"accepted", "held"}
        else []
    )
    return ShipmentValue(
        id=row["id"],
        order_line_id=row["order_line_id"],
        unit_ids=ids,
        boxes=json.loads(row["boxes_json"]),
        exchange_id=row["exchange_id"],
        state=("held" if reasons else "accepted") if shipped else row["state"],
        quantity=amount(row["q_atoms"], p),
        shipped=amount(shipped, p),
        signed=amount(facts.get("sign", 0), p),
        accepted=amount(facts.get("accept", 0), p),
        unit=row["unit"],
        remaining=remaining(tx, pid, row["order_line_id"]),
        blocking_reasons=reasons,
        issues=[
            dict(
                id=i["id"],
                title=i["title"],
                owner_id=i["owner_id"],
                owner_name=i["owner_name"],
                required=bool(i["required"]),
                resolved=i["resolution_id"] is not None,
                evidence=i["evidence"],
            )
            for i in tx.execute(
                "SELECT i.*,r.id resolution_id,r.evidence FROM acceptance_issues i LEFT JOIN acceptance_resolutions r ON r.issue_id=i.id WHERE i.project_id=? AND i.shipment_id=? ORDER BY (r.id IS NOT NULL),i.rowid LIMIT 100",
                (str(pid), row["id"]),
            )
        ],
        facts=[
            dict(
                id=f["id"],
                action=f["action"],
                quantity=amount(f["q_atoms"], p),
                source=admitted_source(tx, pid, f, "delivery_" + f["action"]),
                external_signatory=f["external_signatory"],
                recorded_by=f["actor_id"],
            )
            for f in tx.execute(
                "SELECT * FROM delivery_facts WHERE project_id=? AND shipment_id=? ORDER BY seq DESC LIMIT 100",
                (str(pid), row["id"]),
            )
        ],
    )


def summary(tx, pid, row):
    reasons = (
        current_shipment_reasons(tx, pid, row["id"])
        if row["state"] in {"accepted", "held"}
        else []
    )
    state = (
        ("held" if reasons else "accepted")
        if row["state"] in {"accepted", "held"}
        else row["state"]
    )
    return ObjectSummary(
        id=row["id"],
        project_id=pid,
        kind="shipment",
        title="Shipment " + row["id"][:8],
        state=state,
        blocking_reasons=reasons,
        quantity=amount(row["q_atoms"], project(tx, pid)),
        unit=row["unit"],
        version=1,
    )


def detail(tx, pid, ident):
    row = tx.execute(
        "SELECT * FROM shipments WHERE project_id=? AND id=?", (str(pid), str(ident))
    ).fetchone()
    if not row:
        return None
    return ObjectDetail[ShipmentValue](
        summary=summary(tx, pid, row),
        value=value(tx, pid, row),
        relations=[
            ObjectRelation(
                relation="order",
                project_id=pid,
                kind="order_line",
                id=row["order_line_id"],
            ),
            ObjectRelation(
                relation="authority",
                project_id=pid,
                kind="exchange",
                id=row["exchange_id"],
            ),
        ],
        evidence=[],
        history=history(tx, pid, row["id"]),
    )


for model, handler in [
    (RequestShipment, request_shipment),
    (DeliverySign, record_fact),
    (DeliveryAccept, record_fact),
]:
    COMMAND_REGISTRY.register(
        model, roles={"warehouse"}, qualifications=set(), handler=handler
    )
OBJECT_REGISTRY.register(
    "shipment",
    ShipmentValue,
    count=lambda tx, pid: tx.execute(
        "SELECT COUNT(*) FROM shipments WHERE project_id=?", (str(pid),)
    ).fetchone()[0],
    summaries=lambda tx, pid, limit, offset: [
        summary(tx, pid, r)
        for r in tx.execute(
            "SELECT * FROM shipments WHERE project_id=? ORDER BY created_at,id LIMIT ? OFFSET ?",
            (str(pid), limit, offset),
        )
    ],
    detail=detail,
)


def authorize(tx, actor, pid, command):
    if command.action == "delivery.resolve_issue":
        issue = own(tx, "acceptance_issues", pid, command.issue_id)
        grant = tx.execute(
            "SELECT roles_json FROM project_grants WHERE project_id=? AND user_id=? AND active=1",
            (str(pid), str(actor.user_id)),
        ).fetchone()
        if str(actor.user_id) != issue["owner_id"] and (
            not grant or "project_owner" not in json.loads(grant[0])
        ):
            raise DomainError(
                "FORBIDDEN",
                403,
                "Only the responsible owner or project owner can resolve this issue",
            )


def resolve_issue(tx, context, command):
    authorize(tx, context.actor, context.project_id, command)
    if tx.execute(
        "SELECT 1 FROM acceptance_resolutions WHERE issue_id=?",
        (str(command.issue_id),),
    ).fetchone():
        fail("Issue already resolved")
    row = own(tx, "acceptance_issues", context.project_id, command.issue_id)
    tx.execute(
        "INSERT INTO acceptance_resolutions VALUES (?,?,?,?,?,?)",
        (
            str(uuid4()),
            str(context.project_id),
            str(command.issue_id),
            command.evidence,
            str(context.actor.user_id),
            context.now.isoformat(),
        ),
    )
    return MutationResult(object_type="shipment", object_id=UUID(row["shipment_id"]))


def mandatory_source_discrepancies(tx, pid):
    """Owned unresolved authority mismatches block fulfillment/quality, never readiness/cost.

    A canonical accepted receipt or verified source reconciliation repairs transport
    discrepancies. An explicit authoritative rejection is a no-effect fact, not an
    unresolved source escape. Malformed/changed source associations stay mandatory.
    """
    return [
        f"Source discrepancy {r['exchange_id']}: {r['owner_name']} must reconcile authoritative evidence"
        for r in tx.execute(
            """SELECT d.* FROM exchange_discrepancies d JOIN exchanges e ON e.id=d.exchange_id WHERE d.project_id=? AND d.resolves_seq IS NULL AND e.phase NOT IN ('accepted','posted') AND e.action IN ('reservation.request','source.pull','production.start','production.interrupt','production.resume','eco.switch','shipment.request') AND d.reason<>'Authority rejected request' AND NOT EXISTS(SELECT 1 FROM exchange_discrepancies resolution WHERE resolution.resolves_seq=d.seq) ORDER BY d.seq""",
            (str(pid),),
        )
    ]


def feedback_close_predicates(tx, pid, kind):
    if kind != "quality":
        return []
    from .feedback import quality_blockers

    reasons = [b.reason + ": " + str(b.id) for b in quality_blockers(tx, pid)]
    if tx.execute(
        "SELECT 1 FROM freeze_requests r JOIN freeze_members m ON m.request_id=r.id LEFT JOIN freeze_confirmations f ON f.project_id=m.project_id AND f.object_kind=CASE WHEN m.unit_id IS NULL THEN 'material_lot' ELSE 'unit' END AND f.object_id=COALESCE(m.unit_id,m.lot_id) WHERE r.project_id=? AND r.seq=(SELECT MAX(x.seq) FROM freeze_requests x JOIN freeze_members y ON y.request_id=x.id WHERE y.project_id=m.project_id AND COALESCE(y.unit_id,y.lot_id)=COALESCE(m.unit_id,m.lot_id)) AND (f.request_id IS NULL OR f.source_version<r.source_version OR f.state='frozen') LIMIT 1",
        (str(pid),),
    ).fetchone():
        reasons.append("Quality containment remains pending or frozen")
    return reasons


def close_predicates(tx, project_id, kind) -> list[str]:
    if kind == "cost":
        return []
    p = project(tx, project_id)
    reasons = mandatory_source_discrepancies(tx, project_id)
    from .eco import eco_impacts, uncertain_stock

    for eco in tx.execute(
        "SELECT * FROM eco_changes WHERE project_id=? AND state='open'",
        (str(project_id),),
    ):
        if uncertain_stock(tx, project_id, eco, eco_impacts(tx, project_id, eco)):
            reasons.append(
                "Historical stock source coverage unresolved for ECO "
                + eco["id"]
                + "; engineering owner must request original source proof"
            )
    reasons += [
        f"Required acceptance issue {r['id']}: {r['owner_name']}"
        for r in tx.execute(
            "SELECT i.id,i.owner_name FROM acceptance_issues i WHERE i.project_id=? AND i.required=1 AND NOT EXISTS(SELECT 1 FROM acceptance_resolutions r WHERE r.issue_id=i.id)",
            (str(project_id),),
        )
    ]
    for shipment in tx.execute(
        "SELECT DISTINCT s.* FROM shipments s JOIN shipment_items i ON i.shipment_id=s.id WHERE s.project_id=?",
        (str(project_id),),
    ):
        if current_shipment_reasons(tx, project_id, shipment["id"]):
            reasons.append(
                "Shipped serial has a current quality/freeze escape: " + shipment["id"]
            )
    if kind == "fulfillment":
        policy = json.loads(p["contract_json"])["acceptance_required"]
        if policy == "unknown":
            reasons.append("Acceptance contract policy is unknown")
        for row in tx.execute(
            "SELECT id FROM order_lines WHERE project_id=?", (str(project_id),)
        ):
            b = remaining(tx, project_id, row[0])
            if (
                b.shipped != b.ordered
                or b.signed != b.ordered
                or (policy is True and b.accepted != b.ordered)
                or b.pending_shipment
            ):
                reasons.append(
                    "Order delivery/signature/acceptance remains incomplete: " + row[0]
                )
    elif kind == "quality":
        from .quality import quality_summary, final_good, scrapped

        if any(
            not final_good(tx, project_id, r[0]) and not scrapped(tx, project_id, r[0])
            for r in tx.execute(
                "SELECT DISTINCT unit_id FROM quality_tests WHERE project_id=?",
                (str(project_id),),
            )
        ):
            reasons.append(
                "Measured failed or invalid test evidence still requires qualified quality disposition"
            )

        if quality_summary(tx, project_id).open_nonconformances:
            reasons.append("Mandatory nonconformances remain unresolved")
        if tx.execute(
            "SELECT 1 FROM shipment_freeze_events f WHERE f.project_id=? AND f.state<>'released' AND f.seq=(SELECT MAX(x.seq) FROM shipment_freeze_events x WHERE x.project_id=f.project_id AND x.unit_id=f.unit_id)",
            (str(project_id),),
        ).fetchone():
            reasons.append("Quality containment remains pending or frozen")
    reasons.extend(feedback_close_predicates(tx, project_id, kind))
    return reasons


def record_closure(tx, context, command):
    from .delivery_models import ClosureSourceRecord
    from .imports import admit_records

    record = ClosureSourceRecord(project_id=context.project_id, source=command.source)
    admit_records(tx, context, [record], object_type="closure", trusted=False)
    if command.source.mode != "manual":
        fail(
            "Closure requires explicit manual evidence; API/ERP authority must use a trusted integration"
        )
    reasons = close_predicates(tx, context.project_id, command.kind)
    if reasons:
        fail("; ".join(reasons))
    key = source_key(command.source)
    if tx.execute(
        "SELECT 1 FROM closures WHERE source_system=? AND source_type=? AND source_external_id=?",
        key,
    ).fetchone():
        fail("Closure evidence identity already recorded")
    ident = uuid4()
    tx.execute(
        "INSERT INTO closures(id,project_id,kind,source_system,source_type,source_external_id,source_json,evidence,actor_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            str(ident),
            str(context.project_id),
            command.kind,
            *key,
            command.source.model_dump_json(),
            command.evidence,
            str(context.actor.user_id),
            context.now.isoformat(),
        ),
    )
    return MutationResult(object_type="closure", object_id=ident)


def closure_summary(tx, pid, row):
    return ObjectSummary(
        id=row["id"],
        project_id=pid,
        kind="closure",
        title=row["kind"] + " closure",
        state="blocked" if close_predicates(tx, pid, row["kind"]) else "closed",
        source=admitted_source(tx, pid, row, "closure"),
        version=1,
    )


def closure_detail(tx, pid, ident):
    from .delivery_models import ClosureValue

    row = tx.execute(
        "SELECT * FROM closures WHERE project_id=? AND id=?", (str(pid), str(ident))
    ).fetchone()
    if not row:
        return None
    reasons = close_predicates(tx, pid, row["kind"])
    return ObjectDetail[ClosureValue](
        summary=closure_summary(tx, pid, row),
        value=ClosureValue(
            id=row["id"],
            closure_kind=row["kind"],
            status="blocked" if reasons else "closed",
            source=admitted_source(tx, pid, row, "closure"),
            evidence=row["evidence"],
            blocking_reasons=reasons,
        ),
        relations=[],
        evidence=[],
        history=history(tx, pid, row["id"]),
    )


from .delivery_models import ClosureRecord, ClosureValue, ResolveIssue

COMMAND_REGISTRY.register(
    ResolveIssue,
    roles={
        "project_owner",
        "engineering",
        "planner",
        "supply",
        "production",
        "quality",
        "warehouse",
    },
    qualifications=set(),
    handler=resolve_issue,
)
COMMAND_REGISTRY.register(
    ClosureRecord, roles={"project_owner"}, qualifications=set(), handler=record_closure
)
OBJECT_REGISTRY.register(
    "closure",
    ClosureValue,
    count=lambda tx, pid: tx.execute(
        "SELECT COUNT(*) FROM closures WHERE project_id=?", (str(pid),)
    ).fetchone()[0],
    summaries=lambda tx, pid, limit, offset: [
        closure_summary(tx, pid, r)
        for r in tx.execute(
            "SELECT * FROM closures WHERE project_id=? ORDER BY seq LIMIT ? OFFSET ?",
            (str(pid), limit, offset),
        )
    ],
    detail=closure_detail,
)


def fulfillment_status(tx, pid):
    if close_predicates(tx, pid, "fulfillment"):
        return "open"
    return (
        "closed"
        if tx.execute(
            "SELECT 1 FROM closures WHERE project_id=? AND kind='fulfillment' LIMIT 1",
            (str(pid),),
        ).fetchone()
        else "eligible"
    )


def can_resolve_issue(tx, actor, pid):
    return (
        tx.execute(
            "SELECT 1 FROM acceptance_issues i WHERE i.project_id=? AND NOT EXISTS(SELECT 1 FROM acceptance_resolutions r WHERE r.issue_id=i.id) AND (i.owner_id=? OR EXISTS(SELECT 1 FROM project_grants g,json_each(g.roles_json) role WHERE g.project_id=i.project_id AND g.user_id=? AND g.active=1 AND role.value='project_owner')) LIMIT 1",
            (str(pid), str(actor.user_id), str(actor.user_id)),
        ).fetchone()
        is not None
    )
