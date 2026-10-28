SCHEMA_VERSION = 2
ORDER_SCHEMA = """
CREATE TABLE demands(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), demand_kind TEXT NOT NULL CHECK(demand_kind IN ('inquiry','forecast','firm')), product TEXT NOT NULL, q_atoms INTEGER NOT NULL CHECK(q_atoms>0), unit TEXT NOT NULL, due_date TEXT NOT NULL, supersedes_demand_id TEXT REFERENCES demands(id), source_system TEXT NOT NULL, source_type TEXT NOT NULL, source_external_id TEXT NOT NULL, source_version INTEGER NOT NULL, source_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(source_system,source_type,source_external_id));
CREATE INDEX demands_project_page ON demands(project_id,created_at,id);
CREATE TABLE reviews(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), demand_id TEXT NOT NULL REFERENCES demands(id), dimension TEXT NOT NULL CHECK(dimension IN ('technical','material','capacity','commercial','quality')), decision TEXT NOT NULL CHECK(decision IN ('approved','rejected','unknown')), evidence TEXT NOT NULL, actor_id TEXT NOT NULL, reviewed_at TEXT NOT NULL);
CREATE INDEX reviews_latest ON reviews(project_id,demand_id,dimension,reviewed_at,id);
CREATE TABLE order_lines(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), demand_id TEXT NOT NULL REFERENCES demands(id), original_q_atoms INTEGER NOT NULL CHECK(original_q_atoms>0), current_q_atoms INTEGER NOT NULL CHECK(current_q_atoms>=0), unit TEXT NOT NULL, original_due TEXT NOT NULL, current_due TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('active','cancelled')), source_system TEXT NOT NULL, source_type TEXT NOT NULL, source_external_id TEXT NOT NULL, source_version INTEGER NOT NULL, source_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(source_system,source_type,source_external_id));
CREATE INDEX orders_project_page ON order_lines(project_id,created_at,id);
CREATE TABLE commitment_changes(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), order_line_id TEXT NOT NULL REFERENCES order_lines(id), old_q_atoms INTEGER NOT NULL, new_q_atoms INTEGER NOT NULL, unit TEXT NOT NULL, old_due TEXT NOT NULL, new_due TEXT NOT NULL, cancel INTEGER NOT NULL, reason TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','applied')), source_version INTEGER NOT NULL, source_json TEXT NOT NULL, created_at TEXT NOT NULL, resolved_at TEXT);
CREATE UNIQUE INDEX one_pending_order_change ON commitment_changes(order_line_id) WHERE state='pending';
CREATE INDEX changes_project_page ON commitment_changes(project_id,created_at,id);
CREATE TABLE change_impacts(change_id TEXT NOT NULL REFERENCES commitment_changes(id), project_id TEXT NOT NULL REFERENCES projects(id), object_type TEXT NOT NULL, object_id TEXT NOT NULL, q_atoms INTEGER NOT NULL, unit TEXT NOT NULL, decision TEXT, evidence TEXT, PRIMARY KEY(change_id,object_type,object_id));
CREATE TABLE allocations(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), order_line_id TEXT NOT NULL REFERENCES order_lines(id), work_order_id TEXT NOT NULL, q_atoms INTEGER NOT NULL CHECK(q_atoms>0), unit TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX allocations_work_order ON allocations(project_id,work_order_id);
"""
SCHEMA = (
    """
CREATE TABLE schema_version(version INTEGER NOT NULL);
CREATE TABLE dataset_metadata(id TEXT NOT NULL, mode TEXT NOT NULL, label TEXT NOT NULL);
CREATE TABLE projects(id TEXT PRIMARY KEY, version INTEGER NOT NULL, name TEXT NOT NULL, line_id TEXT NOT NULL, product TEXT NOT NULL, customer_id TEXT NOT NULL, mode TEXT NOT NULL, unit_code TEXT NOT NULL, unit_scale INTEGER NOT NULL, q_atoms INTEGER NOT NULL, contract_json TEXT NOT NULL, legacy_project_id TEXT);
CREATE TABLE project_grants(project_id TEXT NOT NULL REFERENCES projects(id), user_id TEXT NOT NULL, roles_json TEXT NOT NULL, qualifications_json TEXT NOT NULL, active INTEGER NOT NULL, evidence TEXT NOT NULL, PRIMARY KEY(project_id,user_id));
CREATE TABLE operations(dataset TEXT NOT NULL, actor_id TEXT NOT NULL, operation_id TEXT NOT NULL, payload_hash TEXT NOT NULL, result_json TEXT NOT NULL, PRIMARY KEY(dataset,actor_id,operation_id));
CREATE TABLE audit_events(id INTEGER PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), actor_id TEXT NOT NULL, action TEXT NOT NULL, object_id TEXT NOT NULL, occurred_at TEXT NOT NULL, recorded_at TEXT NOT NULL, typed_payload TEXT NOT NULL);
"""
    + ORDER_SCHEMA
)
