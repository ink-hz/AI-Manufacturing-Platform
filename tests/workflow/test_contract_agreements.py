"""Scoped successor agreements retain original contract and fixed history."""

from datetime import datetime
from uuid import uuid4

from .conftest import BASE
from .test_engineering_readiness import _check, _evaluate
from .test_execution import running_execution
from .test_quality import measure


def agree(workflow, pid, revision, **overrides):
    revision = workflow.object(pid, "revision", revision["id"])
    policy = workflow.client().get(f"{BASE}/projects/{pid}").json()["contract"]
    policy = {
        **policy,
        "customer_revision": revision["customer_revision"],
        "internal_revision": revision["internal_revision"],
        "customer_approval_required": True,
        "customer_release_required": True,
        "acceptance_required": True,
    }
    return workflow.command(
        pid,
        "contract.agree",
        revision_id=revision["id"],
        contract=policy,
        customer_id="Customer 1",
        external_signatory="Customer contract owner",
        evidence="Signed scoped successor conditions",
        **overrides,
    )


def test_oem_successor_agreement_allows_split_without_rewriting_old_scope(
    workflow, monkeypatch
):
    create = workflow.create_project
    monkeypatch.setattr(
        workflow, "create_project", lambda **kw: create(**{**kw, "mode": "oem"})
    )
    p, wo, units, _, base = running_execution(workflow)
    pid = p["id"]
    workflow.command(
        pid,
        "execution.record",
        actor_name="production",
        source=workflow.source(str(uuid4()), object_type="execution"),
        **base,
    )
    workflow.grant(
        pid, "quality", ["quality"], ["inspection", "disposition", "quality_release"]
    )
    measure(workflow, p, units[0])
    old = workflow.object(pid, "unit", units[0])
    old_release = workflow.command(
        pid,
        "release.decide",
        kind="customer",
        unit_ids=[units[0]],
        decision="approved",
        evidence="C1 historical receipt",
        customer_id="Customer 1",
        revision_id=old["revision_id"],
        customer_revision="C1",
        external_signatory="Original customer QE",
        method="manual",
        source=workflow.source(str(uuid4()), object_type="customer_release"),
    )
    old_release_value = workflow.object(pid, "release", old_release["object_id"])
    with workflow.db() as db:
        contract_bytes = db.execute(
            "SELECT contract_json FROM projects WHERE id=?", (pid,)
        ).fetchone()[0]
    new = workflow.revision(pid, internal_revision="M2", customer_revision="C2")
    workflow.command(
        pid,
        "engineering.handoff",
        actor_name="engineering",
        revision_id=new["id"],
        to_system="MES",
        received_revision="M2",
        decision="accepted",
        evidence="MES receipt",
    )
    workflow.command(
        pid,
        "engineering.customer_approval",
        revision_id=new["id"],
        customer_id="Customer 1",
        external_signatory="Customer QE",
        decision="approved",
        evidence="C2 approval",
    )
    eco = workflow.command(
        pid,
        "eco.open",
        actor_name="engineering",
        old_revision_id=old["revision_id"],
        new_revision_id=new["id"],
        effective_work_order_ids=[wo["id"]],
        reason="Customer C2 evolution",
    )
    switch = {
        "eco_id": eco["object_id"],
        "target_work_order_id": wo["id"],
        "new_revision_id": new["id"],
        "evidence": "Retain actual C1 and split unexecuted C2",
    }
    workflow.command(
        pid, "eco.switch", actor_name="engineering", expected_status=409, **switch
    )
    agreement = agree(workflow, pid, new)
    result = workflow.command(pid, "eco.switch", actor_name="engineering", **switch)
    workflow.command(
        pid,
        "exchange.dispatch",
        actor_name="engineering",
        exchange_id=result["exchange_id"],
    )
    fresh = workflow.object(pid, "work_order", result["object_id"])
    assert fresh["revision_id"] == new["id"] and fresh["quantity"] == "4"
    assert (
        _check(
            _evaluate(workflow, pid, result["object_id"], "trial"), "customer"
        ).status
        == "ready"
    )
    assert (
        workflow.object(pid, "unit", units[0])["execution_events"]
        == old["execution_events"]
    )
    assert workflow.object(pid, "unit", units[0])["revision_id"] == old["revision_id"]
    assert (
        workflow.object(pid, "release", old_release["object_id"]) == old_release_value
    )
    assert workflow.object(pid, "unit", units[0])["final_good"] is True
    assert (
        _check(_evaluate(workflow, pid, wo["id"], "trial"), "customer").status
        == "ready"
    )
    with workflow.db() as db:
        assert (
            db.execute(
                "SELECT contract_json FROM projects WHERE id=?", (pid,)
            ).fetchone()[0]
            == contract_bytes
        )
    assert (
        workflow.object(pid, "revision", new["id"])["contract_agreement"][
            "project_version"
        ]
        == agreement["project_version"]
    )


