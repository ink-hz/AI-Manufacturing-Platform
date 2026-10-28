"""Actual material movement evidence; reconciliation never creates inventory."""

import json
from decimal import Decimal
from uuid import UUID, uuid4

from .commands import COMMAND_REGISTRY
from .contracts import MutationResult
from .delivery import fail
from .delivery_models import (
    MaterialMovement,
    OwnershipBalance,
    OwnershipReconcile,
    OwnershipSourceRecord,
)
from .exchange_models import ExternalReceipt
from .imports import admit_records
from .orders import own, source_key
from .supply import atoms


def amount(value, scale):
    return format(Decimal(value).scaleb(-scale), f".{scale}f")


def balance(tx, pid, lot) -> OwnershipBalance:
    from .eco import stock_evidence
    from .exchanges import receipt_scope

    evidence, complete, _unknown = stock_evidence(tx, pid, lot)
    # Accepted basis admits physical source quantity, not only its reserved portion.
    for row in tx.execute(
        "SELECT e.* FROM reservations r JOIN exchanges e ON e.id=r.exchange_id WHERE r.project_id=? AND r.material_lot_id=? AND r.authority_receipt_id IS NOT NULL",
        (str(pid), lot["id"]),
    ):
        receipt = ExternalReceipt.model_validate_json(row["receipt_json"])
        if receipt.details[0].stock_basis is None:
            from .stock_proofs import recovered_receipt

            original_request = json.loads(row["request_json"])
            receipt = (
                recovered_receipt(
                    tx, pid, original_request["typed_payload"]["reservation_id"]
                )
                or receipt
            )
        if not receipt_scope(tx, row, receipt):
            complete = False
            continue
        for basis in receipt.details[0].stock_basis or []:
            key = json.dumps(
                ["receipt", basis.system.strip().casefold(), basis.external_id.strip()],
                separators=(",", ":"),
            )
            evidence[key] = max(
                evidence.get(key, 0),
                atoms(basis.source_quantity, basis.unit, lot["unit"], lot["scale"]),
            )
    received = sum(evidence.values())
    consumed = tx.execute(
        "SELECT COALESCE(SUM(q_atoms),0) FROM material_consumption WHERE project_id=? AND lot_id=?",
        (str(pid), lot["id"]),
    ).fetchone()[0]
    movements = {
        r[0]: r[1]
        for r in tx.execute(
            "SELECT movement,SUM(q_atoms) FROM effective_material_movements WHERE project_id=? AND material_lot_id=? GROUP BY movement",
            (str(pid), lot["id"]),
        )
    }
    returned, scrapped = movements.get("return", 0), movements.get("raw_loss", 0)
    residual = received - consumed - returned - scrapped
    return OwnershipBalance(
        **{
            key: amount(value, lot["scale"])
            for key, value in dict(
                received=received,
                consumed=consumed,
                returned=returned,
                scrapped=scrapped,
                balance=max(0, residual),
            ).items()
        },
        complete=complete and residual >= 0,
        unit=lot["unit"],
        owner_id=lot["owner_id"],
        material_id=lot["material_id"],
    )


def scope(tx, context, command, kind):
    lot = own(tx, "material_lots", context.project_id, command.material_lot_id)
    if (command.material_id, command.owner_id, command.unit) != (
        lot["material_id"],
        lot["owner_id"],
        lot["unit"],
    ):
        fail("Material movement identity/ownership/unit differs from the actual lot")
    record = OwnershipSourceRecord(
        project_id=context.project_id,
        object_type=kind,
        material_lot_id=command.material_lot_id,
        source=command.source,
    )
    admit_records(tx, context, [record], object_type=kind, trusted=False)
    if command.source.mode != "manual":
        fail("Actual movement and reconciliation require explicit manual provenance")
    table = (
        "material_movements"
        if kind == "material_movement"
        else "ownership_reconciliations"
    )
    if tx.execute(
        f"SELECT 1 FROM {table} WHERE source_system=? AND source_type=? AND source_external_id=?",
        source_key(command.source),
    ).fetchone():
        fail("Movement source identity already recorded")
    return lot


