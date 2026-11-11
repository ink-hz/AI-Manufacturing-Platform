from .introduction_schema import INTRODUCTION_SCHEMA, ISSUE_RESOLUTION_SCHEMA
from .laboratory_schema import LABORATORY_SCHEMA
from .authority_schema import AUTHORITY_SCHEMA
from .arrival_schema import ARRIVAL_SCHEMA
from .material_handoff_schema import HANDOFF_SCHEMA
from .expedite_schema import EXPEDITE_SCHEMA, ISSUE_MARK_SCHEMA

SCHEMA_VERSION = 27
EXECUTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS units(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),work_order_id TEXT NOT NULL REFERENCES work_orders(id),revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),sn TEXT NOT NULL,sn_key TEXT NOT NULL UNIQUE,state TEXT NOT NULL CHECK(state IN ('registered','start_pending','running','stopped')),mode TEXT,accepted_start_id TEXT,registered_seq INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS units_work_order ON units(project_id,work_order_id,registered_seq);
CREATE TABLE IF NOT EXISTS start_requests(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),work_order_id TEXT NOT NULL REFERENCES work_orders(id),mode TEXT NOT NULL CHECK(mode IN ('trial','bulk')),q_units INTEGER NOT NULL CHECK(q_units>0),exchange_id TEXT NOT NULL UNIQUE REFERENCES exchanges(id),accepted_receipt_id TEXT UNIQUE,accepted_seq INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS start_requests_work_order ON start_requests(project_id,work_order_id);
CREATE TABLE IF NOT EXISTS start_units(start_id TEXT NOT NULL REFERENCES start_requests(id),unit_id TEXT NOT NULL UNIQUE REFERENCES units(id),project_id TEXT NOT NULL REFERENCES projects(id),PRIMARY KEY(start_id,unit_id));
CREATE TABLE IF NOT EXISTS execution_events(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),work_order_id TEXT NOT NULL REFERENCES work_orders(id),unit_id TEXT REFERENCES units(id),claimed_sn TEXT NOT NULL,source_system TEXT NOT NULL,source_type TEXT NOT NULL,source_external_id TEXT NOT NULL,source_version INTEGER NOT NULL,source_json TEXT NOT NULL,station TEXT NOT NULL,route_version TEXT NOT NULL,program_version TEXT NOT NULL,firmware_version TEXT NOT NULL,result TEXT NOT NULL,status TEXT NOT NULL CHECK(status IN ('accepted','rejected')),reason TEXT NOT NULL,route_kind TEXT NOT NULL CHECK(route_kind IN ('initial','rework')),rework_order_id TEXT,supersedes_event_id TEXT REFERENCES execution_events(id),occurred_at TEXT NOT NULL,recorded_at TEXT NOT NULL,accepted_seq INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS execution_events_source ON execution_events(source_system,source_type,source_external_id);
CREATE INDEX IF NOT EXISTS execution_events_unit ON execution_events(project_id,unit_id,accepted_seq);
CREATE TABLE IF NOT EXISTS material_consumption(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),execution_event_id TEXT NOT NULL REFERENCES execution_events(id),unit_id TEXT NOT NULL REFERENCES units(id),lot_id TEXT NOT NULL REFERENCES material_lots(id),material_id TEXT NOT NULL,owner_id TEXT NOT NULL,q_atoms INTEGER NOT NULL CHECK(q_atoms>0),unit TEXT NOT NULL,accepted_seq INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS material_consumption_unit ON material_consumption(project_id,unit_id,accepted_seq);
CREATE TABLE IF NOT EXISTS interruptions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),work_order_id TEXT NOT NULL REFERENCES work_orders(id),reason TEXT NOT NULL,exception_id TEXT,requested_at TEXT NOT NULL,authority_stopped_at TEXT,resolved_at TEXT,interrupted_plan_id TEXT REFERENCES plans(id),plan_id TEXT REFERENCES plans(id),stop_exchange_id TEXT NOT NULL UNIQUE REFERENCES exchanges(id),resume_exchange_id TEXT UNIQUE REFERENCES exchanges(id),trial_resumed_at TEXT,superseded_by TEXT REFERENCES interruptions(id));
CREATE INDEX IF NOT EXISTS interruptions_work_order ON interruptions(project_id,work_order_id,requested_at);
CREATE TABLE IF NOT EXISTS execution_exceptions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),work_order_id TEXT NOT NULL REFERENCES work_orders(id),interruption_id TEXT NOT NULL UNIQUE REFERENCES interruptions(id),kind TEXT NOT NULL CHECK(kind IN ('S3','S4','other')),reason TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS interruption_actions(seq INTEGER PRIMARY KEY AUTOINCREMENT,project_id TEXT NOT NULL REFERENCES projects(id),interruption_id TEXT NOT NULL REFERENCES interruptions(id),exchange_id TEXT NOT NULL UNIQUE REFERENCES exchanges(id),kind TEXT NOT NULL CHECK(kind IN ('stop','resume')));
CREATE INDEX IF NOT EXISTS interruption_actions_scope ON interruption_actions(project_id,interruption_id,seq);
CREATE TABLE IF NOT EXISTS first_articles(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),work_order_id TEXT NOT NULL REFERENCES work_orders(id),revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),route_fingerprint TEXT NOT NULL,test_version TEXT NOT NULL,program_version TEXT NOT NULL,firmware_version TEXT NOT NULL,equipment_check_id TEXT NOT NULL REFERENCES readiness_checks(id),inspection_id TEXT NOT NULL,test_ids_json TEXT NOT NULL,unit_ids_json TEXT NOT NULL,accepted_seq INTEGER NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS first_articles_work_order ON first_articles(project_id,work_order_id,accepted_seq);
"""
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
CREATE TABLE handoffs(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),to_system TEXT NOT NULL,received_revision TEXT NOT NULL,decision TEXT NOT NULL,status TEXT NOT NULL,evidence TEXT NOT NULL,created_at TEXT NOT NULL,accepted_seq INTEGER NOT NULL);
CREATE UNIQUE INDEX handoffs_acceptance_order ON handoffs(project_id,accepted_seq);
CREATE INDEX handoffs_latest ON handoffs(project_id,revision_id,to_system,created_at,id);
CREATE TABLE customer_approvals(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),customer_id TEXT NOT NULL,external_signatory TEXT NOT NULL,method TEXT NOT NULL CHECK(method IN ('manual','file','mock','api')),decision TEXT NOT NULL,evidence TEXT NOT NULL,actor_id TEXT NOT NULL,created_at TEXT NOT NULL,accepted_seq INTEGER NOT NULL);
CREATE INDEX approvals_latest ON customer_approvals(project_id,revision_id,created_at,id);
CREATE UNIQUE INDEX approvals_acceptance_order ON customer_approvals(project_id,accepted_seq);
CREATE TABLE work_orders(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),order_line_id TEXT NOT NULL REFERENCES order_lines(id),revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),q_atoms INTEGER NOT NULL CHECK(q_atoms>0),unit TEXT NOT NULL,purpose TEXT NOT NULL,trial_q_atoms INTEGER NOT NULL CHECK(trial_q_atoms>0 AND trial_q_atoms<=q_atoms),source_system TEXT NOT NULL,source_type TEXT NOT NULL,source_external_id TEXT NOT NULL,source_version INTEGER NOT NULL,source_json TEXT NOT NULL,planned_start TEXT NOT NULL,planned_end TEXT NOT NULL,UNIQUE(source_system,source_type,source_external_id));
CREATE INDEX work_orders_project_page ON work_orders(project_id,planned_start,id);
CREATE TABLE readiness_checks(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),work_order_id TEXT NOT NULL REFERENCES work_orders(id),kind TEXT NOT NULL CHECK(kind IN ('equipment','people')),reference TEXT NOT NULL,evidence TEXT NOT NULL,valid_until TEXT NOT NULL,decision TEXT NOT NULL,created_at TEXT NOT NULL,accepted_seq INTEGER NOT NULL);
CREATE UNIQUE INDEX readiness_checks_acceptance_order ON readiness_checks(project_id,accepted_seq);
CREATE INDEX readiness_latest ON readiness_checks(project_id,work_order_id,kind,created_at,id);
"""
ORDER_SCHEMA = """
CREATE TABLE demands(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), demand_kind TEXT NOT NULL CHECK(demand_kind IN ('inquiry','forecast','firm')), product TEXT NOT NULL, q_atoms INTEGER NOT NULL CHECK(q_atoms>0), unit TEXT NOT NULL, due_date TEXT NOT NULL, supersedes_demand_id TEXT REFERENCES demands(id), source_system TEXT NOT NULL, source_type TEXT NOT NULL, source_external_id TEXT NOT NULL, source_version INTEGER NOT NULL, source_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(source_system,source_type,source_external_id));
CREATE INDEX demands_project_page ON demands(project_id,created_at,id);
CREATE TABLE reviews(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), demand_id TEXT NOT NULL REFERENCES demands(id), dimension TEXT NOT NULL CHECK(dimension IN ('technical','material','capacity','commercial','quality')), decision TEXT NOT NULL CHECK(decision IN ('approved','rejected','unknown')), evidence TEXT NOT NULL, actor_id TEXT NOT NULL, reviewed_at TEXT NOT NULL,accepted_seq INTEGER NOT NULL);
CREATE UNIQUE INDEX reviews_acceptance_order ON reviews(project_id,accepted_seq);
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
    + EXECUTION_SCHEMA
)

EXECUTION_REVIEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS execution_admissions(event_id TEXT PRIMARY KEY REFERENCES execution_events(id),project_id TEXT NOT NULL REFERENCES projects(id),admitted INTEGER NOT NULL,record_json TEXT NOT NULL,claimed_correction_id TEXT);
CREATE TABLE IF NOT EXISTS production_controls(exchange_id TEXT PRIMARY KEY REFERENCES exchanges(id),project_id TEXT NOT NULL REFERENCES projects(id),work_order_id TEXT NOT NULL REFERENCES work_orders(id),source_sequence INTEGER NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('stop','resume')),scope TEXT NOT NULL CHECK(scope IN ('all','trial')),held INTEGER NOT NULL CHECK(held IN (0,1)));
CREATE INDEX IF NOT EXISTS production_control_scope ON production_controls(project_id,work_order_id,source_sequence);
"""
SCHEMA += EXECUTION_REVIEW_SCHEMA

