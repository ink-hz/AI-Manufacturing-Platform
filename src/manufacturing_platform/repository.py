"""SQLite persistence. Every operation uses its own durable connection/transaction."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .models import Record, RecordWrite, Task


class Conflict(Exception):
    """An optimistic version or idempotency key does not match."""


class NotFound(Exception):
    """Task does not exist within the requested scope."""


_SCHEMA = '''
CREATE TABLE IF NOT EXISTS stage_records (
 line_id TEXT NOT NULL, stage_id TEXT NOT NULL, body TEXT NOT NULL,
 PRIMARY KEY (line_id, stage_id)
);
CREATE TABLE IF NOT EXISTS tasks (
 id TEXT PRIMARY KEY, line_id TEXT NOT NULL, stage_id TEXT NOT NULL, body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_scope ON tasks(line_id, stage_id);
CREATE TABLE IF NOT EXISTS task_operations (
 operation_id TEXT PRIMARY KEY, line_id TEXT NOT NULL, stage_id TEXT NOT NULL,
 actor_id TEXT NOT NULL, title TEXT NOT NULL, response TEXT NOT NULL
);
'''


def _now():
    return datetime.now(timezone.utc).isoformat()


def _empty_record():
    return Record(practice='', participants=[], handoffs=[], systems=[], version=0, updated_at=None, updated_by=None).model_dump()


class Repository:
    def __init__(self, database_path: str):
        if not database_path or not database_path.strip() or database_path == ':memory:':
            raise ValueError('An explicit persistent database path is required')
        self.path = Path(database_path)

    @contextmanager
    def _connection(self, *, write=False):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        try:
            db.execute('PRAGMA busy_timeout=5000')
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(_SCHEMA)
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
        finally:
            db.close()

    def health(self):
        with self._connection() as db:
            db.execute('SELECT count(*) FROM stage_records').fetchone()

    @staticmethod
    def _record(db, line_id, stage_id):
        row = db.execute('SELECT body FROM stage_records WHERE line_id=? AND stage_id=?', (line_id, stage_id)).fetchone()
        return Record.model_validate_json(row[0]).model_dump() if row else _empty_record()

    def read_stage(self, line_id, stage_id):
        with self._connection() as db:
            record = self._record(db, line_id, stage_id)
            tasks = [Task.model_validate_json(row[0]).model_dump() for row in db.execute('SELECT body FROM tasks WHERE line_id=? AND stage_id=? ORDER BY rowid', (line_id, stage_id))]
            return {'record': record, 'tasks': tasks}

    def save_record(self, line_id, stage_id, value: RecordWrite, actor_label):
        with self._connection(write=True) as db:
            current = self._record(db, line_id, stage_id)
            if current['version'] != value.expected_version:
                raise Conflict()
            record = Record(**value.model_dump(exclude={'expected_version'}), version=current['version']+1, updated_at=_now(), updated_by=actor_label)
            db.execute('INSERT INTO stage_records VALUES (?,?,?) ON CONFLICT(line_id,stage_id) DO UPDATE SET body=excluded.body', (line_id, stage_id, record.model_dump_json()))
            return record.model_dump()

    def overview(self, line_id):
        result = {}
        with self._connection() as db:
            for stage_id, body in db.execute('SELECT stage_id, body FROM stage_records WHERE line_id=?', (line_id,)):
                record = Record.model_validate_json(body)
                result[stage_id] = {'recorded': bool(record.practice.strip()), 'open_tasks': 0}
            for stage_id, body in db.execute('SELECT stage_id, body FROM tasks WHERE line_id=?', (line_id,)):
                task = Task.model_validate_json(body)
                result.setdefault(stage_id, {'recorded': False, 'open_tasks': 0})['open_tasks'] += int(not task.completed)
        return result

    def create_task(self, line_id, stage_id, value, actor_id, actor_label):
        operation_id = str(value.operation_id)
        with self._connection(write=True) as db:
            operation = db.execute('SELECT line_id,stage_id,actor_id,title,response FROM task_operations WHERE operation_id=?', (operation_id,)).fetchone()
            if operation:
                if operation[:4] != (line_id, stage_id, actor_id, value.title):
                    raise Conflict()
                return Task.model_validate_json(operation[4]).model_dump()
            now = _now()
            task = Task(id=str(uuid4()), title=value.title, completed=False, version=1, created_at=now, updated_at=now, updated_by=actor_label)
            body = task.model_dump_json()
            db.execute('INSERT INTO tasks VALUES (?,?,?,?)', (task.id, line_id, stage_id, body))
            db.execute('INSERT INTO task_operations VALUES (?,?,?,?,?,?)', (operation_id, line_id, stage_id, actor_id, value.title, body))
            return task.model_dump()

    def update_task(self, line_id, stage_id, task_id, value, actor_label):
        with self._connection(write=True) as db:
            row = db.execute('SELECT body FROM tasks WHERE id=? AND line_id=? AND stage_id=?', (task_id, line_id, stage_id)).fetchone()
            if row is None:
                raise NotFound()
            task = Task.model_validate_json(row[0])
            if task.version != value.expected_version:
                raise Conflict()
            task = Task(**{**task.model_dump(), 'title': value.title, 'completed': value.completed, 'version':task.version+1, 'updated_at':_now(), 'updated_by':actor_label})
            db.execute('UPDATE tasks SET body=? WHERE id=? AND line_id=? AND stage_id=?', (task.model_dump_json(), task_id, line_id, stage_id))
            return task.model_dump()
