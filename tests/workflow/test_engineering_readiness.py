"""Fixed engineering evidence and honest readiness through the public workflow API."""

from datetime import UTC, datetime
from uuid import uuid4

from manufacturing_platform.workflow.store import WorkflowStore


def _evaluate(workflow, project_id, work_order_id, mode):
    from manufacturing_platform.workflow.readiness import evaluate

    store = WorkflowStore(
        str(workflow.paths.domain),
        str(workflow.paths.authority),
        {"id": "workflow-test", "mode": "test", "label": "Workflow test"},
    )
    with store.transaction() as tx:
        return evaluate(tx, project_id, work_order_id, mode, datetime.now(UTC))


def _check(result, kind):
    return next(c for c in result.checks if c.kind == kind)


def test_revision_snapshot_survives_new_current_revision(workflow):
    p, _, wo, rev1 = workflow.order_workorder(quantity="5")
    rev2 = workflow.revision(p["id"], internal_revision="M2")
    read = workflow.object(p["id"], "work_order", wo["id"])
    assert read["revision_id"] == rev1["id"]
    assert rev2["id"] != rev1["id"]
    assert workflow.object(p["id"], "revision", rev1["id"])["internal_revision"] == "M1"
    assert workflow.object(p["id"], "revision", rev1["id"])["id"] == rev1["id"]
    assert workflow.object(p["id"], "revision", rev2["id"])["internal_revision"] == "M2"


def test_wrong_handoff_is_retained_and_correct_receipt_resolves(workflow):
    p, _, wo, rev = workflow.order_workorder(quantity="5")
    wrong = workflow.command(
        p["id"],
        "engineering.handoff",
        actor_name="engineering",
        revision_id=rev["id"],
        to_system="MES",
        received_revision="wrong",
        decision="accepted",
        evidence="MES receipt wrong",
    )
    read = workflow.object(p["id"], "revision", rev["id"])
    assert wrong["object_id"] == rev["id"]
    assert read["handoffs"][-1]["status"] == "rejected"
    assert (
        _check(_evaluate(workflow, p["id"], wo["id"], "trial"), "version").status
        == "blocked"
    )
    workflow.command(
        p["id"],
        "engineering.handoff",
        actor_name="engineering",
        revision_id=rev["id"],
        to_system="MES",
        received_revision="M1",
        decision="accepted",
        evidence="MES receipt corrected",
    )
    assert (
        _check(_evaluate(workflow, p["id"], wo["id"], "trial"), "version").status
        == "ready"
    )
    assert [
        h["status"] for h in workflow.object(p["id"], "revision", rev["id"])["handoffs"]
    ] == ["verified", "rejected", "verified"]


def test_planned_start_calibration_and_customer_unknown_block(workflow):
    p, _, wo, rev = workflow.order_workorder(
        quantity="5",
        contract={
            "customer_approval_required": True,
            "customer_release_required": "unknown",
            "acceptance_required": "unknown",
            "customer_revision": "C1",
            "internal_revision": "M1",
            "material_ownership_rules": "unknown",
        },
    )
    workflow.command(
        p["id"],
        "engineering.handoff",
        actor_name="engineering",
        revision_id=rev["id"],
        to_system="MES",
        received_revision="M1",
        decision="accepted",
        evidence="receipt",
    )
    workflow.command(
        p["id"],
        "readiness.record",
        actor_name="engineering",
        work_order_id=wo["id"],
        kind="equipment",
        reference="cal-1",
        evidence="calibration",
        valid_until="2026-11-01T00:00:00+00:00",
        decision="verified",
    )
    for mode in ("trial", "bulk"):
        result = _evaluate(workflow, p["id"], wo["id"], mode)
        assert _check(result, "equipment").status == "blocked"
        assert _check(result, "customer").status == "blocked"
        assert not result.ready


