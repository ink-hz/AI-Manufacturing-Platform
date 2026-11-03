"""Read admitted source inventory deltas without duplicating receipts or IQC."""

from uuid import UUID

from .contracts import IntegrationFact, ProjectionResult
from .store import canonical_hash, identity


def projected_adjustments(tx, project_id, lot):
    adjustment, returned = 0, 0
    if not tx.execute(
        "SELECT 1 FROM sqlite_master WHERE name='integration_projections'"
    ).fetchone():
        return adjustment, returned
    for row in tx.execute(
        "SELECT * FROM integration_projections WHERE project_id=? AND system='wms' AND object_type IN ('stocktake','return')",
        (str(project_id),),
    ):
        fact = IntegrationFact.model_validate_json(row["fact_json"])
        result = ProjectionResult.model_validate_json(row["result_json"])
        if (
            identity(project_id, fact.source_key)
            != tuple(
                row[k]
                for k in (
                    "project_id",
                    "system",
                    "object_type",
                    "external_id",
                    "version",
                )
            )
            or fact.project_id != UUID(str(project_id))
            or result.source_key != fact.source_key
            or result.project_id != fact.project_id
            or result.payload_hash != canonical_hash(fact)
            or row["payload_hash"] != result.payload_hash
            or not any(
                t.kind.value == "material_lot"
                and str(t.id) == lot["id"]
                and t.project_id == fact.project_id
                for t in result.targets
            )
        ):
            continue
        p = fact.payload
        if (
            p.fact_type == "wms.stocktake"
            and str(p.material_lot_id) == lot["id"]
            and (p.owner_id, p.expected.unit, p.expected.scale)
            == (lot["owner_id"], lot["unit"], lot["scale"])
        ):
            adjustment += int(
                (p.counted.quantity - p.expected.quantity).scaleb(lot["scale"])
            )
        elif p.fact_type == "wms.return" and p.direction == "to_supplier":
            returned += sum(
                int(a.amount.quantity.scaleb(lot["scale"]))
                for a in p.allocations
                if str(a.material_lot_id) == lot["id"]
                and (a.owner_id, a.material_id, a.amount.unit, a.amount.scale)
                == (lot["owner_id"], lot["material_id"], lot["unit"], lot["scale"])
            )
    return adjustment, returned
