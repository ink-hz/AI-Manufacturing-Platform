"""Serial scopes, source genealogy and authority-backed production transitions."""

import json
from datetime import datetime, timedelta
from typing import Protocol
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
from .engineering import fixed_revision
from .exchange_models import ExternalRequest, ResumePayload, StartPayload, StopPayload
from .execution_models import (
    InterruptionValue,
    InterruptProduction,
    RecordExecution,
    RecordFirstArticle,
    RegisterUnits,
    ResumeProduction,
    StartProduction,
    UnitValue,
    sn_key,
)
from .orders import _history_rows, own, source_key
from .queries import OBJECT_REGISTRY
from .readiness import evaluate
from .supply import amount, current_plan_id
from .supply import atoms as material_atoms


class TestEvidenceReader(Protocol):
    def complete_pass(
        self, tx, project_id: UUID, test_id: UUID, unit_id: UUID, revision_id: UUID
    ) -> bool: ...


class NoTestEvidence:
    def complete_pass(self, tx, project_id, test_id, unit_id, revision_id):
        return False


def fail(reason):
    raise DomainError("PRECONDITION_FAILED", 409, reason, blocking_reasons=[reason])


def integer_units(tx, project_id, work_order_id):
    wo = own(tx, "work_orders", project_id, work_order_id)
    project = tx.execute(
        "SELECT * FROM projects WHERE id=?", (str(project_id),)
    ).fetchone()
    scale = 10 ** project["unit_scale"]
    if wo["q_atoms"] % scale or wo["trial_q_atoms"] % scale:
        fail("work order and trial quantities must be whole units")
    return wo, wo["q_atoms"] // scale, wo["trial_q_atoms"] // scale


def eligible_units(tx, project_id, work_order_id):
    """Registered, unscoped serials on the immutable work order revision."""
    wo = own(tx, "work_orders", project_id, work_order_id)
    return tx.execute(
        """SELECT u.* FROM units u WHERE u.project_id=? AND u.work_order_id=?
           AND u.revision_id=? AND NOT EXISTS
           (SELECT 1 FROM start_units su WHERE su.unit_id=u.id)
           ORDER BY u.registered_seq LIMIT 500""",
        (str(project_id), str(work_order_id), wo["revision_id"]),
    ).fetchall()


def register_units(tx, context, command: RegisterUnits):
    wo, total, _ = integer_units(tx, context.project_id, command.work_order_id)
    count = tx.execute(
        "SELECT COUNT(*) FROM units WHERE work_order_id=? AND project_id=?",
        (wo["id"], str(context.project_id)),
    ).fetchone()[0]
    if count + len(command.sns) > total:
        fail("registered serials exceed whole work order quantity")
    first = None
    for sn in command.sns:
        if tx.execute("SELECT 1 FROM units WHERE sn_key=?", (sn_key(sn),)).fetchone():
            fail("serial number already registered")
        ident = str(uuid4())
        seq = tx.execute(
            "SELECT COALESCE(MAX(registered_seq),0)+1 FROM units"
        ).fetchone()[0]
        tx.execute(
            "INSERT INTO units VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                ident,
                str(context.project_id),
                wo["id"],
                wo["revision_id"],
                sn,
                sn_key(sn),
                "registered",
                None,
                None,
                seq,
            ),
        )
        first = first or ident
    return MutationResult(object_type="unit", object_id=UUID(first))


def _active_interruption(tx, project_id, work_order_id):
    return tx.execute(
        "SELECT * FROM interruptions WHERE project_id=? AND work_order_id=? AND resolved_at IS NULL ORDER BY rowid DESC LIMIT 1",
        (str(project_id), str(work_order_id)),
    ).fetchone()


