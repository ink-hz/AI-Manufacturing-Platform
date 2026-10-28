"""Reviewed demand, documented orders, immutable changes and allocations."""

import json
from decimal import Decimal
from uuid import UUID, uuid4

from .commands import COMMAND_REGISTRY
from .contracts import (
    DomainError,
    MutationResult,
    ObjectDetail,
    ObjectEvidence,
    ObjectHistory,
    ObjectKind,
    ObjectRelation,
    ObjectSummary,
)
from .order_models import (
    AllocateOrder,
    ChangeOrder,
    CommitmentChangeValue,
    DemandValue,
    OrderLineValue,
    RecordDemand,
    RegisterOrder,
    ResolveOrderChange,
    ReviewDemand,
    WorkOrderImpactPreview,
)
from .queries import OBJECT_REGISTRY

DIMENSIONS = ("technical", "material", "capacity", "commercial", "quality")


def fail(message, *, code="PRECONDITION_FAILED", reasons=None):
    raise DomainError(
        code,
        409 if code != "NOT_FOUND" else 404,
        message,
        blocking_reasons=reasons or [],
    )


def own(tx, table, project_id, object_id):
    row = tx.execute(
        f"SELECT * FROM {table} WHERE id=? AND project_id=?",
        (str(object_id), str(project_id)),
    ).fetchone()
    if row is None:
        fail("Workflow resource not found", code="NOT_FOUND")
    return row


def project(tx, project_id):
    return tx.execute(
        "SELECT * FROM projects WHERE id=?", (str(project_id),)
    ).fetchone()


def atoms(quantity, unit, project_row):
    if unit != project_row["unit_code"]:
        fail("Unit does not match project")
    scale = project_row["unit_scale"]
    value = quantity * (10**scale)
    if value != value.to_integral_value() or value > 2**63 - 1:
        fail("Quantity exceeds unit precision or range")
    return int(value)


def amount(q_atoms, project_row):
    return format(Decimal(q_atoms).scaleb(-project_row["unit_scale"]), "f")


def source_ok(source, object_type):
    if source.object_type != object_type or source.mode not in {"manual", "file"}:
        fail("Source type or mode is not an authorized A2 registration")
    if source.collected_at < source.occurred_at:
        fail("Source collection precedes occurrence")


def source_key(source):
    """Normalize persisted source identity while retaining the raw SourceRef snapshot."""

    def part(name):
        return source[name] if isinstance(source, dict) else getattr(source, name)

    key = (
        part("system").strip().casefold(),
        part("object_type").strip().casefold(),
        part("external_id").strip(),
    )
    if not all(key):
        raise ValueError("source identity must not be blank")
    return key


def source_conflict(tx, source):
    key = (source.system, source.object_type, source.external_id)
    for table in ("demands", "order_lines"):
        if tx.execute(
            f"SELECT 1 FROM {table} WHERE source_system=? AND source_type=? AND source_external_id=?",
            key,
        ).fetchone():
            fail(
                "External source identity is already registered", code="SOURCE_CONFLICT"
            )


def dispatch_record_demand(tx, context, command: RecordDemand):
    p = project(tx, context.project_id)
    source_ok(command.source, "demand")
    source_conflict(tx, command.source)
    if command.product != p["product"]:
        fail("Demand product does not match project")
    q = atoms(command.quantity, command.unit, p)
    if command.supersedes_demand_id:
        prior = own(tx, "demands", context.project_id, command.supersedes_demand_id)
        if prior["product"] != command.product or prior["unit"] != command.unit:
            fail("Superseded demand has different product or unit")
        if prior["demand_kind"] == "firm":
            fail("A firm demand cannot be silently superseded")
        if command.kind != "firm":
            fail("Superseding demand must be firm")
    ident = str(uuid4())
    tx.execute(
        "INSERT INTO demands VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ident,
            str(context.project_id),
            command.kind,
            command.product,
            q,
            command.unit,
            command.due_date.isoformat(),
            str(command.supersedes_demand_id) if command.supersedes_demand_id else None,
            command.source.system,
            command.source.object_type,
            command.source.external_id,
            command.source.version,
            command.source.model_dump_json(),
            context.now.isoformat(),
        ),
    )
    return MutationResult(object_type=ObjectKind.demand, object_id=UUID(ident))