ECO_SCHEMA = """
CREATE TABLE IF NOT EXISTS eco_changes(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),old_revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),new_revision_id TEXT REFERENCES engineering_revisions(id),work_order_ids_json TEXT NOT NULL,sn_ids_json TEXT NOT NULL,reason TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('open','closed')),created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS eco_project ON eco_changes(project_id,created_at,id);
CREATE TABLE IF NOT EXISTS eco_impacts(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),eco_id TEXT NOT NULL REFERENCES eco_changes(id),payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS eco_dispositions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),eco_id TEXT NOT NULL REFERENCES eco_changes(id),impact_id TEXT NOT NULL REFERENCES eco_impacts(id),q_atoms INTEGER NOT NULL CHECK(q_atoms>0),decision TEXT NOT NULL,evidence TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS eco_dispositions_scope ON eco_dispositions(project_id,eco_id,impact_id);
CREATE TABLE IF NOT EXISTS eco_switches(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),eco_id TEXT NOT NULL REFERENCES eco_changes(id),work_order_id TEXT NOT NULL REFERENCES work_orders(id),new_work_order_id TEXT,new_revision_id TEXT REFERENCES engineering_revisions(id),boundary TEXT NOT NULL,q_atoms INTEGER NOT NULL CHECK(q_atoms>0),retained_atoms INTEGER NOT NULL CHECK(retained_atoms>=0),exchange_id TEXT NOT NULL UNIQUE REFERENCES exchanges(id),accepted_receipt_id TEXT UNIQUE,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS eco_switches_scope ON eco_switches(project_id,work_order_id);
CREATE TABLE IF NOT EXISTS allocation_adjustments(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),order_line_id TEXT NOT NULL REFERENCES order_lines(id),work_order_id TEXT NOT NULL REFERENCES work_orders(id),delta_atoms INTEGER NOT NULL,switch_id TEXT NOT NULL REFERENCES eco_switches(id));
CREATE VIEW IF NOT EXISTS effective_work_orders AS SELECT w.*, w.q_atoms-COALESCE((SELECT SUM(s.q_atoms) FROM eco_switches s WHERE s.work_order_id=w.id AND s.project_id=w.project_id AND s.accepted_receipt_id IS NOT NULL),0) obligation_atoms FROM work_orders w;
CREATE VIEW IF NOT EXISTS effective_allocations AS SELECT id,project_id,order_line_id,work_order_id,q_atoms,unit,created_at FROM allocations UNION ALL SELECT a.id,a.project_id,a.order_line_id,a.work_order_id,a.delta_atoms,w.unit,s.created_at FROM allocation_adjustments a JOIN work_orders w ON w.id=a.work_order_id JOIN eco_switches s ON s.id=a.switch_id;
"""
SCHEMA += ECO_SCHEMA

