"""Closed SAP document/literal WSDL reader; no imports or URL resolution."""
import hashlib
import io
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

from .errors import SapAccessError
from ..sap_connection import KNOWN_SOAP_FUNCTIONS

NS = 'urn:sap-com:document:sap:rfc:functions'
W = '{http://schemas.xmlsoap.org/wsdl/}'
S = '{http://schemas.xmlsoap.org/wsdl/soap/}'
X = '{http://www.w3.org/2001/XMLSchema}'
SOAP = '{http://schemas.xmlsoap.org/soap/envelope/}'
FACETS = {'maxLength': 'max_length', 'totalDigits': 'total_digits',
          'fractionDigits': 'fraction_digits', 'pattern': 'pattern'}
PRIMITIVES = {'string', 'decimal', 'int', 'integer', 'long', 'short', 'byte',
              'boolean', 'float', 'double', 'date', 'time', 'dateTime',
              'nonNegativeInteger', 'positiveInteger', 'unsignedInt', 'unsignedLong',
              'unsignedShort', 'unsignedByte', 'base64Binary', 'hexBinary'}


def _name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]{0,127}', value):
        raise ValueError()
    return value


def _occurs(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,9}', value):
        raise ValueError()
    return int(value)


def safe_xml(payload):
    if (not isinstance(payload, bytes) or len(payload) > 2097152
            or b'\x00' in payload or b'<!DOCTYPE' in payload.upper()
            or b'<!ENTITY' in payload.upper()):
        raise SapAccessError('SAP_UNSAFE_XML')
    try:
        root = ET.fromstring(payload)
        if sum(1 for _ in root.iter()) > 12000:
            raise ValueError()
        return root
    except (ET.ParseError, ValueError, RecursionError):
        raise SapAccessError('SAP_INVALID_XML') from None


def parse_wsdl(function, xml_bytes):
    try:
        return _parse(function, xml_bytes)
    except SapAccessError:
        raise
    except Exception:
        raise SapAccessError('SAP_INVALID_CONTRACT') from None


