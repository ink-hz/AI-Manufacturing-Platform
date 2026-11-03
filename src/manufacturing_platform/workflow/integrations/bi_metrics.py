"""Server-derived current-cutoff metrics, frozen with actual source sequence vector."""

from collections import defaultdict
from decimal import Decimal
from .. import quality
from .core_guards import require


def snapshot(system, operation, observations):
    now = system.store.clock()
    inputs = [
        f
        for f in observations.facts.values()
        if f.source.system
        in {"sap", "mes", "wms", "product_test", "customer", "overseas"}
        and f.source.occurred_at <= now
    ]
    require(bool(inputs), "Committed manufacturing sources required for BI refresh")
    keys = sorted(
        (f.source_key for f in inputs),
        key=lambda k: (k.system, k.object_type, k.external_id, k.version),
    )
    require(len(keys) <= 1000, "BI source cohort exceeds supported snapshot bound")
    from .store import identity, canonical_hash

    with system.registry.workflow_store.transaction() as tx:
        admitted = {
            tuple(row[:5]): row[5]
            for row in tx.execute(
                "SELECT project_id,system,object_type,external_id,version,payload_hash FROM integration_projections WHERE project_id=?",
                (str(operation.project_id),),
            )
        }
        attempts = defaultdict(list)
        for f in inputs:
            if f.payload.fact_type == "product_test.test" and admitted.get(
                identity(operation.project_id, f.source_key)
            ) == canonical_hash(f):
                attempts[f.payload.unit_id].append(f)
        cohort = set(attempts)
        first_pass = sum(
            min(
                fs, key=lambda f: (f.payload.attempt, f.source.external_id)
            ).payload.result
            == "pass"
            for fs in attempts.values()
        )
        final_good = 0
        version = tx.execute(
            "SELECT version FROM projects WHERE id=?", (str(operation.project_id),)
        ).fetchone()[0]
        for uid in cohort:
            latest = quality.latest_test(tx, operation.project_id, uid)
            if (
                latest
                and latest["outcome"] == "pass"
                and quality.valid_test(tx, operation.project_id, latest["id"])
                and not quality.scrapped(tx, operation.project_id, uid)
                and not quality.unresolved(tx, operation.project_id, uid)
            ):
                final_good += 1
    # Requirement count is dimensionless; kg and piece quantities are never summed.
    plans = [f for f in inputs if f.payload.fact_type == "sap.plan"]
    current = {}
    for f in plans:
        for r in f.payload.requirements:
            current[r.work_order_id] = f
    requirements = {
        r.requirement_id: r
        for f in current.values()
        for r in f.payload.requirements
        if current[r.work_order_id].source_key == f.source_key
    }
    allocated = defaultdict(Decimal)
    for f in inputs:
        if f.payload.fact_type == "wms.reservation":
            allocated[f.payload.requirement_id] += sum(
                a.amount.quantity for a in f.payload.allocations
            )
        elif f.payload.fact_type == "wms.reservation_release":
            reservation = observations.fact(f.payload.reservation)
            allocated[reservation.payload.requirement_id] -= sum(
                a.amount.quantity for a in f.payload.allocations
            )
    shortage = sum(
        allocated[rid] < r.amount.quantity for rid, r in requirements.items()
    )
    orders = {
        f.source_key.model_dump_json(): f.payload.amount.quantity
        for f in inputs
        if f.payload.fact_type == "sap.order"
    }
    shipped = {
        u.unit_id
        for f in inputs
        if f.payload.fact_type == "wms.shipment"
        for u in f.payload.units
    }
    denominator = sum(orders.values(), Decimal(0))
    require(
        denominator == denominator.to_integral_value(),
        "BI delivery count requires integral serialized unit scope",
    )
    definitions = [
        (
            "first_pass_yield",
            "first-admitted-attempt-pass/distinct-tested-units-v1",
            first_pass,
            len(cohort),
        ),
        (
            "final_yield",
            "current-final-good/first-tested-cohort-v1",
            final_good,
            len(cohort),
        ),
        (
            "shortage",
            "short-requirement-count/current-requirement-count-v1",
            shortage,
            len(requirements),
        ),
        (
            "delivery",
            "distinct-physically-shipped/formal-order-unit-count-v1",
            len(shipped),
            int(denominator),
        ),
    ]
    metrics = [
        dict(
            metric=m,
            formula_version=formula,
            numerator=num,
            denominator=den,
            sources=keys,
        )
        for m, formula, num, den in definitions
    ]
    previous = observations.of_type("bi.snapshot")
    return system.make_fact(
        operation.project_id,
        dict(
            fact_type="bi.snapshot",
            cutoff=now,
            metrics=metrics,
            snapshot_version=len(previous) + 1,
            source_vector=[
                dict(system=k, sequence=v)
                for k, v in sorted(observations.source_cutoffs.items())
                if k != "bi"
            ],
            workflow_version=version,
            cohort_unit_ids=sorted(cohort, key=str),
        ),
        operation.operation_id,
        causes=keys,
    )