ECO_REVIEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS eco_stock_openings(eco_id TEXT NOT NULL REFERENCES eco_changes(id),project_id TEXT NOT NULL REFERENCES projects(id),lot_id TEXT NOT NULL REFERENCES material_lots(id),basis_json TEXT NOT NULL,consumed_atoms INTEGER NOT NULL,complete INTEGER NOT NULL,PRIMARY KEY(eco_id,lot_id));
CREATE TABLE IF NOT EXISTS eco_retentions(eco_id TEXT NOT NULL REFERENCES eco_changes(id),project_id TEXT NOT NULL REFERENCES projects(id),work_order_id TEXT NOT NULL REFERENCES work_orders(id),q_atoms INTEGER NOT NULL CHECK(q_atoms>0),unit_ids_json TEXT NOT NULL,evidence TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(eco_id,work_order_id));
"""
SCHEMA += ECO_REVIEW_SCHEMA

QUALITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS quality_tests(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),unit_id TEXT NOT NULL REFERENCES units(id),revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),attempt INTEGER NOT NULL,scope_json TEXT NOT NULL,measurements_json TEXT NOT NULL,outcome TEXT NOT NULL,rework_order_id TEXT,execution_ids_json TEXT NOT NULL,source_system TEXT NOT NULL,source_type TEXT NOT NULL,source_external_id TEXT NOT NULL,source_json TEXT NOT NULL,actor_id TEXT NOT NULL,occurred_at TEXT NOT NULL,recorded_at TEXT NOT NULL,UNIQUE(unit_id,attempt),UNIQUE(source_system,source_type,source_external_id));
CREATE INDEX IF NOT EXISTS quality_tests_page ON quality_tests(project_id,seq);
CREATE TABLE IF NOT EXISTS nonconformances(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),unit_id TEXT NOT NULL REFERENCES units(id),test_id TEXT NOT NULL UNIQUE REFERENCES quality_tests(id),defect TEXT NOT NULL,evidence TEXT NOT NULL,actor_id TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quality_dispositions(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),nonconformance_id TEXT NOT NULL REFERENCES nonconformances(id),unit_id TEXT NOT NULL REFERENCES units(id),decision TEXT NOT NULL,evidence TEXT NOT NULL,actor_id TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rework_orders(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),nonconformance_id TEXT NOT NULL UNIQUE REFERENCES nonconformances(id),unit_id TEXT NOT NULL REFERENCES units(id),revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),route_id TEXT NOT NULL,route_json TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rework_completions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),rework_order_id TEXT NOT NULL UNIQUE REFERENCES rework_orders(id),execution_ids_json TEXT NOT NULL,test_ids_json TEXT NOT NULL,actor_id TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quality_releases(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),kind TEXT NOT NULL,decision TEXT NOT NULL,payload_json TEXT NOT NULL,actor_id TEXT NOT NULL,created_at TEXT NOT NULL,source_system TEXT,source_type TEXT,source_external_id TEXT,UNIQUE(source_system,source_type,source_external_id));
CREATE TABLE IF NOT EXISTS quality_release_units(release_id TEXT NOT NULL REFERENCES quality_releases(id),project_id TEXT NOT NULL REFERENCES projects(id),unit_id TEXT NOT NULL REFERENCES units(id),test_id TEXT REFERENCES quality_tests(id),PRIMARY KEY(release_id,unit_id));
CREATE INDEX IF NOT EXISTS quality_release_units_scope ON quality_release_units(project_id,unit_id);
"""
SCHEMA += QUALITY_SCHEMA

