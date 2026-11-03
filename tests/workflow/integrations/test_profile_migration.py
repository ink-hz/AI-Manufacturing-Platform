"""Actual frozen schema22, with legacy stored bytes, advances without replay edits."""

import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from manufacturing_platform.workflow.contracts import DomainError
from manufacturing_platform.workflow.integrations.routing import (
    assign_profile,
    profile_for,
)
from manufacturing_platform.workflow.store import WorkflowStore

DATASET = {"id": "migration-fixture", "mode": "test", "label": "Migration fixture"}
PID = UUID("00000000-0000-4000-8000-000000000010")


def store(tmp_path, mode="test"):
    return WorkflowStore(
        str(tmp_path / "workflow.sqlite3"),
        str(tmp_path / "authority.sqlite3"),
        DATASET | {"mode": mode},
    )


def freeze22(tmp_path, version=22):
    db = sqlite3.connect(tmp_path / "workflow.sqlite3")
    ddl = Path(__file__).with_name("schema22.sql").read_text()
    if version == 21:
        # Schema21 boundary is schema22 without the additive handoff DDL.
        from manufacturing_platform.workflow.material_handoff_schema import (
            HANDOFF_SCHEMA,
        )

        assert ddl.endswith(HANDOFF_SCHEMA)
        ddl = ddl[: -len(HANDOFF_SCHEMA)]
    db.executescript(ddl)
    db.execute("INSERT INTO schema_version VALUES (?)", (version,))
    db.execute("INSERT INTO dataset_metadata VALUES (?,?,?)", tuple(DATASET.values()))
    db.execute(
        "INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            str(PID),
            1,
            "Legacy",
            "L1",
            "P1",
            "C1",
            "oem",
            "piece",
            0,
            2,
            '{ "untouched" : true }',
            None,
        ),
    )
    db.execute(
        "INSERT INTO audit_events VALUES (1,?,?,?,?,?,?,?)",
        (
            str(PID),
            "owner",
            "project.create",
            str(PID),
            "2026-01-01",
            "2026-01-01",
            '{ "legacy" : 1 }',
        ),
    )
    db.execute(
        "INSERT INTO operations VALUES (?,?,?,?,?)",
        (DATASET["id"], "owner", "legacy-op", "unchanged-hash", '{ "result" : 1 }'),
    )
    request = '{ "operation_id" : "old", "system" : "erp", "untouched" : "中文" }'
    receipt = '{ "sequence" : 1, "system" : "erp" }'
    db.execute(
        "INSERT INTO exchanges(id,project_id,action,policy_action,system,business_key,mode,request_json,request_hash,phase,receipt_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "exchange-1",
            str(PID),
            "production.start",
            "production.start",
            "erp",
            "legacy-key",
            "mock",
            request,
            "original-hash",
            "accepted",
            receipt,
            "2026-01-01",
        ),
    )
    db.commit()
    snapshot = {
        table: db.execute(f"SELECT * FROM {table}").fetchall()
        for table in ("projects", "operations", "audit_events", "exchanges")
    }
    db.close()
    return snapshot


@pytest.mark.parametrize("version", [21, 22])
def test_migrate_actual_prior_schema_preserves_every_legacy_byte(tmp_path, version):
    before = freeze22(tmp_path, version)
    for _ in range(2):
        with store(tmp_path).transaction(write=True) as tx:
            assert tx.execute("SELECT version FROM schema_version").fetchone()[0] == 23
            for table, rows in before.items():
                assert [tuple(r) for r in tx.execute(f"SELECT * FROM {table}")] == rows
            assert profile_for(tx, PID) == "legacy-erp-v1"
            assert (
                tx.execute("SELECT COUNT(*) FROM integration_intents").fetchone()[0]
                == 0
            )
            assert tx.execute(
                "SELECT name FROM sqlite_master WHERE name='material_handoffs'"
            ).fetchone()
            with pytest.raises(DomainError, match="domain intent"):
                assign_profile(tx, PID, "oem-network-v1")
    assert not (tmp_path / "mock-systems").exists()


def test_fresh_profile_create_assign_then_immutable(workflow):
    project = workflow.create_project()
    with sqlite3.connect(workflow.paths.domain) as tx:
        assert profile_for(tx, UUID(project["id"])) == "legacy-erp-v1"
        assign_profile(tx, UUID(project["id"]), "oem-network-v1")
        assign_profile(tx, UUID(project["id"]), "oem-network-v1")
        assert profile_for(tx, UUID(project["id"])) == "oem-network-v1"
        with pytest.raises(DomainError, match="immutable"):
            assign_profile(tx, UUID(project["id"]), "legacy-erp-v1")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            tx.execute(
                "UPDATE project_integration_profiles SET profile='legacy-erp-v1'"
            )


