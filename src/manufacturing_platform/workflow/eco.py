"""Immutable ECO evidence and explicit authority-confirmed remaining obligations."""

import json
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from .commands import COMMAND_REGISTRY
from .contracts import (
    DomainError,
    MutationResult,
    ObjectDetail,
    ObjectEvidence,
    ObjectSummary,
)
from .eco_models import (
    CloseEco,
    DisposeEco,
    EcoDisposition,
    EcoImpact,
    EcoValue,
    OpenEco,
    SwitchEco,
)
from .engineering import _history, count, fail, fixed_revision
from .orders import allocated, amount, own, project
from .queries import OBJECT_REGISTRY
from .supply import amount as material_amount
from .supply import atoms as material_atoms


def stock_lots(tx, pid, rid):
    return tx.execute(
        "SELECT DISTINCT l.* FROM material_lots l JOIN requirements r ON r.project_id=l.project_id AND r.material_id=l.material_id AND r.owner_id=l.owner_id AND r.unit=l.unit JOIN work_orders w ON w.id=r.work_order_id AND w.project_id=r.project_id WHERE w.project_id=? AND w.revision_id=?",
        (str(pid), str(rid)),
    ).fetchall()


def stock_evidence(tx, pid, lot):
    """Admitted positive physical additions by immutable identity, not net stock."""
    from .exchange_models import ExternalReceipt
    from .exchanges import receipt_scope as admitted_receipt

    evidence = {}
    for r in tx.execute(
        "SELECT * FROM effective_supply_receipts WHERE project_id=? AND material_lot_id=?",
        (str(pid), lot["id"]),
    ):
        key = json.dumps(
            [
                "receipt",
                r["source_system"].strip().casefold(),
                r["source_external_id"].strip(),
            ],
            separators=(",", ":"),
        )
        evidence[key] = r["q_atoms"]
    covered = {}
    complete = True
    unknown = 0
    for r in tx.execute(
        "SELECT e.*,v.confirmed_atoms FROM reservations v JOIN exchanges e ON e.id=v.exchange_id WHERE v.project_id=? AND v.material_lot_id=? AND v.authority_receipt_id IS NOT NULL",
        (str(pid), lot["id"]),
    ):
        receipt = ExternalReceipt.model_validate_json(r["receipt_json"])
        basis = receipt.details[0].stock_basis
        if basis is None or not admitted_receipt(tx, r, receipt):
            complete = False
            unknown += r["confirmed_atoms"]
            continue
        for b in basis:
            key = json.dumps(
                ["receipt", b.system.strip().casefold(), b.external_id.strip()],
                separators=(",", ":"),
            )
            covered[key] = covered.get(key, 0) + material_atoms(
                b.quantity, b.unit, lot["unit"], lot["scale"]
            )
    for key, q in covered.items():
        evidence[key] = max(evidence.get(key, 0), q)
    return evidence, complete, unknown


