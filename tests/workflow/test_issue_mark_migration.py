"""Issue marks extend actual schema23 and existing preview24 without rewriting facts."""
import sqlite3
from pathlib import Path

from manufacturing_platform.workflow.store import WorkflowStore

from .conftest import BASE
from .test_expedites import setup
from .test_issue_marks import mark

DATASET = {"id": "workflow-test", "mode": "test", "label": "Workflow test"}


def rows(tx):
    tables = [r[0] for r in tx.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name!='schema_version'")]
    return {t: tx.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall() for t in tables}


def test_actual_frozen_schema23_ddl_and_business_rows_upgrade_additively(tmp_path):
    path = tmp_path / "previous.db"
    with sqlite3.connect(path) as tx:
        tx.executescript((Path(__file__).parent / "fixtures/schema23.sql").read_text())
        assert tx.execute("SELECT version FROM schema_version").fetchone()[0] == 23
        assert not tx.execute("SELECT 1 FROM sqlite_master WHERE name IN ('issue_marks','material_expedites')").fetchall()
        before = rows(tx)
        assert all(before[t] for t in ("projects", "requirements", "supply_receipts", "iqc_results", "operations", "audit_events"))
    store = WorkflowStore(str(path), str(tmp_path / "authority.db"), DATASET)
    for _ in range(2):
        with store.transaction() as tx:
            assert tx.execute("SELECT version FROM schema_version").fetchone()[0] == 25
            assert tx.execute("SELECT COUNT(*) FROM issue_marks").fetchone()[0] == 0
            assert tx.execute("SELECT COUNT(*) FROM material_expedites").fetchone()[0] == 0
            for table, original in before.items():
                assert [tuple(r) for r in tx.execute(f'SELECT * FROM "{table}" ORDER BY rowid')] == original
            assert tx.execute("PRAGMA foreign_key_check").fetchall() == []


def test_existing_preview24_without_issue_table_initializes_without_rewriting(workflow):
    w = workflow
    pid, rid, _ = setup(w)
    w._client.close()
    with sqlite3.connect(w.paths.domain) as tx:
        tx.execute("DROP TABLE IF EXISTS issue_marks")
        assert tx.execute("SELECT version FROM schema_version").fetchone()[0] == 25
        before = rows(tx)
    w.reopen()
    assert w.client().get(f"{BASE}/projects/{pid}").status_code == 200
    with w.db() as tx:
        assert tx.execute("SELECT version FROM schema_version").fetchone()[0] == 25
        assert tx.execute("SELECT COUNT(*) FROM issue_marks").fetchone()[0] == 0
        for table, original in before.items():
            assert [tuple(r) for r in tx.execute(f'SELECT * FROM "{table}" ORDER BY rowid')] == original
    mark(w, pid, rid)
