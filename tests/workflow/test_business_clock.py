"""Trusted simulation time never replaces authentication or evidence wall time."""

from datetime import UTC, datetime
import sqlite3
from uuid import uuid4

import pytest

from manufacturing_platform.workflow.store import WorkflowStore
from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter


def test_business_clock_is_per_connection_and_validated(tmp_path):
    from manufacturing_platform.workflow.clock import business_time

    dates = [datetime(2026, 10, 28, tzinfo=UTC), datetime(2027, 1, 2, tzinfo=UTC)]
    stores = [
        WorkflowStore(
            str(tmp_path / f"w{i}.db"),
            str(tmp_path / f"a{i}.db"),
            {"id": f"d{i}", "mode": "test", "label": "test"},
            business_clock=lambda d=d: d,
        )
        for i, d in enumerate(dates)
    ]
    with stores[0].transaction() as a, stores[1].transaction() as b:
        assert business_time(a) == dates[0]
        assert business_time(b) == dates[1]
        with sqlite3.connect(":memory:") as ordinary:
            assert (
                abs((business_time(ordinary) - datetime.now(UTC)).total_seconds()) < 2
            )
    with pytest.raises(ValueError, match="UTC"):
        WorkflowStore(
            str(tmp_path / "bad.db"),
            str(tmp_path / "other.db"),
            {"id": "bad", "mode": "test", "label": "test"},
            business_clock=lambda: datetime(2026, 10, 28),
        )


def test_authority_source_time_uses_trusted_business_clock(tmp_path):
    clock = datetime(2026, 10, 28, tzinfo=UTC)
    adapter = MockAuthorityAdapter(
        str(tmp_path / "authority.db"), "clock-test", business_clock=lambda: clock
    )
    receipt = adapter.receive(
        project_id=uuid4(),
        external_id="receipt",
        commitment_id=uuid4(),
        lot_id=uuid4(),
        material_id="steel",
        owner_id="customer",
        quantity="1",
        unit="kg",
        scale=3,
        expiry="2026-10-29",
        external_actor="WMS",
        signature="signed",
    )
    assert receipt.source.occurred_at == clock


def test_tied_review_clock_uses_recorded_order_not_uuid(workflow, monkeypatch):
    from uuid import UUID
    from manufacturing_platform.workflow import orders
    from .test_orders import record, approve, register

    workflow.business_clock = lambda: datetime(2026, 10, 28, tzinfo=UTC)
    workflow.reopen()
    p = workflow.create_project()
    demand = record(workflow, p["id"])
    approve(workflow, p["id"], demand)
    ids = iter(
        [
            UUID("ffffffff-ffff-4fff-8fff-ffffffffffff"),
            UUID("00000000-0000-4000-8000-000000000001"),
        ]
    )
    monkeypatch.setattr(orders, "uuid4", lambda: next(ids))
    for decision in ("rejected", "approved"):
        workflow.command(
            p["id"],
            "demand.review",
            demand_id=demand,
            dimension="quality",
            decision=decision,
            evidence=decision,
        )
    monkeypatch.undo()
    assert register(workflow, p["id"], demand)
    with workflow.db() as db:
        rows = db.execute(
            "SELECT decision,accepted_seq FROM reviews WHERE demand_id=? ORDER BY accepted_seq",
            (demand,),
        ).fetchall()
    assert [r["decision"] for r in rows][-2:] == ["rejected", "approved"]


