"""E01–E10: original commitment, engineering and material acceptance cases."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import json

from .business import (
    order,
    revision,
    work_order,
    prepare,
    start,
    execution,
    lot,
    plan,
    reserve,
    receive_authority,
    dispatch_exchange,
    switch_revision,
)
from .fixtures import connect


def material_case(
    context, qualified="80", *, quantity=100, required="100", second=False
):
    flow = order(context, quantity)
    rid = revision(flow)
    work_order(flow, quantity // 2 if second else quantity, rid)
    if second:
        work_order(flow, quantity - quantity // 2, rid)
    lid = lot(flow, unit="piece", scale=0)
    plan(
        flow,
        [(w, "trial", required, "Customer 1", "steel") for w in flow.work_orders],
        unit="piece",
    )
    req = flow.requirements[0]
    api = flow.api
    due = (context.clock + timedelta(days=1)).date().isoformat()
    commitment = api.command(
        flow.project,
        "supply.commit",
        actor="supply",
        requirement_id=req,
        type="customer",
        owner_id="Customer 1",
        quantity=required,
        unit="piece",
        original_due=due,
        current_due=due,
        source=api.source("commitment"),
    )["object_id"]
    if qualified != "0":
        arrival(flow, lid, commitment, qualified)
    return flow, req, lid, commitment


def arrival(flow, lid, commitment, received, accepted=None, rejected="0"):
    receipt, iqc = receive_authority(
        flow, lid, received, accepted=accepted, rejected=rejected, commitment=commitment
    )
    for actor, kind, record in [
        ("supply", "receipt", receipt),
        ("quality", "iqc", iqc),
    ]:
        flow.api.command(
            flow.project,
            "source.pull",
            actor=actor,
            system="erp",
            object_type=kind,
            external_id=record["source"]["external_id"],
        )
    return receipt, iqc


def e01(context):
    api = connect(context)
    pid = api.project("100")
    due = (context.clock + timedelta(days=7)).date().isoformat()
    forecast = api.command(
        pid,
        "demand.record",
        kind="forecast",
        product="Camera",
        quantity="100",
        unit="piece",
        due_date=due,
        source=api.source("demand"),
    )["object_id"]
    api.command(
        pid,
        "order.register",
        expected=409,
        demand_id=forecast,
        quantity="100",
        unit="piece",
        due_date=due,
        source=api.source("order_line"),
    )
    firm = api.command(
        pid,
        "demand.record",
        kind="firm",
        product="Camera",
        quantity="100",
        unit="piece",
        due_date=due,
        source=api.source("demand"),
        supersedes_demand_id=forecast,
    )["object_id"]
    for dimension in ("technical", "material", "capacity", "commercial", "quality"):
        api.command(
            pid,
            "demand.review",
            demand_id=firm,
            dimension=dimension,
            decision="approved",
            evidence="Signed review",
        )
    source = api.source("order_line", system="Simulated ERP")
    oid = api.command(
        pid,
        "order.register",
        demand_id=firm,
        quantity="100",
        unit="piece",
        due_date=due,
        source=source,
    )["object_id"]
    api.command(
        pid,
        "order.register",
        expected=409,
        demand_id=firm,
        quantity="100",
        unit="piece",
        due_date=due,
        source=source,
    )
    assert (
        len(api.objects(pid, "order_line")) == 1
        and len(api.objects(pid, "demand")) == 2
    )
    assert api.object(pid, "order_line", oid)["original_quantity"] == "100"
    context.actual.update(forecast=forecast, firm=firm, order=oid, duplicate_orders=0)


def e02(context):
    flow = order(context, 10)
    rid = revision(flow)
    wid = work_order(flow, 10, rid)
    prepare(flow)
    api, p = flow.api, flow.project
    start(flow, wid, flow.units[:1])
    execution(flow, flow.units[0], flow.lots[0])
    req = flow.requirements[0]
    due = (context.clock + timedelta(days=1)).date().isoformat()
    api.command(
        p,
        "supply.commit",
        actor="supply",
        requirement_id=req,
        type="purchase",
        owner_id="Customer 1",
        quantity="1",
        unit="kg",
        original_due=due,
        current_due=due,
        source=api.source("commitment"),
    )
    original = api.object(p, "order_line", flow.order)
    change = api.command(
        p,
        "order.change",
        order_line_id=flow.order,
        new_quantity="8",
        cancel=False,
        new_due_date=(context.clock + timedelta(days=8)).date().isoformat(),
        reason="Customer reduction and postponement",
        source={**original["source"], "version": 2},
    )["object_id"]
    value = api.object(p, "commitment_change", change)
    assert value["state"] == "pending" and value["impacts"]
    current = api.object(p, "order_line", flow.order)
    assert current["original_quantity"] == "10" and current["allocated"] == "10"
    api.command(
        p, "order.resolve_change", expected=409, change_id=change, dispositions=[]
    )
    assert api.object(p, "unit", flow.units[0])["execution_event_total"] == 1
    context.actual.update(
        original_quantity="10",
        allocated="10",
        change_state=value["state"],
        impacts=value["impacts"],
    )


def e03(context):
    flow = order(context, 1, mode="oem")
    api, p = flow.api, flow.project
    correct = revision(flow)
    wid = work_order(flow, 1, correct)
    prepare(flow)
    api.command(
        p,
        "engineering.customer_approval",
        revision_id=correct,
        customer_id="Customer 1",
        external_signatory="Customer QE",
        decision="unknown",
        evidence="Customer approval not yet confirmed",
    )
    wrong = revision(flow, "M2", customer="C-WRONG")
    before = api.object(p, "work_order", wid)["trial_readiness"]
    assert (
        next(c for c in before["checks"] if c["kind"] == "customer")["status"]
        == "blocked"
    )
    api.command(
        p,
        "engineering.customer_approval",
        revision_id=correct,
        customer_id="Customer 1",
        external_signatory="Customer QE",
        decision="approved",
        evidence="Correct C1/M1 approval",
    )
    after = api.object(p, "work_order", wid)["trial_readiness"]
    assert (
        next(c for c in after["checks"] if c["kind"] == "customer")["status"] == "ready"
    )
    assert len(api.object(p, "revision", correct)["customer_approvals"]) == 3
    assert api.object(p, "revision", wrong)["customer_revision"] == "C-WRONG"
    context.actual.update(
        wrong_revision=wrong,
        correct_revision=correct,
        wrong_and_correct_receipts_retained=True,
    )


def e04(context):
    from .business import measure

    flow = order(context, 20)
    old = revision(flow)
    wid = work_order(flow, 20, old, trial_quantity=5)
    prepare(flow)
    api, p = flow.api, flow.project
    first = flow.units[:5]
    start(flow, wid, first)
    for uid in first:
        execution(flow, uid, flow.lots[0])
        measure(flow, uid)
    history = [api.object(p, "unit", uid)["execution_events"] for uid in first]
    new = revision(flow, "M2")
    eco, replacement = switch_revision(flow, wid, new)
    api.command(p, "eco.close", actor="engineering", eco_id=eco, expected=409)
    assert api.object(p, "work_order", wid)["quantity"] == "20"
    assert api.object(p, "work_order", wid)["remaining_obligation"] == "5"
    assert api.object(p, "work_order", replacement)["quantity"] == "15"
    api.command(
        p,
        "unit.register",
        actor="production",
        work_order_id=replacement,
        sns=[context.identifier("M2-SN") for _ in range(15)],
    )
    # Summaries intentionally omit detailed lineage; inspect each bound unit.
    new_units = [
        u["id"]
        for u in api.objects(p, "unit")
        if api.object(p, "unit", u["id"])["work_order_id"] == replacement
    ]
    assert len(new_units) == 15 and all(
        api.object(p, "unit", u)["revision_id"] == new for u in new_units
    )
    impacts = api.object(p, "eco", eco)["impacts"]
    assert any(i["type"] == "stock" for i in impacts)
    for uid, events in zip(first, history):
        value = api.object(p, "unit", uid)
        assert value["revision_id"] == old and value["execution_events"] == events
    context.actual.update(
        old_effective=5,
        new_effective=15,
        eco_open=True,
        stock_impacts=impacts,
        project=p,
        old_work_order=wid,
        new_revision=new,
        new_unit_ids=new_units,
    )


def e05(context):
    flow, req, lid, commit = material_case(context)
    reserve(flow, req, lid, "80")
    value = flow.api.object(flow.project, "requirement", req)["balance"]
    assert (
        value["qualified"] == "80"
        and value["reserved"] == "80"
        and value["shortage"] == "20"
        and value["in_transit"] == "20"
    ), value
    context.expected.update(
        required="100", qualified="80", in_transit="20", shortage="20", unit="piece"
    )
    context.actual.update(value)


def e06(context):
    flow, req, lid, commit = material_case(context)
    reserve(flow, req, lid, "80")
    receipt, iqc = arrival(flow, lid, commit, "20", "15", "5")
    reserve(flow, req, lid, "15")
    balance = flow.api.object(flow.project, "requirement", req)["balance"]
    assert balance["shortage"] == "5" and balance["rejected"] == "5"
    arrival(flow, lid, commit, "5")
    reserve(flow, req, lid, "5")
    final = flow.api.object(flow.project, "requirement", req)["balance"]
    assert (
        final["received"] == "105"
        and final["qualified"] == "100"
        and final["rejected"] == "5"
        and final["shortage"] == "0"
    ), final
    with flow.api.db() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM iqc_results WHERE rejected_atoms>0"
            ).fetchone()[0]
            == 1
        )
    context.actual.update(final, original_rejected_iqc=iqc["source"]["external_id"])


def e07(context):
    flow, req, lid, commit = material_case(context, second=True)
    api, p = flow.api, flow.project
    foreign = lot(flow, owner="Other customer", unit="piece", scale=0)
    expired = lot(
        flow,
        unit="piece",
        scale=0,
        expiry=(context.clock - timedelta(days=1)).date().isoformat(),
    )
    for bad in (foreign, expired):
        reserve(flow, req, bad, "1", expected=409)
    hold = api.command(
        p,
        "freeze.request",
        actor="quality",
        lot_ids=[lid],
        unit_ids=[],
        state="frozen",
        reason="Incoming lot hold",
    )
    dispatch_exchange(flow, hold, actor="quality")
    reserve(flow, req, lid, "1", expected=409)
    unhold = api.command(
        p,
        "freeze.request",
        actor="quality",
        lot_ids=[lid],
        unit_ids=[],
        state="unfrozen",
        reason="Qualified release",
    )
    dispatch_exchange(flow, unhold, actor="quality")
    reserve(flow, flow.requirements[1], lid, "80")
    pending = reserve(flow, req, lid, "80", dispatch=False)
    dispatch_exchange(flow, pending, actor="planner", phase="rejected")
    assert api.object(p, "requirement", req)["balance"]["reserved"] == "0"
    assert api.authority("balance", lot_id=lid) == "0"
    context.actual.update(
        foreign_expired_frozen_rejected=True,
        other_work_order_reserved="80",
        new_reserved="0",
    )


def e08(context):
    flow, req, lid, commit = material_case(context, qualified="0")
    api, p = flow.api, flow.project
    original = api.object(p, "commitment", commit)
    # Preserve supplier purchase and customer-replenishment commitments separately.
    # The initial commitment remains customer-owned in this contract; procurement
    # responsibility is explicitly a purchase record rather than an ownership change.
    due = original["original_due"]
    purchase = api.command(
        p,
        "supply.commit",
        actor="supply",
        requirement_id=req,
        type="purchase",
        owner_id="Customer 1",
        quantity="50",
        unit="piece",
        original_due=due,
        current_due=due,
        source=api.source("commitment"),
    )["object_id"]
    for amount in ("30", "20"):
        arrival(flow, lid, purchase, amount)
    prior = api.object(p, "commitment", purchase)
    api.command(
        p,
        "supply.commit",
        actor="supply",
        commitment_id=purchase,
        requirement_id=req,
        type="purchase",
        owner_id="Customer 1",
        quantity="50",
        unit="piece",
        original_due=prior["original_due"],
        current_due=(context.clock + timedelta(days=3)).date().isoformat(),
        source={**prior["source"], "version": 2},
    )
    api.command(
        p,
        "supply.commit",
        actor="supply",
        commitment_id=commit,
        requirement_id=req,
        type="customer",
        owner_id="Customer 1",
        quantity="50",
        unit="piece",
        original_due=due,
        current_due=due,
        source={**original["source"], "version": 2},
    )
    last, iqc = arrival(flow, lid, commit, "50")
    for kind, actor, record in [("receipt", "supply", last), ("iqc", "quality", iqc)]:
        api.command(
            p,
            "source.pull",
            actor=actor,
            system="erp",
            object_type=kind,
            external_id=record["source"]["external_id"],
        )
    supplier = api.object(p, "commitment", purchase)
    customer = api.object(p, "commitment", commit)
    balance = api.object(p, "requirement", req)["balance"]
    assert (
        supplier["original_due"] == prior["original_due"]
        and len(supplier["promise_revisions"]) == 2
    )
    assert supplier["type"] == "purchase" and customer["type"] == "customer"
    assert (
        balance["received"] == "100"
        and balance["qualified"] == "100"
        and balance["in_transit"] == "0"
    )
    context.actual.update(
        balance,
        promise_versions=2,
        purchase_commitment=purchase,
        customer_commitment=commit,
    )


def e09(context):
    flow, req, lid, commitment = material_case(context, qualified="0")
    api, p = flow.api, flow.project
    wid = flow.work_orders[0]
    for unit, quantity in [("kg", "1"), ("piece", "0.1")]:
        rejected = api.command(
            p,
            "reservation.request",
            actor="planner",
            expected=409,
            work_order_id=wid,
            requirement_id=req,
            lot_id=lid,
            quantity=quantity,
            unit=unit,
        )
        assert ("unit" if unit == "kg" else "precision") in rejected["message"]
    bad_source = api.source("receipt", mode="file")
    bad_record = {
        "object_type": "receipt",
        "project_id": p,
        "source": bad_source,
        "external_actor": "Simulated supplier",
        "signature": "Signed unit mismatch fixture",
        "commitment_id": commitment,
        "material_lot_id": lid,
        "quantity": "1",
        "unit": "kg",
    }
    rejected = api.command(
        p,
        "source.import",
        actor="supply",
        expected=409,
        object_type="receipt",
        rows=[bad_record],
    )
    assert rejected["fields"]["line"] == 1
    stale = api.source(
        "plan",
        cutoff=(context.clock - timedelta(days=3)).isoformat(),
        occurred_at=(context.clock - timedelta(days=3)).isoformat(),
    )
    result = api.command(
        p,
        "plan.receive",
        actor="planner",
        source=stale,
        input_revision_ids=flow.revisions,
        input_order_versions=[{"order_line_id": flow.order, "version": 1}],
        requirements=[
            {
                "work_order_id": wid,
                "execution_scope": "trial",
                "material_id": "steel",
                "owner_id": "Customer 1",
                "quantity": "100",
                "unit": "piece",
            }
        ],
    )
    stale_value = api.object(p, "plan", result["object_id"])
    assert (
        stale_value["state"] == "rejected"
        and stale_value["source"]["external_id"] == stale["external_id"]
    )
    assert "cutoff" in stale_value["reason"]
    assert not api.object(p, "work_order", wid)["trial_readiness"]["ready"]
    context.actual.update(
        unit_precision_rejected=True, stale_plan=result["object_id"], readiness=False
    )


def e10(context):
    flow, req, lid, _ = material_case(context, qualified="100", second=True)
    api, p = flow.api, flow.project
    requests = [reserve(flow, r, lid, "80", dispatch=False) for r in flow.requirements]
    assert all(
        api.object(p, "requirement", r)["balance"]["reserved"] == "0"
        for r in flow.requirements
    )
    with api.db() as db:
        bodies = [
            json.loads(
                db.execute(
                    "SELECT request_json FROM exchanges WHERE id=?", (r["exchange_id"],)
                ).fetchone()[0]
            )
            for r in requests
        ]
    # Both requests are real persisted commands; simultaneous delivery is only at mock authority boundary.
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(
            pool.map(lambda body: api.authority("submit", request=body), bodies)
        )
    assert sorted(r["phase"] for r in receipts) == ["accepted", "rejected"]
    for result in requests:
        api.command(
            p, "exchange.query", actor="planner", exchange_id=result["exchange_id"]
        )
        api.command(
            p, "exchange.query", actor="planner", exchange_id=result["exchange_id"]
        )
    assert (
        sum(
            Decimal(api.object(p, "requirement", r)["balance"]["reserved"])
            for r in flow.requirements
        )
        == 80
    )
    assert (
        api.authority("balance", lot_id=lid) == "20"
        and api.authority("operation_count") == 2
    )
    context.actual.update(
        qualified="100",
        total_reserved="80",
        remaining="20",
        independent_receipts=[r["receipt_id"] for r in receipts],
    )
