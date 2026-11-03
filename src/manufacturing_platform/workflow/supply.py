"""Versioned plan evidence, manual receipt/IQC facts and authority-only reservations."""

from .clock import business_time

import json
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from .commands import COMMAND_REGISTRY
from .contracts import (
    DomainError,
    MaterialBalance,
    MutationResult,
    ObjectDetail,
    ObjectEvidence,
    ObjectKind,
    ObjectRelation,
    ObjectSummary,
)
from .orders import _history_rows, own, source_key
from .queries import OBJECT_REGISTRY
from .supply_models import (
    CommitmentValue,
    CommitSupply,
    DefineMaterial,
    InspectSupply,
    MaterialLotValue,
    PlanValue,
    ReceiptValue,
    ReceivePlan,
    ReceiveSupply,
    RequirementValue,
)

MAX_CUTOFF_AGE = timedelta(hours=24)
MAX_CLOCK_SKEW = timedelta(minutes=5)


def fail(message, code="PRECONDITION_FAILED"):
    raise DomainError(code, 409, message, blocking_reasons=[message])


def amount(atoms, scale):
    value = format(Decimal(atoms).scaleb(-scale), "f")
    return value.rstrip("0").rstrip(".") if "." in value else value


def atoms(value, unit, expected_unit, scale):
    if unit != expected_unit:
        fail("material unit mismatch")
    result = value * (10**scale)
    if result != result.to_integral_value() or result > 2**63 - 1:
        fail("material quantity exceeds precision or range")
    return int(result)


def source_ok(
    source,
    expected_type,
    now,
    *,
    retain_bad_time=False,
    source_modes=frozenset({"manual"}),
):
    if source_key(source)[1] != expected_type or source.mode not in source_modes:
        fail("manual source type or mode mismatch")
    if source.collected_at < source.occurred_at:
        fail("source collected before occurrence")
    if not retain_bad_time and (
        source.occurred_at > now + MAX_CLOCK_SKEW
        or source.collected_at > now + MAX_CLOCK_SKEW
    ):
        fail("future source timestamp")


def source_free(tx, table, source, *, versioned=False):
    key = source_key(source)
    row = tx.execute(
        f"SELECT MAX(source_version) FROM {table} WHERE source_system=? AND source_type=? AND source_external_id=?",
        key,
    ).fetchone()
    if row[0] is not None and (not versioned or source.version <= row[0]):
        fail("source identity or version already recorded", "SOURCE_CONFLICT")


def cutoff_issue(source, now):
    if source.occurred_at > now or source.collected_at > now:
        return "plan source timestamp in future"
    if source.cutoff is None:
        return "plan source cutoff missing"
    if source.cutoff > source.collected_at or source.cutoff > now:
        return "plan source cutoff in future"
    if now - source.cutoff > MAX_CUTOFF_AGE:
        return "plan source cutoff expired"
    return None


def current_plan_id(tx, project_id, work_order_id):
    row = tx.execute(
        """SELECT p.id FROM plans p JOIN requirements r ON r.plan_id=p.id
           WHERE p.project_id=? AND r.work_order_id=? AND p.state='confirmed'
           ORDER BY p.accepted_seq DESC LIMIT 1""",
        (str(project_id), str(work_order_id)),
    ).fetchone()
    return row["id"] if row else None


def define_material(tx, context, command: DefineMaterial):
    source_ok(command.source, "material_lot", context.now)
    source_free(tx, "material_lots", command.source)
    if command.expiry < context.now.date():
        fail("material lot expired")
    prior = tx.execute(
        "SELECT unit,scale,owner_id FROM material_lots WHERE project_id=? AND material_id=? LIMIT 1",
        (str(context.project_id), command.material_id),
    ).fetchone()
    if prior and (prior["unit"], prior["scale"], prior["owner_id"]) != (
        command.unit,
        command.scale,
        command.owner_id,
    ):
        fail("material definition conflicts with existing unit, scale or owner")
    ident = str(uuid4())
    key = source_key(command.source)
    tx.execute(
        "INSERT INTO material_lots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ident,
            str(context.project_id),
            command.material_id,
            command.lot_id,
            command.owner_id,
            command.unit,
            command.scale,
            command.expiry.isoformat(),
            "active",
            *key,
            command.source.version,
            command.source.model_dump_json(),
            context.now.isoformat(),
        ),
    )
    return MutationResult(object_type=ObjectKind.material_lot, object_id=UUID(ident))


def receive_plan(tx, context, command: ReceivePlan):
    source_ok(command.source, "plan", context.now, retain_bad_time=True)
    return _receive_plan(tx, context, command)


