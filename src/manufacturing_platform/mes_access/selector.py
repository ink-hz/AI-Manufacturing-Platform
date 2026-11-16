"""Lazy local configuration dispatch, with no constructor or attribute I/O."""
from .service import MesAccessService
from .errors import MesAccessError
from .relay_protocol import read_private_json, RelayProtocolError

class MesAccessSelector:
    def __init__(self, config_path, audit_path):
        self.config_path, self.audit_path = config_path, audit_path
    def _service(self):
        try: config=read_private_json(self.config_path, max_bytes=128 * 1024)
        except RelayProtocolError: raise MesAccessError('MES_CONFIGURATION_ERROR') from None
        if config.get('transport') == 'mac_read_relay':
            from .relay_client import RelayMesAccessService
            return RelayMesAccessService(self.config_path,self.audit_path)
        return MesAccessService(self.config_path,self.audit_path)
    def read_context(self): return self._service().read_context()
    def configuration_matches(self, fingerprint):
        try: return self._service().configuration_matches(fingerprint)
        except MesAccessError: return False
    def source_orders(self,prefix='',after='',actor_id=None,*,expected_fingerprint=None):
        return self._service().source_orders_recent(prefix,after,actor_id,expected_fingerprint=expected_fingerprint)
    def query(self,interface,filters=None,page=1,page_size=1,actor_id=None,*,expected_fingerprint=None):
        return self._service().query(interface,filters,page,page_size,actor_id,expected_fingerprint=expected_fingerprint)
    def collect_order_materials(self,shop_order,actor_id,*,expected_fingerprint=None):
        return self._service().collect_order_materials_by_owner(shop_order,actor_id,expected_fingerprint=expected_fingerprint)
    def order_materials_configuration(self):return self._service().order_materials_configuration()
    def status(self):return self._service().status()
    def interfaces(self):return self._service().interfaces()
    def diagnose(self,actor_id):return self._service().diagnose(actor_id)
