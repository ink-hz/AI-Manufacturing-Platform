"""Shared calibration validation plus exact independent PLC cause binding."""

import json
from .. import laboratory, orders
from ..laboratory_models import RecordCalibration, ConfirmCalibration
from .core_projections import command_data
from .enterprise_admission import projected_fact
from .core_guards import require
from .contracts import ProjectionResult
from .store import identity


def command(tx, context, fact):
    p = fact.payload
    if p.fact_type == "product_test.calibration":
        run = laboratory.qualified_run(tx, context.project_id, p.run_id)
        plan = json.loads(
            orders.own(tx, "test_plans", context.project_id, run["plan_id"])[
                "payload_json"
            ]
        )
        require(
            (run["unit_id"], plan["equipment"], plan["algorithm_version"])
            == (str(p.unit_id), p.equipment, p.algorithm_version),
            "Calibration run/equipment/algorithm mismatch",
        )
        value = RecordCalibration(
            **command_data(context),
            action="calibration.record",
            run_id=p.run_id,
            origin="demo",
            algorithm_version=p.algorithm_version,
            parameters=[v.model_dump(mode="json") for v in p.parameters],
            source_identity=p.source_identity,
            source_version=p.source_version,
            evidence=p.evidence,
        )
        laboratory.validate_calibration(tx, context, value)
        return value
    write = projected_fact(tx, context.project_id, p.calibration)
    q = write.payload
    require(
        q.fact_type == "product_test.calibration", "Exact calibration write required"
    )
    require(
        (q.run_id, q.unit_id, q.equipment, q.source_version)
        == (p.run_id, p.unit_id, p.equipment, p.source_version),
        "Readback scope/version differs from calibration write",
    )
    require(
        write.source.occurred_at <= p.observed_at <= context.now
        and p.source_identity != q.source_identity,
        "Independent readback identity/time required",
    )
    row = tx.execute(
        "SELECT result_json FROM integration_projections WHERE project_id=? AND system=? AND object_type=? AND external_id=? AND version=?",
        identity(context.project_id, p.calibration),
    ).fetchone()
    ids = [
        t.id
        for t in ProjectionResult.model_validate_json(row[0]).targets
        if t.kind == "calibration"
    ]
    require(len(ids) == 1, "Exact calibration target required")
    value = ConfirmCalibration(
        **command_data(context),
        action="calibration.confirm",
        calibration_id=ids[0],
        origin="demo",
        source_identity=p.source_identity,
        source_version=p.source_version,
        readback=[v.model_dump(mode="json") for v in p.parameters],
        evidence=p.evidence,
    )
    _, observed, expected = laboratory.confirmation_basis(tx, context, value)
    require(
        p.parameter_digest == observed
        and p.confirmation_matches == (observed == expected),
        "PLC observed digest/match declaration mismatch",
    )
    return value if p.confirmation_matches else None


def project(tx, context, fact):
    value = command(tx, context, fact)
    if value is None:
        return None
    return (
        laboratory.record_calibration(tx, context, value)
        if fact.payload.fact_type == "product_test.calibration"
        else laboratory.confirm_calibration(tx, context, value)
    )