def impacts(tx, project_id, old_revision_id) -> list[EcoImpact]:
    """Actual revision-linked scope, including pooled stock with matching owner/material.

    Categories describe independent obligations; their quantities must never be summed
    across categories. Source-confirmed starts are WIP even when locally held/stopped.
    """
    p = project(tx, project_id)
    pid, rid = str(project_id), str(old_revision_id)
    result = []

    def add(kind, row, quantity, unit, scale, title, owner, state):
        if quantity <= 0:
            return
        key = f"{pid}:{rid}:{kind}:{row['id']}:{quantity}:{unit}:{scale}"
        result.append(
            EcoImpact(
                id=uuid5(NAMESPACE_URL, key),
                type=kind,
                object_id=row["id"],
                title=title,
                owner_id=owner,
                quantity=material_amount(quantity, scale),
                unit=unit,
                scale=scale,
                state=state,
            )
        )

    for w in tx.execute(
        "SELECT * FROM effective_work_orders WHERE project_id=? AND revision_id=?",
        (pid, rid),
    ):
        add(
            "work_order",
            w,
            w["obligation_atoms"],
            w["unit"],
            p["unit_scale"],
            w["source_external_id"],
            p["customer_id"],
            "registered",
        )
    for u in tx.execute(
        "SELECT u.* FROM units u WHERE u.project_id=? AND u.revision_id=?", (pid, rid)
    ):
        add("unit", u, 1, p["unit_code"], 0, u["sn"], p["customer_id"], u["state"])
        if u["accepted_start_id"]:
            add("wip", u, 1, p["unit_code"], 0, u["sn"], p["customer_id"], u["state"])
    for c in tx.execute(
        """SELECT c.*,r.scale FROM supply_commitments c JOIN requirements r ON r.id=c.requirement_id AND r.project_id=c.project_id JOIN work_orders w ON w.id=r.work_order_id AND w.project_id=r.project_id WHERE w.project_id=? AND w.revision_id=?""",
        (pid, rid),
    ):
        received = tx.execute(
            "SELECT COALESCE(SUM(q_atoms),0) FROM effective_supply_receipts WHERE project_id=? AND commitment_id=?",
            (pid, c["id"]),
        ).fetchone()[0]
        add(
            "purchase",
            c,
            max(0, c["current_q_atoms"] - received),
            c["unit"],
            c["scale"],
            json.loads(c["source_json"])["external_id"],
            c["owner_id"],
            c["type"],
        )
    for lot in stock_lots(tx, pid, rid):
        basis, complete, unknown = stock_evidence(tx, pid, lot)
        consumed = tx.execute(
            "SELECT COALESCE(SUM(q_atoms),0) FROM material_consumption WHERE project_id=? AND lot_id=?",
            (pid, lot["id"]),
        ).fetchone()[0]
        gross = max(sum(basis.values()), unknown)
        count = len(result)
        add(
            "stock",
            lot,
            max(0, gross - consumed),
            lot["unit"],
            lot["scale"],
            lot["lot_id"],
            lot["owner_id"],
            lot["state"],
        )
        if len(result) > count:
            result[-1].stock_basis = {
                key: Decimal(material_amount(q, lot["scale"]))
                for key, q in basis.items()
            }
            result[-1].opening_consumption = Decimal(
                material_amount(consumed, lot["scale"])
            )
            result[-1].stock_basis_complete = complete
    return result


def eco_impacts(tx, pid, row):
    # Retain original snapshots. New/grown physical facts are new explicit obligations.
    saved = [
        EcoImpact.model_validate_json(r[0])
        for r in tx.execute(
            "SELECT payload_json FROM eco_impacts WHERE project_id=? AND eco_id=?",
            (str(pid), row["id"]),
        )
    ]
    totals = {}
    covered = {}
    for opening in tx.execute(
        "SELECT * FROM eco_stock_openings WHERE project_id=? AND eco_id=?",
        (str(pid), row["id"]),
    ):
        for source, q in json.loads(opening["basis_json"]).items():
            covered[(UUID(opening["lot_id"]), source)] = q
    for prior in saved:
        key = (prior.type, prior.object_id)
        totals[key] = totals.get(key, Decimal(0)) + prior.quantity
        if prior.type == "stock":
            for source, quantity in (prior.stock_basis or {}).items():
                q = material_atoms(quantity, prior.unit, prior.unit, prior.scale)
                covered[(prior.object_id, source)] = max(
                    covered.get((prior.object_id, source), 0), q
                )
    if row["state"] == "open":
        for current in impacts(tx, pid, row["old_revision_id"]):
            if current.type == "stock":
                continue
            current.id = uuid5(UUID(row["id"]), str(current.id))
            prior_total = totals.get((current.type, current.object_id), Decimal(0))
            if current.quantity > prior_total:
                current.quantity -= prior_total
                saved.append(current)
        for lot in stock_lots(tx, pid, row["old_revision_id"]):
            basis, complete, _unknown = stock_evidence(tx, pid, lot)
            additions = {
                key: q - covered.get((UUID(lot["id"]), key), 0)
                for key, q in basis.items()
                if q > covered.get((UUID(lot["id"]), key), 0)
            }
            if additions:
                saved.append(
                    EcoImpact(
                        id=uuid5(
                            UUID(row["id"]),
                            lot["id"] + json.dumps(basis, sort_keys=True),
                        ),
                        type="stock",
                        object_id=lot["id"],
                        title=lot["lot_id"],
                        owner_id=lot["owner_id"],
                        quantity=material_amount(sum(additions.values()), lot["scale"]),
                        unit=lot["unit"],
                        scale=lot["scale"],
                        state=lot["state"],
                        stock_basis={
                            key: material_amount(q, lot["scale"])
                            for key, q in basis.items()
                        },
                        stock_basis_complete=complete,
                    )
                )
            if not complete:
                for old in saved:
                    if old.type == "stock" and str(old.object_id) == lot["id"]:
                        old.stock_basis_complete = False
    for i in saved:
        entries = tx.execute(
            "SELECT * FROM eco_dispositions WHERE project_id=? AND eco_id=? AND impact_id=? ORDER BY created_at,id",
            (str(pid), row["id"], str(i.id)),
        ).fetchall()
        i.dispositions = [
            EcoDisposition(
                id=e["id"],
                decision=e["decision"],
                quantity=material_amount(e["q_atoms"], i.scale),
                evidence=e["evidence"],
            )
            for e in entries
        ]
        i.resolved_quantity = Decimal(
            material_amount(sum(e["q_atoms"] for e in entries), i.scale)
        )
    return saved


