import xml.etree.ElementTree as ET
import pytest
from manufacturing_platform.sap_access.stock_requirements import envelope, parse_response
from manufacturing_platform.sap_access.errors import SapAccessError

NS='urn:sap-com:document:sap:rfc:functions'
SOAP='http://schemas.xmlsoap.org/soap/envelope/'

def test_fixed_envelope_exact_scope_and_flags():
    root=ET.fromstring(envelope('MAT-001','P001'))
    op=root[0][0]
    assert op.tag == '{%s}BAPI_MATERIAL_STOCK_REQ_LIST' % NS
    assert {n.tag:n.text or '' for n in op} == {'EXTENSIONOUT':'','GET_IND_LINES':'','GET_ITEM_DETAILS':'X','GET_TOTAL_LINES':'','MATERIAL':'MAT-001','MRP_IND_LINES':'','MRP_ITEMS':'','MRP_TOTAL_LINES':'','PLANT':'P001'}

@pytest.mark.parametrize('material,plant',[('', 'P001'),('x'*19,'P001'),('MAT','x'*5),('MAT',''),('MAT*','P001'),(None,'P001')])
def test_invalid_scope_rejected(material,plant):
    with pytest.raises(SapAccessError): envelope(material,plant)

def response(status='S', rows='<item><ELEMENT>0001</ELEMENT><QUANTITY>1.200</QUANTITY></item>'):
    return (f'<s:Envelope xmlns:s="{SOAP}" xmlns:r="{NS}"><s:Body><r:BAPI_MATERIAL_STOCK_REQ_LIST.Response><MRP_CONTROL_PARAM/><MRP_LIST/><MRP_STOCK_DETAIL/><RETURN><TYPE>{status}</TYPE></RETURN><EXTENSIONOUT/><MRP_IND_LINES/><MRP_ITEMS>{rows}</MRP_ITEMS><MRP_TOTAL_LINES/></r:BAPI_MATERIAL_STOCK_REQ_LIST.Response></s:Body></s:Envelope>').encode()

def test_response_preserves_strings_and_return():
    result=parse_response(response())
    assert result == {'return':{'TYPE':'S'},'mrp_list':{},'items':[{'ELEMENT':'0001','QUANTITY':'1.200'}]}

@pytest.mark.parametrize('status',['E','A','X'])
def test_business_rejection(status):
    with pytest.raises(SapAccessError) as e: parse_response(response(status))
    assert e.value.code == 'SAP_BUSINESS_FAILURE'

def test_oversized_rows_and_malformed_fail():
    for payload in [response(rows='<item><ELEMENT>x</ELEMENT></item>'*51), b'<broken>']:
        with pytest.raises(SapAccessError): parse_response(payload)

def test_fixed_route_authorizes_and_accepts_only_scope():
    from .test_api import install, private, BASE
    browser, service, _, _ = install()
    service.stock_requirements=lambda material,plant,actor: service._call('stock_requirements', material,plant,actor)
    route=BASE+'/mrp/stock-requirements'
    assert private(browser.post(route,json={'material':'MAT-1','plant':'P001'})).status_code == 200
    assert service.calls == [('stock_requirements','MAT-1','P001','admin-1')]
    service.calls.clear()
    assert private(browser.post(route,json={'material':'MAT-1','plant':'P001','xml':'bad'})).status_code == 422
    assert not service.calls

def test_service_requires_opt_in_before_transport(tmp_path):
    from .test_core import config_file
    from manufacturing_platform.sap_access.service import SapAccessService
    s=SapAccessService(config_file(tmp_path), str(tmp_path/'audit.json'), transport_factory=lambda c: pytest.fail('I/O denied'))
    with pytest.raises(SapAccessError) as e: s.stock_requirements('MAT-1','P001','admin')
    assert e.value.code == 'SAP_FUNCTION_NOT_ALLOWED'
    assert not (tmp_path/'audit.json').exists()

def test_cli_stock_requires_exact_arguments_and_live(monkeypatch, capsys, tmp_path):
    from scripts import verify_sap_access as cli
    class Service:
        def stock_requirements(self, material, plant, actor):
            return {'source':'native_sap','items': [],'request_id':'synthetic'}
    monkeypatch.setattr(cli, 'build_sap_access_service', lambda *_: Service())
    base=['stock-requirements','--config',str(tmp_path/'c'),'--audit',str(tmp_path/'a')]
    with pytest.raises(SystemExit): cli.main(base+['--material','MAT-1','--plant','P001'])
    assert cli.main(base+['--live','--material','MAT-1','--plant','P001']) == 0
    assert 'native_sap' in capsys.readouterr().out

