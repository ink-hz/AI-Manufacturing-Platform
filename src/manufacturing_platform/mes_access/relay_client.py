"""Cloud MES adapter with independent local binding and pinned native context."""
from datetime import datetime,timezone
import hashlib,json,os,re,subprocess,sys
from pathlib import Path
from uuid import uuid4
from .errors import MesAccessError
from .relay_protocol import *
from .relay_protocol import _uuid,_keys
from .store import MesAuditStore
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
        result=subprocess.run([sys.executable,'-I',str(Path(__file__).parents[1] / 'sap_access' / 'relay_worker.py')],
            input=json.dumps(value,allow_nan=False).encode(),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            timeout=timeout,check=False)
        if result.returncode or len(result.stdout)>max_bytes*6+1024: raise ValueError()
        reply=strict_json(result.stdout)
        if set(reply)=={'error'}:
            code=reply['error']
            code=code.replace('SAP_','MES_',1) if type(code) is str else None
            raise MesAccessError(code if code in SAFE_CODES or code=='MES_RELAY_INVALID_RESPONSE' else 'MES_RELAY_INVALID_RESPONSE')
        if set(reply)!={'body','status'}: raise ValueError()
        body=strict_json(reply['body'])
        if reply['status']!=200 and (type(body) is not dict or not body.get('error')): raise ValueError()
        if reply['status']==200 and type(body) is dict and body.get('error') is not None: raise ValueError()
        return body, len(reply['body'].encode('utf-8'))
    except subprocess.TimeoutExpired: raise MesAccessError('MES_TIMEOUT') from None
    except MesAccessError: raise
    except Exception: raise MesAccessError('MES_RELAY_INVALID_RESPONSE') from None


def exchange(socket_path, token, command, timeout=70, max_bytes=2097152):
    """Return a bounded relay envelope; bootstrap must validate its UUID/context.

    All secrets travel through the isolated worker's stdin, never argv or logs.
    """
    return _exchange_result(socket_path, token, command, timeout, max_bytes)[0]


def validate_result(result,operation,scope,context):
    try:
        if type(result) is not dict:raise ValueError()
        source=context['source']
        if operation=='order_materials':
            _keys(result,('namespace','fingerprint','environment','site_code','request_ids','total','components'))
            if any(result[k]!=source[k] for k in ('namespace','environment','site_code')) or result['fingerprint']!=context['fingerprint']:raise ValueError()
            if type(result['request_ids']) is not list or not 1<=len(result['request_ids'])<=20 or any(not _uuid(v) for v in result['request_ids']):raise ValueError()
            rows=result['components']
            if type(rows) is not list or not 1<=len(rows)<=100 or type(result['total']) is not int or result['total']!=len(rows):raise ValueError()
            from .order_materials import _text,_amount
            seen=set()
            for row in rows:
                _keys(row,('component_key','material_id','required_quantity','withdrawn_quantity','unit','storage_location'))
                key=_text(row['component_key'])
                if key in seen or not re.fullmatch(r'[^:]+:[^:]+',key):raise ValueError()
                seen.add(key);_text(row['material_id']);_text(row['unit']);_text(row['storage_location'],required=False);_amount(row['required_quantity'])
                if row['withdrawn_quantity'] is not None:_amount(row['withdrawn_quantity'])
        elif operation=='source_orders':
            _keys(result,('source','fingerprint','items','next_cursor','total','page_size','request_id'))
            if result['source']!=source or result['fingerprint']!=context['fingerprint'] or result['total'] is not None or type(result['page_size']) is not int or result['page_size']!=5 or not _uuid(result['request_id']):raise ValueError()
            rows=result['items']
            if type(rows) is not list or len(rows)>5:raise ValueError()
            last=scope['after']
            for row in rows:
                _keys(row,('shop_order','description'));order_scope(row['shop_order'])
                if row['shop_order']<=last or not row['shop_order'].startswith(scope['prefix']) or row['description'] is not None and (type(row['description']) is not str or len(row['description'])>4096):raise ValueError()
                last=row['shop_order']
            if result['next_cursor'] != (last if len(rows)==5 else None):raise ValueError()
        else:
            _keys(result,('rows','total_items','page','page_size','interface','source','authentication_verified','business_query_succeeded','business_data_verified','business_reconciled','request_id'))
            if not _uuid(result['request_id']) or result['interface']!=operation or result['source']!='native_mes' or any(type(result[k]) is not int or result[k]!=scope[k] for k in ('page','page_size')):raise ValueError()
            if result['authentication_verified'] is not True or result['business_query_succeeded'] is not True or result['business_data_verified'] is not False or result['business_reconciled'] is not False:raise ValueError()
            rows=result['rows'];total=result['total_items']
            if type(rows) is not list or len(rows)>scope['page_size'] or type(total) is not int or not 0<=total<=2**31-1 or rows and (scope['page']-1)*scope['page_size']+len(rows)>total:raise ValueError()
            from .parsing import _bounded_tree
            # Preserve the narrowly reviewed inspector USERNAME exception.
            _bounded_tree({'result':{'page':rows}},operation)
            for row in rows:
                if type(row) is not dict:raise ValueError()
                if operation=='material_priority':
                    if row.get('SHOP_ORDER')!=scope['shop_order'] or row.get('MATNR')!=scope['material']:raise ValueError()
                elif row.get('ITEM_NO')!=scope['material']:raise ValueError()
        return result
    except Exception:raise MesAccessError('MES_RELAY_INVALID_RESPONSE',502) from None

