"""Isolated, lazy SQLite storage with dataset validation."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .schema import ENGINEERING_SCHEMA, ORDER_SCHEMA, SCHEMA, SCHEMA_VERSION


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