def save_impacts(tx, pid, eco_id, values):
    for i in values:
        base = i.model_copy(
            update={"dispositions": [], "resolved_quantity": Decimal(0)}
        )
        tx.execute(
            "INSERT OR IGNORE INTO eco_impacts VALUES (?,?,?,?)",
            (str(i.id), str(pid), str(eco_id), base.model_dump_json()),
        )


def open_eco(tx, context, command):
    own(tx, "engineering_revisions", context.project_id, command.old_revision_id)
    if command.new_revision_id:
        own(tx, "engineering_revisions", context.project_id, command.new_revision_id)
    wids = set(map(str, command.effective_work_order_ids))
    for uid in command.effective_sn_ids:
        u = own(tx, "units", context.project_id, uid)
        if u["revision_id"] != str(command.old_revision_id):
            fail("serial boundary differs from old revision")
        wids.add(u["work_order_id"])
    for wid in wids:
        w = own(tx, "work_orders", context.project_id, wid)
        if w["revision_id"] != str(command.old_revision_id):
            fail("work order boundary differs from old revision")
    ident = uuid4()
    tx.execute(
        "INSERT INTO eco_changes VALUES (?,?,?,?,?,?,?,'open',?)",
        (
            str(ident),
            str(context.project_id),
            str(command.old_revision_id),
            str(command.new_revision_id) if command.new_revision_id else None,
            json.dumps(sorted(wids)),
            json.dumps(list(map(str, command.effective_sn_ids))),
            command.reason,
            context.now.isoformat(),
        ),
    )
    for lot in stock_lots(tx, context.project_id, command.old_revision_id):
        basis, complete, _unknown = stock_evidence(tx, context.project_id, lot)
        consumed = tx.execute(
            "SELECT COALESCE(SUM(q_atoms),0) FROM material_consumption WHERE project_id=? AND lot_id=?",
            (str(context.project_id), lot["id"]),
        ).fetchone()[0]
        tx.execute(
            "INSERT INTO eco_stock_openings VALUES (?,?,?,?,?,?)",
            (
                str(ident),
                str(context.project_id),
                lot["id"],
                json.dumps(basis, sort_keys=True),
                consumed,
                int(complete),
            ),
        )
    initial = impacts(tx, context.project_id, command.old_revision_id)
    for i in initial:
        i.id = uuid5(ident, str(i.id))
    save_impacts(tx, context.project_id, ident, initial)
    return MutationResult(object_type="eco", object_id=ident)


def open_row(tx, pid, ident):
    row = own(tx, "eco_changes", pid, ident)
    if row["state"] != "open":
        fail("ECO is closed")
    return row


def dispose(tx, context, command):
    row = open_row(tx, context.project_id, command.eco_id)
    values = eco_impacts(tx, context.project_id, row)
    impact = next((i for i in values if i.id == command.impact_id), None)
    if not impact:
        fail("impact outside ECO", "NOT_FOUND", 404)
    q = material_atoms(command.quantity, impact.unit, impact.unit, impact.scale)
    if command.quantity + impact.resolved_quantity > impact.quantity:
        fail("disposition exceeds unresolved impact quantity")
    save_impacts(tx, context.project_id, row["id"], values)
    tx.execute(
        "INSERT INTO eco_dispositions VALUES (?,?,?,?,?,?,?,?)",
        (
            str(uuid4()),
            str(context.project_id),
            row["id"],
            str(impact.id),
            q,
            command.decision,
            command.evidence,
            context.now.isoformat(),
        ),
    )
    return MutationResult(object_type="eco", object_id=command.eco_id)