def validate_plan(tx, context, command):
    source_free(tx, "plans", command.source, versioned=True)
    reasons = []
    issue = cutoff_issue(command.source, context.now)
    if issue:
        reasons.append(issue)
    revisions = {str(v) for v in command.input_revision_ids}
    versions = {str(v.order_line_id): v.version for v in command.input_order_versions}
    if len(revisions) != len(command.input_revision_ids) or len(versions) != len(
        command.input_order_versions
    ):
        fail("duplicate plan inputs")
    material_meta = {}
    for req in command.requirements:
        wo = own(tx, "work_orders", context.project_id, req.work_order_id)
        if wo["revision_id"] not in revisions:
            reasons.append("work order fixed revision missing from plan inputs")
        if wo["order_line_id"] not in versions:
            reasons.append("work order order version missing from plan inputs")
        order = own(tx, "order_lines", context.project_id, wo["order_line_id"])
        if (
            order["state"] != "active"
            or versions.get(order["id"]) != order["source_version"]
        ):
            reasons.append("order source version mismatch")
        rev = own(tx, "engineering_revisions", context.project_id, wo["revision_id"])
        if rev["id"] not in revisions:
            reasons.append("fixed engineering version mismatch")
        material = tx.execute(
            "SELECT unit,scale,owner_id FROM material_lots WHERE project_id=? AND material_id=? LIMIT 1",
            (str(context.project_id), req.material_id),
        ).fetchone()
        if not material:
            fail("material definition absent")
        if material["owner_id"] != req.owner_id:
            fail("material owner mismatch")
        q = atoms(req.quantity, req.unit, material["unit"], material["scale"])
        material_meta[id(req)] = (q, material["scale"])
    for revision_id in revisions:
        if (
            tx.execute(
                "SELECT 1 FROM engineering_revisions WHERE project_id=? AND id=?",
                (str(context.project_id), revision_id),
            ).fetchone()
            is None
        ):
            reasons.append("declared revision input missing or inaccessible")
    for order_id, version in versions.items():
        order = tx.execute(
            "SELECT source_version FROM order_lines WHERE project_id=? AND id=?",
            (str(context.project_id), order_id),
        ).fetchone()
        if order is None:
            reasons.append("declared order input missing or inaccessible")
        elif order["source_version"] != version:
            reasons.append("order source version mismatch")
    return reasons, material_meta


def _receive_plan(tx, context, command, *, object_id=None, requirement_ids=None):
    reasons, material_meta = validate_plan(tx, context, command)
    ident = str(object_id or uuid4())
    state = "rejected" if reasons else "confirmed"
    reason = "; ".join(dict.fromkeys(reasons))
    key = source_key(command.source)
    tx.execute(
        "INSERT INTO plans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ident,
            str(context.project_id),
            state,
            reason,
            command.source.model_dump_json(),
            *key,
            command.source.version,
            command.source.cutoff.isoformat() if command.source.cutoff else None,
            json.dumps(
                {
                    "input_revision_ids": [str(v) for v in command.input_revision_ids],
                    "input_order_versions": [
                        v.model_dump(mode="json") for v in command.input_order_versions
                    ],
                }
            ),
            context.now.isoformat(),
            tx.execute(
                "SELECT COALESCE(MAX(accepted_seq),0)+1 FROM plans WHERE project_id=?",
                (str(context.project_id),),
            ).fetchone()[0],
        ),
    )
    if state == "confirmed":
        for index, req in enumerate(command.requirements):
            q, scale = material_meta[id(req)]
            previous = tx.execute(
                """SELECT r.id,r.lineage_id FROM requirements r JOIN plans p ON p.id=r.plan_id
                   WHERE r.project_id=? AND r.work_order_id=? AND r.execution_scope=?
                     AND r.material_id=? AND r.owner_id=? AND r.unit=? AND p.state='confirmed'
                   ORDER BY p.accepted_seq DESC,r.id DESC LIMIT 1""",
                (
                    str(context.project_id),
                    str(req.work_order_id),
                    req.execution_scope,
                    req.material_id,
                    req.owner_id,
                    req.unit,
                ),
            ).fetchone()
            lineage_id = previous["lineage_id"] if previous else str(uuid4())
            tx.execute(
                "INSERT INTO requirements VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(
                        requirement_ids[index]
                        if requirement_ids is not None
                        else uuid4()
                    ),
                    str(context.project_id),
                    ident,
                    str(req.work_order_id),
                    req.execution_scope,
                    req.material_id,
                    req.owner_id,
                    q,
                    req.unit,
                    scale,
                    lineage_id,
                    previous["id"] if previous else None,
                    context.now.isoformat(),
                ),
            )
    return MutationResult(object_type=ObjectKind.plan, object_id=UUID(ident))