@pytest.mark.parametrize("boundary", ["audit", "intent"])
def test_initial_assignment_rejected_after_any_domain_intent(workflow, boundary):
    p = workflow.create_project()
    with sqlite3.connect(workflow.paths.domain) as tx:
        if boundary == "audit":
            tx.execute(
                "INSERT INTO audit_events(project_id,actor_id,action,object_id,occurred_at,recorded_at,typed_payload) VALUES (?,?,?,?,?,?,?)",
                (p["id"], "owner", "demand.record", p["id"], "now", "now", "{}"),
            )
        else:
            tx.execute(
                "INSERT INTO integration_intents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "intent",
                    p["id"],
                    "owner",
                    "sap",
                    "sap.release_order",
                    "order.register",
                    1,
                    "{}",
                    "hash",
                    "prepared",
                    "now",
                ),
            )
        with pytest.raises(DomainError, match="domain intent"):
            assign_profile(tx, UUID(p["id"]), "oem-network-v1")


def test_fresh_production_creates_no_mock_store_and_disallows_assignment(tmp_path):
    with store(tmp_path, "production").transaction(write=True) as tx:
        assert tx.execute("SELECT version FROM schema_version").fetchone()[0] == 23
        with pytest.raises(DomainError, match="demo/test"):
            assign_profile(tx, PID, "oem-network-v1")
    assert not (tmp_path / "mock-systems").exists()
    assert not (tmp_path / "authority.sqlite3").exists()


def test_future_schema_rejected(tmp_path):
    freeze22(tmp_path)
    with sqlite3.connect(tmp_path / "workflow.sqlite3") as tx:
        tx.execute("UPDATE schema_version SET version=24")
    with pytest.raises(ValueError, match="dataset mismatch"):
        with store(tmp_path).transaction():
            pass


def test_persisted_intent_identity_is_pinned_and_receipt_is_project_scoped(tmp_path):
    freeze22(tmp_path)
    with store(tmp_path).transaction(write=True) as tx:
        other = str(uuid4())
        tx.execute(
            "INSERT INTO projects SELECT ?,version,name,line_id,product,customer_id,mode,unit_code,unit_scale,q_atoms,contract_json,legacy_project_id FROM projects WHERE id=?",
            (other, str(PID)),
        )
        tx.execute(
            "INSERT INTO integration_intents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "intent",
                str(PID),
                "owner",
                "sap",
                "sap.release_order",
                "order.register",
                1,
                "{}",
                "hash",
                "prepared",
                "now",
            ),
        )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            tx.execute("UPDATE integration_intents SET system='wms' WHERE id='intent'")
        tx.execute("UPDATE integration_intents SET phase='pending' WHERE id='intent'")
        with pytest.raises(sqlite3.IntegrityError):
            tx.execute(
                "INSERT INTO integration_receipts VALUES (?,?,?,?,?)",
                (other, "intent", 1, "{}", "now"),
            )


@pytest.mark.parametrize("recursive_triggers", [0, 1])
def test_sql_replace_and_delete_cannot_erase_pinned_identity(
    tmp_path, recursive_triggers
):
    freeze22(tmp_path)
    with store(tmp_path).transaction(write=True) as tx:
        tx.execute(f"PRAGMA recursive_triggers={recursive_triggers}")
        tx.execute(
            "INSERT INTO project_integration_profiles VALUES (?,?)",
            (str(PID), "oem-network-v1"),
        )
        intent = (
            "intent",
            str(PID),
            "owner",
            "sap",
            "sap.release_order",
            "order.register",
            1,
            '{ "original" : true }',
            "original-hash",
            "prepared",
            "now",
        )
        tx.execute(
            "INSERT INTO integration_intents VALUES (?,?,?,?,?,?,?,?,?,?,?)", intent
        )
        before = {
            table: [tuple(r) for r in tx.execute(f"SELECT * FROM {table}")]
            for table in (
                "project_integration_profiles",
                "integration_intents",
                "exchanges",
                "audit_events",
            )
        }
        for sql, args in [
            (
                "INSERT OR REPLACE INTO project_integration_profiles VALUES (?,?)",
                (str(PID), "legacy-erp-v1"),
            ),
            (
                "INSERT OR REPLACE INTO integration_intents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                intent[:3]
                + (
                    "wms",
                    "wms.ship",
                    "shipment.request",
                    1,
                    "{}",
                    "changed-hash",
                    "prepared",
                    "now",
                ),
            ),
            ("DELETE FROM integration_intents WHERE id=?", ("intent",)),
        ]:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                tx.execute(sql, args)
            assert {
                table: [tuple(r) for r in tx.execute(f"SELECT * FROM {table}")]
                for table in before
            } == before
        assign_profile(tx, PID, "oem-network-v1")
        tx.execute("UPDATE integration_intents SET phase='pending' WHERE id='intent'")
        after = tuple(
            tx.execute("SELECT * FROM integration_intents WHERE id='intent'").fetchone()
        )
        assert after == intent[:9] + ("pending",) + intent[10:]
