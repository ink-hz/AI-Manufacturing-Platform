"""Exact typed source admission for trusted execution and qualified laboratory tests."""

import json
from uuid import UUID
from .. import orders
from .contracts import ObjectRef, ProjectionResult
from .core_guards import require
from .store import canonical_hash


def command_data(context):
    return dict(operation_id=UUID(int=0), expected_version=context.project_version)


def execution_command(context, fact):
    from ..execution_models import RecordExecution

    p = fact.payload
    require(p.fact_type == "mes.execution", "Trusted execution type required")
    return RecordExecution(
        **command_data(context),
        action="execution.record",
        source=fact.source,
        work_order_id=p.work_order_id,
        sn=p.unit.sn,
        station=p.station,
        route_version=p.route_version,
        program_version=p.program_version,
        firmware_version=p.firmware_version,
        material_uses=[
            dict(
                lot_id=a.material_lot_id,
                quantity=str(a.amount.quantity),
                unit=a.amount.unit,
            )
            for a in p.material_uses
        ],
        result=p.result,
        occurred_at=p.occurred_at,
        rework_order_id=p.rework_order_id,
        supersedes_event_id=p.supersedes_event_id,
    )


def validate_execution_admission(tx, context, command, fact):
    from .contracts import IntegrationFact

    fact = IntegrationFact.model_validate_json(fact.model_dump_json())
    require(
        fact.project_id == context.project_id
        and fact.source.mode == "mock"
        and fact.payload.fact_type == "mes.execution",
        "Exact trusted MES execution required",
    )
    require(
        execution_command(context, fact).model_dump() == command.model_dump(),
        "Execution envelope differs from source fact",
    )
    unit = orders.own(tx, "units", context.project_id, fact.payload.unit.unit_id)
    require(
        (unit["work_order_id"], unit["revision_id"], unit["sn"])
        == (
            str(fact.payload.work_order_id),
            str(fact.payload.revision_id),
            fact.payload.unit.sn,
        ),
        "Trusted execution unit scope mismatch",
    )
    for a in fact.payload.material_uses:
        lot = orders.own(tx, "material_lots", context.project_id, a.material_lot_id)
        require(
            (lot["material_id"], lot["owner_id"], lot["unit"], lot["scale"])
            == (a.material_id, a.owner_id, a.amount.unit, a.amount.scale),
            "Execution material scope mismatch",
        )
    require(
        fact.source.occurred_at <= fact.source.collected_at <= context.now
        and fact.payload.occurred_at <= context.now,
        "Execution timestamp invalid",
    )


def test_command(context, fact):
    from ..quality_models import RecordTest

    p = fact.payload
    require(p.fact_type == "product_test.test", "Exact product-test fact required")
    return RecordTest(
        **command_data(context),
        action="test.record",
        source=fact.source,
        unit_id=p.unit_id,
        attempt=p.attempt,
        program_version=p.program_version,
        limit_version=p.test_version,
        firmware_version=p.firmware_version,
        measurements=[m.model_dump(mode="json") for m in p.measurements],
        rework_order_id=p.rework_order_id,
    )


