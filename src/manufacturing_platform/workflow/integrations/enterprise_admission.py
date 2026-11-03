"""Read-only source-target binding checks shared by enterprise projections."""

from .contracts import IntegrationFact, ProjectionResult
from .core_guards import require
from .store import identity, canonical_hash


def projected_fact(tx, project_id, key, *, kind=None, ident=None):
    from .core_models import SourceKey

    key = SourceKey(
        system=key.system,
        object_type=key.object_type,
        external_id=key.external_id,
        version=key.version,
    )
    row = tx.execute(
        "SELECT fact_json,result_json,payload_hash FROM integration_projections WHERE project_id=? AND system=? AND object_type=? AND external_id=? AND version=?",
        identity(project_id, key),
    ).fetchone()
    require(row is not None, "Exact source must be projected")
    fact = IntegrationFact.model_validate_json(row["fact_json"])
    result = ProjectionResult.model_validate_json(row["result_json"])
    require(
        fact.project_id == project_id
        and fact.source_key == key
        and result.project_id == project_id
        and result.source_key == key
        and canonical_hash(fact) == row["payload_hash"] == result.payload_hash,
        "Projected source identity/hash mismatch",
    )
    if kind:
        require(
            any(t.kind == kind and str(t.id) == str(ident) for t in result.targets),
            "Exact source target mismatch",
        )
    return fact


def validate_target(tx, context, target):
    from ..orders import own

    if target.target_type == "engineering":
        npi = own(tx, "npis", context.project_id, target.npi_id)
        require(
            npi["revision_id"] == str(target.revision_id), "OA NPI revision mismatch"
        )
        projected_fact(
            tx,
            context.project_id,
            target.source_key,
            kind="revision",
            ident=target.revision_id,
        )
    else:
        nc = own(tx, "nonconformances", context.project_id, target.nonconformance_id)
        unit = own(tx, "units", context.project_id, nc["unit_id"])
        require(
            unit["work_order_id"] == str(target.work_order_id),
            "OA disposition work order mismatch",
        )
        projected_fact(
            tx, context.project_id, target.source_key, kind="test", ident=nc["test_id"]
        )