def outbound_execution_ready(tx, project_id, payload, now):
    """Fresh local gate after authority query and before a new external effect."""
    if isinstance(payload, StartPayload):
        if _active_interruption(tx, project_id, payload.work_order_id):
            return False
        if tx.execute(
            "SELECT 1 FROM units WHERE project_id=? AND work_order_id=? AND state='start_pending' AND accepted_start_id IS NOT NULL LIMIT 1",
            (str(project_id), str(payload.work_order_id)),
        ).fetchone():
            return False
        request = tx.execute(
            "SELECT 1 FROM start_requests WHERE id=? AND project_id=? AND work_order_id=? AND accepted_receipt_id IS NULL",
            (str(payload.start_id), str(project_id), str(payload.work_order_id)),
        ).fetchone()
        return (
            bool(request)
            and evaluate(tx, project_id, payload.work_order_id, payload.mode, now).ready
        )
    interruption = tx.execute(
        "SELECT * FROM interruptions WHERE id=? AND project_id=? AND work_order_id=?",
        (str(payload.interruption_id), str(project_id), str(payload.work_order_id)),
    ).fetchone()
    if (
        not interruption
        or not interruption["authority_stopped_at"]
        or interruption["resolved_at"]
        or current_plan_id(tx, project_id, payload.work_order_id)
        != str(payload.plan_id)
        or interruption["interrupted_plan_id"] == str(payload.plan_id)
    ):
        return False
    modes = [
        r[0]
        for r in tx.execute(
            "SELECT DISTINCT mode FROM start_requests WHERE project_id=? AND work_order_id=? AND accepted_receipt_id IS NOT NULL",
            (str(project_id), str(payload.work_order_id)),
        )
    ]
    return bool(modes) and all(
        evaluate(tx, project_id, payload.work_order_id, mode, now).ready
        for mode in modes
    )


def start_production(tx, context, command: StartProduction):
    wo, total, trial_limit = integer_units(
        tx, context.project_id, command.work_order_id
    )
    if _active_interruption(tx, context.project_id, wo["id"]):
        fail("production is interrupted")
    if tx.execute(
        "SELECT 1 FROM units WHERE project_id=? AND work_order_id=? AND state='start_pending' AND accepted_start_id IS NOT NULL LIMIT 1",
        (str(context.project_id), wo["id"]),
    ).fetchone():
        fail("MES accepted scope is under local safety hold; request a scoped stop")
    readiness = evaluate(tx, context.project_id, wo["id"], command.mode, context.now)
    if not readiness.ready:
        reasons = [
            c.kind + ": " + c.reason for c in readiness.checks if c.status == "blocked"
        ]
        raise DomainError(
            "PRECONDITION_FAILED",
            409,
            "Production readiness blocked",
            blocking_reasons=reasons,
        )
    prior = tx.execute(
        """SELECT s.mode,COALESCE(SUM(s.q_units),0) n FROM start_requests s JOIN exchanges e ON e.id=s.exchange_id WHERE s.project_id=? AND s.work_order_id=? AND (e.phase!='rejected' OR e.receipt_json IS NULL) GROUP BY s.mode""",
        (str(context.project_id), wo["id"]),
    ).fetchall()
    reserved = sum(r["n"] for r in prior)
    trials = sum(r["n"] for r in prior if r["mode"] == "trial")
    if reserved + len(command.unit_ids) > total or (
        command.mode == "trial" and trials + len(command.unit_ids) > trial_limit
    ):
        fail("start scope exceeds work order or trial budget")
    ids = [str(i) for i in command.unit_ids]
    rows = [own(tx, "units", context.project_id, i) for i in ids]
    for u in rows:
        if (
            u["work_order_id"] != wo["id"]
            or u["revision_id"] != wo["revision_id"]
            or tx.execute(
                "SELECT 1 FROM start_units WHERE unit_id=?", (u["id"],)
            ).fetchone()
        ):
            fail("serial is outside work order or already scoped")
    start_id, eid = uuid4(), uuid4()
    request = ExternalRequest(
        id=eid,
        system="erp",
        action="production.start",
        business_key=str(eid),
        source_version=1,
        project_id=context.project_id,
        typed_payload=StartPayload(
            start_id=start_id,
            work_order_id=command.work_order_id,
            revision_id=UUID(wo["revision_id"]),
            mode=command.mode,
            work_order_quantity=total,
            trial_quantity=trial_limit,
            units=[(UUID(u["id"]), u["sn"]) for u in rows],
        ),
    )
    context.exchange_service.prepare(tx, context, request)
    tx.execute(
        "INSERT INTO start_requests VALUES (?,?,?,?,?,?,NULL,0,?)",
        (
            str(start_id),
            str(context.project_id),
            wo["id"],
            command.mode,
            len(rows),
            str(eid),
            context.now.isoformat(),
        ),
    )
    for u in rows:
        tx.execute(
            "INSERT INTO start_units VALUES (?,?,?)",
            (str(start_id), u["id"], str(context.project_id)),
        )
        tx.execute(
            "UPDATE units SET state='start_pending',mode=? WHERE id=?",
            (command.mode, u["id"]),
        )
    return MutationResult(
        object_type="work_order", object_id=command.work_order_id, exchange_id=eid
    )


