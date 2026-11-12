"""Rebuild the task aggregate transactionally with foreign keys enabled."""
from .material_task_schema import MATERIAL_TASK_SCHEMA


def migrate_material_task_references(tx):
    columns = {r[1] for r in tx.execute('PRAGMA table_info(material_tasks)')}
    if 'reference_json' not in columns:
        # Preserve deleted AUTOINCREMENT high-water marks as well as extant IDs.
        sequences = dict(tx.execute("SELECT name,seq FROM sqlite_sequence WHERE name IN ('material_tasks','material_task_history')"))
        tx.execute("""CREATE TABLE material_tasks_new(
            seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
            project_id TEXT NOT NULL REFERENCES projects(id), requirement_id TEXT REFERENCES requirements(id),
            task_kind TEXT NOT NULL CHECK(task_kind IN ('iqc','trace','verify')), receipt_id TEXT, handoff_id TEXT,
            assignee_id TEXT NOT NULL, proposed_assignee_id TEXT, state TEXT NOT NULL,
            payload_json TEXT NOT NULL, closure_json TEXT, reference_json TEXT, reference_key TEXT, CHECK(task_kind='verify' OR requirement_id IS NOT NULL))""")
        tx.execute("""INSERT INTO material_tasks_new(seq,id,project_id,requirement_id,task_kind,receipt_id,handoff_id,assignee_id,proposed_assignee_id,state,payload_json,closure_json)
            SELECT seq,id,project_id,requirement_id,task_kind,receipt_id,handoff_id,assignee_id,proposed_assignee_id,state,payload_json,closure_json FROM material_tasks""")
        tx.execute("""CREATE TABLE material_task_history_new(seq INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL,
            task_id TEXT NOT NULL REFERENCES material_tasks_new(id), payload_json TEXT NOT NULL)""")
        tx.execute('INSERT INTO material_task_history_new SELECT * FROM material_task_history')
        tx.execute("""CREATE TABLE material_task_evidence_new(project_id TEXT NOT NULL,
            task_id TEXT NOT NULL REFERENCES material_tasks_new(id), handoff_id TEXT NOT NULL REFERENCES material_handoffs(id),
            PRIMARY KEY(project_id,handoff_id))""")
        tx.execute('INSERT INTO material_task_evidence_new SELECT * FROM material_task_evidence')
        tx.execute('DROP TABLE material_task_history')
        tx.execute('DROP TABLE material_task_evidence')
        tx.execute('DROP TABLE material_tasks')
        for old, new in [('material_tasks_new','material_tasks'), ('material_task_history_new','material_task_history'), ('material_task_evidence_new','material_task_evidence')]:
            tx.execute(f'ALTER TABLE {old} RENAME TO {new}')
        for name, high in sequences.items():
            tx.execute('UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name=?', (high,name))
            if not tx.execute('SELECT 1 FROM sqlite_sequence WHERE name=?', (name,)).fetchone():
                tx.execute('INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)', (name,high))
    else:
        info = {r[1]: r for r in tx.execute('PRAGMA table_info(material_tasks)')}
        sql = tx.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='material_tasks'").fetchone()[0]
        if not {'reference_json', 'reference_key', 'requirement_id'} <= info.keys() or info['requirement_id'][3] or "'verify'" not in sql:
            raise ValueError('invalid material task reference schema')
    for statement in MATERIAL_TASK_SCHEMA.split(';'):
        if statement.strip():
            tx.execute(statement)
    tx.execute('INSERT OR IGNORE INTO material_task_requirements(project_id,task_id,requirement_id) SELECT project_id,id,requirement_id FROM material_tasks WHERE requirement_id IS NOT NULL')
    if tx.execute('PRAGMA foreign_key_check').fetchone():
        raise ValueError('material task migration has foreign key violations')
