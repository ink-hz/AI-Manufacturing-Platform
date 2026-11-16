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


def canonical_timestamp(value):
    """Java Timestamp JSON to sortable UTC ISO, retaining all nanoseconds."""
    from datetime import datetime, timezone
    if value is None:
        return None
    if type(value) is not dict:
        raise ValueError()
    millis, nanos = value.get('time'), value.get('nanos')
    if (type(millis) is not int or type(nanos) is not int or not 0 <= nanos < 1_000_000_000
            or millis % 1000 != nanos // 1_000_000):
        raise ValueError()
    stamp = datetime.fromtimestamp(millis // 1000, timezone.utc)
    return stamp.strftime('%Y-%m-%dT%H:%M:%S') + f'.{nanos:09d}Z'


def recent_items(rows, prefix, after):
    try:
        result, seen, previous = [], set(), None
        for row in rows:
            if not {'SHOP_ORDER', 'ORDER_DESC', 'CREATE_DATE', 'HAS_COMPONENTS'} <= row.keys():
                raise ValueError()
            order, description = row.get('SHOP_ORDER'), row.get('ORDER_DESC')
            created = canonical_timestamp(row.get('CREATE_DATE'))
            flag = row.get('HAS_COMPONENTS')
            if (not valid_identity(order) or not order.startswith(prefix) or order == after or order in seen
                    or description is not None and type(description) is not str
                    or type(flag) is not int or flag not in (0, 1)):
                raise ValueError()
            key = (created is not None, created or '', order)
            if previous is not None and key >= previous:
                raise ValueError()
            result.append({'shop_order': order, 'description': description, 'created_at': created,
                           'has_components': bool(flag)})
            seen.add(order)
            previous = key
        return result
    except (ValueError, TypeError, OverflowError, OSError):
        raise MesAccessError('MES_INVALID_RESPONSE', 502) from None
