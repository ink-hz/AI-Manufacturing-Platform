"""Reusable prerequisites, exclusively authorized HTTP and explicit source boundary calls.

These helpers supply inputs and check receipts; the production domain owns every
eligibility decision, quantity calculation and transition.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
import hashlib
from urllib.parse import quote

from .fixtures import connect


@dataclass
class Flow:
    api: object
    project: str
    order: str
    quantity: int
    product: str
    revisions: list = field(default_factory=list)
    work_orders: list = field(default_factory=list)
    units: list = field(default_factory=list)
    lots: list = field(default_factory=list)
    requirements: list = field(default_factory=list)
    tests: dict = field(default_factory=dict)
    shipments: list = field(default_factory=list)


def order(context, quantity=100, product="Camera", mode="internal", **contract):
    api = connect(context)
    pid = api.project(str(quantity), product, mode, **contract)
    due = (context.clock + timedelta(days=7)).date().isoformat()
    demand = api.command(
        pid,
        "demand.record",
        kind="firm",
        product=product,
        quantity=str(quantity),
        unit="piece",
        due_date=due,
        source=api.source("demand"),
    )["object_id"]
    for dimension in ("technical", "material", "capacity", "commercial", "quality"):
        api.command(
            pid,
            "demand.review",
            demand_id=demand,
            dimension=dimension,
            decision="approved",
            evidence="Signed " + dimension + " review",
        )
    oid = api.command(
        pid,
        "order.register",
        demand_id=demand,
        quantity=str(quantity),
        unit="piece",
        due_date=due,
        source=api.source("order_line"),
    )["object_id"]
    return Flow(api, pid, oid, quantity, product)


def revision(flow, version="M1", *, customer="C1"):
    api, p = flow.api, flow.project
    printer = flow.product == "3D Printer"
    rid = api.command(
        p,
        "engineering.revision",
        actor="engineering",
        package_id="package-" + flow.product,
        revision=version,
        internal_revision=version,
        customer_revision=customer,
        items=[
            {
                "id": "drawing",
                "kind": "drawing",
                "title": flow.product + " drawing",
                "revision": version,
                "status": "verified",
                "evidence": "Signed product-specific drawing",
            }
        ],
        route_steps=[
            {
                "station": "extruder" if printer else "assembly",
                "instruction_version": "PRINT-S1" if printer else "S1",
            }
        ],
        test_spec={
            "version": "PRINT-T1" if printer else "T1",
            "program_version": "PRINT-P1" if printer else "P1",
            "measurements": [
                {
                    "name": "temperature" if printer else "voltage",
                    "unit": "C" if printer else "V",
                    "lower": "190" if printer else "4",
                    "upper": "210" if printer else "6",
                }
            ],
        },
        firmware_version="F1",
    )["object_id"]
    api.command(
        p,
        "engineering.handoff",
        actor="engineering",
        revision_id=rid,
        to_system="MES",
        received_revision=version,
        decision="accepted",
        evidence="MES signed fixed revision receipt",
    )
    if api.get("/projects/" + p)["contract"]["customer_approval_required"] is True:
        api.command(
            p,
            "engineering.customer_approval",
            revision_id=rid,
            customer_id="Customer 1",
            external_signatory="Customer QE",
            decision="approved",
            evidence="Customer signed " + customer + "/" + version,
        )
    flow.revisions.append(rid)
    return rid


def work_order(flow, quantity, rid=None, *, trial_quantity=1, allocate=True):
    api, p = flow.api, flow.project
    rid = rid or flow.revisions[-1]
    clock = api.context.clock
    wid = api.command(
        p,
        "work_order.register",
        actor="planner",
        order_line_id=flow.order,
        revision_id=rid,
        source=api.source("work_order"),
        quantity=str(quantity),
        unit="piece",
        purpose="production",
        trial_quantity=str(trial_quantity),
        planned_start=clock.isoformat(),
        planned_end=(clock + timedelta(days=1)).isoformat(),
    )["object_id"]
    if allocate:
        api.command(
            p,
            "order.allocate",
            actor="planner",
            order_line_id=flow.order,
            work_order_id=wid,
            quantity=str(quantity),
            unit="piece",
        )
    flow.work_orders.append(wid)
    return wid


def readiness(flow, wid, *, validity=None, decision="verified"):
    api = flow.api
    for kind in ("equipment", "people"):
        api.command(
            flow.project,
            "readiness.record",
            actor="engineering",
            work_order_id=wid,
            kind=kind,
            reference=api.context.identifier(kind),
            evidence="Signed " + kind + " qualification",
            decision=decision,
            valid_until=validity
            or (api.context.clock + timedelta(days=30)).isoformat(),
        )


def plan(flow, specifications=None, *, unit="kg"):
    api = flow.api
    specifications = specifications or [
        (wid, scope, "1", "Customer 1", "steel")
        for wid in flow.work_orders
        for scope in ("trial", "bulk")
    ]
    result = api.command(
        flow.project,
        "plan.receive",
        actor="planner",
        source=api.source("plan"),
        input_revision_ids=flow.revisions,
        input_order_versions=[
            {
                "order_line_id": flow.order,
                "version": api.object(flow.project, "order_line", flow.order)["source"][
                    "version"
                ],
            }
        ],
        requirements=[
            {
                "work_order_id": wid,
                "execution_scope": scope,
                "material_id": material,
                "owner_id": owner,
                "quantity": quantity,
                "unit": unit,
            }
            for wid, scope, quantity, owner, material in specifications
        ],
    )
    flow.requirements = api.object(flow.project, "plan", result["object_id"])[
        "requirement_ids"
    ]
    return flow.requirements


def lot(flow, *, owner="Customer 1", material="steel", expiry=None, unit="kg", scale=3):
    api = flow.api
    lid = api.command(
        flow.project,
        "material.define",
        actor="supply",
        material_id=material,
        lot_id=api.context.identifier("lot"),
        owner_id=owner,
        unit=unit,
        scale=scale,
        expiry=expiry or (api.context.clock + timedelta(days=90)).date().isoformat(),
        source=api.source("material_lot"),
    )["object_id"]
    flow.lots.append(lid)
    return lid


def receive_authority(
    flow, lid, quantity="2", *, accepted=None, rejected="0", commitment=None
):
    api = flow.api
    detail = api.object(flow.project, "material_lot", lid)
    received = api.authority(
        "receive",
        project_id=flow.project,
        external_id=api.context.identifier("WMS-receipt"),
        commitment_id=commitment or api.context.identifier("external-commitment"),
        lot_id=lid,
        material_id=detail["material_id"],
        owner_id=detail["owner_id"],
        quantity=quantity,
        unit=detail["unit"],
        scale=detail["scale"],
        expiry=detail["expiry"],
        external_actor="Simulated WMS",
        signature="Signed simulated warehouse receipt",
    )
    inspected = api.authority(
        "inspect",
        project_id=flow.project,
        external_id=api.context.identifier("QMS-inspection"),
        receipt_external_id=received["source"]["external_id"],
        accepted=accepted if accepted is not None else quantity,
        rejected=rejected,
        external_actor="Simulated QMS",
        signature="Signed simulated IQC result",
    )
    return received, inspected


def reserve(flow, requirement, lid, quantity="1", *, dispatch=True, expected=200):
    api = flow.api
    req = api.object(flow.project, "requirement", requirement)
    intent = api.command(
        flow.project,
        "reservation.request",
        actor="planner",
        expected=expected,
        work_order_id=req["work_order_id"],
        requirement_id=requirement,
        lot_id=lid,
        quantity=quantity,
        unit=req["unit"],
    )
    if expected == 200 and dispatch:
        dispatch_exchange(flow, intent, actor="planner")
    return intent


def dispatch_exchange(flow, result, *, actor, phase="accepted"):
    api = flow.api
    api.command(
        flow.project,
        "exchange.dispatch",
        actor=actor,
        exchange_id=result["exchange_id"],
    )
    actual = api.object(flow.project, "exchange", result["exchange_id"])
    assert actual["phase"] == phase, actual
    return actual


def prepare(flow, *, quantities=None):
    api = flow.api
    for wid in flow.work_orders:
        lot(flow)
    plan(flow)
    for index, wid in enumerate(flow.work_orders):
        readiness(flow, wid)
        lid = flow.lots[index]
        receive_authority(flow, lid)
        for req_id in flow.requirements:
            req = api.object(flow.project, "requirement", req_id)
            if req["work_order_id"] == wid:
                reserve(flow, req_id, lid)
        quantity = int(api.object(flow.project, "work_order", wid)["quantity"])
        api.command(
            flow.project,
            "unit.register",
            actor="production",
            work_order_id=wid,
            sns=[api.context.identifier("SN") for _ in range(quantity)],
        )
    flow.units = [u["id"] for u in api.objects(flow.project, "unit")]
    assert len(flow.units) == (sum(quantities) if quantities else flow.quantity)
    return flow


def start(flow, wid, units, mode="trial", *, expected=200, dispatch=True):
    result = flow.api.command(
        flow.project,
        "production.start",
        actor="production",
        expected=expected,
        work_order_id=wid,
        mode=mode,
        unit_ids=units,
        quantity=str(len(units)),
    )
    if expected == 200 and dispatch:
        dispatch_exchange(flow, result, actor="production")
    return result


def execution(flow, uid, lid, *, rework=None, **overrides):
    api = flow.api
    unit = api.object(flow.project, "unit", uid)
    rev = api.object(flow.project, "revision", unit["revision_id"])
    route = rev["route_steps"][0]
    body = {
        "work_order_id": unit["work_order_id"],
        "sn": unit["sn"],
        "station": "repair" if rework else route["station"],
        "route_version": "RW-S1" if rework else route["instruction_version"],
        "program_version": rev["test_spec"]["program_version"],
        "firmware_version": "F1",
        "material_uses": [{"lot_id": lid, "quantity": "0.001", "unit": "kg"}],
        "result": "pass",
        "occurred_at": api.context.clock.isoformat(),
        "source": api.source("execution"),
        "rework_order_id": rework,
        **overrides,
    }
    result = api.command(flow.project, "execution.record", actor="production", **body)
    return result


def measure(flow, uid, *, value=None, rework=None, expected=200, **overrides):
    api = flow.api
    unit = api.object(flow.project, "unit", uid)
    rev = api.object(flow.project, "revision", unit["revision_id"])
    spec = rev["test_spec"]
    limit = spec["measurements"][0]
    result = api.command(
        flow.project,
        "test.record",
        actor="quality",
        expected=expected,
        **{
            "unit_id": uid,
            "attempt": unit["test_total"] + 1,
            "program_version": spec["program_version"],
            "limit_version": spec["version"],
            "firmware_version": "F1",
            "measurements": [
                {
                    **limit,
                    "value": value or ("200" if flow.product == "3D Printer" else "5"),
                }
            ],
            "source": api.source("test"),
            "rework_order_id": rework,
            **overrides,
        },
    )
    if expected == 200:
        flow.tests[uid] = result["object_id"]
    return result


def run_production(flow, **execution_fields):
    api = flow.api
    for index, wid in enumerate(flow.work_orders):
        ids = [
            uid
            for uid in flow.units
            if api.object(flow.project, "unit", uid)["work_order_id"] == wid
        ]
        start(flow, wid, ids[:1])
        execution(flow, ids[0], flow.lots[index], **execution_fields)
        measure(flow, ids[0])
        api.command(
            flow.project,
            "first_article.record",
            actor="quality",
            work_order_id=wid,
            unit_ids=ids[:1],
            test_ids=[flow.tests[ids[0]]],
            inspection_id=api.context.identifier("FAI"),
        )
        if len(ids) > 1:
            start(flow, wid, ids[1:], mode="bulk")
            for uid in ids[1:]:
                execution(flow, uid, flow.lots[index], **execution_fields)
                measure(flow, uid)
    return flow


def release(flow, units=None, *, customer=True):
    api = flow.api
    units = units or flow.units
    for actor, kind in [("production", "manufacturing"), ("quality", "quality")]:
        api.command(
            flow.project,
            "release.decide",
            actor=actor,
            kind=kind,
            unit_ids=units,
            decision="approved",
            evidence="Independent qualified " + kind + " release",
        )
    if (
        customer
        and api.get("/projects/" + flow.project)["contract"][
            "customer_release_required"
        ]
        is True
    ):
        for rid in flow.revisions:
            group = [
                u
                for u in units
                if api.object(flow.project, "unit", u)["revision_id"] == rid
            ]
            if group:
                api.command(
                    flow.project,
                    "release.decide",
                    kind="customer",
                    unit_ids=group,
                    decision="approved",
                    evidence="Customer signed final product release",
                    customer_id="Customer 1",
                    revision_id=rid,
                    customer_revision="C1",
                    external_signatory="Customer QE",
                    method="manual",
                    source=api.source("customer_release"),
                )
    return flow


def released(context, quantity=1, splits=None, product="Camera", mode="internal"):
    flow = order(context, quantity, product, mode)
    rid = revision(flow)
    for q in splits or [quantity]:
        work_order(flow, q, rid)
    return release(run_production(prepare(flow)))


def ship(flow, units, *, expected=200, dispatch=True, quantity=None):
    result = flow.api.command(
        flow.project,
        "shipment.request",
        actor="warehouse",
        expected=expected,
        order_line_id=flow.order,
        unit_ids=units,
        boxes=[],
        quantity=quantity or str(len(units)),
        unit="piece",
    )
    if expected == 200:
        if dispatch:
            dispatch_exchange(flow, result, actor="warehouse", phase="accepted")
        flow.shipments.append(result["object_id"])
    return result


def accept(flow, shipment, quantity, *, issues=None, sign=True):
    if sign:
        flow.api.command(
            flow.project,
            "delivery.sign",
            actor="warehouse",
            shipment_id=shipment,
            quantity=str(quantity),
            source=flow.api.source("delivery_sign"),
            external_signatory="Customer receiving officer",
        )
    return flow.api.command(
        flow.project,
        "delivery.accept",
        actor="warehouse",
        shipment_id=shipment,
        quantity=str(quantity),
        source=flow.api.source("delivery_accept"),
        external_signatory="Customer acceptance officer",
        issues=issues or [],
    )


def closure(flow, kind, *, expected=200):
    api = flow.api
    source = api.source(
        "closure",
        system="Simulated ERP cost receipt"
        if kind == "cost"
        else "Signed acceptance review",
    )
    if kind == "cost":
        receipt = {
            "receipt_id": source["external_id"],
            "project_id": flow.project,
            "source_system": source["system"],
            "occurred_at": api.context.clock.isoformat(),
            "external_signatory": "Simulated ERP costing clerk",
            "decision": "cost_closed",
            "boundary": "Synthetic external receipt manually recorded through closure.record; no ERP API or accounting voucher",
        }
        artifact = api.context.evidence.record("external-erp-cost-receipt", receipt)
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        source["evidence"] = (
            f"Manual transcription of synthetic ERP receipt {receipt['receipt_id']}; file SHA256 {digest}; signed by {receipt['external_signatory']}"
        )
    result = api.command(
        flow.project,
        "closure.record",
        kind=kind,
        source=source,
        evidence="Signed independent " + kind + " closure",
        expected=expected,
    )
    if expected == 200:
        value = api.object(flow.project, "closure", result["object_id"])
        assert value["status"] == "closed"
        assert (
            value["source"]["mode"] == "manual"
            and value["source"]["external_id"] == source["external_id"]
        )
    return result


def feedback(flow, uid=None, shipment=None, *, close=True):
    api = flow.api
    rma = api.command(
        flow.project,
        "rma.open",
        actor="quality",
        unit_id=uid or flow.units[0],
        shipment_id=shipment or flow.shipments[0],
        reason="Delivered product handling feedback",
        source=api.source("rma"),
    )["object_id"]
    capa = None
    for step in ("containment", "root_cause", "correction", "verification"):
        extra = (
            {
                "action_kind": "training",
                "implementation_evidence": "Customer handling instruction revised and training attendance signed",
            }
            if step == "correction"
            else {"effective": True}
            if step == "verification"
            else {}
        )
        capa = api.command(
            flow.project,
            "capa.update",
            actor="quality",
            rma_id=rma,
            capa_id=capa,
            step=step,
            description="Documented " + step,
            evidence="Signed " + step,
            **extra,
        )["object_id"]
    if close:
        api.command(flow.project, "capa.close", actor="quality", capa_id=capa)
    return rma, capa


def assert_trace(flow, uid):
    api = flow.api
    detail = api.object(flow.project, "unit", uid)
    trace = api.get("/projects/" + flow.project + "/trace?sn=" + quote(detail["sn"]))
    assert (
        detail["revision_id"] in str(trace)
        and uid in str(trace)
        and flow.order in str(trace)
    )
    return trace


def repair(flow, uid, lid):
    api = flow.api
    nc = api.command(
        flow.project,
        "nonconformance.open",
        actor="quality",
        test_id=flow.tests[uid],
        defect="Measured trial defect",
        evidence="Original failed result retained",
    )["object_id"]
    rw = api.command(
        flow.project,
        "nonconformance.disposition",
        actor="quality",
        nonconformance_id=nc,
        decision="rework",
        route_id="RW-1",
        route_steps=[{"station": "repair", "instruction_version": "RW-S1"}],
        evidence="Qualified repair route",
    )["object_id"]
    execution(flow, uid, lid, rework=rw)
    result = measure(flow, uid, rework=rw)
    unit = api.object(flow.project, "unit", uid)
    api.command(
        flow.project,
        "rework.complete",
        actor="quality",
        rework_order_id=rw,
        execution_event_ids=[unit["execution_events"][-1]["id"]],
        test_ids=[result["object_id"]],
    )
    assert api.object(flow.project, "nonconformance", nc)["state"] == "resolved"
    return nc, rw


def switch_revision(flow, old_wid, new_rid):
    api = flow.api
    old = api.object(flow.project, "work_order", old_wid)
    eco = api.command(
        flow.project,
        "eco.open",
        actor="engineering",
        old_revision_id=old["revision_id"],
        new_revision_id=new_rid,
        effective_work_order_ids=[old_wid],
        reason="Approved engineering correction",
    )["object_id"]
    api.command(
        flow.project, "eco.close", actor="engineering", eco_id=eco, expected=409
    )
    result = api.command(
        flow.project,
        "eco.switch",
        actor="engineering",
        eco_id=eco,
        target_work_order_id=old_wid,
        new_revision_id=new_rid,
        boundary="split_remaining",
        evidence="Explicit unexecuted scope switch",
    )
    dispatch_exchange(flow, result, actor="engineering")
    return eco, result["object_id"]


def dispose_eco(flow, eco):
    api = flow.api
    for impact in api.object(flow.project, "eco", eco)["impacts"]:
        remaining = Decimal(impact["quantity"]) - Decimal(impact["resolved_quantity"])
        if remaining > 0:
            api.command(
                flow.project,
                "eco.disposition",
                actor="engineering",
                eco_id=eco,
                impact_id=impact["id"],
                quantity=str(remaining),
                decision="use_old",
                evidence="Reviewed original stock/WIP retained under original applicability",
            )
    api.command(flow.project, "eco.close", actor="engineering", eco_id=eco)