def interrupt_production(tx, context, command: InterruptProduction):
    wo = own(tx, "work_orders", context.project_id, command.work_order_id)
    active = _active_interruption(tx, context.project_id, wo["id"])
    if active:
        prior = tx.execute(
            "SELECT phase,receipt_json FROM exchanges WHERE id=? AND project_id=?",
            (active["stop_exchange_id"], str(context.project_id)),
        ).fetchone()
        exception = tx.execute(
            "SELECT kind FROM execution_exceptions WHERE id=? AND project_id=?",
            (active["exception_id"], str(context.project_id)),
        ).fetchone()
        if (
            not command.interruption_id
            or str(command.interruption_id) != active["id"]
            or active["authority_stopped_at"]
            or not prior
            or prior["phase"] != "rejected"
            or not prior["receipt_json"]
            or not exception
            or exception["kind"] != command.kind
            or active["reason"] != command.reason
        ):
            fail(
                "production already interrupted; a new stop attempt requires the rejected interruption"
            )
        old_request = tx.execute(
            "SELECT request_json FROM exchanges WHERE id=? AND project_id=?",
            (active["stop_exchange_id"], str(context.project_id)),
        ).fetchone()
        old_start_id = ExternalRequest.model_validate_json(
            old_request[0]
        ).typed_payload.start_id
        if command.start_id != old_start_id:
            fail("stop retry must preserve the original held start scope")
        iid, eid = UUID(active["id"]), uuid4()
    else:
        if command.interruption_id:
            fail("no active rejected interruption to retry")
        if not tx.execute(
            "SELECT 1 FROM start_requests WHERE project_id=? AND work_order_id=? AND accepted_receipt_id IS NOT NULL",
            (str(context.project_id), wo["id"]),
        ).fetchone():
            fail("no accepted production scope to interrupt")
        held = tx.execute(
            """SELECT s.id,s.q_units,COUNT(u.id) held_units FROM start_requests s
               JOIN start_units su ON su.start_id=s.id JOIN units u ON u.id=su.unit_id
               WHERE s.project_id=? AND s.work_order_id=? AND s.accepted_receipt_id IS NOT NULL
                 AND u.state='start_pending' AND u.accepted_start_id=s.id
               GROUP BY s.id ORDER BY s.accepted_seq LIMIT 500""",
            (str(context.project_id), wo["id"]),
        ).fetchall()
        if held and not command.start_id:
            fail("select an MES accepted held start scope for the safety stop")
        if command.start_id and not any(
            r["id"] == str(command.start_id) and r["held_units"] == r["q_units"]
            for r in held
        ):
            fail("held start scope is not an accepted scope of this work order")
        iid, eid = uuid4(), uuid4()
    request = ExternalRequest(
        id=eid,
        system="erp",
        action="production.interrupt",
        business_key=str(eid),
        source_version=1,
        project_id=context.project_id,
        typed_payload=StopPayload(
            interruption_id=iid,
            work_order_id=command.work_order_id,
            reason=command.reason,
            start_id=command.start_id,
        ),
    )
    context.exchange_service.prepare(tx, context, request)
    if active:
        tx.execute(
            "UPDATE interruptions SET stop_exchange_id=? WHERE id=? AND project_id=?",
            (str(eid), str(iid), str(context.project_id)),
        )
    else:
        exception_id = uuid4()
        tx.execute(
            "INSERT INTO interruptions(id,project_id,work_order_id,reason,exception_id,requested_at,interrupted_plan_id,stop_exchange_id) VALUES (?,?,?,?,?,?,?,?)",
            (
                str(iid),
                str(context.project_id),
                wo["id"],
                command.reason,
                str(exception_id),
                context.now.isoformat(),
                current_plan_id(tx, context.project_id, wo["id"]),
                str(eid),
            ),
        )
        tx.execute(
            "INSERT INTO execution_exceptions VALUES (?,?,?,?,?,?,?)",
            (
                str(exception_id),
                str(context.project_id),
                wo["id"],
                str(iid),
                command.kind,
                command.reason,
                context.now.isoformat(),
            ),
        )
    tx.execute(
        "INSERT INTO interruption_actions(project_id,interruption_id,exchange_id,kind) VALUES (?,?,?,'stop')",
        (str(context.project_id), str(iid), str(eid)),
    )
    return MutationResult(object_type="interruption", object_id=iid, exchange_id=eid)


