"""Bounded explicit causal delivery; consumer commit always precedes producer ack."""

from pydantic import Field, ValidationError

from ..contracts import DomainError
from .contracts import DeliveryBatch, DeliveryReceipt, SystemError
from .store import canonical, canonical_hash, conflict


class NetworkBatch(DeliveryBatch):
    delivered: int = Field(ge=0)
    duplicate: int = Field(ge=0)
    failed: int = Field(ge=0)
    cursor: str | None = None


class MockNetwork:
    def __init__(self, registry):
        self.registry = registry

    def drain(self, project_id, *, limit=100):
        if self.registry.workflow_store.dataset["mode"] not in {"demo", "test"}:
            raise DomainError("SOURCE_UNAVAILABLE", 503, "Mock network unavailable")
        if type(limit) is not int or not 1 <= limit <= 200:
            raise DomainError("INVALID_PAGINATION", 422, "Invalid delivery limit")
        receipts = []
        duplicates = 0
        cursor = None
        stores = self.registry.existing_stores()
        for producer in stores:
            if len(receipts) >= limit:
                break
            for delivery in producer.pending(project_id, limit - len(receipts)):
                cursor = f"{producer.system}:{delivery.delivery_id}"
                try:
                    self.registry.require_available(delivery.consumer)
                    duplicate = (
                        self.registry.source_store(delivery.consumer).inbox_receipt(
                            project_id, delivery.fact.source_key
                        )
                        is not None
                    )
                    receipt = self.registry.adapter(delivery.consumer).consume(delivery)
                    receipt = DeliveryReceipt.model_validate(receipt)
                    receipt = DeliveryReceipt.model_validate_json(canonical(receipt))
                    if (
                        receipt.delivery_id,
                        receipt.project_id,
                        receipt.consumer,
                        receipt.source_key,
                        receipt.payload_hash,
                    ) != (
                        delivery.delivery_id,
                        delivery.project_id,
                        delivery.consumer,
                        delivery.fact.source_key,
                        delivery.payload_hash,
                    ):
                        conflict("Consumer receipt scope mismatch")
                    if receipt.phase in {"accepted", "rejected"}:
                        durable = self.registry.source_store(
                            delivery.consumer
                        ).inbox_receipt(project_id, delivery.fact.source_key)
                        if durable is None or canonical_hash(durable) != canonical_hash(
                            receipt
                        ):
                            conflict(
                                "Consumer acknowledgment was not durably committed"
                            )
                        producer.acknowledge(delivery.delivery_id, receipt)
                    receipts.append(receipt)
                    duplicates += int(duplicate)
                except (OSError, TimeoutError, DomainError, ValidationError) as exc:
                    # No acknowledgment on transient failure or invalid target receipt.
                    receipts.append(
                        DeliveryReceipt(
                            delivery_id=delivery.delivery_id,
                            project_id=project_id,
                            consumer=delivery.consumer,
                            source_key=delivery.fact.source_key,
                            payload_hash=delivery.payload_hash,
                            phase="pending",
                            received_at=producer.clock(),
                            error=SystemError(
                                code=getattr(exc, "code", "SOURCE_UNAVAILABLE"),
                                message="Causal delivery remains pending",
                                retryable=True,
                            ),
                        )
                    )
        return NetworkBatch(
            project_id=project_id,
            receipts=receipts,
            pending=sum(
                s.pending_count(project_id) for s in self.registry.existing_stores()
            ),
            delivered=sum(r.phase == "accepted" for r in receipts),
            duplicate=duplicates,
            failed=sum(r.phase == "rejected" for r in receipts),
            cursor=cursor,
        )