def test_trial_first_article_is_not_circular_and_material_is_honestly_blocked(workflow):
    p, _, wo, rev = workflow.order_workorder(quantity="5")
    workflow.command(
        p["id"],
        "engineering.handoff",
        actor_name="engineering",
        revision_id=rev["id"],
        to_system="MES",
        received_revision="M1",
        decision="accepted",
        evidence="receipt",
    )
    for kind in ("equipment", "people"):
        workflow.command(
            p["id"],
            "readiness.record",
            actor_name="engineering",
            work_order_id=wo["id"],
            kind=kind,
            reference=f"{kind}-1",
            evidence=f"{kind} qualified",
            valid_until="2027-01-01T00:00:00+00:00",
            decision="verified",
        )
    trial = _evaluate(workflow, p["id"], wo["id"], "trial")
    bulk = _evaluate(workflow, p["id"], wo["id"], "bulk")
    assert _check(trial, "first_article").required is False
    assert _check(bulk, "first_article").status == "blocked"
    assert _check(trial, "material").status == "blocked"
    assert _check(bulk, "material").status == "blocked"
    assert _check(trial, "equipment").status == "ready"
    assert _check(trial, "people").status == "ready"
    assert not trial.ready and not bulk.ready
    assert workflow.command(
        p["id"],
        "readiness.record",
        actor_name="engineering",
        work_order_id=wo["id"],
        kind="material",
        reference="fake",
        evidence="fake",
        valid_until="2027-01-01T00:00:00+00:00",
        decision="verified",
        expected_status=422,
    )


def test_public_work_order_allocation_and_unknown_order_denial(workflow):
    p, order, wo, rev = workflow.order_workorder(quantity="5")
    workflow.command(
        p["id"],
        "order.allocate",
        actor_name="planner",
        order_line_id=order["id"],
        work_order_id=wo["id"],
        quantity="5",
        unit="piece",
    )
    assert workflow.object(p["id"], "order_line", order["id"])["allocated"] == "5"
    assert workflow.command(
        p["id"],
        "order.allocate",
        actor_name="planner",
        order_line_id=order["id"],
        work_order_id=wo["id"],
        quantity="1",
        unit="piece",
        expected_status=409,
    )
    assert workflow.command(
        p["id"],
        "work_order.register",
        actor_name="planner",
        order_line_id=str(uuid4()),
        revision_id=rev["id"],
        source=workflow.source("unauthorized", object_type="work_order"),
        quantity="1",
        unit="piece",
        purpose="trial",
        trial_quantity="1",
        planned_start="2026-12-01T00:00:00+00:00",
        planned_end="2026-12-02T00:00:00+00:00",
        expected_status=404,
    )


def test_customer_approval_requires_named_evidence_and_matching_revision(workflow):
    contract = {
        "customer_approval_required": True,
        "customer_release_required": "unknown",
        "acceptance_required": "unknown",
        "customer_revision": "C1",
        "internal_revision": "M1",
        "material_ownership_rules": "unknown",
    }
    p, _, wo, rev = workflow.order_workorder(quantity="5", contract=contract)
    assert workflow.command(
        p["id"],
        "engineering.customer_approval",
        revision_id=rev["id"],
        customer_id="Someone else",
        external_signatory="Alice",
        decision="approved",
        evidence="signed approval",
        expected_status=409,
    )
    assert workflow.command(
        p["id"],
        "engineering.customer_approval",
        revision_id=rev["id"],
        customer_id="Customer 1",
        decision="approved",
        evidence="signed approval",
        expected_status=422,
    )
    workflow.command(
        p["id"],
        "engineering.customer_approval",
        revision_id=rev["id"],
        customer_id="Customer 1",
        external_signatory="Alice Customer",
        decision="approved",
        evidence="manual registration: signed C1 approval",
    )
    customer = _check(_evaluate(workflow, p["id"], wo["id"], "trial"), "customer")
    assert customer.status == "ready" and customer.evidence_ids
    approval = workflow.object(p["id"], "revision", rev["id"])["customer_approvals"][0]
    assert approval["external_signatory"] == "Alice Customer"
    assert approval["method"] == "manual"
    assert approval["recorded_by"] == "00000000-0000-4000-8000-000000000001"
    assert approval["evidence"].startswith("manual registration")