def dispatch_review_demand(tx, context, command: ReviewDemand):
    own(tx, "demands", context.project_id, command.demand_id)
    tx.execute(
        "INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?)",
        (
            str(uuid4()),
            str(context.project_id),
            str(command.demand_id),
            command.dimension,
            command.decision,
            command.evidence,
            str(context.actor.user_id),
            context.now.isoformat(),
        ),
    )
    return MutationResult(object_type=ObjectKind.demand, object_id=command.demand_id)


def latest_reviews(tx, project_id, demand_id):
    rows = tx.execute(
        "SELECT dimension,decision FROM reviews WHERE project_id=? AND demand_id=? "
        "ORDER BY reviewed_at,id",
        (str(project_id), str(demand_id)),
    ).fetchall()
    return {r["dimension"]: r["decision"] for r in rows}


def dispatch_register_order(tx, context, command: RegisterOrder):
    p = project(tx, context.project_id)
    demand = own(tx, "demands", context.project_id, command.demand_id)
    source_ok(command.source, "order_line")
    source_conflict(tx, command.source)
    reviews = latest_reviews(tx, context.project_id, command.demand_id)
    blocking = [d for d in DIMENSIONS if reviews.get(d) != "approved"]
    if demand["demand_kind"] != "firm":
        blocking.insert(0, "firm demand required")
    if blocking:
        fail("Firm demand and five approvals required", reasons=blocking)
    if command.due_date.isoformat() != demand["due_date"]:
        fail("Order due date differs from the reviewed commercial commitment")
    q = atoms(command.quantity, command.unit, p)
    if command.unit != demand["unit"]:
        fail("Order unit does not match demand")
    prior = tx.execute(
        "SELECT COALESCE(SUM(original_q_atoms),0) FROM order_lines WHERE demand_id=? AND project_id=?",
        (str(command.demand_id), str(context.project_id)),
    ).fetchone()[0]
    if q + prior > demand["q_atoms"]:
        fail("Formal orders exceed reviewed firm demand")
    ident = str(uuid4())
    tx.execute(
        "INSERT INTO order_lines VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ident,
            str(context.project_id),
            str(command.demand_id),
            q,
            q,
            command.unit,
            command.due_date.isoformat(),
            command.due_date.isoformat(),
            "active",
            command.source.system,
            command.source.object_type,
            command.source.external_id,
            command.source.version,
            command.source.model_dump_json(),
            context.now.isoformat(),
        ),
    )
    return MutationResult(object_type=ObjectKind.order_line, object_id=UUID(ident))


def allocated(tx, project_id, order_id=None, work_order_id=None):
    clauses = ["project_id=?"]
    args = [str(project_id)]
    if order_id is not None:
        clauses.append("order_line_id=?")
        args.append(str(order_id))
    if work_order_id is not None:
        clauses.append("work_order_id=?")
        args.append(str(work_order_id))
    return tx.execute(
        "SELECT COALESCE(SUM(q_atoms),0) FROM effective_allocations WHERE "
        + " AND ".join(clauses),
        args,
    ).fetchone()[0]


def shipped_atoms(tx, project_id, order_id, project_row):
    if not tx.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shipment_items'"
    ).fetchone():
        return 0
    # C2 records one accepted shipment item per serialised finished unit.
    count = tx.execute(
        "SELECT COUNT(DISTINCT unit_id) FROM shipment_items WHERE project_id=? AND order_line_id=?",
        (str(project_id), str(order_id)),
    ).fetchone()[0]
    return count * (10 ** project_row["unit_scale"])


