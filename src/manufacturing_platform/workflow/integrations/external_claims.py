"""Shipment-scoped external claims and honestly derived per-unit RMA work."""

from uuid import UUID, uuid5
from .. import orders, delivery
from ..delivery_models import DeliverySign, DeliveryAccept
from .contracts import ObjectRef
from .core_projections import command_data, domain_id
from .core_guards import require
from .enterprise_admission import projected_fact
from .store import canonical_hash, identity

RETURN_TAGS = {"crm.return_claim", "overseas.return_claim"}
DELIVERY_TAGS = {"customer.acceptance", "overseas.delivery_receipt"}


def accepted_units(payload):
    if getattr(payload, "decision", None) == "accepted":
        return {u.unit_id for u in payload.units}
    return set(getattr(payload, "accepted_unit_ids", []))


def source_causes(payload, observations):
    shipment = observations.fact(payload.shipment)
    p = shipment.payload
    require(
        p.fact_type == "wms.shipment" and p.shipment_id == payload.shipment_id,
        "Exact actual shipment required",
    )
    selected = {(u.unit_id, u.sn) for u in payload.units}
    require(
        selected <= {(u.unit_id, u.sn) for u in p.units},
        "Claim serials differ from physical shipment",
    )
    contexts = [
        f
        for f in observations.of_type("mes.delivery_context")
        if f.payload.shipment == payload.shipment
    ]
    covered = set()
    causes = [shipment.source_key]
    for context in contexts:
        scope = {(u.unit_id, u.sn) for u in context.payload.units}
        if selected & scope:
            require(not covered & scope, "Ambiguous delivery context coverage")
            covered |= scope
            causes.append(context.source_key)
    require(
        selected <= covered,
        "Actual MES context required for every claimed unit/work order",
    )
    return causes


def command(context, fact):
    p = fact.payload
    count = len(accepted_units(p))
    if count == 0:
        return None
    cls = DeliveryAccept if p.fact_type == "customer.acceptance" else DeliverySign
    return cls(
        **command_data(context),
        action="delivery.accept" if cls is DeliveryAccept else "delivery.sign",
        shipment_id=p.shipment_id,
        quantity=str(count),
        source=fact.source,
        external_signatory=p.external_signer,
    )


def validate(tx, context, fact):
    p = fact.payload
    project = orders.project(tx, context.project_id)
    require(
        (p.customer_id, p.amount.unit, p.amount.scale)
        == (project["customer_id"], project["unit_code"], project["unit_scale"]),
        "Claim customer/dimensions mismatch",
    )
    require(p.occurred_at <= context.now, "Claim occurrence is in the future")
    shipment = projected_fact(
        tx, context.project_id, p.shipment, kind="shipment", ident=p.shipment_id
    )
    require(
        shipment.payload.fact_type == "wms.shipment",
        "Claim needs WMS physical shipment",
    )
    require(
        shipment.source.occurred_at <= p.occurred_at,
        "Claim predates actual physical shipment",
    )
    for unit in p.units:
        row = orders.own(tx, "units", context.project_id, unit.unit_id)
        require(
            row["sn"] == unit.sn
            and tx.execute(
                "SELECT 1 FROM shipment_items WHERE project_id=? AND shipment_id=? AND unit_id=?",
                (str(context.project_id), str(p.shipment_id), str(unit.unit_id)),
            ).fetchone()
            is not None,
            "Exact accepted shipped serial membership required",
        )
        if p.fact_type in RETURN_TAGS:
            from ..feedback import validate_rma

            validate_rma(tx, context, unit.unit_id, p.shipment_id)
    if p.fact_type in DELIVERY_TAGS:
        value = command(context, fact)
        if value:
            delivery.validate_delivery_fact(tx, context, value)
        # Per-unit counts prevent a different external document accepting the same SN twice.
        from .contracts import IntegrationFact

        for row in tx.execute(
            "SELECT fact_json FROM integration_projections WHERE project_id=? AND system=? AND object_type=?",
            (str(context.project_id), fact.source.system, fact.source.object_type),
        ):
            prior = IntegrationFact.model_validate_json(row[0])
            require(
                not accepted_units(prior.payload) & accepted_units(p),
                "Serial already confirmed by this counterparty",
            )


def project(tx, context, fact):
    validate(tx, context, fact)
    p = fact.payload
    if p.fact_type in DELIVERY_TAGS:
        value = command(context, fact)
        if value:
            delivery._record_fact(tx, context, value)
        return [
            ObjectRef(project_id=context.project_id, kind="shipment", id=p.shipment_id)
        ]
    refs = []
    for member in p.units:
        uid = str(member.unit_id)
        ident = uuid5(domain_id(fact), uid)
        from ..feedback import _persist_rma

        _persist_rma(
            tx,
            context,
            unit_id=member.unit_id,
            shipment_id=p.shipment_id,
            reason=p.reason,
            source=fact.source,
            derived_id=ident,
        )
        tx.execute(
            "INSERT INTO integration_return_units VALUES (?,?,?,?,?,?,?,?)",
            (
                *identity(context.project_id, fact.source_key),
                canonical_hash(fact),
                uid,
                str(ident),
            ),
        )
        refs.append(ObjectRef(project_id=context.project_id, kind="rma", id=ident))
    return refs


def admitted_return(tx, pid, row, source):
    from pydantic import ValidationError
    from ..contracts import DomainError

    try:
        fact = projected_fact(tx, UUID(str(pid)), source, kind="rma", ident=row["id"])
        p = fact.payload
        mapping = tx.execute(
            "SELECT * FROM integration_return_units WHERE project_id=? AND rma_id=?",
            (str(pid), row["id"]),
        ).fetchone()
        if (
            not mapping
            or p.fact_type not in RETURN_TAGS
            or fact.source.model_dump() != source.model_dump()
            or mapping["payload_hash"] != canonical_hash(fact)
        ):
            return None
        if (row["source_system"], row["source_type"], row["source_external_id"]) != (
            "platform-derived",
            "rma_unit",
            row["id"],
        ):
            return None
        if tuple(
            mapping[k]
            for k in ("project_id", "system", "object_type", "external_id", "version")
        ) != identity(pid, fact.source_key):
            return None
        if (
            str(p.shipment_id) != row["shipment_id"]
            or p.customer_id != row["customer_id"]
            or p.reason != row["reason"]
            or not any(str(u.unit_id) == row["unit_id"] for u in p.units)
        ):
            return None
        return source
    except (DomainError, ValidationError, ValueError, KeyError, IndexError):
        return None


def admitted_delivery(tx, pid, row, source):
    from pydantic import ValidationError
    from ..contracts import DomainError

    try:
        if (source.system, source.object_type, source.external_id) != (
            row["source_system"],
            row["source_type"],
            row["source_external_id"],
        ) or str(row["project_id"]) != str(pid):
            return None
        fact = projected_fact(
            tx, UUID(str(pid)), source, kind="shipment", ident=row["shipment_id"]
        )
        if (
            fact.payload.fact_type not in DELIVERY_TAGS
            or source.model_dump() != fact.source.model_dump()
        ):
            return None
        p = orders.project(tx, pid)
        expected = (
            "accept" if fact.payload.fact_type == "customer.acceptance" else "sign"
        )
        if (
            row["action"] != expected
            or row["q_atoms"]
            != len(accepted_units(fact.payload)) * 10 ** p["unit_scale"]
            or row["external_signatory"] != fact.payload.external_signer
        ):
            return None
        return source
    except (DomainError, ValidationError, ValueError, KeyError, IndexError):
        return None
