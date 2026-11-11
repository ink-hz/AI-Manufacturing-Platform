"""Validate an entire bounded MES order-material observation."""
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from urllib.parse import urlsplit

from .errors import MesAccessError


def _text(value, *, required=True):
    if value in (None, '') and not required:
        return None
    if type(value) is not str or not 1 <= len(value) <= 128 or value != value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError()
    return value


def _amount(value):
    if type(value) not in (str, int):
        raise ValueError()
    value = str(value)
    if len(value) > 128 or not re.fullmatch(r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', value):
        raise ValueError()
    number = Decimal(value)
    if not number.is_finite() or number < 0:
        raise ValueError()
    return value


def namespace(config):
    url = urlsplit(config.base_url)
    port = url.port
    host = url.hostname.lower()
    if ':' in host:
        host = '[' + host + ']'
    origin = url.scheme.lower() + '://' + host
    if port and port != {'http': 80, 'https': 443}[url.scheme.lower()]:
        origin += ':' + str(port)
    fields = [origin, config.environment, config.site_id.lower() if config.site_id else None, config.site_code]
    return hashlib.sha256(json.dumps(fields, separators=(',', ':')).encode()).hexdigest()


def collect(service, config, fingerprint, store, shop_order, actor_id):
    try:
        size = min(5, config.max_rows)
        source_namespace = namespace(config)
        components, seen, total, requests = [], set(), None, []
        for page in range(1, 21):
            result = service._query(config, source_namespace, store, 'order_materials', {'shopOrder': shop_order}, page, size, actor_id)
            observed = result['total_items']
            if type(observed) is not int:
                raise ValueError()
            if observed == 0:
                raise MesAccessError('MES_ORDER_EMPTY', 422)
            if observed > min(100, 20 * size):
                raise MesAccessError('MES_COLLECTION_LIMIT', 422)
            if observed < 0 or total is not None and observed != total:
                raise MesAccessError('MES_COLLECTION_INCOMPLETE', 502)
            total = observed
            rows = result['rows']
            if len(rows) != min(size, total - (page - 1) * size):
                raise MesAccessError('MES_COLLECTION_INCOMPLETE', 502)
            requests.append(result['request_id'])
            for row in rows:
                if _text(row.get('SHOP_ORDER')) != shop_order:
                    raise MesAccessError('MES_ORDER_MISMATCH', 502)
                reservation = row.get('RSNUM')
                if type(reservation) is int and reservation >= 0:
                    reservation = str(reservation)
                key = (_text(reservation), _text(row.get('RSPOS')))
                if any(':' in item for item in key):
                    raise ValueError()
                if key in seen:
                    raise ValueError()
                seen.add(key)
                components.append({'component_key': ':'.join(key), 'material_id': _text(row.get('MATNR')),
                    'required_quantity': _amount(row.get('BDMNG')), 'withdrawn_quantity': None if row.get('ENMNG') in (None, '') else _amount(row.get('ENMNG')),
                    'unit': _text(row.get('MEINS')), 'storage_location': _text(row.get('LGORT'), required=False)})
            if len(components) == total:
                break
        if len(components) != total:
            raise MesAccessError('MES_COLLECTION_INCOMPLETE', 502)
        if not service.configuration_matches(fingerprint):
            raise MesAccessError('MES_CONFIGURATION_CHANGED', 409)
        return {'namespace': source_namespace, 'fingerprint': fingerprint, 'environment': config.environment,
                'site_code': config.site_code, 'request_ids': requests, 'total': total, 'components': components}
    except (ValueError, TypeError, KeyError, InvalidOperation):
        raise MesAccessError('MES_INVALID_ORDER_MATERIALS', 502) from None
