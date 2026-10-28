"""E11–E19: bound execution, measured quality and independent authority."""

from datetime import datetime, timedelta
from .business import (
    order,
    revision,
    work_order,
    prepare,
    start,
    execution,
    measure,
    repair,
    readiness,
    plan,
    reserve,
    receive_authority,
    dispatch_exchange,
    run_production,
    release,
    ship,
)


def ready(context, quantity=2, trial=1, mode="internal"):
    flow = order(context, quantity, mode=mode)
    rid = revision(flow)
    work_order(flow, quantity, rid, trial_quantity=trial)
    return prepare(flow)


def measured(context):
    flow = ready(context, 1)
    start(flow, flow.work_orders[0], flow.units)
    execution(flow, flow.units[0], flow.lots[0])
    measure(flow, flow.units[0])
    return flow


def e11(context):
    from .orders_supply_cases import e04

    e04(context)
    api = context.client
    p = context.actual["project"]
    old = context.actual["old_work_order"]
    new = context.actual["new_revision"]
    value = api.object(p, "work_order", old)
    api.command(
        p,
        "work_order.register",
        actor="planner",
        expected=409,
        order_line_id=value["order_line_id"],
        revision_id=new,
        source=value["source"],
        quantity=value["quantity"],
        unit=value["unit"],
        purpose=value["purpose"],
        trial_quantity=value["trial_quantity"],
        planned_start=value["planned_start"],
        planned_end=value["planned_end"],
    )
    assert api.object(p, "work_order", old)["revision_id"] == value["revision_id"]
    context.actual["direct_rebind_rejected"] = True


def e12(context):
    planned = context.clock + timedelta(days=2)
    expires = context.clock + timedelta(days=1)
    flow = order(context, 2)
    rid = revision(flow)
    wid = work_order(flow, 2, rid, planned_start=planned)
    prepare(flow)
    api, p = flow.api, flow.project
    readiness(flow, wid, validity=expires.isoformat(), kinds=("equipment",))
    before_value = api.object(p, "work_order", wid)
    assert (
        context.clock < expires < datetime.fromisoformat(before_value["planned_start"])
    ), "Equipment must expire strictly between now and planned use"
    before = before_value["trial_readiness"]
    blocked = [
        c["kind"] for c in before["checks"] if c["required"] and c["status"] != "ready"
    ]
    assert blocked == ["equipment"], f"Only future-use equipment may block: {before}"
    equipment = next(c for c in before["checks"] if c["kind"] == "equipment")
    assert "planned use" in equipment["reason"] and equipment["evidence_ids"], equipment
    assert not before["ready"], "Expired-at-use equipment must block readiness"
    start(flow, wid, flow.units[:1], expected=409)
    with api.db() as db:
        original = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM readiness_checks WHERE project_id=? AND work_order_id=? ORDER BY accepted_seq",
                (p, wid),
            )
        ]
    readiness(
        flow,
        wid,
        validity=(planned + timedelta(days=1)).isoformat(),
        kinds=("equipment",),
    )
    after = api.object(p, "work_order", wid)["trial_readiness"]
    assert after["ready"], after
    assert [c for c in before["checks"] if c["kind"] != "equipment"] == [
        c for c in after["checks"] if c["kind"] != "equipment"
    ], "Correction must not change other prerequisites"
    with api.db() as db:
        corrected = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM readiness_checks WHERE project_id=? AND work_order_id=? ORDER BY accepted_seq",
                (p, wid),
            )
        ]
    assert corrected[:-1] == original and corrected[-1]["kind"] == "equipment", (
        "Only one equipment fact may be appended"
    )
    start(flow, wid, flow.units[:1])
    context.evidence.record(
        "planned-use-equipment-proof",
        {
            "before": before_value,
            "after": after,
            "equipment_expiry": expires.isoformat(),
            "original_facts": original,
            "corrected_facts": corrected,
        },
    )
    context.actual.update(
        calibration_blocked=True,
        corrected_and_reevaluated=True,
        planned_use_after_equipment_expiry=True,
        only_equipment_changed=True,
        blocked_kinds=blocked,
    )


