"""The four original quantities and complete S1–S9 business flows."""

from .business import released, ship, accept, closure, feedback, assert_trace


def f01(context):
    context.expected.update(
        quantity=100,
        work_order_quantities=[60, 40],
        shipments=[60, 40],
        accepted="100",
        feedback_closed=True,
    )
    flow = released(context, 100, [60, 40])
    api, p = flow.api, flow.project
    original = api.object(p, "order_line", flow.order)["original_quantity"]
    first = ship(flow, flow.units[:60])
    accept(flow, first["object_id"], 60)
    balance = api.object(p, "order_line", flow.order)
    assert balance["remaining_to_ship"] == "40", balance
    closure(flow, "fulfillment", expected=409)
    second = ship(flow, flow.units[60:])
    accept(flow, second["object_id"], 40)
    rma, capa = feedback(flow)
    for kind in ("fulfillment", "cost", "quality"):
        closure(flow, kind)
    final = api.object(p, "order_line", flow.order)
    assert final["original_quantity"] == original == "100"
    assert final["accepted"] == "100"
    for uid in flow.units:
        assert_trace(
            flow,
            uid,
            completed=True,
            feedback_ids=(rma, capa) if uid == flow.units[0] else None,
        )
    with api.db() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM units WHERE project_id=?", (p,)
            ).fetchone()[0]
            == 100
        )
        assert (
            db.execute(
                "SELECT SUM(q_atoms) FROM allocations WHERE project_id=?", (p,)
            ).fetchone()[0]
            == 100
        )
        assert (
            db.execute(
                "SELECT COUNT(*) FROM shipment_items WHERE project_id=?", (p,)
            ).fetchone()[0]
            == 100
        )
        assert (
            db.execute(
                'SELECT COUNT(*) FROM execution_events WHERE project_id=? AND status="accepted"',
                (p,),
            ).fetchone()[0]
            == 100
        )
    assert api.object(p, "capa", capa)["state"] == "closed"
    context.actual.update(
        quantity=100,
        work_order_quantities=[
            int(api.object(p, "work_order", w)["quantity"]) for w in flow.work_orders
        ],
        remaining_after_first=balance["remaining_to_ship"],
        accepted=final["accepted"],
        feedback_closed=True,
        rma=rma,
    )


def f02(context):
    from .business import (
        order,
        revision,
        work_order,
        prepare,
        start,
        execution,
        measure,
        repair,
        release,
        switch_revision,
        dispose_eco,
        run_production,
    )

    context.expected.update(
        quantity=20,
        trial_quantity=5,
        subsequent_quantity=15,
        fixed_revisions=["M1", "M2"],
    )
    flow = order(context, 20, product="Data acquisition camera")
    api, p = flow.api, flow.project
    m1 = revision(flow)
    trial = work_order(flow, 5, m1, trial_quantity=5)
    pending = work_order(flow, 15, m1)
    # Only the actual five-unit trial is prepared/executed; the planned15 has no fake execution.
    flow.work_orders = [trial]
    prepare(flow, quantities=[5])
    trial_units = flow.units.copy()
    start(flow, trial, trial_units)
    for i, uid in enumerate(trial_units):
        execution(flow, uid, flow.lots[0])
        measure(flow, uid, value="7" if i == 0 else "5")
    nc, rw = repair(flow, trial_units[0], flow.lots[0])
    api.command(
        p,
        "first_article.record",
        actor="quality",
        work_order_id=trial,
        unit_ids=trial_units,
        test_ids=[flow.tests[u] for u in trial_units],
        inspection_id=context.identifier("M1-trial-FAI"),
    )
    release(flow, trial_units)
    historical = [api.object(p, "unit", u) for u in trial_units]
    m2 = revision(flow, "M2")
    eco, new_wid = switch_revision(flow, pending, m2)
    assert api.object(p, "work_order", pending)["quantity"] == "15"
    assert api.object(p, "work_order", pending)["remaining_obligation"] == "0"
    assert api.object(p, "work_order", new_wid)["quantity"] == "15"
    assert not api.object(p, "work_order", new_wid)["trial_readiness"]["ready"]
    flow.work_orders = [new_wid]
    flow.lots = []
    prepare(flow, quantities=[20])
    # Original units remain in the project; restrict production to the new bound work order.
    new_units = [
        u for u in flow.units if api.object(p, "unit", u)["work_order_id"] == new_wid
    ]
    flow.units = new_units
    run_production(flow)
    release(flow)
    dispose_eco(flow, eco)
    for old, uid in zip(historical, trial_units):
        current = api.object(p, "unit", uid)
        assert (
            current["revision_id"] == m1
            and current["execution_events"] == old["execution_events"]
            and current["tests"] == old["tests"]
        )
    flow.units = trial_units + new_units
    for group in (trial_units, new_units):
        result = ship(flow, group)
        accept(flow, result["object_id"], len(group))
    rma, capa = feedback(flow)
    for kind in ("fulfillment", "cost", "quality"):
        closure(flow, kind)
    balance = api.object(p, "order_line", flow.order)
    assert balance["allocated"] == "20" and balance["accepted"] == "20"
    assert api.object(p, "nonconformance", nc)["state"] == "resolved"
    for uid in flow.units:
        assert_trace(
            flow,
            uid,
            completed=True,
            feedback_ids=(rma, capa) if uid == flow.units[0] else None,
        )
    context.actual.update(
        quantity=20,
        trial_quantity=5,
        subsequent_quantity=15,
        archived_planned_wo=pending,
        trial_issue=nc,
        eco=eco,
        accepted=balance["accepted"],
        feedback_closed=api.object(p, "capa", capa)["state"] == "closed",
    )


