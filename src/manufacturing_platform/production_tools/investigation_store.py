"""Independent metadata store. Never extends or alters observation snapshots."""

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from ..workflow.contracts import DomainError
from .store import _json, validate_snapshot_path


def missing():
    return DomainError('NOT_FOUND', 404, 'Investigation not found')


class InvestigationStore:
    def __init__(self, path, *, protected_paths=()):
        self.path = path
        self.protected_paths = tuple(protected_paths)
        validate_snapshot_path(path, self.protected_paths)
        fresh = False
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
            fresh = True
        with sqlite3.connect(path) as conn:
            if fresh:
                conn.executescript('''
                    CREATE TABLE metadata(version INTEGER NOT NULL);
                    INSERT INTO metadata VALUES(1);
                    CREATE TABLE investigations(id TEXT PRIMARY KEY, kind TEXT NOT NULL, owner_id TEXT NOT NULL, scope_fingerprint TEXT NOT NULL, source_project_id TEXT NOT NULL, version INTEGER NOT NULL, expires_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL);
                    CREATE INDEX investigations_owner ON investigations(kind, owner_id, source_project_id, updated_at);
                ''')
            self._validate(conn)
        os.chmod(path, 0o600)

    def _validate(self, conn):
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        columns = tuple(row[1] for row in conn.execute('PRAGMA table_info(investigations)'))
        if tables != {'metadata', 'investigations'} or columns != ('id', 'kind', 'owner_id', 'scope_fingerprint', 'source_project_id', 'version', 'expires_at', 'updated_at', 'payload_json', 'payload_sha256') or conn.execute('SELECT version FROM metadata').fetchall() != [(1,)]:
            raise ValueError('unrecognized investigation database')

    @contextmanager
    def transaction(self, *, write=False):
        validate_snapshot_path(self.path, self.protected_paths)
        conn = sqlite3.connect(f'{Path(self.path).as_uri()}?mode=rw', uri=True, isolation_level=None, timeout=5)
        try:
            conn.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            self._validate(conn)
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get(self, conn, identifier, *, kind, owner, project, fingerprint, now):
        row = conn.execute('SELECT owner_id,scope_fingerprint,source_project_id,expires_at,payload_json,payload_sha256 FROM investigations WHERE id=? AND kind=?', (str(identifier), kind)).fetchone()
        if row is None or (owner is not None and row[0] != str(owner)) or row[1] != fingerprint or (project is not None and row[2] != project):
            raise missing()
        if row[3] <= now.isoformat():
            raise DomainError('INVESTIGATION_EXPIRED', 410, 'Investigation expired')
        if hashlib.sha256(row[4].encode()).hexdigest() != row[5]:
            raise ValueError('invalid investigation metadata')
        return json.loads(row[4])

    def put(self, conn, payload, *, kind, fingerprint, insert=False):
        encoded = _json(payload)
        values = (kind, payload['owner_id'], fingerprint, payload['source_project_id'], payload['version'], payload['expires_at'], payload.get('updated_at', payload['created_at']), encoded, hashlib.sha256(encoded.encode()).hexdigest(), payload['id'])
        if insert:
            conn.execute('INSERT INTO investigations(kind,owner_id,scope_fingerprint,source_project_id,version,expires_at,updated_at,payload_json,payload_sha256,id) VALUES(?,?,?,?,?,?,?,?,?,?)', values)
        else:
            conn.execute('UPDATE investigations SET kind=?,owner_id=?,scope_fingerprint=?,source_project_id=?,version=?,expires_at=?,updated_at=?,payload_json=?,payload_sha256=? WHERE id=?', values)
