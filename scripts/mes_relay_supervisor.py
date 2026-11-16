#!/usr/bin/env python3
"""The fixed MES relay lifecycle; SAP retains its independent default profile."""
import sys
from sap_relay_supervisor import main,MES_PROFILE
if __name__=='__main__':sys.exit(main(profile=MES_PROFILE))