def test_work_order_registration_binds_formal_order_scope_and_external_number(workflow):
    p, order, wo, rev = workflow.order_workorder(quantity="5")
    fields = {
        "actor_name": "planner",
        "order_line_id": order["id"],
        "revision_id": rev["id"],
        "source": workflow.source("wo-repeat", object_type="work_order"),
        "quantity": "1",
        "unit": "piece",
        "purpose": "trial",
        "trial_quantity": "1",
        "planned_start": "2026-12-01T00:00:00+00:00",
        "planned_end": "2026-12-02T00:00:00+00:00",
    }
    assert (
        workflow.command(p["id"], "work_order.register", **fields, expected_status=409)[
            "code"
        ]
        == "PRECONDITION_FAILED"
    )  # all five units already planned
    p2, _, _, _ = workflow.order_workorder(quantity="5")
    assert (
        workflow.command(
            p2["id"],
            "work_order.register",
            **{
                **fields,
                "source": workflow.source("wo-other", object_type="work_order"),
            },
            expected_status=404,
        )["code"]
        == "NOT_FOUND"
    )
    assert wo["id"]


def test_new_customer_revision_is_recorded_but_cannot_satisfy_old_contract(workflow):
    contract = {
        "customer_approval_required": True,
        "customer_release_required": "unknown",
        "acceptance_required": "unknown",
        "customer_revision": "C1",
        "internal_revision": "M1",
        "material_ownership_rules": "unknown",
    }
    p, _, wo, rev = workflow.order_workorder(contract=contract)
    new_revision = workflow.revision(
        p["id"], internal_revision="M2", customer_revision="C2"
    )
    assert (
        workflow.object(p["id"], "revision", new_revision["id"])["customer_revision"]
        == "C2"
    )
    assert workflow.object(p["id"], "work_order", wo["id"])["revision_id"] == rev["id"]


def test_v2_database_migrates_without_losing_reviewed_order(workflow):
    p, order, _, _ = workflow.order_workorder(quantity="5")
    # Emulate the persisted A2 schema: only A3-owned tables are removed.
    import sqlite3

    with sqlite3.connect(workflow.paths.domain) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        for view in ("effective_supply_receipts", "effective_iqc_results"):
            db.execute(f"DROP VIEW {view}")
        for table in ("source_corrections", "exchange_discrepancies", "source_confirmations", "exchange_receipts", "exchange_events", "exchanges"):
            db.execute(f"DROP TABLE {table}")
        db.execute("ALTER TABLE reservations DROP COLUMN exchange_id")
        db.execute("ALTER TABLE reservations DROP COLUMN accepted_sequence")
        for table in (
            "readiness_checks",
            "work_orders",
            "customer_approvals",
            "handoffs",
            "revision_routes",
            "revision_items",
            "engineering_revisions",
        ):
            db.execute(f"DROP TABLE {table}")
        db.execute("UPDATE schema_version SET version=2")
    workflow.reopen()
    assert (
        workflow.object(p["id"], "order_line", order["id"])["current_quantity"] == "5"
    )
    assert workflow.revision(p["id"], internal_revision="M2")["id"]
    with workflow.db() as db:
        assert db.execute("SELECT version FROM schema_version").fetchone()[0] == 7


def test_measurement_limits_accept_finite_zero_and_negative_bounds():
    from pydantic import ValidationError

    from manufacturing_platform.workflow.engineering_models import MeasurementLimit

    limit = MeasurementLimit.model_validate(
        {"name": "temperature", "unit": "C", "lower": "-20", "upper": "0"}
    )
    assert limit.model_dump(mode="json")["lower"] == "-20"
    for bad in ("NaN", "Infinity", "1e3", "-0"):
        with __import__("pytest").raises(ValidationError):
            MeasurementLimit.model_validate(
                {"name": "temperature", "unit": "C", "lower": bad, "upper": "0"}
            )


def test_work_order_detail_exposes_separate_trial_and_bulk_blockers(workflow):
    p, _, wo, _ = workflow.order_workorder(quantity="5")
    read = workflow.object(p["id"], "work_order", wo["id"])
    assert read["trial_readiness"]["ready"] is False
    assert read["bulk_readiness"]["ready"] is False
    trial = {c["kind"]: c for c in read["trial_readiness"]["checks"]}
    bulk = {c["kind"]: c for c in read["bulk_readiness"]["checks"]}
    assert trial["first_article"]["required"] is False
    assert bulk["first_article"]["status"] == "blocked"
    assert trial["material"]["status"] == "blocked"