def commit_supply(tx, context, command: CommitSupply):
    req = own(tx, "requirements", context.project_id, command.requirement_id)
    if command.commitment_id is None and req["plan_id"] != current_plan_id(
        tx, context.project_id, req["work_order_id"]
    ):
        fail("new supply commitment requires current confirmed plan requirement")
    if req["owner_id"] != command.owner_id:
        fail("supply owner mismatch")
    q = atoms(command.quantity, command.unit, req["unit"], req["scale"])
    source_ok(command.source, "commitment", context.now)
    if command.commitment_id is None:
        source_free(tx, "supply_promise_revisions", command.source)
        ident = str(uuid4())
        tx.execute(
            "INSERT INTO supply_commitments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ident,
                str(context.project_id),
                req["id"],
                command.type,
                command.owner_id,
                q,
                q,
                command.unit,
                command.original_due.isoformat(),
                command.current_due.isoformat(),
                command.source.model_dump_json(),
                command.source.version,
                context.now.isoformat(),
            ),
        )
    else:
        prior = own(tx, "supply_commitments", context.project_id, command.commitment_id)
        if (
            prior["requirement_id"],
            prior["type"],
            prior["owner_id"],
            prior["unit"],
        ) != (req["id"], command.type, command.owner_id, command.unit):
            fail("promise amendment changes immutable identity")
        if command.original_due.isoformat() != prior["original_due"]:
            fail("original supplier promise is immutable")
        if command.source.version <= prior["source_version"]:
            fail("promise source version must increase")
        original_source = json.loads(
            tx.execute(
                "SELECT source_json FROM supply_promise_revisions WHERE project_id=? AND commitment_id=? ORDER BY created_at,id LIMIT 1",
                (str(context.project_id), prior["id"]),
            ).fetchone()[0]
        )
        if source_key(command.source) != source_key(original_source):
            fail("promise amendment must retain source identity")
        source_free(tx, "supply_promise_revisions", command.source, versioned=True)
        ident = prior["id"]
        tx.execute(
            "UPDATE supply_commitments SET current_q_atoms=?,current_due=?,source_json=?,source_version=? WHERE id=?",
            (
                q,
                command.current_due.isoformat(),
                command.source.model_dump_json(),
                command.source.version,
                ident,
            ),
        )
    key = source_key(command.source)
    tx.execute(
        "INSERT INTO supply_promise_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            str(uuid4()),
            str(context.project_id),
            ident,
            q,
            command.current_due.isoformat(),
            command.source.model_dump_json(),
            *key,
            command.source.version,
            context.now.isoformat(),
        ),
    )
    return MutationResult(object_type=ObjectKind.commitment, object_id=UUID(ident))


def receive_supply(
    tx, context, command: ReceiveSupply, *, source_modes=frozenset({"manual"})
):
    commitment = own(
        tx, "supply_commitments", context.project_id, command.commitment_id
    )
    requirement = own(
        tx, "requirements", context.project_id, commitment["requirement_id"]
    )
    lot = own(tx, "material_lots", context.project_id, command.material_lot_id)
    if (lot["material_id"], lot["owner_id"], lot["unit"]) != (
        requirement["material_id"],
        requirement["owner_id"],
        requirement["unit"],
    ):
        fail("receipt material, owner or unit mismatch")
    if lot["state"] != "active" or lot["expiry"] < context.now.date().isoformat():
        fail("material lot frozen or expired")
    q = atoms(command.quantity, command.unit, lot["unit"], lot["scale"])
    source_ok(command.source, "receipt", context.now, source_modes=source_modes)
    source_free(tx, "supply_receipts", command.source)
    ident = str(uuid4())
    key = source_key(command.source)
    tx.execute(
        "INSERT INTO supply_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ident,
            str(context.project_id),
            commitment["id"],
            lot["id"],
            q,
            command.unit,
            command.source.model_dump_json(),
            *key,
            command.source.version,
            context.now.isoformat(),
        ),
    )
    return MutationResult(object_type=ObjectKind.receipt, object_id=UUID(ident))


def validate_inspection_conservation(
    tx, project_id, receipt_id, *, replacement=None, target_id=None, received_atoms=None
):
    """One invariant for inspection append/replacement and receipt quantity correction."""
    receipt = own(tx, "effective_supply_receipts", project_id, receipt_id)
    if target_id is not None:
        target = own(tx, "effective_iqc_results", project_id, target_id)
        if target["receipt_id"] != receipt["id"] or replacement is None:
            fail("Inspection target does not match receipt")
    total = tx.execute(
        """SELECT COALESCE(SUM(accepted_atoms+rejected_atoms),0) checked,
            COALESCE(MIN(accepted_atoms),0) min_accepted,COALESCE(MIN(rejected_atoms),0) min_rejected
            FROM effective_iqc_results WHERE project_id=? AND receipt_id=? AND (? IS NULL OR id<>?)""",
        (
            str(project_id),
            receipt["id"],
            str(target_id) if target_id else None,
            str(target_id) if target_id else None,
        ),
    ).fetchone()
    accepted, rejected = replacement if replacement is not None else (0, 0)
    received = receipt["q_atoms"] if received_atoms is None else received_atoms
    if (
        min(total["min_accepted"], total["min_rejected"], accepted, rejected, received)
        < 0
    ):
        fail("Receipt and inspection quantities must remain nonnegative")
    if replacement is not None and accepted + rejected == 0:
        fail("IQC result has no quantity")
    if total["checked"] + accepted + rejected > received:
        fail("IQC quantity exceeds effective receipt")