def _parse(function, xml_bytes):
    if function not in KNOWN_SOAP_FUNCTIONS:
        raise ValueError()
    root = safe_xml(xml_bytes)
    if root.tag != W + 'definitions' or root.get('targetNamespace') != NS:
        raise ValueError()
    prefixes = {}
    for _, pair in ET.iterparse(io.BytesIO(xml_bytes), events=['start-ns']):
        if pair[0] in prefixes and prefixes[pair[0]] != pair[1]:
            raise ValueError()
        prefixes[pair[0]] = pair[1]
    if any(node.tag in {W+'import', X+'import', X+'include', X+'redefine'} for node in root.iter()):
        raise ValueError()

    def qname(value):
        prefix, sep, local = (value or '').partition(':')
        if not sep or prefix not in prefixes:
            raise ValueError()
        _name(local)
        return prefixes[prefix], local

    schemas = root.findall(W+'types/'+X+'schema')
    if len(schemas) != 1 or schemas[0].get('targetNamespace') != NS:
        raise ValueError()
    schema = schemas[0]
    types = {}
    elements = {}
    for node in schema:
        if node.tag not in {X+'element', X+'simpleType', X+'complexType'}:
            raise ValueError()
        target = elements if node.tag == X+'element' else types
        name = _name(node.get('name'))
        if not name or name in target:
            raise ValueError()
        target[name] = node

    expanded_nodes = 0

    def describe(node, depth=0):
        nonlocal expanded_nodes
        expanded_nodes += 1
        if depth > 8 or expanded_nodes > 5000:
            raise ValueError()
        minimum = _occurs(node.get('minOccurs', '1'))
        maximum = node.get('maxOccurs', '1')
        if maximum != 'unbounded' and _occurs(maximum) < minimum:
            raise ValueError()
        data = {'name': _name(node.get('name')), 'required': minimum != 0,
                'min_occurs': minimum, 'max_occurs': maximum}
        typed = node
        if node.get('type'):
            namespace, local = qname(node.get('type'))
            data['type'] = local
            if namespace == NS:
                typed = types[local]
            elif namespace != X[1:-1] or local not in PRIMITIVES:
                raise ValueError()
        restriction = typed.find('.//'+X+'restriction')
        complex_type = typed if typed.tag == X+'complexType' else typed.find(X+'complexType')
        if complex_type is not None:
            groups = list(complex_type)
            if len(groups) != 1 or groups[0].tag not in {X+'all', X+'sequence'}:
                raise ValueError()
            children = list(groups[0])
            if any(child.tag != X+'element' for child in children):
                raise ValueError()
            if len({c.get('name') for c in children}) != len(children):
                raise ValueError()
            data.setdefault('type', 'structure')
            data['fields'] = [describe(child, depth+1) for child in children]
            data['table'] = len(children) == 1 and children[0].get('name') == 'item' and children[0].get('maxOccurs') == 'unbounded'
        elif restriction is not None:
            namespace, base = qname(restriction.get('base'))
            if namespace != X[1:-1] or base not in PRIMITIVES:
                raise ValueError()
            data.setdefault('type', base)
            data['base_type'] = base
            for facet in restriction:
                key = FACETS.get(facet.tag.removeprefix(X))
                if key:
                    if key == 'pattern':
                        value = facet.get('value')
                        if not isinstance(value, str) or len(value) > 2048:
                            raise ValueError()
                    else:
                        value = _occurs(facet.get('value'))
                        if key == 'total_digits' and value < 1:
                            raise ValueError()
                    data[key] = value
                else:
                    raise ValueError()
            if data.get('fraction_digits', 0) > data.get('total_digits', 999999999):
                raise ValueError()
        elif not node.get('type'):
            raise ValueError()
        return data

    # A generated name alone is insufficient: validate message, port and binding.
    port = root.find(W+'portType')
    operation = port.find(W+'operation') if port is not None else None
    binding = root.find(W+'binding')
    if operation is None or binding is None or operation.get('name') != function:
        raise ValueError()
    if qname(binding.get('type')) != (NS, port.get('name')):
        raise ValueError()
    for direction, element in [('input', function), ('output', function+'.Response')]:
        reference = operation.find(W+direction)
        ns, message_name = qname(reference.get('message'))
        message = next(m for m in root.findall(W+'message') if m.get('name') == message_name)
        parts = message.findall(W+'part')
        if ns != NS or len(parts) != 1 or qname(parts[0].get('element')) != (NS, element):
            raise ValueError()
    soap_binding = binding.find(S+'binding')
    bop = binding.find(W+'operation')
    action = bop.find(S+'operation') if bop is not None else None
    if (soap_binding is None or soap_binding.get('style') != 'document'
            or soap_binding.get('transport') != 'http://schemas.xmlsoap.org/soap/http'
            or bop.get('name') != function or action is None
            or action.get('soapAction') != 'http://www.sap.com/'+function):
        raise ValueError()
    for direction in ['input', 'output']:
        body = bop.find(W+direction+'/'+S+'body')
        if body is None or body.get('use') != 'literal':
            raise ValueError()
    address = root.find(W+'service/'+W+'port/'+S+'address')
    advertised = address.get('location') if address is not None else None
    if advertised is not None:
        parsed = urlsplit(advertised)
        if (len(advertised) > 512 or parsed.scheme not in {'http', 'https'}
                or not parsed.hostname or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path != '/sap/bc/soap/rfc'
                or any(ord(c) < 33 for c in advertised)):
            raise ValueError()
        parsed.port  # Reject malformed ports without following the address.
    return {'function': function, 'namespace': NS, 'soap_action': action.get('soapAction'),
            'request_fields': describe(elements[function])['fields'],
            'response_fields': describe(elements[function+'.Response'])['fields'],
            'types': {name: describe(node) for name, node in types.items()},
            'digest': hashlib.sha256(xml_bytes).hexdigest(),
            'soap_endpoint_advertised': advertised}


def ping_envelope():
    root = ET.Element(SOAP+'Envelope')
    ET.SubElement(ET.SubElement(root, SOAP+'Body'), '{'+NS+'}RFC_PING')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def validate_ping(payload):
    root = safe_xml(payload)
    body = root.find(SOAP+'Body')
    if (root.tag != SOAP+'Envelope' or body is None or len(body) != 1
            or [n.tag for n in root] not in [[SOAP+'Body'], [SOAP+'Header', SOAP+'Body']]
            or (root.text or '').strip() or any((n.tail or '').strip() for n in root)
            or (body.text or '').strip()
            or body[0].tag != '{'+NS+'}RFC_PING.Response' or len(body[0])
            or body[0].attrib or (body[0].text or '').strip()
            or (body[0].tail or '').strip()):
        raise SapAccessError('SAP_INVALID_RESPONSE')
