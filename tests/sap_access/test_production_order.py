"""Synthetic records only; field names match the reviewed SAP wire schema."""
import xml.etree.ElementTree as ET
import pytest
from manufacturing_platform.sap_access.errors import SapAccessError


def test_fixed_request():
    from manufacturing_platform.sap_access.production_order import envelope
    op=ET.fromstring(envelope('123','P001'))[0][0]
    assert op.find('NUMBER').text == '000000000123'
    assert {n.tag:n.text or '' for n in op.find('ORDER_OBJECTS')} == {'HEADER':'X','POSITIONS':'','SEQUENCES':'','OPERATIONS':'','COMPONENTS':'X','PROD_REL_TOOLS':'','TRIGGER_POINTS':'','SUBOPERATIONS':''}
    assert not op.find('COLLECTIVE_ORDER').text

@pytest.mark.parametrize('number,plant',[('', 'P001'),('1'*13,'P001'),('１２','P001'),('12*','P001'),('12',''),('12','P0001'),(None,'P001')])
def test_invalid_scope(number,plant):
    from manufacturing_platform.sap_access.production_order import envelope
    with pytest.raises(SapAccessError): envelope(number,plant)

# Schema names only, extracted from the reviewed captured contract.
HEADER_FIELDS = ('ORDER_NUMBER', 'PRODUCTION_PLANT', 'MRP_CONTROLLER', 'PRODUCTION_SCHEDULER', 'MATERIAL', 'EXPL_DATE', 'ROUTING_NO', 'RESERVATION_NUMBER', 'SCHED_RELEASE_DATE', 'ACTUAL_RELEASE_DATE', 'FINISH_DATE', 'START_DATE', 'PRODUCTION_FINISH_DATE', 'PRODUCTION_START_DATE', 'ACTUAL_START_DATE', 'ACTUAL_FINISH_DATE', 'SCRAP', 'TARGET_QUANTITY', 'UNIT', 'UNIT_ISO', 'PRIORITY', 'ORDER_TYPE', 'ENTERED_BY', 'ENTER_DATE', 'DELETION_FLAG', 'WBS_ELEMENT', 'CONF_NO', 'CONF_CNT', 'INT_OBJ_NO', 'SCHED_FIN_TIME', 'SCHED_START_TIME', 'COLLECTIVE_ORDER', 'ORDER_SEQ_NO', 'FINISH_TIME', 'START_TIME', 'ACTUAL_START_TIME', 'LEADING_ORDER', 'SALES_ORDER', 'SALES_ORDER_ITEM', 'PROD_SCHED_PROFILE', 'MATERIAL_TEXT', 'SYSTEM_STATUS', 'CONFIRMED_QUANTITY', 'PLAN_PLANT', 'BATCH', 'MATERIAL_EXTERNAL', 'MATERIAL_GUID', 'MATERIAL_VERSION', 'DATE_OF_EXPIRY', 'DATE_OF_MANUFACTURE', 'MATERIAL_LONG')
COMPONENT_FIELDS = ('RESERVATION_NUMBER', 'RESERVATION_ITEM', 'RESERVATION_TYPE', 'DELETION_INDICATOR', 'MATERIAL', 'PROD_PLANT', 'STORAGE_LOCATION', 'SUPPLY_AREA', 'BATCH', 'SPECIAL_STOCK', 'REQ_DATE', 'REQ_QUAN', 'BASE_UOM', 'BASE_UOM_ISO', 'WITHDRAWN_QUANTITY', 'ENTRY_QUANTITY', 'ENTRY_UOM', 'ENTRY_UOM_ISO', 'ORDER_NUMBER', 'MOVEMENT_TYPE', 'ITEM_CATEGORY', 'ITEM_NUMBER', 'SEQUENCE', 'OPERATION', 'BACKFLUSH', 'VALUATION_SPEC_STOCK', 'SYSTEM_STATUS', 'MATERIAL_DESCRIPTION', 'COMMITED_QUANTITY', 'SHORTAGE', 'PURCHASE_REQ_NO', 'PURCHASE_REQ_ITEM', 'MATERIAL_EXTERNAL', 'MATERIAL_GUID', 'MATERIAL_VERSION', 'REQ_SEGMENT', 'STOCK_SEGMENT', 'MATERIAL_LONG', 'REQ_SEG_LONG', 'STK_SEG_LONG')
RETURN_FIELDS = ('TYPE', 'ID', 'NUMBER', 'MESSAGE', 'LOG_NO', 'LOG_MSG_NO', 'MESSAGE_V1', 'MESSAGE_V2', 'MESSAGE_V3', 'MESSAGE_V4', 'PARAMETER', 'ROW', 'FIELD', 'SYSTEM')