def resume_production(tx, context, command: ResumeProduction):
    interruption = own(tx, "interruptions", context.project_id, command.interruption_id)
    if interruption["resolved_at"] or not interruption["authority_stopped_at"]:
        fail("interruption is not confirmed stopped or already resuming")
    if interruption["resume_exchange_id"]:
        prior = tx.execute(
            "SELECT phase,receipt_json FROM exchanges WHERE id=? AND project_id=?",
            (interruption["resume_exchange_id"], str(context.project_id)),
        ).fetchone()
        if not prior or prior["phase"] != "rejected" or not prior["receipt_json"]:
            fail("resume already requested; query authority before another attempt")
    if current_plan_id(tx, context.project_id, interruption["work_order_id"]) != str(
        command.plan_id
    ):
        fail("resume requires current accepted replan")
    if interruption["interrupted_plan_id"] == str(command.plan_id):
        fail("resume requires a new accepted plan after interruption")
    modes = [
        r[0]
        for r in tx.execute(
            "SELECT DISTINCT mode FROM start_requests WHERE project_id=? AND work_order_id=? AND accepted_receipt_id IS NOT NULL",
            (str(context.project_id), interruption["work_order_id"]),
        )
    ]
    for mode in modes:
        readiness = evaluate(
            tx, context.project_id, interruption["work_order_id"], mode, context.now
        )
        if not readiness.ready:
            raise DomainError(
                "PRECONDITION_FAILED",
                409,
                "Resume readiness blocked",
                blocking_reasons=[
                    c.kind + ": " + c.reason
                    for c in readiness.checks
                    if c.status == "blocked"
                ],
            )
    eid = uuid4()
    request = ExternalRequest(
        id=eid,
        system="erp",
        action="production.resume",
        business_key=str(eid),
        source_version=1,
        project_id=context.project_id,
        typed_payload=ResumePayload(
            interruption_id=command.interruption_id,
            work_order_id=UUID(interruption["work_order_id"]),
            plan_id=command.plan_id,
        ),
    )
    context.exchange_service.prepare(tx, context, request)
    tx.execute(
        "UPDATE interruptions SET resume_exchange_id=?,plan_id=? WHERE id=?",
        (str(eid), str(command.plan_id), str(command.interruption_id)),
    )
    tx.execute(
        "INSERT INTO interruption_actions(project_id,interruption_id,exchange_id,kind) VALUES (?,?,?,'resume')",
        (str(context.project_id), str(command.interruption_id), str(eid)),
    )
    return MutationResult(
        object_type="interruption", object_id=command.interruption_id, exchange_id=eid
    )