def revision_ready(tx, pid, revision_id):
    rev = fixed_revision(tx, pid, revision_id)
    handoff = tx.execute(
        "SELECT * FROM handoffs WHERE project_id=? AND revision_id=? AND to_system='MES' ORDER BY rowid DESC LIMIT 1",
        (str(pid), str(revision_id)),
    ).fetchone()
    if (
        not handoff
        or handoff["status"] != "verified"
        or handoff["received_revision"] != rev.internal_revision
    ):
        fail("new revision requires matching MES handoff")
    p = project(tx, pid)
    contract = json.loads(p["contract_json"])
    if contract["customer_approval_required"] is not False:
        approval = tx.execute(
            "SELECT * FROM customer_approvals WHERE project_id=? AND revision_id=? ORDER BY accepted_seq DESC LIMIT 1",
            (str(pid), str(revision_id)),
        ).fetchone()
        if (
            contract["customer_approval_required"] is not True
            or contract["customer_revision"] != rev.customer_revision
            or not approval
            or approval["decision"] != "approved"
            or approval["customer_id"] != p["customer_id"]
        ):
            fail("new revision customer approval or contract is unknown or missing")


def accepted_membership(tx, pid, wid):
    if tx.execute(
        "SELECT 1 FROM start_requests s JOIN exchanges e ON e.id=s.exchange_id WHERE s.project_id=? AND s.work_order_id=? AND s.accepted_receipt_id IS NULL AND (e.phase!='rejected' OR e.receipt_json IS NULL)",
        (str(pid), str(wid)),
    ).fetchone():
        fail("unresolved physical start membership prevents retained approval")
    return [
        r[0]
        for r in tx.execute(
            "SELECT u.id FROM units u JOIN start_requests s ON s.id=u.accepted_start_id AND s.project_id=u.project_id WHERE u.project_id=? AND u.work_order_id=? AND s.accepted_receipt_id IS NOT NULL ORDER BY u.id",
            (str(pid), str(wid)),
        )
    ]


def verify_retention(tx, pid, row, wid, quantity, evidence_ids=None):
    wo = own(tx, "work_orders", pid, wid)
    ids = accepted_membership(tx, pid, wid)
    scale = 10 ** project(tx, pid)["unit_scale"]
    if (
        scope_locked(tx, pid, wid)
        or quantity != wo["q_atoms"]
        or len(ids) * scale != quantity
        or (evidence_ids is not None and ids != evidence_ids)
    ):
        fail(
            "retained boundary must exactly cover current accepted original membership"
        )
    relevant = [
        i
        for i in eco_impacts(tx, pid, row)
        if (i.type == "work_order" and str(i.object_id) == str(wid))
        or (i.type in {"unit", "wip"} and str(i.object_id) in ids)
    ]
    if not relevant or any(
        i.quantity != i.resolved_quantity
        or any(d.decision != "use_old" for d in i.dispositions)
        for i in relevant
    ):
        fail(
            "complete old-use dispositions required for retained WO and accepted SN/WIP"
        )
    return ids


def retain(tx, context, command, row):
    p = project(tx, context.project_id)
    q = material_atoms(
        command.retained_quantity, p["unit_code"], p["unit_code"], p["unit_scale"]
    )
    ids = verify_retention(tx, context.project_id, row, command.target_work_order_id, q)
    if tx.execute(
        "SELECT 1 FROM eco_retentions WHERE eco_id=? AND work_order_id=?",
        (row["id"], str(command.target_work_order_id)),
    ).fetchone():
        fail("retained boundary already recorded")
    tx.execute(
        "INSERT INTO eco_retentions VALUES (?,?,?,?,?,?,?)",
        (
            row["id"],
            str(context.project_id),
            str(command.target_work_order_id),
            q,
            json.dumps(ids),
            command.evidence,
            context.now.isoformat(),
        ),
    )
    return MutationResult(object_type="eco", object_id=command.eco_id)


