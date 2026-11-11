"""Strict finite JSON and bounded business rows; never echo upstream failures."""
import json
import math
import re

from .errors import MesAccessError
from .registry import INTERFACES

MAX_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 6
MAX_NODES = 2000
SENSITIVE_KEY = re.compile(r'password|passwd|pwd|secret|token|cookie|authorization|username|sessionid', re.I)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError()


def _bounded_tree(value, interface):
    nodes = 0

    def visit(item, depth, path=()):
        nonlocal nodes
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            raise ValueError()
        if type(item) is dict:
            if len(item) > 128:
                raise ValueError()
            for key, child in item.items():
                # The current report's inspector name is a business field only
                # at result.page[index].USERNAME, never an authentication field.
                inspector = (interface == 'iqc_inspections' and key == 'USERNAME'
                             and len(path) == 3 and path[:2] == ('result', 'page')
                             and type(path[2]) is int and (type(child) is str or child is None))
                if (len(key) > 128
                        or SENSITIVE_KEY.search(re.sub('[^A-Za-z0-9]', '', key)) and not inspector
                        or any(ord(c) < 32 for c in key)):
                    raise ValueError()
                visit(child, depth + 1, (*path, key))
        elif type(item) is list:
            if len(item) > 128:
                raise ValueError()
            for index, child in enumerate(item):
                visit(child, depth + 1, (*path, index))
        elif type(item) is str:
            if len(item) > 4096 or any(0xD800 <= ord(c) <= 0xDFFF for c in item):
                raise ValueError()
        elif type(item) is int:
            if not -(2**63) <= item < 2**63:
                raise ValueError()
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValueError()
        elif item is not None and type(item) is not bool:
            raise ValueError()
    visit(value, 0)


def parse_query_response(interface, payload, *, page=1, page_size=1):
    if type(interface) is not str or interface not in INTERFACES:
        raise MesAccessError('MES_INTERFACE_DENIED', 404)
    try:
        spec = INTERFACES[interface]
        if (type(page) is not int or not 1 <= page <= 1_000_000
                or spec.pagination_mode == 'bounded_data' and page != 1
                or type(page_size) is not int or not 1 <= page_size <= 5
                or type(payload) is not bytes or len(payload) > MAX_BYTES):
            raise ValueError()
        if payload.lstrip().startswith(b'<'):
            raise MesAccessError('MES_SESSION_EXPIRED', 502)
        root = json.loads(payload.decode('utf-8'), object_pairs_hook=_unique,
                          parse_constant=_invalid_constant,
                          **({'parse_float': str} if interface == 'iqc_receive' else {}))
        _bounded_tree(root, interface)
        if type(root) is not dict or type(root.get('result')) is not dict:
            raise ValueError()
        result = root['result']
        if root.get('status') is not True or result.get('MSTATUS') != 'S':
            raise MesAccessError('MES_BUSINESS_FAILURE', 502)
        rows = result.get(spec.rows_key)
        if type(rows) is not list or len(rows) > page_size or any(type(row) is not dict for row in rows):
            raise ValueError()
        if spec.pagination_mode == 'bounded_data':
            reported_page = result.get('pageNumber', 1)
            if type(reported_page) is not int or reported_page != 1:
                raise ValueError()
            # DATA is a bounded sample, not a paginated population. Neither the
            # row count nor an unproved generic totalItems establishes a total.
            return {'rows': rows, 'total_items': None, 'total_items_known': False,
                    'page': 1, 'page_size': page_size}
        total = result.get('totalItems')
        reported_page = result.get('pageNumber', page if interface == 'iqc_records' else None)
        if (type(total) is not int or not 0 <= total <= 2**31 - 1
                or type(reported_page) is not int or reported_page != page
                or rows and (page - 1) * page_size + len(rows) > total):
            raise ValueError()
        return {'rows': rows, 'total_items': total, 'page': page, 'page_size': page_size}
    except MesAccessError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise MesAccessError('MES_INVALID_RESPONSE', 502) from None
