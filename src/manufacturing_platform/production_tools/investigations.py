"""Private drafts and immutable administrator handoffs of source metadata."""

import hashlib
from datetime import UTC, datetime, timedelta
from functools import wraps
from uuid import UUID, uuid4

from pydantic import ValidationError

from ..workflow.clock import checked_time
from ..workflow.contracts import DomainError
from .contracts import ProductionQuery, is_missing_dimension
from .investigation_models import CreateHandoff, CreateInvestigation, ForkHandoff, UpdateInvestigation
from .investigation_store import InvestigationStore, missing
from .investigation_statistics import capture_impact, scope_filters
from .source import error
from .store import _fingerprint, _json

# Only scalar locating fields survive the observation cache's 24 hour lifetime.
DESCRIPTOR_FIELDS = frozenset({
    'id', 'timestamp', 'time', 'createtime', 'sn', 'csn', 'barcode',
    'stageid', 'stage_id', 'stage', 'softwareid', 'software_id', 'softwarename',
    'softwareversion', 'software_version', 'configid', 'configlogid', 'config_log_id',
    'configversion', 'config_version', 'devicename', 'device', 'orderid', 'order_id',
    'status', 'errorcode', 'error_code', 'projuectid',
    'workstagesid', 'version', 'configlogsid', 'cversion', 'workselectid', 'toolsname', 'state',
})
ALIASES = {
    'stage_id': ('workstagesid', 'stageid', 'stage_id', 'stage'),
    'software_id': ('softwareid', 'software_id'),
    'software_version': ('version', 'softwareversion', 'software_version'),
    'config_log_id': ('configlogsid', 'configlogid', 'config_log_id'),
    'config_version': ('cversion', 'configversion', 'config_version'),
    'device': ('devicename', 'device'), 'error_code': ('errorcode', 'error_code'),
    'order_id': ('orderid', 'order_id'), 'barcode': ('barcode',),
    'sn': ('sn',), 'status': ('status',),
}


def guarded(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except DomainError:
            raise
        except ValidationError:
            raise error('SOURCE_INVALID_QUERY', 422) from None
        except Exception:  # noqa: BLE001 - Never expose storage paths or private connector errors.
            raise DomainError('INVESTIGATION_UNAVAILABLE', 503, 'Investigation storage or source unavailable') from None
    return invoke


def _hash(row):
    return hashlib.sha256(_json(row).encode()).hexdigest()


def _descriptor(row):
    return {key: value for key, value in row.items() if key in DESCRIPTOR_FIELDS and (value is None or type(value) in (str, int, float, bool)) and (not isinstance(value, str) or len(value) <= 200)}


def _time(row):
    value = next((row[key] for key in ('timestamp', 'time', 'createtime') if row.get(key) is not None), None)
    if type(value) is int or (isinstance(value, str) and value.isdecimal()):
        # Native relational timestamps are integer milliseconds; retain exact integer arithmetic.
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=int(value))
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.utcoffset() is not None:
            return parsed.astimezone(UTC)
    return None