FLAGS=('HEADER','POSITIONS','SEQUENCES','OPERATIONS','COMPONENTS','PROD_REL_TOOLS','TRIGGER_POINTS','SUBOPERATIONS')
TABLES=('COMPONENT','FSH_BUNDLES','HEADER','OPERATION','POSITION','PROD_REL_TOOL','SEQUENCE','TRIGGER_POINT')
RETURN_LENGTHS = dict(zip(RETURN_FIELDS, (1,20,3,220,20,6,50,50,50,50,32,None,30,10)))
def return_scalar(name):
    if name == 'ROW': return {'name':name,'type':'int'}
    return {'name':name,'type':'string','base_type':'string','max_length':RETURN_LENGTHS[name], **({'pattern':r'\d*'} if name in {'NUMBER','LOG_MSG_NO'} else {})}

def contract():
    def scalar(n, length=1): return {'name':n,'max_length':length}
    def table(n, fields): return {'name':n,'table':True,'fields':[{'name':'item','fields':[scalar(f,100) for f in fields]}]}
    return {'request_fields':[scalar('COLLECTIVE_ORDER'),*[table(n,HEADER_FIELDS if n=='HEADER' else COMPONENT_FIELDS if n=='COMPONENT' else ('DUMMY',)) for n in TABLES],scalar('NUMBER',12),{'name':'ORDER_OBJECTS','fields':[scalar(n) for n in FLAGS]}], 'response_fields':[{'name':'RETURN','fields':[return_scalar(n) for n in RETURN_FIELDS]},*[table(n,HEADER_FIELDS if n=='HEADER' else COMPONENT_FIELDS if n=='COMPONENT' else ('DUMMY',)) for n in TABLES]]}

def response(status='',count=1,header_number='000000000123',header_plant='P001',component_number='000000000123',component_plant='P001',duplicate=False):
    root=ET.Element('{http://schemas.xmlsoap.org/soap/envelope/}Envelope'); op=ET.SubElement(ET.SubElement(root,'{http://schemas.xmlsoap.org/soap/envelope/}Body'),'{urn:sap-com:document:sap:rfc:functions}BAPI_PRODORD_GET_DETAIL.Response')
    def fields(node,names,values):
        for n in names: ET.SubElement(node,n).text=values.get(n,'')
    fields(ET.SubElement(op,'RETURN'),RETURN_FIELDS,{'TYPE':status})
    for n in TABLES:
        table=ET.SubElement(op,n)
        if n=='HEADER': fields(ET.SubElement(table,'item'),HEADER_FIELDS,{'ORDER_NUMBER':header_number,'PRODUCTION_PLANT':header_plant,'MATERIAL':'MAT-1','TARGET_QUANTITY':'001.200','UNIT':'EA','MATERIAL_TEXT':'Synthetic'})
        if n=='COMPONENT':
            for i in range(count): fields(ET.SubElement(table,'item'),COMPONENT_FIELDS,{'ORDER_NUMBER':component_number,'PROD_PLANT':component_plant,'RESERVATION_NUMBER':'0000000001','RESERVATION_ITEM':str(1 if duplicate else i+1),'RESERVATION_TYPE':'1','MATERIAL':'PART-1','REQ_QUAN':'001.200','WITHDRAWN_QUANTITY':'0.000','BASE_UOM':'EA'})
    return ET.tostring(root)

def test_normalization_preserves_quantity_and_empty_components():
    from manufacturing_platform.sap_access.production_order import parse_response
    result=parse_response(response(),'123','P001',contract())
    assert result['number']=='000000000123' and result['quantity']=='001.200'
    assert result['components'][0]['required_quantity']=='001.200'
    assert result['components'][0]['withdrawn_quantity']=='0.000'
    assert parse_response(response(count=0),'123','P001',contract())['total']==0

