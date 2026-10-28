"""E20–E29,E31–E32: genealogy, fulfillment and explicitly required host proof."""

from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess

from .base import ScenarioBlocked, ScenarioContext, run_case
from .business import (
    released,
    ship,
    accept,
    closure,
    feedback,
    assert_trace,
    order,
    revision,
    work_order,
    prepare,
    measure,
    release,
    run_production,
    dispose_eco,
    dispatch_exchange,
    reserve,
)
from .orders_supply_cases import material_case
from .fixtures import connect, BASE


def e20(context):
    flow = released(context, 2)
    api, p = flow.api, flow.project
    shipment = ship(flow, flow.units[:1])
    forward = api.get("/projects/" + p + "/trace?material_lot_id=" + flow.lots[0])
    reverse = assert_trace(flow, flow.units[0])
    assert {n["id"] for n in forward["nodes"] if n["kind"] == "unit"} == set(flow.units)
    assert {
        n["customer_id"] for n in forward["nodes"] if n["kind"] == "order_line"
    } == {"Customer 1"}
    assert {n["kind"] for n in reverse["nodes"]} >= {
        "revision",
        "material_lot",
        "test",
        "shipment",
        "order_line",
    }
    freeze = api.command(
        p,
        "freeze.request",
        actor="quality",
        unit_ids=flow.units,
        lot_ids=[flow.lots[0]],
        state="frozen",
        reason="Suspect material lot traced to actual customers",
    )
    before = api.object(p, "unit", flow.units[0])
    assert before["freeze_pending"] and before["freeze_confirmed"] != "frozen"
    dispatch_exchange(flow, freeze, actor="quality")
    assert all(
        api.object(p, "unit", u)["freeze_confirmed"] == "frozen" for u in flow.units
    )
    assert api.object(p, "shipment", shipment["object_id"])["shipped"] == "1"
    context.actual.update(
        forward_units=flow.units,
        reverse_shipment=shipment["object_id"],
        pending_then_confirmed=True,
    )


def e21(context):
    flow = released(context, 100)
    api, p = flow.api, flow.project
    first = ship(flow, flow.units[:60])
    accept(flow, first["object_id"], 60)
    balance = api.object(p, "order_line", flow.order)
    assert (
        balance["remaining_to_ship"] == "40"
        and balance["fulfillment_status"] != "closed"
    )
    ship(flow, [flow.units[0]], expected=409)
    ship(flow, flow.units[60:], quantity="41", expected=409)
    second = ship(flow, flow.units[60:])
    assert api.object(p, "order_line", flow.order)["remaining_to_accept"] == "40"
    closure(flow, "fulfillment", expected=409)
    accept(flow, second["object_id"], 40)
    closure(flow, "fulfillment")
    result = api.object(p, "order_line", flow.order)
    assert result["accepted"] == "100" and result["remaining_to_ship"] == "0"
    context.expected.update(
        quantity=100, shipments=[60, 40], remaining_after_first="40"
    )
    context.actual.update(
        result, remaining_after_first="40", duplicate_and_41_rejected=True
    )


def e22(context):
    flow = released(context, 2)
    api, p = flow.api, flow.project
    sid = ship(flow, flow.units)["object_id"]
    before = api.object(p, "order_line", flow.order)
    assert (
        before["shipped"] == "2"
        and before["signed"] == "0"
        and before["accepted"] == "0"
    )
    closure(flow, "fulfillment", expected=409)
    api.command(
        p,
        "delivery.sign",
        actor="warehouse",
        shipment_id=sid,
        quantity="2",
        source=api.source("delivery_sign"),
        external_signatory="Customer receiver",
    )
    signed = api.object(p, "order_line", flow.order)
    assert signed["signed"] == "2" and signed["accepted"] == "0"
    closure(flow, "fulfillment", expected=409)
    accept(
        flow,
        sid,
        2,
        sign=False,
        issues=[
            {
                "title": "Required packing report",
                "owner_id": api.sessions["quality"][2]["user_id"],
                "required": True,
            }
        ],
    )
    issue = api.object(p, "shipment", sid)["issues"][0]
    assert issue["owner_name"] and not issue["resolved"]
    closure(flow, "fulfillment", expected=409)
    api.command(
        p,
        "delivery.resolve_issue",
        actor="quality",
        issue_id=issue["id"],
        evidence="Customer confirmed required document delivered",
    )
    closure(flow, "fulfillment")
    context.actual.update(
        shipped_signed_accepted_separate=True,
        required_issue=issue,
        fulfilled_after_resolution=True,
    )


