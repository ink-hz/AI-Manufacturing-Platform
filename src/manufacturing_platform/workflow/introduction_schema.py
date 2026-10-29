"""Additive v18 engineering introduction storage; no existing facts rewritten."""

INTRODUCTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS npis(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),product_family TEXT NOT NULL,scenario TEXT NOT NULL,required_checks_json TEXT NOT NULL,generation INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS npis_page ON npis(project_id,created_at,id);
CREATE TABLE IF NOT EXISTS npi_work_orders(npi_id TEXT NOT NULL REFERENCES npis(id),project_id TEXT NOT NULL REFERENCES projects(id),work_order_id TEXT NOT NULL REFERENCES work_orders(id),PRIMARY KEY(npi_id,work_order_id));
CREATE INDEX IF NOT EXISTS npi_work_orders_gate ON npi_work_orders(project_id,work_order_id);
CREATE TABLE IF NOT EXISTS npi_records(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),npi_id TEXT NOT NULL REFERENCES npis(id),record_type TEXT NOT NULL,payload_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS npi_records_scope ON npi_records(project_id,npi_id,record_type,seq);
CREATE TABLE IF NOT EXISTS npi_issues(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),npi_id TEXT NOT NULL REFERENCES npis(id),payload_json TEXT NOT NULL,resolution_json TEXT,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS npi_issues_scope ON npi_issues(project_id,npi_id,created_at,id);
CREATE TABLE IF NOT EXISTS reusable_assets(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),issue_id TEXT NOT NULL REFERENCES npi_issues(id),content_json TEXT NOT NULL,public_content_json TEXT,supersedes_id TEXT UNIQUE REFERENCES reusable_assets(id),revision INTEGER NOT NULL,published_by TEXT NOT NULL,published_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS reusable_assets_page ON reusable_assets(project_id,seq);
CREATE INDEX IF NOT EXISTS reusable_assets_public ON reusable_assets(seq) WHERE public_content_json IS NOT NULL;
CREATE TABLE IF NOT EXISTS asset_uses(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),npi_id TEXT NOT NULL REFERENCES npis(id),asset_revision_id TEXT NOT NULL REFERENCES reusable_assets(id),revision INTEGER NOT NULL,snapshot_json TEXT NOT NULL,required INTEGER NOT NULL,created_at TEXT NOT NULL,UNIQUE(npi_id,asset_revision_id));
CREATE INDEX IF NOT EXISTS asset_uses_scope ON asset_uses(project_id,npi_id,created_at,id);
CREATE TABLE IF NOT EXISTS asset_verifications(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),asset_use_id TEXT NOT NULL REFERENCES asset_uses(id),payload_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS asset_verifications_scope ON asset_verifications(project_id,asset_use_id,seq);
"""
