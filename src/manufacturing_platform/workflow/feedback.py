"""Immutable delivered-product feedback and ordered human corrective evidence."""

from datetime import datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from pydantic import ValidationError

from .commands import COMMAND_REGISTRY
from .contracts import (
    DomainError,
    MutationResult,
    ObjectDetail,
    ObjectEvidence,
    ObjectRelation,
    ObjectSummary,
    SourceRef,
)
from .delivery import fail
from .feedback_models import (
    BlockingReason,
    CapaClose,
    CapaStep,
    CapaUpdate,
    CapaValue,
    RmaOpen,
    RmaSourceRecord,
    RmaValue,
)
from .orders import _history_rows, own, project, source_key
from .queries import OBJECT_REGISTRY


def open_rma(tx, context, command):
    from .imports import admit_records

    pid = context.project_id
    unit = own(tx, "units", pid, command.unit_id)
    shipment = own(tx, "shipments", pid, command.shipment_id)
    membership = tx.execute(
        "SELECT * FROM shipment_items WHERE project_id=? AND shipment_id=? AND unit_id=?",
        (str(pid), shipment["id"], unit["id"]),
    ).fetchone()
    if not membership:
        fail("RMA requires actual accepted shipped serial membership")
    record = RmaSourceRecord(
        project_id=pid,
        unit_id=command.unit_id,
        shipment_id=command.shipment_id,
        source=command.source,
    )
    admit_records(tx, context, [record], object_type="rma", trusted=False)
    if command.source.mode != "manual":
        fail("Direct RMA requires explicitly labeled manual source provenance")
    if tx.execute(
        "SELECT 1 FROM rmas WHERE source_system=? AND source_type=? AND source_external_id=?",
        source_key(command.source),
    ).fetchone():
        fail("RMA source identity already recorded")
    if tx.execute(
        "SELECT 1 FROM rmas r LEFT JOIN capas c ON c.rma_id=r.id WHERE r.project_id=? AND r.unit_id=? AND (c.id IS NULL OR c.state<>'closed')",
        (str(pid), unit["id"]),
    ).fetchone():
        fail("Serial already has open mandatory RMA")
    ident = uuid4()
    cutoff = tx.execute(
        "SELECT COALESCE(MAX(seq),0) FROM quality_tests WHERE project_id=? AND unit_id=?",
        (str(pid), unit["id"]),
    ).fetchone()[0]
    tx.execute(
        "INSERT INTO rmas(id,project_id,unit_id,shipment_id,order_line_id,customer_id,revision_id,test_cutoff,reason,source_system,source_type,source_external_id,source_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            str(ident),
            str(pid),
            unit["id"],
            shipment["id"],
            membership["order_line_id"],
            project(tx, pid)["customer_id"],
            unit["revision_id"],
            cutoff,
            command.reason,
            *source_key(command.source),
            command.source.model_dump_json(),
            context.now.isoformat(),
        ),
    )
    return MutationResult(object_type="rma", object_id=ident)


def admitted_source(tx, pid, row):
    from .imports import record_scope, validate_record

    try:
        if row["project_id"] != str(pid):
            return None
        source = SourceRef.model_validate_json(row["source_json"])
        if source.mode != "manual" or source_key(source) != (
            row["source_system"],
            row["source_type"],
            row["source_external_id"],
        ):
            return None
        record = RmaSourceRecord(
            project_id=pid,
            unit_id=row["unit_id"],
            shipment_id=row["shipment_id"],
            source=source,
        )
        record_scope(tx, pid, record, object_type="rma")
        validate_record(
            record,
            SimpleNamespace(
                project_id=UUID(str(pid)), now=datetime.fromisoformat(row["created_at"])
            ),
            trusted=False,
        )
        return source
    except (DomainError, ValidationError, ValueError, TypeError):
        return None


CAPA_ORDER = ("containment", "root_cause", "correction", "verification")


def latest_step_row(tx, pid, cid, step):
    row = tx.execute(
        "SELECT * FROM capa_steps WHERE project_id=? AND capa_id=? AND step=? ORDER BY seq DESC LIMIT 1",
        (str(pid), str(cid), step),
    ).fetchone()
    if row is None:
        return None
    # Durable acceptance order, independent of clocks: revising an earlier
    # prerequisite invalidates downstream evidence in the current cycle only.
    for earlier in CAPA_ORDER[:CAPA_ORDER.index(step)]:
        prior = latest_step_row(tx, pid, cid, earlier)
        if prior is None or prior["seq"] >= row["seq"]:
            return None
    return row