def project_shipped_atoms(tx, project_row):
    if not tx.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shipment_items'"
    ).fetchone():
        return 0
    # C2 contract: one accepted shipment_items row per unit_id, with project_id
    # and order_line_id matching its linked order_lines row.
    count = tx.execute(
        "SELECT COUNT(DISTINCT si.unit_id) FROM shipment_items si "
        "JOIN order_lines o ON o.id=si.order_line_id AND o.project_id=si.project_id "
        "WHERE si.project_id=?",
        (project_row["id"],),
    ).fetchone()[0]
    return count * (10 ** project_row["unit_scale"])


def dispatch_change_order(tx, context, command: ChangeOrder):
    p = project(tx, context.project_id)
    order = own(tx, "order_lines", context.project_id, command.order_line_id)
    if order["state"] != "active":
        fail("Order is not active")
    source_ok(command.source, "order_line")
    if (command.source.system, command.source.external_id) != (
        order["source_system"],
        order["source_external_id"],
    ):
        fail("Change source must revise the same formal order")
    if command.source.version <= order["source_version"]:
        fail("Change source revision must increase")
    new_q = atoms(command.new_quantity, order["unit"], p)
    if command.cancel and new_q != order["current_q_atoms"]:
        fail("Cancellation must preserve the proposed quantity")
    pending = tx.execute(
        "SELECT 1 FROM commitment_changes WHERE order_line_id=? AND state='pending'",
        (str(command.order_line_id),),
    ).fetchone()
    if pending:
        fail("Prior order change remains pending")
    ident = str(uuid4())
    tx.execute(
        "INSERT INTO commitment_changes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ident,
            str(context.project_id),
            str(command.order_line_id),
            order["current_q_atoms"],
            0 if command.cancel else new_q,
            order["unit"],
            order["current_due"],
            command.new_due_date.isoformat(),
            int(command.cancel),
            command.reason,
            "pending",
            command.source.version,
            command.source.model_dump_json(),
            context.now.isoformat(),
            None,
        ),
    )
    registered = {
        r["id"]: r["q_atoms"]
        for r in tx.execute(
            "SELECT id,obligation_atoms AS q_atoms FROM effective_work_orders WHERE project_id=? AND order_line_id=?",
            (str(context.project_id), str(command.order_line_id)),
        )
    }
    rows = tx.execute(
        "SELECT work_order_id,SUM(q_atoms) AS quantity FROM effective_allocations WHERE project_id=? AND order_line_id=? GROUP BY work_order_id",
        (str(context.project_id), str(command.order_line_id)),
    ).fetchall()
    for r in rows:
        registered[r["work_order_id"]] = max(
            registered.get(r["work_order_id"], 0), r["quantity"]
        )
    for work_order_id, quantity in sorted(registered.items()):
        tx.execute(
            "INSERT INTO change_impacts VALUES (?,?,?,?,?,?,?,?)",
            (
                ident,
                str(context.project_id),
                "work_order",
                work_order_id,
                quantity,
                order["unit"],
                None,
                None,
            ),
        )
    return MutationResult(
        object_type=ObjectKind.commitment_change, object_id=UUID(ident)
    )


