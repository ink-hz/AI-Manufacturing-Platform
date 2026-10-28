SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE schema_version(version INTEGER NOT NULL);
CREATE TABLE dataset_metadata(id TEXT NOT NULL, mode TEXT NOT NULL, label TEXT NOT NULL);
CREATE TABLE projects(id TEXT PRIMARY KEY, version INTEGER NOT NULL, name TEXT NOT NULL, line_id TEXT NOT NULL, product TEXT NOT NULL, customer_id TEXT NOT NULL, mode TEXT NOT NULL, unit_code TEXT NOT NULL, unit_scale INTEGER NOT NULL, q_atoms INTEGER NOT NULL, contract_json TEXT NOT NULL, legacy_project_id TEXT);
CREATE TABLE project_grants(project_id TEXT NOT NULL REFERENCES projects(id), user_id TEXT NOT NULL, roles_json TEXT NOT NULL, qualifications_json TEXT NOT NULL, active INTEGER NOT NULL, evidence TEXT NOT NULL, PRIMARY KEY(project_id,user_id));
CREATE TABLE operations(dataset TEXT NOT NULL, actor_id TEXT NOT NULL, operation_id TEXT NOT NULL, payload_hash TEXT NOT NULL, result_json TEXT NOT NULL, PRIMARY KEY(dataset,actor_id,operation_id));
CREATE TABLE audit_events(id INTEGER PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), actor_id TEXT NOT NULL, action TEXT NOT NULL, object_id TEXT NOT NULL, occurred_at TEXT NOT NULL, recorded_at TEXT NOT NULL, typed_payload TEXT NOT NULL);
"""
