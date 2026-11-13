"""Exact single production-order observation; no source business mutations."""
import re
import xml.etree.ElementTree as ET
from .contracts import NS, SOAP
from .errors import SapAccessError
from .transport import _xml_document

FUNCTION = 'BAPI_PRODORD_GET_DETAIL'
MAX_ROWS = 500
# Scalar metadata from the reviewed BAPIRET2 WSDL; no business values.
RETURN_LENGTHS = dict(zip(('TYPE','ID','NUMBER','MESSAGE','LOG_NO','LOG_MSG_NO',
                          'MESSAGE_V1','MESSAGE_V2','MESSAGE_V3','MESSAGE_V4',
                          'PARAMETER','ROW','FIELD','SYSTEM'),
                         (1,20,3,220,20,6,50,50,50,50,32,None,30,10)))
HEADER_FIELDS = ('ORDER_NUMBER', 'PRODUCTION_PLANT', 'MRP_CONTROLLER', 'PRODUCTION_SCHEDULER', 'MATERIAL', 'EXPL_DATE', 'ROUTING_NO', 'RESERVATION_NUMBER', 'SCHED_RELEASE_DATE', 'ACTUAL_RELEASE_DATE', 'FINISH_DATE', 'START_DATE', 'PRODUCTION_FINISH_DATE', 'PRODUCTION_START_DATE', 'ACTUAL_START_DATE', 'ACTUAL_FINISH_DATE', 'SCRAP', 'TARGET_QUANTITY', 'UNIT', 'UNIT_ISO', 'PRIORITY', 'ORDER_TYPE', 'ENTERED_BY', 'ENTER_DATE', 'DELETION_FLAG', 'WBS_ELEMENT', 'CONF_NO', 'CONF_CNT', 'INT_OBJ_NO', 'SCHED_FIN_TIME', 'SCHED_START_TIME', 'COLLECTIVE_ORDER', 'ORDER_SEQ_NO', 'FINISH_TIME', 'START_TIME', 'ACTUAL_START_TIME', 'LEADING_ORDER', 'SALES_ORDER', 'SALES_ORDER_ITEM', 'PROD_SCHED_PROFILE', 'MATERIAL_TEXT', 'SYSTEM_STATUS', 'CONFIRMED_QUANTITY', 'PLAN_PLANT', 'BATCH', 'MATERIAL_EXTERNAL', 'MATERIAL_GUID', 'MATERIAL_VERSION', 'DATE_OF_EXPIRY', 'DATE_OF_MANUFACTURE', 'MATERIAL_LONG')
COMPONENT_FIELDS = ('RESERVATION_NUMBER', 'RESERVATION_ITEM', 'RESERVATION_TYPE', 'DELETION_INDICATOR', 'MATERIAL', 'PROD_PLANT', 'STORAGE_LOCATION', 'SUPPLY_AREA', 'BATCH', 'SPECIAL_STOCK', 'REQ_DATE', 'REQ_QUAN', 'BASE_UOM', 'BASE_UOM_ISO', 'WITHDRAWN_QUANTITY', 'ENTRY_QUANTITY', 'ENTRY_UOM', 'ENTRY_UOM_ISO', 'ORDER_NUMBER', 'MOVEMENT_TYPE', 'ITEM_CATEGORY', 'ITEM_NUMBER', 'SEQUENCE', 'OPERATION', 'BACKFLUSH', 'VALUATION_SPEC_STOCK', 'SYSTEM_STATUS', 'MATERIAL_DESCRIPTION', 'COMMITED_QUANTITY', 'SHORTAGE', 'PURCHASE_REQ_NO', 'PURCHASE_REQ_ITEM', 'MATERIAL_EXTERNAL', 'MATERIAL_GUID', 'MATERIAL_VERSION', 'REQ_SEGMENT', 'STOCK_SEGMENT', 'MATERIAL_LONG', 'REQ_SEG_LONG', 'STK_SEG_LONG')
RETURN_FIELDS = ('TYPE', 'ID', 'NUMBER', 'MESSAGE', 'LOG_NO', 'LOG_MSG_NO', 'MESSAGE_V1', 'MESSAGE_V2', 'MESSAGE_V3', 'MESSAGE_V4', 'PARAMETER', 'ROW', 'FIELD', 'SYSTEM')
FLAGS=('HEADER','POSITIONS','SEQUENCES','OPERATIONS','COMPONENTS','PROD_REL_TOOLS','TRIGGER_POINTS','SUBOPERATIONS')
TABLES=('COMPONENT','FSH_BUNDLES','HEADER','OPERATION','POSITION','PROD_REL_TOOL','SEQUENCE','TRIGGER_POINT')

def scope(number, plant):
    if (type(number) is not str or not re.fullmatch(r'[0-9]{1,12}', number)
            or type(plant) is not str or not re.fullmatch(r'[A-Za-z0-9]{1,4}', plant)):
        raise SapAccessError('SAP_INVALID_QUERY', 400)
    return number.zfill(12), plant


