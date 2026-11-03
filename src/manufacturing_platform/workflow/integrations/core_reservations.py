"""Explicit source-owned release of unused warehouse reservation claims."""

from decimal import Decimal
from uuid import UUID

from ..exchange_models import ExternalRequest
from ..orders import own
from .core_guards import require
from .store import canonical_hash, identity


def released_quantity(observations, reservation, qualification=None, lot_id=None):
    return sum(
        (
            a.amount.quantity
            for f in observations.of_type("wms.reservation_release")
            if f.payload.reservation == reservation
            for a in f.payload.allocations
            if (qualification is None or a.qualification == qualification)
            and (lot_id is None or a.material_lot_id == lot_id)
        ),
        Decimal(0),
    )


def prepare_release(system, operation, observations):
    from .core_preparation import bound_requests

    p = operation.payload
    original = observations.fact(p.reservation)
    require(
        original.payload.fact_type == "wms.reservation",
        "Original source reservation required",
    )
    with system.registry.workflow_store.transaction() as tx:
        requests = bound_requests(
            tx, operation.project_id, UUID(p.reservation.external_id)
        )
        allocations = []
        for a in p.allocations:
            matches = [
                r
                for r in requests
                if r.typed_payload.kind == "reserve"
                and r.typed_payload.lot_id == a.material_lot_id
            ]
            require(
                len(matches) == 1,
                "Release requires exact original prepared reservation",
            )
            qualified = observations.fact(a.qualification)
            require(
                qualified.payload.fact_type == "wms.qualification",
                "Release qualification source required",
            )
            value = a.model_dump(mode="json")
            value.update(
                receipt=qualified.payload.receipt,
                reservation_id=matches[0].typed_payload.reservation_id,
            )
            allocations.append(value)
    payload = p.model_dump(mode="json", exclude={"operation", "allocations"})
    payload.update(fact_type="wms.reservation_release", allocations=allocations)
    return [
        system.make_fact(
            operation.project_id,
            payload,
            operation.operation_id,
            causes=[
                p.reservation,
                p.cause,
                *{
                    a.qualification.model_dump_json(): a.qualification
                    for a in p.allocations
                }.values(),
            ],
        )
    ]


def validate_release(operation, observations):
    p = operation.payload
    original = observations.fact(p.reservation).payload
    require(
        original.fact_type == "wms.reservation"
        and original.work_order_id == p.work_order_id,
        "Reservation release work order mismatch",
    )
    cause = observations.fact(p.cause).payload
    require(
        cause.fact_type
        in {"wms.return", "mes.completion", "mes.remaining_cancellation"}
        and cause.work_order_id == p.work_order_id,
        "Release requires actual unused-return/completion/cancellation cause",
    )
    if cause.fact_type == "wms.return":
        require(
            cause.direction == "to_warehouse",
            "Supplier return cannot release another allocation",
        )
    keys = [
        (a.material_lot_id, a.qualification.model_dump_json()) for a in p.allocations
    ]
    require(len(keys) == len(set(keys)), "Duplicate reservation release allocation")
    observations.containment(lot_ids=[a.material_lot_id for a in p.allocations])
    for a in p.allocations:
        matches = [
            v
            for v in original.allocations
            if v.material_lot_id == a.material_lot_id
            and v.qualification == a.qualification
        ]
        require(
            bool(matches)
            and all(
                (v.material_id, v.owner_id, v.amount.unit, v.amount.scale)
                == (a.material_id, a.owner_id, a.amount.unit, a.amount.scale)
                for v in matches
            ),
            "Release differs from original qualified allocation",
        )
        quantity = sum(v.amount.quantity for v in matches)
        picked = sum(
            v.amount.quantity
            for f in observations.of_type("wms.pick")
            for v in f.payload.allocations
            if v.reservation == p.reservation
            and v.qualification == a.qualification
            and v.material_lot_id == a.material_lot_id
        )
        returned = sum(
            v.amount.quantity
            for f in observations.of_type("wms.return")
            if f.payload.direction == "to_warehouse"
            for v in f.payload.allocations
            if v.reservation == p.reservation
            and v.qualification == a.qualification
            and v.material_lot_id == a.material_lot_id
        )
        released = released_quantity(
            observations, p.reservation, a.qualification, a.material_lot_id
        )
        require(
            a.amount.quantity <= quantity - picked + returned - released,
            "Release exceeds unused warehouse-held reservation",
        )


