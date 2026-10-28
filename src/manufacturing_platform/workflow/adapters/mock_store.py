"""The authority owns its own durable state and serializes competing inventory writes."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE metadata(dataset TEXT NOT NULL);
CREATE TABLE inventory(lot_id TEXT PRIMARY KEY,project_id TEXT NOT NULL,material_id TEXT NOT NULL,owner_id TEXT NOT NULL,unit TEXT NOT NULL,scale INTEGER NOT NULL,expiry TEXT NOT NULL,state TEXT NOT NULL,received INTEGER NOT NULL DEFAULT 0,qualified INTEGER NOT NULL DEFAULT 0,reserved INTEGER NOT NULL DEFAULT 0,version INTEGER NOT NULL DEFAULT 1,CHECK(received>=qualified AND qualified>=reserved AND reserved>=0));
CREATE TABLE source_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,system TEXT NOT NULL,object_type TEXT NOT NULL,external_id TEXT NOT NULL,project_id TEXT NOT NULL,version INTEGER NOT NULL,payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL,UNIQUE(system,object_type,external_id));
CREATE TABLE authority_operations(seq INTEGER PRIMARY KEY AUTOINCREMENT,system TEXT NOT NULL,business_key TEXT NOT NULL,request_hash TEXT NOT NULL,request_json TEXT NOT NULL,receipt_json TEXT,UNIQUE(system,business_key));
CREATE TABLE authority_reservations(id TEXT PRIMARY KEY,lot_id TEXT NOT NULL REFERENCES inventory(lot_id),project_id TEXT NOT NULL,business_key TEXT NOT NULL UNIQUE,q_atoms INTEGER NOT NULL CHECK(q_atoms>0));
CREATE TABLE faults(name TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS authority_work_orders(project_id TEXT NOT NULL,work_order_id TEXT NOT NULL,revision_id TEXT NOT NULL,total_units INTEGER NOT NULL,trial_units INTEGER NOT NULL,started_units INTEGER NOT NULL DEFAULT 0,started_trial INTEGER NOT NULL DEFAULT 0,state TEXT NOT NULL DEFAULT 'running',PRIMARY KEY(project_id,work_order_id));
CREATE TABLE IF NOT EXISTS authority_start_units(project_id TEXT NOT NULL,work_order_id TEXT NOT NULL,unit_id TEXT NOT NULL UNIQUE,sn_key TEXT NOT NULL UNIQUE,mode TEXT NOT NULL,start_id TEXT NOT NULL,PRIMARY KEY(project_id,work_order_id,unit_id));
CREATE TABLE IF NOT EXISTS authority_interruptions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,work_order_id TEXT NOT NULL,stopped INTEGER NOT NULL,resumed INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS authority_stop_lineage ON authority_operations(json_extract(request_json,'$.project_id'),json_extract(request_json,'$.typed_payload.work_order_id'),seq DESC) WHERE json_extract(request_json,'$.action')='production.interrupt' AND json_extract(receipt_json,'$.phase')='accepted';
"""


class MockStore:
    def __init__(self, path, dataset):
        if not Path(path).is_absolute() or str(path) == "/:memory:":
            raise ValueError("authority requires explicit persistent path")
        self.path, self.dataset = str(path), dataset

    @contextmanager
    def transaction(self, *, write=False):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA journal_mode=WAL")
            # Initialization also requires serialization across adapter instances.
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='metadata'"
            ).fetchone():
                if conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchone():
                    raise ValueError("unrecognized authority database")
                for statement in SCHEMA.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute("INSERT INTO metadata VALUES (?)", (self.dataset,))
            if [r[0] for r in conn.execute("SELECT dataset FROM metadata")] != [
                self.dataset
            ]:
                raise ValueError("authority dataset mismatch")
            for statement in SCHEMA.split(";"):
                if statement.strip() and "IF NOT EXISTS authority_" in statement:
                    conn.execute(statement)
            if "state" not in {
                r[1] for r in conn.execute("PRAGMA table_info(authority_start_units)")
            }:
                conn.execute(
                    "ALTER TABLE authority_start_units ADD COLUMN state TEXT NOT NULL DEFAULT 'running'"
                )
                conn.execute(
                    "UPDATE authority_start_units SET state=COALESCE((SELECT state FROM authority_work_orders w WHERE w.project_id=authority_start_units.project_id AND w.work_order_id=authority_start_units.work_order_id),'running')"
                )
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
