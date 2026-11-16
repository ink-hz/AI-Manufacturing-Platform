#!/usr/bin/env python3
"""The fixed MES relay lifecycle; SAP retains its independent default profile."""
import importlib.util
from pathlib import Path
import sys

# Isolated Python omits the script directory from sys.path. Load only the
# supervisor shipped beside this entrypoint, independent of cwd/PYTHONPATH.
_spec = importlib.util.spec_from_file_location(
    'sap_relay_supervisor', Path(__file__).resolve().with_name('sap_relay_supervisor.py')
)
_supervisor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_supervisor)

if __name__ == '__main__':
    sys.exit(_supervisor.main(profile=_supervisor.MES_PROFILE))