def uncertain_stock(tx, pid, row, values):
    ids = {
        str(i.id)
        for i in values
        if i.type == "stock" and (i.stock_basis is None or not i.stock_basis_complete)
    }
    ids.update(
        r[0]
        for r in tx.execute(
            "SELECT lot_id FROM eco_stock_openings WHERE eco_id=? AND complete=0",
            (row["id"],),
        )
    )
    if row["state"] == "open":
        ids.update(
            lot["id"]
            for lot in stock_lots(tx, pid, row["old_revision_id"])
            if not stock_evidence(tx, pid, lot)[1]
        )
    return sorted(ids)


def close(tx, context, command):
    row = open_row(tx, context.project_id, command.eco_id)
    values = eco_impacts(tx, context.project_id, row)
    uncertain = uncertain_stock(tx, context.project_id, row, values)
    unresolved = [str(i.id) for i in values if i.resolved_quantity != i.quantity]
    if uncertain:
        raise DomainError(
            "PRECONDITION_FAILED",
            409,
            "Stock evidence overlap requires authoritative source reconciliation",
            fields={
                "unresolved_stock_basis_ids": uncertain,
                "unresolved_impact_ids": unresolved,
            },
        )
    if unresolved:
        raise DomainError(
            "PRECONDITION_FAILED",
            409,
            "Unresolved ECO impacts",
            fields={"unresolved_impact_ids": unresolved},
        )
    switched = {
        r[0]
        for r in tx.execute(
            "SELECT work_order_id FROM eco_switches WHERE project_id=? AND eco_id=? AND accepted_receipt_id IS NOT NULL",
            (str(context.project_id), row["id"]),
        )
    }
    retained = set()
    for proof in tx.execute(
        "SELECT * FROM eco_retentions WHERE project_id=? AND eco_id=?",
        (str(context.project_id), row["id"]),
    ):
        verify_retention(
            tx,
            context.project_id,
            row,
            proof["work_order_id"],
            proof["q_atoms"],
            json.loads(proof["unit_ids_json"]),
        )
        retained.add(proof["work_order_id"])
    if not set(json.loads(row["work_order_ids_json"])) <= switched | retained:
        fail(
            "every selected work order requires actual switch or cancellation receipts"
        )
    if row["new_revision_id"] and switched:
        revision_ready(tx, context.project_id, row["new_revision_id"])
    save_impacts(tx, context.project_id, row["id"], values)
    tx.execute("UPDATE eco_changes SET state='closed' WHERE id=?", (row["id"],))
    return MutationResult(object_type="eco", object_id=command.eco_id)


def summary(row):
    return ObjectSummary(
        id=row["id"],
        project_id=row["project_id"],
        kind="eco",
        title=f"ECO · {row['reason']}",
        state=row["state"],
        version=1,
        next_actions=["eco.disposition", "eco.switch", "eco.close"]
        if row["state"] == "open"
        else [],
    )


def page(tx, pid, limit, offset):
    return [
        summary(r)
        for r in tx.execute(
            "SELECT * FROM eco_changes WHERE project_id=? ORDER BY created_at,id LIMIT ? OFFSET ?",
            (str(pid), limit, offset),
        )
    ]


def detail(tx, pid, ident):
    row = tx.execute(
        "SELECT * FROM eco_changes WHERE project_id=? AND id=?", (str(pid), str(ident))
    ).fetchone()
    if not row:
        return None
    p = project(tx, pid)
    switches = [
        {
            "id": r["id"],
            "work_order_id": r["work_order_id"],
            "new_work_order_id": r["new_work_order_id"],
            "boundary": r["boundary"],
            "quantity": amount(r["q_atoms"], p),
            "retained_quantity": amount(r["retained_atoms"], p),
            "exchange_id": r["exchange_id"],
            "phase": r["phase"],
        }
        for r in tx.execute(
            "SELECT s.*,e.phase FROM eco_switches s JOIN exchanges e ON e.id=s.exchange_id WHERE s.project_id=? AND s.eco_id=? ORDER BY s.created_at,s.id",
            (str(pid), row["id"]),
        )
    ]
    retentions = [
        {
            "work_order_id": r["work_order_id"],
            "quantity": amount(r["q_atoms"], p),
            "unit_ids": json.loads(r["unit_ids_json"]),
            "evidence": r["evidence"],
        }
        for r in tx.execute(
            "SELECT * FROM eco_retentions WHERE project_id=? AND eco_id=? ORDER BY work_order_id",
            (str(pid), row["id"]),
        )
    ]
    outcomes = ({"retained"} if retentions else set()) | {
        "switched" if item["boundary"] == "split_remaining" else "cancelled"
        for item in switches
        if item["phase"] == "accepted"
    }
    value = EcoValue(
        id=ident,
        old_revision_id=row["old_revision_id"],
        new_revision_id=row["new_revision_id"],
        old_revision=fixed_revision(tx, pid, row["old_revision_id"]).internal_revision,
        new_revision=fixed_revision(tx, pid, row["new_revision_id"]).internal_revision
        if row["new_revision_id"]
        else None,
        effective_work_order_ids=json.loads(row["work_order_ids_json"]),
        effective_sn_ids=json.loads(row["sn_ids_json"]),
        reason=row["reason"],
        state=row["state"],
        impacts=eco_impacts(tx, pid, row),
        switches=switches,
        retentions=retentions,
        unresolved_stock_basis_ids=uncertain_stock(
            tx, pid, row, eco_impacts(tx, pid, row)
        ),
        implementation_outcome=next(iter(outcomes))
        if len(outcomes) == 1
        else "mixed"
        if outcomes
        else "pending",
    )
    return ObjectDetail[EcoValue](
        summary=summary(row),
        value=value,
        relations=[],
        evidence=[ObjectEvidence(reference=row["reason"])],
        history=_history(tx, pid, ident),
    )