@pytest.mark.parametrize('kw',[{'status':'E'},{'status':'A'},{'status':'X'},{'header_number':'000000000124'},{'header_plant':'P002'},{'component_number':'000000000124'},{'component_plant':'P002'},{'count':2,'duplicate':True},{'count':501}])
def test_invalid_source_result_rejected(kw):
    from manufacturing_platform.sap_access.production_order import parse_response
    with pytest.raises(SapAccessError): parse_response(response(**kw),'123','P001',contract())

@pytest.mark.parametrize('status',['','S','I','W'])
def test_nonerror_return(status):
    from manufacturing_platform.sap_access.production_order import parse_response
    assert parse_response(response(status=status),'123','P001',contract())['total']==1

def test_contract_drift_rejected():
    from manufacturing_platform.sap_access.production_order import validate_contract
    c=contract(); c['response_fields'][0]['fields'].pop()
    with pytest.raises(SapAccessError): validate_contract(c)

def test_transport_tamper_every_field():
    from manufacturing_platform.sap_access.production_order import envelope,FUNCTION
    from manufacturing_platform.sap_access.transport import SoapTransport
    from .test_transport import config,Sender
    sender=Sender(None); t=SoapTransport(config(allowed_functions=(FUNCTION,)),sender=sender)
    root=ET.fromstring(envelope('123','P001'))
    for i,node in enumerate(list(root[0][0].iter())[1:]):
        body=ET.fromstring(envelope('123','P001')); list(body[0][0].iter())[i+1].text='Y'
        with pytest.raises(SapAccessError): t.invoke(FUNCTION,ET.tostring(body),'http://www.sap.com/'+FUNCTION)
    assert not sender.calls

def test_context_private_binding_and_configuration_switch(tmp_path):
    import json
    from .test_core import config_file
    from manufacturing_platform.sap_access.service import SapAccessService
    path=config_file(tmp_path); s=SapAccessService(path,str(tmp_path/'audit.json'))
    context=s.read_context(); assert context['source']['origin']=='native'
    assert 'application_server' not in context['source'] and 'password' not in repr(context)
    assert s.configuration_matches(context['fingerprint'])
    raw=json.loads(open(path).read()); raw['password']='changed'; open(path,'w').write(json.dumps(raw))
    assert not s.configuration_matches(context['fingerprint'])
    raw['enabled']=False; open(path,'w').write(json.dumps(raw))
    with pytest.raises(SapAccessError): s.read_context()

def test_500_components_are_complete():
    from manufacturing_platform.sap_access.production_order import parse_response
    assert parse_response(response(count=500),'123','P001',contract())['total']==500

@pytest.mark.parametrize('old,new',[(b'<COMPONENT>',b'<COMPONENT>bad'),(b'<item>',b'<item bad="1">'),(b'</REQ_QUAN>',b'</REQ_QUAN>bad'),(b'<POSITION />',b'<POSITION><item/></POSITION>')])
def test_malformed_structure_rejected(old,new):
    from manufacturing_platform.sap_access.production_order import parse_response
    with pytest.raises(SapAccessError): parse_response(response().replace(old,new),'123','P001',contract())

def test_service_contract_validation_audit_and_configuration(tmp_path,monkeypatch):
    import json
    from .test_core import config_file
    import manufacturing_platform.sap_access.service as mod
    from manufacturing_platform.sap_access.production_order import FUNCTION
    path=config_file(tmp_path); raw=json.loads(open(path).read()); raw['allowed_functions'].append(FUNCTION); open(path,'w').write(json.dumps(raw))
    descriptor={**contract(),'function':FUNCTION,'digest':'a'*64,'soap_action':'http://www.sap.com/'+FUNCTION}
    monkeypatch.setattr(mod,'parse_wsdl',lambda *args:descriptor)
    calls=[]
    class Transport:
        def __init__(self,c): assert json.loads((tmp_path/'audit.json').read_text())['events'][-1]['status']=='started'
        def fetch_wsdl(self,fn): calls.append('wsdl'); return b'synthetic'
        def invoke(self,*args): calls.append('invoke'); return response()
    s=mod.SapAccessService(path,str(tmp_path/'audit.json'),transport_factory=Transport)
    result=s.production_order('123','P001','admin')
    assert result['source']==s.read_context()['source'] and result['request_id'] and result['function']==FUNCTION
    audit=(tmp_path/'audit.json').read_text()
    assert 'MAT-1' not in audit and '001.200' not in audit and '000000000123' not in audit
    descriptor['response_fields'][0]['fields'].pop()
    calls.clear()
    with pytest.raises(SapAccessError) as e: s.production_order('123','P001','admin')
    assert e.value.code=='SAP_INVALID_CONTRACT' and calls==['wsdl']

