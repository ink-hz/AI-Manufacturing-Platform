SCHEMA_VERSION = 3
ENGINEERING_SCHEMA = """
CREATE TABLE engineering_revisions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),package_id TEXT NOT NULL,revision TEXT NOT NULL,customer_revision TEXT NOT NULL,internal_revision TEXT NOT NULL,firmware_version TEXT NOT NULL,test_spec_json TEXT NOT NULL,content_hash TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(project_id,package_id,revision));
CREATE INDEX revisions_project_page ON engineering_revisions(project_id,created_at,id);
CREATE TABLE revision_items(revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),project_id TEXT NOT NULL REFERENCES projects(id),position INTEGER NOT NULL,item_id TEXT NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(revision_id,position),UNIQUE(revision_id,item_id));
CREATE TABLE revision_routes(revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),project_id TEXT NOT NULL REFERENCES projects(id),position INTEGER NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(revision_id,position));
CREATE TABLE handoffs(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),to_system TEXT NOT NULL,received_revision TEXT NOT NULL,decision TEXT NOT NULL,status TEXT NOT NULL,evidence TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX handoffs_latest ON handoffs(project_id,revision_id,to_system,created_at,id);
CREATE TABLE customer_approvals(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),customer_id TEXT NOT NULL,external_signatory TEXT NOT NULL,method TEXT NOT NULL CHECK(method='manual'),decision TEXT NOT NULL,evidence TEXT NOT NULL,actor_id TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX approvals_latest ON customer_approvals(project_id,revision_id,created_at,id);
CREATE TABLE work_orders(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),order_line_id TEXT NOT NULL REFERENCES order_lines(id),revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),q_atoms INTEGER NOT NULL CHECK(q_atoms>0),unit TEXT NOT NULL,purpose TEXT NOT NULL,trial_q_atoms INTEGER NOT NULL CHECK(trial_q_atoms>0 AND trial_q_atoms<=q_atoms),source_system TEXT NOT NULL,source_type TEXT NOT NULL,source_external_id TEXT NOT NULL,source_version INTEGER NOT NULL,source_json TEXT NOT NULL,planned_start TEXT NOT NULL,planned_end TEXT NOT NULL,UNIQUE(source_system,source_type,source_external_id));
CREATE INDEX work_orders_project_page ON work_orders(project_id,planned_start,id);
CREATE TABLE readiness_checks(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),work_order_id TEXT NOT NULL REFERENCES work_orders(id),kind TEXT NOT NULL CHECK(kind IN ('equipment','people')),reference TEXT NOT NULL,evidence TEXT NOT NULL,valid_until TEXT NOT NULL,decision TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX readiness_latest ON readiness_checks(project_id,work_order_id,kind,created_at,id);
"""
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
    + ENGINEERING_SCHEMA
)
