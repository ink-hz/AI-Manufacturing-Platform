"""Isolated, lazy SQLite storage with dataset validation."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .orders import source_key
from .schema import (
    ENGINEERING_SCHEMA,
    ORDER_SCHEMA,
    SCHEMA,
    SCHEMA_VERSION,
    SUPPLY_SCHEMA,
)


class WorkflowStore:
    def __init__(self, database_path, authority_database_path, dataset):
        self.database_path = database_path
        self.authority_database_path = authority_database_path
        self.dataset = dataset

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
                conn.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION,))
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
                    "material_lots", "plans", "supply_promise_revisions", "supply_receipts"
                ):
                    rows = conn.execute(f"SELECT id,source_json FROM {table}").fetchall()
                    for row in rows:
                        conn.execute(
                            f"""UPDATE {table} SET source_system=?,source_type=?,
                                source_external_id=? WHERE id=?""",
                            (*source_key(json.loads(row["source_json"])), row["id"]),
                        )
                conn.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION,))
                version = conn.execute("SELECT version FROM schema_version").fetchall()
            metadata = conn.execute(
                "SELECT id,mode,label FROM dataset_metadata"
            ).fetchall()
            if (
                len(version) != 1
                or version[0][0] != SCHEMA_VERSION
                or len(metadata) != 1
                or tuple(metadata[0])
                != (self.dataset["id"], self.dataset["mode"], self.dataset["label"])
            ):
                raise ValueError("workflow dataset mismatch")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
