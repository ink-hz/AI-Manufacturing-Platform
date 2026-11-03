"""Typed equipment and test evidence through existing quality admission."""

from .. import orders
from .contracts import AuxiliaryRef, ObjectRef, ProjectionResult
from .core_admission import project_test_fact
from .core_guards import require
from .core_projections import domain_id
from .evidence_models import (
    EquipmentRecord,
    PreparedArtifactRecord,
    ExternalClaimRecord,
    MetricSnapshot,
)
from .store import canonical_hash


def validate_fact(tx, context, fact):
    p = fact.payload
    require(
        fact.project_id == context.project_id
        and fact.source.occurred_at <= fact.source.collected_at <= context.now,
        "Evidence source scope/time mismatch",
    )
    if p.fact_type == "product_test.test":
        from .core_projections import validate_fact as validate_core

        validate_core(tx, context, fact)
    elif p.fact_type in {"customer.customer_approval", "customer.serial_mapping"}:
        from .customer_bridge import command

        command(tx, context, fact)
    elif p.fact_type == "bi.snapshot":
        require(
            p.cutoff <= context.now
            and len({m.metric for m in p.metrics}) == len(p.metrics),
            "Metric cutoff/scope invalid",
        )
        require(
            all(m.numerator <= m.denominator for m in p.metrics),
            "Metric ratio exceeds denominator",
        )
    elif p.fact_type in {
        "customer.acceptance",
        "overseas.delivery_receipt",
        "overseas.return_claim",
    }:
        from .external_claims import validate

        validate(tx, context, fact)
    elif p.fact_type in {"product_test.calibration", "plc.readback"}:
        from .calibration_bridge import command

        command(tx, context, fact)
    elif p.fact_type == "product_test.artifact":
        orders.own(tx, "test_runs", context.project_id, p.prepared.run_id)
        require(
            p.prepared.artifact_ref.project_id == context.project_id,
            "Artifact project mismatch",
        )
    elif p.fact_type == "plc.equipment":
        require(p.observed_at <= context.now, "Future equipment observation")
    elif p.fact_type == "plc.sample":
        unit = orders.own(tx, "units", context.project_id, p.unit_id)
        require(
            unit["work_order_id"] == str(p.work_order_id),
            "PLC sample unit/work order mismatch",
        )
        require(p.observed_at <= context.now, "Future sample observation")
    else:
        require(False, "Evidence fact admission unavailable")


def auxiliary_record(fact):
    if fact.payload.fact_type == "bi.snapshot":
        return MetricSnapshot(
            project_id=fact.project_id,
            source_key=fact.source_key,
            payload_hash=canonical_hash(fact),
            snapshot=fact.payload.model_dump(mode="json"),
        )
    if fact.payload.fact_type in {
        "customer.acceptance",
        "overseas.delivery_receipt",
        "overseas.return_claim",
    }:
        from .external_claims import accepted_units

        accepted = accepted_units(fact.payload)
        return ExternalClaimRecord(
            project_id=fact.project_id,
            source_key=fact.source_key,
            payload_hash=canonical_hash(fact),
            claim=fact.payload.model_dump(mode="json"),
            accepted_unit_ids=sorted(accepted, key=str),
            issue_unit_ids=[
                u.unit_id for u in fact.payload.units if u.unit_id not in accepted
            ],
        )
    if fact.payload.fact_type.startswith("plc."):
        from ..laboratory import digest, parameter_content

        p = fact.payload
        return EquipmentRecord(
            confirmation_state=("matched" if p.confirmation_matches else "mismatched")
            if p.fact_type == "plc.readback"
            else "not_applicable",
            kind=fact.source.object_type,
            project_id=fact.project_id,
            source_key=fact.source_key,
            payload_hash=canonical_hash(fact),
            observation=p.model_dump(mode="json"),
            parameter_digest=digest(parameter_content(p.parameters))
            if hasattr(p, "parameters")
            else None,
        )
    if fact.payload.fact_type == "product_test.artifact":
        return PreparedArtifactRecord(
            project_id=fact.project_id,
            source_key=fact.source_key,
            payload_hash=canonical_hash(fact),
            artifact=fact.payload.model_dump(mode="json"),
        )


def project_fact(tx, context, fact):
    validate_fact(tx, context, fact)
    if fact.payload.fact_type == "product_test.test":
        return project_test_fact(tx, context, fact)
    targets = []
    if fact.payload.fact_type in {
        "customer.customer_approval",
        "customer.serial_mapping",
    }:
        from .customer_bridge import project

        result = project(tx, context, fact)
        targets.append(
            ObjectRef(
                project_id=context.project_id,
                kind=result.object_type,
                id=result.object_id,
            )
        )
    if fact.payload.fact_type in {
        "customer.acceptance",
        "overseas.delivery_receipt",
        "overseas.return_claim",
    }:
        from .external_claims import project

        targets.extend(project(tx, context, fact))
    if fact.payload.fact_type in {"product_test.calibration", "plc.readback"}:
        from .calibration_bridge import project

        result = project(tx, context, fact)
        if result:
            targets.append(
                ObjectRef(
                    project_id=context.project_id,
                    kind=result.object_type,
                    id=result.object_id,
                )
            )
    record = auxiliary_record(fact)
    require(record is not None or targets, "Typed evidence read model required")
    return ProjectionResult(
        project_id=context.project_id,
        source_key=fact.source_key,
        payload_hash=canonical_hash(fact),
        targets=targets,
        auxiliary=[
            AuxiliaryRef(
                project_id=context.project_id, kind=record.kind, id=domain_id(fact)
            )
        ]
        if record
        else [],
    )
