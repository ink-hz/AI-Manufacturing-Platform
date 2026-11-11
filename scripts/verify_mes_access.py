#!/usr/bin/env python3
"""Read MES status or explicitly run a bounded, audited production read."""
import argparse
import json
import os
import sys
from uuid import UUID

from manufacturing_platform.mes_access import build_mes_access_service
from manufacturing_platform.mes_access.api import _unique_object
from manufacturing_platform.mes_access.errors import MesAccessError
from manufacturing_platform.mes_access.registry import INTERFACES

_MAX_FILTER_BYTES = 4096
_FLAGS = {'configuration_valid', 'enabled', 'read_only', 'credentials_configured',
          'authentication_verified', 'business_query_succeeded',
          'business_data_verified', 'business_reconciled', 'execution_enabled', 'total_items_known'}
_COUNTS = {'version', 'allowed_path_count', 'max_rows', 'audit_retention_events',
           'page', 'page_size', 'total_items', 'default_page_size', 'max_page_size', 'max_page'}


def _summary(result):
    """Project known metadata only; business rows and source bodies stay private."""
    output = {key: value for key, value in result.items()
              if (key in _FLAGS and type(value) is bool)
              or (key in _COUNTS and type(value) is int and value >= 0)}
    if result.get('total_items_known') is False:
        output['total_items'] = None
    if result.get('source') == 'native_mes':
        output['source'] = 'native_mes'
    if result.get('interface') in INTERFACES:
        output['interface'] = result['interface']
    if type(result.get('rows')) is list:
        output['row_count'] = len(result['rows'])
    if type(result.get('interfaces')) is list:
        output['interfaces'] = [_summary(item) for item in result['interfaces']
                                if type(item) is dict and item.get('interface') in INTERFACES]
    if type(result.get('request_id')) is str:
        try:
            output['request_id'] = str(UUID(result['request_id']))
        except ValueError:
            pass
    return output


class _SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default includes unknown argument values (possibly secrets).
        self.exit(2, json.dumps({'code': 'MES_INVALID_ARGUMENTS'}) + '\n')


def main(argv=None):
    parser = _SafeParser(description=__doc__)
    parser.add_argument('operation', choices=['status', 'interfaces', 'diagnose', 'query'])
    parser.add_argument('--config', required=True, help='Absolute private server configuration path')
    parser.add_argument('--audit', required=True, help='Absolute private audit evidence path')
    parser.add_argument('--live', action='store_true', help='Explicitly execute a fixed read against MES')
    parser.add_argument('--interface', choices=tuple(INTERFACES))
    parser.add_argument('--filters', help='JSON object of allowed string filters')
    parser.add_argument('--page', type=int)
    parser.add_argument('--page-size', type=int)
    args = parser.parse_args(argv)
    if not os.path.isabs(args.config) or not os.path.isabs(args.audit):
        parser.error('--config and --audit require absolute paths')
    if args.operation in {'diagnose', 'query'} and not args.live:
        parser.error('diagnose and query require --live')
    if args.operation != 'query' and any(value is not None for value in
            (args.interface, args.filters, args.page, args.page_size)):
        parser.error('query options require the query command')
    filters, page, page_size = {}, args.page if args.page is not None else 1, args.page_size if args.page_size is not None else 1
    if args.operation == 'query':
        if args.interface is None:
            parser.error('query requires --interface')
        try:
            if args.filters is not None:
                if len(args.filters.encode('utf-8')) > _MAX_FILTER_BYTES:
                    raise ValueError()
                filters = json.loads(args.filters, object_pairs_hook=_unique_object)
            spec = INTERFACES[args.interface]
            if (type(filters) is not dict or set(filters) - set(spec.filters)
                    or any(type(value) is not str or len(value) > 128 for value in filters.values())
                    or any(not filters.get(key, '').strip() for key in spec.required_filters)
                    or spec.pagination_mode == 'bounded_data' and page != 1
                    or not 1 <= page <= 1_000_000 or not 1 <= page_size <= 5):
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            parser.error('invalid query filters or pagination')
    try:
        service = build_mes_access_service(args.config, args.audit)
        result = {'status': service.status, 'interfaces': service.interfaces,
                  'diagnose': lambda: service.diagnose('local-cli'),
                  'query': lambda: service.query(args.interface, filters, page, page_size, 'local-cli')}[args.operation]()
        output = _summary(result)
    except MesAccessError as exc:
        # Revalidate even a mutated exception's code before displaying it.
        print(json.dumps({'code': MesAccessError(exc.code).code}))
        return 1
    except Exception:
        print(json.dumps({'code': 'MES_OPERATION_FAILED'}))
        return 1
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
