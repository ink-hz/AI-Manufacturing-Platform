"""Transactional control storage, immutable operation receipts and audit snapshots."""
import json
from uuid import uuid4
from fastapi import HTTPException
from .project_repository import ProjectRepository, _json
from .repository import Conflict, NotFound, _now

SCHEMA = '''
CREATE TABLE IF NOT EXISTS manufacturing_systems (id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS manufacturing_authorities (
 id TEXT PRIMARY KEY, line_id TEXT NOT NULL, object_type TEXT NOT NULL,
 system_id TEXT NOT NULL REFERENCES manufacturing_systems(id), active INTEGER NOT NULL, body TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS manufacturing_active_authority
 ON manufacturing_authorities(line_id,object_type) WHERE active=1;
CREATE TABLE IF NOT EXISTS manufacturing_packages (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES manufacturing_projects(id),
 family_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
 UNIQUE(family_id,revision)
);
CREATE TABLE IF NOT EXISTS manufacturing_handoffs (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES manufacturing_projects(id),
 package_id TEXT NOT NULL REFERENCES manufacturing_packages(id), body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS manufacturing_readiness (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES manufacturing_projects(id),
 package_id TEXT NOT NULL REFERENCES manufacturing_packages(id), body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS manufacturing_task_sources (
 project_id TEXT NOT NULL REFERENCES manufacturing_projects(id), task_id TEXT NOT NULL,
 readiness_id TEXT NOT NULL REFERENCES manufacturing_readiness(id), item_id TEXT NOT NULL,
 PRIMARY KEY(project_id,task_id)
);
CREATE TABLE IF NOT EXISTS manufacturing_control_events (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
 project_id TEXT, object_type TEXT NOT NULL, object_id TEXT NOT NULL, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS manufacturing_control_operations (
 operation_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, kind TEXT NOT NULL,
 scope TEXT NOT NULL, payload TEXT NOT NULL, response TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS manufacturing_events_no_update BEFORE UPDATE ON manufacturing_control_events
 BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
CREATE TRIGGER IF NOT EXISTS manufacturing_events_no_delete BEFORE DELETE ON manufacturing_control_events
 BEGIN SELECT RAISE(ABORT, 'immutable audit'); END;
CREATE TRIGGER IF NOT EXISTS manufacturing_operations_no_update BEFORE UPDATE ON manufacturing_control_operations
 BEGIN SELECT RAISE(ABORT, 'immutable operation'); END;
CREATE TRIGGER IF NOT EXISTS manufacturing_operations_no_delete BEFORE DELETE ON manufacturing_control_operations
 BEGIN SELECT RAISE(ABORT, 'immutable operation'); END;
'''
TABLES = {kind: 'manufacturing_'+kind for kind in ('systems','authorities','packages','handoffs','readiness')}


def require(condition, message):
    if not condition:
        raise HTTPException(422, message)


class CollaborationStore(ProjectRepository):
    @staticmethod
    def rows(db, kind, project_id=None):
        table = TABLES[kind]
        where, args = (' WHERE project_id=?', (project_id,)) if project_id is not None else ('', ())
        return [json.loads(row[0]) for row in db.execute(f'SELECT body FROM {table}{where} ORDER BY rowid', args)]

    @staticmethod
    def object(db, kind, object_id, project_id=None):
        row = db.execute(f'SELECT body FROM {TABLES[kind]} WHERE id=?', (object_id,)).fetchone()
        if not row:
            raise NotFound()
        value = json.loads(row[0])
        if project_id is not None and value['project_id'] != project_id:
            raise NotFound()
        return value

    @staticmethod
    def persist(db, kind, value):
        columns = {'id': value['id']}
        if kind == 'authorities':
            columns.update({k:value[k] for k in ('line_id','object_type','system_id','active')})
        elif kind == 'packages':
            columns.update({k:value[k] for k in ('project_id','family_id','revision')})
        elif kind in {'handoffs','readiness'}:
            columns.update({k:value[k] for k in ('project_id','package_id')})
        columns['body'] = _json(value)
        names = ','.join(columns)
        updates = ','.join(f'{k}=excluded.{k}' for k in columns if k != 'id')
        db.execute(f'INSERT INTO {TABLES[kind]} ({names}) VALUES ({",".join("?" for _ in columns)}) ON CONFLICT(id) DO UPDATE SET {updates}', tuple(columns.values()))

    @staticmethod
    def new(body, actor):
        now = _now()
        return {**body, 'id':str(uuid4()),'version':1,'created_at':now,'updated_at':now,'updated_by':actor,
                'recording_mode':'manual'}

    @staticmethod
    def changed(value, actor):
        return {**value,'version':value['version']+1,'updated_at':_now(),'updated_by':actor}

    @staticmethod
    def cas(value, request):
        if value['version'] != request.expected_version:
            raise Conflict()

    @staticmethod
    def fields(request, *, patch=False):
        return request.model_dump(mode='json',exclude={'operation_id','expected_version'},exclude_unset=patch)

    def event(self, db, kind, value, action, actor_id, actor, operation_id, *, reason=''):
        now = _now()
        event = {'id':str(uuid4()),'version':1,'created_at':now,'updated_at':now,'updated_by':actor,
                 'project_id':value.get('project_id'),'object_type':{'systems':'system','authorities':'authority','packages':'package','handoffs':'handoff','readiness':'readiness'}[kind],
                 'object_id':value['id'],'actor_id':actor_id,'actor':actor,'action':action,'reason':reason,
                 'operation_id':str(operation_id),'recording_mode':'manual','occurred_at':value.get('occurred_at'),
                 'snapshot':value}
        db.execute('INSERT INTO manufacturing_control_events(id,project_id,object_type,object_id,body) VALUES (?,?,?,?,?)',
                   (event['id'],event['project_id'],event['object_type'],value['id'],_json(event)))

    def transact(self, request, actor_id, actor, kind, scope, handler):
        with self._connection(write=True) as db:
            payload = _json(request.model_dump(mode='json',exclude={'operation_id'}))
            operation = str(request.operation_id)
            row = db.execute('SELECT actor_id,kind,scope,payload,response FROM manufacturing_control_operations WHERE operation_id=?',(operation,)).fetchone()
            if row:
                if row[:4] != (actor_id,kind,scope,payload):
                    raise Conflict()
                return json.loads(row[4])
            for table in ('manufacturing_project_operations','task_operations'):
                if db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone() and db.execute(f'SELECT 1 FROM {table} WHERE operation_id=?',(operation,)).fetchone():
                    raise Conflict()
            result = handler(db)
            db.execute('INSERT INTO manufacturing_control_operations VALUES (?,?,?,?,?,?)',
                       (operation,actor_id,kind,scope,payload,_json(result)))
            return result

    def reference(self, db, system_id, *, line_id=None, active=False):
        if system_id is None:
            return
        system = self.object(db,'systems',system_id)
        require(not active or system['active'], 'System is retired')
        require(line_id is None or line_id in system['line_ids'], 'System does not cover this business line')
        return system
