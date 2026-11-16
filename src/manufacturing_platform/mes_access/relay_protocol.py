"""Closed MES observation relay schema; no arbitrary endpoint or SQL."""
import re
from ..sap_access import relay_protocol as shared
from .source_orders import valid_identity
MAX_REQUEST_BYTES=2048
MAX_RESPONSE_BYTES=2*1024*1024
class RelayProtocolError(ValueError):
    def __init__(self,code='MES_RELAY_INVALID_REQUEST'):
        self.code=code
        super().__init__(code)
def _reject():raise RelayProtocolError()
def _keys(value,keys):
    if type(value) is not dict or set(value)!=set(keys):_reject()
_hex=shared._hex
_uuid=shared._uuid
SAFE_CODES=frozenset('MES_'+c for c in ('RELAY_INVALID_REQUEST','RELAY_INVALID_RESPONSE','RELAY_UNAUTHORIZED','RELAY_UNAVAILABLE','RELAY_BUSY','RELAY_CONTEXT_MISMATCH','RELAY_RESPONSE_TOO_LARGE','CONFIGURATION_ERROR','CONFIGURATION_CHANGED','DISABLED','INVALID_QUERY','INTERFACE_DENIED','AUDIT_UNAVAILABLE','AUTHENTICATION_FAILED','RESPONSE_TOO_LARGE','INVALID_RESPONSE','TIMEOUT','BUSINESS_FAILURE','SESSION_EXPIRED','INVALID_COOKIE','LOGIN_CONTRACT_CHANGED','TRANSPORT_ERROR','UNSUPPORTED_ENCODING','OPERATION_FAILED','COLLECTION_LIMIT','COLLECTION_INCOMPLETE','ORDER_EMPTY','ORDER_MISMATCH','INVALID_ORDER_MATERIALS','CONNECTION_FAILED','TLS_ERROR','HTTP_ERROR','REDIRECT_BLOCKED'))
def _wrap(fn,*args,**kwargs):
    try:return fn(*args,**kwargs)
    except shared.RelayProtocolError:raise RelayProtocolError() from None
def strict_json(payload):return _wrap(shared.strict_json,payload)
def read_private_json(path,max_bytes=65536):return _wrap(shared.read_private_json,path,max_bytes)
def load_token(path):return _wrap(shared.load_token,path)
def text_scope(value,*,empty=False,limit=128):
    if type(value) is not str or len(value)>limit or (not value and not empty) or value!=value.strip() or (value and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.:/ -]*',value)):_reject()
    return value
def order_scope(value, *, empty=False):
    if not (empty and value == '' and type(value) is str) and not valid_identity(value):_reject()
    return value
def validate_context(value):
    _keys(value,('source','fingerprint'));source=value['source']
    _keys(source,('system','origin','fact_role','environment','site_code','namespace'))
    if source['system']!='mes' or source['origin']!='native' or source['fact_role']!='observation' or source['environment'] not in ('production','test','development') or not _hex(source['namespace']) or not _hex(value['fingerprint']):_reject()
    if type(source['site_code']) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,32}',source['site_code']):_reject()
    return value
def parse_request(payload):
    if type(payload) is not bytes or len(payload)>MAX_REQUEST_BYTES:_reject()
    v=strict_json(payload);_keys(v,('version','request_id','operation','actor_hash','expected_fingerprint','scope'))
    if type(v['version']) is not int or v['version']!=1 or not _uuid(v['request_id']) or not _hex(v['actor_hash']):_reject()
    op=v['operation'];s=v['scope']
    if type(op) is not str:_reject()
    if op=='describe':
        _keys(s,())
        if v['expected_fingerprint'] is not None:_reject()
    else:
        if not _hex(v['expected_fingerprint']):_reject()
        if op=='source_orders':
            _keys(s,('prefix','after','directory_mode') if type(s) is dict and 'directory_mode' in s else ('prefix','after'))
            if 'directory_mode' in s and s['directory_mode']!='recent':_reject()
            text_scope(s['prefix'],empty=True,limit=64);order_scope(s['after'],empty=True)
        elif op=='order_materials':
            _keys(s,('shop_order','component_mode') if type(s) is dict and 'component_mode' in s else ('shop_order',))
            if 'component_mode' in s and s['component_mode']!='owner':_reject()
            order_scope(s['shop_order'])
        elif op in ('material_priority','iqc_inspections'):
            _keys(s,('shop_order','material','page','page_size') if op=='material_priority' else ('material','page','page_size'))
            text_scope(s['material'])
            if op=='material_priority':order_scope(s['shop_order'])
            if type(s['page']) is not int or not 1<=s['page']<=1000000 or type(s['page_size']) is not int or not 1<=s['page_size']<=5:_reject()
        else:_reject()
    return v
def validate_response(value,*,request_id,expected_context=None):
    _keys(value,('version','request_id','context','result','error'))
    if type(value['version']) is not int or value['version']!=1 or not _uuid(value['request_id']) or value['request_id']!=request_id:_reject()
    if value['error'] is None:
        validate_context(value['context'])
        if type(value['result']) is not dict or expected_context is not None and value['context']!=validate_context(expected_context):_reject()
    else:
        _keys(value['error'],('code',));code=value['error']['code']
        if type(code) is not str or code not in SAFE_CODES or value['context'] is not None or value['result'] is not None:_reject()
    import json
    try:size=len(json.dumps(value,allow_nan=False).encode())
    except (ValueError,TypeError,RecursionError):_reject()
    if size>MAX_RESPONSE_BYTES:_reject()
    return value
