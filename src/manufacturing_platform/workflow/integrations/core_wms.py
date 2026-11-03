"""WMS receipt, qualification and physical reservation/custody conservation."""

from dataclasses import dataclass
from decimal import Decimal

from .contracts import IntegrationFact
from .core_guards import require
from .core_systems import CoreSystem


@dataclass(frozen=True)
class PhysicalBalance:
    received: Decimal
    qualified: Decimal
    rejected: Decimal
    reserved: Decimal
    picked: Decimal
    consumed: Decimal
    returned: Decimal
    supplier_returned: Decimal
    qualified_adjustment: Decimal
    pending_adjustment: Decimal

    @property
    def line_side(self):
        return self.picked - self.consumed - self.returned


def physical_balance(tx, project_id, lot_id):
    facts = [
        IntegrationFact.model_validate_json(r[0])
        for r in tx.execute(
            "SELECT fact_json FROM facts WHERE project_id=? ORDER BY sequence",
            (str(project_id),),
        )
    ]
    totals = dict(
        received=Decimal(0),
        qualified=Decimal(0),
        rejected=Decimal(0),
        reserved=Decimal(0),
        picked=Decimal(0),
        consumed=Decimal(0),
        returned=Decimal(0),
        supplier_returned=Decimal(0),
        qualified_adjustment=Decimal(0),
        pending_adjustment=Decimal(0),
    )
    for f in facts:
        p = f.payload
        if p.fact_type == "wms.receipt" and p.material_lot_id == lot_id:
            totals["received"] += p.amount.quantity
        elif p.fact_type == "wms.qualification" and p.material_lot_id == lot_id:
            totals["qualified"] += p.accepted.quantity
            totals["rejected"] += p.rejected.quantity
        elif p.fact_type == "wms.reservation_release":
            totals["reserved"] -= sum(
                a.amount.quantity for a in p.allocations if a.material_lot_id == lot_id
            )
        elif p.fact_type == "wms.stocktake" and p.material_lot_id == lot_id:
            totals[p.quality_state + "_adjustment"] += (
                p.counted.quantity - p.expected.quantity
            )
        elif p.fact_type == "wms.return":
            field = "returned" if p.direction == "to_warehouse" else "supplier_returned"
            totals[field] += sum(
                a.amount.quantity for a in p.allocations if a.material_lot_id == lot_id
            )
        elif p.fact_type in {"wms.reservation", "wms.pick", "wms.consumption"}:
            name = {
                "wms.reservation": "reserved",
                "wms.pick": "picked",
                "wms.consumption": "consumed",
            }[p.fact_type]
            totals[name] += sum(
                a.amount.quantity for a in p.allocations if a.material_lot_id == lot_id
            )
    return PhysicalBalance(**totals)


def location_quantity(observations, qualification_key, location, custodian=None):
    """Qualified quantity at a real location; custody mirror facts never add stock."""
    qualification = observations.fact(qualification_key).payload
    receipt = observations.fact(qualification.receipt).payload
    quantity = (
        qualification.accepted.quantity
        if receipt.location == location
        and (custodian is None or receipt.custodian == custodian)
        else Decimal(0)
    )
    for f in observations.facts.values():
        p = f.payload
        if p.fact_type not in {"wms.putaway", "wms.pick", "wms.return"}:
            continue
        amount = sum(
            a.amount.quantity
            for a in p.allocations
            if a.qualification == qualification_key
        )
        if p.source_custody.location == location and (
            custodian is None or p.source_custody.custodian == custodian
        ):
            quantity -= amount
        if (
            p.destination_custody.location == location
            and (custodian is None or p.destination_custody.custodian == custodian)
            and not (p.fact_type == "wms.return" and p.direction == "to_supplier")
        ):
            quantity += amount
    # Execution spends line-side stock even before its WMS mirror is delivered.
    for execution in observations.of_type("mes.execution"):
        for a in execution.payload.material_uses:
            if a.qualification != qualification_key:
                continue
            picks = [
                f
                for f in observations.of_type("wms.pick")
                if f.payload.work_order_id == execution.payload.work_order_id
                and any(
                    v.qualification == qualification_key
                    and v.reservation == a.reservation
                    for v in f.payload.allocations
                )
            ]
            if (
                picks
                and picks[-1].payload.destination_custody.location == location
                and (
                    custodian is None
                    or picks[-1].payload.destination_custody.custodian == custodian
                )
            ):
                quantity -= a.amount.quantity
    return quantity