class InvestigationService:
    def __init__(self, production_service, *, path, clock, protected_paths=()):
        self.production = production_service
        self.clock = clock
        self.store = InvestigationStore(path, clock=clock, protected_paths=(*protected_paths, *production_service.config.protected_paths, production_service.config.snapshot_path) if production_service.config else protected_paths) if path else None

    def _scope(self, actor, project, *, write=False):
        self.production._authorize(actor)
        if write and actor.read_only:
            raise DomainError('FORBIDDEN', 403, 'Investigation is read-only')
        scope = self.production._scope_for(project)
        if self.store is None:
            raise DomainError('INVESTIGATION_UNAVAILABLE', 503, 'Investigation storage unavailable')
        return scope

    def _get(self, conn, actor, project, identifier, scope, *, kind='draft'):
        return self.store.get(conn, identifier, kind=kind, owner=actor.user_id if kind == 'draft' else None, project=project, fingerprint=_fingerprint(scope), now=checked_time(self.clock))

    def _handoff(self, conn, actor, identifier, *, write=False):
        self.production._authorize(actor)
        if write and actor.read_only:
            raise DomainError('FORBIDDEN', 403, 'Investigation is read-only')
        row = conn.execute("SELECT source_project_id FROM investigations WHERE id=? AND kind='handoff'", (str(identifier),)).fetchone()
        if row is None:
            raise missing()
        scope = self._scope(actor, row[0], write=write)
        return self._get(conn, actor, row[0], identifier, scope, kind='handoff'), scope

    def _check_context(self, context, selection, *, primary=True):
        if selection is None:
            return
        descriptor = selection['descriptor']
        # A retained event must never silently migrate into a contradictory investigation scope.
        for name, aliases in ALIASES.items():
            if name not in context or context[name] is None:
                continue
            if not primary and name in {'sn', 'barcode', 'device', 'status', 'error_code', 'software_version', 'config_log_id', 'config_version'}:
                continue
            actual = next((descriptor[key] for key in aliases if descriptor.get(key) is not None), None)
            if actual is not None and str(actual) != str(context[name]):
                raise error('SOURCE_INVALID_QUERY', 422)
        for field in context.get('missing_fields') or ():
            if not primary and field in {'device', 'error_code', 'software_version', 'config_log_id', 'config_version'}:
                continue
            actual = next((descriptor[key] for key in ALIASES[field] if key in descriptor), None)
            if not is_missing_dimension(field, actual):
                raise error('SOURCE_INVALID_QUERY', 422)
        when = _time(descriptor)
        if primary and when is not None and not datetime.fromisoformat(context['start'].replace('Z', '+00:00')) <= when < datetime.fromisoformat(context['end'].replace('Z', '+00:00')):
            raise error('SOURCE_INVALID_QUERY', 422)

    def _selection(self, actor, project, value, context, *, primary=True, previous=None):
        page = self.production.snapshot(actor, project, value.snapshot_id, offset=value.offset, limit=1)
        if page['source_kind'] not in {'production', 'stopover'} or len(page['items']) != 1:
            raise error('SOURCE_INVALID_QUERY', 422)
        row = page['items'][0]
        if row.get('projuectid') is not None and str(row['projuectid']) != project:
            raise error('SOURCE_INVALID_QUERY', 422)
        filters = ProductionQuery.model_validate(page['filters']).model_dump(mode='json', exclude_none=True)
        if filters['kind'] != page['source_kind']:
            raise error('SOURCE_INVALID_QUERY', 422)
        selected = {
            'selection_id': str(uuid4()), 'snapshot_id': str(value.snapshot_id), 'offset': value.offset,
            'source_kind': page['source_kind'], 'descriptor': _descriptor(row),
            'fingerprint': _hash(row), 'fingerprint_version': 1,
            'captured_at': page['captured_at'], 'filters': filters,
        }
        self._check_context(context, selected, primary=primary)
        if previous and all(selected[key] == previous[key] for key in ('snapshot_id', 'offset', 'fingerprint')):
            return previous
        return selected

    def _check_log_context(self, context, descriptor):
        span = context.get('evidence_range') or context
        log_context = {key: value for key, value in context.items() if key != 'sn'}
        log_context['missing_fields'] = [field for field in context.get('missing_fields') or () if field == 'device']
        log_context.update(start=span['start'], end=span['end'])
        self._check_context(log_context, {'descriptor': descriptor})
        if context.get('candidate_csn') is not None and descriptor.get('csn') != context['candidate_csn']:
            raise error('SOURCE_INVALID_QUERY', 422)

    def _log_scan(self, actor, project, ids, context):
        span = context.get('evidence_range') or context
        query = ProductionQuery(kind='evidence', start=span['start'], end=span['end'], sn=context.get('candidate_csn'), order_id=context.get('order_id'), device=context.get('device'), missing_fields=[field for field in context.get('missing_fields') or () if field == 'device'])
        page = self.production.query(actor, project, query)
        found = {identifier: [] for identifier in ids}
        # Inspect every retained candidate (at most 1000); duplicate IDs never choose a row implicitly.
        for _ in range(11):
            for offset, row in enumerate(page['items']):
                identifier = str(row.get('id', ''))
                if identifier in found:
                    if row.get('projuectid') is not None and str(row['projuectid']) != project:
                        raise error('SOURCE_INVALID_QUERY', 422)
                    descriptor = _descriptor(row)
                    self._check_log_context(context, descriptor)
                    metadata = {'source_log_id': identifier, 'descriptor': descriptor, 'fingerprint': _hash(descriptor), 'fingerprint_version': 1, 'captured_at': page['captured_at'], 'filters': query.model_dump(mode='json', exclude_none=True), 'match_basis': 'project_time_and_explicit_csn' if context.get('candidate_csn') else 'project_and_time', 'state': 'unverified'}
                    candidate = {'snapshot_id': page['snapshot_id'], 'offset': page['offset'] + offset, 'row': descriptor}
                    found[identifier].append((metadata, candidate))
            if not page['has_more']:
                break
            page = self.production.snapshot(actor, project, UUID(page['snapshot_id']), offset=page['offset'] + len(page['items']), limit=100)
        return found, page['complete'] and not page['has_more']

    def _logs(self, actor, project, ids, context):
        if not ids:
            return []
        found, _ = self._log_scan(actor, project, ids, context)
        if any(len(found[identifier]) != 1 for identifier in ids):
            raise error('SOURCE_INVALID_QUERY', 422)
        return [found[identifier][0][0] for identifier in ids]

    def _new(self, actor, scope, body, *, origin=None):
        context = body.context.model_dump(mode='json', exclude_none=True)
        primary = self._selection(actor, scope.source_project_id, body.primary, context) if body.primary else None
        comparison = self._selection(actor, scope.source_project_id, body.comparison, context, primary=False) if body.comparison else None
        if comparison and not primary:
            raise error('SOURCE_INVALID_QUERY', 422)
        logs = self._logs(actor, scope.source_project_id, body.logs, context)
        impact = capture_impact(self.production, actor, scope, context, clock=self.clock)
        now = checked_time(self.clock)
        return {'id': str(uuid4()), 'source_namespace': scope.source_namespace, 'source_project_id': scope.source_project_id, 'owner_id': str(actor.user_id), 'version': 1, 'created_at': now.isoformat(), 'updated_at': now.isoformat(), 'expires_at': (now + timedelta(days=30)).isoformat(), 'origin_handoff_id': origin, 'context': context, 'primary': primary, 'comparison': comparison, 'logs': logs, 'note': body.note, 'impact': impact}

    @guarded
    def create(self, actor, project, body):
        scope = self._scope(actor, project, write=True)
        body = CreateInvestigation.model_validate(body)
        payload = self._new(actor, scope, body)
        self.production._reauthorize(actor, project, scope)
        self._scope(actor, project, write=True)
        with self.store.transaction(write=True) as conn:
            self.store.put(conn, payload, kind='draft', fingerprint=_fingerprint(scope), insert=True)
        return payload

    @guarded
    def get(self, actor, project, identifier):
        scope = self._scope(actor, project)
        with self.store.transaction() as conn:
            return self._get(conn, actor, project, identifier, scope)

    @guarded
    def list(self, actor, project):
        scope = self._scope(actor, project)
        with self.store.transaction() as conn:
            rows = conn.execute("SELECT id FROM investigations WHERE kind='draft' AND owner_id=? AND source_project_id=? AND scope_fingerprint=? AND expires_at>? ORDER BY updated_at DESC,id LIMIT 101", (str(actor.user_id), project, _fingerprint(scope), checked_time(self.clock).isoformat())).fetchall()
            return {'items': [self._get(conn, actor, project, row[0], scope) for row in rows[:100]], 'has_more': len(rows) > 100}

    @guarded
    def update(self, actor, project, identifier, body):
        scope = self._scope(actor, project, write=True)
        body = UpdateInvestigation.model_validate(body)
        # Do source work outside the write lock, then check the latest revision again inside it.
        old = self.get(actor, project, identifier)
        self._version(old, body.expected_version)
        changed = body.model_fields_set
        context = body.context.model_dump(mode='json', exclude_none=True) if 'context' in changed else old['context']
        primary = old['primary']
        if 'primary' in changed:
            primary = self._selection(actor, project, body.primary, context, previous=old['primary']) if body.primary else None
        replaced = (primary or {}).get('selection_id') != (old['primary'] or {}).get('selection_id')
        if replaced and (body.comparison is not None or body.logs):
            raise error('SOURCE_INVALID_QUERY', 422)
        comparison = None if replaced else old['comparison']
        logs = [] if replaced else old['logs']
        if 'comparison' in changed:
            comparison = self._selection(actor, project, body.comparison, context, primary=False, previous=old['comparison']) if body.comparison else None
        if comparison and not primary:
            raise error('SOURCE_INVALID_QUERY', 422)
        if 'logs' in changed:
            logs = self._logs(actor, project, body.logs, context)
        self._check_context(context, primary)
        self._check_context(context, comparison, primary=False)
        if 'context' in changed and logs and any(log['filters'].get(query_key) != context.get(context_key) for log in logs for query_key, context_key in (('sn', 'candidate_csn'), ('order_id', 'order_id'))):
            raise error('SOURCE_INVALID_QUERY', 422)
        if 'context' in changed:
            span = context.get('evidence_range') or context
            for log in logs:
                self._check_log_context(context, log['descriptor'])
        impact = capture_impact(self.production, actor, scope, context, clock=self.clock) if scope_filters(context) != scope_filters(old['context']) else old.get('impact')
        now = checked_time(self.clock)
        result = old | {'impact': impact, 'context': context, 'primary': primary, 'comparison': comparison, 'logs': logs, 'note': body.note if 'note' in changed else old['note'], 'version': old['version'] + 1, 'updated_at': now.isoformat(), 'expires_at': (now + timedelta(days=30)).isoformat()}
        self._scope(actor, project, write=True)
        self.production._reauthorize(actor, project, scope)
        with self.store.transaction(write=True) as conn:
            self._version(self._get(conn, actor, project, identifier, scope), body.expected_version)
            self.store.put(conn, result, kind='draft', fingerprint=_fingerprint(scope))
        return result

    @staticmethod
    def _version(payload, expected):
        if payload['version'] != expected:
            raise DomainError('INVESTIGATION_CONFLICT', 409, 'Investigation changed; reload the latest version')

    @guarded
    def create_handoff(self, actor, project, identifier, body):
        scope = self._scope(actor, project, write=True)
        body = CreateHandoff.model_validate(body)
        with self.store.transaction(write=True) as conn:
            draft = self._get(conn, actor, project, identifier, scope)
            self._version(draft, body.expected_version)
            now = checked_time(self.clock)
            payload = draft | {'id': str(uuid4()), 'investigation_id': draft['id'], 'created_at': now.isoformat(), 'expires_at': (now + timedelta(days=30)).isoformat()}
            self._scope(actor, project, write=True)
            self.production._reauthorize(actor, project, scope)
            self.store.put(conn, payload, kind='handoff', fingerprint=_fingerprint(scope), insert=True)
        return payload

    @guarded
    def get_handoff(self, actor, identifier):
        self.production._authorize(actor)
        if self.store is None:
            raise DomainError('INVESTIGATION_UNAVAILABLE', 503, 'Investigation storage unavailable')
        with self.store.transaction() as conn:
            return self._handoff(conn, actor, identifier)[0]

    @guarded
    def fork(self, actor, identifier, body):
        self.production._authorize(actor)
        if actor.read_only:
            raise DomainError('FORBIDDEN', 403, 'Investigation is read-only')
        ForkHandoff.model_validate(body)
        if self.store is None:
            raise DomainError('INVESTIGATION_UNAVAILABLE', 503, 'Investigation storage unavailable')
        with self.store.transaction(write=True) as conn:
            handoff, scope = self._handoff(conn, actor, identifier, write=True)
            now = checked_time(self.clock)
            draft = {key: value for key, value in handoff.items() if key != 'investigation_id'} | {'id': str(uuid4()), 'owner_id': str(actor.user_id), 'version': 1, 'created_at': now.isoformat(), 'updated_at': now.isoformat(), 'expires_at': (now + timedelta(days=30)).isoformat(), 'origin_handoff_id': handoff['id'], 'origin_handoff_version': handoff['version']}
            self.store.put(conn, draft, kind='draft', fingerprint=_fingerprint(scope), insert=True)
        return draft

    def _resolve_selection(self, actor, project, selected):
        if selected is None:
            return None
        descriptor = selected['descriptor']
        result = {'descriptor': descriptor, 'candidates': [], 'complete': False}
        try:
            try:
                page = self.production.snapshot(actor, project, UUID(selected['snapshot_id']), offset=selected['offset'], limit=1)
                rows = page['items']
                if len(rows) == 1 and _hash(rows[0]) == selected['fingerprint']:
                    return result | {'state': 'verified', 'candidates': [{'snapshot_id': page['snapshot_id'], 'offset': selected['offset'], 'row': rows[0]}], 'complete': True}
            except DomainError as exc:
                if exc.status not in {404, 410}:
                    raise
            when = _time(descriptor)
            sn = descriptor.get('sn')
            if when is None or not isinstance(sn, str):
                return result | {'state': 'partial', 'error': 'EVENT_LOCATOR_INCOMPLETE'}
            # A microsecond interval isolates the source timestamp; never scan only the original window's first page.
            query = ProductionQuery(kind=selected['source_kind'], start=when, end=when + timedelta(microseconds=1), sn=sn, missing_fields=selected.get('filters', {}).get('missing_fields'))
            page = self.production.query(actor, project, query)
            candidates = []
            offset = 0
            for _ in range(11):
                for index, row in enumerate(page['items']):
                    if _time(row) == when and row.get('sn') == sn:
                        candidates.append({'snapshot_id': page['snapshot_id'], 'offset': offset + index, 'row': row})
                if not page['has_more']:
                    break
                offset += len(page['items'])
                page = self.production.snapshot(actor, project, UUID(page['snapshot_id']), offset=offset, limit=100)
            complete = page['complete'] and not page['has_more']
            state = 'partial' if not complete else 'not_found' if not candidates else 'ambiguous' if len(candidates) > 1 else 'verified' if _hash(candidates[0]['row']) == selected['fingerprint'] else 'changed'
            return result | {'state': state, 'candidates': candidates, 'complete': complete}
        except DomainError as exc:
            if exc.status == 403:
                raise
            return result | {'state': 'unavailable', 'error': 'SOURCE_UNAVAILABLE'}
        except Exception:  # noqa: BLE001 - Individual missing evidence does not hide stored metadata.
            return result | {'state': 'unavailable', 'error': 'SOURCE_UNAVAILABLE'}

    @guarded
    def resolve(self, actor, project, identifier):
        return self._resolve(actor, self.get(actor, project, identifier), kind='draft')

    @guarded
    def resolve_handoff(self, actor, identifier):
        return self._resolve(actor, self.get_handoff(actor, identifier), kind='handoff')

    def _resolve(self, actor, payload, *, kind):
        project = payload['source_project_id']
        scope = self._scope(actor, project)
        logs = []
        for saved in payload['logs']:
            resolved = {'source_log_id': saved['source_log_id'], 'descriptor': saved['descriptor'], 'candidates': [], 'complete': False}
            try:
                found, complete = self._log_scan(actor, project, [saved['source_log_id']], payload['context'])
                matches = found[saved['source_log_id']]
                state = 'partial' if not complete else 'not_found' if not matches else 'ambiguous' if len(matches) > 1 else 'verified' if matches[0][0]['fingerprint'] == saved['fingerprint'] else 'changed'
                resolved.update(state=state, complete=complete, candidates=[match[1] for match in matches])
            except DomainError as exc:
                if exc.status == 403:
                    raise
                resolved.update(state='unavailable', error='SOURCE_UNAVAILABLE')
            logs.append(resolved)
        # Bind to this exact payload; a concurrent draft update must not relabel resolved evidence.
        binding = {
            'kind': kind, 'id': payload['id'], 'version': payload['version'],
            'primary_selection_id': (payload['primary'] or {}).get('selection_id'),
            'comparison_selection_id': (payload['comparison'] or {}).get('selection_id'),
        }
        result = {'binding': binding, 'primary': self._resolve_selection(actor, project, payload['primary']), 'comparison': self._resolve_selection(actor, project, payload['comparison']), 'logs': logs, 'captured_at': checked_time(self.clock).isoformat()}
        self.production._reauthorize(actor, project, scope)
        return result
