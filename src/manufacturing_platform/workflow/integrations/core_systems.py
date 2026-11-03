"""Fixed core adapter composition; immutable source execution and consumption shell."""

from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from ..contracts import DomainError
from .catalog import EDGES, OPERATIONS
from .contracts import IntegrationFact, SystemError, SystemReceipt
from .core_guards import SourceSnapshot, project_guard
from .core_projections import project_fact, validate_fact
from .store import canonical_hash


class CoreSystem:
    def __init__(self, store, registry):
        self.store, self.registry = store, registry

    def query(self, project_id, operation_id):
        return self.store.query(project_id, operation_id)

    def query_delivery(self, project_id, delivery_id):
        return self.store.query_delivery(project_id, delivery_id)

    def fact(self, project_id, key):
        return self.store.get_fact(project_id, key)

    def facts(self, *args):
        return self.store.list_facts(*args)

    def make_fact(self, project_id, payload, external_id, *, causes=(), now=None):
        now = now or self.store.clock()
        return IntegrationFact(
            project_id=project_id,
            source=dict(
                system=self.store.system,
                object_type=payload["fact_type"].split(".")[1],
                external_id=str(external_id),
                version=1,
                occurred_at=now,
                collected_at=now,
                evidence="Source-owned committed mock fact",
            ),
            payload=payload,
            external_actor=f"{self.store.system} mock authority",
            evidence="Source-owned committed mock fact",
            caused_by=list(causes),
        )

    def emit(self, tx, fact):
        sequence = self.store.append_fact(tx, fact)
        for edge in EDGES:
            if (
                edge.producer == self.store.system
                and fact.payload.fact_type in edge.fact_types
            ):
                self.store.enqueue(tx, fact, edge.consumer)
        return sequence

    def execute(self, operation):
        with project_guard(self.registry, operation.project_id):
            # Store.execute still verifies hash if the operation already exists.
            old = self.query(operation.project_id, operation.operation_id)
            if old:
                return self.store.execute(operation, lambda *_: None)
            fault = self.store.take_fault(operation.project_id, operation.operation_id)
            observations = SourceSnapshot(self.registry, operation.project_id)
            error = None
            requests = []
            with self.registry.workflow_store.transaction() as tx:
                from .core_preparation import bound_requests

                requests = bound_requests(
                    tx, operation.project_id, operation.operation_id
                )
            try:
                facts = self.prepare(operation, observations)
                with self.registry.workflow_store.transaction() as tx:
                    context = SimpleNamespace(
                        project_id=operation.project_id,
                        now=self.store.clock(),
                        project_version=tx.execute(
                            "SELECT version FROM projects WHERE id=?",
                            (str(operation.project_id),),
                        ).fetchone()[0],
                    )
                    from ..contracts import Actor
                    from uuid import UUID

                    initiator = tx.execute(
                        "SELECT actor_id FROM integration_intents WHERE project_id=? AND id=?",
                        (str(operation.project_id), str(operation.operation_id)),
                    ).fetchone()
                    context.actor = Actor(
                        user_id=UUID(initiator[0]) if initiator else UUID(int=0),
                        display_name="Source operation initiator",
                        configuration_admin=False,
                        read_only=False,
                    )
                    from .core_preparation import bound_requests

                    requests = bound_requests(
                        tx, operation.project_id, operation.operation_id
                    )
                    self.validate_operation(tx, context, operation, requests)
                    for fact in facts:
                        validate_fact(tx, context, fact)
            except DomainError as exc:
                if exc.status >= 500:
                    raise
                error = SystemError(code=exc.code, message=exc.message, retryable=False)
                facts = []

            def apply(tx, op):
                failure = error
                sequence = 0
                tx.execute("SAVEPOINT core_effect")
                try:
                    if failure is None:
                        self.transition(tx, op, facts, observations)
                        for fact in facts:
                            sequence = self.emit(tx, fact)
                except DomainError as exc:
                    tx.execute("ROLLBACK TO core_effect")
                    if exc.status >= 500:
                        raise
                    failure = SystemError(
                        code=exc.code, message=exc.message, retryable=False
                    )
                tx.execute("RELEASE core_effect")
                from .core_authority import next_sequence

                sequence = max(sequence, next_sequence(tx))
                receipt = SystemReceipt(
                    operation_id=op.operation_id,
                    system=op.system,
                    request_hash=canonical_hash(op),
                    phase="rejected" if failure else "accepted",
                    source_keys=[] if failure else [f.source_key for f in facts],
                    sequence=sequence,
                    occurred_at=self.store.clock(),
                    received_at=self.store.clock(),
                    error=failure,
                    posted_at=self.store.clock()
                    if failure is None
                    and op.system == "sap"
                    and any(
                        getattr(f.payload, "posted_at", None) is not None for f in facts
                    )
                    else None,
                )
                if requests:
                    from .core_authority import record_wires

                    record_wires(tx, op, receipt, requests, observations)
                return receipt

            receipt = self.store.execute(operation, apply)
        if fault == "timeout_after_commit":
            raise TimeoutError("Response lost after durable source commit")
        return receipt

    def prepare(self, operation, observations):
        p = operation.payload.model_dump(mode="json")
        tag = OPERATIONS[p.pop("operation")].output_fact_types[0]
        return [
            self.make_fact(
                operation.project_id, dict(fact_type=tag, **p), operation.operation_id
            )
        ]

    def validate_operation(self, tx, context, operation, requests):
        return None

    def transition(self, tx, operation, facts, observations):
        raise DomainError("SOURCE_UNAVAILABLE", 503, "Core transition unavailable")

    def consume(self, delivery):
        with project_guard(self.registry, delivery.project_id):
            observations = SourceSnapshot(self.registry, delivery.project_id)
            original = observations.fact(delivery.fact.source_key)
            if canonical_hash(original) != canonical_hash(delivery.fact):
                raise DomainError(
                    "SOURCE_CONFLICT", 409, "Delivery differs from actual producer"
                )
            return self.store.consume(
                delivery, lambda tx, value: self.consume_fact(tx, value, observations)
            )

    def consume_fact(self, tx, delivery, observations):
        # Consumer inbox itself is the durable causal receipt. Families add only
        # genuine owned effects; retaining another producer's copy creates no stock.
        return None

    def child(self, delivery, payload):
        return self.make_fact(
            delivery.project_id,
            payload,
            uuid5(NAMESPACE_URL, f"{delivery.delivery_id}:{payload['fact_type']}"),
            causes=[delivery.fact.source_key],
        )


def authorize(tx, actor, project_id, value):
    # Generic operation/fact policy and project authorization run before this
    # hook. Domain scope is checked before source commit and again at projection.
    from .core_guards import require

    require(value.project_id == project_id, "Source project mismatch")
    p = value.payload
    if getattr(p, "operation", None) == "mes.prepare" and p.approval_target is not None:
        from .operations import require_action

        require_action(
            tx,
            actor,
            project_id,
            "npi.review"
            if p.approval_target.target_type == "engineering"
            else "nonconformance.disposition",
        )


def register_core(registry):
    from .core_sap import SapSystem
    from .core_wms import WmsSystem
    from .core_mes import MesSystem

    for system, cls in (("sap", SapSystem), ("wms", WmsSystem), ("mes", MesSystem)):
        registry.register(
            system,
            factory=lambda store, cls=cls: cls(store, registry),
            projector=project_fact,
            authorize=authorize,
        )
        from .core_authority import CoreAuthorityAdapter

        registry.register_exchange_adapter(
            system,
            lambda registry, system=system: CoreAuthorityAdapter(system, registry),
        )