for model, handler in ((OpenEco, open_eco), (DisposeEco, dispose), (CloseEco, close)):
    COMMAND_REGISTRY.register(
        model, roles={"engineering"}, qualifications=set(), handler=handler
    )
OBJECT_REGISTRY.register(
    "eco", EcoValue, count=count("eco_changes"), summaries=page, detail=detail
)


def scope_locked(tx, pid, wid):
    return bool(
        tx.execute(
            """SELECT 1 FROM eco_switches s JOIN exchanges e ON e.id=s.exchange_id WHERE s.project_id=? AND s.work_order_id=? AND (s.accepted_receipt_id IS NOT NULL OR e.phase!='rejected' OR e.receipt_json IS NULL) LIMIT 1""",
            (str(pid), str(wid)),
        ).fetchone()
    )


def switch(tx, context, command):
    from .exchange_models import EcoSwitchPayload, ExternalRequest

    row = open_row(tx, context.project_id, command.eco_id)
    wo = own(tx, "work_orders", context.project_id, command.target_work_order_id)
    if wo["id"] not in json.loads(row["work_order_ids_json"]):
        fail("work order outside explicit ECO boundary")
    if command.boundary == "retain_existing":
        return retain(tx, context, command, row)
    if tx.execute(
        "SELECT 1 FROM eco_retentions WHERE eco_id=? AND work_order_id=?",
        (row["id"], wo["id"]),
    ).fetchone():
        fail("retained boundary cannot be overwritten by a switch")
    if scope_locked(tx, context.project_id, wo["id"]):
        fail("remaining scope already switched or awaiting authoritative result")
    if tx.execute(
        """SELECT 1 FROM start_requests s JOIN exchanges e ON e.id=s.exchange_id WHERE s.project_id=? AND s.work_order_id=? AND s.accepted_receipt_id IS NULL AND (e.phase!='rejected' OR e.receipt_json IS NULL) LIMIT 1""",
        (str(context.project_id), wo["id"]),
    ).fetchone():
        fail("unresolved physical start scope must be reconciled before cancellation")
    if command.boundary == "split_remaining":
        if row["new_revision_id"] != str(command.new_revision_id):
            fail("split revision differs from approved ECO target")
        revision_ready(tx, context.project_id, command.new_revision_id)
    retained = [
        r[0]
        for r in tx.execute(
            "SELECT u.id FROM units u JOIN start_requests s ON s.id=u.accepted_start_id AND s.project_id=u.project_id WHERE u.project_id=? AND u.work_order_id=? AND s.accepted_receipt_id IS NOT NULL ORDER BY u.id",
            (str(context.project_id), wo["id"]),
        )
    ]
    p = project(tx, context.project_id)
    scale = 10 ** p["unit_scale"]
    if wo["q_atoms"] % scale or wo["trial_q_atoms"] % scale:
        fail("ECO scope must be whole serialized products")
    total, trial = wo["q_atoms"] // scale, wo["trial_q_atoms"] // scale
    remaining = total - len(retained)
    if remaining <= 0:
        fail("no unstarted remaining scope to switch")
    # A serial-only boundary must explicitly cover every cancelled registered SN.
    selected = set(json.loads(row["sn_ids_json"]))
    if selected:
        unstarted = {
            r[0]
            for r in tx.execute(
                "SELECT id FROM units WHERE project_id=? AND work_order_id=? AND accepted_start_id IS NULL",
                (str(context.project_id), wo["id"]),
            )
        }
        if not unstarted <= selected:
            fail("serial boundary does not cover all remaining registered scope")
        if selected.intersection(retained):
            fail("executed serials cannot cross a revision boundary")
    sid, eid = uuid4(), uuid4()
    new_id = uuid4() if command.boundary == "split_remaining" else None
    payload = EcoSwitchPayload(
        switch_id=sid,
        eco_id=command.eco_id,
        work_order_id=command.target_work_order_id,
        old_revision_id=UUID(wo["revision_id"]),
        new_revision_id=command.new_revision_id,
        new_work_order_id=new_id,
        boundary=command.boundary,
        original_quantity=total,
        original_trial_quantity=trial,
        remaining_quantity=remaining,
        retained_unit_ids=retained,
        new_trial_quantity=min(trial, remaining) if new_id else 0,
    )
    request = ExternalRequest(
        id=eid,
        system="erp",
        action="eco.switch",
        business_key=str(eid),
        source_version=1,
        project_id=context.project_id,
        typed_payload=payload,
    )
    context.exchange_service.prepare(tx, context, request)
    tx.execute(
        "INSERT INTO eco_switches VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?)",
        (
            str(sid),
            str(context.project_id),
            row["id"],
            wo["id"],
            str(new_id) if new_id else None,
            str(command.new_revision_id) if command.new_revision_id else None,
            command.boundary,
            remaining * scale,
            len(retained) * scale,
            str(eid),
            context.now.isoformat(),
        ),
    )
    return MutationResult(
        object_type="work_order" if new_id else "eco",
        object_id=new_id or command.eco_id,
        exchange_id=eid,
    )