def e23(context):
    flow = released(context, 1)
    sid = ship(flow, flow.units)["object_id"]
    accept(flow, sid, 1)
    rma, capa = feedback(flow, close=False)
    closed = closure(flow, "cost")
    closure(flow, "quality", expected=409)
    assert (
        flow.api.object(flow.project, "closure", closed["object_id"])["status"]
        == "closed"
    )
    assert (
        flow.api.object(flow.project, "rma", rma)["state"] == "open"
        and flow.api.object(flow.project, "capa", capa)["state"] == "open"
    )
    context.actual.update(cost_closed=True, quality_open=True, rma=rma, capa=capa)


def e24(context):
    flow = released(context, 1)
    api, p = flow.api, flow.project
    sid = ship(flow, flow.units)["object_id"]
    accept(flow, sid, 1)
    uid = flow.units[0]
    original = api.object(p, "unit", uid)
    measure(flow, uid, value="7")
    failed = flow.tests[uid]
    rma = api.command(
        p,
        "rma.open",
        actor="quality",
        unit_id=uid,
        shipment_id=sid,
        reason="Returned product failed field measurement",
        source=api.source("rma"),
    )["object_id"]
    old = api.object(p, "order_line", flow.order)
    change = api.command(
        p,
        "order.change",
        order_line_id=flow.order,
        new_quantity="2",
        cancel=False,
        new_due_date=old["current_due"],
        reason="Customer replacement scope",
        source={**old["source"], "version": 2},
    )["object_id"]
    impacts = api.object(p, "commitment_change", change)["impacts"]
    api.command(
        p,
        "order.resolve_change",
        change_id=change,
        dispositions=[
            {
                "object_type": i["object_type"],
                "object_id": i["object_id"],
                "decision": "retain",
                "evidence": "Original delivered scope remains immutable",
            }
            for i in impacts
        ],
    )
    future = work_order(flow, 1, original["revision_id"])
    new = revision(flow, "M2")
    eco = api.command(
        p,
        "eco.open",
        actor="engineering",
        old_revision_id=original["revision_id"],
        new_revision_id=new,
        effective_work_order_ids=[future],
        reason="Engineering correction from actual RMA",
    )["object_id"]
    capa = None
    for step in ("containment", "root_cause", "correction", "verification"):
        extra = (
            {"action_kind": "engineering", "eco_id": eco}
            if step == "correction"
            else {"effective": True}
            if step == "verification"
            else {}
        )
        capa = api.command(
            p,
            "capa.update",
            actor="quality",
            rma_id=rma,
            capa_id=capa,
            step=step,
            description="Actual " + step,
            evidence="Signed " + step,
            **extra,
        )["object_id"]
    api.command(p, "capa.close", actor="quality", capa_id=capa, expected=409)
    switched = api.command(
        p,
        "eco.switch",
        actor="engineering",
        eco_id=eco,
        target_work_order_id=future,
        new_revision_id=new,
        boundary="split_remaining",
        evidence="Source-confirmed correction implementation",
    )
    dispatch_exchange(flow, switched, actor="engineering")
    newwid = switched["object_id"]
    flow.work_orders = [newwid]
    flow.lots = []
    flow.quantity = 2
    prepare(flow)
    flow.units = [
        u for u in flow.units if api.object(p, "unit", u)["work_order_id"] == newwid
    ]
    run_production(flow)
    release(flow)
    dispose_eco(flow, eco)
    api.command(p, "capa.close", actor="quality", capa_id=capa)
    assert (
        api.object(p, "test", failed)["outcome"] == "fail"
        and api.object(p, "shipment", sid)["shipped"] == "1"
    )
    assert api.object(p, "unit", uid)["revision_id"] == original["revision_id"]
    assert api.object(p, "capa", capa)["state"] == "closed"
    context.actual.update(
        rma=rma,
        capa=capa,
        eco=eco,
        new_work_order=newwid,
        original_failure=failed,
        original_delivery=sid,
    )