def move(tx, context, command):
    lot = scope(tx, context, command, "material_movement")
    q = atoms(command.quantity, command.unit, lot["unit"], lot["scale"])
    previous = 0
    if command.supersedes_id:
        old = own(tx, "material_movements", context.project_id, command.supersedes_id)
        if (
            old["material_lot_id"] != lot["id"]
            or old["movement"] != command.movement
            or tx.execute(
                "SELECT 1 FROM material_movements WHERE supersedes_id=?", (old["id"],)
            ).fetchone()
        ):
            fail("Correction must supersede the current same-lot movement")
        old_source = json.loads(old["source_json"])
        from datetime import datetime

        if command.source.occurred_at < datetime.fromisoformat(
            old_source["occurred_at"]
        ):
            fail("Movement correction predates the original evidence")
        previous = old["q_atoms"]
    current = balance(tx, context.project_id, lot)
    if (
        not current.complete
        or q > atoms(current.balance, lot["unit"], lot["unit"], lot["scale"]) + previous
    ):
        fail(
            "Actual raw movement exceeds unconsumed physical material; product scrap is already consumed"
        )
    ident = uuid4()
    tx.execute(
        "INSERT INTO material_movements(id,project_id,material_lot_id,movement,q_atoms,supersedes_id,source_system,source_type,source_external_id,source_json,external_signatory,evidence,actor_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            str(ident),
            str(context.project_id),
            lot["id"],
            command.movement,
            q,
            str(command.supersedes_id) if command.supersedes_id else None,
            *source_key(command.source),
            command.source.model_dump_json(),
            command.external_signatory,
            command.evidence,
            str(context.actor.user_id),
            context.now.isoformat(),
        ),
    )
    return MutationResult(object_type="material_lot", object_id=UUID(lot["id"]))


def reconcile(tx, context, command):
    lot = scope(tx, context, command, "ownership")
    current = balance(tx, context.project_id, lot)
    differences = {
        key: {
            "claimed": str(getattr(command, key)),
            "actual": str(getattr(current, key)),
        }
        for key in ("received", "consumed", "scrapped", "returned", "balance")
        if getattr(command, key) != getattr(current, key)
    }
    if differences or not current.complete:
        from .contracts import DomainError

        raise DomainError(
            "PRECONDITION_FAILED",
            409,
            "Ownership reconciliation differs from actual admitted movements",
            fields={"differences": differences, "source_complete": current.complete},
        )
    ident = uuid4()
    tx.execute(
        "INSERT INTO ownership_reconciliations(id,project_id,material_lot_id,balance_json,source_system,source_type,source_external_id,source_json,actor_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            str(ident),
            str(context.project_id),
            lot["id"],
            current.model_dump_json(),
            *source_key(command.source),
            command.source.model_dump_json(),
            str(context.actor.user_id),
            context.now.isoformat(),
        ),
    )
    return MutationResult(object_type="material_lot", object_id=UUID(lot["id"]))


for model, handler in [(MaterialMovement, move), (OwnershipReconcile, reconcile)]:
    COMMAND_REGISTRY.register(
        model, roles={"supply"}, qualifications=set(), handler=handler
    )


def material_hold(tx, pid, lot):
    """Actual movements never silently release still-accepted authority claims."""
    from .freeze import lot_hold
    containment = lot_hold(tx, pid, lot["id"])
    if containment:
        return containment
    if not tx.execute(
        "SELECT 1 FROM material_movements WHERE project_id=? AND material_lot_id=? LIMIT 1",
        (str(pid), lot["id"]),
    ).fetchone():
        return None
    current = balance(tx, pid, lot)
    reserved = tx.execute(
        "SELECT COALESCE(SUM(confirmed_atoms),0) FROM reservations WHERE project_id=? AND material_lot_id=? AND authority_receipt_id IS NOT NULL",
        (str(pid), lot["id"]),
    ).fetchone()[0]
    consumed = atoms(current.consumed, lot["unit"], lot["unit"], lot["scale"])
    if not current.complete or atoms(
        current.balance, lot["unit"], lot["unit"], lot["scale"]
    ) < max(0, reserved - consumed):
        return "Actual return/raw loss conflicts with held authority reservations; supply owner must obtain real source release and replan"
    return None


def admitted_source(tx, pid, row, kind):
    from datetime import datetime
    from types import SimpleNamespace

    from pydantic import ValidationError

    from .contracts import DomainError, SourceRef
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
        record = OwnershipSourceRecord(
            project_id=row["project_id"],
            source=source,
            material_lot_id=row["material_lot_id"],
            object_type=kind,
        )
        record_scope(tx, pid, record, object_type=kind)
        validate_record(
            record,
            SimpleNamespace(
                project_id=UUID(str(pid)), now=datetime.fromisoformat(row["created_at"])
            ),
            trusted=False,
        )
        return source
    except (DomainError, ValidationError, ValueError, KeyError, TypeError):
        return None


