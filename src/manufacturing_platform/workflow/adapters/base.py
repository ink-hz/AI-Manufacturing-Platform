from typing import Protocol

from ..exchange_models import AuthoritySnapshot, ExternalReceipt, ExternalRequest


class AuthorityAdapter(Protocol):
    mode: str

    def submit(self, request: ExternalRequest) -> ExternalReceipt: ...
    def query(self, system: str, business_key: str) -> ExternalReceipt | None: ...
    def snapshot(self, system: str, object_type: str) -> AuthoritySnapshot: ...