def validate_projection(tx, context, fact):
    p = fact.payload
    rows = {}
    for a in p.allocations:
        reservation = own(
            tx, "effective_reservations", context.project_id, a.reservation_id
        )
        request_row = own(
            tx, "exchanges", context.project_id, reservation["exchange_id"]
        )
        request = ExternalRequest.model_validate_json(request_row["request_json"])
        require(
            request.system == "wms"
            and request.typed_payload.kind == "reserve"
            and reservation["authority_receipt_id"] is not None,
            "Release requires projected accepted original WMS reservation",
        )
        require(
            (
                reservation["work_order_id"],
                reservation["material_lot_id"],
                request.typed_payload.material_id,
                request.typed_payload.owner_id,
                request.typed_payload.unit,
                request.typed_payload.scale,
            )
            == (
                str(p.work_order_id),
                str(a.material_lot_id),
                a.material_id,
                a.owner_id,
                a.amount.unit,
                a.amount.scale,
            ),
            "Projected release scope mismatch",
        )
        rows[str(a.reservation_id)] = reservation
    for rid, row in rows.items():
        total = sum(
            int(a.amount.quantity.scaleb(a.amount.scale))
            for a in p.allocations
            if str(a.reservation_id) == rid
        )
        require(
            total <= row["confirmed_atoms"],
            "Release exceeds current confirmed reservation",
        )
    return rows


def project_release(tx, context, fact):
    from .contracts import ObjectRef

    rows = validate_projection(tx, context, fact)
    for a in fact.payload.allocations:
        tx.execute(
            "INSERT INTO integration_reservation_releases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                *identity(context.project_id, fact.source_key),
                str(a.reservation_id),
                a.qualification.model_dump_json(),
                a.receipt.system,
                a.receipt.external_id,
                a.receipt.version,
                int(a.amount.quantity.scaleb(a.amount.scale)),
                canonical_hash(fact),
                context.now.isoformat(),
            ),
        )
    return [
        ObjectRef(project_id=context.project_id, kind="reservation", id=rid)
        for rid in rows
    ]


def released_basis_atoms(tx, project_id, reservation_id, system, external_id, version):
    return tx.execute(
        "SELECT COALESCE(SUM(q_atoms),0) FROM integration_reservation_releases WHERE project_id=? AND reservation_id=? AND receipt_system=? AND receipt_external_id=? AND receipt_version=?",
        (str(project_id), str(reservation_id), system, external_id, version),
    ).fetchone()[0]


def validate_requirement_budget(payload, observations):
    """Source reservations count even when their workflow projection is delayed."""
    requirements = {
        r.requirement_id: r
        for f in observations.of_type("sap.plan")
        for r in f.payload.requirements
    }
    current = requirements.get(payload.requirement_id)
    require(
        current is not None and current.work_order_id == payload.work_order_id,
        "Actual SAP requirement scope required",
    )
    scope = lambda r: (
        r.work_order_id,
        r.execution_scope,
        r.material_id,
        r.owner_id,
        r.amount.unit,
        r.amount.scale,
    )
    reserved = Decimal(0)
    for fact in observations.of_type("wms.reservation"):
        previous = requirements.get(fact.payload.requirement_id)
        if previous is not None and scope(previous) == scope(current):
            reserved += sum(
                a.amount.quantity for a in fact.payload.allocations
            ) - released_quantity(observations, fact.source_key)
    require(
        reserved + sum(a.amount.quantity for a in payload.allocations)
        <= current.amount.quantity,
        "Source reservations exceed current requirement budget",
    )
