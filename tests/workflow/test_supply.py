"""Supply evidence, quantity boundaries and scoped readiness through the public API."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from .conftest import BASE


def test_received_is_not_qualified_and_rejected_is_immutable(workflow):
    p, req, commit = workflow.material_requirement()
    receipt = workflow.receive(
        p["id"], commit["id"], quantity="20", lot_id=commit["lot_id"]
    )
    before = workflow.balance(p["id"], req["id"])
    assert (
        before["required"],
        before["received"],
        before["qualified"],
        before["reserved"],
        before["shortage"],
    ) == ("100", "100", "80", "0", "100")
    workflow.inspect(p["id"], receipt["object_id"], accepted="15", rejected="5")
    workflow.reopen()
    after = workflow.balance(p["id"], req["id"])
    assert (
        after["received"],
        after["qualified"],
        after["rejected"],
        after["reserved"],
        after["shortage"],
    ) == ("100", "95", "5", "0", "100")
    replacement = workflow.receive(
        p["id"], commit["id"], quantity="5", lot_id=commit["lot_id"]
    )
    workflow.inspect(p["id"], replacement["object_id"], accepted="5", rejected="0")
    assert workflow.balance(p["id"], req["id"])["rejected"] == "5"
    assert workflow.balance(p["id"], req["id"])["qualified"] == "100"
    assert workflow.balance(p["id"], req["id"])["reserved"] == "0"


def test_material_scale_is_independent_of_finished_piece_scale(workflow):
    p, req, _ = workflow.material_requirement(required="1.250", qualified="0.125")
    assert p["unit"]["code"] == "piece" and p["unit"]["scale"] == 0
    assert workflow.balance(p["id"], req["id"])["required"] == "1.25"
    assert workflow.balance(p["id"], req["id"])["qualified"] == "0.125"
    assert workflow.balance(p["id"], req["id"])["in_transit"] == "1.125"


@pytest.mark.parametrize("field", ["system", "object_type", "external_id"])
@pytest.mark.parametrize("action,table,source_type", [
    ("material.define", "material_lots", "material_lot"),
    ("plan.receive", "plans", "plan"),
    ("supply.commit", "supply_commitments", "commitment"),
    ("supply.receive", "supply_receipts", "receipt"),
])
def test_blank_normalized_supply_source_is_rejected_without_any_fact(
    workflow, field, action, table, source_type
):
    p, req, commit = workflow.material_requirement(qualified="0")
    source = workflow.source(f"blank-{uuid4()}", object_type=source_type)
    source[field] = " \t "
    fields = {
        "material.define": {"material_id": "steel-2", "lot_id": f"lot-{uuid4()}",
                            "owner_id": "Customer 1", "unit": "kg", "scale": 3,
                            "expiry": "2027-12-01"},
        "plan.receive": {"input_revision_ids": [commit["revision_id"]],
                         "input_order_versions": [{"order_line_id": commit["order_id"], "version": 1}],
                         "requirements": [{"work_order_id": commit["work_order_id"],
                                           "execution_scope": "trial", "material_id": "steel-1",
                                           "owner_id": "Customer 1", "quantity": "1", "unit": "kg"}]},
        "supply.commit": {"requirement_id": req["id"], "type": "purchase",
                          "owner_id": "Customer 1", "quantity": "1", "unit": "kg",
                          "original_due": "2026-12-01", "current_due": "2026-12-01"},
        "supply.receive": {"commitment_id": commit["id"],
                           "material_lot_id": commit["lot_id"], "quantity": "1", "unit": "kg"},
    }
    version = workflow.client().get(f"{BASE}/projects/{p['id']}").json()["version"]
    with workflow.db() as db:
        count = db.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (p["id"],)).fetchone()[0]
    workflow.command(p["id"], action, actor_name="planner" if action == "plan.receive" else "supply",
                     source=source, expected_status=422, **fields[action])
    assert workflow.client().get(f"{BASE}/projects/{p['id']}").json()["version"] == version
    with workflow.db() as db:
        assert db.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (p["id"],)).fetchone()[0] == count


def test_duplicate_receipt_source_and_overinspection_cannot_increment(workflow):
    p, req, commit = workflow.material_requirement(qualified="0")
    source = workflow.source("delivery-same", object_type="receipt")
    first = workflow.receive(
        p["id"], commit["id"], quantity="20", lot_id=commit["lot_id"], source=source
    )
    assert (
        workflow.command(
            p["id"],
            "supply.receive",
            actor_name="supply",
            commitment_id=commit["id"],
            material_lot_id=commit["lot_id"],
            quantity="20",
            unit="kg",
            source=source,
            expected_status=409,
        )["code"]
        == "SOURCE_CONFLICT"
    )
    workflow.inspect(p["id"], first["object_id"], accepted="15", rejected="5")
    assert workflow.command(
        p["id"],
        "supply.inspect",
        actor_name="quality",
        receipt_id=first["object_id"],
        accepted="1",
        rejected="0",
        evidence="duplicate",
        expected_status=409,
    )
    assert workflow.balance(p["id"], req["id"])["qualified"] == "15"


def test_in_transit_keeps_other_supplier_promise_when_one_overdelivers(workflow):
    p, req, commit = workflow.material_requirement(qualified="0")
    workflow.command(
        p["id"],
        "supply.commit",
        actor_name="supply",
        requirement_id=req["id"],
        type="purchase",
        owner_id="Customer 1",
        quantity="50",
        unit="kg",
        original_due="2026-12-01",
        current_due="2026-12-01",
        source=workflow.source(f"second-{uuid4()}", object_type="commitment"),
    )
    workflow.receive(p["id"], commit["id"], quantity="120", lot_id=commit["lot_id"])
    assert workflow.balance(p["id"], req["id"])["in_transit"] == "50"
    page = (
        workflow.client().get(f"{BASE}/projects/{p['id']}/objects/requirement").json()
    )
    assert page["items"][0]["material_balance"]["in_transit"] == "50"


def test_material_precision_owner_and_source_mode_are_enforced(workflow):
    p, req, commit = workflow.material_requirement(qualified="0")
    for quantity, unit, owner in (
        ("1.0001", "kg", "Customer 1"),
        ("1", "piece", "Customer 1"),
        ("1", "kg", "Other"),
    ):
        assert workflow.command(
            p["id"],
            "supply.commit",
            actor_name="supply",
            requirement_id=req["id"],
            type="purchase",
            owner_id=owner,
            quantity=quantity,
            unit=unit,
            original_due="2026-12-01",
            current_due="2026-12-01",
            source=workflow.source(f"bad-{uuid4()}", object_type="commitment"),
            expected_status=409,
        )
    spoof = workflow.source("spoof", object_type="receipt", mode="api")
    assert workflow.command(
        p["id"],
        "supply.receive",
        actor_name="supply",
        commitment_id=commit["id"],
        material_lot_id=commit["lot_id"],
        quantity="1",
        unit="kg",
        source=spoof,
        expected_status=409,
    )
    file_claim = workflow.source("file-claim", object_type="receipt", mode="file")
    assert workflow.command(
        p["id"],
        "supply.receive",
        actor_name="supply",
        commitment_id=commit["id"],
        material_lot_id=commit["lot_id"],
        quantity="1",
        unit="kg",
        source=file_claim,
        expected_status=409,
    )
    assert workflow.balance(p["id"], req["id"])["received"] == "0"
    assert workflow.command(
        p["id"],
        "material.define",
        actor_name="supply",
        material_id="steel-1",
        lot_id="expired",
        owner_id="Customer 1",
        unit="kg",
        scale=3,
        expiry="2020-01-01",
        source=workflow.source(f"expired-{uuid4()}", object_type="material_lot"),
        expected_status=409,
    )


def test_promise_amendment_retains_original_and_current(workflow):
    p, _, commit = workflow.material_requirement(qualified="0")
    prior = workflow.object(p["id"], "commitment", commit["id"])
    amended = workflow.command(
        p["id"],
        "supply.commit",
        actor_name="supply",
        commitment_id=commit["id"],
        requirement_id=prior["requirement_id"],
        type="customer",
        owner_id="Customer 1",
        quantity="100",
        unit="kg",
        original_due=prior["original_due"],
        current_due="2026-12-10",
        source=workflow.source(
            prior["source"]["external_id"] + " ", system=" ERP ",
            object_type=" Commitment ", version=2
        ),
    )
    assert amended["object_id"] == commit["id"]
    value = workflow.object(p["id"], "commitment", commit["id"])
    assert value["original_due"] != value["current_due"]
    assert value["current_due"] == "2026-12-10"
    assert len(value["promise_revisions"]) == 2
    assert value["source"]["system"] == " ERP "


def test_existing_promise_source_cannot_create_second_commitment_without_id(workflow):
    p, req, commit = workflow.material_requirement(qualified="0")
    original = workflow.object(p["id"], "commitment", commit["id"])
    alias = workflow.source(
        original["source"]["external_id"] + " ",
        system=" ERP ",
        object_type=" Commitment ",
        version=2,
    )
    before = workflow.balance(p["id"], req["id"])
    result = workflow.command(
        p["id"], "supply.commit", actor_name="supply", expected_status=409,
        requirement_id=req["id"], type="customer", owner_id="Customer 1",
        quantity="100", unit="kg", original_due=original["original_due"],
        current_due="2026-12-10", source=alias,
    )
    assert result["code"] == "SOURCE_CONFLICT"
    assert workflow.balance(p["id"], req["id"]) == before
    assert workflow.client().get(f"{BASE}/projects/{p['id']}/objects/commitment").json()["total"] == 1


def test_receipt_source_alias_is_not_counted_twice(workflow):
    p, req, commit = workflow.material_requirement(qualified="0")
    workflow.receive(p["id"], commit["id"], quantity="20", lot_id=commit["lot_id"],
                     source=workflow.source("shipment-7", system="ERP", object_type="receipt"))
    result = workflow.command(
        p["id"], "supply.receive", actor_name="supply", expected_status=409,
        commitment_id=commit["id"], material_lot_id=commit["lot_id"],
        quantity="20", unit="kg",
        source=workflow.source("shipment-7 ", system=" erp ", object_type=" Receipt "),
    )
    assert result["code"] == "SOURCE_CONFLICT"
    assert workflow.balance(p["id"], req["id"])["received"] == "20"


def test_amendment_requires_matching_existing_promise_identity(workflow):
    p, req, commit = workflow.material_requirement(qualified="0")
    original = workflow.object(p["id"], "commitment", commit["id"])
    result = workflow.command(
        p["id"], "supply.commit", actor_name="supply", expected_status=409,
        commitment_id=commit["id"], requirement_id=req["id"], type="customer",
        owner_id="Customer 1", quantity="100", unit="kg",
        original_due=original["original_due"], current_due="2026-12-10",
        source=workflow.source("other-promise", object_type="commitment", version=2),
    )
    assert result["code"] == "PRECONDITION_FAILED"


def test_same_clock_plan_acceptance_uses_project_sequence(workflow, monkeypatch):
    from manufacturing_platform.workflow import service

    p, req, commit = workflow.material_requirement(qualified="0")
    fixed = datetime.now(UTC)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(service, "datetime", FixedDatetime)
    first_source = workflow.object(p["id"], "plan",
        workflow.object(p["id"], "requirement", req["id"])["plan_id"])["source"]

    def plan(source, scope):
        return workflow.command(
            p["id"], "plan.receive", actor_name="planner", source=source,
            input_revision_ids=[commit["revision_id"]],
            input_order_versions=[{"order_line_id":commit["order_id"],"version":1}],
            requirements=[{"work_order_id":commit["work_order_id"],
                "execution_scope":scope,"material_id":"steel-1",
                "owner_id":"Customer 1","quantity":"50","unit":"kg"}],
        )

    common = {"occurred_at":(fixed-timedelta(minutes=2)).isoformat(),
              "collected_at":(fixed-timedelta(minutes=1)).isoformat(),
              "cutoff":(fixed-timedelta(minutes=2)).isoformat()}
    source_a = workflow.source(first_source["external_id"],object_type="plan",version=2)
    source_a.update(common)
    a = plan(source_a, "trial")
    source_b = workflow.source(f"other-plan-{uuid4()}",object_type="plan",version=1)
    source_b.update(common)
    b = plan(source_b, "bulk")
    assert a["object_id"] != b["object_id"]
    wo = workflow.object(p["id"], "work_order", commit["work_order_id"])
    assert wo["trial_readiness"]["input_versions"]["plan_id"] == b["object_id"]
    assert next(c for c in wo["trial_readiness"]["checks"] if c["kind"]=="plan")["status"]=="blocked"
    assert next(c for c in wo["bulk_readiness"]["checks"] if c["kind"]=="plan")["status"]=="ready"
    page = workflow.client().get(f"{BASE}/projects/{p['id']}/objects/requirement").json()["items"]
    assert next(r for r in page if r["id"]==req["id"])["state"]=="superseded"


def test_missing_declared_plan_inputs_are_visible_rejected_evidence(workflow):
    p, _, commit = workflow.material_requirement(qualified="0")
    other, _, _, foreign_revision = workflow.order_workorder(quantity="5")
    assert other["id"] != p["id"]
    now = datetime.now(UTC)
    source = workflow.source(f"unresolved-{uuid4()}", object_type="plan")
    source.update(occurred_at=(now-timedelta(minutes=2)).isoformat(),
                  collected_at=(now-timedelta(minutes=1)).isoformat(),
                  cutoff=(now-timedelta(minutes=2)).isoformat())
    result = workflow.command(
        p["id"], "plan.receive", actor_name="planner", source=source,
        input_revision_ids=[commit["revision_id"], foreign_revision["id"]],
        input_order_versions=[{"order_line_id":commit["order_id"],"version":1},
                              {"order_line_id":str(uuid4()),"version":1}],
        requirements=[{"work_order_id":commit["work_order_id"],
            "execution_scope":"bulk","material_id":"steel-1",
            "owner_id":"Customer 1","quantity":"100","unit":"kg"}],
    )
    value = workflow.object(p["id"], "plan", result["object_id"])
    assert value["state"] == "rejected"
    assert "declared revision input missing" in value["reason"]
    assert "declared order input missing" in value["reason"]
    assert foreign_revision["id"] not in value["reason"]
    assert value["requirement_ids"] == []


def test_corrected_plan_reuses_business_identity_with_new_source_version(workflow):
    p, req, commit = workflow.material_requirement(qualified="0")
    receipt = workflow.receive(
        p["id"], commit["id"], quantity="20", lot_id=commit["lot_id"]
    )
    workflow.inspect(p["id"], receipt["object_id"], accepted="15", rejected="5")
    first = workflow.object(
        p["id"], "plan", workflow.object(p["id"], "requirement", req["id"])["plan_id"]
    )
    now = datetime.now(UTC)
    source = workflow.source(
        first["source"]["external_id"], object_type="plan", version=2
    )
    source.update(
        occurred_at=(now - timedelta(minutes=2)).isoformat(),
        collected_at=(now - timedelta(minutes=1)).isoformat(),
        cutoff=(now - timedelta(minutes=2)).isoformat(),
    )
    revised = workflow.command(
        p["id"],
        "plan.receive",
        actor_name="planner",
        source=source,
        input_revision_ids=[commit["revision_id"]],
        input_order_versions=[{"order_line_id": commit["order_id"], "version": 1}],
        requirements=[
            {
                "work_order_id": commit["work_order_id"],
                "execution_scope": "trial",
                "material_id": "steel-1",
                "owner_id": "Customer 1",
                "quantity": "50",
                "unit": "kg",
            }
        ],
    )
    assert (
        revised["object_id"]
        != workflow.object(p["id"], "requirement", req["id"])["plan_id"]
    )
    assert (
        workflow.object(p["id"], "plan", revised["object_id"])["state"] == "confirmed"
    )
    assert (
        workflow.client().get(f"{BASE}/projects/{p['id']}/objects/plan").json()["total"]
        == 2
    )
    old_req = workflow.object(p["id"], "requirement", req["id"])
    new_id = workflow.object(p["id"], "plan", revised["object_id"])["requirement_ids"][
        0
    ]
    new_req = workflow.object(p["id"], "requirement", new_id)
    assert new_req["supersedes_requirement_id"] == req["id"]
    assert new_req["lineage_id"] == old_req["lineage_id"]
    assert new_req["balance"]["required"] == "50"
    assert new_req["balance"]["received"] == "20"
    assert new_req["balance"]["qualified"] == "15"
    readiness = workflow.object(p["id"], "work_order", commit["work_order_id"])[
        "trial_readiness"
    ]
    assert readiness["input_versions"]["plan_id"] == revised["object_id"]
    assert readiness["input_versions"]["plan_cutoff"] == source["cutoff"]
    page = (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/requirement")
        .json()["items"]
    )
    states = {r["id"]: r["state"] for r in page}
    assert states[req["id"]] == "superseded" and states[new_id] == "required"
    assert workflow.command(
        p["id"],
        "supply.commit",
        actor_name="supply",
        requirement_id=req["id"],
        type="purchase",
        owner_id="Customer 1",
        quantity="10",
        unit="kg",
        original_due="2026-12-01",
        current_due="2026-12-01",
        source=workflow.source(f"old-{uuid4()}", object_type="commitment"),
        expected_status=409,
    )


def test_plan_version_mismatch_is_visible_and_trial_scope_excludes_bulk(workflow):
    p, req, commit = workflow.material_requirement(qualified="0", scope="trial")
    assert workflow.balance(p["id"], req["id"])["shortage"] == "100"
    now = datetime.now(UTC)
    source = workflow.source(f"stale-{uuid4()}", object_type="plan")
    source.update(
        occurred_at=(now - timedelta(minutes=2)).isoformat(),
        collected_at=(now - timedelta(minutes=1)).isoformat(),
        cutoff=(now - timedelta(minutes=2)).isoformat(),
    )
    wrong = workflow.command(
        p["id"],
        "plan.receive",
        actor_name="planner",
        source=source,
        input_revision_ids=[commit["revision_id"]],
        input_order_versions=[{"order_line_id": commit["order_id"], "version": 999}],
        requirements=[
            {
                "work_order_id": commit["work_order_id"],
                "execution_scope": "bulk",
                "material_id": "steel-1",
                "owner_id": "Customer 1",
                "quantity": "100",
                "unit": "kg",
            }
        ],
    )
    detail = workflow.object(p["id"], "plan", wrong["object_id"])
    assert detail["state"] == "rejected" and "version" in detail["reason"]
    wo = workflow.object(p["id"], "work_order", commit["work_order_id"])
    assert (
        next(c for c in wo["trial_readiness"]["checks"] if c["kind"] == "plan")[
            "status"
        ]
        == "ready"
    )
    assert (
        next(c for c in wo["bulk_readiness"]["checks"] if c["kind"] == "material")[
            "status"
        ]
        == "blocked"
    )


def test_future_plan_cutoff_is_retained_as_rejected_fact(workflow):
    p, _, commit = workflow.material_requirement(qualified="0")
    later = datetime.now(UTC) + timedelta(minutes=1)
    source = workflow.source(f"future-{uuid4()}", object_type="plan")
    source.update(
        occurred_at=later.isoformat(),
        collected_at=later.isoformat(),
        cutoff=later.isoformat(),
    )
    result = workflow.command(
        p["id"],
        "plan.receive",
        actor_name="planner",
        source=source,
        input_revision_ids=[commit["revision_id"]],
        input_order_versions=[{"order_line_id": commit["order_id"], "version": 1}],
        requirements=[
            {
                "work_order_id": commit["work_order_id"],
                "execution_scope": "trial",
                "material_id": "steel-1",
                "owner_id": "Customer 1",
                "quantity": "50",
                "unit": "kg",
            }
        ],
    )
    value = workflow.object(p["id"], "plan", result["object_id"])
    assert value["state"] == "rejected" and "future" in value["reason"]


def test_expired_plan_cutoff_is_retained_as_rejected_fact(workflow):
    p, _, commit = workflow.material_requirement(qualified="0")
    old = datetime.now(UTC) - timedelta(hours=25)
    source = workflow.source(f"expired-plan-{uuid4()}", object_type="plan")
    source.update(
        occurred_at=old.isoformat(),
        collected_at=old.isoformat(),
        cutoff=old.isoformat(),
    )
    result = workflow.command(
        p["id"],
        "plan.receive",
        actor_name="planner",
        source=source,
        input_revision_ids=[commit["revision_id"]],
        input_order_versions=[{"order_line_id": commit["order_id"], "version": 1}],
        requirements=[
            {
                "work_order_id": commit["work_order_id"],
                "execution_scope": "trial",
                "material_id": "steel-1",
                "owner_id": "Customer 1",
                "quantity": "50",
                "unit": "kg",
            }
        ],
    )
    value = workflow.object(p["id"], "plan", result["object_id"])
    assert value["state"] == "rejected" and "expired" in value["reason"]


def test_latest_confirmed_bulk_plan_does_not_reuse_old_trial_line(workflow):
    p, req, commit = workflow.material_requirement(qualified="0")
    first = workflow.object(
        p["id"], "plan", workflow.object(p["id"], "requirement", req["id"])["plan_id"]
    )
    now = datetime.now(UTC)
    source = workflow.source(
        first["source"]["external_id"], object_type="plan", version=2
    )
    source.update(
        occurred_at=(now - timedelta(minutes=2)).isoformat(),
        collected_at=(now - timedelta(minutes=1)).isoformat(),
        cutoff=(now - timedelta(minutes=2)).isoformat(),
    )
    workflow.command(
        p["id"],
        "plan.receive",
        actor_name="planner",
        source=source,
        input_revision_ids=[commit["revision_id"]],
        input_order_versions=[{"order_line_id": commit["order_id"], "version": 1}],
        requirements=[
            {
                "work_order_id": commit["work_order_id"],
                "execution_scope": "bulk",
                "material_id": "steel-1",
                "owner_id": "Customer 1",
                "quantity": "50",
                "unit": "kg",
            }
        ],
    )
    wo = workflow.object(p["id"], "work_order", commit["work_order_id"])
    assert (
        next(c for c in wo["trial_readiness"]["checks"] if c["kind"] == "plan")[
            "status"
        ]
        == "blocked"
    )
    assert (
        next(c for c in wo["bulk_readiness"]["checks"] if c["kind"] == "plan")["status"]
        == "ready"
    )


def test_iqc_requires_live_quality_inspection_grant(workflow):
    p, _, commit = workflow.material_requirement(qualified="0")
    receipt = workflow.receive(
        p["id"], commit["id"], quantity="1", lot_id=commit["lot_id"]
    )
    workflow.grant(p["id"], "quality", ["quality"], [])
    assert (
        workflow.command(
            p["id"],
            "supply.inspect",
            actor_name="quality",
            receipt_id=receipt["object_id"],
            accepted="1",
            rejected="0",
            evidence="check",
            expected_status=403,
        )["code"]
        == "FORBIDDEN"
    )
    assert (
        workflow.command(
            p["id"],
            "supply.inspect",
            actor_name="owner",
            receipt_id=receipt["object_id"],
            accepted="1",
            rejected="0",
            evidence="admin check",
            expected_status=403,
        )["code"]
        == "FORBIDDEN"
    )


def test_supply_pages_are_bounded_and_empty_plan_never_ready(workflow):
    p, _, wo, _ = workflow.order_workorder()
    read = workflow.object(p["id"], "work_order", wo["id"])
    assert (
        next(c for c in read["trial_readiness"]["checks"] if c["kind"] == "plan")[
            "status"
        ]
        == "blocked"
    )
    page = (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/plan?limit=1&offset=0")
        .json()
    )
    assert page["total"] == 0 and page["items"] == []


def test_v3_database_migrates_supply_without_touching_existing_orders(workflow):
    import sqlite3

    p, order, _, _ = workflow.order_workorder()
    with sqlite3.connect(workflow.paths.domain) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        for view in ("effective_supply_receipts", "effective_iqc_results"):
            db.execute(f"DROP VIEW {view}")
        for table in ("source_corrections", "exchange_discrepancies", "source_confirmations", "exchange_receipts", "exchange_events", "exchanges"):
            db.execute(f"DROP TABLE {table}")
        db.execute("ALTER TABLE reservations DROP COLUMN exchange_id")
        db.execute("ALTER TABLE reservations DROP COLUMN accepted_sequence")
        for table in (
            "reservations",
            "iqc_results",
            "supply_receipts",
            "supply_promise_revisions",
            "supply_commitments",
            "requirements",
            "plans",
            "material_lots",
        ):
            db.execute(f"DROP TABLE {table}")
        db.execute("UPDATE schema_version SET version=3")
    workflow.reopen()
    assert (
        workflow.object(p["id"], "order_line", order["id"])["current_quantity"] == "5"
    )
    workflow.grant(p["id"], "supply", ["supply"])
    assert (
        workflow.command(
            p["id"],
            "material.define",
            actor_name="supply",
            material_id="steel",
            lot_id="v3-lot",
            owner_id="Customer 1",
            unit="kg",
            scale=3,
            expiry="2027-12-01",
            source=workflow.source(f"v3-{uuid4()}", object_type="material_lot"),
        )["object_type"]
        == "material_lot"
    )
    with workflow.db() as db:
        assert db.execute("SELECT version FROM schema_version").fetchone()[0] == 7


def test_v4_migration_orders_audited_plans_and_normalizes_supply_keys(workflow):
    import json
    import sqlite3

    p, req, commit = workflow.material_requirement(qualified="0")
    plan_id = workflow.object(p["id"], "requirement", req["id"])["plan_id"]
    with sqlite3.connect(workflow.paths.domain) as db:
        source = json.loads(db.execute("SELECT source_json FROM plans WHERE id=?", (plan_id,)).fetchone()[0])
        source["system"] = " ERP "
        source["external_id"] += " "
        db.execute("UPDATE plans SET source_json=?,source_system=?,source_type=?,source_external_id=? WHERE id=?",
                   (json.dumps(source), " ERP ", " Plan ", source["external_id"], plan_id))
        for view in ("effective_supply_receipts", "effective_iqc_results"):
            db.execute(f"DROP VIEW {view}")
        for table in ("source_corrections", "exchange_discrepancies", "source_confirmations", "exchange_receipts", "exchange_events", "exchanges"):
            db.execute(f"DROP TABLE {table}")
        db.execute("ALTER TABLE reservations DROP COLUMN exchange_id")
        db.execute("ALTER TABLE reservations DROP COLUMN accepted_sequence")
        db.execute("DROP INDEX plans_acceptance_order")
        db.execute("ALTER TABLE plans DROP COLUMN accepted_seq")
        db.execute("UPDATE schema_version SET version=4")
    workflow.reopen()
    old = workflow.object(p["id"], "plan", plan_id)
    assert old["source"]["system"] == " ERP "
    with workflow.db() as db:
        row = db.execute("SELECT source_system,source_type,source_external_id,accepted_seq FROM plans WHERE id=?", (plan_id,)).fetchone()
        assert tuple(row) == ("erp", "plan", source["external_id"].strip(), 1)
        assert db.execute("SELECT version FROM schema_version").fetchone()[0] == 7
    source["system"] = "erp"
    source["external_id"] = source["external_id"].strip()
    source["version"] = 2
    now = datetime.now(UTC)
    source.update(occurred_at=(now - timedelta(minutes=2)).isoformat(),
                  collected_at=(now - timedelta(minutes=1)).isoformat(),
                  cutoff=(now - timedelta(minutes=2)).isoformat())
    result = workflow.command(p["id"], "plan.receive", actor_name="planner", source=source,
                              input_revision_ids=[commit["revision_id"]],
                              input_order_versions=[{"order_line_id": commit["order_id"], "version": 1}],
                              requirements=[{"work_order_id": commit["work_order_id"], "execution_scope": "trial",
                                             "material_id": "steel-1", "owner_id": "Customer 1",
                                             "quantity": "100", "unit": "kg"}])
    with workflow.db() as db:
        assert db.execute("SELECT accepted_seq FROM plans WHERE id=?", (result["object_id"],)).fetchone()[0] == 2


def test_v4_migration_fails_closed_on_historical_blank_source_key(workflow):
    import json
    import sqlite3

    from manufacturing_platform.workflow.orders import source_key
    from manufacturing_platform.workflow.store import WorkflowStore

    with pytest.raises(ValueError, match="source identity"):
        source_key({"system": " \t ", "object_type": "plan", "external_id": "legacy"})
    p, req, _ = workflow.material_requirement(qualified="0")
    plan_id = workflow.object(p["id"], "requirement", req["id"])["plan_id"]
    with sqlite3.connect(workflow.paths.domain) as db:
        source = json.loads(db.execute("SELECT source_json FROM plans WHERE id=?", (plan_id,)).fetchone()[0])
        source["system"] = " \t "
        db.execute("UPDATE plans SET source_json=? WHERE id=?", (json.dumps(source), plan_id))
        for view in ("effective_supply_receipts", "effective_iqc_results"):
            db.execute(f"DROP VIEW {view}")
        for table in ("source_corrections", "exchange_discrepancies", "source_confirmations", "exchange_receipts", "exchange_events", "exchanges"):
            db.execute(f"DROP TABLE {table}")
        db.execute("ALTER TABLE reservations DROP COLUMN exchange_id")
        db.execute("ALTER TABLE reservations DROP COLUMN accepted_sequence")
        db.execute("DROP INDEX plans_acceptance_order")
        db.execute("ALTER TABLE plans DROP COLUMN accepted_seq")
        db.execute("UPDATE schema_version SET version=4")
    store = WorkflowStore(str(workflow.paths.domain), str(workflow.paths.authority),
                          {"id": "workflow-test", "mode": "test", "label": "Workflow test"})
    with pytest.raises(ValueError, match="source identity"), store.transaction():
        pass
    with workflow.db() as db:
        assert db.execute("SELECT version FROM schema_version").fetchone()[0] == 4
        assert "accepted_seq" not in {row[1] for row in db.execute("PRAGMA table_info(plans)")}


def test_requirement_page_exposes_bounded_balance_columns(workflow):
    p, req, _ = workflow.material_requirement(required="100", qualified="80")
    page = (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/requirement?limit=1&offset=0")
        .json()
    )
    assert page["total"] == 1 and len(page["items"]) == 1
    assert page["items"][0]["id"] == req["id"]
    balance = page["items"][0]["material_balance"]
    assert [
        balance[k]
        for k in (
            "required",
            "in_transit",
            "received",
            "qualified",
            "reserved",
            "shortage",
            "unit",
        )
    ] == ["100", "20", "80", "80", "0", "100", "kg"]
    assert balance["cutoff"] is not None