def dispatch_resolve_change(tx, context, command: ResolveOrderChange):
    change = own(tx, "commitment_changes", context.project_id, command.change_id)
    if change["state"] != "pending":
        fail("Change has already been resolved")
    order = own(tx, "order_lines", context.project_id, change["order_line_id"])
    if (
        order["source_version"] >= change["source_version"]
        or order["current_q_atoms"] != change["old_q_atoms"]
    ):
        fail("Order has changed since proposal")
    impacts = tx.execute(
        "SELECT * FROM change_impacts WHERE change_id=? AND project_id=?",
        (str(command.change_id), str(context.project_id)),
    ).fetchall()
    expected = {(r["object_type"], r["object_id"]) for r in impacts}
    supplied = {(d.object_type, str(d.object_id)) for d in command.dispositions}
    if len(supplied) != len(command.dispositions) or supplied != expected:
        fail("Every affected obligation requires one disposition")
    registered_total = tx.execute(
        "SELECT COALESCE(SUM(obligation_atoms),0) FROM effective_work_orders WHERE project_id=? AND order_line_id=?",
        (str(context.project_id), order["id"]),
    ).fetchone()[0]
    if change["new_q_atoms"] < registered_total:
        fail(
            "Authoritative cancellation or split of registered work orders is required",
            reasons=["registered work orders"],
        )
    if any(
        d.object_type == "work_order"
        and d.decision != "retain"
        and not tx.execute(
            "SELECT 1 FROM eco_switches WHERE project_id=? AND work_order_id=? AND accepted_receipt_id IS NOT NULL",
            (str(context.project_id), str(d.object_id)),
        ).fetchone()
        for d in command.dispositions
    ):
        fail(
            "Work order cancellation or transfer requires an authoritative receipt",
            reasons=["registered work orders"],
        )
    allocation = allocated(tx, context.project_id, order_id=order["id"])
    if change["new_q_atoms"] < allocation:
        fail(
            "Authoritative cancellation of allocated work is required",
            reasons=["allocated work orders"],
        )
    if change["new_q_atoms"] < shipped_atoms(
        tx, context.project_id, order["id"], project(tx, context.project_id)
    ):
        fail(
            "Order quantity cannot fall below shipped units",
            reasons=["delivered units"],
        )
    for d in command.dispositions:
        tx.execute(
            "UPDATE change_impacts SET decision=?,evidence=? WHERE change_id=? AND object_type=? AND object_id=?",
            (
                d.decision,
                d.evidence,
                str(command.change_id),
                d.object_type,
                str(d.object_id),
            ),
        )
    tx.execute(
        "UPDATE order_lines SET current_q_atoms=?,current_due=?,state=?,source_version=?,source_json=? WHERE id=? AND project_id=?",
        (
            change["new_q_atoms"],
            change["new_due"],
            "cancelled" if change["cancel"] else "active",
            change["source_version"],
            change["source_json"],
            order["id"],
            str(context.project_id),
        ),
    )
    tx.execute(
        "UPDATE commitment_changes SET state='applied',resolved_at=? WHERE id=? AND project_id=?",
        (context.now.isoformat(), str(command.change_id), str(context.project_id)),
    )
    return MutationResult(
        object_type=ObjectKind.commitment_change, object_id=command.change_id
    )


def dispatch_allocate_order(tx, context, command: AllocateOrder):
    from .eco import scope_locked

    if scope_locked(tx, context.project_id, command.work_order_id):
        fail("ECO boundary prevents new allocation to original scope")
    p = project(tx, context.project_id)
    order = own(tx, "order_lines", context.project_id, command.order_line_id)
    if order["state"] != "active":
        fail("Order is not active")
    q = atoms(command.quantity, command.unit, p)
    if command.unit != order["unit"]:
        fail("Allocation unit does not match order")
    if tx.execute(
        "SELECT 1 FROM commitment_changes WHERE order_line_id=? AND state='pending'",
        (order["id"],),
    ).fetchone():
        fail("Order change is pending")
    if not tx.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='work_orders'"
    ).fetchone():
        fail("Work order registration is unavailable")
    work_order = tx.execute(
        "SELECT project_id,order_line_id,obligation_atoms AS q_atoms,unit FROM effective_work_orders WHERE id=?",
        (str(command.work_order_id),),
    ).fetchone()
    if work_order is None or work_order["project_id"] != str(context.project_id):
        fail("Workflow resource not found", code="NOT_FOUND")
    if work_order["unit"] != command.unit:
        fail("Work order unit does not match allocation")
    if work_order["order_line_id"] != order["id"]:
        fail("Work order is bound to a different formal order")
    if (
        allocated(tx, context.project_id, order_id=order["id"]) + q
        > order["current_q_atoms"]
    ):
        fail("Allocation exceeds order quantity")
    if (
        allocated(tx, context.project_id, work_order_id=command.work_order_id) + q
        > work_order["q_atoms"]
    ):
        fail("Allocation exceeds work order quantity")
    ident = str(uuid4())
    tx.execute(
        "INSERT INTO allocations VALUES (?,?,?,?,?,?,?)",
        (
            ident,
            str(context.project_id),
            order["id"],
            str(command.work_order_id),
            q,
            command.unit,
            context.now.isoformat(),
        ),
    )
    return MutationResult(
        object_type=ObjectKind.order_line, object_id=command.order_line_id
    )