def e25(context):
    api = connect(context)
    p = api.project("2")
    api.grant(p, "planner", ["project_owner", "planner"])
    version = api.get("/projects/" + p)["version"]
    op = context.identifier("idempotency")
    body = {
        "operation_id": op,
        "expected_version": version,
        "action": "demand.record",
        "kind": "firm",
        "product": "Camera",
        "quantity": "2",
        "unit": "piece",
        "due_date": (context.clock + timedelta(days=1)).date().isoformat(),
        "source": api.source("demand"),
    }
    path = f"/projects/{p}/commands"
    first = api.post(path, body, actor="planner")
    same = api.post(path, body, actor="planner")
    assert same["object_id"] == first["object_id"] and same["replayed"]
    api.post(path, {**body, "quantity": "1"}, actor="planner", expected=409)
    assert len(api.objects(p, "demand")) == 1
    api.grant(p, "planner", ["project_owner", "planner"], active=False)
    api.post(path, body, actor="planner", expected=404)
    context.actual.update(
        operation_id=op,
        object_id=first["object_id"],
        successful_rows=1,
        changed_payload_conflict=True,
        revoked_replay_denied=True,
    )


def e26(context):
    flow, req, lid, _ = material_case(context, qualified="100")
    api, p = flow.api, flow.project
    intent = reserve(flow, req, lid, "80", dispatch=False)
    api.authority("configure_fault", name="timeout_after_commit")
    dispatch_exchange(flow, intent, actor="planner", phase="unknown")
    assert api.object(p, "requirement", req)["balance"]["reserved"] == "0"
    assert api.authority("balance", lot_id=lid) == "20"
    api.restart()
    api.authority("configure_fault", name="none")
    for _ in range(2):
        api.command(
            p, "exchange.query", actor="planner", exchange_id=intent["exchange_id"]
        )
    assert api.object(p, "exchange", intent["exchange_id"])["phase"] == "accepted"
    assert api.object(p, "requirement", req)["balance"]["reserved"] == "80"
    assert api.authority("operation_count", business_key=intent["exchange_id"]) == 1
    context.actual.update(
        unknown_before_restart=True, reserved_after_query="80", external_effect_count=1
    )


def e27(context):
    flow = released(context, 1)
    api, p = flow.api, flow.project
    old = api.command(
        p,
        "freeze.request",
        actor="quality",
        unit_ids=flow.units,
        lot_ids=[],
        state="unfrozen",
        reason="Older release",
    )
    newer = api.command(
        p,
        "freeze.request",
        actor="quality",
        unit_ids=flow.units,
        lot_ids=[],
        state="frozen",
        reason="Newer material issue",
    )
    dispatch_exchange(flow, newer, actor="quality")
    dispatch_exchange(flow, old, actor="quality", phase="rejected")
    assert api.object(p, "unit", flow.units[0])["freeze_confirmed"] == "frozen"
    ship(flow, flow.units, expected=409)
    rejected = api.object(p, "exchange", old["exchange_id"])
    assert (
        rejected["receipt"]["source_version"]
        < api.object(p, "exchange", newer["exchange_id"])["receipt"]["source_version"]
    )
    context.actual.update(
        new_state="frozen",
        old_rejected_receipt=rejected["receipt"],
        rejection_history=rejected["events"],
    )