def test_pending_package_item_cannot_be_fixed_as_approved_revision(workflow):
    p = workflow.create_project()
    workflow.grant(p["id"], "engineering", ["engineering"])
    result = workflow.command(
        p["id"],
        "engineering.revision",
        actor_name="engineering",
        package_id="incomplete",
        revision="M1",
        customer_revision="C1",
        internal_revision="M1",
        items=[
            {
                "id": "drawing",
                "kind": "drawing",
                "title": "unfinished drawing",
                "status": "pending",
            }
        ],
        route_steps=[{"station": "assembly", "instruction_version": "S1"}],
        test_spec={
            "version": "T1",
            "program_version": "P1",
            "measurements": [
                {"name": "voltage", "unit": "V", "lower": "4", "upper": "6"}
            ],
        },
        firmware_version="F1",
        expected_status=409,
    )
    assert result["code"] == "PRECONDITION_FAILED"


def test_readiness_record_needs_live_project_verification_qualification(workflow):
    p, _, wo, _ = workflow.order_workorder()
    workflow.grant(p["id"], "engineering", ["engineering"], [])
    other = workflow.create_project()
    workflow.grant(
        other["id"], "engineering", ["engineering"], ["readiness_verification"]
    )
    workflow.grant(p["id"], "owner", ["project_owner", "engineering"], [])
    fields = {
        "work_order_id": wo["id"],
        "kind": "equipment",
        "reference": "cal-1",
        "evidence": "calibration certificate checked",
        "valid_until": "2027-01-01T00:00:00+00:00",
        "decision": "verified",
    }
    assert (
        workflow.command(
            p["id"],
            "readiness.record",
            actor_name="engineering",
            **fields,
            expected_status=403,
        )["code"]
        == "FORBIDDEN"
    )
    assert (
        workflow.command(
            p["id"],
            "readiness.record",
            actor_name="owner",
            **fields,
            expected_status=403,
        )["code"]
        == "FORBIDDEN"
    )
    assert (
        _check(_evaluate(workflow, p["id"], wo["id"], "trial"), "equipment").status
        == "blocked"
    )
    workflow.grant(p["id"], "engineering", ["engineering"], ["readiness_verification"])
    workflow.command(p["id"], "readiness.record", actor_name="engineering", **fields)
    assert (
        _check(_evaluate(workflow, p["id"], wo["id"], "trial"), "equipment").status
        == "ready"
    )
    workflow.grant(p["id"], "engineering", ["engineering"], [])
    assert (
        workflow.command(
            p["id"],
            "readiness.record",
            actor_name="engineering",
            **{**fields, "kind": "people"},
            expected_status=403,
        )["code"]
        == "FORBIDDEN"
    )
    assert (
        _check(_evaluate(workflow, p["id"], wo["id"], "trial"), "people").status
        == "blocked"
    )


def test_forecast_demand_cannot_authorize_formal_work_order(workflow):
    p = workflow.create_project()
    forecast = workflow.command(
        p["id"],
        "demand.record",
        kind="forecast",
        product="Camera",
        quantity="5",
        unit="piece",
        due_date="2026-12-01",
        source=workflow.source("forecast-for-wo"),
    )["object_id"]
    for dimension in ("technical", "material", "capacity", "commercial", "quality"):
        workflow.command(
            p["id"],
            "demand.review",
            demand_id=forecast,
            dimension=dimension,
            decision="approved",
            evidence="forecast review",
        )
    assert (
        workflow.command(
            p["id"],
            "order.register",
            demand_id=forecast,
            source=workflow.source("forecast-order", object_type="order_line"),
            quantity="5",
            unit="piece",
            due_date="2026-12-01",
            expected_status=409,
        )["code"]
        == "PRECONDITION_FAILED"
    )
    rev = workflow.revision(p["id"])
    workflow.grant(p["id"], "planner", ["planner"])
    assert (
        workflow.command(
            p["id"],
            "work_order.register",
            actor_name="planner",
            order_line_id=forecast,
            revision_id=rev["id"],
            source=workflow.source("forecast-wo", object_type="work_order"),
            quantity="5",
            unit="piece",
            purpose="trial",
            trial_quantity="1",
            planned_start="2026-12-01T00:00:00+00:00",
            planned_end="2026-12-02T00:00:00+00:00",
            expected_status=404,
        )["code"]
        == "NOT_FOUND"
    )
    assert (
        workflow.client()
        .get(f"/api/v1/manufacturing/workflow/projects/{p['id']}/objects/work_order")
        .json()["total"]
        == 0
    )