QUALITY_REVIEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS quality_test_bases(test_id TEXT PRIMARY KEY REFERENCES quality_tests(id),project_id TEXT NOT NULL REFERENCES projects(id),execution_cutoff INTEGER,prior_test_id TEXT REFERENCES quality_tests(id));
CREATE VIEW IF NOT EXISTS valid_quality_tests AS
SELECT t.* FROM quality_tests t WHERE t.rework_order_id IS NULL OR EXISTS (
 SELECT 1 FROM quality_test_bases b JOIN quality_test_bases prior ON prior.test_id=b.prior_test_id AND prior.project_id=b.project_id
 JOIN rework_orders rw ON rw.id=t.rework_order_id AND rw.project_id=t.project_id AND rw.unit_id=t.unit_id
 JOIN nonconformances nc ON nc.id=rw.nonconformance_id AND nc.project_id=rw.project_id
 WHERE b.test_id=t.id AND b.project_id=t.project_id AND b.execution_cutoff IS NOT NULL AND prior.execution_cutoff IS NOT NULL
 AND b.prior_test_id=COALESCE((SELECT earlier.id FROM quality_tests earlier WHERE earlier.project_id=t.project_id AND earlier.rework_order_id=t.rework_order_id AND earlier.seq<t.seq ORDER BY earlier.seq DESC LIMIT 1),nc.test_id)
 AND json_array_length(t.execution_ids_json)>0
 AND NOT EXISTS (SELECT 1 FROM json_each(t.execution_ids_json) proof LEFT JOIN execution_events e ON e.id=proof.value AND e.project_id=t.project_id
 WHERE e.id IS NULL OR e.unit_id<>t.unit_id OR e.rework_order_id IS NOT t.rework_order_id OR e.status<>'accepted' OR e.result<>'pass'
 OR e.accepted_seq<=prior.execution_cutoff OR e.accepted_seq>b.execution_cutoff
 OR NOT EXISTS(SELECT 1 FROM execution_admissions a WHERE a.event_id=e.id AND a.project_id=e.project_id AND a.admitted=1))
);
"""
SCHEMA += QUALITY_REVIEW_SCHEMA

DELIVERY_SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_basis_proofs(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),eco_id TEXT NOT NULL REFERENCES eco_changes(id),reservation_id TEXT NOT NULL REFERENCES reservations(id),exchange_id TEXT NOT NULL UNIQUE REFERENCES exchanges(id),proof_json TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS material_movements(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),material_lot_id TEXT NOT NULL REFERENCES material_lots(id),movement TEXT NOT NULL CHECK(movement IN ('return','raw_loss')),q_atoms INTEGER NOT NULL CHECK(q_atoms>0),supersedes_id TEXT UNIQUE REFERENCES material_movements(id),source_system TEXT NOT NULL,source_type TEXT NOT NULL,source_external_id TEXT NOT NULL,source_json TEXT NOT NULL,external_signatory TEXT NOT NULL,evidence TEXT NOT NULL,actor_id TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(source_system,source_type,source_external_id));
CREATE VIEW IF NOT EXISTS effective_material_movements AS SELECT m.* FROM material_movements m WHERE NOT EXISTS(SELECT 1 FROM material_movements correction WHERE correction.supersedes_id=m.id);
CREATE TABLE IF NOT EXISTS ownership_reconciliations(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),material_lot_id TEXT NOT NULL REFERENCES material_lots(id),balance_json TEXT NOT NULL,source_system TEXT NOT NULL,source_type TEXT NOT NULL,source_external_id TEXT NOT NULL,source_json TEXT NOT NULL,actor_id TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(source_system,source_type,source_external_id));
CREATE TABLE IF NOT EXISTS closures(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),kind TEXT NOT NULL CHECK(kind IN ('fulfillment','quality','cost')),source_system TEXT NOT NULL,source_type TEXT NOT NULL,source_external_id TEXT NOT NULL,source_json TEXT NOT NULL,evidence TEXT NOT NULL,actor_id TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(source_system,source_type,source_external_id));
CREATE TABLE IF NOT EXISTS shipments(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),order_line_id TEXT NOT NULL REFERENCES order_lines(id),exchange_id TEXT NOT NULL REFERENCES exchanges(id),q_atoms INTEGER NOT NULL CHECK(q_atoms>0),unit TEXT NOT NULL,units_json TEXT NOT NULL,boxes_json TEXT NOT NULL,state TEXT NOT NULL CHECK(state IN ('pending','accepted','rejected','held')),created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS shipments_page ON shipments(project_id,created_at,id);
CREATE TABLE IF NOT EXISTS shipment_claims(unit_id TEXT PRIMARY KEY REFERENCES units(id),project_id TEXT NOT NULL REFERENCES projects(id),order_line_id TEXT NOT NULL REFERENCES order_lines(id),shipment_id TEXT NOT NULL REFERENCES shipments(id));
CREATE TABLE IF NOT EXISTS shipment_items(unit_id TEXT PRIMARY KEY REFERENCES units(id),project_id TEXT NOT NULL REFERENCES projects(id),order_line_id TEXT NOT NULL REFERENCES order_lines(id),shipment_id TEXT NOT NULL REFERENCES shipments(id),receipt_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shipment_box_claims(box_id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),shipment_id TEXT NOT NULL REFERENCES shipments(id));
CREATE TABLE IF NOT EXISTS shipment_freeze_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,project_id TEXT NOT NULL REFERENCES projects(id),unit_id TEXT NOT NULL REFERENCES units(id),state TEXT NOT NULL CHECK(state IN ('pending','frozen','released')),source_sequence INTEGER,reference TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS shipment_freeze_scope ON shipment_freeze_events(project_id,unit_id,seq DESC);
CREATE TABLE IF NOT EXISTS delivery_facts(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),shipment_id TEXT NOT NULL REFERENCES shipments(id),action TEXT NOT NULL CHECK(action IN ('sign','accept')),q_atoms INTEGER NOT NULL CHECK(q_atoms>0),source_system TEXT NOT NULL,source_type TEXT NOT NULL,source_external_id TEXT NOT NULL,source_json TEXT NOT NULL,external_signatory TEXT NOT NULL,actor_id TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(source_system,source_type,source_external_id));
CREATE TABLE IF NOT EXISTS acceptance_issues(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),shipment_id TEXT NOT NULL REFERENCES shipments(id),fact_id TEXT NOT NULL REFERENCES delivery_facts(id),title TEXT NOT NULL,owner_id TEXT NOT NULL,owner_name TEXT NOT NULL,required INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS acceptance_resolutions(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),issue_id TEXT NOT NULL UNIQUE REFERENCES acceptance_issues(id),evidence TEXT NOT NULL,actor_id TEXT NOT NULL,created_at TEXT NOT NULL);
"""
SCHEMA += DELIVERY_SCHEMA

