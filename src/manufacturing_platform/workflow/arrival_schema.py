"""Non-accounting observations with append-only attribution of receipt matches."""

ARRIVAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS arrivals(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),payload_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS arrivals_page ON arrivals(project_id,seq);
CREATE TABLE IF NOT EXISTS arrival_matches(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),arrival_id TEXT NOT NULL REFERENCES arrivals(id),receipt_id TEXT NOT NULL REFERENCES supply_receipts(id),payload_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS arrival_matches_history ON arrival_matches(project_id,arrival_id,seq);
"""
