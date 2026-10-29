"""Additive schema20 laboratory records; existing production facts remain intact."""

LABORATORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS test_plans(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),payload_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS test_plans_page ON test_plans(project_id,seq);
CREATE TABLE IF NOT EXISTS test_runs(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),unit_id TEXT NOT NULL REFERENCES units(id),payload_json TEXT NOT NULL,finish_json TEXT);
CREATE INDEX IF NOT EXISTS test_runs_page ON test_runs(project_id,seq);
CREATE TABLE IF NOT EXISTS calibrations(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),payload_json TEXT NOT NULL,confirmation_json TEXT);
CREATE INDEX IF NOT EXISTS calibrations_page ON calibrations(project_id,seq);
CREATE TABLE IF NOT EXISTS component_links(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),unit_id TEXT NOT NULL REFERENCES units(id),material_id TEXT NOT NULL,serial_key TEXT NOT NULL,payload_json TEXT NOT NULL,removal_json TEXT);
CREATE INDEX IF NOT EXISTS component_links_page ON component_links(project_id,seq);
CREATE UNIQUE INDEX IF NOT EXISTS component_active ON component_links(project_id,material_id,serial_key) WHERE removal_json IS NULL;
CREATE TABLE IF NOT EXISTS unit_aliases(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),unit_id TEXT NOT NULL REFERENCES units(id),customer_id TEXT NOT NULL,serial_key TEXT NOT NULL,payload_json TEXT NOT NULL,UNIQUE(customer_id,serial_key));
CREATE INDEX IF NOT EXISTS unit_aliases_unit ON unit_aliases(project_id,unit_id,seq);
"""
