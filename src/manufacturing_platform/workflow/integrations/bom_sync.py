"""Exact PDM BOM response and SAP master-data gate, including replacement WOs."""

import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from .core_guards import require
from .core_mes_contexts import released_revision
from .contracts import DeliveryReceipt
from .store import identity


def bom_digest(materials):
    content = sorted(
        [m.model_dump(mode="json") for m in materials], key=lambda m: m["material_id"]
    )
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def emit_confirmation(system, tx, delivery, observations):
    request = delivery.fact
    if request.payload.fact_type != "sap.bom_request":
        return
    revision = observations.fact(
        released_revision(observations, request.payload.work_order_id)
    )
    p = revision.payload
    require(
        revision.source_key in request.caused_by
        and p.revision == request.payload.requested_revision
        and [m.material_id for m in p.bom_materials] == request.payload.material_ids,
        "BOM request differs from actual released revision",
    )
    system.emit(
        tx,
        system.child(
            delivery,
            dict(
                fact_type="pdm.bom_confirmation",
                request=request.source_key,
                released_revision=revision.source_key,
                work_order_id=request.payload.work_order_id,
                bom_materials=[m.model_dump(mode="json") for m in p.bom_materials],
                bom_digest=bom_digest(p.bom_materials),
            ),
        ),
    )


def plan_causes(system, operation, observations):
    from ..orders import own

    causes = []
    grouped = defaultdict(list)
    for req in operation.payload.requirements:
        grouped[req.work_order_id].append(req)
    with system.registry.workflow_store.transaction() as tx:
        for wid, requirements in grouped.items():
            revision = observations.fact(released_revision(observations, wid))
            confirmations = [
                f
                for f in observations.of_type("pdm.bom_confirmation")
                if f.payload.work_order_id == wid
                and f.payload.released_revision == revision.source_key
            ]
            require(
                bool(confirmations),
                "Exact work-order BOM confirmation required before planning",
            )
            confirmed = confirmations[-1]
            request = observations.fact(confirmed.payload.request)
            require(
                request.payload.fact_type == "sap.bom_request"
                and request.payload.work_order_id == wid
                and revision.source_key in request.caused_by,
                "BOM confirmation request scope mismatch",
            )
            require(
                confirmed.payload.bom_materials == revision.payload.bom_materials
                and confirmed.payload.bom_digest
                == bom_digest(revision.payload.bom_materials),
                "Confirmed BOM differs from release",
            )
            ack = observations.acks.get(
                (*identity(operation.project_id, confirmed.source_key), "sap")
            )
            require(
                ack is not None
                and DeliveryReceipt.model_validate_json(ack).phase == "accepted",
                "SAP must acknowledge exact BOM confirmation",
            )
            bom = {m.material_id: m.per_unit for m in confirmed.payload.bom_materials}
            wo = own(tx, "effective_work_orders", operation.project_id, wid)
            project = tx.execute(
                "SELECT * FROM projects WHERE id=?", (str(operation.project_id),)
            ).fetchone()
            quantity = Decimal(wo["obligation_atoms"]) / (10 ** project["unit_scale"])
            totals = defaultdict(Decimal)
            for req in requirements:
                expected = bom.get(req.material_id)
                require(
                    expected is not None
                    and (req.amount.unit, req.amount.scale)
                    == (expected.unit, expected.scale),
                    "Plan material/dimensions absent from confirmed BOM",
                )
                totals[req.material_id] += req.amount.quantity
            require(
                set(totals) == set(bom)
                and all(totals[m] == v.quantity * quantity for m, v in bom.items()),
                "Plan material requirements must equal confirmed per-unit BOM times work-order obligation",
            )
            causes.extend(
                [request.source_key, confirmed.source_key, revision.source_key]
            )
    return list({k.model_dump_json(): k for k in causes}.values())


def request_fact(system, operation, observations):
    from ..orders import own

    p = operation.payload
    revision = observations.fact(released_revision(observations, p.work_order_id))
    with system.registry.workflow_store.transaction() as tx:
        own(tx, "work_orders", operation.project_id, p.work_order_id)
        product = tx.execute(
            "SELECT product FROM projects WHERE id=?", (str(operation.project_id),)
        ).fetchone()[0]
    require(
        not any(
            f.payload.work_order_id == p.work_order_id
            and revision.source_key in f.caused_by
            for f in observations.of_type("sap.bom_request")
        ),
        "Exact work-order BOM request already exists",
    )
    return system.make_fact(
        operation.project_id,
        dict(
            fact_type="sap.bom_request",
            work_order_id=p.work_order_id,
            product=product,
            material_ids=[m.material_id for m in revision.payload.bom_materials],
            requested_revision=revision.payload.revision,
        ),
        operation.operation_id,
        causes=[revision.source_key],
    )