def f03(context):
    from .business import measure

    context.expected.update(
        quantity=10,
        work_order_quantities=[6, 4],
        product="3D Printer",
        camera_evidence_rejected=True,
    )
    flow = released(context, 10, [6, 4], product="3D Printer")
    api, p = flow.api, flow.project
    uid = flow.units[0]
    original_unit = api.object(p, "unit", uid)
    rejected = measure(
        flow,
        uid,
        expected=422,
        program_version="P1",
        limit_version="T1",
        measurements=[
            {"name": "voltage", "value": "5", "unit": "V", "lower": "4", "upper": "6"}
        ],
    )
    assert (
        rejected["code"] == "INVALID_COMMAND"
        and "complete frozen specification" in rejected["fields"]["measurements"]
    ), rejected
    unchanged_unit = api.object(p, "unit", uid)
    assert unchanged_unit["test_total"] == original_unit["test_total"] == 1
    assert unchanged_unit["tests"] == original_unit["tests"]
    assert unchanged_unit["final_good"] is original_unit["final_good"] is True
    assert len(flow.units) == 10 and len(api.objects(p, "unit")) == 10
    for group in (flow.units[:6], flow.units[6:]):
        result = ship(flow, group)
        accept(flow, result["object_id"], len(group))
    rma, capa = feedback(flow)
    for kind in ("fulfillment", "cost", "quality"):
        closure(flow, kind)
    for uid in flow.units:
        assert_trace(
            flow,
            uid,
            completed=True,
            feedback_ids=(rma, capa) if uid == flow.units[0] else None,
        )
    context.actual.update(
        quantity=10,
        work_order_quantities=[6, 4],
        camera_evidence_rejected=True,
        accepted=api.object(p, "order_line", flow.order)["accepted"],
        feedback_closed=api.object(p, "capa", capa)["state"] == "closed",
    )


def f04(context):
    from .business import (
        order,
        revision,
        work_order,
        lot,
        plan,
        readiness,
        receive_authority,
        reserve,
        run_production,
        release,
    )

    context.expected.update(
        quantity=30,
        customer_revision="C1",
        internal_revision="M1",
        shipments=[10, 20],
        mixed_ownership=True,
    )
    flow = order(context, 30, product="OEM robot", mode="oem")
    api, p = flow.api, flow.project
    rid = revision(flow)
    wid = work_order(flow, 30, rid)
    customer = lot(flow)
    purchased = lot(flow, owner="Manufacturer", material="purchased-steel")
    plan(
        flow,
        [
            (wid, scope, "1", owner, material)
            for scope in ("trial", "bulk")
            for owner, material in [
                ("Customer 1", "steel"),
                ("Manufacturer", "purchased-steel"),
            ]
        ],
    )
    readiness(flow, wid)
    for lid in (customer, purchased):
        receive_authority(flow, lid)
    for req in flow.requirements:
        value = api.object(p, "requirement", req)
        reserve(flow, req, customer if value["owner_id"] == "Customer 1" else purchased)
    api.command(
        p,
        "unit.register",
        actor="production",
        work_order_id=wid,
        sns=[context.identifier("SN") for _ in range(30)],
    )
    flow.units = [u["id"] for u in api.objects(p, "unit")]
    run_production(
        flow,
        material_uses=[
            {"lot_id": lid, "quantity": "0.001", "unit": "kg"}
            for lid in (customer, purchased)
        ],
    )
    release(flow, customer=False)
    ship(flow, flow.units[:10], expected=409)
    release(flow)
    for group in (flow.units[:10], flow.units[10:]):
        result = ship(flow, group)
        accept(flow, result["object_id"], len(group))
    api.command(
        p,
        "ownership.movement",
        actor="supply",
        material_lot_id=customer,
        material_id="steel",
        owner_id="Customer 1",
        unit="kg",
        movement="return",
        quantity="0.500",
        source=api.source("material_movement"),
        external_signatory="Customer material custodian",
        evidence="Actual customer-owned unused material returned",
    )
    api.command(
        p,
        "ownership.reconcile",
        actor="supply",
        material_lot_id=customer,
        material_id="steel",
        owner_id="Customer 1",
        unit="kg",
        received="2.000",
        consumed="0.030",
        scrapped="0.000",
        returned="0.500",
        balance="1.470",
        source=api.source("ownership"),
    )
    rma, capa = feedback(flow)
    for kind in ("fulfillment", "cost", "quality"):
        closure(flow, kind)
    assert api.object(p, "material_lot", customer)["owner_id"] == "Customer 1"
    assert api.object(p, "material_lot", purchased)["owner_id"] == "Manufacturer"
    for uid in flow.units:
        assert_trace(
            flow,
            uid,
            completed=True,
            feedback_ids=(rma, capa) if uid == flow.units[0] else None,
        )
    context.actual.update(
        quantity=30,
        accepted=api.object(p, "order_line", flow.order)["accepted"],
        mixed_ownership=True,
        customer_returned="0.500",
        feedback_closed=api.object(p, "capa", capa)["state"] == "closed",
    )