def e28(context):
    flow, req, lid, _ = material_case(context, qualified="100")
    api, p = flow.api, flow.project
    intent = reserve(flow, req, lid, "80")
    receipt = api.object(p, "exchange", intent["exchange_id"])["receipt"]
    details = [{**d} for d in receipt["details"]]
    details[0]["key"] = context.identifier("wrong-detail")
    api.command(
        p,
        "exchange.reconcile",
        actor="planner",
        exchange_id=intent["exchange_id"],
        source=api.source("reservation"),
        object_type="reservation",
        source_version=receipt["source_version"],
        details=details,
        evidence="Same total but mismatched actual detail",
    )
    conflict = api.object(p, "exchange", intent["exchange_id"])
    assert conflict["discrepancies"] and conflict["discrepancies"][0]["owner_id"]
    rejected = reserve(flow, req, lid, "20", dispatch=False)
    api.authority("configure_fault", name="reject")
    dispatch_exchange(flow, rejected, actor="planner", phase="rejected")
    assert api.object(p, "requirement", req)["balance"]["reserved"] == "80"
    context.actual.update(
        same_sum_difference_owned=conflict["discrepancies"],
        rejected_not_posted=True,
        reserved="80",
    )


HOST_ASSERTIONS = {
    "E29": (
        "pf-real-identity-csrf",
        "project-customer-action-acl",
        "qualification-revocation",
        "retired-page-callbacks",
        "legacy-endpoints-protected",
    ),
    "E31": (
        "actual-host-fresh-process-sessions",
        "all-critical-phase-readback",
        "api-db-dashboard-consistency",
        "idempotent-resume",
        "historical-create-replay-compatibility",
    ),
    "E32": (
        "seven-legacy-created-by-real-api",
        "all-legacy-table-hashes-unchanged",
        "owned-demo-reset-only",
        "seeded-mock-state-replay",
        "persistent-simulation-labels",
    ),
}


def host_proof(context):
    """D3 fills the reviewed private runner; absence blocks the aggregate case."""
    configured = os.environ.get("WORKFLOW_D3_PROOF_COMMAND")
    if not configured:
        raise ScenarioBlocked(
            "Required D3 actual-host proof runner unavailable: "
            + ",".join(HOST_ASSERTIONS[context.case_id])
        )
    command = json.loads(configured)
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(v, str) for v in command)
    ):
        raise ValueError("D3 proof command must be a JSON string array")
    # Every command element naming a local executable/script is hashed independently.
    files = {}
    for part in command:
        path = Path(part)
        if path.is_absolute() and path.is_file() and not path.is_symlink():
            files[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not files:
        raise ScenarioBlocked(
            "D3 proof command requires pinned absolute private runner files"
        )
    manifest = json.loads((context.directory / "manifest.json").read_text())
    output = context.directory / "d3-proof.json"
    args = [
        *command,
        "--case",
        context.case_id,
        "--case-directory",
        str(context.directory),
        "--output",
        str(output),
    ]
    context.evidence.record(
        "d3-runner",
        {
            "command": args,
            "files": files,
            "required_assertions": HOST_ASSERTIONS[context.case_id],
        },
    )
    result = subprocess.run(args, capture_output=True, text=True, timeout=60)
    context.evidence.record(
        "d3-process",
        {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
    )
    assert result.returncode == 0, "D3 private host runner failed"
    if output.is_symlink():
        raise AssertionError("D3 proof symlink refused")
    proof = json.loads(output.read_text())
    expected = {
        "case_id": context.case_id,
        "dataset_id": context.dataset_id,
        "seed": context.seed,
        "release_hash": manifest["source"]["release_hash"],
        "runner_files": files,
    }
    for key, value in expected.items():
        assert proof.get(key) == value, f"D3 provenance mismatch: {key}"
    assertions = proof.get("assertions", {})
    for name in HOST_ASSERTIONS[context.case_id]:
        assertion = assertions.get(name, {})
        assert assertion.get("passed") is True and assertion.get("evidence"), (
            f"Missing D3 evidence: {name}"
        )
        for artifact in assertion["evidence"]:
            relative = Path(artifact["path"])
            path = context.directory / relative
            assert (
                not relative.is_absolute()
                and ".." not in relative.parts
                and not path.is_symlink()
                and path.resolve().is_relative_to(context.directory.resolve())
            ), "Foreign D3 evidence refused"
            assert all(
                not parent.is_symlink()
                for parent in path.parents
                if parent != context.directory.parent
            ), "Symlink D3 evidence refused"
            assert (
                path.is_file()
                and hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]
            ), "D3 evidence digest mismatch"
    context.actual["d3_host_assertions"] = list(assertions)


def e29(context):
    api = connect(context)
    p = api.project("1")
    api.request("GET", BASE + "/projects/" + p, anonymous=True, expected=401)
    api.get("/projects/" + p, actor="outsider", expected=404)
    body = {
        "operation_id": context.identifier("denied"),
        "expected_version": api.get("/projects/" + p)["version"],
        "action": "project.stage",
        "stage": "S1",
        "status": "active",
        "reason": "Denied",
    }
    api.post(
        "/projects/" + p + "/commands",
        body,
        headers={"x-csrf-token": "invalid"},
        expected=403,
    )
    api.post("/projects/" + p + "/commands", body, actor="quality", expected=403)
    api.request("POST", "/fixture/revoke", body={"name": "quality"})
    api.get("/projects/" + p, actor="quality", expected=401)
    with api.db() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM audit_events WHERE action='project.stage'"
            ).fetchone()[0]
            == 0
        )
    context.actual.update(local_session_csrf_scope_qualification_revocation=True)
    host_proof(context)