def audit_evidence(tx, pid, object_id, audit, payload):
    """Project ownership audit evidence only from its original admitted fact."""
    from datetime import datetime
    from hashlib import sha256

    from pydantic import ValidationError

    from .contracts import DomainError, ObjectEvidence
    from .orders import _audit_evidence

    source_type = (
        (payload.get("source") or {}).get("object_type")
        if isinstance(payload.get("source"), dict)
        else None
    )
    owned = (
        str(audit["action"]).startswith("ownership.")
        or str(payload.get("action", "")).startswith("ownership.")
        or source_type in {"material_movement", "ownership"}
    )
    if not owned:
        return _audit_evidence(payload)
    models = {
        "ownership.movement": MaterialMovement,
        "ownership.reconcile": OwnershipReconcile,
    }
    if audit["action"] not in models:
        return []
    try:
        if (
            payload.get("project_id") != str(pid)
            or audit["project_id"] != str(pid)
            or audit["object_id"] != str(object_id)
        ):
            return []
        command = models[audit["action"]].model_validate(
            {k: v for k, v in payload.items() if k != "project_id"}
        )
        if str(command.material_lot_id) != str(object_id):
            return []
        lot = own(tx, "material_lots", pid, command.material_lot_id)
        if (command.material_id, command.owner_id, command.unit) != (
            lot["material_id"],
            lot["owner_id"],
            lot["unit"],
        ):
            return []
        movement = isinstance(command, MaterialMovement)
        table = "material_movements" if movement else "ownership_reconciliations"
        fact = tx.execute(
            f"SELECT * FROM {table} WHERE project_id=? AND material_lot_id=? AND source_system=? AND source_type=? AND source_external_id=?",
            (str(pid), str(object_id), *source_key(command.source)),
        ).fetchone()
        if not fact or fact["actor_id"] != audit["actor_id"]:
            return []
        source = admitted_source(
            tx, pid, fact, "material_movement" if movement else "ownership"
        )
        if source is None or source != command.source:
            return []
        if datetime.fromisoformat(fact["created_at"]) > datetime.fromisoformat(
            audit["recorded_at"]
        ):
            return []
        if movement:
            if (
                fact["movement"],
                fact["q_atoms"],
                fact["supersedes_id"],
                fact["external_signatory"],
                fact["evidence"],
            ) != (
                command.movement,
                atoms(command.quantity, command.unit, lot["unit"], lot["scale"]),
                str(command.supersedes_id) if command.supersedes_id else None,
                command.external_signatory,
                command.evidence,
            ):
                return []
        else:
            recorded = OwnershipBalance.model_validate_json(fact["balance_json"])
            if (
                any(
                    getattr(recorded, k) != getattr(command, k)
                    for k in (
                        "received",
                        "consumed",
                        "scrapped",
                        "returned",
                        "balance",
                        "unit",
                        "owner_id",
                        "material_id",
                    )
                )
                or not recorded.complete
            ):
                return []
        payload_hash = sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest()
        operation = tx.execute(
            "SELECT result_json FROM operations WHERE actor_id=? AND operation_id=? AND payload_hash=?",
            (audit["actor_id"], str(command.operation_id), payload_hash),
        ).fetchone()
        if not operation:
            return []
        result = json.loads(operation["result_json"])
        if (
            result.get("project_id") != str(pid)
            or result.get("object_id") != str(object_id)
            or result.get("object_type") != "material_lot"
        ):
            return []
        return [ObjectEvidence(reference=source.evidence, source=source)]
    except (DomainError, ValidationError, ValueError, KeyError, TypeError):
        return []


def history(tx, pid, lot):
    from .delivery_models import MaterialMovementView, OwnershipReconciliationView

    movements = [
        MaterialMovementView(
            id=r["id"],
            movement=r["movement"],
            quantity=amount(r["q_atoms"], lot["scale"]),
            supersedes_id=r["supersedes_id"],
            current=not r["superseded"],
            source=admitted_source(tx, pid, r, "material_movement"),
            external_signatory=r["external_signatory"],
            evidence=r["evidence"],
        )
        for r in tx.execute(
            "SELECT m.*,EXISTS(SELECT 1 FROM material_movements correction WHERE correction.supersedes_id=m.id) superseded FROM material_movements m WHERE m.project_id=? AND m.material_lot_id=? ORDER BY m.seq DESC LIMIT 100",
            (str(pid), lot["id"]),
        )
    ]
    current = balance(tx, pid, lot)
    reconciliations = []
    for r in tx.execute(
        "SELECT * FROM ownership_reconciliations WHERE project_id=? AND material_lot_id=? ORDER BY seq DESC LIMIT 20",
        (str(pid), lot["id"]),
    ):
        recorded = OwnershipBalance.model_validate_json(r["balance_json"])
        matches = all(
            getattr(current, k) == getattr(recorded, k)
            for k in (
                "received",
                "consumed",
                "scrapped",
                "returned",
                "balance",
                "complete",
            )
        )
        reconciliations.append(
            OwnershipReconciliationView(
                id=r["id"],
                current=matches,
                source=admitted_source(tx, pid, r, "ownership"),
                balance=recorded,
            )
        )
    return movements, reconciliations