def e13(context):
    flow = ready(context, 2)
    api, p = flow.api, flow.project
    wid = flow.work_orders[0]
    first = flow.units[0]
    api.command(
        p,
        "project.stage",
        stage="S4",
        status="active",
        reason="First article scheduled; this is not inspection approval",
    )
    start(flow, wid, flow.units[1:], mode="bulk", expected=409)
    start(flow, wid, [first])
    execution(flow, first, flow.lots[0])
    measure(flow, first, value="7")
    failed = flow.tests[first]
    api.command(
        p,
        "first_article.record",
        actor="quality",
        expected=409,
        work_order_id=wid,
        unit_ids=[first],
        test_ids=[failed],
        inspection_id=context.identifier("failed-FAI"),
    )
    start(flow, wid, flow.units[1:], mode="bulk", expected=409)
    repair(flow, first, flow.lots[0])
    api.command(
        p,
        "first_article.record",
        actor="quality",
        work_order_id=wid,
        unit_ids=[first],
        test_ids=[flow.tests[first]],
        inspection_id=context.identifier("passed-FAI"),
    )
    start(flow, wid, flow.units[1:], mode="bulk")
    assert api.object(p, "test", failed)["outcome"] == "fail"
    context.actual.update(
        planned_and_failed_blocked=True,
        trial_available=True,
        retest_unblocked_bulk=True,
        original_failure=failed,
    )


def e14(context):
    flow = ready(context, 2)
    api, p = flow.api, flow.project
    uid = flow.units[0]
    wid = flow.work_orders[0]
    start(flow, wid, [uid])
    for invalid in (
        {"station": "wrong"},
        {"program_version": "wrong"},
        {"sn": context.identifier("unknown-SN")},
    ):
        execution(flow, uid, flow.lots[0], **invalid)
    duplicate_source = api.source("execution")
    execution(flow, uid, flow.lots[0], source=duplicate_source)
    with api.db() as db:
        original = dict(db.execute("SELECT * FROM execution_events WHERE project_id=? AND status='accepted'", (p,)).fetchone())
        consumption = [tuple(r) for r in db.execute("SELECT * FROM material_consumption WHERE project_id=?", (p,))]
    execution(flow, uid, flow.lots[0], source=duplicate_source)
    api.command(
        p,
        "unit.register",
        actor="production",
        expected=409,
        work_order_id=wid,
        sns=[context.identifier("excess-SN")],
    )
    with api.db() as db:
        rows = db.execute(
            "SELECT status,reason FROM execution_events WHERE project_id=?", (p,)
        ).fetchall()
        assert sum(r["status"] == "accepted" for r in rows) == 1
        assert sum(r["status"] == "rejected" for r in rows) == 4
        assert sum(r["reason"] == "duplicate execution source event" for r in rows) == 1
        assert dict(db.execute("SELECT * FROM execution_events WHERE id=?", (original["id"],)).fetchone()) == original
        assert [tuple(r) for r in db.execute("SELECT * FROM material_consumption WHERE project_id=?", (p,))] == consumption
        duplicate = db.execute("SELECT source_json FROM execution_events WHERE project_id=? AND reason='duplicate execution source event'", (p,)).fetchone()[0]
        assert duplicate == original["source_json"]
    assert api.get("/projects/" + p)["quality_summary"]["final_good"] == 0
    context.actual.update(
        accepted_events=1, rejected_events=4, overreport_rejected=True, good_count=0
    )


def e15(context):
    flow = ready(context, 2)
    api, p = flow.api, flow.project
    wid = flow.work_orders[0]
    start(flow, wid, flow.units[:1])
    old_plan = api.object(p, "requirement", flow.requirements[0])["plan_id"]
    stop = api.command(
        p,
        "production.interrupt",
        actor="production",
        work_order_id=wid,
        kind="S3",
        reason="Physical material shortage observed at use",
    )
    dispatch_exchange(flow, stop, actor="production")
    api.command(
        p,
        "production.resume",
        actor="production",
        expected=409,
        interruption_id=stop["object_id"],
        plan_id=old_plan,
        evidence="Old plan cannot erase interruption",
        scope="trial",
    )
    plan(
        flow,
        [
            (wid, "trial", "2", "Customer 1", "steel"),
            (wid, "bulk", "1", "Customer 1", "steel"),
        ],
    )
    newplan = api.object(p, "requirement", flow.requirements[0])["plan_id"]
    api.command(
        p,
        "production.resume",
        actor="production",
        expected=409,
        interruption_id=stop["object_id"],
        plan_id=newplan,
        evidence="Replan still short",
        scope="trial",
    )
    receive_authority(flow, flow.lots[0], "1")
    reserve(flow, flow.requirements[0], flow.lots[0], "1")
    resumed = api.command(
        p,
        "production.resume",
        actor="production",
        interruption_id=stop["object_id"],
        plan_id=newplan,
        evidence="New qualified supply and revised plan confirmed",
        scope="trial",
    )
    dispatch_exchange(flow, resumed, actor="production")
    interruption = api.object(p, "interruption", stop["object_id"])
    assert (
        interruption["requested_at"]
        and interruption["authority_stopped_at"]
        and (interruption.get("trial_resumed_at") or interruption.get("resolved_at"))
    )
    assert api.object(p, "unit", flow.units[0])["state"] == "running"
    context.actual.update(interruption=interruption, history_retained=True)


