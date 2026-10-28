"""Append-only recovery of a missing optional historical stock basis.

Only the configured source's original canonical reservation receipt can supply
its missing basis. Other malformed receipts and genuinely anonymous inventory
are outside this protocol. No balances or original evidence are rewritten.
"""

import hashlib
import json
from datetime import datetime
from uuid import UUID, uuid4

from pydantic import ValidationError

from .commands import COMMAND_REGISTRY
from .contracts import DomainError, MutationResult
from .delivery import fail
from .delivery_models import ReconcileStockBasis
from .exchange_models import (
    ExternalReceipt,
    ExternalRequest,
    StockBasisProof,
    StockProofPayload,
)
from .orders import own
from .supply import atoms


def raw_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def opening_hash(opening):
    return raw_hash(json.dumps(dict(opening), sort_keys=True, separators=(",", ":")))


def prepare(tx, context, command):
    eco = own(tx, "eco_changes", context.project_id, command.eco_id)
    reservation = own(tx, "reservations", context.project_id, command.reservation_id)
    original = own(tx, "exchanges", context.project_id, reservation["exchange_id"])
    opening = tx.execute(
        "SELECT * FROM eco_stock_openings WHERE project_id=? AND eco_id=? AND lot_id=?",
        (str(context.project_id), eco["id"], reservation["material_lot_id"]),
    ).fetchone()
    if (
        not opening
        or not original["receipt_json"]
        or not reservation["authority_receipt_id"]
    ):
        fail("Historical opening and accepted original reservation are required")
    receipt = ExternalReceipt.model_validate_json(original["receipt_json"])
    if receipt.occurred_at > datetime.fromisoformat(eco["created_at"]):
        fail("Later reservation cannot repair an earlier opening")
    if eco["state"] != "open":
        fail("Historical proof recovery requires an open ECO")
    from decimal import Decimal

    lot = own(tx, "material_lots", context.project_id, reservation["material_lot_id"])
    accounted = (
        sum(
            atoms(
                Decimal(json.loads(r[0])["quantity"]),
                lot["unit"],
                lot["unit"],
                lot["scale"],
            )
            for r in tx.execute(
                "SELECT payload_json FROM eco_impacts WHERE eco_id=? AND json_extract(payload_json,'$.type')='stock' AND json_extract(payload_json,'$.object_id')=?",
                (eco["id"], lot["id"]),
            )
        )
        + opening["consumed_atoms"]
    )
    eid = uuid4()
    request = ExternalRequest(
        id=eid,
        project_id=context.project_id,
        system=original["system"],
        action=command.action,
        business_key=str(eid),
        source_version=1,
        typed_payload=StockProofPayload(
            eco_id=command.eco_id,
            reservation_id=command.reservation_id,
            original_exchange_id=original["id"],
            original_business_key=original["business_key"],
            original_receipt_hash=raw_hash(original["receipt_json"]),
            original_opening_hash=opening_hash(opening),
            original_accounted_atoms=accounted,
        ),
    )
    context.exchange_service.prepare(tx, context, request)
    return MutationResult(object_type="eco", object_id=command.eco_id, exchange_id=eid)


def validate(tx, pid, row, proof, mode):
    from .exchanges import receipt_scope

    request = ExternalRequest.model_validate_json(row["request_json"])
    payload = request.typed_payload
    if (
        not isinstance(payload, StockProofPayload)
        or request.project_id != UUID(str(pid))
        or proof.mode != mode
        or proof.request_hash != row["request_hash"]
    ):
        fail("Stock proof request or provenance mismatch")
    reservation = own(tx, "reservations", pid, payload.reservation_id)
    original = own(tx, "exchanges", pid, payload.original_exchange_id)
    eco = own(tx, "eco_changes", pid, payload.eco_id)
    opening = tx.execute(
        "SELECT * FROM eco_stock_openings WHERE project_id=? AND eco_id=? AND lot_id=?",
        (str(pid), eco["id"], reservation["material_lot_id"]),
    ).fetchone()
    if (
        not opening
        or opening_hash(opening) != payload.original_opening_hash
        or reservation["exchange_id"] != original["id"]
        or original["business_key"] != payload.original_business_key
        or raw_hash(original["receipt_json"] or "") != payload.original_receipt_hash
    ):
        fail("Historical stock proof binding changed")
    local = ExternalReceipt.model_validate_json(original["receipt_json"])
    canonical = proof.receipt
    if (
        canonical.phase not in {"accepted", "posted"}
        or not receipt_scope(tx, original, canonical)
        or not receipt_scope(tx, original, local)
        or canonical.sequence < 1
        or canonical.sequence != original["source_sequence"]
        or canonical.source_version != local.source_version
    ):
        fail("Stock proof must match the admitted original reservation")
    local_body = local.model_dump(mode="json")
    source_body = canonical.model_dump(mode="json")
    if (
        len(local.details) != 1
        or len(canonical.details) != 1
        or canonical.details[0].stock_basis is None
    ):
        fail("Source has no original historical stock basis")
    # The optional basis is the only field allowed to have been absent locally.
    if local.details[0].stock_basis is None:
        source_body["details"][0].pop("stock_basis", None)
    if local_body != source_body:
        fail("Stock proof changes original receipt identity or business detail")
    if canonical.occurred_at > datetime.fromisoformat(eco["created_at"]):
        fail("Source reservation is newer than the historical opening")
    lot = own(tx, "material_lots", pid, reservation["material_lot_id"])
    indexed = {}
    for source in proof.sources:
        key = (
            source.source.system.strip().casefold(),
            source.source.external_id.strip(),
        )
        if (
            key in indexed
            or (
                source.project_id,
                str(source.lot_id),
                source.owner_id,
                source.material_id,
                source.unit,
            )
            != (
                UUID(str(pid)),
                lot["id"],
                lot["owner_id"],
                lot["material_id"],
                lot["unit"],
            )
            or source.source.object_type.strip().casefold() != "receipt"
            or source.source.mode != mode
        ):
            fail("Stock proof source scope or identity mismatch")
        if (
            source.source.occurred_at > source.source.collected_at
            or source.source.collected_at > canonical.occurred_at
        ):
            fail("Later material arrival cannot repair historical coverage")
        indexed[key] = source
    expected = {
        (b.system.strip().casefold(), b.external_id.strip())
        for b in canonical.details[0].stock_basis
    }
    if expected != set(indexed):
        fail("Stock proof source membership differs from original basis")
    for basis in canonical.details[0].stock_basis:
        source = indexed[(basis.system.strip().casefold(), basis.external_id.strip())]
        if (
            source.source.version != basis.source_version
            or source.quantity != basis.source_quantity
        ):
            fail("Stock proof source version or physical quantity changed")
    return canonical


