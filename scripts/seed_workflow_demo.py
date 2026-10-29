#!/usr/bin/env python3
"""Explicit maintenance import into an existing demo workflow dataset only."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from uuid import UUID, NAMESPACE_URL, uuid5

from manufacturing_platform.workflow.contracts import Actor, GrantChange, ObjectKind, ProjectCreate
from manufacturing_platform.workflow.service import WorkflowService, digest
from manufacturing_platform.workflow.store import WorkflowStore

VERSION = 'realistic-manufacturing-demo-v1'
ROLES = ['project_owner', 'engineering', 'planner', 'supply', 'production', 'quality', 'warehouse']
QUALIFICATIONS = {'engineering': ['readiness_verification'], 'quality': ['inspection', 'disposition', 'quality_release']}


def plain(value):
    return value.model_dump(mode='json') if hasattr(value, 'model_dump') else value


class Importer:
    def __init__(self, *, workflow_db, authority_db, dataset, owner_ids, manifest):
        if dataset.get('mode') != 'demo':
            raise ValueError('Importer accepts demo mode only')
        self.path = Path(manifest)
        paths = [Path(workflow_db), Path(authority_db), self.path]
        if any(not p.is_absolute() for p in paths) or len({p.resolve() for p in paths}) != 3:
            raise ValueError('Use distinct absolute database and manifest paths')
        owners = sorted({str(UUID(v)) for v in owner_ids})
        if not owners:
            raise ValueError('An explicitly verified owner UUID is required')
        self.config = dict(version=VERSION, workflow_db=str(paths[0].resolve()), authority_db=str(paths[1].resolve()), dataset=dataset, owner_ids=owners)
        self.namespace = uuid5(NAMESPACE_URL, VERSION + ':' + dataset['id'])
        self.actors = {name: Actor(user_id=self.ident('actor/' + name), display_name='【模拟维护】' + name,
            read_only=False, configuration_admin=name == 'maintenance') for name in ['maintenance', *ROLES[1:]]}
        actor_ids = {str(a.user_id) for a in self.actors.values()}
        if actor_ids.intersection(owners):
            raise ValueError('Owner UUID must not be a synthetic maintenance identity')
        known = actor_ids | set(owners)
        self.store = WorkflowStore(workflow_db, authority_db, dataset)
        self.service = WorkflowService(self.store, lambda uid: str(uid) in known,
            resolve_subject_profiles=lambda ids: [dict(user_id=str(uid), display_name=next((a.display_name for a in self.actors.values() if a.user_id == uid), '指定项目负责人')) for uid in ids if str(uid) in known])
        self.manifest = None

    def ident(self, key):
        return str(uuid5(self.namespace, key))

    def checkpoint(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix='.' + self.path.name, dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(self.manifest, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def source(self, key, kind):
        times = self.manifest.setdefault('source_times', {})
        if key not in times:
            times[key] = datetime.now(UTC).isoformat()
            self.checkpoint()
        at = times[key]
        return dict(system='DEMO-模拟业务凭证', object_type=kind, external_id='DEMO-' + self.ident('source/' + key),
            version=1, mode='manual', occurred_at=at, collected_at=at, cutoff=at,
            evidence='【模拟】虚构业务凭证，仅供工作台演示；非真实客户、ERP或工厂签署')

    def detail(self, pid):
        return plain(self.service.detail(self.actors['maintenance'], UUID(pid), include_progress=False))

    def obj(self, pid, kind, oid):
        return plain(self.service.object_detail(self.actors['maintenance'], UUID(pid), ObjectKind(kind), UUID(oid)))['value']

    def objects(self, pid, kind):
        return [self.obj(pid, kind, str(v.id)) for v in self.service.objects(self.actors['maintenance'], UUID(pid), ObjectKind(kind), limit=200).items]

    def step(self, key, kind, payload, actor='maintenance', pid=None, target=None):
        intent = dict(kind=kind, actor=actor, project_id=pid, target=target, payload=payload)
        prior = self.manifest['steps'].get(key)
        if prior:
            # Replay the saved version, never silently rebase an existing intent.
            candidate = {**intent, 'payload': {**payload}}
            if 'expected_version' in prior['payload']:
                candidate['payload']['expected_version'] = prior['payload']['expected_version']
            if any(candidate[k] != prior[k] for k in intent):
                raise ValueError('Incomplete recovery intent conflict: ' + key)
            if 'result' in prior:
                return prior['result']
            intent = prior
        else:
            if pid:
                current = self.detail(pid)['version']
                expected = self.manifest['project_versions'].get(pid)
                if expected is not None and current != expected:
                    raise ValueError('Incomplete recovery conflict: project edited outside importer: ' + pid)
                payload['expected_version'] = current
            self.manifest['steps'][key] = intent
            self.checkpoint()  # durable intent before any business mutation
        who = self.actors[actor]
        body = intent['payload']
        if kind == 'project':
            result = self.service.create_project(who, ProjectCreate.model_validate(body))
        elif kind == 'grant':
            result = self.service.change_grant(who, UUID(pid), UUID(target), GrantChange.model_validate(body))
        elif kind == 'command':
            result = self.service.execute(who, UUID(pid), body)
        elif kind in {'receive', 'inspect'}:
            result = self.authority_step(kind, body)
        else:
            raise ValueError('Unknown intent kind')
        result = plain(result)
        if kind == 'project':
            self.manifest['project_versions'][result['id']] = result['version']
        elif kind in {'command', 'grant'}:
            # Preserve the immutable commit version; a later user edit must conflict.
            self.manifest['project_versions'][pid] = self.committed_version(result, body, actor, pid)
        intent['result'] = result
        self.checkpoint()
        return result

    def committed_version(self, result, body, actor, pid):
        version = result['project_version']
        if body.get('action') not in {'source.pull', 'exchange.dispatch', 'exchange.query'}:
            return version
        # The outbox commits intent and apply separately. Bind the immutable second
        # commit to this intent; live current_project_version may include user edits.
        with sqlite3.connect('file:' + self.config['workflow_db'] + '?mode=ro', uri=True) as db:
            rows = db.execute("SELECT typed_payload FROM audit_events WHERE project_id=? AND actor_id=? AND action='exchange.apply' AND json_extract(typed_payload,'$.intent_operation_id')=?",
                (pid, str(self.actors[actor].user_id), body['operation_id'])).fetchall()
        if len(rows) != 1 or json.loads(rows[0][0]) != dict(exchange_id=result['exchange_id'], intent_operation_id=body['operation_id'], expected_version=version, action='exchange.apply'):
            raise ValueError('Incomplete exchange recovery requires explicit reconciliation: ' + body['operation_id'])
        if self.obj(pid, 'exchange', result['exchange_id'])['phase'] != 'accepted':
            raise ValueError('Exchange is not accepted; explicit reconciliation required: ' + body['operation_id'])
        return version + 1

    def authority_step(self, kind, body):
        adapter = self.service.exchange_service.adapter
        source_type = 'receipt' if kind == 'receive' else 'iqc'
        records = [plain(r) for r in adapter.snapshot('erp', source_type).records]
        old = next((r for r in records if r['source']['external_id'] == body['external_id']), None)
        if old:
            aliases = {'lot_id': 'material_lot_id'}
            for key in ('project_id', 'commitment_id', 'lot_id', 'quantity', 'unit', 'receipt_external_id', 'accepted', 'rejected', 'external_actor', 'signature'):
                if key in body and str(old.get(aliases.get(key, key))) != str(body[key]):
                    raise ValueError('Authority recovery source conflict: ' + body['external_id'])
            return old
        return getattr(adapter, kind)(**body)

    def command(self, key, pid, action, actor='maintenance', **fields):
        payload = dict(operation_id=self.ident('operation/' + key), expected_version=1, action=action, **fields)
        return self.step(key, 'command', payload, actor, pid)

    def grant(self, key, pid, target, roles, qualifications=()):
        return self.step(key, 'grant', dict(operation_id=self.ident('operation/' + key), expected_version=1,
            scope=dict(kind='project', project_id=pid), roles=roles, qualifications=list(qualifications), active=True,
            evidence='【模拟】仅新增演示项目的显式角色授权；真实用户不授予质量资格'), pid=pid, target=target)

    def verify(self):
        # Source events are immutable receipts; verification never reconstructs missing evidence.
        authority_sources = {kind: {r.source.external_id: plain(r) for r in self.service.exchange_service.adapter.snapshot('erp', kind).records} for kind in ['receipt', 'iqc']}
        # Read-only operation receipts establish provenance without replaying commands.
        with sqlite3.connect('file:' + self.config['workflow_db'] + '?mode=ro', uri=True) as db:
            for key, step in self.manifest['steps'].items():
                if 'result' not in step:
                    raise ValueError('Incomplete manifest: ' + key)
                if step['kind'] in {'receive', 'inspect'}:
                    kind = 'receipt' if step['kind'] == 'receive' else 'iqc'
                    if authority_sources[kind].get(step['payload']['external_id']) != step['result']:
                        raise ValueError('Authority provenance mismatch: ' + key)
                    continue
                payload = step['payload']
                if step['kind'] == 'project':
                    canonical = {'action': 'project.create', **plain(ProjectCreate.model_validate(payload))}
                elif step['kind'] == 'grant':
                    canonical = {'action': 'grant.change', 'project_id': step['project_id'], 'user_id': step['target'], **plain(GrantChange.model_validate(payload))}
                else:
                    canonical = {'project_id': step['project_id'], **plain(self.service.command_registry.parse(payload))}
                row = db.execute('SELECT payload_hash FROM operations WHERE dataset=? AND actor_id=? AND operation_id=?',
                    (self.config['dataset']['id'], str(self.actors[step['actor']].user_id), payload['operation_id'])).fetchone()
                if not row or row[0] != digest(canonical):
                    raise ValueError('Operation provenance mismatch: ' + key)
        projects = []
        for entry in self.manifest['projects']:
            detail = self.detail(entry['id'])
            # Require owner visibility, but preserve intentional subsequent grant/role edits.
            for owner in self.config['owner_ids']:
                self.service.detail(Actor(user_id=owner, display_name='指定项目负责人', read_only=False, configuration_admin=False), UUID(entry['id']), include_progress=False)
            counts = {kind: self.service.objects(self.actors['maintenance'], UUID(entry['id']), ObjectKind(kind), limit=1).total
                for kind in ['demand', 'order_line', 'revision', 'work_order', 'plan', 'requirement', 'material_lot', 'commitment', 'unit', 'receipt', 'reservation', 'release', 'test', 'nonconformance', 'rework', 'shipment', 'rma', 'capa']}
            projects.append({**entry, 'name': detail['name'], 'line_id': detail['line_id'], 'version': detail['version'], 'summary': detail['summary'], 'counts': counts})
        return dict(status='complete', importer_version=VERSION, dataset=self.config['dataset'], projects=projects,
            steps=len(self.manifest['steps']), manifest=str(self.path), simulated=True)

    def run(self, verify_only=False):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_fd = os.open(str(self.path) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(lock_fd, 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.path.exists():
                if not all(Path(self.config[k]).is_file() for k in ['workflow_db', 'authority_db']):
                    raise ValueError('Manifest database pair is missing; restore backup before recovery')
                self.manifest = json.loads(self.path.read_text())
                if self.manifest['config'] != self.config:
                    raise ValueError('Manifest configuration mismatch')
                if self.path.stat().st_mode & 0o077:
                    raise ValueError('Manifest must be private (0600)')
            else:
                if verify_only:
                    raise ValueError('Verification requires existing manifest')
                # Validate both configured stores before creating any business data.
                with self.store.transaction():
                    pass
                self.service.exchange_service.adapter.snapshot('erp', 'receipt')
                # Global admin visibility is not importer ownership. Preserve even
                # revoked namespace responsibility as evidence of a lost manifest.
                with self.store.transaction() as db:
                    namespace_exists = db.execute(
                        'SELECT 1 FROM project_grants WHERE user_id=? LIMIT 1',
                        (str(self.actors['maintenance'].user_id),),
                    ).fetchone() is not None
                if namespace_exists:
                    raise ValueError('Existing demo namespace requires its original manifest')
                self.manifest = dict(config=self.config, started_at=datetime.now(UTC).isoformat(), steps={}, project_versions={}, projects=[], complete=False)
                self.checkpoint()
            if self.manifest['complete']:
                return self.verify()
            if verify_only:
                raise ValueError('Incomplete manifest; resume import explicitly')
            try:
                from workflow_demo.portfolio import populate
                populate(self)
                result = self.verify()
                self.manifest['complete'] = True
                self.checkpoint()
                return result
            except Exception as exc:
                # Preserve the very first failure without altering committed domain facts.
                if 'first_failure' not in self.manifest:
                    self.manifest['first_failure'] = dict(type=type(exc).__name__, message=str(exc), at=datetime.now(UTC).isoformat())
                    self.checkpoint()
                raise


def run(**config):
    verify_only = config.pop('verify_only', False)
    return Importer(**config).run(verify_only=verify_only)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workflow-db', 'authority-db', 'dataset-id', 'dataset-label', 'manifest']:
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--owner-id', action='append', required=True)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    try:
        result = run(workflow_db=args.workflow_db, authority_db=args.authority_db,
            dataset=dict(id=args.dataset_id, mode='demo', label=args.dataset_label), owner_ids=args.owner_id,
            manifest=args.manifest, verify_only=args.verify_only)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps(dict(status='failed', error=type(exc).__name__, message=str(exc)), ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
