"""Pure qualified warehouse/line custody guards over actual source lineage."""

from decimal import Decimal

from .core_guards import require
from .core_reservations import released_quantity


def lot_scope(allocation):
    return (
        allocation.material_lot_id,
        allocation.material_id,
        allocation.owner_id,
        allocation.amount.unit,
        allocation.amount.scale,
    )


def same_allocation(left, right):
    return (
        lot_scope(left) == lot_scope(right)
        and left.qualification == right.qualification
        and left.reservation == right.reservation
    )


def custody_key(custody):
    return custody.location, custody.custodian


def warehouse_custodies(observations, qualification):
    """Receipt and warehouse-putaway lineage, never custodian-name heuristics."""
    receipt = observations.fact(
        observations.fact(qualification).payload.receipt
    ).payload
    warehouses = {(receipt.location, receipt.custodian)}
    lines = {
        custody_key(f.payload.destination_custody)
        for f in observations.of_type("wms.pick")
        if any(a.qualification == qualification for a in f.payload.allocations)
    }
    for fact in observations.of_type("wms.putaway"):
        p = fact.payload
        if (
            any(a.qualification == qualification for a in p.allocations)
            and custody_key(p.source_custody) in warehouses - lines
            and custody_key(p.destination_custody) not in lines
        ):
            warehouses.add(custody_key(p.destination_custody))
    return warehouses - lines, lines


def validate_transfer_custody(payload, allocation, observations):
    warehouses, lines = warehouse_custodies(observations, allocation.qualification)
    source, destination = (
        custody_key(payload.source_custody),
        custody_key(payload.destination_custody),
    )
    if payload.operation == "wms.return" and payload.direction == "to_warehouse":
        require(
            allocation.reservation is not None and payload.work_order_id is not None,
            "Warehouse return requires exact custody scope",
        )
        picks = [
            f
            for f in observations.of_type("wms.pick")
            if f.payload.work_order_id == payload.work_order_id
            and any(same_allocation(v, allocation) for v in f.payload.allocations)
        ]
        require(
            bool(picks)
            and all(
                custody_key(f.payload.destination_custody) == source for f in picks
            ),
            "Return source custody differs from actual picked allocation",
        )
        require(
            destination in warehouses,
            "Return destination requires actual warehouse custody",
        )
        picked = sum(
            v.amount.quantity
            for f in picks
            for v in f.payload.allocations
            if same_allocation(v, allocation)
        )
        consumed = sum(
            v.amount.quantity
            for f in observations.of_type("mes.execution")
            if f.payload.work_order_id == payload.work_order_id
            for v in f.payload.material_uses
            if same_allocation(v, allocation)
        )
        returned = sum(
            v.amount.quantity
            for f in observations.of_type("wms.return")
            if f.payload.direction == "to_warehouse"
            and f.payload.work_order_id == payload.work_order_id
            for v in f.payload.allocations
            if same_allocation(v, allocation)
        )
        require(
            allocation.amount.quantity <= picked - consumed - returned,
            "Return exceeds exact unconsumed physical custody",
        )
    else:
        require(
            source in warehouses,
            "Transfer source requires actual warehouse custody/location",
        )
        if payload.operation == "wms.pick":
            require(
                destination not in warehouses,
                "Pick destination must be distinct line-side custody",
            )
        elif payload.operation == "wms.putaway":
            require(
                destination not in lines, "Putaway cannot relocate line-side custody"
            )
        else:
            require(
                destination not in warehouses | lines,
                "Supplier destination cannot be internal custody",
            )


def qualification_unreserved(observations, allocation):
    """Exact qualified claim budget; lot/location variance is enforced separately.

    Stocktake has no qualification attribution. Do not invent one: the caller
    intersects this budget with the actual lot and location variance budgets.
    """
    qualification = observations.fact(allocation.qualification).payload
    claimed = Decimal(0)
    for f in observations.of_type("wms.reservation"):
        claimed += sum(
            v.amount.quantity
            for v in f.payload.allocations
            if lot_scope(v) == lot_scope(allocation)
            and v.qualification == allocation.qualification
        )
        claimed -= released_quantity(
            observations,
            f.source_key,
            allocation.qualification,
            allocation.material_lot_id,
        )
    returned = sum(
        v.amount.quantity
        for f in observations.of_type("wms.return")
        if f.payload.direction == "to_supplier"
        for v in f.payload.allocations
        if lot_scope(v) == lot_scope(allocation)
        and v.qualification == allocation.qualification
    )
    return qualification.accepted.quantity - claimed - returned


def validate_supplier_return(payload, allocation, observations, balance):
    proposed_lot = sum(
        v.amount.quantity
        for v in payload.allocations
        if lot_scope(v) == lot_scope(allocation)
    )
    proposed_qualification = sum(
        v.amount.quantity
        for v in payload.allocations
        if lot_scope(v) == lot_scope(allocation)
        and v.qualification == allocation.qualification
    )
    require(
        allocation.reservation is None
        and proposed_lot
        <= balance.qualified
        + balance.qualified_adjustment
        - balance.reserved
        - balance.supplier_returned,
        "Supplier return exceeds aggregate unreserved qualified stock",
    )
    require(
        proposed_qualification <= qualification_unreserved(observations, allocation),
        "Supplier return exceeds exact qualification unreserved stock",
    )


def validate_warehouse_count(payload, observations):
    """Unattributed qualified loss cannot remove line-side reservation custody."""
    warehouses, lines = set(), set()
    for fact in observations.of_type("wms.qualification"):
        if fact.payload.material_lot_id == payload.material_lot_id:
            warehouse, line = warehouse_custodies(observations, fact.source_key)
            warehouses.update(location for location, _ in warehouse)
            lines.update(location for location, _ in line)
    require(
        payload.location in warehouses - lines,
        "Qualified stocktake requires unambiguous warehouse location",
    )
