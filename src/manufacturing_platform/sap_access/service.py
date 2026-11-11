"""Native SAP diagnostic and contract service, separate from mock business state."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from time import monotonic
from uuid import uuid4

from ..sap_connection import load_sap_connection_config
from .contracts import parse_wsdl, ping_envelope, validate_ping
from .errors import SapAccessError
from .registry import INTERFACES
from .store import SapAuditStore
from .transport import SoapTransport
from .stock_requirements import FUNCTION, envelope, parse_response


class SapAccessService:
    def __init__(self, config_path, audit_path, *, transport_factory=SoapTransport):
        self.config_path = config_path
        self.audit_path = audit_path
        self.transport_factory = transport_factory

    def _context(self):
        try:
            if (not os.path.isabs(self.audit_path) or not os.path.isabs(self.config_path)
                    or os.path.realpath(self.audit_path) == os.path.realpath(self.config_path)
                    or os.path.realpath(self.audit_path+'.lock') == os.path.realpath(self.config_path)):
                raise ValueError()
            config = load_sap_connection_config(self.config_path)
        except Exception:
            raise SapAccessError('SAP_CONFIGURATION_ERROR') from None
        # Stored only in the private audit file; never projected to API responses.
        binding = hashlib.sha256(json.dumps(asdict(config), sort_keys=True).encode()).hexdigest()
        return config, binding, SapAuditStore(self.audit_path)

    @staticmethod
    def _live(config):
        if not config.enabled:
            raise SapAccessError('SAP_DISABLED')
        if config.version != 2 or config.transport != 'soap_http':
            raise SapAccessError('SAP_CONFIGURATION_ERROR')

    def status(self):
        config, binding, store = self._context()
        records = [e for e in store.read()['events'] if e.get('binding') == binding and e.get('operation') == 'ping']
        latest = records[-1] if records else None
        return {**config.summary(), 'authentication_verified': bool(latest and latest['status'] == 'success'),
                'last_ping_at': latest['timestamp'] if latest else None,
                'business_data_verified': False, 'business_execution_enabled': False,
                'source': 'native_sap', 'audit_retention_events': 1000}

    def interfaces(self):
        config, binding, store = self._context()
        cached = store.read()['contracts']
        return {'source': 'native_sap', 'business_data_verified': False,
                'interfaces': [{'function': fn, **policy,
                    'execution_enabled': policy['execution_enabled'] and config.enabled and config.transport == 'soap_http' and fn in config.allowed_functions,
                    'contract_cached': fn in cached and cached[fn]['binding'] == binding}
                    for fn, policy in INTERFACES.items()]}

    def contract(self, function):
        if function not in INTERFACES:
            raise SapAccessError('SAP_FUNCTION_DENIED', 404)
        _, binding, store = self._context()
        cached = store.read()['contracts'].get(function)
        if not cached or cached['binding'] != binding:
            raise SapAccessError('SAP_CONTRACT_NOT_CACHED', 404)
        return {**cached['descriptor'], 'fetched_at': cached['fetched_at'],
                'business_data_verified': False, 'source': 'native_sap'}

    def _operation(self, operation, function, actor_id, callback):
        config, binding, store = self._context()
        self._live(config)
        event = {'request_id': str(uuid4()), 'operation': operation, 'function': function,
                 'timestamp': datetime.now(timezone.utc).isoformat(), 'status': 'started',
                 'actor_hash': hashlib.sha256(str(actor_id).encode()).hexdigest(), 'binding': binding}
        # Persist intent before I/O; storage failures close the operation.
        store.record(event)
        start = monotonic()
        try:
            result, size, contract = callback(self.transport_factory(config))
        except Exception as exc:
            error = exc if isinstance(exc, SapAccessError) else SapAccessError('SAP_OPERATION_FAILED')
            store.record({**event, 'status': 'failed', 'error_code': error.code,
                          'elapsed_ms': round((monotonic()-start)*1000)})
            raise error from None
        store.record({**event, 'status': 'success', 'response_bytes': size,
                      'contract_digest': contract['digest'] if contract else None,
                      'elapsed_ms': round((monotonic()-start)*1000)}, contract=contract)
        return {**result, 'request_id': event['request_id']}

    def ping(self, actor_id):
        def call(transport):
            contract = parse_wsdl('RFC_PING', transport.fetch_wsdl('RFC_PING'))
            if contract['request_fields'] or contract['response_fields']:
                raise SapAccessError('SAP_INVALID_CONTRACT')
            reply = transport.invoke('RFC_PING', ping_envelope(), contract['soap_action'])
            validate_ping(reply)
            return {'authentication_verified': True, 'business_data_verified': False,
                    'function': 'RFC_PING', 'source': 'native_sap'}, len(reply), contract
        return self._operation('ping', 'RFC_PING', actor_id, call)

    def stock_requirements(self, material, plant, actor_id):
        request = envelope(material, plant)
        config, _, _ = self._context()
        self._live(config)
        if FUNCTION not in config.allowed_functions:
            raise SapAccessError('SAP_FUNCTION_NOT_ALLOWED', 403)
        def call(transport):
            contract = parse_wsdl(FUNCTION, transport.fetch_wsdl(FUNCTION))
            fields = {field['name']: field for field in contract['request_fields']}
            if (fields.get('MATERIAL', {}).get('max_length') != 18
                    or fields.get('PLANT', {}).get('max_length') != 4
                    or any(not fields.get(name, {}).get('table') for name in
                           ('EXTENSIONOUT', 'MRP_IND_LINES', 'MRP_ITEMS', 'MRP_TOTAL_LINES'))):
                raise SapAccessError('SAP_INVALID_CONTRACT')
            try:
                response_fields = {field['name']: field for field in contract['response_fields']}
                item_fields = response_fields['MRP_ITEMS']['fields'][0]['fields']
                return_fields = response_fields['RETURN']['fields']
                response_fields['MRP_LIST']['fields']
                if not item_fields or 'TYPE' not in {field['name'] for field in return_fields}:
                    raise ValueError()
            except (KeyError, IndexError, TypeError, ValueError):
                raise SapAccessError('SAP_INVALID_CONTRACT') from None
            reply = transport.invoke(FUNCTION, request, contract['soap_action'])
            if type(reply) is not bytes or len(reply) > config.max_response_bytes:
                raise SapAccessError('SAP_RESPONSE_TOO_LARGE', 502)
            result = parse_response(reply, contract)
            return {**result, 'function': FUNCTION, 'source': 'native_sap'}, len(reply), contract
        return self._operation('stock_requirements', FUNCTION, actor_id, call)

    def refresh_contracts(self, actor_id):
        successful, failed = [], []
        for function in INTERFACES:
            def call(transport, fn=function):
                payload = transport.fetch_wsdl(fn)
                descriptor = parse_wsdl(fn, payload)
                return {'function': fn}, len(payload), descriptor
            try:
                self._operation('refresh_contract', function, actor_id, call)
                successful.append(function)
            except SapAccessError as exc:
                # Fail closed for configuration/audit errors; ordinary missing
                # contracts are per-function discovery results.
                if exc.code in {'SAP_AUDIT_UNAVAILABLE', 'SAP_CONFIGURATION_ERROR', 'SAP_DISABLED', 'SAP_AUTHENTICATION_FAILED'}:
                    raise
                failed.append({'function': function, 'code': exc.code})
        return {'successful': successful, 'failed': failed, 'business_data_verified': False, 'source': 'native_sap'}