def test_tied_handoff_readiness_and_customer_decisions_keep_acceptance_order(workflow):
    workflow.business_clock = lambda: datetime(2026, 10, 28, tzinfo=UTC)
    workflow.reopen()
    p, _, wo, rev = workflow.order_workorder(
        contract={
            "customer_approval_required": True,
            "customer_release_required": True,
            "acceptance_required": True,
            "customer_revision": "C1",
            "internal_revision": "M1",
            "material_ownership_rules": "Customer 1",
        }
    )
    for value in ("wrong", "M1"):
        workflow.command(
            p["id"],
            "engineering.handoff",
            actor_name="engineering",
            revision_id=rev["id"],
            to_system="MES",
            received_revision=value,
            decision="accepted",
            evidence=value,
        )
    for decision in ("unknown", "approved"):
        workflow.command(
            p["id"],
            "engineering.customer_approval",
            revision_id=rev["id"],
            customer_id="Customer 1",
            external_signatory="Customer QE",
            decision=decision,
            evidence=decision,
        )
    for decision in ("rejected", "verified"):
        workflow.command(
            p["id"],
            "readiness.record",
            actor_name="engineering",
            work_order_id=wo["id"],
            kind="equipment",
            reference="cal",
            evidence=decision,
            decision=decision,
            valid_until="2027-01-01T00:00:00Z",
        )
    detail = workflow.object(p["id"], "revision", rev["id"])
    assert [h["status"] for h in detail["handoffs"]] == [
        "verified",
        "rejected",
        "verified",
    ]
    with workflow.db() as db:
        for table in ("handoffs", "customer_approvals", "readiness_checks"):
            values = list(
                db.execute(f"SELECT accepted_seq FROM {table} ORDER BY rowid")
            )
            assert [r[0] for r in values] == sorted({r[0] for r in values})
    checks = workflow.object(p["id"], "work_order", wo["id"])["trial_readiness"][
        "checks"
    ]
    assert all(
        c["status"] == "ready"
        for c in checks
        if c["kind"] in ("equipment", "customer", "version")
    )


def test_v14_order_migration_preserves_all_original_fact_and_audit_bytes(workflow):
    workflow.business_clock = lambda: datetime(2026, 10, 28, tzinfo=UTC)
    workflow.reopen()
    p, _, wo, rev = workflow.order_workorder()
    workflow.command(
        p["id"],
        "readiness.record",
        actor_name="engineering",
        work_order_id=wo["id"],
        kind="equipment",
        reference="cal",
        evidence="original calibration",
        decision="verified",
        valid_until="2027-01-01T00:00:00Z",
    )
    workflow._client.close()
    # Schema-only reconstruction of supported v14; every business row came from HTTP.
    with sqlite3.connect(workflow.paths.domain) as db:
        for table in ("reviews", "handoffs", "readiness_checks"):
            db.execute(f"DROP INDEX IF EXISTS {table}_acceptance_order")
            db.execute(f"ALTER TABLE {table} DROP COLUMN accepted_seq")
        db.execute("UPDATE schema_version SET version=14")
        tables = (
            "reviews",
            "handoffs",
            "readiness_checks",
            "operations",
            "audit_events",
        )
        before = {
            t: (
                list(db.execute(f"SELECT * FROM {t} ORDER BY rowid")),
                [r[1] for r in db.execute(f"PRAGMA table_info({t})")],
            )
            for t in tables
        }
    workflow.reopen()
    assert workflow.object(p["id"], "work_order", wo["id"])["revision_id"] == rev["id"]
    with workflow.db() as db:
        for table, (rows, columns) in before.items():
            assert [
                tuple(r)
                for r in db.execute(
                    f"SELECT {','.join(columns)} FROM {table} ORDER BY rowid"
                )
            ] == rows
        assert db.execute("SELECT version FROM schema_version").fetchone()[0] == 16


def test_clock_binding_resets_after_nested_error(tmp_path):
    from manufacturing_platform.workflow.clock import bind_business_clock, business_time

    date = datetime(2026, 10, 28, tzinfo=UTC)
    with sqlite3.connect(":memory:") as a, sqlite3.connect(":memory:") as b:
        with bind_business_clock(a, lambda: date):
            with pytest.raises(RuntimeError):
                with bind_business_clock(b, lambda: date.replace(year=2027)):
                    raise RuntimeError("rollback")
            assert business_time(a) == date
            assert abs((business_time(b) - datetime.now(UTC)).total_seconds()) < 2
        assert abs((business_time(a) - datetime.now(UTC)).total_seconds()) < 2


def test_business_clock_isolated_across_threads(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from manufacturing_platform.workflow.clock import business_time

    barrier = Barrier(2)

    def read(year):
        date = datetime(year, 10, 28, tzinfo=UTC)
        store = WorkflowStore(
            str(tmp_path / f"{year}.db"),
            str(tmp_path / f"{year}-authority.db"),
            {"id": str(year), "mode": "test", "label": "Concurrent clock"},
            business_clock=lambda: date,
        )
        with store.transaction() as tx:
            barrier.wait(timeout=5)
            assert business_time(tx) == date
        return date

    with ThreadPoolExecutor(2) as pool:
        assert [v.year for v in pool.map(read, [2026, 2027])] == [2026, 2027]
