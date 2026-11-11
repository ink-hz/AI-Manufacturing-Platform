"""Fixed SAP current stock/requirements list, with no planning execution."""
import re
import xml.etree.ElementTree as ET
from .contracts import NS, SOAP, safe_xml
from .errors import SapAccessError

FUNCTION = 'BAPI_MATERIAL_STOCK_REQ_LIST'
MAX_ROWS = 50

def envelope(material, plant):
    if (type(material) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,17}', material)
            or type(plant) is not str or not re.fullmatch(r'[A-Za-z0-9]{1,4}', plant)):
        raise SapAccessError('SAP_INVALID_QUERY', 400)
    root = ET.Element(SOAP+'Envelope')
    op = ET.SubElement(ET.SubElement(root, SOAP+'Body'), '{'+NS+'}'+FUNCTION)
    for key, value in [('EXTENSIONOUT',''), ('GET_IND_LINES',''), ('GET_ITEM_DETAILS','X'),
                       ('GET_TOTAL_LINES',''), ('MATERIAL',material), ('MRP_IND_LINES',''),
                       ('MRP_ITEMS',''), ('MRP_TOTAL_LINES',''), ('PLANT',plant)]:
        ET.SubElement(op, key).text = value
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)

def parse_response(payload, contract=None):
    try:
        root = safe_xml(payload)
        if root.tag != SOAP+'Envelope' or len(root) != 1 or root[0].tag != SOAP+'Body' or len(root[0]) != 1:
            raise ValueError()
        op = root[0][0]
        if op.tag != '{'+NS+'}'+FUNCTION+'.Response': raise ValueError()
        expected = {'MRP_CONTROL_PARAM','MRP_LIST','MRP_STOCK_DETAIL','RETURN','EXTENSIONOUT','MRP_IND_LINES','MRP_ITEMS','MRP_TOTAL_LINES'}
        if {n.tag for n in op} != expected or len(op) != len(expected): raise ValueError()
        def fields(node):
            result = {}
            for child in node:
                if (not re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}',child.tag) or child.tag in result
                        or len(child) or child.attrib or len(child.text or '') > 4096): raise ValueError()
                result[child.tag] = child.text or ''
            return result
        ret = fields(op.find('RETURN'))
        mrp_list = fields(op.find('MRP_LIST'))
        if ret.get('TYPE') not in {'', 'S', 'I', 'W', 'E', 'A', 'X'}: raise ValueError()
        if ret['TYPE'] in {'E','A','X'}: raise SapAccessError('SAP_BUSINESS_FAILURE', 502)
        rows = op.find('MRP_ITEMS')
        if len(rows) > MAX_ROWS or any(n.tag != 'item' for n in rows): raise ValueError()
        items = [fields(n) for n in rows]
        if any(not row for row in items): raise ValueError()
        if contract is not None:
            response_fields = {field['name']: field for field in contract['response_fields']}
            item_spec = response_fields['MRP_ITEMS']['fields'][0]['fields']
            allowed_items = {field['name'] for field in item_spec}
            allowed_return = {field['name'] for field in response_fields['RETURN']['fields']}
            if not allowed_items or not allowed_return or any(set(row) != allowed_items for row in items) or set(ret) != allowed_return or set(mrp_list) != {field['name'] for field in response_fields['MRP_LIST']['fields']}:
                raise ValueError()
        for name in ('EXTENSIONOUT','MRP_IND_LINES','MRP_TOTAL_LINES'):
            if len(op.find(name)): raise ValueError()
        return {'return': ret, 'mrp_list': mrp_list, 'items': items}
    except SapAccessError: raise
    except Exception: raise SapAccessError('SAP_INVALID_RESPONSE', 502) from None