def latest_step(tx, pid, cid, step):
    row = latest_step_row(tx, pid, cid, step)
    return CapaUpdate.model_validate_json(row["payload_json"]) if row else None


def implementation_reasons(tx, pid, rma, correction):
    if correction is None or correction.action_kind is None:
        return ["Corrective action and verified implementation required"]
    if correction.action_kind != "engineering":
        return (
            []
            if correction.implementation_evidence
            and correction.implementation_evidence.strip()
            else ["Supplier/training/process implementation evidence required"]
        )
    if not correction.eco_id:
        return ["Engineering correction requires an applicable implemented closed ECO"]
    eco = own(tx, "eco_changes", pid, correction.eco_id)
    applied = tx.execute(
        """SELECT 1 FROM eco_switches s JOIN work_orders original ON original.id=s.work_order_id AND original.project_id=s.project_id JOIN work_orders replacement ON replacement.id=s.new_work_order_id AND replacement.project_id=s.project_id JOIN exchanges e ON e.id=s.exchange_id AND e.project_id=s.project_id WHERE s.project_id=? AND s.eco_id=? AND s.accepted_receipt_id IS NOT NULL AND s.boundary='split_remaining' AND s.q_atoms>0 AND s.new_revision_id=? AND original.revision_id=? AND original.order_line_id=? AND replacement.order_line_id=original.order_line_id AND replacement.revision_id=s.new_revision_id AND json_extract(e.receipt_json,'$.receipt_id')=s.accepted_receipt_id AND json_extract(e.receipt_json,'$.phase') IN ('accepted','posted') LIMIT 1""",
        (
            str(pid),
            str(correction.eco_id),
            eco["new_revision_id"],
            rma["revision_id"],
            rma["order_line_id"],
        ),
    ).fetchone()
    if (
        eco["state"] != "closed"
        or eco["old_revision_id"] != rma["revision_id"]
        or not applied
    ):
        return [
            "Engineering correction requires actual applicable new-revision implementation and ECO closure; retention/cancellation is insufficient"
        ]
    return []


def capa_reasons(tx, pid, row):
    reasons = []
    for name in ("containment", "root_cause", "correction", "verification"):
        if latest_step(tx, pid, row["id"], name) is None:
            reasons.append(name + " evidence required")
    verification = latest_step(tx, pid, row["id"], "verification")
    if verification and verification.effective is not True:
        reasons.append("Effectiveness verification failed; CAPA remains open")
    reasons += implementation_reasons(
        tx,
        pid,
        own(tx, "rmas", pid, row["rma_id"]),
        latest_step(tx, pid, row["id"], "correction"),
    )
    return reasons


def update_capa(tx, context, command):
    pid = context.project_id
    own(tx, "rmas", pid, command.rma_id)
    cid = command.capa_id
    if cid is None:
        if command.step != "containment":
            fail("CAPA begins with containment")
        if tx.execute(
            "SELECT 1 FROM capas WHERE rma_id=?", (str(command.rma_id),)
        ).fetchone():
            fail("RMA already has CAPA; use its existing identity")
        cid = uuid4()
        tx.execute(
            "INSERT INTO capas(id,project_id,rma_id,state,created_at) VALUES (?,?,?,'open',?)",
            (str(cid), str(pid), str(command.rma_id), context.now.isoformat()),
        )
    row = own(tx, "capas", pid, cid)
    if row["rma_id"] != str(command.rma_id) or row["state"] != "open":
        fail("CAPA must be open and belong to this RMA")
    steps = ("containment", "root_cause", "correction", "verification")
    index = steps.index(command.step)
    if any(latest_step(tx, pid, cid, name) is None for name in steps[:index]):
        fail("Complete prior CAPA evidence steps in order")
    if command.step == "verification":
        if command.effective is None:
            fail("Verification requires explicit effectiveness result")
        basis = latest_step_row(tx, pid, cid, "correction")
        if command.basis_sequence is not None and command.basis_sequence != basis["seq"]:
            fail("Verification basis is stale; review the current correction")
    elif command.effective is not None or command.basis_sequence is not None:
        fail("Effectiveness result and basis belong only to verification")
    if command.step == "correction":
        if command.action_kind is None:
            fail("Correction requires its action kind")
        if command.action_kind == "engineering":
            if command.eco_id is None:
                fail("Engineering correction requires ECO")
            own(tx, "eco_changes", pid, command.eco_id)
        elif (
            command.eco_id is not None
            or not command.implementation_evidence
            or not command.implementation_evidence.strip()
        ):
            fail("Non-engineering correction requires its own implementation evidence")
    elif command.action_kind or command.eco_id or command.implementation_evidence:
        fail("Implementation belongs to the correction step")
    tx.execute(
        "INSERT INTO capa_steps(project_id,capa_id,step,payload_json,created_at) VALUES (?,?,?,?,?)",
        (
            str(pid),
            str(cid),
            command.step,
            command.model_dump_json(),
            context.now.isoformat(),
        ),
    )
    return MutationResult(object_type="capa", object_id=cid)


