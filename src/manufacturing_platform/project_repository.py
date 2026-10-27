"""Durable isolated project aggregates; child writes serialize without lost updates."""
from contextlib import contextmanager
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .project_models import ProjectDetail
from .repository import Conflict, NotFound, _now

_SCHEMA = '''
CREATE TABLE IF NOT EXISTS manufacturing_projects (
 id TEXT PRIMARY KEY, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS manufacturing_project_operations (
 operation_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL,
 kind TEXT NOT NULL, scope TEXT NOT NULL, payload TEXT NOT NULL, response TEXT NOT NULL
);
'''


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _summary(detail, db=None):
    project = dict(detail['project'])
    stages, tasks = detail['stages'], detail['tasks']
    if project['archived']:
        status = 'archived'
    elif any(item['status'] == 'blocked' for item in stages + tasks):
        status = 'blocked'
    elif all(item['status'] == 'done' for item in stages + tasks):
        status = 'completed'
    elif any(item['status'] in {'doing', 'done'} for item in stages + tasks):
        status = 'active'
    else:
        status = 'planned'
    if db is not None:
        from .collaboration_queries import compose_status
        status = compose_status(db, project['id'], status)
    current = next((s for s in stages if s['status'] in {'doing', 'blocked'}), None)
    current = current or next((s for s in stages if s['status'] != 'done'), stages[-1])
    return {**project, 'status': status, 'current_stage_id': current['id'], 'current_stage_name': current['name'],
            'completed_stages': sum(s['status'] == 'done' for s in stages), 'total_stages': len(stages),
            'open_tasks': sum(t['status'] != 'done' for t in tasks)}


def _public(detail, db=None):
    return {**detail, 'project': _summary(detail, db), 'activity': list(reversed(detail['activity'][-50:]))}