def test_base_unit_is_available_with_items():
    payload=response().replace(b'<MRP_LIST/>', b'<MRP_LIST><BASE_UOM>EA</BASE_UOM></MRP_LIST>')
    assert parse_response(payload)['mrp_list']['BASE_UOM'] == 'EA'

def test_contract_rejects_incomplete_rows():
    contract={'response_fields':[{'name':'MRP_ITEMS','fields':[{'fields':[{'name':'ELEMENT'},{'name':'QUANTITY'},{'name':'UNIT'}]}]}, {'name':'RETURN','fields':[{'name':'TYPE'}]}, {'name':'MRP_LIST','fields':[]}]}
    with pytest.raises(SapAccessError): parse_response(response(), contract)

def test_service_records_intent_before_io_and_never_audits_scope_or_rows(tmp_path, monkeypatch):
    import json
    from .test_core import config_file
    import manufacturing_platform.sap_access.service as mod
    from manufacturing_platform.sap_access.stock_requirements import FUNCTION
    path=config_file(tmp_path); raw=json.loads(open(path).read()); raw['allowed_functions'].append(FUNCTION)
    open(path,'w').write(json.dumps(raw))
    descriptor={'function':FUNCTION,'digest':'a'*64,'soap_action':'http://www.sap.com/'+FUNCTION,
        'request_fields':[{'name':'MATERIAL','max_length':18},{'name':'PLANT','max_length':4}, *({'name':n,'table':True} for n in ['EXTENSIONOUT','MRP_IND_LINES','MRP_ITEMS','MRP_TOTAL_LINES'])],
        'response_fields':[{'name':'MRP_ITEMS','fields':[{'fields':[{'name':'ELEMENT'},{'name':'QUANTITY'}]}]}, {'name':'RETURN','fields':[{'name':'TYPE'}]}, {'name':'MRP_LIST','fields':[]}]}
    monkeypatch.setattr(mod,'parse_wsdl',lambda *args: descriptor)
    class Transport:
        def __init__(self, config):
            assert json.loads((tmp_path/'audit.json').read_text())['events'][-1]['status']=='started'
        def fetch_wsdl(self, fn): return b'wsdl'
        def invoke(self, fn, request, action): return response()
    s=mod.SapAccessService(path, str(tmp_path/'audit.json'), transport_factory=Transport)
    result=s.stock_requirements('MAT-PRIVATE','P001','admin')
    assert result['source']=='native_sap' and result['items'][0]['QUANTITY']=='1.200'
    audit=(tmp_path/'audit.json').read_text()
    assert 'MAT-PRIVATE' not in audit and '1.200' not in audit and 'secret-password' not in audit
    assert [e['status'] for e in json.loads(audit)['events']] == ['started','success']

def test_transport_rejects_arbitrary_stock_xml_before_io():
    from .test_transport import config, Sender
    from manufacturing_platform.sap_access.transport import SoapTransport
    from manufacturing_platform.sap_access.stock_requirements import FUNCTION
    sender=Sender(None)
    t=SoapTransport(config(allowed_functions=(FUNCTION,)),sender=sender)
    for body in [envelope('MAT-1','P001').replace(b'<GET_ITEM_DETAILS>X',b'<GET_ITEM_DETAILS>Y'),
                 envelope('MAT-1','P001').replace(b'</MATERIAL>',b'</MATERIAL><PLAN_SCENARIO>001</PLAN_SCENARIO>')]:
        with pytest.raises(SapAccessError): t.invoke(FUNCTION,body,'http://www.sap.com/'+FUNCTION)
    assert not sender.calls