def _history(tx, project_id, object_id):
    rows = tx.execute(
        "SELECT * FROM audit_events WHERE project_id=? AND object_id=? ORDER BY id",
        (str(project_id), str(object_id)),
    ).fetchall()
    return _history_rows(rows)


def _history_rows(rows):
    events = []
    for row in rows:
        payload = json.loads(row["typed_payload"])
        source = payload.get("source")
        evidence = (
            [ObjectEvidence(reference=source["evidence"], source=source)]
            if isinstance(source, dict)
            else [ObjectEvidence(reference=payload["evidence"])]
            if isinstance(payload.get("evidence"), str)
            else []
        )
        events.append(
            ObjectHistory(
                event_id=row["id"],
                actor_id=row["actor_id"],
                action=row["action"],
                occurred_at=row["occurred_at"],
                recorded_at=row["recorded_at"],
                evidence=evidence,
            )
        )
    return events


def _order_history(tx, project_id, order_id):
    rows = tx.execute(
        "SELECT * FROM audit_events WHERE project_id=? AND "
        "(object_id=? OR object_id IN "
        "(SELECT id FROM commitment_changes WHERE project_id=? AND order_line_id=?)) "
        "ORDER BY id",
        (str(project_id), str(order_id), str(project_id), str(order_id)),
    ).fetchall()
    return _history_rows(rows)


def _summary(row, kind, project_row):
    source = json.loads(row["source_json"])
    if kind == ObjectKind.demand:
        title, state, q = row["product"], row["demand_kind"], row["q_atoms"]
    elif kind == ObjectKind.order_line:
        title, state, q = (
            row["source_external_id"],
            row["state"],
            row["current_q_atoms"],
        )
    else:
        title, state, q = row["reason"], row["state"], row["new_q_atoms"]
    return ObjectSummary(
        id=row["id"],
        kind=kind,
        project_id=row["project_id"],
        title=title,
        state=state,
        quantity=amount(q, project_row),
        unit=row["unit"],
        source=source,
        version=row["source_version"],
        blocking_reasons=["change disposition pending"] if state == "pending" else [],
        next_actions=["order.resolve_change"] if state == "pending" else [],
    )


def _count(table):
    def reader(tx, project_id):
        return tx.execute(
            f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (str(project_id),)
        ).fetchone()[0]

    return reader


def _summaries(table, kind):
    def reader(tx, project_id, limit, offset):
        p = project(tx, project_id)
        rows = tx.execute(
            f"SELECT * FROM {table} WHERE project_id=? ORDER BY created_at,id LIMIT ? OFFSET ?",
            (str(project_id), limit, offset),
        ).fetchall()
        return [_summary(r, kind, p) for r in rows]

    return reader


def demand_detail(tx, project_id, object_id):
    row = tx.execute(
        "SELECT * FROM demands WHERE id=? AND project_id=?",
        (str(object_id), str(project_id)),
    ).fetchone()
    if row is None:
        return None
    p = project(tx, project_id)
    source = json.loads(row["source_json"])
    relations = (
        [
            ObjectRelation(
                relation="supersedes",
                project_id=project_id,
                kind=ObjectKind.demand,
                id=row["supersedes_demand_id"],
            )
        ]
        if row["supersedes_demand_id"]
        else []
    )
    return ObjectDetail[DemandValue](
        summary=_summary(row, ObjectKind.demand, p),
        value=DemandValue(
            demand_kind=row["demand_kind"],
            product=row["product"],
            quantity=amount(row["q_atoms"], p),
            unit=row["unit"],
            due_date=row["due_date"],
            source=source,
            supersedes_demand_id=row["supersedes_demand_id"],
            reviews=latest_reviews(tx, project_id, object_id),
        ),
        relations=relations,
        evidence=[ObjectEvidence(reference=source["evidence"], source=source)],
        history=_history(tx, project_id, object_id),
    )