class WmsSystem(CoreSystem):
    def balance(self, project_id, lot_id):
        with self.store.transaction() as tx:
            return physical_balance(tx, project_id, lot_id)

    def prepare(self, operation, observations):
        if operation.payload.operation == "wms.release_reservation":
            from .core_reservations import prepare_release

            return prepare_release(self, operation, observations)
        facts = super().prepare(operation, observations)
        p = operation.payload
        causes = []
        if p.operation == "wms.receive":
            notices = [
                f
                for f in observations.of_type("srm.arrival")
                if f.payload.commitment_id == p.commitment_id
                and f.payload.material_id == p.material_id
                and f.payload.supplier_batch == p.supplier_batch
            ]
            causes.extend(f.source_key for f in notices)
        if hasattr(p, "allocations"):
            for a in p.allocations:
                causes.extend(
                    [a.qualification] + ([a.reservation] if a.reservation else [])
                )
        if hasattr(p, "cause"):
            causes.append(p.cause)
        if p.operation == "wms.ship":
            causes.extend(p.releases)
        unique = {k.model_dump_json(): k for k in causes}
        facts[0] = facts[0].model_copy(update={"caused_by": list(unique.values())})
        if p.operation == "wms.pick":
            from uuid import uuid5, NAMESPACE_URL

            payload = p.model_dump(mode="json", exclude={"operation"})
            payload.update(fact_type="wms.custody", cause=facts[0].source_key)
            facts.append(
                self.make_fact(
                    operation.project_id,
                    payload,
                    uuid5(NAMESPACE_URL, f"{operation.operation_id}:custody"),
                    causes=[facts[0].source_key],
                )
            )
        return facts

    def validate_operation(self, tx, context, operation, requests):
        p = operation.payload
        if p.operation == "wms.ship":
            from ..delivery import current_shipment_reasons
            from ..orders import own

            require(
                len(requests) == 1
                and requests[0].typed_payload.shipment_id == p.shipment_id,
                "Shipment prepared scope mismatch",
            )
            require(
                not current_shipment_reasons(tx, context.project_id, p.shipment_id),
                "Current shipment eligibility blocked",
            )
            for member in p.units:
                unit = own(tx, "units", context.project_id, member.unit_id)
                require(unit["sn"] == member.sn, "Shipment SN mismatch")
        if p.operation == "wms.reserve":
            from ..exchanges import validate_reservation
            from ..exchange_models import RequestReservation
            from .core_projections import command_data

            for a in p.allocations:
                validate_reservation(
                    tx,
                    context,
                    RequestReservation(
                        **command_data(context),
                        action="reservation.request",
                        work_order_id=p.work_order_id,
                        requirement_id=p.requirement_id,
                        lot_id=a.material_lot_id,
                        quantity=str(sum(v.amount.quantity for v in p.allocations)),
                        unit=a.amount.unit,
                    ),
                    exclude_exchange_ids=[r.id for r in requests],
                )

    def transition(self, tx, operation, facts, observations):
        p = operation.payload
        if p.operation == "wms.release_reservation":
            from .core_reservations import validate_release

            validate_release(operation, observations)
            return
        if p.operation == "wms.receive":
            return
        if p.operation == "wms.stocktake":
            cause = observations.fact(p.cause)
            require(
                cause.source.system == "wms"
                and (
                    getattr(cause.payload, "material_lot_id", None) == p.material_lot_id
                    or any(
                        a.material_lot_id == p.material_lot_id
                        for a in getattr(cause.payload, "allocations", [])
                    )
                ),
                "Stocktake requires scoped physical WMS cause",
            )
            receipts = [
                f
                for f in observations.of_type("wms.receipt")
                if f.payload.material_lot_id == p.material_lot_id
            ]
            require(bool(receipts), "Stocktake requires actual lot provenance")
            receipt = receipts[0].payload
            require(
                (p.owner_id, p.expected.unit, p.expected.scale)
                == (receipt.owner_id, receipt.amount.unit, receipt.amount.scale),
                "Stocktake owner/dimensions mismatch",
            )
            observations.containment(lot_ids=[p.material_lot_id])
            balance = physical_balance(tx, operation.project_id, p.material_lot_id)
            previous = sum(
                f.payload.counted.quantity - f.payload.expected.quantity
                for f in observations.of_type("wms.stocktake")
                if f.payload.material_lot_id == p.material_lot_id
                and f.payload.location == p.location
                and f.payload.quality_state == p.quality_state
            )
            if p.quality_state == "qualified":
                from .core_custody import validate_warehouse_count

                validate_warehouse_count(p, observations)
                expected = (
                    sum(
                        location_quantity(observations, f.source_key, p.location)
                        for f in observations.of_type("wms.qualification")
                        if f.payload.material_lot_id == p.material_lot_id
                    )
                    + previous
                )
                require(
                    p.counted.quantity <= p.expected.quantity,
                    "Positive variance cannot create qualified stock",
                )
                missing = p.expected.quantity - p.counted.quantity
                require(
                    missing
                    <= balance.qualified
                    + balance.qualified_adjustment
                    - balance.reserved
                    - balance.supplier_returned,
                    "Stocktake would remove reserved qualified stock",
                )
            else:
                expected = (
                    sum(
                        f.payload.amount.quantity
                        for f in receipts
                        if f.payload.location == p.location
                    )
                    - sum(
                        f.payload.accepted.quantity + f.payload.rejected.quantity
                        for f in observations.of_type("wms.qualification")
                        if observations.fact(f.payload.receipt).payload.material_lot_id
                        == p.material_lot_id
                        and observations.fact(f.payload.receipt).payload.location
                        == p.location
                    )
                    + previous
                )
            require(
                p.expected.quantity == expected,
                "Stocktake expected location quantity is stale",
            )
            return
        if p.operation == "wms.ship":
            ids = {u.unit_id for u in p.units}
            releases = [observations.fact(key) for key in p.releases]
            require(
                all(
                    f.payload.fact_type == "mes.release"
                    and f.payload.decision == "approved"
                    and ids.intersection(u.unit_id for u in f.payload.units)
                    for f in releases
                ),
                "Shipment release scope mismatch",
            )
            for uid in ids:
                for kind in ("manufacturing", "quality"):
                    releases = [
                        f
                        for f in observations.of_type("mes.release")
                        if f.payload.kind == kind
                        and any(u.unit_id == uid for u in f.payload.units)
                    ]
                    require(
                        bool(releases)
                        and releases[-1].payload.decision == "approved"
                        and releases[-1].source_key in p.releases,
                        "Latest manufacturing and quality approvals required",
                    )
                require(
                    not any(
                        any(u.unit_id == uid for u in f.payload.units)
                        for f in observations.of_type("wms.shipment")
                    ),
                    "Unit already physically shipped",
                )
            lots = [
                a.material_lot_id
                for f in observations.of_type("mes.execution")
                if f.payload.unit.unit_id in ids
                for a in f.payload.material_uses
            ]
            observations.containment(unit_ids=ids, lot_ids=lots)
            return
        require(
            p.operation in {"wms.reserve", "wms.pick", "wms.putaway", "wms.return"},
            "WMS operation prerequisite unavailable",
        )
        if p.operation == "wms.reserve":
            from .core_reservations import validate_requirement_budget

            validate_requirement_budget(p, observations)
        lots = [a.material_lot_id for a in p.allocations]
        keys = [
            (
                a.material_lot_id,
                a.qualification.model_dump_json(),
                a.reservation.model_dump_json() if a.reservation else None,
            )
            for a in p.allocations
        ]
        require(len(keys) == len(set(keys)), "Duplicate physical allocation")
        observations.containment(lot_ids=lots)
        for a in p.allocations:
            qualification = observations.fact(a.qualification)
            require(
                qualification.payload.fact_type == "wms.qualification"
                and qualification.payload.material_lot_id == a.material_lot_id,
                "Qualification lot mismatch",
            )
            receipt = observations.fact(qualification.payload.receipt).payload
            require(
                (a.material_id, a.owner_id, a.amount.unit, a.amount.scale)
                == (
                    receipt.material_id,
                    receipt.owner_id,
                    receipt.amount.unit,
                    receipt.amount.scale,
                ),
                "Allocation owner/material/dimensions mismatch",
            )
            if p.operation in {"wms.pick", "wms.putaway", "wms.return"}:
                from .core_custody import validate_transfer_custody

                validate_transfer_custody(p, a, observations)
                cause = observations.fact(p.cause)
                require(
                    p.source_custody != p.destination_custody,
                    "Physical transfer requires different custody",
                )
                available = location_quantity(
                    observations,
                    a.qualification,
                    p.source_custody.location,
                    p.source_custody.custodian,
                )
                proposed_here = sum(
                    v.amount.quantity
                    for v in p.allocations
                    if v.qualification == a.qualification
                )
                adjustment = sum(
                    f.payload.counted.quantity - f.payload.expected.quantity
                    for f in observations.of_type("wms.stocktake")
                    if f.payload.material_lot_id == a.material_lot_id
                    and f.payload.location == p.source_custody.location
                    and f.payload.quality_state == "qualified"
                )
                total_here = (
                    sum(
                        location_quantity(
                            observations, f.source_key, p.source_custody.location
                        )
                        for f in observations.of_type("wms.qualification")
                        if f.payload.material_lot_id == a.material_lot_id
                    )
                    + adjustment
                )
                require(
                    proposed_here <= available
                    and sum(
                        v.amount.quantity
                        for v in p.allocations
                        if v.material_lot_id == a.material_lot_id
                    )
                    <= total_here,
                    "Insufficient source location/custody quantity",
                )
            balance = physical_balance(tx, operation.project_id, a.material_lot_id)
            if p.operation == "wms.reserve":
                proposed = sum(
                    v.amount.quantity
                    for v in p.allocations
                    if v.material_lot_id == a.material_lot_id
                )
                require(
                    proposed
                    <= balance.qualified
                    + balance.qualified_adjustment
                    - balance.reserved
                    - balance.supplier_returned,
                    "Reservation exceeds qualified available quantity",
                )
                from .core_custody import qualification_unreserved

                proposed_scope = sum(
                    v.amount.quantity
                    for v in p.allocations
                    if v.qualification == a.qualification
                )
                require(
                    proposed_scope <= qualification_unreserved(observations, a),
                    "Reservation exceeds exact IQC qualification available quantity",
                )
            elif p.operation == "wms.return":
                if p.direction == "to_supplier":
                    from .core_custody import validate_supplier_return

                    validate_supplier_return(p, a, observations, balance)
            elif p.operation == "wms.pick":
                require(a.reservation is not None, "Pick requires exact reservation")
                previous = [
                    f
                    for f in observations.of_type("wms.pick")
                    if any(
                        v.reservation == a.reservation
                        and v.qualification == a.qualification
                        for v in f.payload.allocations
                    )
                ]
                require(
                    all(
                        f.payload.destination_custody == p.destination_custody
                        for f in previous
                    ),
                    "Reserved allocation has another line-side custody",
                )
                reservation = observations.fact(a.reservation).payload
                require(
                    reservation.fact_type == "wms.reservation"
                    and reservation.work_order_id == p.work_order_id,
                    "Pick work order mismatch",
                )
                allocated = sum(
                    v.amount.quantity
                    for v in reservation.allocations
                    if v.material_lot_id == a.material_lot_id
                    and v.qualification == a.qualification
                )
                from .core_reservations import released_quantity

                allocated -= released_quantity(
                    observations, a.reservation, a.qualification, a.material_lot_id
                )
                used = sum(
                    v.amount.quantity
                    for f in observations.of_type("wms.pick")
                    for v in f.payload.allocations
                    if v.reservation == a.reservation
                    and v.material_lot_id == a.material_lot_id
                    and v.qualification == a.qualification
                )
                returned = sum(
                    v.amount.quantity
                    for f in observations.of_type("wms.return")
                    if f.payload.direction == "to_warehouse"
                    for v in f.payload.allocations
                    if v.reservation == a.reservation
                    and v.material_lot_id == a.material_lot_id
                    and v.qualification == a.qualification
                )
                require(
                    a.amount.quantity + used - returned <= allocated,
                    "Pick exceeds exact reservation",
                )

    def consume_fact(self, tx, delivery, observations):
        p = delivery.fact.payload
        if p.fact_type == "mes.iqc":
            receipt = observations.fact(p.receipt)
            payload = p.model_dump(mode="json")
            payload.update(
                fact_type="wms.qualification",
                iqc=delivery.fact.source_key.model_dump(),
                material_lot_id=receipt.payload.material_lot_id,
            )
            self.emit(tx, self.child(delivery, payload))

        elif p.fact_type == "mes.execution" and p.material_uses:
            payload = dict(
                fact_type="wms.consumption",
                cause=delivery.fact.source_key.model_dump(),
                work_order_id=p.work_order_id,
                unit_id=p.unit.unit_id,
                allocations=[a.model_dump(mode="json") for a in p.material_uses],
            )
            self.emit(tx, self.child(delivery, payload))