def validate_test_admission(tx, context, command, fact, *, check_running=True):
    from ..laboratory import current_basis
    from .contracts import IntegrationFact

    fact = IntegrationFact.model_validate_json(fact.model_dump_json())
    p = fact.payload
    require(
        fact.project_id == context.project_id
        and fact.source.mode == "mock"
        and p.fact_type == "product_test.test",
        "Exact trusted product-test source required",
    )
    require(
        test_command(context, fact).model_dump() == command.model_dump(),
        "Test envelope differs from source fact",
    )
    unit = orders.own(tx, "units", context.project_id, p.unit_id)
    require(
        (unit["work_order_id"], unit["revision_id"])
        == (str(p.work_order_id), str(p.revision_id)),
        "Test unit scope mismatch",
    )
    plan = json.loads(
        orders.own(tx, "test_plans", context.project_id, p.plan_id)["payload_json"]
    )
    run_row = orders.own(tx, "test_runs", context.project_id, p.run_id)
    run = json.loads(run_row["payload_json"])
    require(
        (run["unit_id"], run["revision_id"], run["plan_id"], run["rework_order_id"])
        == (
            str(p.unit_id),
            str(p.revision_id),
            str(p.plan_id),
            str(p.rework_order_id) if p.rework_order_id else None,
        ),
        "Test run scope mismatch",
    )
    require(
        (
            plan["revision_id"],
            plan["station"],
            plan["equipment"],
            plan["fixture"],
            plan["algorithm_version"],
        )
        == (str(p.revision_id), p.station, p.equipment, p.fixture, p.algorithm_version),
        "Test plan/equipment/version mismatch",
    )
    require(
        fact.source.occurred_at == p.occurred_at
        and p.occurred_at <= fact.source.collected_at <= context.now,
        "Test occurrence mismatch",
    )
    require(
        p.result
        == (
            "pass"
            if all(m.lower <= m.value <= m.upper for m in p.measurements)
            else "fail"
        ),
        "Test result differs from measured result",
    )
    if check_running:
        require(run_row["finish_json"] is None, "Finished test run is immutable")
        scope, events = current_basis(tx, context, unit, p.rework_order_id)
        require(
            scope == run["scope"]
            and events == run["execution_event_ids"]
            and unit["accepted_start_id"] == run["accepted_start_id"],
            "Captured run eligibility changed",
        )


def project_test_fact(tx, context, fact):
    from ..laboratory import _finish
    from typing import Literal
    from ..commands import WorkflowCommand
    from ..quality_models import Measurement
    from .contracts import MockSourceRef
    from .evidence_models import MockRawEvidence

    class TrustedFinish(WorkflowCommand):
        action: Literal["test_run.finish"]
        run_id: UUID
        state: Literal["completed"]
        source: MockSourceRef
        measurements: list[Measurement]
        raw: MockRawEvidence
        reason: None = None

    p = fact.payload
    command = TrustedFinish(
        **command_data(context),
        action="test_run.finish",
        run_id=p.run_id,
        state="completed",
        source=fact.source,
        measurements=[m.model_dump(mode="json") for m in p.measurements],
        raw=p.raw.model_dump(mode="json"),
    )
    _finish(tx, context, command, trusted_fact=fact)
    row = orders.own(tx, "test_runs", context.project_id, p.run_id)
    finish = json.loads(row["finish_json"])
    return ProjectionResult(
        project_id=context.project_id,
        source_key=fact.source_key,
        payload_hash=canonical_hash(fact),
        targets=[
            ObjectRef(project_id=context.project_id, kind="test", id=finish["test_id"]),
            ObjectRef(project_id=context.project_id, kind="test_run", id=p.run_id),
        ],
    )


def admitted_component_source(tx, project_id, row):
    """A component's source is attributable only through its exact typed projection."""
    from pydantic import ValidationError
    from ..contracts import SourceRef
    from .contracts import IntegrationFact
    from .store import identity

    try:
        data = json.loads(row["payload_json"])
        source = SourceRef.model_validate(data.get("source"))
        projected = tx.execute(
            "SELECT * FROM integration_projections WHERE project_id=? AND system=? AND object_type=? AND external_id=? AND version=?",
            identity(project_id, source),
        ).fetchone()
        if not projected:
            return None
        fact = IntegrationFact.model_validate_json(projected["fact_json"])
        result = ProjectionResult.model_validate_json(projected["result_json"])
        p = fact.payload
        if (
            fact.project_id != UUID(str(project_id))
            or fact.source.model_dump() != source.model_dump()
            or p.fact_type != "mes.component"
            or row["project_id"] != str(project_id)
        ):
            return None
        if (
            projected["payload_hash"] != canonical_hash(fact)
            or result.payload_hash != canonical_hash(fact)
            or result.source_key != fact.source_key
            or result.project_id != fact.project_id
        ):
            return None
        if not any(
            t.project_id == fact.project_id
            and t.kind.value == "component_link"
            and str(t.id) == row["id"]
            for t in result.targets
        ):
            return None
        if (
            data["unit_id"],
            data["material_id"],
            data["component_serial"],
            data["lot_id"],
            data["evidence"],
            data["origin"],
        ) != (
            str(p.unit_id),
            p.material_id,
            p.component_serial,
            str(p.material_lot_id),
            p.evidence,
            "demo",
        ):
            return None
        return source
    except (ValidationError, ValueError, KeyError, TypeError):
        return None