def test_contract_missing_response_structure_fails_before_invoke(tmp_path, monkeypatch):
    import json
    from .test_core import config_file
    import manufacturing_platform.sap_access.service as mod
    from manufacturing_platform.sap_access.stock_requirements import FUNCTION
    path=config_file(tmp_path); raw=json.loads(open(path).read()); raw['allowed_functions'].append(FUNCTION); open(path,'w').write(json.dumps(raw))
    descriptor={'function':FUNCTION,'digest':'a'*64,'soap_action':'http://www.sap.com/'+FUNCTION,
        'request_fields':[{'name':'MATERIAL','max_length':18},{'name':'PLANT','max_length':4}, *({'name':n,'table':True} for n in ['EXTENSIONOUT','MRP_IND_LINES','MRP_ITEMS','MRP_TOTAL_LINES'])], 'response_fields':[]}
    monkeypatch.setattr(mod,'parse_wsdl',lambda *args: descriptor)
    class Transport:
        def __init__(self, config): pass
        def fetch_wsdl(self, fn): return b'wsdl'
        def invoke(self, *args): pytest.fail('invalid contract must never invoke')
    s=mod.SapAccessService(path, str(tmp_path/'audit.json'), transport_factory=Transport)
    with pytest.raises(SapAccessError) as err: s.stock_requirements('MAT-1','P001','admin')
    assert err.value.code == 'SAP_INVALID_CONTRACT'

def test_cli_does_not_echo_unknown_argument(capsys):
    from scripts.verify_sap_access import main
    with pytest.raises(SystemExit): main(['status','--config','/tmp/c','--audit','/tmp/a','--password','PRIVATE-SECRET'])
    assert 'PRIVATE-SECRET' not in capsys.readouterr().err

@pytest.mark.parametrize('function',['ZMMRFC35','ZMMRFC78','ZPPRFC06'])
def test_legacy_functions_remain_denied_even_if_configured(function):
    from .test_transport import config, Sender, envelope as generic
    from manufacturing_platform.sap_access.transport import SoapTransport
    sender=Sender(None); t=SoapTransport(config(allowed_functions=(function,)),sender=sender)
    with pytest.raises(SapAccessError) as err: t.invoke(function,generic(function),'http://www.sap.com/'+function)
    assert err.value.code=='SAP_FUNCTION_NOT_ALLOWED' and not sender.calls

@pytest.mark.parametrize('replace_from,replace_to', [
    (b'<MRP_ITEMS>', b'<MRP_ITEMS>bad'),
    (b'<item>', b'<item>bad'),
    (b'</ELEMENT>', b'</ELEMENT>bad'),
    (b'<MRP_ITEMS>', b'<MRP_ITEMS bad="1">'),
    (b'<item>', b'<item xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true">'),
    (b'<EXTENSIONOUT/>', b'<EXTENSIONOUT>bad</EXTENSIONOUT>'),
    (b'<MRP_LIST/>', b'<MRP_LIST bad="1"/>'),
])
def test_response_rejects_mixed_text_and_attributes(replace_from,replace_to):
    with pytest.raises(SapAccessError): parse_response(response().replace(replace_from,replace_to))

def synthetic_wsdl():
    from .test_core import WSDL
    from manufacturing_platform.sap_access.stock_requirements import FUNCTION
    def scalar(name, length=10):
        return f'<x:element name="{name}" minOccurs="0"><x:simpleType><x:restriction base="x:string"><x:maxLength value="{length}"/></x:restriction></x:simpleType></x:element>'
    def struct(name, names):
        return '<x:element name="'+name+'"><x:complexType><x:sequence>'+''.join(scalar(n) for n in names)+'</x:sequence></x:complexType></x:element>'
    def table(name, names):
        return '<x:element name="'+name+'"><x:complexType><x:sequence><x:element name="item" minOccurs="0" maxOccurs="unbounded"><x:complexType><x:sequence>'+''.join(scalar(n) for n in names)+'</x:sequence></x:complexType></x:element></x:sequence></x:complexType></x:element>'
    tables=['EXTENSIONOUT','MRP_IND_LINES','MRP_ITEMS','MRP_TOTAL_LINES']
    req=''.join(table(n,['DUMMY']) for n in tables)+scalar('MATERIAL',18)+scalar('PLANT',4)+''.join(scalar(n,1) for n in ['GET_ITEM_DETAILS','GET_IND_LINES','GET_TOTAL_LINES'])
    fields=''.join([struct('MRP_CONTROL_PARAM',['DUMMY']),struct('MRP_LIST',['BASE_UOM']),struct('MRP_STOCK_DETAIL',['DUMMY']),struct('RETURN',['TYPE']),table('EXTENSIONOUT',['DUMMY']),table('MRP_IND_LINES',['DUMMY']),table('MRP_ITEMS',['ELEMENT','QUANTITY','ENTRY_UOM']),table('MRP_TOTAL_LINES',['DUMMY'])])
    value=WSDL.replace(b'RFC_PING',FUNCTION.encode())
    value=value.replace(b'<x:all/>', ('<x:sequence>'+req+'</x:sequence>').encode(),1)
    return value.replace(b'<x:all/>', ('<x:sequence>'+fields+'</x:sequence>').encode(),1)