def checkpoint(flow, name):
    api = flow.api
    p = flow.project
    before = api.get("/projects/" + p)
    with api.db() as db:
        tables = [
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        facts = {
            t: [tuple(r) for r in db.execute(f'SELECT * FROM "{t}" ORDER BY rowid')]
            for t in tables
        }
    api.restart()
    assert api.get("/projects/" + p) == before
    with api.db() as db:
        assert {
            t: [tuple(r) for r in db.execute(f'SELECT * FROM "{t}" ORDER BY rowid')]
            for t in tables
        } == facts
    api.context.evidence.record(
        "phase-restart",
        {
            "phase": name,
            "project": before,
            "facts_sha256": hashlib.sha256(
                json.dumps(facts, sort_keys=True).encode()
            ).hexdigest(),
            "dashboard": api.get("/dashboard"),
        },
    )


def e31(context):
    flow = order(context, 2)
    checkpoint(flow, "reviewed-order")
    rid = revision(flow)
    work_order(flow, 2, rid)
    prepare(flow)
    checkpoint(flow, "reserved-and-ready")
    run_production(flow)
    release(flow)
    checkpoint(flow, "executed-tested-released")
    sid = ship(flow, flow.units)["object_id"]
    checkpoint(flow, "shipped")
    accept(flow, sid, 2)
    feedback(flow)
    checkpoint(flow, "accepted-feedback-closed")
    for kind in ("fulfillment", "cost", "quality"):
        closure(flow, kind)
    checkpoint(flow, "independent-closures")
    assert flow.api.object(flow.project, "order_line", flow.order)["accepted"] == "2"
    context.actual.update(local_fresh_process_phases=6, accepted="2")
    host_proof(context)


def e32(context):
    runs = []
    for seed in (context.seed + 1, context.seed + 2):
        child = ScenarioContext.isolated(
            context.directory / "seed-replays",
            case_id="E14",
            seed=seed,
            clock=context.clock,
        )
        result = run_case(child)
        assert result.status == "passed", result.error
        import sqlite3

        with sqlite3.connect(f"file:{child.paths.domain}?mode=ro", uri=True) as db:
            serials = [
                r[0] for r in db.execute("SELECT sn FROM units ORDER BY registered_seq")
            ]
        runs.append(
            {
                "seed": seed,
                "serials": serials,
                "actual": result.actual,
                "directory": str(child.directory),
            }
        )
    assert (
        runs[0]["serials"] != runs[1]["serials"]
        and runs[0]["actual"] == runs[1]["actual"]
    )
    flow, req, lid, _ = material_case(context, qualified="100")
    intent = reserve(flow, req, lid, "80", dispatch=False)
    flow.api.authority("configure_fault", name="reject")
    dispatch_exchange(flow, intent, actor="planner", phase="rejected")
    flow.api.authority("configure_fault", name="none")
    new = reserve(flow, req, lid, "80")
    assert new["exchange_id"] != intent["exchange_id"]
    context.actual.update(
        alternate_seed_runs=runs, mock_state_changed_via_boundary=True
    )
    host_proof(context)