def inspect_supply(tx, context, command: InspectSupply):
    receipt = own(
        tx, "effective_supply_receipts", context.project_id, command.receipt_id
    )
    lot = own(tx, "material_lots", context.project_id, receipt["material_lot_id"])
    accepted = atoms(command.accepted, lot["unit"], lot["unit"], lot["scale"])
    rejected = atoms(command.rejected, lot["unit"], lot["unit"], lot["scale"])
    validate_inspection_conservation(
        tx, context.project_id, receipt["id"], replacement=(accepted, rejected)
    )
    tx.execute(
        "INSERT INTO iqc_results VALUES (?,?,?,?,?,?,?,?)",
        (
            str(uuid4()),
            str(context.project_id),
            receipt["id"],
            accepted,
            rejected,
            command.evidence,
            str(context.actor.user_id),
            context.now.isoformat(),
        ),
    )
    return MutationResult(object_type=ObjectKind.receipt, object_id=UUID(receipt["id"]))


def available(tx, project_id, requirement_id, now) -> MaterialBalance:
    req = own(tx, "requirements", project_id, requirement_id)
    plan = own(tx, "plans", project_id, req["plan_id"])
    totals = tx.execute(
        """SELECT COALESCE(SUM(MAX(0,c.current_q_atoms-(SELECT COALESCE(SUM(r.q_atoms),0)
                      FROM effective_supply_receipts r WHERE r.project_id=c.project_id AND r.commitment_id=c.id))),0) in_transit,
                  COALESCE(SUM((SELECT COALESCE(SUM(r.q_atoms),0) FROM effective_supply_receipts r WHERE r.project_id=c.project_id AND r.commitment_id=c.id)),0) received
           FROM supply_commitments c JOIN requirements prior ON prior.id=c.requirement_id
           WHERE c.project_id=? AND prior.project_id=c.project_id AND prior.lineage_id=?""",
        (str(project_id), req["lineage_id"]),
    ).fetchone()
    qualified = tx.execute(
        """SELECT COALESCE(SUM(i.accepted_atoms),0),COALESCE(SUM(i.rejected_atoms),0)
           FROM supply_commitments c JOIN requirements prior ON prior.id=c.requirement_id AND prior.project_id=c.project_id
           JOIN effective_supply_receipts r ON r.commitment_id=c.id AND r.project_id=c.project_id
           JOIN effective_iqc_results i ON i.receipt_id=r.id AND i.project_id=r.project_id
           WHERE c.project_id=? AND prior.lineage_id=?""",
        (str(project_id), req["lineage_id"]),
    ).fetchone()
    reserved = tx.execute(
        """SELECT COALESCE(SUM(v.confirmed_atoms),0) FROM effective_reservations v
           JOIN requirements prior ON prior.id=v.requirement_id AND prior.project_id=v.project_id
           WHERE v.project_id=? AND prior.lineage_id=? AND v.work_order_id=?
             AND v.authority_receipt_id IS NOT NULL""",
        (str(project_id), req["lineage_id"], req["work_order_id"]),
    ).fetchone()[0]
    from .ownership import material_hold

    usable, movement_holds = 0, []
    for row in tx.execute(
        "SELECT l.*,SUM(v.confirmed_atoms) confirmed FROM effective_reservations v JOIN requirements prior ON prior.id=v.requirement_id AND prior.project_id=v.project_id JOIN material_lots l ON l.id=v.material_lot_id AND l.project_id=v.project_id WHERE v.project_id=? AND prior.lineage_id=? AND v.work_order_id=? AND v.authority_receipt_id IS NOT NULL GROUP BY l.id",
        (str(project_id), req["lineage_id"], req["work_order_id"]),
    ):
        hold = material_hold(tx, project_id, row)
        if hold:
            movement_holds.append(hold)
        else:
            usable += row["confirmed"]
    scale = req["scale"]
    return MaterialBalance(
        blocking_reasons=movement_holds if usable < req["q_atoms"] else [],
        required=amount(req["q_atoms"], scale),
        in_transit=amount(totals["in_transit"], scale),
        received=amount(totals["received"], scale),
        qualified=amount(qualified[0], scale),
        rejected=amount(qualified[1], scale),
        reserved=amount(reserved, scale),
        shortage=amount(max(0, req["q_atoms"] - usable), scale),
        unit=req["unit"],
        cutoff=plan["cutoff"],
        source_version=plan["source_version"],
    )


def _totals(tx, where, args):
    row = tx.execute(
        f"""SELECT COALESCE(SUM(r.q_atoms),0) received,
                   COALESCE(SUM((SELECT COALESCE(SUM(i.accepted_atoms),0) FROM effective_iqc_results i WHERE i.receipt_id=r.id)),0) qualified,
                   COALESCE(SUM((SELECT COALESCE(SUM(i.rejected_atoms),0) FROM effective_iqc_results i WHERE i.receipt_id=r.id)),0) rejected
            FROM effective_supply_receipts r WHERE {where}""",
        args,
    ).fetchone()
    return row["received"], row["qualified"], row["rejected"]


def receipt_presentation(received, accepted, rejected):
    pending = received - accepted - rejected
    if pending:
        state = "partially_inspected" if accepted or rejected else "pending_inspection"
    else:
        state = "mixed" if accepted and rejected else "rejected" if rejected else "accepted"
    next_step = (
        "inspect_remaining" if pending
        else "review_rejected" if rejected
        else "await_authority_reservation"
    )
    return dict(quantity_state=state, next_step=next_step)


