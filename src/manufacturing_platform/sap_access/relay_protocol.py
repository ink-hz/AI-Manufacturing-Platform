"""Closed, bounded wire format for the loopback read relay."""
import json
import os
import re
import stat
from uuid import UUID
from .production_order import scope as order_scope
from .stock_requirements import envelope
from .errors import SapAccessError

MAX_REQUEST_BYTES = 2048
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
SAFE_CODES = frozenset({'SAP_RELAY_INVALID_REQUEST','SAP_RELAY_UNAUTHORIZED','SAP_RELAY_UNAVAILABLE','SAP_RELAY_BUSY','SAP_RELAY_CONTEXT_MISMATCH','SAP_RELAY_RESPONSE_TOO_LARGE','SAP_CONFIGURATION_ERROR','SAP_DISABLED','SAP_INVALID_QUERY','SAP_FUNCTION_NOT_ALLOWED','SAP_AUDIT_UNAVAILABLE','SAP_AUTHENTICATION_FAILED','SAP_OPERATION_FAILED','SAP_RESPONSE_TOO_LARGE','SAP_INVALID_CONTRACT','SAP_INVALID_RESPONSE','SAP_TRANSPORT_ERROR','SAP_TIMEOUT','SAP_BUSINESS_FAILURE','SAP_RESULT_LIMIT_EXCEEDED','SAP_TLS_ERROR','SAP_CONNECTION_FAILED','SAP_REDIRECT_BLOCKED','SAP_HTTP_ERROR','SAP_INVALID_XML','SAP_UNSAFE_XML','SAP_SOAP_FAULT','SAP_INVALID_REQUEST'})
class RelayProtocolError(ValueError):
    def __init__(self, code='SAP_RELAY_INVALID_REQUEST'):
        self.code=code
        super().__init__(code)
def _reject(*args): raise RelayProtocolError()
def _pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result: _reject()
        result[key]=value
    return result
def strict_json(payload):
    try:return json.loads(payload,object_pairs_hook=_pairs,parse_constant=_reject)
    except (ValueError,UnicodeError,RecursionError):raise RelayProtocolError() from None
def _keys(value,keys):
    if type(value) is not dict or set(value)!=set(keys):_reject()
def _hex(value):return type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None
def _uuid(value):
    try:return type(value) is str and str(UUID(value))==value
    except (ValueError,AttributeError):return False
def validate_context(value):
    _keys(value,('source','fingerprint'));source=value['source']
    _keys(source,('system','origin','fact_role','environment','system_id','client','namespace'))
    if (source['system']!='sap' or source['origin']!='native' or source['fact_role']!='observation'
        or source['environment'] not in ('test','development') or not _hex(source['namespace'])
        or type(source['system_id']) is not str or not re.fullmatch('[A-Z][A-Z0-9]{2}',source['system_id'])
        or type(source['client']) is not str or not re.fullmatch('[0-9]{3}',source['client'])
        or not _hex(value['fingerprint'])):_reject()
    return value
def parse_request(payload):
    if type(payload) is not bytes or len(payload)>MAX_REQUEST_BYTES:_reject()
    value=strict_json(payload);_keys(value,('version','request_id','operation','actor_hash','expected_fingerprint','scope'))
    if type(value['version']) is not int or value['version']!=1 or not _uuid(value['request_id']) or not _hex(value['actor_hash']):_reject()
    op=value['operation'];scope=value['scope']
    if type(op) is not str:_reject()
    if op=='describe':
        _keys(scope,());
        if value['expected_fingerprint'] is not None:_reject()
    elif op in ('production_order','stock_requirements'):
        if not _hex(value['expected_fingerprint']):_reject()
        try:
            if op=='production_order':
                _keys(scope,('number','plant')); number,plant=order_scope(scope['number'],scope['plant']);value['scope']={'number':number,'plant':plant}
            else:
                _keys(scope,('material','plant'));envelope(scope['material'],scope['plant'])
        except SapAccessError:raise RelayProtocolError() from None
    else:_reject()
    return value
def validate_response(value, *, request_id, expected_context=None):
    _keys(value,('version','request_id','context','result','error'))
    if type(value['version']) is not int or value['version']!=1 or not _uuid(value['request_id']) or value['request_id']!=request_id:_reject()
    if value['error'] is None:
        validate_context(value['context'])
        if type(value['result']) is not dict:_reject()
        if expected_context is not None and value['context']!=validate_context(expected_context):_reject()
    else:
        _keys(value['error'],('code',))
        if type(value['error']['code']) is not str or value['error']['code'] not in SAFE_CODES or value['context'] is not None or value['result'] is not None:_reject()
    try:encoded=json.dumps(value,allow_nan=False).encode()
    except (ValueError,TypeError,RecursionError):raise RelayProtocolError() from None
    if len(encoded)>MAX_RESPONSE_BYTES:_reject()
    return value
def _private_bytes(path,max_bytes):
    try:
        if not os.path.isabs(path):_reject()
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid not in (0,os.getuid()) or info.st_mode&0o077 or info.st_size>max_bytes:_reject()
            payload=stream.read(max_bytes+1)
            if len(payload)>max_bytes:_reject()
            return payload
    except (OSError,TypeError):raise RelayProtocolError() from None
def read_private_json(path,max_bytes=65536):
    value=strict_json(_private_bytes(path,max_bytes))
    if type(value) is not dict:_reject()
    return value
def load_token(path):
    try:value=_private_bytes(path,65).decode('ascii').removesuffix('\n')
    except UnicodeError:raise RelayProtocolError() from None
    if not _hex(value):_reject()
    return value