def e16(context):
    flow = ready(context, 100, trial=100)
    api, p = flow.api, flow.project
    start(flow, flow.work_orders[0], flow.units)
    first_failures = []
    for i, uid in enumerate(flow.units):
        execution(flow, uid, flow.lots[0])
        measure(flow, uid, value="5" if i < 96 else "7")
        if i >= 96:
            first_failures.append(flow.tests[uid])
    for uid in flow.units[96:99]:
        repair(flow, uid, flow.lots[0])
    uid = flow.units[99]
    nc = api.command(
        p,
        "nonconformance.open",
        actor="quality",
        test_id=flow.tests[uid],
        defect="Fourth original failure",
        evidence="Measured failed result",
    )["object_id"]
    rw = api.command(
        p,
        "nonconformance.disposition",
        actor="quality",
        nonconformance_id=nc,
        decision="rework",
        route_id="RW-SCRAP",
        route_steps=[{"station": "repair", "instruction_version": "RW-S1"}],
        evidence="Attempt qualified rework",
    )["object_id"]
    execution(flow, uid, flow.lots[0], rework=rw)
    measure(flow, uid, value="7", rework=rw)
    api.command(
        p,
        "nonconformance.disposition",
        actor="quality",
        nonconformance_id=nc,
        decision="scrap",
        evidence="Retest still failed; irreversible scrap",
    )
    release(flow, flow.units[:99])
    ship(flow, flow.units, expected=409)
    summary = api.get("/projects/" + p)["quality_summary"]
    assert (
        summary["first_passed"] == 96
        and summary["final_good"] == 99
        and summary["scrapped"] == 1
    ), summary
    for tid in first_failures:
        assert api.object(p, "test", tid)["outcome"] == "fail"
    context.expected.update(
        first_tested=100, first_passed=96, final_good=99, scrapped=1
    )
    context.actual.update(
        summary, first_failures=first_failures, ship_100_rejected=True
    )


def e17(context):
    flow = ready(context, 1)
    api, p = flow.api, flow.project
    uid = flow.units[0]
    start(flow, flow.work_orders[0], flow.units)
    execution(flow, uid, flow.lots[0])
    full = {"name": "voltage", "value": "5", "unit": "V", "lower": "4", "upper": "6"}
    for missing in ("value", "unit"):
        measure(
            flow,
            uid,
            expected=422,
            measurements=[{k: v for k, v in full.items() if k != missing}],
        )
    measure(flow, uid, expected=422, limit_version="")
    for override in ({"limit_version": "T2"}, {"program_version": "P2"}):
        measure(flow, uid, expected=409, **override)
    assert api.object(p, "unit", uid)["test_total"] == 0
    assert api.get("/projects/" + p)["quality_summary"]["final_good"] == 0
    context.actual.update(
        incomplete_or_wrong_evidence_rejected=True, test_count=0, good_count=0
    )


def e18(context):
    flow = measured(context)
    api, p = flow.api, flow.project
    uid = flow.units[0]
    for actor in ("production", "owner"):
        api.command(
            p,
            "release.decide",
            actor=actor,
            expected=403,
            kind="quality",
            unit_ids=[uid],
            decision="approved",
            evidence="Unqualified quality claim",
        )
    api.command(
        p,
        "release.decide",
        actor="quality",
        kind="quality",
        unit_ids=[uid],
        decision="approved",
        evidence="Qualified scoped quality signoff",
    )
    with api.db() as db:
        rows = db.execute(
            "SELECT actor_id FROM audit_events WHERE project_id=? AND action='release.decide'",
            (p,),
        ).fetchall()
        assert [r[0] for r in rows] == [api.sessions["quality"][2]["user_id"]]
    context.actual.update(
        production_forbidden=True,
        bare_admin_forbidden=True,
        qualified_audit_actor=api.sessions["quality"][2]["user_id"],
    )


def e19(context):
    flow = ready(context, 1, mode="oem")
    run_production(flow)
    release(flow, customer=False)
    ship(flow, flow.units, expected=409)
    release(flow)
    result = ship(flow, flow.units)
    assert (
        flow.api.object(flow.project, "shipment", result["object_id"])["shipped"] == "1"
    )
    context.actual.update(
        contractual_customer_missing_blocked=True,
        independent_customer_release_unlocked=True,
    )