def work_order_impact(tx, project_id, order_id, project_row):
    # Aggregate before limiting references; never infer totals from a choice page.
    totals = tx.execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(obligation_atoms),0) AS quantity FROM effective_work_orders "
        "WHERE project_id=? AND order_line_id=?",
        (str(project_id), str(order_id)),
    ).fetchone()
    rows = tx.execute(
        "SELECT id,source_system,source_external_id,obligation_atoms AS q_atoms,unit FROM effective_work_orders "
        "WHERE project_id=? AND order_line_id=? "
        "ORDER BY source_system,source_external_id,id LIMIT 50",
        (str(project_id), str(order_id)),
    ).fetchall()
    return WorkOrderImpactPreview(
        registered_quantity=amount(totals["quantity"], project_row),
        total=totals["total"],
        shown=len(rows),
        has_more=totals["total"] > len(rows),
        items=[
            {
                "id": row["id"],
                "source_system": row["source_system"],
                "external_id": row["source_external_id"],
                "quantity": amount(row["q_atoms"], project_row),
                "unit": row["unit"],
            }
            for row in rows
        ],
    )


def order_detail(tx, project_id, object_id):
    from .quality import final_good_count

    row = tx.execute(
        "SELECT * FROM order_lines WHERE id=? AND project_id=?",
        (str(object_id), str(project_id)),
    ).fetchone()
    if row is None:
        return None
    p = project(tx, project_id)
    source = json.loads(row["source_json"])
    allocation = allocated(tx, project_id, order_id=object_id)
    quantity = row["current_q_atoms"]
    shipped = shipped_atoms(tx, project_id, object_id, p)
    links = tx.execute(
        "SELECT DISTINCT work_order_id FROM effective_allocations WHERE project_id=? AND order_line_id=? ORDER BY work_order_id",
        (str(project_id), str(object_id)),
    ).fetchall()
    relations = [
        ObjectRelation(
            relation="formal_demand",
            project_id=project_id,
            kind=ObjectKind.demand,
            id=row["demand_id"],
        )
    ]
    relations += [
        ObjectRelation(
            relation="allocated_work_order",
            project_id=project_id,
            kind=ObjectKind.work_order,
            id=r[0],
        )
        for r in links
    ]
    from .delivery import remaining, fulfillment_status

    delivery_balance = remaining(tx, project_id, object_id)
    return ObjectDetail[OrderLineValue](
        summary=_summary(row, ObjectKind.order_line, p),
        value=OrderLineValue(
            fulfillment_status=fulfillment_status(tx, project_id),
            work_order_impact=work_order_impact(tx, project_id, object_id, p),
            demand_id=row["demand_id"],
            original_quantity=amount(row["original_q_atoms"], p),
            current_quantity=amount(quantity, p),
            unit=row["unit"],
            original_due=row["original_due"],
            current_due=row["current_due"],
            source=source,
            state=row["state"],
            allocated=amount(allocation, p),
            produced_good=amount(
                final_good_count(tx, project_id, object_id) * (10 ** p["unit_scale"]), p
            ),
            shipped=amount(shipped, p),
            signed=str(delivery_balance.signed),
            accepted=str(delivery_balance.accepted),
            remaining_to_ship=amount(max(0, quantity - shipped), p),
            remaining_to_accept=str(delivery_balance.remaining_to_accept),
        ),
        relations=relations,
        evidence=[ObjectEvidence(reference=source["evidence"], source=source)],
        history=_order_history(tx, project_id, object_id),
    )