def synthetic_response(rows):
    return (f'<s:Envelope xmlns:s="{SOAP}" xmlns:r="{NS}"><s:Body><r:BAPI_MATERIAL_STOCK_REQ_LIST.Response><MRP_CONTROL_PARAM><DUMMY/></MRP_CONTROL_PARAM><MRP_LIST><BASE_UOM>EA</BASE_UOM></MRP_LIST><MRP_STOCK_DETAIL><DUMMY/></MRP_STOCK_DETAIL><RETURN><TYPE>S</TYPE></RETURN><EXTENSIONOUT/><MRP_IND_LINES/><MRP_ITEMS>{rows}</MRP_ITEMS><MRP_TOTAL_LINES/></r:BAPI_MATERIAL_STOCK_REQ_LIST.Response></s:Body></s:Envelope>').encode()

@pytest.mark.parametrize('rows,count', [('',0), ('<item><ELEMENT>0001</ELEMENT><QUANTITY>1.200</QUANTITY><ENTRY_UOM>EA</ENTRY_UOM></item>',1)])
def test_real_wsdl_parser_through_service_and_transport(tmp_path, rows, count):
    import json
    from .test_core import config_file
    from manufacturing_platform.sap_access.transport import SoapTransport, HttpReply
    from manufacturing_platform.sap_access.stock_requirements import FUNCTION
    from manufacturing_platform.sap_access.service import SapAccessService
    path=config_file(tmp_path); raw=json.loads(open(path).read()); raw['allowed_functions'].append(FUNCTION); open(path,'w').write(json.dumps(raw))
    calls=[]
    def sender(method,path,body,headers,timeout,cap):
        calls.append((method,path,body))
        return HttpReply(200,{'Content-Type':'text/xml'},synthetic_wsdl() if method=='GET' else synthetic_response(rows))
    s=SapAccessService(path,str(tmp_path/'audit.json'),transport_factory=lambda cfg: SoapTransport(cfg,sender=sender))
    result=s.stock_requirements('MAT-1','P001','admin')
    assert len(result['items'])==count and result['mrp_list']['BASE_UOM']=='EA'
    if count: assert result['items'][0]['QUANTITY']=='1.200' and result['items'][0]['ENTRY_UOM']=='EA'
    assert [call[0] for call in calls]==['GET','POST'] and ET.fromstring(calls[1][2])[0][0][4].text=='MAT-1'

def test_schema_optional_omission_rejected_to_avoid_incomplete_success():
    from manufacturing_platform.sap_access.contracts import parse_wsdl
    from manufacturing_platform.sap_access.stock_requirements import FUNCTION
    contract=parse_wsdl(FUNCTION,synthetic_wsdl())
    with pytest.raises(SapAccessError):
        parse_response(synthetic_response('<item><ELEMENT>0001</ELEMENT><QUANTITY>1.200</QUANTITY></item>'),contract)

@pytest.mark.parametrize('old,new',[(b'<MRP_ITEMS>',b'<MRP_ITEMS>invalid'),
    (b'<item>',b'<item>invalid'),(b'</ELEMENT>',b'</ELEMENT>invalid'),
    (b'<MRP_ITEMS>',b'<MRP_ITEMS bad="x">'),
    (b'<item>',b'<item xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true">'),
    (b'<MRP_TOTAL_LINES/>',b'<MRP_TOTAL_LINES>invalid</MRP_TOTAL_LINES>')])
def test_full_contract_rejects_malformed_structural_nodes(old,new):
    from manufacturing_platform.sap_access.contracts import parse_wsdl
    from manufacturing_platform.sap_access.stock_requirements import FUNCTION
    contract=parse_wsdl(FUNCTION,synthetic_wsdl())
    payload=synthetic_response('<item><ELEMENT>1</ELEMENT><QUANTITY>1.200</QUANTITY><ENTRY_UOM>EA</ENTRY_UOM></item>')
    with pytest.raises(SapAccessError): parse_response(payload.replace(old,new),contract)