FEEDBACK_SCHEMA = """
CREATE TABLE IF NOT EXISTS freeze_requests(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),exchange_id TEXT NOT NULL UNIQUE REFERENCES exchanges(id),requested_state TEXT NOT NULL CHECK(requested_state IN ('frozen','unfrozen')),source_version INTEGER NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS freeze_members(request_id TEXT NOT NULL REFERENCES freeze_requests(id),project_id TEXT NOT NULL REFERENCES projects(id),unit_id TEXT REFERENCES units(id),lot_id TEXT REFERENCES material_lots(id),CHECK((unit_id IS NULL)<>(lot_id IS NULL)));
CREATE INDEX IF NOT EXISTS freeze_unit ON freeze_members(project_id,unit_id,request_id);
CREATE INDEX IF NOT EXISTS freeze_lot ON freeze_members(project_id,lot_id,request_id);
CREATE TABLE IF NOT EXISTS freeze_confirmations(project_id TEXT NOT NULL REFERENCES projects(id),object_kind TEXT NOT NULL,object_id TEXT NOT NULL,request_id TEXT NOT NULL REFERENCES freeze_requests(id),state TEXT NOT NULL CHECK(state IN ('frozen','unfrozen')),source_version INTEGER NOT NULL,source_sequence INTEGER NOT NULL,PRIMARY KEY(project_id,object_kind,object_id));
CREATE TABLE IF NOT EXISTS rmas(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),unit_id TEXT NOT NULL REFERENCES units(id),shipment_id TEXT NOT NULL REFERENCES shipments(id),order_line_id TEXT NOT NULL REFERENCES order_lines(id),customer_id TEXT NOT NULL,revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),test_cutoff INTEGER NOT NULL,reason TEXT NOT NULL,source_system TEXT NOT NULL,source_type TEXT NOT NULL,source_external_id TEXT NOT NULL,source_json TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(source_system,source_type,source_external_id));
CREATE INDEX IF NOT EXISTS rmas_scope ON rmas(project_id,unit_id,seq);
CREATE TABLE IF NOT EXISTS capas(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,project_id TEXT NOT NULL REFERENCES projects(id),rma_id TEXT NOT NULL UNIQUE REFERENCES rmas(id),state TEXT NOT NULL CHECK(state IN ('open','closed')),created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS capa_steps(seq INTEGER PRIMARY KEY AUTOINCREMENT,project_id TEXT NOT NULL REFERENCES projects(id),capa_id TEXT NOT NULL REFERENCES capas(id),step TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS capa_steps_scope ON capa_steps(project_id,capa_id,seq);
CREATE INDEX IF NOT EXISTS consumption_lot_trace ON material_consumption(project_id,lot_id,unit_id);
"""
SCHEMA += FEEDBACK_SCHEMA

AGREEMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS contract_agreements(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),revision_id TEXT NOT NULL REFERENCES engineering_revisions(id),supersedes_id TEXT UNIQUE REFERENCES contract_agreements(id),contract_json TEXT NOT NULL,customer_id TEXT NOT NULL,external_signatory TEXT NOT NULL,evidence TEXT NOT NULL,project_version INTEGER NOT NULL,created_at TEXT NOT NULL,UNIQUE(project_id,project_version));
CREATE INDEX IF NOT EXISTS contract_agreements_scope ON contract_agreements(project_id,revision_id,project_version DESC);
CREATE VIEW IF NOT EXISTS current_revision_contracts AS SELECT r.project_id,r.id revision_id,COALESCE(a.contract_json,p.contract_json) contract_json FROM engineering_revisions r JOIN projects p ON p.id=r.project_id LEFT JOIN contract_agreements a ON a.id=(SELECT id FROM contract_agreements current WHERE current.project_id=r.project_id AND current.revision_id=r.id ORDER BY current.project_version DESC LIMIT 1);
"""
SCHEMA += AGREEMENT_SCHEMA

SCHEMA += INTRODUCTION_SCHEMA
SCHEMA += ISSUE_RESOLUTION_SCHEMA

SCHEMA += LABORATORY_SCHEMA

SCHEMA += AUTHORITY_SCHEMA + ARRIVAL_SCHEMA

SCHEMA += HANDOFF_SCHEMA

SCHEMA += EXPEDITE_SCHEMA + ISSUE_MARK_SCHEMA

from .material_task_schema import MATERIAL_TASK_SCHEMA
SCHEMA += MATERIAL_TASK_SCHEMA

from .native_material_schema import NATIVE_MATERIAL_SCHEMA
SCHEMA += NATIVE_MATERIAL_SCHEMA

from .material_need_time import SCHEMA as MATERIAL_NEED_TIME_SCHEMA
SCHEMA += MATERIAL_NEED_TIME_SCHEMA
