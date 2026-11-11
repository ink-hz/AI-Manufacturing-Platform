"""Audited, per-operation native MES access; business records stay in memory."""
from datetime import datetime, timezone
import hashlib
import os
from time import monotonic
from uuid import uuid4

from ..mes_connection import load_mes_connection_config
from .errors import MesAccessError
from .parsing import parse_query_response
from .registry import INTERFACES, prepare_query
from .store import MesAuditStore
from .transport import SessionTransport


class MesAccessService:
    def __init__(self, config_path, audit_path, *, transport_factory=SessionTransport):
        self.config_path = config_path
        self.audit_path = audit_path
        self.transport_factory = transport_factory

    def _context(self):
        try:
            if (not isinstance(self.config_path, str) or not isinstance(self.audit_path, str)
                    or not os.path.isabs(self.config_path) or not os.path.isabs(self.audit_path)
                    or os.path.realpath(self.config_path) in {
                        os.path.realpath(self.audit_path), os.path.realpath(self.audit_path + '.lock')}):
                raise ValueError()
            config = load_mes_connection_config(self.config_path)
        except Exception:
            raise MesAccessError('MES_CONFIGURATION_ERROR') from None
        return config, config.fingerprint(), MesAuditStore(self.audit_path)

    @staticmethod
    def _live(config):
        if not config.enabled:
            raise MesAccessError('MES_DISABLED')
        if config.version != 2 or config.read_only is not True:
            raise MesAccessError('MES_CONFIGURATION_ERROR')

    @staticmethod
    def _evidence(config, binding, store):
        return [event for event in store.read()['events'] if event['binding'] == binding] if config.enabled else []

    def status(self):
        config, binding, store = self._context()
        events = self._evidence(config, binding, store)
        latest = events[-1] if events else None
        queries = [event for event in events if event['operation'] == 'query']
        query = queries[-1] if queries else None
        return {**config.summary(), 'source': 'native_mes',
                'authentication_verified': bool(latest and latest['status'] == 'success'),
                'business_query_succeeded': bool(query and query['status'] == 'success'),
                'business_data_verified': False, 'business_reconciled': False,
                'last_operation_at': latest['timestamp'] if latest else None,
                'last_query_at': query['timestamp'] if query else None,
                'audit_retention_events': 1000}

    def interfaces(self):
        config, binding, store = self._context()
        events = self._evidence(config, binding, store)
        entries = []
        for name, spec in INTERFACES.items():
            queries = [event for event in events if event['function'] == name]
            latest = queries[-1] if queries else None
            entries.append({'interface': name, 'label': spec.label, 'path': spec.path,
                'filters': list(spec.filters), 'default_page_size': 1, 'max_page_size': min(5, config.max_rows),
                'required_filters': list(spec.required_filters), 'pagination_mode': spec.pagination_mode,
                'max_page': 1 if spec.pagination_mode == 'bounded_data' else 1_000_000,
                'total_items_known': spec.pagination_mode != 'bounded_data',
                'execution_enabled': bool(config.enabled and config.version == 2 and config.read_only and spec.path in config.allowed_api_paths),
                'business_query_succeeded': bool(latest and latest['status'] == 'success'),
                'business_data_verified': False, 'business_reconciled': False})
        return {'source': 'native_mes', 'interfaces': entries,
                'business_data_verified': False, 'business_reconciled': False}

    def _operation(self, config, binding, store, operation, interface, actor_id, callback):
        event = {'request_id': str(uuid4()), 'operation': operation, 'function': interface,
                 'timestamp': datetime.now(timezone.utc).isoformat(), 'status': 'started',
                 'actor_hash': hashlib.sha256(str(actor_id).encode()).hexdigest(), 'binding': binding}
        # Intent must survive a process crash before transport construction.
        store.record(event)
        started = monotonic()
        transport = None
        try:
            try:
                transport = self.transport_factory(config)
                result = callback(transport)
                size = transport.response_bytes
            finally:
                if transport is not None:
                    transport.close()
        except Exception as exc:
            error = exc if isinstance(exc, MesAccessError) else MesAccessError('MES_OPERATION_FAILED')
            store.record({**event, 'status': 'failed', 'error_code': error.code,
                          'elapsed_ms': round((monotonic() - started) * 1000)})
            raise error from None
        row_metadata = {'row_count': len(result['rows'])} if operation == 'query' else {}
        store.record({**event, **row_metadata, 'status': 'success', 'response_bytes': size,
                      'elapsed_ms': round((monotonic() - started) * 1000)})
        return {**result, 'request_id': event['request_id']}

    def diagnose(self, actor_id):
        config, binding, store = self._context()
        self._live(config)
        def call(transport):
            transport.login()
            return {'source': 'native_mes', 'site_code': config.site_code,
                    'authentication_verified': True, 'business_query_succeeded': False,
                    'business_data_verified': False, 'business_reconciled': False}
        return self._operation(config, binding, store, 'diagnose', None, actor_id, call)

    def query(self, interface, filters=None, page=1, page_size=1, actor_id=None):
        config, binding, store = self._context()
        self._live(config)
        spec, params = prepare_query(config, interface, filters, page, page_size)
        # Freeze caller-owned filters before I/O; a shared service never stores
        # transport/session state or mutable request inputs between operations.
        public_filters = {key: params[key] for key in spec.filters}
        def call(transport):
            payload = transport.query(interface, public_filters, page, page_size)
            if type(payload) is not bytes or len(payload) > config.max_response_bytes:
                raise MesAccessError('MES_RESPONSE_TOO_LARGE', 502)
            result = parse_query_response(interface, payload, page=page, page_size=page_size)
            return {**result, 'interface': interface, 'source': 'native_mes',
                    'authentication_verified': True, 'business_query_succeeded': True,
                    'business_data_verified': False, 'business_reconciled': False}
        return self._operation(config, binding, store, 'query', interface, actor_id, call)
