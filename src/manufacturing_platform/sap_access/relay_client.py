"""Cloud-only fixed read relay. SAP credentials never enter this adapter."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4, UUID

from .errors import SapAccessError
from .relay_protocol import read_private_json, load_token, validate_context, validate_response, strict_json, parse_request, RelayProtocolError, SAFE_CODES
from .service import SapAccessService
from .store import SapAuditStore
from .production_order import scope as order_scope, FUNCTION as ORDER_FUNCTION
from .stock_requirements import envelope, FUNCTION as MRP_FUNCTION


def _exchange_result(socket_path, token, command, timeout=70, max_bytes=2097152):
    """Bounded isolated AF_UNIX POST; returns JSON envelope, including describe.

    Bootstrap callers must validate_response with their generated request UUID.
    No configuration, context discovery, retry, DNS, or proxy lookup occurs here.
    """
    try:
        if (type(socket_path) is not str or not os.path.isabs(socket_path)
                or len(socket_path.encode()) > 100 or '\x00' in socket_path
                or type(token) is not str or not re.fullmatch('[0-9a-f]{64}', token)
                or type(timeout) not in (int, float) or not 0 < timeout <= 70
                or type(max_bytes) is not int or not 1024 <= max_bytes <= 2097152):
            raise ValueError()
        command = parse_request(json.dumps(command, allow_nan=False).encode())
        value={'socket_path':socket_path,'token':token,'command':command,'timeout':timeout,'max_bytes':max_bytes}
        result=subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('relay_worker.py'))],
            input=json.dumps(value,allow_nan=False).encode(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            timeout=timeout,check=False)
        if result.returncode or len(result.stdout)>max_bytes*6+1024: raise ValueError()
        reply=strict_json(result.stdout)
        if set(reply)=={'error'}:
            code=reply['error']
            raise SapAccessError(code if code in SAFE_CODES or code=='SAP_RELAY_INVALID_RESPONSE' else 'SAP_RELAY_INVALID_RESPONSE')
        if set(reply)!={'body','status'}: raise ValueError()
        body=strict_json(reply['body'])
        if reply['status']!=200 and (type(body) is not dict or not body.get('error')): raise ValueError()
        if reply['status']==200 and type(body) is dict and body.get('error') is not None: raise ValueError()
        return body, len(reply['body'].encode('utf-8'))
    except subprocess.TimeoutExpired: raise SapAccessError('SAP_TIMEOUT') from None
    except SapAccessError: raise
    except Exception: raise SapAccessError('SAP_RELAY_INVALID_RESPONSE') from None


def exchange(socket_path, token, command, timeout=70, max_bytes=2097152):
    """Return a bounded relay envelope; bootstrap must validate its UUID/context.

    All secrets travel through the isolated worker's stdin, never argv or logs.
    """
    return _exchange_result(socket_path, token, command, timeout, max_bytes)[0]


def _strings(value):
    return (type(value) is dict and len(value)<=256 and all(type(k) is str and re.fullmatch('[A-Z][A-Z0-9_]{0,127}',k)
        and type(v) is str and len(v)<=4096 for k,v in value.items()))


def validate_result(result, operation, scope, source):
    """Accept only the normalized native shapes and original query identity."""
    try:
        if type(result) is not dict: raise ValueError()
        if str(UUID(result['request_id']))!=result['request_id']: raise ValueError()
        if operation=='production_order':
            if set(result)!={'number','plant','material','description','quantity','unit','components','total','function','source','request_id'}: raise ValueError()
            if result['function']!=ORDER_FUNCTION or result['source']!=source or result['number']!=scope['number'] or result['plant']!=scope['plant']: raise ValueError()
            for field in ('number','plant','material','description','quantity','unit'):
                if type(result[field]) is not str or len(result[field])>4096: raise ValueError()
            decimal=lambda v: type(v) is str and re.fullmatch(r'[+-]?[0-9]+(?:\.[0-9]+)?',v)
            if not decimal(result['quantity']): raise ValueError()
            rows=result['components']
            if type(rows) is not list or len(rows)>500 or type(result['total']) is not int or result['total']!=len(rows): raise ValueError()
            keys=set()
            for row in rows:
                if type(row) is not dict or set(row)!={'component_key','material','plant','storage_location','required_quantity','withdrawn_quantity','unit','required_at'}: raise ValueError()
                if any(type(v) is not str or len(v)>4096 for v in row.values()): raise ValueError()
                key=row['component_key']
                if not re.fullmatch(r'[0-9]+:[0-9]+:[0-9]*',key) or key in keys or row['plant']!=scope['plant']: raise ValueError()
                keys.add(key)
                if not decimal(row['required_quantity']) or not decimal(row['withdrawn_quantity']): raise ValueError()
        else:
            if set(result)!={'return','mrp_list','items','function','source','request_id'} or result['function']!=MRP_FUNCTION or result['source']!='native_sap': raise ValueError()
            if not _strings(result['return']) or result['return'].get('TYPE') not in ('','S','W','I') or not _strings(result['mrp_list']): raise ValueError()
            header=result['mrp_list']; material=header.get('MATERIAL_LONG') or header.get('MATERIAL')
            def alpha(a,b): return a==b or (type(a) is str and a.isascii() and b.isascii() and a.isdecimal() and b.isdecimal() and int(a)==int(b))
            if not alpha(material,scope['material']) or header.get('PLANT')!=scope['plant']: raise ValueError()
            if any(header.get(key) and not alpha(header[key],scope['material']) for key in ('MATERIAL','MATERIAL_LONG')): raise ValueError()
            if type(result['items']) is not list or len(result['items'])>50 or any(not _strings(row) or not row for row in result['items']): raise ValueError()
    except Exception: raise SapAccessError('SAP_RELAY_INVALID_RESPONSE',502) from None
    return result


class RelaySapAccessService:
    def __init__(self, config_path, audit_path): self.config_path,self.audit_path=config_path,audit_path
    def _context(self):
        try:
            cfg=read_private_json(self.config_path)
            if set(cfg)!={'version','transport','enabled','read_only','environment','socket_path','token_path','expected_context','timeout_seconds','max_response_bytes'}: raise ValueError()
            if type(cfg['version']) is not int or cfg['version']!=1 or cfg['transport']!='mac_read_relay' or type(cfg['enabled']) is not bool or cfg['read_only'] is not True or cfg['environment'] not in ('test','development'): raise ValueError()
            validate_context(cfg['expected_context'])
            if cfg['expected_context']['source']['environment']!=cfg['environment']: raise ValueError()
            path=cfg['socket_path']
            if type(path) is not str or not os.path.isabs(path) or len(path.encode())>100 or '\x00' in path: raise ValueError()
            if type(cfg['timeout_seconds']) is not int or not 1<=cfg['timeout_seconds']<=70 or type(cfg['max_response_bytes']) is not int or not 1024<=cfg['max_response_bytes']<=2097152: raise ValueError()
            paths=[self.config_path,cfg['token_path'],self.audit_path,self.audit_path+'.lock']
            if any(type(p) is not str or not os.path.isabs(p) for p in paths) or len({os.path.realpath(p) for p in paths})!=4: raise ValueError()
            for i,a in enumerate(paths):
                for b in paths[i+1:]:
                    if os.path.exists(a) and os.path.exists(b) and os.path.samefile(a,b): raise ValueError()
            token=load_token(cfg['token_path'])
            binding=hashlib.sha256(json.dumps([cfg,token],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        except Exception: raise SapAccessError('SAP_CONFIGURATION_ERROR') from None
        if not cfg['enabled']: raise SapAccessError('SAP_DISABLED')
        return cfg,token,binding,SapAuditStore(self.audit_path)
    def read_context(self):
        cfg,_,binding,_=self._context()
        return {'source':cfg['expected_context']['source'],'fingerprint':binding}
    def configuration_matches(self, fingerprint):
        try: return SapAccessService._binding_matches(self.read_context()['fingerprint'],fingerprint)
        except SapAccessError: return False
    def _query(self,operation,scope,actor_id,expected):
        cfg,token,binding,store=self._context()
        SapAccessService._require_binding(binding,expected)
        request_id=str(uuid4()); actor_hash=hashlib.sha256(str(actor_id).encode()).hexdigest()
        command={'version':1,'request_id':request_id,'operation':operation,'actor_hash':actor_hash,'expected_fingerprint':cfg['expected_context']['fingerprint'],'scope':scope}
        event={'request_id':request_id,'operation':operation,'function':ORDER_FUNCTION if operation=='production_order' else MRP_FUNCTION,'timestamp':datetime.now(timezone.utc).isoformat(),'status':'started','actor_hash':actor_hash,'binding':binding}
        store.record(event)
        try:
            reply,response_bytes=_exchange_result(cfg['socket_path'],token,command,cfg['timeout_seconds'],cfg['max_response_bytes'])
            try: validate_response(reply,request_id=request_id,expected_context=cfg['expected_context'])
            except RelayProtocolError: raise SapAccessError('SAP_RELAY_INVALID_RESPONSE',502) from None
            if reply['error']: raise SapAccessError(reply['error']['code'])
            result=validate_result(reply['result'],operation,scope,cfg['expected_context']['source'])
            if not self.configuration_matches(binding): raise SapAccessError('SAP_CONFIGURATION_ERROR')
        except SapAccessError as exc:
            store.record({**event,'status':'failed','error_code':exc.code}); raise
        # Preserve upstream correlation only in the private audit (not business rows).
        store.record({**event,'status':'success','response_bytes':response_bytes,'source_request_id':result['request_id']})
        return {**result,'request_id':request_id}
    def production_order(self, number, plant, actor_id, *, expected_fingerprint=None):
        number,plant=order_scope(number,plant)
        return self._query('production_order',{'number':number,'plant':plant},actor_id,expected_fingerprint)
    def stock_requirements(self, material, plant, actor_id, *, expected_fingerprint=None):
        envelope(material,plant)
        return self._query('stock_requirements',{'material':material,'plant':plant},actor_id,expected_fingerprint)
    def status(self):
        cfg,_,_,_=self._context()
        return {'enabled':True,'transport':'mac_read_relay','environment':cfg['environment'],'read_only':True,'authentication_verified':False,'last_ping_at':None,'business_data_verified':False,'business_execution_enabled':False,'source':'native_sap','audit_retention_events':1000}
    def interfaces(self):
        self._context()
        return {'source':'native_sap','business_data_verified':False,'interfaces':[{'function':f,'execution_enabled':True,'contract_cached':False} for f in (ORDER_FUNCTION,MRP_FUNCTION)]}
    def contract(self,function): raise SapAccessError('SAP_CONTRACT_NOT_CACHED',404)
    def ping(self,actor_id): raise SapAccessError('SAP_FUNCTION_NOT_ALLOWED',403)
    def refresh_contracts(self,actor_id): raise SapAccessError('SAP_FUNCTION_NOT_ALLOWED',403)
