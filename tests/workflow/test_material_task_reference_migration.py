from manufacturing_platform.workflow.schema import SCHEMA_VERSION


def test_fresh_schema_supports_verify_and_nullable_requirement(workflow):
    workflow.create_project(mode='oem')
    with workflow.db() as tx:
        assert SCHEMA_VERSION == 28
        columns = {row['name']: row for row in tx.execute('PRAGMA table_info(material_tasks)')}
        assert not columns['requirement_id']['notnull']
        assert 'reference_json' in columns and 'reference_key' in columns
        assert tx.execute("SELECT 1 FROM sqlite_master WHERE name='material_task_requirements'").fetchone()


def _legacy_db():
    import sqlite3
    from manufacturing_platform.workflow.material_task_schema import LEGACY_MATERIAL_TASK_SCHEMA
    db = sqlite3.connect(':memory:', isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    for table in ('projects', 'requirements', 'material_handoffs'):
        db.execute(f'CREATE TABLE {table}(id TEXT PRIMARY KEY)')
        db.execute(f"INSERT INTO {table} VALUES ('{table}')")
    for statement in LEGACY_MATERIAL_TASK_SCHEMA.split(';'):
        if statement.strip():
            db.execute(statement)
    db.execute("INSERT INTO material_tasks(id,project_id,requirement_id,task_kind,assignee_id,state,payload_json,closure_json) VALUES ('t','projects','requirements','iqc','u','closed',' {\"source\": 1} ',' {\"result\": 2} ')")
    for idx, state in enumerate(('pending','processing','verification','cancelled'), 1):
        db.execute("INSERT INTO material_tasks(id,project_id,requirement_id,task_kind,handoff_id,assignee_id,proposed_assignee_id,state,payload_json) VALUES (?,?,?,?,?,?,?,?,?)",
                   (f'trace-{idx}','projects','requirements','trace',f'handoff-{idx}','u','proposed',state,' {"source": "unchanged"} '))
    db.execute("INSERT INTO material_task_history(project_id,task_id,payload_json) VALUES ('projects','t',' {\"history\": 3} ')")
    db.execute("INSERT INTO material_task_evidence VALUES ('projects','t','material_handoffs')")
    db.execute("UPDATE sqlite_sequence SET seq=91 WHERE name='material_tasks'")
    db.execute("UPDATE sqlite_sequence SET seq=93 WHERE name='material_task_history'")
    return db


def test_legacy_rebuild_preserves_children_bytes_and_highwater():
    from manufacturing_platform.workflow.material_task_reference_migration import migrate_material_task_references
    db = _legacy_db()
    before = {name: [tuple(r) for r in db.execute(f'SELECT * FROM {name}')] for name in ('material_tasks', 'material_task_history', 'material_task_evidence')}
    db.execute('BEGIN')
    migrate_material_task_references(db)
    db.commit()
    assert [tuple(row)[:12] for row in db.execute('SELECT * FROM material_tasks')] == before['material_tasks']
    for table in ('material_task_history', 'material_task_evidence'):
        assert [tuple(r) for r in db.execute(f'SELECT * FROM {table}')] == before[table]
    assert [tuple(r) for r in db.execute('PRAGMA foreign_key_check')] == []
    assert tuple(db.execute('SELECT project_id,task_id,requirement_id FROM material_task_requirements').fetchone()) == ('projects','t','requirements')
    db.execute("INSERT INTO material_tasks(id,project_id,task_kind,assignee_id,state,payload_json) VALUES ('new','projects','verify','u','pending','{}')")
    db.execute("INSERT INTO material_task_history(project_id,task_id,payload_json) VALUES ('projects','new','{}')")
    assert db.execute("SELECT seq FROM material_tasks WHERE id='new'").fetchone()[0] == 92
    assert db.execute("SELECT seq FROM material_task_history WHERE task_id='new'").fetchone()[0] == 94
    db.execute('BEGIN')
    migrate_material_task_references(db)
    db.commit()
    assert db.execute('SELECT COUNT(*) FROM material_task_requirements').fetchone()[0] == 5


def test_failed_migration_rolls_back_entire_rebuild():
    import pytest
    from manufacturing_platform.workflow.material_task_reference_migration import migrate_material_task_references
    db = _legacy_db()
    db.execute('PRAGMA foreign_keys=OFF')
    db.execute("INSERT INTO material_task_history(project_id,task_id,payload_json) VALUES ('projects','missing','{}')")
    db.execute('PRAGMA foreign_keys=ON')
    before = list(db.iterdump())
    db.execute('BEGIN')
    with pytest.raises(Exception):
        migrate_material_task_references(db)
    db.rollback()
    assert list(db.iterdump()) == before
    assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1


def test_store_read_migrates_legacy_once_and_reopens(workflow):
    import sqlite3
    from .conftest import BASE, USERS
    from .test_expedites import setup
    from manufacturing_platform.workflow.material_task_schema import LEGACY_MATERIAL_TASK_SCHEMA
    pid, rid, facts = setup(workflow, qualified='0')
    receipt = workflow.receive(pid, facts['id'], quantity='1', lot_id=facts['lot_id'])['object_id']
    task = workflow.command(pid, 'material_task.open', actor_name='supply', requirement_id=rid, task_kind='iqc',
        receipt_id=receipt, assignee_id=str(USERS['quality']), note='inspection')['object_id']
    with sqlite3.connect(workflow.paths.domain) as db:
        tasks = db.execute('SELECT seq,id,project_id,requirement_id,task_kind,receipt_id,handoff_id,assignee_id,proposed_assignee_id,state,payload_json,closure_json FROM material_tasks').fetchall()
        history = db.execute('SELECT * FROM material_task_history').fetchall()
        evidence = db.execute('SELECT * FROM material_task_evidence').fetchall()
        db.execute('DROP TABLE material_task_requirements')
        db.execute('DROP TABLE material_task_evidence')
        db.execute('DROP TABLE material_task_history')
        db.execute('DROP TABLE material_tasks')
        for statement in LEGACY_MATERIAL_TASK_SCHEMA.split(';'):
            if statement.strip(): db.execute(statement)
        db.executemany('INSERT INTO material_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', tasks)
        db.executemany('INSERT INTO material_task_history VALUES (?,?,?,?)', history)
        db.executemany('INSERT INTO material_task_evidence VALUES (?,?,?)', evidence)
        db.execute("UPDATE sqlite_sequence SET seq=100 WHERE name='material_task_history'")
        db.execute('UPDATE schema_version SET version=27')
    for _ in range(2):
        workflow.reopen()
        response = workflow.client('supply').get(f'{BASE}/projects/{pid}/objects/material_task/{task}')
        assert response.status_code == 200 and not response.json()['value']['reference_pinned']
        with workflow.db() as db:
            assert db.execute('SELECT version FROM schema_version').fetchone()[0] == SCHEMA_VERSION
            assert [tuple(row)[:12] for row in db.execute('SELECT * FROM material_tasks')] == tasks
            assert [tuple(row) for row in db.execute('SELECT * FROM material_task_history')] == history
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
            assert db.execute("SELECT seq FROM sqlite_sequence WHERE name='material_task_history'").fetchone()[0] == 100