def test_unknown_conditions_confirm_with_scoped_evidence_and_current_actor_policy(
    workflow,
):
    p, _, wo, revision = workflow.order_workorder()
    pid = p["id"]
    assert (
        _check(_evaluate(workflow, pid, wo["id"], "trial"), "customer").status
        == "blocked"
    )
    agree(workflow, pid, revision, actor_name="engineering", expected_status=403)
    agree(workflow, pid, revision)
    assert (
        _check(_evaluate(workflow, pid, wo["id"], "trial"), "customer").status
        == "blocked"
    )  # independent approval still missing
    workflow.command(
        pid,
        "engineering.customer_approval",
        revision_id=revision["id"],
        customer_id="Customer 1",
        external_signatory="Customer QE",
        decision="approved",
        evidence="Approved exact revision",
    )
    assert (
        _check(_evaluate(workflow, pid, wo["id"], "trial"), "customer").status
        == "ready"
    )
    assert (
        workflow.client().get(f"{BASE}/projects/{pid}").json()["contract"]
        == p["contract"]
    )


def test_successor_customer_release_and_late_confirmation_do_not_authorize_backdated_use(
    workflow, monkeypatch
):
    from datetime import timedelta

    from manufacturing_platform.workflow.quality import shipment_eligibility

    from .test_quality import executed

    create = workflow.create_project
    monkeypatch.setattr(
        workflow, "create_project", lambda **kw: create(**{**kw, "mode": "oem"})
    )
    revision_method = workflow.revision

    def successor(pid, **kw):
        revision = revision_method(pid, customer_revision="C2")
        agree(workflow, pid, revision)
        return revision

    monkeypatch.setattr(workflow, "revision", successor)
    p, _, uid, base = executed(workflow)
    pid = p["id"]
    measured = measure(workflow, p, uid)
    revision_id = workflow.object(pid, "test", measured["object_id"])["revision_id"]
    for actor, kind in [("production", "manufacturing"), ("quality", "quality")]:
        workflow.command(
            pid,
            "release.decide",
            actor_name=actor,
            kind=kind,
            unit_ids=[uid],
            decision="approved",
            evidence="Independent signoff",
        )
    with workflow.db() as db:
        assert not shipment_eligibility(db, pid, [uid]).allowed
    fields = {
        "kind": "customer",
        "unit_ids": [uid],
        "decision": "approved",
        "evidence": "Signed C2 receipt",
        "customer_id": "Customer 1",
        "revision_id": revision_id,
        "customer_revision": "C2",
        "external_signatory": "Customer QE",
        "method": "manual",
        "source": workflow.source(str(uuid4()), object_type="customer_release"),
    }
    workflow.command(pid, "release.decide", **fields)
    with workflow.db() as db:
        assert shipment_eligibility(db, pid, [uid]).allowed
        accepted_at = datetime.fromisoformat(
            db.execute(
                "SELECT created_at FROM contract_agreements WHERE revision_id=?",
                (revision_id,),
            ).fetchone()[0]
        )
    backdated = {
        **base,
        "occurred_at": (accepted_at - timedelta(seconds=1)).isoformat(),
    }
    workflow.command(
        pid,
        "execution.record",
        actor_name="production",
        source=workflow.source(str(uuid4()), object_type="execution"),
        **backdated,
    )
    assert (
        workflow.object(pid, "unit", uid)["execution_events"][-1]["status"]
        == "rejected"
    )
    workflow.command(
        pid,
        "release.decide",
        **{
            **fields,
            "source": workflow.source(str(uuid4()), object_type="customer_release"),
            "customer_revision": "C1",
        },
        expected_status=409,
    )


def test_v16_migration_preserves_original_contract_route_operation_and_audit_bytes(
    workflow,
):
    import json
    import sqlite3

    p, _, _, revision = workflow.order_workorder()
    pid = p["id"]
    tables = (
        "projects",
        "engineering_revisions",
        "revision_routes",
        "operations",
        "audit_events",
    )
    with workflow.db() as db:
        saved = {
            table: db.execute("SELECT * FROM " + table).fetchall() for table in tables
        }
        audit = db.execute(
            "SELECT typed_payload FROM audit_events WHERE action='engineering.revision'"
        ).fetchone()[0]
    with sqlite3.connect(workflow.paths.domain) as db:
        db.execute("DROP TABLE contract_agreements")
        db.execute("UPDATE schema_version SET version=16")
    workflow.reopen()
    assert workflow.client().get(f"{BASE}/projects/{pid}").status_code == 200
    with workflow.db() as db:
        assert db.execute("SELECT version FROM schema_version").fetchone()[0] == 17
        for table in tables:
            assert db.execute("SELECT * FROM " + table).fetchall() == saved[table]
    payload = json.loads(audit)
    payload.pop("project_id", None)
    replay = workflow.client("engineering").post(
        f"{BASE}/projects/{pid}/commands", json=payload
    )
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert (
        "material_consumption"
        not in workflow.object(pid, "revision", revision["id"])["route_steps"][0]
    )