def switch_receipt_details(payload):
    values = [
        {
            "key": str(payload.switch_id) + ":cancel",
            "effect": "cancel_remaining",
            "work_order_id": payload.work_order_id,
            "revision_id": payload.old_revision_id,
            "quantity": str(payload.remaining_quantity),
            "retained_quantity": str(len(payload.retained_unit_ids)),
        }
    ]
    if payload.new_work_order_id:
        values.append(
            {
                "key": str(payload.switch_id) + ":create",
                "effect": "create_replacement",
                "work_order_id": payload.new_work_order_id,
                "revision_id": payload.new_revision_id,
                "quantity": str(payload.remaining_quantity),
                "retained_quantity": "0",
            }
        )
    return values


def receipt_scope(tx, row, receipt):
    from .exchange_models import EcoReceiptDetail, ExternalRequest

    payload = ExternalRequest.model_validate_json(row["request_json"]).typed_payload
    scoped = tx.execute(
        "SELECT 1 FROM eco_switches WHERE id=? AND project_id=? AND work_order_id=? AND exchange_id=?",
        (
            str(payload.switch_id),
            row["project_id"],
            str(payload.work_order_id),
            row["id"],
        ),
    ).fetchone()
    details = [
        EcoReceiptDetail(**d).model_dump(mode="json")
        for d in switch_receipt_details(payload)
    ]
    return (
        bool(scoped)
        and receipt.business_key == row["business_key"]
        and receipt.request_hash == row["request_hash"]
        and receipt.source_object_id == str(payload.switch_id)
        and (
            not receipt.details
            if receipt.phase == "rejected"
            else [d.model_dump(mode="json") for d in receipt.details] == details
        )
        and not tx.execute(
            "SELECT 1 FROM exchange_receipts WHERE receipt_id=? AND exchange_id<>? AND valid=1",
            (str(receipt.receipt_id), row["id"]),
        ).fetchone()
    )