class RelayMesAccessService:
    def __init__(self,config_path,audit_path):self.config_path,self.audit_path=config_path,audit_path
    def _context(self):
        try:
            cfg=read_private_json(self.config_path)
            _keys(cfg,('version','transport','enabled','read_only','environment','socket_path','token_path','expected_context','timeout_seconds','max_response_bytes'))
            if type(cfg['version']) is not int or cfg['version']!=1 or cfg['transport']!='mac_read_relay' or type(cfg['enabled']) is not bool or cfg['read_only'] is not True:raise ValueError()
            validate_context(cfg['expected_context'])
            if cfg['environment']!=cfg['expected_context']['source']['environment']:raise ValueError()
            path=cfg['socket_path']
            if type(path) is not str or not os.path.isabs(path) or len(path.encode())>100 or '\x00' in path:raise ValueError()
            if type(cfg['timeout_seconds']) is not int or not 1<=cfg['timeout_seconds']<=70 or type(cfg['max_response_bytes']) is not int or not 1024<=cfg['max_response_bytes']<=2097152:raise ValueError()
            paths=[self.config_path,cfg['token_path'],self.audit_path,self.audit_path+'.lock']
            if any(type(p) is not str or not os.path.isabs(p) for p in paths) or len({os.path.realpath(p) for p in paths})!=4:raise ValueError()
            for i,a in enumerate(paths):
                for b in paths[i+1:]:
                    if os.path.exists(a) and os.path.exists(b) and os.path.samefile(a,b):raise ValueError()
            token=load_token(cfg['token_path'])
            binding=hashlib.sha256(json.dumps([cfg,token],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        except Exception:raise MesAccessError('MES_CONFIGURATION_ERROR') from None
        if not cfg['enabled']:raise MesAccessError('MES_DISABLED')
        return cfg,token,binding,MesAuditStore(self.audit_path)
    def read_context(self):
        cfg,_,binding,_=self._context()
        return {'source':cfg['expected_context']['source'],'fingerprint':binding}
    def configuration_matches(self,fingerprint):
        try:return self.read_context()['fingerprint']==fingerprint
        except MesAccessError:return False
    def order_materials_configuration(self):
        context=self.read_context()
        return {'namespace':context['source']['namespace'],'fingerprint':context['fingerprint']}
    def _query(self,operation,scope,actor_id,expected):
        cfg,token,binding,store=self._context()
        if expected is not None and expected!=binding:raise MesAccessError('MES_CONFIGURATION_CHANGED',409)
        rid=str(uuid4());actor_hash=hashlib.sha256(str(actor_id).encode()).hexdigest()
        command=dict(version=1,request_id=rid,operation=operation,actor_hash=actor_hash,expected_fingerprint=cfg['expected_context']['fingerprint'],scope=scope)
        try:parse_request(json.dumps(command).encode())
        except RelayProtocolError:raise MesAccessError('MES_INVALID_QUERY',400) from None
        function='order_materials' if operation=='order_materials' else operation
        event=dict(request_id=rid,operation='query',function=function,timestamp=datetime.now(timezone.utc).isoformat(),status='started',actor_hash=actor_hash,binding=binding)
        store.record(event)
        try:
            reply,size=_exchange_result(cfg['socket_path'],token,command,cfg['timeout_seconds'],cfg['max_response_bytes'])
            try:validate_response(reply,request_id=rid,expected_context=cfg['expected_context'])
            except RelayProtocolError:raise MesAccessError('MES_RELAY_INVALID_RESPONSE',502) from None
            if reply['error'] is not None:raise MesAccessError(reply['error']['code'])
            result=validate_result(reply['result'],operation,scope,cfg['expected_context'])
            if not self.configuration_matches(binding):raise MesAccessError('MES_CONFIGURATION_CHANGED',409)
        except MesAccessError as exc:
            store.record({**event,'status':'failed','error_code':exc.code});raise
        store.record({**event,'status':'success','response_bytes':size})
        if operation in ('order_materials','source_orders'):return {**result,'fingerprint':binding}
        return result
    def source_orders(self,prefix='',after='',actor_id=None,*,expected_fingerprint=None):
        return self._query('source_orders',{'prefix':prefix,'after':after},actor_id,expected_fingerprint)
    def collect_order_materials(self,shop_order,actor_id,*,expected_fingerprint=None):
        return self._query('order_materials',{'shop_order':shop_order},actor_id,expected_fingerprint)
    def query(self,interface,filters=None,page=1,page_size=1,actor_id=None,*,expected_fingerprint=None):
        try:
            keys={'material_priority':('shopOrder','itemNo'),'iqc_inspections':('item_no',)}
            if interface not in keys or type(filters) is not dict or set(filters)!=set(keys[interface]):raise ValueError()
            scope={'material':filters['itemNo'] if interface=='material_priority' else filters['item_no'],'page':page,'page_size':page_size}
            if interface=='material_priority':scope['shop_order']=filters['shopOrder']
            parse_request(json.dumps(dict(version=1,request_id=str(uuid4()),operation=interface,actor_hash='0'*64,expected_fingerprint='0'*64,scope=scope)).encode())
        except Exception:raise MesAccessError('MES_INVALID_QUERY',400) from None
        return self._query(interface,scope,actor_id,expected_fingerprint)
    def status(self):
        c=self.read_context()
        return {'enabled':True,'transport':'mac_read_relay','environment':c['source']['environment'],'read_only':True,'source':'native_mes','business_data_verified':False,'business_reconciled':False,'authentication_verified':False,'business_query_succeeded':False,'last_operation_at':None,'last_query_at':None,'audit_retention_events':1000}
    def interfaces(self):
        self._context()
        from .registry import INTERFACES
        return {'source':'native_mes','business_data_verified':False,'interfaces':[{'interface':n,'label':INTERFACES[n].label,'filters':list(INTERFACES[n].filters),'max_page_size':5} for n in ('order_materials','material_priority','iqc_inspections')]}
    def diagnose(self,actor_id):raise MesAccessError('MES_INTERFACE_DENIED',403)