def _summary(
    kind,
    row,
    title,
    state,
    quantity=None,
    unit=None,
    source=None,
    reasons=(),
    material_balance=None,
):
    return ObjectSummary(
        id=row["id"],
        kind=kind,
        project_id=row["project_id"],
        title=title,
        state=state,
        quantity=quantity,
        unit=unit,
        source=json.loads(source) if source else None,
        version=1 if kind == ObjectKind.requirement else row["source_version"],
        blocking_reasons=list(reasons),
        material_balance=material_balance,
        next_actions=(
            ["supply.inspect"]
            if kind == ObjectKind.receipt and state in {"pending_inspection", "partially_inspected"}
            else []
        ),
    )


def _history(tx, project_id, object_id):
    from .ownership import audit_evidence

    return _history_rows(
        tx.execute(
            "SELECT * FROM audit_events WHERE project_id=? AND object_id=? ORDER BY id",
            (str(project_id), str(object_id)),
        ).fetchall(),
        evidence_projector=lambda row, payload: audit_evidence(
            tx, project_id, object_id, row, payload
        ),
    )


def _detail(tx, project_id, kind, object_id):
    table = {
        "plan": "plans",
        "requirement": "requirements",
        "commitment": "supply_commitments",
        "material_lot": "material_lots",
        "receipt": "effective_supply_receipts",
    }[kind]
    row = tx.execute(
        f"SELECT * FROM {table} WHERE project_id=? AND id=?",
        (str(project_id), str(object_id)),
    ).fetchone()
    if not row:
        return None
    relations = []
    evidence = []
    if kind == "plan":
        inputs = json.loads(row["inputs_json"])
        req_ids = [
            r["id"]
            for r in tx.execute(
                "SELECT id FROM requirements WHERE project_id=? AND plan_id=? ORDER BY created_at,id LIMIT 500",
                (str(project_id), row["id"]),
            )
        ]
        value = PlanValue(
            state=row["state"],
            reason=row["reason"],
            source=json.loads(row["source_json"]),
            requirement_ids=req_ids,
            cutoff=row["cutoff"],
            **inputs,
        )
        summary = _summary(
            ObjectKind.plan,
            row,
            row["source_external_id"],
            row["state"],
            source=row["source_json"],
            reasons=[row["reason"]] if row["reason"] else [],
        )
        evidence = [
            ObjectEvidence(reference=value.source.evidence, source=value.source)
        ]
    elif kind == "requirement":
        bal = available(tx, project_id, object_id, business_time(tx))
        value = RequirementValue(
            plan_id=row["plan_id"],
            lineage_id=row["lineage_id"],
            supersedes_requirement_id=row["supersedes_requirement_id"],
            work_order_id=row["work_order_id"],
            execution_scope=row["execution_scope"],
            material_id=row["material_id"],
            owner_id=row["owner_id"],
            quantity=amount(row["q_atoms"], row["scale"]),
            unit=row["unit"],
            balance=bal,
            unqualified_quantity=amount(
                max(
                    0,
                    int(Decimal(bal.received) * 10 ** row["scale"])
                    - int(Decimal(bal.qualified) * 10 ** row["scale"]),
                ),
                row["scale"],
            ),
        )
        summary = _summary(
            ObjectKind.requirement,
            row,
            row["material_id"],
            "required"
            if row["plan_id"] == current_plan_id(tx, project_id, row["work_order_id"])
            else "superseded",
            amount(row["q_atoms"], row["scale"]),
            row["unit"],
            material_balance=bal,
        )
        relations = [
            ObjectRelation(
                relation="planned_by",
                project_id=project_id,
                kind=ObjectKind.plan,
                id=row["plan_id"],
            ),
            ObjectRelation(
                relation="for_work_order",
                project_id=project_id,
                kind=ObjectKind.work_order,
                id=row["work_order_id"],
            ),
        ]
    elif kind == "commitment":
        req = own(tx, "requirements", project_id, row["requirement_id"])
        revisions = [
            {
                "source": json.loads(r["source_json"]),
                "quantity": amount(r["q_atoms"], req["scale"]),
                "current_due": r["current_due"],
            }
            for r in tx.execute(
                "SELECT * FROM supply_promise_revisions WHERE project_id=? AND commitment_id=? ORDER BY created_at,id",
                (str(project_id), row["id"]),
            )
        ]
        lot_ids = [
            r["material_lot_id"]
            for r in tx.execute(
                "SELECT DISTINCT material_lot_id FROM effective_supply_receipts WHERE project_id=? AND commitment_id=? ORDER BY material_lot_id LIMIT 200",
                (str(project_id), row["id"]),
            )
        ]
        totals = _totals(
            tx, "r.project_id=? AND r.commitment_id=?", (str(project_id), row["id"])
        )
        value = CommitmentValue(
            requirement_id=row["requirement_id"],
            type=row["type"],
            owner_id=row["owner_id"],
            original_quantity=amount(row["original_q_atoms"], req["scale"]),
            current_quantity=amount(row["current_q_atoms"], req["scale"]),
            unit=row["unit"],
            original_due=row["original_due"],
            current_due=row["current_due"],
            source=json.loads(row["source_json"]),
            promise_revisions=revisions,
            material_lot_ids=lot_ids,
            received=amount(totals[0], req["scale"]),
            qualified=amount(totals[1], req["scale"]),
            rejected=amount(totals[2], req["scale"]),
        )
        summary = _summary(
            ObjectKind.commitment,
            row,
            row["type"],
            "promised",
            amount(row["current_q_atoms"], req["scale"]),
            row["unit"],
            row["source_json"],
        )
        relations = [
            ObjectRelation(
                relation="for_requirement",
                project_id=project_id,
                kind=ObjectKind.requirement,
                id=row["requirement_id"],
            )
        ]
        evidence = [
            ObjectEvidence(reference=v.source.evidence, source=v.source)
            for v in value.promise_revisions
        ]
    elif kind == "material_lot":
        totals = _totals(
            tx, "r.project_id=? AND r.material_lot_id=?", (str(project_id), row["id"])
        )
        from .ownership import balance, material_hold, history as ownership_history

        movements, reconciliations = ownership_history(tx, project_id, row)
        ownership = balance(tx, project_id, row)
        ownership.hold_reason = material_hold(tx, project_id, row)
        from .freeze import projection

        value = MaterialLotValue(
            **projection(tx, project_id, "material_lot", row["id"]).model_dump(),
            ownership_balance=ownership,
            material_movements=movements,
            ownership_reconciliations=reconciliations,
            material_id=row["material_id"],
            lot_id=row["lot_id"],
            owner_id=row["owner_id"],
            unit=row["unit"],
            scale=row["scale"],
            expiry=row["expiry"],
            state=row["state"],
            source=json.loads(row["source_json"]),
            received=amount(totals[0], row["scale"]),
            qualified=amount(totals[1], row["scale"]),
            rejected=amount(totals[2], row["scale"]),
        )
        summary = _summary(
            ObjectKind.material_lot,
            row,
            row["lot_id"],
            row["state"],
            source=row["source_json"],
        )
        evidence = [
            ObjectEvidence(reference=value.source.evidence, source=value.source)
        ]
    else:
        lot = own(tx, "material_lots", project_id, row["material_lot_id"])
        iqc = tx.execute(
            "SELECT COALESCE(SUM(accepted_atoms),0),COALESCE(SUM(rejected_atoms),0) FROM effective_iqc_results WHERE project_id=? AND receipt_id=?",
            (str(project_id), row["id"]),
        ).fetchone()
        confirmations = []
        for confirmation in tx.execute(
            "SELECT * FROM source_confirmations WHERE project_id=? AND object_id=? ORDER BY seq LIMIT 500",
            (str(project_id), row["id"]),
        ):
            source = json.loads(confirmation["source_json"])
            source.pop("iqc_id", None)
            confirmations.append(
                {
                    "source": source,
                    "external_actor": confirmation["external_actor"],
                    "signature": confirmation["signature"],
                    "recorded_by": confirmation["recorded_by"],
                    "sequence": confirmation["seq"],
                }
            )
        original = own(tx, "supply_receipts", project_id, row["id"])
        corrections = [
            {
                "sequence": c["seq"],
                "received_delta": amount(c["received_delta"], lot["scale"]),
                "accepted_delta": amount(c["accepted_delta"], lot["scale"]),
                "rejected_delta": amount(c["rejected_delta"], lot["scale"]),
                "evidence": c["evidence"],
            }
            for c in tx.execute(
                "SELECT * FROM source_corrections WHERE project_id=? AND receipt_id=? ORDER BY seq LIMIT 500",
                (str(project_id), row["id"]),
            )
        ]
        presentation = receipt_presentation(row["q_atoms"], iqc[0], iqc[1])
        value = ReceiptValue(
            **presentation,
            original_quantity=amount(original["q_atoms"], lot["scale"]),
            corrections=corrections,
            confirmations=confirmations,
            commitment_id=row["commitment_id"],
            material_lot_id=row["material_lot_id"],
            quantity=amount(row["q_atoms"], lot["scale"]),
            unit=row["unit"],
            source=json.loads(row["source_json"]),
            accepted=amount(iqc[0], lot["scale"]),
            rejected=amount(iqc[1], lot["scale"]),
            uninspected=amount(row["q_atoms"] - iqc[0] - iqc[1], lot["scale"]),
        )
        summary = _summary(
            ObjectKind.receipt,
            row,
            row["source_external_id"],
            value.quantity_state,
            amount(row["q_atoms"], lot["scale"]),
            row["unit"],
            row["source_json"],
        )
        relations = [
            ObjectRelation(
                relation="against_commitment",
                project_id=project_id,
                kind=ObjectKind.commitment,
                id=row["commitment_id"],
            ),
            ObjectRelation(
                relation="material_lot",
                project_id=project_id,
                kind=ObjectKind.material_lot,
                id=row["material_lot_id"],
            ),
        ]
        evidence = [
            ObjectEvidence(reference=value.source.evidence, source=value.source)
        ]
        evidence += [
            ObjectEvidence(reference=r["evidence"])
            for r in tx.execute(
                "SELECT evidence FROM effective_iqc_results WHERE project_id=? AND receipt_id=? ORDER BY created_at,id",
                (str(project_id), row["id"]),
            )
        ]
    model = {
        "plan": PlanValue,
        "requirement": RequirementValue,
        "commitment": CommitmentValue,
        "material_lot": MaterialLotValue,
        "receipt": ReceiptValue,
    }[kind]
    return ObjectDetail[model](
        summary=summary,
        value=value,
        relations=relations,
        evidence=evidence,
        history=_history(tx, project_id, object_id),
    )


