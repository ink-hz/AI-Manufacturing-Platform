"""Isolated, lazy SQLite storage with dataset validation."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .execution import TestEvidenceReader

from .orders import source_key
from .clock import bind_business_clock, checked_time, utc_now
from .schema import (
    AGREEMENT_SCHEMA,
    DELIVERY_SCHEMA,
    FEEDBACK_SCHEMA,
    ECO_REVIEW_SCHEMA,
    ECO_SCHEMA,
    ENGINEERING_SCHEMA,
    EXCHANGE_SCHEMA,
    EXECUTION_REVIEW_SCHEMA,
    EXECUTION_SCHEMA,
    ORDER_SCHEMA,
    QUALITY_REVIEW_SCHEMA,
    QUALITY_SCHEMA,
    SCHEMA,
    SCHEMA_VERSION,
    SUPPLY_SCHEMA,
)


class WorkflowStore:
    def __init__(self, database_path, authority_database_path, dataset, *, business_clock=None):
        self.business_clock = business_clock or utc_now
        checked_time(self.business_clock)
        self.database_path = database_path
        self.authority_database_path = authority_database_path
        self.dataset = dataset
        self._test_evidence_reader: TestEvidenceReader | None = None

    def bind_test_evidence_reader(self, reader: "TestEvidenceReader") -> None:
        if (
            self._test_evidence_reader is not None
            and self._test_evidence_reader is not reader
        ):
            raise ValueError("workflow store evidence reader is already bound")
        self._test_evidence_reader = reader

    def _validate(self):
        paths = [Path(self.database_path), Path(self.authority_database_path)]
        if any(
            not str(p) or not p.is_absolute() or str(p) == "/:memory:" for p in paths
        ):
            raise ValueError("invalid workflow configuration")
        if paths[0].resolve() == paths[1].resolve() or (
            paths[0].exists() and paths[1].exists() and paths[0].samefile(paths[1])
        ):
            raise ValueError("invalid workflow configuration")
        if (
            set(self.dataset) != {"id", "mode", "label"}
            or not self.dataset["id"]
            or not self.dataset["label"]
            or self.dataset["mode"] not in {"production", "demo", "test"}
        ):
            raise ValueError("invalid dataset")

    @contextmanager
    def transaction(self, *, write=False):
        self._validate()
        conn = sqlite3.connect(self.database_path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
            ).fetchone()
            if not exists:
                # Do not adopt a foreign or corrupt database.
                if conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchone():
                    raise ValueError("unrecognized workflow database")
                for statement in SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                from .integrations.schema import migrate_integration_schema

                migrate_integration_schema(conn)
                conn.execute("INSERT INTO schema_version VALUES (?)", (SCHEMA_VERSION,))
                conn.execute(
                    "INSERT INTO dataset_metadata VALUES (?,?,?)",
                    (self.dataset["id"], self.dataset["mode"], self.dataset["label"]),
                )
            version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 1:
                for statement in ORDER_SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("UPDATE schema_version SET version=2")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 2:
                for statement in ENGINEERING_SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("UPDATE schema_version SET version=3")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 3:
                for statement in SUPPLY_SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("UPDATE schema_version SET version=5")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 4:
                conn.execute("ALTER TABLE plans ADD COLUMN accepted_seq INTEGER")
                # Every v4 command wrote its plan and audit event in one transaction.
                # Audit IDs retain insertion order even when business clocks coincide.
                plans = conn.execute(
                    """SELECT p.id,p.project_id,a.id audit_id FROM plans p
                       LEFT JOIN audit_events a ON a.object_id=p.id
                         AND a.project_id=p.project_id AND a.action='plan.receive'
                       ORDER BY p.project_id,a.id"""
                ).fetchall()
                if any(row["audit_id"] is None for row in plans):
                    raise ValueError("unmigratable supply plan without audit event")
                prior_project = None
                seq = 0
                for row in plans:
                    if row["project_id"] != prior_project:
                        prior_project, seq = row["project_id"], 0
                    seq += 1
                    conn.execute(
                        "UPDATE plans SET accepted_seq=? WHERE id=?", (seq, row["id"])
                    )
                conn.execute(
                    "CREATE UNIQUE INDEX plans_acceptance_order ON plans(project_id,accepted_seq)"
                )
                for table in (
                    "material_lots",
                    "plans",
                    "supply_promise_revisions",
                    "supply_receipts",
                ):
                    rows = conn.execute(
                        f"SELECT id,source_json FROM {table}"
                    ).fetchall()
                    for row in rows:
                        conn.execute(
                            f"""UPDATE {table} SET source_system=?,source_type=?,
                                source_external_id=? WHERE id=?""",
                            (*source_key(json.loads(row["source_json"])), row["id"]),
                        )
                conn.execute("UPDATE schema_version SET version=5")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 5:
                for statement in EXCHANGE_SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute(
                    "ALTER TABLE customer_approvals RENAME TO customer_approvals_v5"
                )
                conn.execute("DROP INDEX approvals_latest")
                conn.execute(
                    """CREATE TABLE customer_approvals(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),customer_id TEXT NOT NULL,external_signatory TEXT NOT NULL,method TEXT NOT NULL CHECK(method IN ('manual','file','mock','api')),decision TEXT NOT NULL,evidence TEXT NOT NULL,actor_id TEXT NOT NULL,created_at TEXT NOT NULL,accepted_seq INTEGER NOT NULL)"""
                )
                conn.execute(
                    "INSERT INTO customer_approvals SELECT id,project_id,revision_id,customer_id,external_signatory,method,decision,evidence,actor_id,created_at,rowid FROM customer_approvals_v5 ORDER BY rowid"
                )
                conn.execute("DROP TABLE customer_approvals_v5")
                conn.execute(
                    "CREATE INDEX approvals_latest ON customer_approvals(project_id,revision_id,created_at,id)"
                )
                conn.execute(
                    "CREATE UNIQUE INDEX approvals_acceptance_order ON customer_approvals(project_id,accepted_seq)"
                )
                conn.execute("UPDATE schema_version SET version=6")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 6:
                for statement in EXECUTION_SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("UPDATE schema_version SET version=7")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 7:
                for statement in EXECUTION_REVIEW_SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                columns = {
                    r[1] for r in conn.execute("PRAGMA table_info(interruptions)")
                }
                for name, declaration in (
                    ("trial_resumed_at", "TEXT"),
                    ("superseded_by", "TEXT REFERENCES interruptions(id)"),
                ):
                    if name not in columns:
                        conn.execute(
                            f"ALTER TABLE interruptions ADD COLUMN {name} {declaration}"
                        )
                # Reconstruct ordered projections only from immutable accepted receipts.
                conn.execute("""INSERT OR IGNORE INTO production_controls
                    SELECT e.id,e.project_id,json_extract(e.request_json,'$.typed_payload.work_order_id'),e.source_sequence,
                    CASE e.action WHEN 'production.interrupt' THEN 'stop' ELSE 'resume' END,'all',
                    CASE WHEN e.action='production.resume' AND EXISTS(SELECT 1 FROM units u WHERE u.project_id=e.project_id AND u.work_order_id=json_extract(e.request_json,'$.typed_payload.work_order_id') AND u.state='start_pending' AND u.accepted_start_id IS NOT NULL) THEN 1 ELSE 0 END
                    FROM exchanges e WHERE e.action IN ('production.interrupt','production.resume')
                    AND e.phase='accepted' AND json_extract(e.receipt_json,'$.phase')='accepted' AND e.source_sequence>0""")
                conn.execute("UPDATE schema_version SET version=8")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            metadata = conn.execute(
                "SELECT id,mode,label FROM dataset_metadata"
            ).fetchall()
            if len(version) == 1 and version[0][0] == 8:
                for statement in ECO_SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("UPDATE schema_version SET version=9")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 9:
                for statement in ECO_REVIEW_SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("UPDATE schema_version SET version=10")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 10:
                for statement in QUALITY_SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("UPDATE schema_version SET version=11")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 11:
                for statement in QUALITY_REVIEW_SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                from .quality import rebuild_test_bases

                rebuild_test_bases(conn)
                conn.execute("UPDATE schema_version SET version=12")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 12:
                for statement in DELIVERY_SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("UPDATE schema_version SET version=13")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 13:
                for statement in FEEDBACK_SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("UPDATE schema_version SET version=14")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 14:
                # Reconstruct extant supported insertion order, not source chronology.
                # Original business facts, operations and audit payloads are untouched.
                for table in ("reviews", "handoffs", "readiness_checks"):
                    columns = {
                        r[1] for r in conn.execute(f"PRAGMA table_info({table})")
                    }
                    if "accepted_seq" not in columns:
                        conn.execute(
                            f"ALTER TABLE {table} ADD COLUMN accepted_seq INTEGER"
                        )
                        conn.execute(f"UPDATE {table} SET accepted_seq=rowid")
                    conn.execute(
                        f"CREATE UNIQUE INDEX IF NOT EXISTS {table}_acceptance_order ON {table}(project_id,accepted_seq)"
                    )
                conn.execute("UPDATE schema_version SET version=15")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 15:
                from .source_identity_migration import migrate_source_identities

                migrate_source_identities(conn)
                conn.execute("UPDATE schema_version SET version=16")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 16:
                for statement in AGREEMENT_SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("UPDATE schema_version SET version=17")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 17:
                from .introduction_schema import INTRODUCTION_SCHEMA

                for statement in INTRODUCTION_SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("UPDATE schema_version SET version=18")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 18:
                from .introduction_schema import ISSUE_RESOLUTION_SCHEMA

                for statement in ISSUE_RESOLUTION_SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("UPDATE schema_version SET version=19")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 19:
                from .laboratory_schema import LABORATORY_SCHEMA

                for statement in LABORATORY_SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("UPDATE schema_version SET version=20")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 20:
                from .authority_schema import AUTHORITY_SCHEMA
                from .arrival_schema import ARRIVAL_SCHEMA

                for statement in (AUTHORITY_SCHEMA + ARRIVAL_SCHEMA).split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("UPDATE schema_version SET version=21")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 21:
                from .material_handoff_schema import HANDOFF_SCHEMA

                for statement in HANDOFF_SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("UPDATE schema_version SET version=22")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 22:
                from .integrations.schema import migrate_integration_schema

                migrate_integration_schema(conn)
                conn.execute("UPDATE schema_version SET version=23")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 23:
                from .expedite_schema import EXPEDITE_SCHEMA, ISSUE_MARK_SCHEMA

                for statement in (EXPEDITE_SCHEMA + ISSUE_MARK_SCHEMA).split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("UPDATE schema_version SET version=24")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if len(version) == 1 and version[0][0] == 24:
                from .material_task_schema import MATERIAL_TASK_SCHEMA
                for statement in MATERIAL_TASK_SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("UPDATE schema_version SET version=25")
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            if (
                len(version) != 1
                or version[0][0] != SCHEMA_VERSION
                or len(metadata) != 1
                or tuple(metadata[0])
                != (self.dataset["id"], self.dataset["mode"], self.dataset["label"])
            ):
                raise ValueError("workflow dataset mismatch")
            # Existing preview24 stores predate the additive issue fact table.
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='issue_marks'"
            ).fetchone():
                from .expedite_schema import ISSUE_MARK_SCHEMA

                for statement in ISSUE_MARK_SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
            # Task3 adds an undeployed, additive reservation release ledger to v23.
            # Existing v23 datasets need the same initialization as fresh stores.
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='view' AND name='effective_reservations'"
            ).fetchone():
                from .integrations.schema import initialize_reservation_releases

                initialize_reservation_releases(conn)
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='integration_return_units'").fetchone():
                from .integrations.schema import initialize_claims
                initialize_claims(conn)
            from . import quality
            from .execution import bind_test_reader

            with (
                bind_test_reader(conn, self._test_evidence_reader or quality),
                bind_business_clock(conn, self.business_clock),
            ):
                yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
