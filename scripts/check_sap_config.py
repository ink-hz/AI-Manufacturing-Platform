"""Check private SAP configuration offline; never attempt an SAP login."""
import argparse
import json

from manufacturing_platform.sap_connection import load_sap_connection_config


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, help='absolute path to private JSON')
    args = parser.parse_args(argv)
    try:
        result = load_sap_connection_config(args.config).summary()
    except ValueError:
        print(json.dumps({'configuration_valid': False, 'error': 'INVALID_SAP_CONFIGURATION'}))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