def close_capa(tx, context, command):
    row = own(tx, "capas", context.project_id, command.capa_id)
    if row["state"] != "open":
        fail("CAPA already closed")
    reasons = capa_reasons(tx, context.project_id, row)
    if reasons:
        fail("; ".join(reasons))
    tx.execute("UPDATE capas SET state='closed' WHERE id=?", (row["id"],))
    return MutationResult(object_type="capa", object_id=command.capa_id)


def quality_blockers(tx, project_id) -> list[BlockingReason]:
    # Only existence is needed for closure, so bounded witnesses suffice.
    blockers = []
    for row in tx.execute(
        "SELECT r.id FROM rmas r LEFT JOIN capas c ON c.rma_id=r.id WHERE r.project_id=? AND (c.id IS NULL OR c.state<>'closed') ORDER BY r.seq LIMIT 100",
        (str(project_id),),
    ):
        blockers.append(
            BlockingReason(kind="rma", id=row[0], reason="Mandatory RMA remains open")
        )
    for row in tx.execute(
        "SELECT id FROM capas WHERE project_id=? AND state='open' ORDER BY seq LIMIT 100",
        (str(project_id),),
    ):
        blockers.append(
            BlockingReason(kind="capa", id=row[0], reason="Mandatory CAPA remains open")
        )
    for row in tx.execute(
        """SELECT n.id FROM nonconformances n LEFT JOIN quality_dispositions d ON d.nonconformance_id=n.id LEFT JOIN rework_orders r ON r.nonconformance_id=n.id LEFT JOIN rework_completions c ON c.rework_order_id=r.id WHERE n.project_id=? AND NOT EXISTS(SELECT 1 FROM quality_dispositions scrap WHERE scrap.unit_id=n.unit_id AND scrap.decision='scrap') AND (d.id IS NULL OR (d.decision='rework' AND c.id IS NULL)) LIMIT 1""",
        (str(project_id),),
    ):
        blockers.append(
            BlockingReason(
                kind="nonconformance",
                id=row[0],
                reason="Mandatory nonconformance remains unresolved",
            )
        )
    return blockers


def summary(tx, pid, kind, row):
    if kind == "rma":
        closed = tx.execute(
            "SELECT 1 FROM capas WHERE rma_id=? AND state='closed'", (row["id"],)
        ).fetchone()
        state = "closed" if closed else "open"
    else:
        state = row["state"]
    return ObjectSummary(
        id=row["id"],
        kind=kind,
        project_id=pid,
        title=kind.upper() + " " + row["id"][:8],
        state=state,
        version=1,
        next_actions=["capa.update"] if state == "open" else [],
    )


def audit_evidence(tx, pid, row, payload):
    try:
        if payload.get("project_id") != str(pid):
            return []
        fields = {k: v for k, v in payload.items() if k != "project_id"}
        if row["action"] == "rma.open":
            command = RmaOpen.model_validate(fields)
            fact = own(tx, "rmas", pid, row["object_id"])
            source = admitted_source(tx, pid, fact)
            if (
                not source
                or command.source != source
                or str(command.unit_id) != fact["unit_id"]
                or str(command.shipment_id) != fact["shipment_id"]
                or command.reason != fact["reason"]
            ):
                return []
            return [ObjectEvidence(reference=source.evidence, source=source)]
        if row["action"] == "capa.update":
            command = CapaUpdate.model_validate(fields)
            fact = own(tx, "capas", pid, row["object_id"])
            if (
                fact["rma_id"] != str(command.rma_id)
                or not tx.execute(
                    "SELECT 1 FROM capa_steps WHERE project_id=? AND capa_id=? AND payload_json=?",
                    (str(pid), row["object_id"], command.model_dump_json()),
                ).fetchone()
            ):
                return []
            return [ObjectEvidence(reference=command.evidence)]
        return []
    except (DomainError, ValidationError, ValueError, TypeError):
        return []


