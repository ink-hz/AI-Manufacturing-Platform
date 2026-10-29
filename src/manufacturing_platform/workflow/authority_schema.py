"""Append-only scope revisions and contract verification; no routing projection."""

AUTHORITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS authority_rules(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),object_category TEXT NOT NULL,scope_key TEXT NOT NULL,revision INTEGER NOT NULL,payload_json TEXT NOT NULL,UNIQUE(project_id,object_category,scope_key,revision));
CREATE INDEX IF NOT EXISTS authority_rules_page ON authority_rules(project_id,seq);
CREATE TABLE IF NOT EXISTS authority_verifications(rule_id TEXT PRIMARY KEY REFERENCES authority_rules(id),project_id TEXT NOT NULL REFERENCES projects(id),payload_json TEXT NOT NULL);
"""
