"""Distinct customer design decisions and actual shipped-SN aliases."""

from typing import Literal
from .. import orders, engineering, laboratory
from ..engineering_models import RecordCustomerApproval
from ..laboratory_models import AliasUnit
from .core_projections import command_data, domain_id
from .core_guards import require
from .enterprise_admission import projected_fact
from .contracts import IntegrationFact


class TrustedCustomerApproval(RecordCustomerApproval):
    method: Literal["mock"] = "mock"


def command(tx, context, fact):
    p = fact.payload
    project = orders.project(tx, context.project_id)
    require(p.customer_id == project["customer_id"], "Actual project customer required")
    if p.fact_type == "customer.customer_approval":
        revision = projected_fact(
            tx, context.project_id, p.revision, kind="revision", ident=p.revision_id
        )
        require(
            revision.payload.fact_type == "pdm.revision"
            and revision.source.occurred_at <= p.signed_at <= context.now,
            "Customer approval revision/time mismatch",
        )
        return TrustedCustomerApproval(
            **command_data(context),
            action="engineering.customer_approval",
            revision_id=p.revision_id,
            decision=p.decision,
            customer_id=p.customer_id,
            external_signatory=p.external_signer,
            evidence=p.evidence,
        )
    shipment = projected_fact(tx, context.project_id, p.shipment)
    require(
        shipment.payload.fact_type == "wms.shipment"
        and any(u.unit_id == p.unit_id for u in shipment.payload.units),
        "Customer serial requires exact actual shipment member",
    )
    value = AliasUnit(
        **command_data(context),
        action="unit.alias",
        unit_id=p.unit_id,
        customer_serial=p.customer_serial,
        evidence=p.evidence,
    )
    laboratory.validate_alias(tx, context, value)
    return value


def project(tx, context, fact):
    value = command(tx, context, fact)
    if fact.payload.fact_type == "customer.customer_approval":
        return engineering.record_customer_approval(
            tx, context, value, approval_id=domain_id(fact)
        )
    return laboratory.alias(tx, context, value)


def admitted_approval(tx, pid, row):
    for candidate in tx.execute(
        "SELECT fact_json FROM integration_projections WHERE project_id=? AND system='customer' AND object_type='customer_approval'",
        (str(pid),),
    ):
        fact = IntegrationFact.model_validate_json(candidate[0])
        if str(domain_id(fact)) != row["id"]:
            continue
        p = fact.payload
        projected_fact(
            tx,
            fact.project_id,
            fact.source_key,
            kind="revision",
            ident=row["revision_id"],
        )
        if (
            str(p.revision_id),
            p.customer_id,
            p.external_signer,
            p.decision,
            p.evidence,
        ) == (
            row["revision_id"],
            row["customer_id"],
            row["external_signatory"],
            row["decision"],
            row["evidence"],
        ):
            return fact.source
    return None
