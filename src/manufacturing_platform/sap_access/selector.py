"""Lazy local configuration dispatch, with no constructor or attribute I/O."""
from .service import SapAccessService
from .errors import SapAccessError
from .relay_protocol import read_private_json, RelayProtocolError

class SapAccessSelector:
    def __init__(self, config_path, audit_path):
        self.config_path, self.audit_path = config_path, audit_path
    def _service(self):
        try: config=read_private_json(self.config_path)
        except RelayProtocolError: raise SapAccessError('SAP_CONFIGURATION_ERROR') from None
        if config.get('transport') == 'mac_read_relay':
            from .relay_client import RelaySapAccessService
            return RelaySapAccessService(self.config_path,self.audit_path)
        return SapAccessService(self.config_path,self.audit_path)
    def read_context(self): return self._service().read_context()
    def configuration_matches(self, fingerprint):
        try: return self._service().configuration_matches(fingerprint)
        except SapAccessError: return False
    def production_order(self, number, plant, actor_id, *, expected_fingerprint=None):
        return self._service().production_order(number,plant,actor_id,expected_fingerprint=expected_fingerprint)
    def stock_requirements(self, material, plant, actor_id, *, expected_fingerprint=None):
        return self._service().stock_requirements(material,plant,actor_id,expected_fingerprint=expected_fingerprint)
    def status(self): return self._service().status()
    def interfaces(self): return self._service().interfaces()
    def contract(self, function): return self._service().contract(function)
    def ping(self, actor_id): return self._service().ping(actor_id)
    def refresh_contracts(self, actor_id): return self._service().refresh_contracts(actor_id)