class ProjectRepository:
    def __init__(self, database_path, catalog):
        if not database_path or not database_path.strip() or database_path == ':memory:':
            raise ValueError('An explicit persistent database path is required')
        self.path = Path(database_path)
        self.catalog = catalog

    @contextmanager
    def _connection(self, *, write=False):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        try:
            db.execute('PRAGMA busy_timeout=5000')
            db.execute('PRAGMA journal_mode=WAL')
            from .collaboration_store import SCHEMA
            db.execute('PRAGMA foreign_keys=ON')
            db.executescript(_SCHEMA + SCHEMA)
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
        finally:
            db.close()

    @staticmethod
    def _read(db, project_id):
        row = db.execute('SELECT body FROM manufacturing_projects WHERE id=?', (project_id,)).fetchone()
        if not row:
            raise NotFound()
        return ProjectDetail.model_validate_json(row[0]).model_dump(mode='json')

    @staticmethod
    def _save(db, detail):
        detail['project'] = _summary(detail)
        db.execute('UPDATE manufacturing_projects SET body=? WHERE id=?', (_json(detail), detail['project']['id']))

    @staticmethod
    def _activity(detail, actor, action, summary, *, stage_id=None, task_id=None):
        now = _now()
        detail['project'].update(updated_at=now, updated_by=actor)
        detail['activity'].append({'id': str(uuid4()), 'created_at': now, 'actor': actor,
                                   'action': action, 'summary': summary, 'stage_id': stage_id, 'task_id': task_id})
        detail['activity'] = detail['activity'][-200:]

    @staticmethod
    def _retry(db, value, actor, kind, scope):
        payload = _json(value.model_dump(mode='json', exclude={'operation_id'}))
        if db.execute('SELECT 1 FROM manufacturing_control_operations WHERE operation_id=?',(str(value.operation_id),)).fetchone():
            raise Conflict()
        row = db.execute('SELECT actor_id,kind,scope,payload,response FROM manufacturing_project_operations WHERE operation_id=?', (str(value.operation_id),)).fetchone()
        if row:
            if row[:4] != (actor, kind, scope, payload):
                raise Conflict()
            return json.loads(row[4]), payload
        return None, payload

    @staticmethod
    def _remember(db, value, actor, kind, scope, payload, response):
        db.execute('INSERT INTO manufacturing_project_operations VALUES (?,?,?,?,?,?)', (str(value.operation_id), actor, kind, scope, payload, _json(response)))

    def create(self, value, actor_id, actor_label):
        # A recorded operation outlives catalog changes. New unknown scopes do
        # not initialize an empty database; existing keys are checked first.
        try:
            line = self.catalog.line(value.line_id)
            templates = self.catalog.line_stages(value.line_id)
        except KeyError:
            line, templates = None, []
        if not templates and not self.path.is_file():
            raise NotFound()
        with self._connection(write=True) as db:
            retry, payload = self._retry(db, value, actor_id, 'project', '')
            if retry is not None:
                return retry
            if not templates:
                raise NotFound()
            now, project_id = _now(), str(uuid4())
            core = value.model_dump(mode='json', exclude={'operation_id'})
            project = {**core, 'id': project_id, 'code': 'MF-'+project_id.upper(), 'line_name': line['name'], 'group_id': line['group_id'],
                       'archived': False, 'version': 1, 'created_at': now, 'updated_at': now, 'updated_by': actor_label}
            stages = [{**stage, 'status': 'todo', 'owner': '', 'due_date': None, 'blocker': '', 'practice': '',
                       'participants': [], 'handoffs': [], 'systems': [], 'version': 1, 'updated_at': now, 'updated_by': actor_label} for stage in templates]
            detail = {'project': project, 'stages': stages, 'tasks': [], 'activity': []}
            self._activity(detail, actor_label, 'project_created', '创建制造项目')
            detail['project'] = _summary(detail)
            db.execute('INSERT INTO manufacturing_projects VALUES (?,?)', (project_id, _json(detail)))
            response = _public(detail, db)
            self._remember(db, value, actor_id, 'project', '', payload, response)
            return response

    def get(self, project_id):
        with self._connection() as db:
            return _public(self._read(db, project_id), db)

    def _all(self, db=None):
        if db is None:
            with self._connection() as connection:
                return self._all(connection)
        return [ProjectDetail.model_validate_json(row[0]).model_dump(mode='json') for row in db.execute('SELECT body FROM manufacturing_projects ORDER BY rowid DESC')]

    def list(self):
        with self._connection() as db:
            return [_summary(detail, db) for detail in self._all(db)]

    def update(self, project_id, value, actor_label):
        with self._connection(write=True) as db:
            detail = self._read(db, project_id)
            project = detail['project']
            if project['version'] != value.expected_version:
                raise Conflict()
            changes = value.model_dump(mode='json', exclude_unset=True, exclude={'expected_version'})
            if any(project[k] != v for k, v in changes.items()):
                project.update(changes)
                project.update(version=project['version']+1, updated_at=_now(), updated_by=actor_label)
                self._activity(detail, actor_label, 'project_updated', '更新项目资料')
                self._save(db, detail)
            return _public(detail, db)

    def update_stage(self, project_id, stage_id, value, actor_label):
        with self._connection(write=True) as db:
            detail = self._read(db, project_id)
            stage = next((s for s in detail['stages'] if s['id'] == stage_id), None)
            if stage is None:
                raise NotFound()
            if stage['version'] != value.expected_version:
                raise Conflict()
            changes = value.model_dump(mode='json', exclude={'expected_version'})
            if any(stage[k] != v for k, v in changes.items()):
                stage.update(changes)
                stage.update(version=stage['version']+1, updated_at=_now(), updated_by=actor_label)
                self._activity(detail, actor_label, 'stage_updated', '更新项目阶段', stage_id=stage_id)
                self._save(db, detail)
            return stage

    def create_task(self, project_id, value, actor_id, actor_label):
        with self._connection(write=True) as db:
            retry, payload = self._retry(db, value, actor_id, 'task', project_id)
            if retry is not None:
                return retry
            detail = self._read(db, project_id)
            if value.stage_id not in {s['id'] for s in detail['stages']}:
                raise NotFound()
            now = _now()
            task = {**value.model_dump(mode='json', exclude={'operation_id'}), 'id': str(uuid4()), 'project_id': project_id,
                    'status': 'todo', 'version': 1, 'created_at': now, 'updated_at': now, 'updated_by': actor_label, 'source': None}
            detail['tasks'].append(task)
            self._activity(detail, actor_label, 'task_created', '创建项目事项', stage_id=task['stage_id'], task_id=task['id'])
            self._save(db, detail)
            self._remember(db, value, actor_id, 'task', project_id, payload, task)
            return task

    def update_task(self, project_id, task_id, value, actor_label):
        with self._connection(write=True) as db:
            detail = self._read(db, project_id)
            task = next((t for t in detail['tasks'] if t['id'] == task_id), None)
            if task is None:
                raise NotFound()
            if task['version'] != value.expected_version:
                raise Conflict()
            changes = value.model_dump(mode='json', exclude_unset=True, exclude={'expected_version'})
            if changes.get('stage_id', task['stage_id']) not in {s['id'] for s in detail['stages']}:
                raise NotFound()
            if any(task[k] != v for k, v in changes.items()):
                task.update(changes)
                task.update(version=task['version']+1, updated_at=_now(), updated_by=actor_label)
                self._activity(detail, actor_label, 'task_updated', '更新项目事项', stage_id=task['stage_id'], task_id=task_id)
                self._save(db, detail)
            return task

    @staticmethod
    def _flat(details):
        result = []
        for detail in details:
            project = detail['project']
            if project['archived']:
                continue
            stages = {s['id']: s['name'] for s in detail['stages']}
            for task in detail['tasks']:
                result.append({**task, 'project_name': project['name'], 'project_code': project['code'], 'line_id': project['line_id'],
                               'line_name': project['line_name'], 'group_id': project['group_id'], 'stage_name': stages[task['stage_id']]})
        return result

    def tasks(self):
        return self._flat(self._all())

    def dashboard(self):
        with self._connection() as db:
            return self._dashboard(db)

    def _dashboard(self, db):
        from .collaboration_queries import attention as control_attention
        details = [d for d in self._all(db) if not d['project']['archived']]
        projects = sorted((_summary(d, db) for d in details), key=lambda p: p['updated_at'], reverse=True)
        tasks = self._flat(details)
        open_tasks = [t for t in tasks if t['status'] != 'done']
        today = date.today()
        soon = (today + timedelta(days=6)).isoformat()
        attention = sorted(open_tasks, key=lambda t: (t['status'] != 'blocked', {'urgent': 0, 'high': 1, 'normal': 2}[t['priority']], t['due_date'] is None, t['due_date'] or '', t['created_at'], t['id']))[:20]
        blockers, activity = [], []
        for detail in details:
            project = detail['project']
            stages = {s['id']: s for s in detail['stages']}
            for stage in detail['stages']:
                if stage['status'] == 'blocked':
                    blockers.append({'project_id': project['id'], 'project_name': project['name'], 'stage_id': stage['id'], 'stage_name': stage['name'],
                                     'task_id': None, 'title': stage['name'], 'reason': stage['blocker'], 'owner': stage['owner'], 'due_date': stage['due_date']})
            for task in detail['tasks']:
                if task['status'] == 'blocked':
                    blockers.append({'project_id': project['id'], 'project_name': project['name'], 'stage_id': task['stage_id'], 'stage_name': stages[task['stage_id']]['name'],
                                     'task_id': task['id'], 'title': task['title'], 'reason': task['notes'], 'owner': task['owner'], 'due_date': task['due_date']})
            activity.extend({**item, 'project_id': project['id'], 'project_name': project['name']} for item in detail['activity'])
        return {'control_attention': control_attention(db), 'counts': {'active_projects': sum(p['status'] != 'completed' for p in projects), 'blocked_projects': sum(p['status'] == 'blocked' for p in projects),
                           'due_soon': sum(p['status'] != 'completed' and p['due_date'] is not None and today.isoformat() <= p['due_date'] <= soon for p in projects),
                           'open_tasks': len(open_tasks), 'pending_confirmations': sum(t['kind'] == 'confirmation' for t in open_tasks)},
                'projects': sorted(projects, key=lambda p: (p['status'] == 'completed', p['status'] != 'blocked', p['due_date'] is None, p['due_date'] or ''))[:8],
                'attention': attention, 'blockers': blockers, 'activity': sorted(activity, key=lambda a: (a['created_at'], a['id']), reverse=True)[:50]}
