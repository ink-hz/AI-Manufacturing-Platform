"""Additive coordination records; no inventory or quality mutations."""
MATERIAL_TASK_SCHEMA = """
CREATE TABLE IF NOT EXISTS material_tasks(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
 project_id TEXT NOT NULL REFERENCES projects(id), requirement_id TEXT NOT NULL REFERENCES requirements(id),
 task_kind TEXT NOT NULL CHECK(task_kind IN ('iqc','trace')), receipt_id TEXT, handoff_id TEXT,
 assignee_id TEXT NOT NULL, proposed_assignee_id TEXT, state TEXT NOT NULL,
 payload_json TEXT NOT NULL, closure_json TEXT
);
CREATE INDEX IF NOT EXISTS material_tasks_page ON material_tasks(project_id,seq);
CREATE UNIQUE INDEX IF NOT EXISTS material_task_open_iqc ON material_tasks(project_id,receipt_id) WHERE task_kind='iqc' AND state NOT IN ('closed','cancelled');
CREATE UNIQUE INDEX IF NOT EXISTS material_task_open_trace ON material_tasks(project_id,handoff_id) WHERE task_kind='trace' AND state NOT IN ('closed','cancelled');
CREATE TABLE IF NOT EXISTS material_task_history(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, task_id TEXT NOT NULL REFERENCES material_tasks(id), payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS material_task_history_scope ON material_task_history(project_id,task_id,seq);
CREATE TABLE IF NOT EXISTS material_task_evidence(
 project_id TEXT NOT NULL, task_id TEXT NOT NULL REFERENCES material_tasks(id), handoff_id TEXT NOT NULL REFERENCES material_handoffs(id),
 PRIMARY KEY(project_id,handoff_id)
);
"""