def _page_balances(tx, project_id, rows):
    if not rows:
        return {}
    lineages = list(dict.fromkeys(r["lineage_id"] for r in rows))
    slots = ",".join("?" for _ in lineages)
    commitments = {
        r["lineage_id"]: r
        for r in tx.execute(
            f"""SELECT prior.lineage_id,COALESCE(SUM(MAX(0,c.current_q_atoms-
                      (SELECT COALESCE(SUM(sr.q_atoms),0) FROM effective_supply_receipts sr
                       WHERE sr.project_id=c.project_id AND sr.commitment_id=c.id))),0) in_transit,
                       COALESCE(SUM((SELECT COALESCE(SUM(sr.q_atoms),0) FROM effective_supply_receipts sr
                           WHERE sr.project_id=c.project_id AND sr.commitment_id=c.id)),0) received
                FROM supply_commitments c JOIN requirements prior
                  ON prior.id=c.requirement_id AND prior.project_id=c.project_id
                WHERE prior.project_id=? AND prior.lineage_id IN ({slots}) GROUP BY prior.lineage_id""",
            (str(project_id), *lineages),
        )
    }
    inspections = {
        r["lineage_id"]: r
        for r in tx.execute(
            f"""SELECT prior.lineage_id,COALESCE(SUM(i.accepted_atoms),0) qualified,
                       COALESCE(SUM(i.rejected_atoms),0) rejected
                FROM effective_iqc_results i JOIN effective_supply_receipts sr ON sr.id=i.receipt_id
                JOIN supply_commitments c ON c.id=sr.commitment_id
                JOIN requirements prior ON prior.id=c.requirement_id AND prior.project_id=c.project_id
                WHERE prior.project_id=? AND prior.lineage_id IN ({slots}) GROUP BY prior.lineage_id""",
            (str(project_id), *lineages),
        )
    }
    reservations = {
        r["lineage_id"]: r["reserved"]
        for r in tx.execute(
            f"""SELECT prior.lineage_id,COALESCE(SUM(v.confirmed_atoms),0) reserved
                FROM effective_reservations v JOIN requirements prior
                  ON prior.id=v.requirement_id AND prior.project_id=v.project_id
                WHERE prior.project_id=? AND prior.lineage_id IN ({slots}) AND v.authority_receipt_id IS NOT NULL
                GROUP BY prior.lineage_id""",
            (str(project_id), *lineages),
        )
    }
    from .ownership import material_hold

    held_atoms, hold_reasons, hold_cache = {}, {}, {}
    for claim in tx.execute(
        f"""SELECT l.*,prior.lineage_id,SUM(v.confirmed_atoms) confirmed FROM effective_reservations v
            JOIN requirements prior ON prior.id=v.requirement_id AND prior.project_id=v.project_id
            JOIN material_lots l ON l.id=v.material_lot_id AND l.project_id=v.project_id
            WHERE v.project_id=? AND prior.lineage_id IN ({slots}) AND v.authority_receipt_id IS NOT NULL
            GROUP BY l.id,prior.lineage_id""",
        (str(project_id), *lineages),
    ):
        if claim["id"] not in hold_cache:
            hold_cache[claim["id"]] = material_hold(tx, project_id, claim)
        reason = hold_cache[claim["id"]]
        if reason:
            lineage = claim["lineage_id"]
            held_atoms[lineage] = held_atoms.get(lineage, 0) + claim["confirmed"]
            hold_reasons.setdefault(lineage, []).append(reason)
    balances = {}
    for row in rows:
        lineage = row["lineage_id"]
        c, i = commitments.get(lineage), inspections.get(lineage)
        in_transit, received = (c["in_transit"], c["received"]) if c else (0, 0)
        qualified, rejected = (i["qualified"], i["rejected"]) if i else (0, 0)
        reserved = reservations.get(lineage, 0)
        scale = row["scale"]
        usable = max(0, reserved - held_atoms.get(lineage, 0))
        balances[row["id"]] = MaterialBalance(
            blocking_reasons=hold_reasons.get(lineage, [])
            if usable < row["q_atoms"]
            else [],
            required=amount(row["q_atoms"], scale),
            in_transit=amount(in_transit, scale),
            received=amount(received, scale),
            qualified=amount(qualified, scale),
            rejected=amount(rejected, scale),
            reserved=amount(reserved, scale),
            shortage=amount(max(0, row["q_atoms"] - usable), scale),
            unit=row["unit"],
            cutoff=row["cutoff"],
            source_version=row["source_version"],
        )
    return balances