def envelope(number, plant):
    number, _ = scope(number, plant)
    root = ET.Element(SOAP+'Envelope')
    op = ET.SubElement(ET.SubElement(root, SOAP+'Body'), '{'+NS+'}'+FUNCTION)
    for name in ('COLLECTIVE_ORDER','COMPONENT','FSH_BUNDLES','HEADER','NUMBER','OPERATION','ORDER_OBJECTS','POSITION','PROD_REL_TOOL','SEQUENCE','TRIGGER_POINT'):
        node = ET.SubElement(op, name)
        if name == 'NUMBER': node.text = number
        if name == 'ORDER_OBJECTS':
            for flag in FLAGS:
                ET.SubElement(node, flag).text = 'X' if flag in {'HEADER','COMPONENTS'} else ''
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def validate_contract(contract):
    try:
        def named(fields):
            result = {f['name']:f for f in fields}
            if len(result) != len(fields): raise ValueError()
            return result
        req = named(contract['request_fields']); res = named(contract['response_fields'])
        if set(req) != set(TABLES) | {'COLLECTIVE_ORDER','NUMBER','ORDER_OBJECTS'} or set(res) != set(TABLES) | {'RETURN'}: raise ValueError()
        if req['NUMBER']['max_length'] != 12 or req['COLLECTIVE_ORDER']['max_length'] != 1: raise ValueError()
        flags = named(req['ORDER_OBJECTS']['fields'])
        if set(flags) != set(FLAGS) or any(f.get('max_length') != 1 for f in flags.values()): raise ValueError()
        for side in (req, res):
            for name in TABLES:
                table = side[name]
                if not table.get('table') or len(table['fields']) != 1 or table['fields'][0]['name'] != 'item': raise ValueError()
                fields = named(table['fields'][0]['fields'])
                expected = HEADER_FIELDS if name == 'HEADER' else COMPONENT_FIELDS if name == 'COMPONENT' else None
                if expected is not None and (set(fields) != set(expected) or any('fields' in f or f.get('table') for f in fields.values())): raise ValueError()
        return_fields = named(res['RETURN']['fields'])
        if set(return_fields) != set(RETURN_FIELDS) or res['RETURN'].get('table'):
            raise ValueError()
        scalar_keys = {'type','base_type','max_length','pattern','total_digits','fraction_digits'}
        for name, field in return_fields.items():
            if 'fields' in field or field.get('table'):
                raise ValueError()
            expected = ({'type':'int'} if name == 'ROW' else
                        {'type':'string','base_type':'string','max_length':RETURN_LENGTHS[name],
                         **({'pattern':r'\d*'} if name in {'NUMBER','LOG_MSG_NO'} else {})})
            if {key:field[key] for key in scalar_keys if key in field} != expected:
                raise ValueError()
    except (KeyError, TypeError, ValueError, IndexError):
        raise SapAccessError('SAP_INVALID_CONTRACT') from None


def parse_response(payload, number, plant, contract):
    number, plant = scope(number, plant)
    validate_contract(contract)
    try:
        root = _xml_document(payload, 2*1024*1024)
        for node in root.iter():
            if node.attrib or (node.tail or '').strip(): raise ValueError()
        def container(node):
            if node is None or (node.text or '').strip(): raise ValueError()
        for node in (root, root[0], root[0][0]): container(node)
        if root.tag != SOAP+'Envelope' or len(root) != 1 or root[0].tag != SOAP+'Body' or len(root[0]) != 1: raise ValueError()
        op = root[0][0]
        if op.tag != '{'+NS+'}'+FUNCTION+'.Response' or len(op) != len(TABLES)+1 or {n.tag for n in op} != set(TABLES)|{'RETURN'}: raise ValueError()
        def fields(node, names):
            container(node)
            if len(node) != len(names) or {n.tag for n in node} != set(names): raise ValueError()
            if any(len(n) or len(n.text or '') > 4096 for n in node): raise ValueError()
            return {n.tag:n.text or '' for n in node}
        ret = fields(op.find('RETURN'), RETURN_FIELDS)
        if ret['TYPE'] not in {'','S','I','W','E','A','X'}: raise ValueError()
        if ret['TYPE'] in {'E','A','X'}: raise SapAccessError('SAP_BUSINESS_FAILURE',502)
        for name in TABLES:
            container(op.find(name))
            if name not in {'HEADER','COMPONENT'} and len(op.find(name)): raise ValueError()
        headers = op.find('HEADER'); rows = op.find('COMPONENT')
        if len(headers) != 1 or headers[0].tag != 'item' or len(rows) > MAX_ROWS: raise ValueError()
        header = fields(headers[0], HEADER_FIELDS)
        if header['ORDER_NUMBER'] != number or header['PRODUCTION_PLANT'] != plant: raise ValueError()
        def decimal(value):
            if not re.fullmatch(r'[+-]?[0-9]+(?:\.[0-9]+)?', value): raise ValueError()
            return value
        decimal(header['TARGET_QUANTITY'])
        components = []; keys = set()
        for node in rows:
            if node.tag != 'item': raise ValueError()
            row = fields(node, COMPONENT_FIELDS)
            decimal(row['REQ_QUAN']); decimal(row['WITHDRAWN_QUANTITY'])
            if row['ORDER_NUMBER'] != number or row['PROD_PLANT'] != plant: raise ValueError()
            keyparts = [row[n] for n in ('RESERVATION_NUMBER','RESERVATION_ITEM','RESERVATION_TYPE')]
            if (any(not re.fullmatch(r'[0-9]+', p) for p in keyparts[:2])
                    or not re.fullmatch(r'[0-9]*', keyparts[2])): raise ValueError()
            key = ':'.join(keyparts)
            if key in keys: raise ValueError()
            keys.add(key)
            components.append({'component_key':key,'material':row['MATERIAL_LONG'] or row['MATERIAL'],
                'plant':row['PROD_PLANT'],'storage_location':row['STORAGE_LOCATION'],
                'required_quantity':row['REQ_QUAN'],'withdrawn_quantity':row['WITHDRAWN_QUANTITY'],
                'unit':row['BASE_UOM'],'required_at':row['REQ_DATE']})
        return {'number':number,'plant':plant,'material':header['MATERIAL_LONG'] or header['MATERIAL'],
                'description':header['MATERIAL_TEXT'],'quantity':header['TARGET_QUANTITY'],
                'unit':header['UNIT'],'components':components,'total':len(components)}
    except SapAccessError: raise
    except Exception: raise SapAccessError('SAP_INVALID_RESPONSE',502) from None
