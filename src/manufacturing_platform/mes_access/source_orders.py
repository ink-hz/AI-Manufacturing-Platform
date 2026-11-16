"""Fixed two-field MES identity reads; no inferred header or project facts."""
import re

from .errors import MesAccessError
from .order_materials import namespace


def source(config):
    return {'system': 'mes', 'origin': 'native', 'fact_role': 'observation',
            'environment': config.environment, 'site_code': config.site_code,
            'namespace': namespace(config)}


def valid_identity(value):
    """Exact order IDs and keyset cursors share one round-trippable alphabet."""
    return (type(value) is str and 1 <= len(value) <= 64
            and value == value.strip()
            and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/ -]{0,63}', value) is not None)


def validate_scope(prefix, after):
    if prefix is not None and (type(prefix) is not str or len(prefix) > 64
            or prefix != prefix.strip()
            or prefix and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.:/ -]{0,63}', prefix)):
        raise MesAccessError('MES_INVALID_QUERY', 400)
    if after is not None and (type(after) is not str or after and not valid_identity(after)):
        raise MesAccessError('MES_INVALID_QUERY', 400)
    return prefix or '', after or None


def items(rows, prefix, after):
    result = []
    previous = after
    for row in rows:
        order = row.get('SHOP_ORDER')
        description = row.get('ORDER_DESC')
        if (not valid_identity(order)
                or not order.startswith(prefix) or previous is not None and order <= previous
                or description is not None and type(description) is not str):
            raise MesAccessError('MES_INVALID_RESPONSE', 502)
        result.append({'shop_order': order, 'description': description})
        previous = order
    return result