def apply_switch(service, tx, context, row, request, receipt):
    from .exchanges import event

    payload = request.typed_payload
    if row["receipt_json"] == receipt.model_dump_json() and row["phase"] in {
        "accepted",
        "rejected",
    }:
        return MutationResult(
            object_type="exchange",
            object_id=UUID(row["id"]),
            exchange_id=UUID(row["id"]),
        )
    valid = (
        receipt.source_version == request.source_version
        and receipt.sequence > row["source_sequence"]
        and receipt.sequence > 0
        and (receipt.occurred_at - context.now).total_seconds() <= 300
    )
    valid = (
        valid
        and receipt.phase in {"accepted", "rejected"}
        and receipt.accepted_quantity + receipt.rejected_quantity
        == payload.remaining_quantity
        and receipt.accepted_quantity
        == (payload.remaining_quantity if receipt.phase == "accepted" else 0)
    )
    tx.execute(
        "INSERT OR IGNORE INTO exchange_receipts(exchange_id,project_id,receipt_id,payload_json,valid,reason) VALUES (?,?,?,?,?,?)",
        (
            row["id"],
            str(context.project_id),
            str(receipt.receipt_id),
            receipt.model_dump_json(),
            int(valid),
            "" if valid else "ECO receipt conservation or sequence mismatch",
        ),
    )
    if not valid:
        service._reject(
            tx, context, row, "ECO receipt conservation or sequence mismatch"
        )
    elif receipt.phase == "rejected":
        service._reject(tx, context, row, "Authority rejected ECO boundary")
        tx.execute(
            "UPDATE exchanges SET receipt_json=?,source_sequence=? WHERE id=?",
            (receipt.model_dump_json(), receipt.sequence, row["id"]),
        )
    else:
        s = own(tx, "eco_switches", context.project_id, payload.switch_id)
        if s["accepted_receipt_id"]:
            fail("switch already applied")
        wo = own(tx, "work_orders", context.project_id, payload.work_order_id)
        allocated_atoms = allocated(tx, context.project_id, work_order_id=wo["id"])
        transfer = max(0, allocated_atoms - s["retained_atoms"])
        if payload.new_work_order_id:
            source = {
                "system": request.system,
                "object_type": "work_order",
                "external_id": str(payload.new_work_order_id),
                "version": receipt.source_version,
                "mode": row["mode"],
                "occurred_at": receipt.occurred_at.isoformat(),
                "collected_at": context.now.isoformat(),
                "cutoff": receipt.occurred_at.isoformat(),
                "evidence": f"Authority ECO creation receipt {receipt.receipt_id}",
            }
            scale = 10 ** project(tx, context.project_id)["unit_scale"]
            tx.execute(
                "INSERT INTO work_orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(payload.new_work_order_id),
                    str(context.project_id),
                    wo["order_line_id"],
                    str(payload.new_revision_id),
                    s["q_atoms"],
                    wo["unit"],
                    wo["purpose"],
                    payload.new_trial_quantity * scale,
                    request.system,
                    "work_order",
                    str(payload.new_work_order_id),
                    receipt.source_version,
                    json.dumps(source),
                    wo["planned_start"],
                    wo["planned_end"],
                ),
            )
        if transfer:
            tx.execute(
                "INSERT INTO allocation_adjustments VALUES (?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    str(context.project_id),
                    wo["order_line_id"],
                    wo["id"],
                    -transfer,
                    s["id"],
                ),
            )
            if payload.new_work_order_id:
                tx.execute(
                    "INSERT INTO allocation_adjustments VALUES (?,?,?,?,?,?)",
                    (
                        str(uuid4()),
                        str(context.project_id),
                        wo["order_line_id"],
                        str(payload.new_work_order_id),
                        transfer,
                        s["id"],
                    ),
                )
        tx.execute(
            "UPDATE eco_switches SET accepted_receipt_id=? WHERE id=?",
            (str(receipt.receipt_id), s["id"]),
        )
        tx.execute(
            "UPDATE exchanges SET phase='accepted',reason='',receipt_json=?,source_sequence=? WHERE id=?",
            (receipt.model_dump_json(), receipt.sequence, row["id"]),
        )
        event(
            tx,
            row,
            "accepted",
            "Authority cancellation and creation verified; local obligations transferred atomically",
            receipt.model_dump(mode="json"),
        )
    return MutationResult(
        object_type="exchange", object_id=UUID(row["id"]), exchange_id=UUID(row["id"])
    )


COMMAND_REGISTRY.register(
    SwitchEco, roles={"engineering"}, qualifications=set(), handler=switch
)
