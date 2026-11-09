"""Additive schema24: expedite cases with append-only cross-role progress."""

EXPEDITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS material_expedites(
 seq INTEGER PRIMARY KEY AUTOINCREMENT,
 id TEXT NOT NULL UNIQUE,
 project_id TEXT NOT NULL REFERENCES projects(id),
 requirement_id TEXT NOT NULL REFERENCES requirements(id),
 work_order_id TEXT NOT NULL REFERENCES work_orders(id),
 opened_by TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('open','closed')),
 payload_json TEXT NOT NULL,
 closure_json TEXT
);
CREATE INDEX IF NOT EXISTS material_expedites_page ON material_expedites(project_id,seq);
CREATE INDEX IF NOT EXISTS material_expedites_state ON material_expedites(project_id,state,seq);
CREATE UNIQUE INDEX IF NOT EXISTS material_expedites_open_requirement ON material_expedites(project_id,requirement_id) WHERE state='open';
CREATE TABLE IF NOT EXISTS expedite_progress(
 seq INTEGER PRIMARY KEY AUTOINCREMENT,
 project_id TEXT NOT NULL REFERENCES projects(id),
 expedite_id TEXT NOT NULL REFERENCES material_expedites(id),
 payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS expedite_progress_scope ON expedite_progress(project_id,expedite_id,seq);
"""

# This remains part of the unpublished schema24 boundary.
ISSUE_MARK_SCHEMA = """
CREATE TABLE IF NOT EXISTS issue_marks(
 seq INTEGER PRIMARY KEY AUTOINCREMENT,
 id TEXT NOT NULL UNIQUE,
 project_id TEXT NOT NULL REFERENCES projects(id),
 requirement_id TEXT NOT NULL REFERENCES requirements(id),
 work_order_id TEXT NOT NULL REFERENCES work_orders(id),
 stage TEXT NOT NULL CHECK(stage IN ('printed','picked','receipted','posted')),
 payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS issue_marks_page ON issue_marks(project_id,seq);
CREATE INDEX IF NOT EXISTS issue_marks_requirement_page ON issue_marks(project_id,requirement_id,seq);
"""
