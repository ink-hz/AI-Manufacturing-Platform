"""Fixed two-field MES identity reads; no inferred header or project facts."""
import re

from .errors import MesAccessError
from .order_materials import namespace


def source(config):
    return {'system': 'mes', 'origin': 'native', 'fact_role': 'observation',
            'environment': config.environment, 'site_code': config.site_code,
            'namespace': namespace(config)}


def validate_scope(prefix, after):
    for value in (prefix, after):
        if value is not None and (type(value) is not str or len(value) > 64
                or value and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.:/ -]{0,63}', value)
                or value != value.strip()):
            raise MesAccessError('MES_INVALID_QUERY', 400)
    return prefix or '', after or None


def items(rows, prefix, after):
    result = []
    previous = after
    for row in rows:
        order = row.get('SHOP_ORDER')
        description = row.get('ORDER_DESC')
        if (type(order) is not str or not order or len(order) > 128
                or order != order.strip() or any(ord(c) < 32 for c in order)
                or not order.startswith(prefix) or previous is not None and order <= previous
                or description is not None and type(description) is not str):
            raise MesAccessError('MES_INVALID_RESPONSE', 502)
        result.append({'shop_order': order, 'description': description})
        previous = order
    return result