def _page(kind, table):
    def count(tx, project_id):
        return tx.execute(
            f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (str(project_id),)
        ).fetchone()[0]

    def page(tx, project_id, limit, offset):
        if kind == "requirement":
            rows = tx.execute(
                """SELECT r.*,p.cutoff,p.source_version,
                   CASE WHEN r.plan_id=(SELECT p2.id FROM plans p2 JOIN requirements r2 ON r2.plan_id=p2.id
                        WHERE p2.project_id=r.project_id AND r2.work_order_id=r.work_order_id
                          AND p2.state='confirmed' ORDER BY p2.accepted_seq DESC LIMIT 1)
                        THEN 'required' ELSE 'superseded' END requirement_state
                   FROM requirements r JOIN plans p ON p.id=r.plan_id
                   WHERE r.project_id=? ORDER BY r.created_at,r.id LIMIT ? OFFSET ?""",
                (str(project_id), limit, offset),
            ).fetchall()
            balances = _page_balances(tx, project_id, rows)
        elif kind == "commitment":
            rows = tx.execute(
                """SELECT c.*,r.scale FROM supply_commitments c JOIN requirements r ON r.id=c.requirement_id
                   WHERE c.project_id=? ORDER BY c.created_at,c.id LIMIT ? OFFSET ?""",
                (str(project_id), limit, offset),
            )
        elif kind == "receipt":
            rows = tx.execute(
                """SELECT sr.*,l.scale FROM effective_supply_receipts sr JOIN material_lots l ON l.id=sr.material_lot_id
                   WHERE sr.project_id=? ORDER BY sr.created_at,sr.id LIMIT ? OFFSET ?""",
                (str(project_id), limit, offset),
            )
        else:
            rows = tx.execute(
                f"SELECT * FROM {table} WHERE project_id=? ORDER BY created_at,id LIMIT ? OFFSET ?",
                (str(project_id), limit, offset),
            )
        result = []
        for row in rows:
            if kind == "plan":
                result.append(
                    _summary(
                        ObjectKind.plan,
                        row,
                        row["source_external_id"],
                        row["state"],
                        source=row["source_json"],
                        reasons=[row["reason"]] if row["reason"] else [],
                    )
                )
            elif kind == "requirement":
                result.append(
                    _summary(
                        ObjectKind.requirement,
                        row,
                        row["material_id"],
                        row["requirement_state"],
                        amount(row["q_atoms"], row["scale"]),
                        row["unit"],
                        material_balance=balances[row["id"]],
                    )
                )
            elif kind == "commitment":
                result.append(
                    _summary(
                        ObjectKind.commitment,
                        row,
                        row["type"],
                        "promised",
                        amount(row["current_q_atoms"], row["scale"]),
                        row["unit"],
                        row["source_json"],
                    )
                )
            elif kind == "material_lot":
                result.append(
                    _summary(
                        ObjectKind.material_lot,
                        row,
                        row["lot_id"],
                        row["state"],
                        source=row["source_json"],
                    )
                )
            else:
                result.append(
                    _summary(
                        ObjectKind.receipt,
                        row,
                        row["source_external_id"],
                        receipt_presentation(
                            row["q_atoms"],
                            *tx.execute(
                                "SELECT COALESCE(SUM(accepted_atoms),0),COALESCE(SUM(rejected_atoms),0) "
                                "FROM effective_iqc_results WHERE project_id=? AND receipt_id=?",
                                (str(project_id), row["id"]),
                            ).fetchone(),
                        )["quantity_state"],
                        amount(row["q_atoms"], row["scale"]),
                        row["unit"],
                        row["source_json"],
                    )
                )
        return result

    return count, page


for model, roles, qualifications, handler in (
    (ReceivePlan, {"planner"}, set(), receive_plan),
    (DefineMaterial, {"supply"}, set(), define_material),
    (CommitSupply, {"supply"}, set(), commit_supply),
    (ReceiveSupply, {"supply"}, set(), receive_supply),
    (InspectSupply, {"quality"}, {"inspection"}, inspect_supply),
):
    COMMAND_REGISTRY.register(
        model, roles=roles, qualifications=qualifications, handler=handler
    )

for kind, table, model in (
    (ObjectKind.plan, "plans", PlanValue),
    (ObjectKind.requirement, "requirements", RequirementValue),
    (ObjectKind.commitment, "supply_commitments", CommitmentValue),
    (ObjectKind.material_lot, "material_lots", MaterialLotValue),
    (ObjectKind.receipt, "supply_receipts", ReceiptValue),
):
    count, page = _page(kind.value, table)
    OBJECT_REGISTRY.register(
        kind,
        model,
        count=count,
        summaries=page,
        detail=lambda tx, pid, oid, k=kind.value: _detail(tx, pid, k, oid),
    )