def record_execution(tx, context, command: RecordExecution):
    wo = own(tx, "work_orders", context.project_id, command.work_order_id)
    source = command.source
    key = source_key(source)
    prior = tx.execute(
        "SELECT id FROM execution_events WHERE source_system=? AND source_type=? AND source_external_id=? ORDER BY accepted_seq DESC LIMIT 1",
        key,
    ).fetchone()
    unit = tx.execute(
        "SELECT * FROM units WHERE sn_key=? AND project_id=?",
        (sn_key(command.sn), str(context.project_id)),
    ).fetchone()
    reason = ""
    if (
        source.object_type != "execution"
        or source.mode not in {"manual", "file"}
        or source.collected_at < source.occurred_at
    ):
        reason = "execution source identity or provenance invalid"
    elif (
        command.occurred_at > context.now + timedelta(minutes=5)
        or source.collected_at + timedelta(minutes=5) < command.occurred_at
    ):
        reason = "execution occurrence is future or after source collection"
    elif prior:
        reason = "duplicate execution source event"
    elif not unit or unit["work_order_id"] != wo["id"]:
        reason = "unknown or wrong work order serial"
    elif unit["state"] != "running" or _active_interruption(
        tx, context.project_id, wo["id"]
    ):
        reason = "serial is not authority-confirmed running"
    elif command.rework_order_id:
        reason = "rework route requires C1 qualified rework order"
    else:
        revision = fixed_revision(tx, context.project_id, wo["revision_id"])
        route = {s.station: s.instruction_version for s in revision.route_steps}
        if (
            route.get(command.station) != command.route_version
            or command.program_version != revision.test_spec.program_version
            or command.firmware_version != revision.firmware_version
        ):
            reason = "station, SOP, program or firmware differs from fixed package"
        elif not command.material_uses:
            reason = "material usage links required"
        else:
            proposed_by_lot = {}
            for use in command.material_uses:
                lot = tx.execute(
                    "SELECT * FROM material_lots WHERE id=? AND project_id=?",
                    (str(use.lot_id), str(context.project_id)),
                ).fetchone()
                if (
                    not lot
                    or lot["state"] != "active"
                    or lot["expiry"] < context.now.date().isoformat()
                    or use.unit != lot["unit"]
                ):
                    reason = "material lot ownership, state, expiry or unit invalid"
                    break
                plan_id = current_plan_id(tx, context.project_id, wo["id"])
                eligible = tx.execute(
                    """SELECT COALESCE(SUM(r.confirmed_atoms),0) FROM reservations r JOIN requirements q ON q.id=r.requirement_id AND q.project_id=r.project_id WHERE r.project_id=? AND r.work_order_id=? AND r.material_lot_id=? AND r.authority_receipt_id IS NOT NULL AND q.material_id=? AND q.owner_id=? AND EXISTS (SELECT 1 FROM requirements current WHERE current.project_id=r.project_id AND current.plan_id=? AND current.work_order_id=r.work_order_id AND current.lineage_id=q.lineage_id AND current.execution_scope IN (?,'common'))""",
                    (
                        str(context.project_id),
                        wo["id"],
                        lot["id"],
                        lot["material_id"],
                        lot["owner_id"],
                        plan_id,
                        unit["mode"],
                    ),
                ).fetchone()[0]
                eligible_all = tx.execute(
                    """SELECT COALESCE(SUM(r.confirmed_atoms),0) FROM reservations r JOIN requirements q ON q.id=r.requirement_id AND q.project_id=r.project_id WHERE r.project_id=? AND r.work_order_id=? AND r.material_lot_id=? AND r.authority_receipt_id IS NOT NULL AND q.material_id=? AND q.owner_id=? AND EXISTS (SELECT 1 FROM requirements current WHERE current.project_id=r.project_id AND current.plan_id=? AND current.work_order_id=r.work_order_id AND current.lineage_id=q.lineage_id)""",
                    (
                        str(context.project_id),
                        wo["id"],
                        lot["id"],
                        lot["material_id"],
                        lot["owner_id"],
                        plan_id,
                    ),
                ).fetchone()[0]
                used = tx.execute(
                    """SELECT COALESCE(SUM(mc.q_atoms),0) FROM material_consumption mc JOIN units u ON u.id=mc.unit_id AND u.project_id=mc.project_id WHERE mc.project_id=? AND mc.lot_id=? AND u.work_order_id=? AND u.mode=?""",
                    (str(context.project_id), lot["id"], wo["id"], unit["mode"]),
                ).fetchone()[0]
                used_all = tx.execute(
                    """SELECT COALESCE(SUM(mc.q_atoms),0) FROM material_consumption mc JOIN units u ON u.id=mc.unit_id AND u.project_id=mc.project_id WHERE mc.project_id=? AND mc.lot_id=? AND u.work_order_id=?""",
                    (str(context.project_id), lot["id"], wo["id"]),
                ).fetchone()[0]
                try:
                    requested = material_atoms(
                        use.quantity, use.unit, lot["unit"], lot["scale"]
                    )
                except DomainError:
                    reason = "material use quantity precision or unit invalid"
                    break
                proposed_by_lot[lot["id"]] = (
                    proposed_by_lot.get(lot["id"], 0) + requested
                )
                if (
                    proposed_by_lot[lot["id"]] > eligible - used
                    or proposed_by_lot[lot["id"]] > eligible_all - used_all
                ):
                    reason = "material use exceeds scoped accepted reservation"
                    break
    if command.supersedes_event_id:
        old = tx.execute(
            "SELECT * FROM execution_events WHERE id=? AND project_id=?",
            (str(command.supersedes_event_id), str(context.project_id)),
        ).fetchone()
        if not old or old["status"] != "rejected" or old["work_order_id"] != wo["id"]:
            reason = "correction must link a rejected event in this work order"
    ident = str(uuid4())
    seq = tx.execute(
        "SELECT COALESCE(MAX(accepted_seq),0)+1 FROM execution_events"
    ).fetchone()[0]
    tx.execute(
        """INSERT INTO execution_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            ident,
            str(context.project_id),
            wo["id"],
            unit["id"] if unit else None,
            command.sn,
            *key,
            source.version,
            source.model_dump_json(),
            command.station,
            command.route_version,
            command.program_version,
            command.firmware_version,
            command.result,
            "rejected" if reason else "accepted",
            reason,
            "rework" if command.rework_order_id else "initial",
            str(command.rework_order_id) if command.rework_order_id else None,
            str(command.supersedes_event_id) if command.supersedes_event_id else None,
            command.occurred_at.isoformat(),
            context.now.isoformat(),
            seq,
        ),
    )
    if not reason:
        for use in command.material_uses:
            lot = own(tx, "material_lots", context.project_id, use.lot_id)
            tx.execute(
                "INSERT INTO material_consumption VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    str(context.project_id),
                    ident,
                    unit["id"],
                    lot["id"],
                    lot["material_id"],
                    lot["owner_id"],
                    material_atoms(use.quantity, use.unit, lot["unit"], lot["scale"]),
                    use.unit,
                    seq,
                ),
            )
    return MutationResult(
        object_type="unit",
        object_id=UUID(unit["id"]) if unit else command.work_order_id,
    )


def record_first_article(tx, context, command: RecordFirstArticle):
    wo = own(tx, "work_orders", context.project_id, command.work_order_id)
    if len(command.unit_ids) != len(command.test_ids) or len(
        set(command.unit_ids)
    ) != len(command.unit_ids):
        fail("first article requires one unique complete test per trial serial")
    reader = context.exchange_service.workflow.test_evidence_reader
    revision = fixed_revision(tx, context.project_id, wo["revision_id"])
    for uid, tid in zip(command.unit_ids, command.test_ids, strict=True):
        unit = own(tx, "units", context.project_id, uid)
        if (
            unit["work_order_id"] != wo["id"]
            or unit["mode"] != "trial"
            or unit["state"] != "running"
            or not reader.complete_pass(
                tx, context.project_id, tid, uid, UUID(wo["revision_id"])
            )
        ):
            fail("first_article requires complete matching trial test evidence")
    equipment = tx.execute(
        "SELECT * FROM readiness_checks WHERE project_id=? AND work_order_id=? AND kind='equipment' ORDER BY rowid DESC LIMIT 1",
        (str(context.project_id), wo["id"]),
    ).fetchone()
    if (
        not equipment
        or equipment["decision"] != "verified"
        or datetime.fromisoformat(equipment["valid_until"]) < context.now
    ):
        fail("first_article equipment calibration expired")
    ident = str(uuid4())
    seq = tx.execute(
        "SELECT COALESCE(MAX(accepted_seq),0)+1 FROM first_articles"
    ).fetchone()[0]
    tx.execute(
        "INSERT INTO first_articles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ident,
            str(context.project_id),
            wo["id"],
            wo["revision_id"],
            revision.content_hash,
            revision.test_spec.version,
            revision.test_spec.program_version,
            revision.firmware_version,
            equipment["id"],
            command.inspection_id,
            json.dumps([str(t) for t in command.test_ids]),
            json.dumps([str(u) for u in command.unit_ids]),
            seq,
            context.now.isoformat(),
        ),
    )
    return MutationResult(object_type="work_order", object_id=command.work_order_id)


def unit_summary(row):
    visible_state = (
        "mes_accepted_held"
        if row["state"] == "start_pending" and row["accepted_start_id"]
        else row["state"]
    )
    return ObjectSummary(
        id=row["id"],
        project_id=row["project_id"],
        kind="unit",
        title=row["sn"],
        state=visible_state,
        version=row["registered_seq"],
        next_actions=["execution.record"] if row["state"] == "running" else [],
    )


def event_view(tx, pid, e):
    uses = [
        {
            "lot_id": u["lot_id"],
            "material_id": u["material_id"],
            "owner_id": u["owner_id"],
            "quantity": amount(u["q_atoms"], u["scale"]),
            "unit": u["unit"],
        }
        for u in tx.execute(
            "SELECT mc.*,l.scale FROM material_consumption mc JOIN material_lots l ON l.id=mc.lot_id AND l.project_id=mc.project_id WHERE mc.project_id=? AND mc.execution_event_id=? ORDER BY mc.accepted_seq,mc.id LIMIT 200",
            (str(pid), e["id"]),
        )
    ]
    return {
        "id": e["id"],
        "claimed_sn": e["claimed_sn"],
        "source": json.loads(e["source_json"]),
        "status": e["status"],
        "reason": e["reason"],
        "station": e["station"],
        "route_version": e["route_version"],
        "program_version": e["program_version"],
        "firmware_version": e["firmware_version"],
        "result": e["result"],
        "route_kind": e["route_kind"],
        "supersedes_event_id": e["supersedes_event_id"],
        "occurred_at": e["occurred_at"],
        "recorded_at": e["recorded_at"],
        "material_uses": uses,
    }


def work_order_events(tx, pid, work_order_id):
    total = tx.execute(
        "SELECT COUNT(*) FROM execution_events WHERE project_id=? AND work_order_id=?",
        (str(pid), str(work_order_id)),
    ).fetchone()[0]
    rows = tx.execute(
        "SELECT * FROM execution_events WHERE project_id=? AND work_order_id=? ORDER BY accepted_seq DESC LIMIT 100",
        (str(pid), str(work_order_id)),
    ).fetchall()
    return total, [event_view(tx, pid, e) for e in reversed(rows)]


def unit_detail(tx, pid, ident):
    row = tx.execute(
        "SELECT * FROM units WHERE id=? AND project_id=?", (str(ident), str(pid))
    ).fetchone()
    if not row:
        return None
    event_total = tx.execute(
        "SELECT COUNT(*) FROM execution_events WHERE project_id=? AND unit_id=?",
        (str(pid), str(ident)),
    ).fetchone()[0]
    events = tx.execute(
        "SELECT * FROM execution_events WHERE project_id=? AND unit_id=? ORDER BY accepted_seq DESC LIMIT 100",
        (str(pid), str(ident)),
    ).fetchall()
    event_views = [event_view(tx, pid, e) for e in reversed(events)]
    return ObjectDetail[UnitValue](
        summary=unit_summary(row),
        value=UnitValue(
            id=row["id"],
            project_id=row["project_id"],
            work_order_id=row["work_order_id"],
            revision_id=row["revision_id"],
            sn=row["sn"],
            state=row["state"],
            mode=row["mode"],
            accepted_start_id=row["accepted_start_id"],
            authority_start_accepted=row["accepted_start_id"] is not None,
            execution_event_ids=[e["id"] for e in reversed(events)],
            execution_event_total=event_total,
            execution_events=event_views,
        ),
        relations=[
            ObjectRelation(
                relation="work_order",
                project_id=pid,
                kind="work_order",
                id=row["work_order_id"],
            )
        ],
        evidence=[],
        history=_history_rows(
            tx.execute(
                "SELECT * FROM audit_events WHERE project_id=? AND object_id=? ORDER BY id LIMIT 500",
                (str(pid), str(ident)),
            ).fetchall()
        ),
    )


def interruption_summary(row):
    state = (
        "resumed"
        if row["resolved_at"]
        else "stopped"
        if row["authority_stopped_at"]
        else "stop_requested"
    )
    return ObjectSummary(
        id=row["id"],
        project_id=row["project_id"],
        kind="interruption",
        title=row["reason"][:120],
        state=state,
        version=1,
        next_actions=["production.resume"] if state == "stopped" else [],
    )


def interruption_detail(tx, pid, ident):
    row = tx.execute(
        "SELECT * FROM interruptions WHERE id=? AND project_id=?",
        (str(ident), str(pid)),
    ).fetchone()
    if not row:
        return None
    exception = tx.execute(
        "SELECT kind FROM execution_exceptions WHERE id=? AND project_id=? AND interruption_id=?",
        (row["exception_id"], str(pid), row["id"]),
    ).fetchone()
    actions = tx.execute(
        "SELECT exchange_id,kind FROM interruption_actions WHERE project_id=? AND interruption_id=? ORDER BY seq LIMIT 100",
        (str(pid), row["id"]),
    ).fetchall()
    stop_request = tx.execute(
        "SELECT request_json FROM exchanges WHERE id=? AND project_id=?",
        (row["stop_exchange_id"], str(pid)),
    ).fetchone()
    recovery_start_id = (
        ExternalRequest.model_validate_json(stop_request[0]).typed_payload.start_id
        if stop_request
        else None
    )
    return ObjectDetail[InterruptionValue](
        summary=interruption_summary(row),
        value=InterruptionValue(
            id=row["id"],
            work_order_id=row["work_order_id"],
            reason=row["reason"],
            exception_id=row["exception_id"],
            exception_kind=exception["kind"] if exception else "other",
            requested_at=row["requested_at"],
            authority_stopped_at=row["authority_stopped_at"],
            resolved_at=row["resolved_at"],
            plan_id=row["plan_id"],
            stop_exchange_id=row["stop_exchange_id"],
            recovery_start_id=recovery_start_id,
            resume_exchange_id=row["resume_exchange_id"],
            stop_exchange_ids=[
                a["exchange_id"] for a in actions if a["kind"] == "stop"
            ],
            resume_exchange_ids=[
                a["exchange_id"] for a in actions if a["kind"] == "resume"
            ],
        ),
        relations=[
            ObjectRelation(
                relation="work_order",
                project_id=pid,
                kind="work_order",
                id=row["work_order_id"],
            )
        ],
        evidence=[ObjectEvidence(reference=row["reason"])],
        history=_history_rows(
            tx.execute(
                "SELECT * FROM audit_events WHERE project_id=? AND object_id=? ORDER BY id LIMIT 500",
                (str(pid), str(ident)),
            ).fetchall()
        ),
    )


for model, roles, qualifications, handler in (
    (RegisterUnits, {"production"}, set(), register_units),
    (StartProduction, {"production"}, set(), start_production),
    (InterruptProduction, {"production"}, set(), interrupt_production),
    (ResumeProduction, {"production"}, set(), resume_production),
    (RecordExecution, {"production"}, set(), record_execution),
    (RecordFirstArticle, {"quality"}, {"inspection"}, record_first_article),
):
    COMMAND_REGISTRY.register(
        model, roles=roles, qualifications=qualifications, handler=handler
    )


for kind, table, model, summary, detail in (
    ("unit", "units", UnitValue, unit_summary, unit_detail),
    (
        "interruption",
        "interruptions",
        InterruptionValue,
        interruption_summary,
        interruption_detail,
    ),
):
    OBJECT_REGISTRY.register(
        ObjectKind(kind),
        model,
        count=lambda tx, pid, t=table: tx.execute(
            f"SELECT COUNT(*) FROM {t} WHERE project_id=?", (str(pid),)
        ).fetchone()[0],
        summaries=lambda tx, pid, limit, offset, t=table, s=summary: [
            s(r)
            for r in tx.execute(
                f"SELECT * FROM {t} WHERE project_id=? ORDER BY rowid LIMIT ? OFFSET ?",
                (str(pid), limit, offset),
            )
        ],
        detail=detail,
    )
