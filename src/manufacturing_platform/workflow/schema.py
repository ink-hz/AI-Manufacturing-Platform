SCHEMA_VERSION = 6
SUPPLY_SCHEMA = """
CREATE TABLE IF NOT EXISTS material_lots(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),material_id TEXT NOT NULL,lot_id TEXT NOT NULL,owner_id TEXT NOT NULL,unit TEXT NOT NULL,scale INTEGER NOT NULL,expiry TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('active','frozen')),source_system TEXT NOT NULL,source_type TEXT NOT NULL,source_external_id TEXT NOT NULL,source_version INTEGER NOT NULL,source_json TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(project_id,lot_id),UNIQUE(source_system,source_type,source_external_id));
CREATE INDEX IF NOT EXISTS material_lots_page ON material_lots(project_id,created_at,id);
CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),state TEXT NOT NULL CHECK(state IN ('confirmed','rejected')),reason TEXT NOT NULL,source_json TEXT NOT NULL,source_system TEXT NOT NULL,source_type TEXT NOT NULL,source_external_id TEXT NOT NULL,source_version INTEGER NOT NULL,cutoff TEXT,inputs_json TEXT NOT NULL,created_at TEXT NOT NULL,accepted_seq INTEGER NOT NULL,UNIQUE(source_system,source_type,source_external_id,source_version));
CREATE INDEX IF NOT EXISTS plans_page ON plans(project_id,created_at,id);
CREATE UNIQUE INDEX IF NOT EXISTS plans_acceptance_order ON plans(project_id,accepted_seq);
CREATE TABLE IF NOT EXISTS requirements(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),plan_id TEXT NOT NULL REFERENCES plans(id),work_order_id TEXT NOT NULL REFERENCES work_orders(id),execution_scope TEXT NOT NULL CHECK(execution_scope IN ('trial','bulk','common')),material_id TEXT NOT NULL,owner_id TEXT NOT NULL,q_atoms INTEGER NOT NULL CHECK(q_atoms>0),unit TEXT NOT NULL,scale INTEGER NOT NULL,lineage_id TEXT NOT NULL,supersedes_requirement_id TEXT REFERENCES requirements(id),created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS requirements_page ON requirements(project_id,plan_id,created_at,id);
CREATE INDEX IF NOT EXISTS requirements_work_order ON requirements(project_id,work_order_id,execution_scope,plan_id);
CREATE INDEX IF NOT EXISTS requirements_lineage ON requirements(project_id,lineage_id,created_at,id);
CREATE TABLE IF NOT EXISTS supply_commitments(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),requirement_id TEXT NOT NULL REFERENCES requirements(id),type TEXT NOT NULL CHECK(type IN ('purchase','customer')),owner_id TEXT NOT NULL,original_q_atoms INTEGER NOT NULL,current_q_atoms INTEGER NOT NULL,unit TEXT NOT NULL,original_due TEXT NOT NULL,current_due TEXT NOT NULL,source_json TEXT NOT NULL,source_version INTEGER NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS commitments_page ON supply_commitments(project_id,created_at,id);
CREATE INDEX IF NOT EXISTS commitments_requirement ON supply_commitments(project_id,requirement_id);
CREATE TABLE IF NOT EXISTS supply_promise_revisions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),commitment_id TEXT NOT NULL REFERENCES supply_commitments(id),q_atoms INTEGER NOT NULL,current_due TEXT NOT NULL,source_json TEXT NOT NULL,source_system TEXT NOT NULL,source_type TEXT NOT NULL,source_external_id TEXT NOT NULL,source_version INTEGER NOT NULL,created_at TEXT NOT NULL,UNIQUE(source_system,source_type,source_external_id,source_version));
CREATE INDEX IF NOT EXISTS promise_revisions ON supply_promise_revisions(project_id,commitment_id,created_at,id);
CREATE TABLE IF NOT EXISTS supply_receipts(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),commitment_id TEXT NOT NULL REFERENCES supply_commitments(id),material_lot_id TEXT NOT NULL REFERENCES material_lots(id),q_atoms INTEGER NOT NULL CHECK(q_atoms>0),unit TEXT NOT NULL,source_json TEXT NOT NULL,source_system TEXT NOT NULL,source_type TEXT NOT NULL,source_external_id TEXT NOT NULL,source_version INTEGER NOT NULL,created_at TEXT NOT NULL,UNIQUE(source_system,source_type,source_external_id));
CREATE INDEX IF NOT EXISTS receipts_commitment ON supply_receipts(project_id,commitment_id,created_at,id);
CREATE TABLE IF NOT EXISTS iqc_results(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),receipt_id TEXT NOT NULL REFERENCES supply_receipts(id),accepted_atoms INTEGER NOT NULL CHECK(accepted_atoms>=0),rejected_atoms INTEGER NOT NULL CHECK(rejected_atoms>=0),evidence TEXT NOT NULL,actor_id TEXT NOT NULL,created_at TEXT NOT NULL,CHECK(accepted_atoms+rejected_atoms>0));
CREATE INDEX IF NOT EXISTS iqc_receipt ON iqc_results(project_id,receipt_id,created_at,id);
CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),requirement_id TEXT NOT NULL REFERENCES requirements(id),work_order_id TEXT NOT NULL REFERENCES work_orders(id),material_lot_id TEXT NOT NULL REFERENCES material_lots(id),requested_atoms INTEGER NOT NULL CHECK(requested_atoms>0),confirmed_atoms INTEGER NOT NULL DEFAULT 0 CHECK(confirmed_atoms>=0 AND confirmed_atoms<=requested_atoms),unit TEXT NOT NULL,source_version INTEGER NOT NULL,authority_receipt_id TEXT,created_at TEXT NOT NULL,UNIQUE(authority_receipt_id));
CREATE INDEX IF NOT EXISTS reservations_requirement ON reservations(project_id,requirement_id,work_order_id);
"""
ENGINEERING_SCHEMA = """
CREATE TABLE engineering_revisions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),package_id TEXT NOT NULL,revision TEXT NOT NULL,customer_revision TEXT NOT NULL,internal_revision TEXT NOT NULL,firmware_version TEXT NOT NULL,test_spec_json TEXT NOT NULL,content_hash TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(project_id,package_id,revision));
CREATE INDEX revisions_project_page ON engineering_revisions(project_id,created_at,id);
CREATE TABLE revision_items(revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),project_id TEXT NOT NULL REFERENCES projects(id),position INTEGER NOT NULL,item_id TEXT NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(revision_id,position),UNIQUE(revision_id,item_id));
CREATE TABLE revision_routes(revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),project_id TEXT NOT NULL REFERENCES projects(id),position INTEGER NOT NULL,payload_json TEXT NOT NULL,PRIMARY KEY(revision_id,position));
CREATE TABLE handoffs(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),to_system TEXT NOT NULL,received_revision TEXT NOT NULL,decision TEXT NOT NULL,status TEXT NOT NULL,evidence TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX handoffs_latest ON handoffs(project_id,revision_id,to_system,created_at,id);
CREATE TABLE customer_approvals(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),customer_id TEXT NOT NULL,external_signatory TEXT NOT NULL,method TEXT NOT NULL CHECK(method IN ('manual','file','mock','api')),decision TEXT NOT NULL,evidence TEXT NOT NULL,actor_id TEXT NOT NULL,created_at TEXT NOT NULL,accepted_seq INTEGER NOT NULL);
CREATE INDEX approvals_latest ON customer_approvals(project_id,revision_id,created_at,id);
CREATE UNIQUE INDEX approvals_acceptance_order ON customer_approvals(project_id,accepted_seq);
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

EXCHANGE_SCHEMA = """
CREATE TABLE exchanges(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),reservation_id TEXT REFERENCES reservations(id),action TEXT NOT NULL,policy_action TEXT NOT NULL,system TEXT NOT NULL,business_key TEXT NOT NULL UNIQUE,mode TEXT NOT NULL,request_json TEXT NOT NULL,request_hash TEXT NOT NULL,phase TEXT NOT NULL,attempted INTEGER NOT NULL DEFAULT 0,reason TEXT NOT NULL DEFAULT '',receipt_json TEXT,source_sequence INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
CREATE INDEX exchanges_project ON exchanges(project_id,seq);
CREATE TABLE exchange_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,exchange_id TEXT NOT NULL REFERENCES exchanges(id),project_id TEXT NOT NULL REFERENCES projects(id),phase TEXT NOT NULL,reason TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE exchange_receipts(seq INTEGER PRIMARY KEY AUTOINCREMENT,exchange_id TEXT NOT NULL REFERENCES exchanges(id),project_id TEXT NOT NULL REFERENCES projects(id),receipt_id TEXT NOT NULL,payload_json TEXT NOT NULL,valid INTEGER NOT NULL,reason TEXT NOT NULL,UNIQUE(exchange_id,receipt_id,payload_json));
CREATE TABLE source_confirmations(seq INTEGER PRIMARY KEY AUTOINCREMENT,project_id TEXT NOT NULL REFERENCES projects(id),system TEXT NOT NULL,object_type TEXT NOT NULL,external_id TEXT NOT NULL,version INTEGER NOT NULL,object_id TEXT NOT NULL,payload_hash TEXT NOT NULL,source_json TEXT NOT NULL,mode TEXT NOT NULL,fact_id TEXT NOT NULL,external_actor TEXT NOT NULL,signature TEXT NOT NULL,recorded_by TEXT NOT NULL,UNIQUE(system,object_type,external_id,version,mode));
CREATE TABLE exchange_discrepancies(seq INTEGER PRIMARY KEY AUTOINCREMENT,exchange_id TEXT NOT NULL REFERENCES exchanges(id),project_id TEXT NOT NULL REFERENCES projects(id),owner_id TEXT NOT NULL,owner_name TEXT NOT NULL,reason TEXT NOT NULL,evidence TEXT NOT NULL,resolves_seq INTEGER REFERENCES exchange_discrepancies(seq));
CREATE TABLE source_corrections(seq INTEGER PRIMARY KEY AUTOINCREMENT,project_id TEXT NOT NULL REFERENCES projects(id),receipt_id TEXT NOT NULL REFERENCES supply_receipts(id),iqc_id TEXT REFERENCES iqc_results(id),received_delta INTEGER NOT NULL DEFAULT 0,accepted_delta INTEGER NOT NULL DEFAULT 0,rejected_delta INTEGER NOT NULL DEFAULT 0,exchange_id TEXT NOT NULL REFERENCES exchanges(id),evidence TEXT NOT NULL);
CREATE VIEW effective_supply_receipts AS SELECT r.id,r.project_id,r.commitment_id,r.material_lot_id,r.q_atoms+COALESCE((SELECT SUM(c.received_delta) FROM source_corrections c WHERE c.receipt_id=r.id),0) q_atoms,r.unit,r.source_json,r.source_system,r.source_type,r.source_external_id,r.source_version,r.created_at FROM supply_receipts r;
CREATE VIEW effective_iqc_results AS SELECT i.rowid accepted_seq,i.id,i.project_id,i.receipt_id,i.accepted_atoms+COALESCE((SELECT SUM(c.accepted_delta) FROM source_corrections c WHERE c.iqc_id=i.id),0) accepted_atoms,i.rejected_atoms+COALESCE((SELECT SUM(c.rejected_delta) FROM source_corrections c WHERE c.iqc_id=i.id),0) rejected_atoms,i.evidence,i.actor_id,i.created_at FROM iqc_results i;
ALTER TABLE reservations ADD COLUMN exchange_id TEXT REFERENCES exchanges(id);
ALTER TABLE reservations ADD COLUMN accepted_sequence INTEGER NOT NULL DEFAULT 0;
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
    + SUPPLY_SCHEMA
    + EXCHANGE_SCHEMA
)
