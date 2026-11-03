"""Bounded explicit causal delivery; consumer commit always precedes producer ack."""

from collections import deque

from pydantic import Field, ValidationError

from ..contracts import DomainError, StrictModel
from .catalog import SYSTEM_IDS
from .contracts import DeliveryBatch, DeliveryReceipt, SystemError
from .core_models import SystemId
from .schema import NETWORK_SCHEDULER_SCHEMA
from .store import canonical, canonical_hash, conflict


class NetworkCursor(StrictModel):
    producer: SystemId
    position: int = Field(strict=True, ge=1)


class ProducerSchedule(StrictModel):
    cursor: NetworkCursor
    turn: int = Field(strict=True, ge=1)


class NetworkBatch(DeliveryBatch):
    delivered: int = Field(ge=0)
    duplicate: int = Field(ge=0)
    failed: int = Field(ge=0)
    cursor: NetworkCursor | None = None


class MockNetwork:
    def __init__(self, registry):
        self.registry = registry

    def _schedule(self, project_id):
        with self.registry.workflow_store.transaction(write=True) as tx:
            # Also supports schema23 databases initialized before this additive fix.
            tx.execute(NETWORK_SCHEDULER_SCHEMA)
            if not tx.execute(
                "SELECT 1 FROM projects WHERE id=?", (str(project_id),)
            ).fetchone():
                raise DomainError("NOT_FOUND", 404, "Network project not found")
            rows = tx.execute(
                "SELECT producer,position,turn FROM integration_network_cursors WHERE project_id=? ORDER BY turn LIMIT 15",
                (str(project_id),),
            ).fetchall()
            return [
                ProducerSchedule(
                    cursor=NetworkCursor(producer=r[0], position=r[1]), turn=r[2]
                )
                for r in rows
            ]

    def _advance(self, project_id, cursor):
        # Scheduling is committed before I/O, independently of source effects.
        # Interrupted work stays pending and is retried after a fair rotation.
        with self.registry.workflow_store.transaction(write=True) as tx:
            turn = tx.execute(
                "SELECT COALESCE(MAX(turn),0)+1 FROM integration_network_cursors WHERE project_id=?",
                (str(project_id),),
            ).fetchone()[0]
            tx.execute(
                "INSERT INTO integration_network_cursors VALUES (?,?,?,?) ON CONFLICT(project_id,producer) DO UPDATE SET position=excluded.position,turn=excluded.turn",
                (str(project_id), cursor.producer, cursor.position, turn),
            )

    def _scheduled(self, project_id, stores, schedule, limit):
        positions = {entry.cursor.producer: entry for entry in schedule}
        ordered = sorted(
            stores,
            key=lambda store: (
                positions[store.system].turn if store.system in positions else 0,
                SYSTEM_IDS.index(store.system),
            ),
        )
        queues = []
        for producer in ordered:
            previous = positions.get(producer.system)
            after = previous.cursor.position if previous else 0
            pending = producer.pending_window(project_id, limit, after=after)
            if after and len(pending) < limit:
                pending += producer.pending_window(
                    project_id, limit - len(pending), through=after
                )
            if pending:
                queues.append((producer, deque(pending)))
        candidates = []
        while queues and len(candidates) < limit:
            next_round = []
            for producer, pending in queues:
                if len(candidates) == limit:
                    break
                candidates.append((producer, pending.popleft()))
                if pending:
                    next_round.append((producer, pending))
            queues = next_round
        return candidates

    def drain(self, project_id, *, limit=100):
        if self.registry.workflow_store.dataset["mode"] not in {"demo", "test"}:
            raise DomainError("SOURCE_UNAVAILABLE", 503, "Mock network unavailable")
        if type(limit) is not int or not 1 <= limit <= 200:
            raise DomainError("INVALID_PAGINATION", 422, "Invalid delivery limit")
        receipts = []
        duplicates = 0
        schedule = self._schedule(project_id)
        cursor = schedule[-1].cursor if schedule else None
        stores = self.registry.existing_stores()
        for producer, scheduled in self._scheduled(project_id, stores, schedule, limit):
            delivery = scheduled.delivery
            cursor = NetworkCursor(
                producer=producer.system, position=scheduled.position
            )
            self._advance(project_id, cursor)
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
                        conflict("Consumer acknowledgment was not durably committed")
                    from .core_guards import project_guard

                    with project_guard(self.registry, project_id):
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
