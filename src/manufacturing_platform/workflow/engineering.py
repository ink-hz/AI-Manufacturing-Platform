"""Immutable engineering snapshots and attributable work order evidence."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from .commands import COMMAND_REGISTRY
from .contracts import (
    DomainError,
    MutationResult,
    ObjectDetail,
    ObjectEvidence,
    ObjectKind,
    ObjectRelation,
    ObjectSummary,
)
from .engineering_models import (
    CustomerApprovalView,
    EngineeringRevision,
    HandoffView,
    RecordCustomerApproval,
    RecordHandoff,
    RecordReadiness,
    RecordRevision,
    RegisterWorkOrder,
    WorkOrder,
)
from .orders import _history_rows, amount, atoms, own, project, source_ok
from .queries import OBJECT_REGISTRY


def fail(reason, code="PRECONDITION_FAILED", status=409):
    raise DomainError(code, status, reason, blocking_reasons=[reason])


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def record_revision(tx, context, command: RecordRevision):
    if any(item.status == "pending" for item in command.items):
        fail("fixed revision contains pending package items")
    exists = tx.execute(
        "SELECT 1 FROM engineering_revisions WHERE project_id=? AND package_id=? AND revision=?",
        (str(context.project_id), command.package_id, command.revision),
    ).fetchone()
    if exists:
        fail("fixed engineering revision already registered", "SOURCE_CONFLICT")
    ident = str(uuid4())
    payload = command.model_dump(mode="json")
    fingerprint = hashlib.sha256(
        _json(
            {
                k: v
                for k, v in payload.items()
                if k not in {"operation_id", "expected_version", "action"}
            }
        ).encode()
    ).hexdigest()
    tx.execute(
        "INSERT INTO engineering_revisions VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            ident,
            str(context.project_id),
            command.package_id,
            command.revision,
            command.customer_revision,
            command.internal_revision,
            command.firmware_version,
            _json(command.test_spec.model_dump(mode="json")),
            fingerprint,
            context.now.isoformat(),
        ),
    )
    for position, item in enumerate(command.items):
        tx.execute(
            "INSERT INTO revision_items VALUES (?,?,?,?,?)",
            (
                ident,
                str(context.project_id),
                position,
                item.id,
                _json(item.model_dump(mode="json")),
            ),
        )
    for position, step in enumerate(command.route_steps):
        tx.execute(
            "INSERT INTO revision_routes VALUES (?,?,?,?)",
            (
                ident,
                str(context.project_id),
                position,
                _json(step.model_dump(mode="json")),
            ),
        )
    return MutationResult(object_type=ObjectKind.revision, object_id=UUID(ident))


def record_handoff(tx, context, command: RecordHandoff):
    rev = own(tx, "engineering_revisions", context.project_id, command.revision_id)
    ident = str(uuid4())
    status = (
        "verified"
        if command.decision == "accepted"
        and command.received_revision == rev["internal_revision"]
        else "rejected"
    )
    tx.execute(
        "INSERT INTO handoffs VALUES (?,?,?,?,?,?,?,?,?)",
        (
            ident,
            str(context.project_id),
            str(command.revision_id),
            command.to_system,
            command.received_revision,
            command.decision,
            status,
            command.evidence,
            context.now.isoformat(),
        ),
    )
    return MutationResult(
        object_type=ObjectKind.revision, object_id=command.revision_id
    )


def record_customer_approval(tx, context, command: RecordCustomerApproval):
    own(tx, "engineering_revisions", context.project_id, command.revision_id)
    p = project(tx, context.project_id)
    if command.customer_id != p["customer_id"]:
        fail("customer approval must name project customer")
    ident = str(uuid4())
    tx.execute(
        "INSERT INTO customer_approvals VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            ident,
            str(context.project_id),
            str(command.revision_id),
            command.customer_id,
            command.external_signatory,
            command.method,
            command.decision,
            command.evidence,
            str(context.actor.user_id),
            context.now.isoformat(),
            tx.execute(
                "SELECT COALESCE(MAX(accepted_seq),0)+1 FROM customer_approvals WHERE project_id=?",
                (str(context.project_id),),
            ).fetchone()[0],
        ),
    )
    return MutationResult(
        object_type=ObjectKind.revision, object_id=command.revision_id
    )


def register_work_order(tx, context, command: RegisterWorkOrder):
    p = project(tx, context.project_id)
    order = own(tx, "order_lines", context.project_id, command.order_line_id)
    own(tx, "engineering_revisions", context.project_id, command.revision_id)
    source_ok(command.source, "work_order")
    if (
        order["state"] != "active"
        or tx.execute(
            "SELECT 1 FROM commitment_changes WHERE order_line_id=? AND state='pending'",
            (order["id"],),
        ).fetchone()
    ):
        fail("firm reviewed order must be active and settled")
    demand = own(tx, "demands", context.project_id, order["demand_id"])
    if demand["demand_kind"] != "firm":
        fail("firm reviewed order authorization required")
    from .orders import DIMENSIONS, latest_reviews

    if any(
        latest_reviews(tx, context.project_id, demand["id"]).get(d) != "approved"
        for d in DIMENSIONS
    ):
        fail("five current order reviews required")
    if command.unit != order["unit"]:
        fail("work order unit differs from formal order")
    q = atoms(command.quantity, command.unit, p)
    trial = atoms(command.trial_quantity, command.unit, p)
    used = tx.execute(
        "SELECT COALESCE(SUM(obligation_atoms),0) FROM effective_work_orders WHERE project_id=? AND order_line_id=?",
        (str(context.project_id), order["id"]),
    ).fetchone()[0]
    if q + used > order["current_q_atoms"]:
        fail("work orders exceed formal order")
    if tx.execute(
        "SELECT 1 FROM work_orders WHERE source_system=? AND source_type=? AND source_external_id=?",
        (command.source.system, command.source.object_type, command.source.external_id),
    ).fetchone():
        fail("external work order number already registered", "SOURCE_CONFLICT")
    ident = str(uuid4())
    tx.execute(
        "INSERT INTO work_orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ident,
            str(context.project_id),
            order["id"],
            str(command.revision_id),
            q,
            command.unit,
            command.purpose,
            trial,
            command.source.system,
            command.source.object_type,
            command.source.external_id,
            command.source.version,
            command.source.model_dump_json(),
            command.planned_start.isoformat(),
            command.planned_end.isoformat(),
        ),
    )
    return MutationResult(object_type=ObjectKind.work_order, object_id=UUID(ident))


def record_readiness(tx, context, command: RecordReadiness):
    own(tx, "work_orders", context.project_id, command.work_order_id)
    ident = str(uuid4())
    tx.execute(
        "INSERT INTO readiness_checks VALUES (?,?,?,?,?,?,?,?,?)",
        (
            ident,
            str(context.project_id),
            str(command.work_order_id),
            command.kind,
            command.reference,
            command.evidence,
            command.valid_until.isoformat(),
            command.decision,
            context.now.isoformat(),
        ),
    )
    return MutationResult(
        object_type=ObjectKind.work_order, object_id=command.work_order_id
    )


def fixed_revision(tx, project_id, revision_id) -> EngineeringRevision:
    row = own(tx, "engineering_revisions", project_id, revision_id)
    items = [
        json.loads(r["payload_json"])
        for r in tx.execute(
            "SELECT payload_json FROM revision_items WHERE revision_id=? AND project_id=? ORDER BY position",
            (row["id"], str(project_id)),
        )
    ]
    routes = [
        json.loads(r["payload_json"])
        for r in tx.execute(
            "SELECT payload_json FROM revision_routes WHERE revision_id=? AND project_id=? ORDER BY position",
            (row["id"], str(project_id)),
        )
    ]
    handoffs = [
        HandoffView(
            id=r["id"],
            to_system=r["to_system"],
            received_revision=r["received_revision"],
            status=r["status"],
            evidence=r["evidence"],
        )
        for r in tx.execute(
            "SELECT * FROM handoffs WHERE revision_id=? AND project_id=? ORDER BY created_at,id",
            (row["id"], str(project_id)),
        )
    ]
    approvals = [
        CustomerApprovalView(
            source=json.loads(r["authority_source"]) if r["authority_source"] else None,
            id=r["id"],
            method=r["method"],
            recorded_by=r["actor_id"],
            customer_id=r["customer_id"],
            external_signatory=r["external_signatory"],
            decision=r["decision"],
            evidence=r["evidence"],
        )
        for r in tx.execute(
            "SELECT a.*,(SELECT c.source_json FROM source_confirmations c WHERE c.fact_id=a.id AND c.project_id=a.project_id ORDER BY c.seq DESC LIMIT 1) authority_source FROM customer_approvals a WHERE revision_id=? AND project_id=? ORDER BY accepted_seq",
            (row["id"], str(project_id)),
        )
    ]
    return EngineeringRevision(
        id=row["id"],
        project_id=row["project_id"],
        package_id=row["package_id"],
        revision=row["revision"],
        customer_revision=row["customer_revision"],
        internal_revision=row["internal_revision"],
        items=tuple(items),
        route_steps=tuple(routes),
        test_spec=json.loads(row["test_spec_json"]),
        firmware_version=row["firmware_version"],
        content_hash=row["content_hash"],
        handoffs=tuple(handoffs),
        customer_approvals=tuple(approvals),
    )


def _history(tx, project_id, object_id):
    rows = tx.execute(
        "SELECT * FROM audit_events WHERE project_id=? AND object_id=? ORDER BY id",
        (str(project_id), str(object_id)),
    ).fetchall()
    return _history_rows(rows)


def revision_summary(row):
    return ObjectSummary(
        id=row["id"],
        kind=ObjectKind.revision,
        project_id=row["project_id"],
        title=f"{row['package_id']} {row['revision']}",
        state="fixed",
        version=1,
    )


def work_order_summary(row, p):
    return ObjectSummary(
        id=row["id"],
        kind=ObjectKind.work_order,
        project_id=row["project_id"],
        title=row["source_external_id"],
        state="planned",
        quantity=amount(row["q_atoms"], p),
        unit=row["unit"],
        source=json.loads(row["source_json"]),
        version=row["source_version"],
    )


def count(table):
    def reader(tx, project_id):
        return tx.execute(
            f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (str(project_id),)
        ).fetchone()[0]

    return reader


def revision_page(tx, project_id, limit, offset):
    return [
        revision_summary(r)
        for r in tx.execute(
            "SELECT * FROM engineering_revisions WHERE project_id=? ORDER BY created_at,id LIMIT ? OFFSET ?",
            (str(project_id), limit, offset),
        )
    ]


def work_order_page(tx, project_id, limit, offset):
    p = project(tx, project_id)
    return [
        work_order_summary(r, p)
        for r in tx.execute(
            "SELECT * FROM work_orders WHERE project_id=? ORDER BY planned_start,id LIMIT ? OFFSET ?",
            (str(project_id), limit, offset),
        )
    ]


def revision_detail(tx, project_id, object_id):
    row = tx.execute(
        "SELECT * FROM engineering_revisions WHERE id=? AND project_id=?",
        (str(object_id), str(project_id)),
    ).fetchone()
    if row is None:
        return None
    value = fixed_revision(tx, project_id, object_id)
    evidence = [ObjectEvidence(reference=i.evidence) for i in value.items if i.evidence]
    evidence += [ObjectEvidence(reference=h.evidence) for h in value.handoffs]
    evidence += [ObjectEvidence(reference=a.evidence) for a in value.customer_approvals]
    return ObjectDetail[EngineeringRevision](
        summary=revision_summary(row),
        value=value,
        relations=[],
        evidence=evidence,
        history=_history(tx, project_id, object_id),
    )


def work_order_detail(tx, project_id, object_id):
    row = tx.execute(
        "SELECT * FROM work_orders WHERE id=? AND project_id=?",
        (str(object_id), str(project_id)),
    ).fetchone()
    if row is None:
        return None
    p = project(tx, project_id)
    source = json.loads(row["source_json"])
    from .execution import work_order_events
    from .readiness import evaluate

    now = datetime.now(UTC)
    event_total, events = work_order_events(tx, project_id, object_id)
    held_rows = tx.execute(
        """SELECT s.id,s.mode,s.exchange_id,s.accepted_receipt_id,u.sn
           FROM start_requests s JOIN start_units su ON su.start_id=s.id
           JOIN units u ON u.id=su.unit_id AND u.project_id=s.project_id
           WHERE s.project_id=? AND s.work_order_id=? AND s.accepted_receipt_id IS NOT NULL
             AND u.state='start_pending' AND u.accepted_start_id=s.id
           ORDER BY s.accepted_seq,u.registered_seq LIMIT 500""",
        (str(project_id), str(object_id)),
    ).fetchall()
    held = {}
    for scope in held_rows:
        item = held.setdefault(
            scope["id"],
            {
                "id": scope["id"],
                "mode": scope["mode"],
                "sns": [],
                "exchange_id": scope["exchange_id"],
                "receipt_id": scope["accepted_receipt_id"],
            },
        )
        item["sns"].append(scope["sn"])
    value = WorkOrder(
        order_line_id=row["order_line_id"],
        revision_id=row["revision_id"],
        quantity=amount(row["q_atoms"], p),
        unit=row["unit"],
        purpose=row["purpose"],
        trial_quantity=amount(row["trial_q_atoms"], p),
        source=source,
        planned_start=row["planned_start"],
        planned_end=row["planned_end"],
        trial_readiness=evaluate(tx, project_id, object_id, "trial", now),
        bulk_readiness=evaluate(tx, project_id, object_id, "bulk", now),
        remaining_obligation=amount(
            tx.execute(
                "SELECT obligation_atoms FROM effective_work_orders WHERE id=?",
                (row["id"],),
            ).fetchone()[0],
            p,
        ),
        execution_event_total=event_total,
        execution_events=events,
        held_start_scopes=list(held.values()),
    )
    relations = [
        ObjectRelation(
            relation="authorized_by",
            project_id=project_id,
            kind=ObjectKind.order_line,
            id=row["order_line_id"],
        ),
        ObjectRelation(
            relation="fixed_revision",
            project_id=project_id,
            kind=ObjectKind.revision,
            id=row["revision_id"],
        ),
    ]
    evidence = [ObjectEvidence(reference=source["evidence"], source=source)]
    evidence += [
        ObjectEvidence(reference=r["evidence"])
        for r in tx.execute(
            "SELECT evidence FROM readiness_checks WHERE project_id=? AND work_order_id=? ORDER BY created_at,id",
            (str(project_id), str(object_id)),
        )
    ]
    return ObjectDetail[WorkOrder](
        summary=work_order_summary(row, p),
        value=value,
        relations=relations,
        evidence=evidence,
        history=_history(tx, project_id, object_id),
    )


def register():
    for model, roles, handler in (
        (RecordRevision, {"engineering"}, record_revision),
        (RecordHandoff, {"engineering"}, record_handoff),
        (RecordCustomerApproval, {"project_owner"}, record_customer_approval),
        (RegisterWorkOrder, {"planner"}, register_work_order),
        (RecordReadiness, {"engineering"}, record_readiness),
    ):
        COMMAND_REGISTRY.register(
            model,
            roles=roles,
            qualifications={"readiness_verification"}
            if model is RecordReadiness
            else set(),
            handler=handler,
        )
    OBJECT_REGISTRY.register(
        ObjectKind.revision,
        EngineeringRevision,
        count=count("engineering_revisions"),
        summaries=revision_page,
        detail=revision_detail,
    )
    OBJECT_REGISTRY.register(
        ObjectKind.work_order,
        WorkOrder,
        count=count("work_orders"),
        summaries=work_order_page,
        detail=work_order_detail,
    )


register()
