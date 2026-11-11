"""Strict MES audit metadata over the existing secure atomic persistence layer."""
from datetime import datetime
import re

from ..sap_access.errors import SapAccessError
from ..sap_access.store import SapAuditStore
from .errors import MesAccessError
from .registry import INTERFACES

BASE_FIELDS = {'request_id', 'operation', 'function', 'timestamp', 'status', 'actor_hash', 'binding'}
EXTRA_FIELDS = {'elapsed_ms', 'error_code', 'response_bytes', 'row_count'}


def _validate_event(event):
    if type(event) is not dict or not BASE_FIELDS <= set(event) or set(event) - BASE_FIELDS - EXTRA_FIELDS:
        raise ValueError()
    for key in ('actor_hash', 'binding'):
        if type(event[key]) is not str or not re.fullmatch('[a-f0-9]{64}', event[key]):
            raise ValueError()
    if type(event['request_id']) is not str or not re.fullmatch('[a-f0-9-]{36}', event['request_id']):
        raise ValueError()
    if type(event['timestamp']) is not str or len(event['timestamp']) > 40 or datetime.fromisoformat(event['timestamp']).tzinfo is None:
        raise ValueError()
    if event['operation'] not in {'diagnose', 'query'} or event['status'] not in {'started', 'success', 'failed'}:
        raise ValueError()
    if ((event['operation'] == 'diagnose' and event['function'] is not None)
            or event['operation'] == 'query' and event['function'] not in INTERFACES):
        raise ValueError()
    for key in ('elapsed_ms', 'response_bytes'):
        if key in event and (type(event[key]) is not int or not 0 <= event[key] <= 2**31 - 1):
            raise ValueError()
    if 'row_count' in event and (event['operation'] != 'query' or event['status'] != 'success'
            or type(event['row_count']) is not int or not 0 <= event['row_count'] <= 5):
        raise ValueError()
    if 'error_code' in event and (type(event['error_code']) is not str or not re.fullmatch('MES_[A-Z0-9_]{1,56}', event['error_code'])):
        raise ValueError()


class _MetadataStore(SapAuditStore):
    def _read(self):
        data = super()._read()
        # MES never caches contracts or business records. Validate existing
        # metadata under the same file lock used for the eventual replacement.
        try:
            if data['contracts'] or len(data['events']) > 1000:
                raise ValueError()
            for event in data['events']:
                _validate_event(event)
        except Exception:
            raise SapAccessError('SAP_AUDIT_UNAVAILABLE') from None
        return data


class MesAuditStore:
    def __init__(self, path):
        self._store = _MetadataStore(path)

    def read(self):
        try:
            return {'events': self._store.read()['events']}
        except Exception:
            raise MesAccessError('MES_AUDIT_UNAVAILABLE') from None

    def record(self, event):
        try:
            _validate_event(event)
            self._store.record(event)
        except Exception:
            raise MesAccessError('MES_AUDIT_UNAVAILABLE') from None