def apply_proof(tx, context, row, proof, mode):
    from .exchanges import event

    validate(tx, context.project_id, row, proof, mode)
    request = ExternalRequest.model_validate_json(row["request_json"])
    payload = request.typed_payload
    tx.execute(
        "INSERT INTO stock_basis_proofs(id,project_id,eco_id,reservation_id,exchange_id,proof_json,created_at) VALUES (?,?,?,?,?,?,?)",
        (
            str(uuid4()),
            str(context.project_id),
            str(payload.eco_id),
            str(payload.reservation_id),
            row["id"],
            proof.model_dump_json(),
            context.now.isoformat(),
        ),
    )
    event(tx, row, "accepted", "Verified original stock coverage appended")


def recovered_receipt(tx, pid, reservation_id, eco_id=None):
    args = [str(pid), str(reservation_id)]
    scope = " AND p.eco_id=?" if eco_id else ""
    if eco_id:
        args.append(str(eco_id))
    for row in tx.execute(
        "SELECT p.proof_json,e.* FROM stock_basis_proofs p JOIN exchanges e ON e.id=p.exchange_id WHERE p.project_id=? AND p.reservation_id=?"
        + scope
        + " ORDER BY p.seq DESC LIMIT 50",
        args,
    ):
        try:
            proof = StockBasisProof.model_validate_json(row["proof_json"])
            return validate(tx, pid, row, proof, row["mode"])
        except (DomainError, ValidationError, ValueError, TypeError):
            continue
    return None


def opening_coverage(tx, pid, opening):
    """Recover only the quantity already accounted when this ECO was opened."""
    basis = json.loads(opening["basis_json"])
    if opening["complete"]:
        return basis, True
    eco = own(tx, "eco_changes", pid, opening["eco_id"])
    lot = own(tx, "material_lots", pid, opening["lot_id"])
    complete = True
    covered = {}
    for reservation in tx.execute(
        "SELECT r.id,e.receipt_json FROM reservations r JOIN exchanges e ON e.id=r.exchange_id WHERE r.project_id=? AND r.material_lot_id=? AND r.authority_receipt_id IS NOT NULL",
        (str(pid), lot["id"]),
    ):
        receipt = ExternalReceipt.model_validate_json(reservation["receipt_json"])
        if receipt.occurred_at > datetime.fromisoformat(eco["created_at"]):
            continue
        if receipt.details[0].stock_basis is None:
            receipt = recovered_receipt(tx, pid, reservation["id"], eco["id"])
        if receipt is None or receipt.details[0].stock_basis is None:
            complete = False
            continue
        for item in receipt.details[0].stock_basis:
            key = json.dumps(
                ["receipt", item.system.strip().casefold(), item.external_id.strip()],
                separators=(",", ":"),
            )
            covered[key] = covered.get(key, 0) + atoms(
                item.quantity, item.unit, lot["unit"], lot["scale"]
            )
    # Original initial stock snapshot + consumed opening stock is an immutable budget.
    rows = tx.execute(
        "SELECT e.request_json FROM stock_basis_proofs p JOIN exchanges e ON e.id=p.exchange_id WHERE p.project_id=? AND p.eco_id=? AND p.reservation_id IN (SELECT id FROM reservations WHERE material_lot_id=?) ORDER BY p.seq",
        (str(pid), eco["id"], lot["id"]),
    ).fetchall()
    historical = min(
        (
            ExternalRequest.model_validate_json(
                r[0]
            ).typed_payload.original_accounted_atoms
            for r in rows
        ),
        default=sum(basis.values()),
    )
    budget = max(0, historical - sum(basis.values()))
    for key, q in sorted(covered.items()):
        addition = min(budget, max(0, q - basis.get(key, 0)))
        if addition:
            basis[key] = basis.get(key, 0) + addition
            budget -= addition
    return basis, complete


COMMAND_REGISTRY.register(
    ReconcileStockBasis, roles={"engineering"}, qualifications=set(), handler=prepare
)
