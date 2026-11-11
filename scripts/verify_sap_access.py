#!/usr/bin/env python3
"""Run fixed SAP diagnostics; credentials are read only from a private config."""
import argparse
import json
import sys

from manufacturing_platform.sap_access import build_sap_access_service
from manufacturing_platform.sap_access.errors import SapAccessError


class _SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, json.dumps({'code': 'SAP_INVALID_ARGUMENTS'}) + '\n')


def main(argv=None):
    parser = _SafeParser(description=__doc__)
    parser.add_argument('operation', choices=['status', 'interfaces', 'ping', 'refresh', 'stock-requirements'])
    parser.add_argument('--config', required=True, help='Absolute private server config path')
    parser.add_argument('--audit', required=True, help='Absolute private evidence cache path')
    parser.add_argument('--live', action='store_true', help='Explicitly execute a fixed read-only diagnostic against SAP')
    parser.add_argument('--material')
    parser.add_argument('--plant')
    args = parser.parse_args(argv)
    if args.operation in {'ping', 'refresh', 'stock-requirements'} and not args.live:
        parser.error('ping and refresh require --live')
    if args.operation == 'stock-requirements':
        if not args.material or not args.plant: parser.error('material and plant are required')
    elif args.material is not None or args.plant is not None:
        parser.error('scope is only valid for stock-requirements')
    service = build_sap_access_service(args.config, args.audit)
    try:
        result = {'status': lambda: service.status(), 'interfaces': lambda: service.interfaces(),
                  'ping': lambda: service.ping('local-cli'),
                  'refresh': lambda: service.refresh_contracts('local-cli'),
                  'stock-requirements': lambda: service.stock_requirements(args.material, args.plant, 'local-cli')}[args.operation]()
    except SapAccessError as exc:
        print(json.dumps({'code': exc.code}))
        return 1
    except Exception:
        print(json.dumps({'code': 'SAP_OPERATION_FAILED'}))
        return 1
    if args.operation == 'stock-requirements':
        result = {'source': result['source'], 'request_id': result['request_id'], 'row_count': len(result['items'])}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result.get('failed') else 0


if __name__ == '__main__':
    sys.exit(main())