def change_detail(tx, project_id, object_id):
    row = tx.execute(
        "SELECT * FROM commitment_changes WHERE id=? AND project_id=?",
        (str(object_id), str(project_id)),
    ).fetchone()
    if row is None:
        return None
    p = project(tx, project_id)
    source = json.loads(row["source_json"])
    impacts = [
        {
            "object_type": r["object_type"],
            "object_id": r["object_id"],
            "quantity": amount(r["q_atoms"], p),
            "unit": r["unit"],
            "decision": r["decision"],
            "evidence": r["evidence"],
        }
        for r in tx.execute(
            "SELECT * FROM change_impacts WHERE change_id=? AND project_id=? ORDER BY object_type,object_id",
            (str(object_id), str(project_id)),
        )
    ]
    return ObjectDetail[CommitmentChangeValue](
        summary=_summary(row, ObjectKind.commitment_change, p),
        value=CommitmentChangeValue(
            order_line_id=row["order_line_id"],
            old_quantity=amount(row["old_q_atoms"], p),
            new_quantity=amount(row["new_q_atoms"], p),
            unit=row["unit"],
            old_due=row["old_due"],
            new_due=row["new_due"],
            cancel=bool(row["cancel"]),
            reason=row["reason"],
            source=source,
            state=row["state"],
            impacts=impacts,
        ),
        relations=[
            ObjectRelation(
                relation="changes_order",
                project_id=project_id,
                kind=ObjectKind.order_line,
                id=row["order_line_id"],
            )
        ],
        evidence=[ObjectEvidence(reference=source["evidence"], source=source)],
        history=_history(tx, project_id, object_id),
    )


def project_summary(tx, project_row):
    from .contracts import ProjectQuantitySummary
    from .quality import final_good_count

    pid = project_row["id"]
    totals = tx.execute(
        "SELECT COALESCE(SUM(original_q_atoms),0),COALESCE(SUM(current_q_atoms),0) FROM order_lines WHERE project_id=?",
        (pid,),
    ).fetchone()
    allocation = allocated(tx, pid)
    original, current = totals
    shipped = project_shipped_atoms(tx, project_row)
    from .delivery import totals as delivery_totals

    facts = delivery_totals(tx, pid)
    return ProjectQuantitySummary(
        original_order_quantity=amount(original, project_row),
        current_order_quantity=amount(current, project_row),
        allocated=amount(allocation, project_row),
        produced_good=amount(
            final_good_count(tx, pid) * (10 ** project_row["unit_scale"]), project_row
        ),
        shipped=amount(shipped, project_row),
        signed=amount(facts.get("sign", 0), project_row),
        accepted=amount(facts.get("accept", 0), project_row),
        remaining_to_ship=amount(max(0, current - shipped), project_row),
        remaining_to_accept=amount(
            max(0, current - facts.get("accept", 0)), project_row
        ),
    )


def register():
    for model, roles, handler in (
        (RecordDemand, {"project_owner"}, dispatch_record_demand),
        (ReviewDemand, {"project_owner"}, dispatch_review_demand),
        (RegisterOrder, {"project_owner"}, dispatch_register_order),
        (ChangeOrder, {"project_owner"}, dispatch_change_order),
        (ResolveOrderChange, {"project_owner"}, dispatch_resolve_change),
        (AllocateOrder, {"planner"}, dispatch_allocate_order),
    ):
        COMMAND_REGISTRY.register(
            model, roles=roles, qualifications=set(), handler=handler
        )
    for kind, model, table, detail in (
        (ObjectKind.demand, DemandValue, "demands", demand_detail),
        (ObjectKind.order_line, OrderLineValue, "order_lines", order_detail),
        (
            ObjectKind.commitment_change,
            CommitmentChangeValue,
            "commitment_changes",
            change_detail,
        ),
    ):
        OBJECT_REGISTRY.register(
            kind,
            model,
            count=_count(table),
            summaries=_summaries(table, kind),
            detail=detail,
        )


register()
