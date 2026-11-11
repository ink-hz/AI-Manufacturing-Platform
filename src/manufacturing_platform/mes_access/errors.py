"""Secret-safe failures at the native MES boundary."""
import re


class MesAccessError(Exception):
    def __init__(self, code='MES_UNAVAILABLE', status=503):
        self.code = code if isinstance(code,str) and re.fullmatch(r'MES_[A-Z0-9_]{1,56}',code) else 'MES_UNAVAILABLE'
        self.status = status if type(status) is int and 400 <= status <= 599 else 503
        super().__init__(self.code)