@pytest.mark.parametrize('change',[{'environment':'production'},{'enabled':False},{'allowed_functions':['RFC_PING']}])
def test_service_configuration_denies_before_io(tmp_path,change):
    import json
    from .test_core import config_file
    from manufacturing_platform.sap_access.service import SapAccessService
    path=config_file(tmp_path); raw=json.loads(open(path).read()); raw.update(change); open(path,'w').write(json.dumps(raw))
    s=SapAccessService(path,str(tmp_path/'audit.json'),transport_factory=lambda c:pytest.fail('no I/O'))
    with pytest.raises(SapAccessError): s.production_order('123','P001','admin')
    assert not (tmp_path/'audit.json').exists()

def test_empty_reservation_type_is_valid_captured_schema_semantics():
    from manufacturing_platform.sap_access.production_order import parse_response
    payload=response().replace(b'<RESERVATION_TYPE>1</RESERVATION_TYPE>',b'<RESERVATION_TYPE/>')
    assert parse_response(payload,'123','P001',contract())['total']==1

def test_contract_nested_scalar_drift_rejected():
    from manufacturing_platform.sap_access.production_order import validate_contract
    c=contract(); c['response_fields'][1]['fields'][0]['fields'][0]['fields']=[{'name':'UNREVIEWED'}]
    with pytest.raises(SapAccessError): validate_contract(c)

@pytest.mark.parametrize('old,new',[(b'001.200',b'NaN'),(b'0.000',b'1e3')])
def test_nondecimal_quantities_fail(old,new):
    from manufacturing_platform.sap_access.production_order import parse_response
    with pytest.raises(SapAccessError): parse_response(response().replace(old,new),'123','P001',contract())

def test_real_contract_parser_service_transport_roundtrip(tmp_path):
    import json
    from .test_core import config_file,WSDL
    from manufacturing_platform.sap_access.service import SapAccessService
    from manufacturing_platform.sap_access.transport import SoapTransport,HttpReply
    from manufacturing_platform.sap_access.production_order import FUNCTION
    def element(f):
        attrs=' name="'+f['name']+'"'+(' minOccurs="0" maxOccurs="unbounded"' if f['name']=='item' else '')
        if f.get('type') == 'int': return '<x:element'+attrs+' type="x:int"/>'
        facets='<x:maxLength value="'+str(f.get('max_length',100))+'"/>'+ ('<x:pattern value="'+f['pattern']+'"/>' if 'pattern' in f else '')
        content=('<x:complexType><x:sequence>'+''.join(element(c) for c in f['fields'])+'</x:sequence></x:complexType>' if 'fields' in f else '<x:simpleType><x:restriction base="x:string">'+facets+'</x:restriction></x:simpleType>')
        return '<x:element'+attrs+'>'+content+'</x:element>'
    c=contract(); wsdl=WSDL.replace(b'RFC_PING',FUNCTION.encode())
    for direction in ('request_fields','response_fields'):
        wsdl=wsdl.replace(b'<x:all/>',('<x:sequence>'+''.join(element(f) for f in c[direction])+'</x:sequence>').encode(),1)
    path=config_file(tmp_path); raw=json.loads(open(path).read()); raw['allowed_functions'].append(FUNCTION); open(path,'w').write(json.dumps(raw))
    calls=[]
    def sender(method,path,body,*args):
        calls.append(method); return HttpReply(200,{'Content-Type':'text/xml'},wsdl if method=='GET' else response())
    s=SapAccessService(path,str(tmp_path/'audit.json'),transport_factory=lambda c:SoapTransport(c,sender=sender))
    result=s.production_order('123','P001','admin')
    assert result['quantity']=='001.200' and result['source']['environment']=='test' and calls==['GET','POST']