def detail(tx, pid, kind, ident):
    table = "rmas" if kind == "rma" else "capas"
    row = tx.execute(
        f"SELECT * FROM {table} WHERE project_id=? AND id=?", (str(pid), str(ident))
    ).fetchone()
    if not row:
        return None
    summarised = summary(tx, pid, kind, row)
    if kind == "rma":
        tests = tx.execute(
            "SELECT id FROM quality_tests WHERE project_id=? AND unit_id=? AND seq<=? ORDER BY seq LIMIT 501",
            (str(pid), row["unit_id"], row["test_cutoff"]),
        ).fetchall()
        value = RmaValue(
            id=row["id"],
            unit_id=row["unit_id"],
            shipment_id=row["shipment_id"],
            order_line_id=row["order_line_id"],
            customer_id=row["customer_id"],
            revision_id=row["revision_id"],
            test_ids=[r[0] for r in tests[:500]],
            tests_truncated=len(tests) > 500,
            reason=row["reason"],
            source=admitted_source(tx, pid, row),
            state=summarised.state,
        )
        links = [
            ("unit", row["unit_id"]),
            ("shipment", row["shipment_id"]),
            ("revision", row["revision_id"]),
            ("order_line", row["order_line_id"]),
        ]
    else:
        steps = tx.execute(
            "SELECT * FROM capa_steps WHERE project_id=? AND capa_id=? ORDER BY seq DESC LIMIT 101",
            (str(pid), str(ident)),
        ).fetchall()
        values = []
        for s in reversed(steps[:100]):
            data = CapaUpdate.model_validate_json(s["payload_json"])
            values.append(
                CapaStep(
                    sequence=s["seq"],
                    basis_sequence=(tx.execute(
                        "SELECT MAX(seq) FROM capa_steps WHERE project_id=? AND capa_id=? AND step='correction' AND seq<?",
                        (str(pid), str(ident), s["seq"]),
                    ).fetchone()[0] if s["step"] == "verification" else None),
                    **{
                        k: getattr(data, k)
                        for k in CapaStep.model_fields
                        if k not in {"sequence", "basis_sequence"}
                    },
                )
            )
        value = CapaValue(
            id=row["id"],
            rma_id=row["rma_id"],
            state=row["state"],
            steps=values,
            current_basis_sequence=(basis["seq"] if (basis := latest_step_row(tx, pid, ident, "correction")) else None),
            steps_truncated=len(steps) > 100,
            blocking_reasons=capa_reasons(tx, pid, row)
            if row["state"] == "open"
            else [],
        )
        links = [("rma", row["rma_id"])]
    history = _history_rows(
        tx.execute(
            "SELECT * FROM audit_events WHERE project_id=? AND object_id=? ORDER BY id DESC LIMIT 100",
            (str(pid), str(ident)),
        ),
        evidence_projector=lambda event, payload: audit_evidence(
            tx, pid, event, payload
        ),
    )
    return ObjectDetail(
        summary=summarised,
        value=value,
        relations=[
            ObjectRelation(relation=k, kind=k, project_id=pid, id=i) for k, i in links
        ],
        evidence=[],
        history=history,
    )


for model, handler in [
    (RmaOpen, open_rma),
    (CapaUpdate, update_capa),
    (CapaClose, close_capa),
]:
    COMMAND_REGISTRY.register(
        model, roles={"quality"}, qualifications={"disposition"}, handler=handler
    )


def register(kind, table, model):
    OBJECT_REGISTRY.register(
        kind,
        model,
        count=lambda tx, pid: tx.execute(
            f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (str(pid),)
        ).fetchone()[0],
        summaries=lambda tx, pid, limit, offset: [
            summary(tx, pid, kind, r)
            for r in tx.execute(
                f"SELECT * FROM {table} WHERE project_id=? ORDER BY seq LIMIT ? OFFSET ?",
                (str(pid), limit, offset),
            )
        ],
        detail=lambda tx, pid, ident: detail(tx, pid, kind, ident),
    )


register("rma", "rmas", RmaValue)
register("capa", "capas", CapaValue)