@pytest.mark.parametrize('name',RETURN_FIELDS)
@pytest.mark.parametrize('drift',[{'fields':[]},{'table':True}])
def test_every_return_member_rejects_nonscalar_shape(name,drift):
    from manufacturing_platform.sap_access.production_order import validate_contract
    c=contract(); next(f for f in c['response_fields'][0]['fields'] if f['name']==name).update(drift)
    with pytest.raises(SapAccessError) as e: validate_contract(c)
    assert e.value.code=='SAP_INVALID_CONTRACT'

@pytest.mark.parametrize('name,drift',[('TYPE',{'max_length':2}),('TYPE',{'type':'int'}),('ROW',{'type':'string'}),('NUMBER',{'pattern':'unreviewed'}),('MESSAGE',{'fraction_digits':1})])
def test_return_type_and_facets_drift_rejected(name,drift):
    from manufacturing_platform.sap_access.production_order import validate_contract
    c=contract(); next(f for f in c['response_fields'][0]['fields'] if f['name']==name).update(drift)
    with pytest.raises(SapAccessError): validate_contract(c)


def test_service_rejects_nested_return_before_invoke(tmp_path,monkeypatch):
    import json
    from .test_core import config_file
    import manufacturing_platform.sap_access.service as mod
    from manufacturing_platform.sap_access.production_order import FUNCTION
    path=config_file(tmp_path); raw=json.loads(open(path).read()); raw['allowed_functions'].append(FUNCTION); open(path,'w').write(json.dumps(raw))
    c=contract(); c['response_fields'][0]['fields'][0]['fields']=[{'name':'DRIFT'}]
    monkeypatch.setattr(mod,'parse_wsdl',lambda *args:c)
    class Transport:
        def __init__(self,c): pass
        def fetch_wsdl(self,fn): return b'synthetic'
        def invoke(self,*args): pytest.fail('unreviewed RETURN must not invoke')
    s=mod.SapAccessService(path,str(tmp_path/'audit.json'),transport_factory=Transport)
    with pytest.raises(SapAccessError) as e: s.production_order('123','P001','admin')
    assert e.value.code=='SAP_INVALID_CONTRACT'

def test_501_components_returns_explicit_limit_code():
    from manufacturing_platform.sap_access.production_order import parse_response
    with pytest.raises(SapAccessError) as e: parse_response(response(count=501),'123','P001',contract())
    assert e.value.code=='SAP_RESULT_LIMIT_EXCEEDED' and e.value.status==502

def test_malformed_component_still_returns_invalid_response():
    from manufacturing_platform.sap_access.production_order import parse_response
    with pytest.raises(SapAccessError) as e:
        parse_response(response().replace(b'<COMPONENT>',b'<COMPONENT>invalid'),'123','P001',contract())
    assert e.value.code=='SAP_INVALID_RESPONSE'

@pytest.mark.parametrize('operation', ['production_order', 'stock_requirements'])
@pytest.mark.parametrize('change_at', ['initial', 'transport'])
def test_native_read_pins_the_configuration_used_for_transport(tmp_path, monkeypatch, operation, change_at):
    import json
    from .test_core import config_file
    from manufacturing_platform.sap_access.service import SapAccessService
    path = config_file(tmp_path)
    raw = json.loads(open(path).read())
    raw['allowed_functions'] += ['BAPI_PRODORD_GET_DETAIL', 'BAPI_MATERIAL_STOCK_REQ_LIST']
    open(path, 'w').write(json.dumps(raw))
    transports = []
    def transport(config):
        transports.append(config)
        raise RuntimeError('must not construct mismatched transport')
    service = SapAccessService(path, str(tmp_path/'audit.json'), transport_factory=transport)
    config, _, audit = service._context()
    contexts = []
    def changing_context():
        contexts.append(True)
        transport_index = 3 if operation == 'production_order' else 2
        binding = 'B' if change_at == 'initial' or len(contexts) == transport_index else 'A'
        return config, binding, audit
    monkeypatch.setattr(service, '_context', changing_context)
    kwargs = {'expected_fingerprint':'A'} if change_at == 'initial' else {}
    with pytest.raises(SapAccessError) as caught:
        getattr(service, operation)('123', 'P001', 'isolated-admin', **kwargs)
    assert caught.value.code == 'SAP_CONFIGURATION_ERROR'
    assert not transports
