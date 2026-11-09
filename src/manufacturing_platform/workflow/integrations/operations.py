"""Authorized prepare / external I/O / reauthorize-and-CAS projection boundary."""

from dataclasses import dataclass
from types import MappingProxyType, SimpleNamespace
from typing import Literal
from uuid import UUID, uuid4

from pydantic import model_validator

from ..authorization import require_action, require_project
from ..clock import business_time
from ..commands import BUSINESS_ROLES, COMMAND_REGISTRY, CommandContext
from ..contracts import CommandResult, Dataset, DomainError, MutationResult, StrictModel
from .catalog import OPERATIONS
from .contracts import (
    ExecuteSystemOperation,
    IntegrationFact,
    ProjectionResult,
    PullIntegrationFact,
    QuerySystemOperation,
    RetrySystemOperation,
    SystemOperation,
    SystemReceipt,
)
from .network import MockNetwork, NetworkBatch
from .routing import profile_for
from .store import canonical, canonical_hash, conflict, identity

COMMANDS = (
    ExecuteSystemOperation,
    QuerySystemOperation,
    RetrySystemOperation,
    PullIntegrationFact,
)


class PinnedPull(StrictModel):
    project_id: UUID
    command: PullIntegrationFact
    fact: IntegrationFact

    @model_validator(mode="after")
    def scope(self):
        if (
            self.fact.project_id != self.project_id
            or self.fact.source_key != self.command.source_key
        ):
            raise ValueError("cross-project pull observation")
        return self


class IntegrationStatus(StrictModel):
    intent_id: UUID
    phase: Literal["prepared", "pending", "unknown", "accepted", "rejected", "applied"]
    source_committed: bool | None
    receipt_phase: Literal["accepted", "rejected", "pending", "unknown"] | None
    projection_applied: bool


class IntegrationCommandResult(CommandResult):
    integration: IntegrationStatus
    network: NetworkBatch | None = None


def intent(tx, project_id, intent_id):
    row = tx.execute(
        "SELECT * FROM integration_intents WHERE project_id=? AND id=?",
        (str(project_id), str(intent_id)),
    ).fetchone()
    if not row:
        raise DomainError("NOT_FOUND", 404, "Integration intent not found")
    return row


@dataclass(frozen=True)
class FactPolicy:
    action: str
    target_policies: tuple[tuple[str, str], ...] = ()

    def for_fact(self, fact: IntegrationFact) -> str:
        if self.target_policies:
            return dict(self.target_policies)[fact.payload.target.target_type]
        return self.action


# Fixed server catalog, including the consumer-only WMS IQC projection.
FACT_POLICIES = MappingProxyType(
    {
        **{
            tag: FactPolicy(spec.underlying_action, spec.target_policies)
            for spec in OPERATIONS.values()
            for tag in spec.output_fact_types
        },
        "pdm.bom_confirmation": FactPolicy("engineering.handoff"),
        "wms.qualification": FactPolicy("supply.inspect"),
        "mes.shortage": FactPolicy("expedite.open"),
        "wms.consumption": FactPolicy("execution.record"),
        "sap.variance_posting": FactPolicy("ownership.movement"),
        "sap.receipt_posting": FactPolicy("ownership.movement"),
        "sap.shipment_posting": FactPolicy("shipment.request"),
        "mes.delivery_context": FactPolicy("shipment.request"),
        "mes.test_request": FactPolicy("test_plan.publish"),
        "mes.approval_request": FactPolicy(
            "npi.review",
            (("engineering", "npi.review"), ("quality", "nonconformance.disposition")),
        ),
    }
)


def fact_policy(fact):
    policy = FACT_POLICIES.get(fact.payload.fact_type)
    if policy is None:
        raise DomainError("SOURCE_UNAVAILABLE", 503, "Fact policy is unavailable")
    return policy.for_fact(fact)


class IntegrationService:
    def __init__(self, workflow, registry):
        self.workflow, self.registry = workflow, registry

    @staticmethod
    def intent_id(command):
        return (
            command.intent_id
            if isinstance(command, (QuerySystemOperation, RetrySystemOperation))
            else command.operation_id
        )

    def result(self, tx, result, *, intent_id, network=None):
        row = intent(tx, result.project_id, intent_id)
        receipt = tx.execute(
            "SELECT receipt_json FROM integration_receipts WHERE project_id=? AND intent_id=? ORDER BY attempt DESC LIMIT 1",
            (str(result.project_id), str(intent_id)),
        ).fetchone()
        phase = SystemReceipt.model_validate_json(receipt[0]).phase if receipt else None
        status = IntegrationStatus(
            intent_id=intent_id,
            phase=row["phase"],
            source_committed=True
            if phase == "accepted"
            else False
            if phase == "rejected"
            else None,
            receipt_phase=phase,
            projection_applied=row["phase"] == "applied",
        )
        current = tx.execute(
            "SELECT version FROM projects WHERE id=?", (str(result.project_id),)
        ).fetchone()[0]
        return IntegrationCommandResult(
            **(result.model_dump(mode="json") | {"current_project_version": current}),
            integration=status,
            network=network,
        )

    def _operation(self, tx, project_id, command):
        if isinstance(command, ExecuteSystemOperation):
            return SystemOperation(
                operation_id=command.operation_id,
                system=command.system,
                project_id=project_id,
                payload=command.payload,
            )
        row = intent(tx, project_id, command.intent_id)
        if row["operation"] == "integration.pull":
            return PinnedPull.model_validate_json(row["payload_json"])
        return SystemOperation.model_validate_json(row["payload_json"])

    def _policy(self, tx, actor, pid, operation):
        spec = OPERATIONS[operation.payload.operation]
        require_action(tx, actor, pid, spec.policy_for(operation.payload))
        if spec.policy_for(operation.payload) == "release.decide":
            from ..quality import authorize_release

            authorize_release(
                tx, actor, pid, SimpleNamespace(kind=operation.payload.kind)
            )
        self.registry.authorize(tx, actor, pid, operation)

    def _pull_policy(self, tx, actor, pid, key):
        policy = FACT_POLICIES.get(f"{key.system}.{key.object_type}")
        if policy is None:
            raise DomainError("SOURCE_UNAVAILABLE", 503, "Fact policy unavailable")
        # This admits a read-only preflight. The exact observed target/variant is
        # authorized before persisting any pull intent, and again before apply.
        actions = [p for _, p in policy.target_policies] or [policy.action]
        errors = []
        for action in actions:
            try:
                require_action(tx, actor, pid, action)
                break
            except DomainError as exc:
                errors.append(exc)
        else:
            raise errors[0]
        self.registry.require_available(key.system)

    def authorize(self, tx, actor, project_id, command):
        if not isinstance(command, COMMANDS):
            return
        require_project(tx, actor, project_id)
        if actor.read_only:
            raise DomainError("FORBIDDEN", 403, "Workflow is read-only")
        if self.workflow.store.dataset["mode"] not in {"demo", "test"}:
            raise DomainError("SOURCE_UNAVAILABLE", 503, "Mock source unavailable")
        if profile_for(tx, project_id) != "oem-network-v1":
            raise DomainError(
                "SOURCE_UNAVAILABLE", 503, "Project has no OEM source profile"
            )
        value = (
            command
            if isinstance(command, PullIntegrationFact)
            else self._operation(tx, project_id, command)
        )
        if isinstance(value, PullIntegrationFact):
            saved = tx.execute(
                "SELECT payload_json FROM integration_intents WHERE project_id=? AND id=?",
                (str(project_id), str(value.operation_id)),
            ).fetchone()
            if saved:
                self._admit_fact(
                    tx, actor, project_id, PinnedPull.model_validate_json(saved[0]).fact
                )
            else:
                self._pull_policy(tx, actor, project_id, value.source_key)
        elif isinstance(value, PinnedPull):
            self._admit_fact(tx, actor, project_id, value.fact)
        else:
            self._policy(tx, actor, project_id, value)

    def preflight_pull(self, actor, project_id, command):
        with self.workflow.store.transaction() as tx:
            self.authorize(tx, actor, project_id, command)
            saved = tx.execute(
                "SELECT payload_json FROM integration_intents WHERE project_id=? AND id=?",
                (str(project_id), str(command.operation_id)),
            ).fetchone()
            if saved:
                return PinnedPull.model_validate_json(saved[0]).fact
            project = require_project(tx, actor, project_id)
            if project["version"] != command.expected_version:
                raise DomainError(
                    "VERSION_CONFLICT",
                    409,
                    "Project version changed",
                    {"current_version": project["version"]},
                )
        observation = self.registry.observe_fact(project_id, command.source_key)
        with self.workflow.store.transaction() as tx:
            self._admit_fact(tx, actor, project_id, observation)
        return observation

    def prepare(self, tx, context, command, *, observed_fact=None):
        self.authorize(tx, context.actor, context.project_id, command)
        if isinstance(command, (QuerySystemOperation, RetrySystemOperation)):
            return MutationResult(object_type="project", object_id=context.project_id)
        if isinstance(command, ExecuteSystemOperation):
            value = self._operation(tx, context.project_id, command)
            system, operation, policy = (
                value.system,
                value.payload.operation,
                OPERATIONS[value.payload.operation].policy_for(value.payload),
            )
        else:
            if observed_fact is None:
                raise DomainError(
                    "SOURCE_UNAVAILABLE",
                    503,
                    "Pull requires an authorized preflight observation",
                )
            observed_fact = self._admit_fact(
                tx, context.actor, context.project_id, observed_fact
            )
            value = PinnedPull(
                project_id=context.project_id, command=command, fact=observed_fact
            )
            system, operation, policy = (
                command.source_key.system,
                "integration.pull",
                fact_policy(observed_fact),
            )
        old = tx.execute(
            "SELECT payload_hash FROM integration_intents WHERE id=?",
            (str(command.operation_id),),
        ).fetchone()
        if old:
            if old[0] != canonical_hash(value):
                raise DomainError(
                    "IDEMPOTENCY_CONFLICT", 409, "Intent identity already used"
                )
        else:
            if isinstance(value, SystemOperation) and value.system in {
                "sap",
                "wms",
                "mes",
            }:
                from .core_preparation import prepare_core_effect

                prepare_core_effect(tx, context, value)
            tx.execute(
                "INSERT INTO integration_intents VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(command.operation_id),
                    str(context.project_id),
                    str(context.actor.user_id),
                    system,
                    operation,
                    policy,
                    context.project_version,
                    canonical(value),
                    canonical_hash(value),
                    "prepared",
                    context.now.isoformat(),
                ),
            )
        return MutationResult(object_type="project", object_id=context.project_id)

    def _admit_fact(self, tx, actor, pid, fact):
        fact = IntegrationFact.model_validate_json(canonical(fact))
        if fact.project_id != pid:
            raise DomainError("NOT_FOUND", 404, "Source fact not found")
        require_action(tx, actor, pid, fact_policy(fact))
        if fact_policy(fact) == "release.decide":
            from ..quality import authorize_release

            release_payload = fact.payload
            if fact.payload.fact_type == "mes.delivery_context":
                ancestor = tx.execute(
                    "SELECT fact_json FROM integration_projections WHERE project_id=? AND system=? AND object_type=? AND external_id=? AND version=?",
                    identity(pid, fact.payload.releases[0]),
                ).fetchone()
                if not ancestor:
                    raise DomainError(
                        "PRECONDITION_FAILED",
                        409,
                        "Project the exact release before its delivery context",
                    )
                release = IntegrationFact.model_validate_json(ancestor[0])
                if release.payload.fact_type != "mes.release":
                    conflict("Delivery context has no exact MES release")
                release_payload = release.payload
            authorize_release(
                tx, actor, pid, SimpleNamespace(kind=release_payload.kind)
            )
        self.registry.authorize(tx, actor, pid, fact)
        return fact

    def _project(self, tx, context, fact):
        self._admit_fact(tx, context.actor, context.project_id, fact)
        key = identity(context.project_id, fact.source_key)
        row = tx.execute(
            "SELECT payload_hash,result_json FROM integration_projections WHERE project_id=? AND system=? AND object_type=? AND external_id=? AND version=?",
            key,
        ).fetchone()
        if row:
            if row["payload_hash"] != canonical_hash(fact):
                conflict("Projected source changed")
            return ProjectionResult.model_validate_json(row["result_json"])
        result = ProjectionResult.model_validate(
            self.registry.project(tx, context, fact)
        )
        if (
            result.project_id != context.project_id
            or result.source_key != fact.source_key
            or result.payload_hash != canonical_hash(fact)
        ):
            conflict("Projector identity mismatch")
        # A family cannot smuggle an unrelated or nonexistent object link.
        for ref in result.targets:
            if (
                self.workflow.object_registry.detail(
                    tx, context.project_id, ref.kind, ref.id
                )
                is None
            ):
                raise DomainError("NOT_FOUND", 404, "Projection target not found")
        tx.execute(
            "INSERT INTO integration_projections VALUES (?,?,?,?,?,?,?,?,?)",
            (
                *key,
                canonical_hash(fact),
                canonical(fact),
                canonical(result),
                context.now.isoformat(),
            ),
        )
        for ref in result.targets:
            tx.execute(
                "INSERT INTO integration_object_links VALUES (?,?,?,?,?,?,?,?)",
                (*key, ref.kind.value, str(ref.id), "projected"),
            )
        return result

    def _before_io(self, tx, actor, project_id, command, result):
        self.authorize(tx, actor, project_id, command)
        project = require_project(tx, actor, project_id)
        if project["version"] != result.project_version:
            raise DomainError(
                "VERSION_CONFLICT",
                409,
                "Project changed before source I/O",
                {
                    "intent_id": str(self.intent_id(command)),
                    "source_committed": None,
                    "projection_applied": False,
                    "current_version": project["version"],
                    "current_project_version": project["version"],
                },
            )

    def perform(self, actor, project_id, command, result):
        intent_id = self.intent_id(command)
        with self.workflow.store.transaction() as tx:
            self.authorize(tx, actor, project_id, command)
            row = dict(intent(tx, project_id, intent_id))
            completed = row["phase"] == "applied"
            advance_network = isinstance(
                command, (QuerySystemOperation, RetrySystemOperation)
            )
            if completed and not advance_network:
                return self.result(tx, result, intent_id=intent_id)
            self._before_io(tx, actor, project_id, command, result)
            value = (
                PinnedPull.model_validate_json(row["payload_json"])
                if row["operation"] == "integration.pull"
                else SystemOperation.model_validate_json(row["payload_json"])
            )
        if completed:
            batch = MockNetwork(self.registry).drain(project_id, limit=100)
            with self.workflow.store.transaction() as tx:
                self.authorize(tx, actor, project_id, command)
                return self.result(tx, result, intent_id=intent_id, network=batch)
        adapter = self.registry.adapter(row["system"])
        receipt = None
        facts = []
        phase = "unknown"
        try:
            if isinstance(value, PinnedPull):
                observed = self.registry.observe_fact(
                    project_id, value.command.source_key
                )
                if canonical_hash(observed) != canonical_hash(value.fact):
                    conflict("Pinned pull observation changed")
                from .browse import InboxOrigin, OperationOrigin

                origin = self.registry.source_store(observed.source.system).origin(
                    project_id, observed.source_key
                )
                if isinstance(origin, OperationOrigin):
                    accepted = (
                        origin.operation_receipt.phase == "accepted"
                        and observed.source_key in origin.operation_receipt.source_keys
                    )
                elif isinstance(origin, InboxOrigin):
                    accepted = (
                        origin.inbox_receipt.phase == "accepted"
                        and origin.inbox_receipt.project_id == project_id
                        and origin.inbox_receipt.consumer == observed.source.system
                        and origin.inbox_receipt.source_key in observed.caused_by
                    )
                else:
                    accepted = False
                if not accepted:
                    conflict(
                        "Source fact has no accepted durable operation or causal inbox origin"
                    )
                facts = [observed]
                phase = "accepted"
            else:
                # The durable original ID and full canonical payload are the only retry authority.
                receipt = adapter.query(project_id, value.operation_id)
                if receipt is None and not isinstance(command, QuerySystemOperation):
                    with self.workflow.store.transaction() as tx:
                        self._before_io(tx, actor, project_id, command, result)
                    receipt = adapter.execute(value)
                if receipt is not None:
                    receipt = SystemReceipt.model_validate(receipt)
                    if (
                        receipt.operation_id != value.operation_id
                        or receipt.system != value.system
                        or receipt.request_hash != row["payload_hash"]
                    ):
                        conflict("Source receipt does not match original intent")
                    if len({canonical(k) for k in receipt.source_keys}) != len(
                        receipt.source_keys
                    ):
                        conflict("Duplicate receipt source")
                    self.registry.validate_receipt(value, receipt)
                    allowed = OPERATIONS[value.payload.operation].output_fact_types
                    if any(
                        f"{k.system}.{k.object_type}" not in allowed
                        for k in receipt.source_keys
                    ):
                        conflict("Unexpected source receipt fact type")
                    phase = receipt.phase
                    if phase == "accepted":
                        if not receipt.source_keys:
                            conflict("Accepted receipt has no source facts")
                        facts = [
                            self.registry.observe_fact(project_id, k)
                            for k in receipt.source_keys
                        ]
                        if any(
                            f.project_id != project_id or f.source_key != k
                            for f, k in zip(facts, receipt.source_keys)
                        ):
                            conflict("Source fact scope mismatch")
        except (TimeoutError, OSError):
            phase = "unknown"
        wire_observations = []
        if isinstance(value, PinnedPull) and value.fact.source.system in {
            "sap",
            "wms",
            "mes",
        }:
            from .core_authority import observed_wires

            try:
                source_operation_id = UUID(value.fact.source.external_id)
            except ValueError:
                source_operation_id = None
            if source_operation_id:
                wire_observations = observed_wires(
                    self.registry,
                    project_id,
                    source_operation_id,
                    value.fact.source.system,
                )
        elif receipt is not None and value.system in {"sap", "wms", "mes"}:
            from .core_authority import observed_wires

            wire_observations = observed_wires(
                self.registry, project_id, value.operation_id, value.system
            )
        # Persist observed receipt before any reauthorization/CAS can reject application.
        # This is internal durability only; a revoked caller receives no source evidence.
        with self.workflow.store.transaction(write=True) as tx:
            current = intent(tx, project_id, intent_id)
            if wire_observations:
                from .core_preparation import ensure_core_tables

                ensure_core_tables(tx)
                for exchange_id, raw in wire_observations:
                    old_wire = tx.execute(
                        "SELECT receipt_json FROM integration_core_receipts WHERE project_id=? AND exchange_id=?",
                        (str(project_id), exchange_id),
                    ).fetchone()
                    if old_wire and old_wire[0] != raw:
                        conflict("Original authority receipt changed")
                    if not old_wire:
                        tx.execute(
                            "INSERT INTO integration_core_receipts VALUES (?,?,?)",
                            (str(project_id), exchange_id, raw),
                        )
            if receipt is not None:
                attempt = tx.execute(
                    "SELECT COALESCE(MAX(attempt),0)+1 FROM integration_receipts WHERE project_id=? AND intent_id=?",
                    (str(project_id), str(intent_id)),
                ).fetchone()[0]
                tx.execute(
                    "INSERT INTO integration_receipts VALUES (?,?,?,?,?)",
                    (
                        str(project_id),
                        str(intent_id),
                        attempt,
                        canonical(receipt),
                        receipt.received_at.isoformat(),
                    ),
                )
            if current["phase"] != "applied":
                tx.execute(
                    "UPDATE integration_intents SET phase=? WHERE project_id=? AND id=?",
                    (phase, str(project_id), str(intent_id)),
                )
        batch = None
        if advance_network:
            with self.workflow.store.transaction() as tx:
                self.authorize(tx, actor, project_id, command)
            batch = MockNetwork(self.registry).drain(project_id, limit=100)
        with self.workflow.store.transaction(write=True) as tx:
            self.authorize(tx, actor, project_id, command)
            project = require_project(tx, actor, project_id)
            current = intent(tx, project_id, intent_id)
            if current["phase"] == "applied":
                return self.result(tx, result, intent_id=intent_id, network=batch)
            if project["version"] != result.project_version:
                raise DomainError(
                    "VERSION_CONFLICT",
                    409,
                    "Project changed while source was responding",
                    dict(
                        intent_id=str(intent_id),
                        source_committed=True
                        if receipt and receipt.phase == "accepted"
                        else None,
                        receipt_phase=phase,
                        projection_applied=False,
                        current_version=project["version"],
                        current_project_version=project["version"],
                    ),
                )
            if phase == "rejected" and wire_observations:
                from ..exchange_models import ExternalReceipt

                rejection_context = CommandContext(
                    actor,
                    project_id,
                    project["version"],
                    business_time(tx),
                    Dataset.model_validate(self.workflow.store.dataset),
                    self.workflow.exchange_service,
                )
                changed = False
                for exchange_id, raw in wire_observations:
                    existing = tx.execute(
                        "SELECT receipt_json FROM exchanges WHERE project_id=? AND id=?",
                        (str(project_id), exchange_id),
                    ).fetchone()
                    if existing and existing[0] != raw:
                        self.workflow.exchange_service.apply(
                            tx,
                            rejection_context,
                            ExternalReceipt.model_validate_json(raw),
                        )
                        changed = True
                if changed:
                    tx.execute(
                        "UPDATE projects SET version=version+1 WHERE id=?",
                        (str(project_id),),
                    )
            if phase == "accepted":
                context = CommandContext(
                    actor,
                    project_id,
                    project["version"],
                    business_time(tx),
                    Dataset.model_validate(self.workflow.store.dataset),
                    self.workflow.exchange_service,
                )
                for fact in facts:
                    self._project(tx, context, fact)
                tx.execute(
                    "UPDATE integration_intents SET phase='applied' WHERE project_id=? AND id=?",
                    (str(project_id), str(intent_id)),
                )
                applied_id = uuid4()
                applied = result.model_copy(
                    update={
                        "operation_id": applied_id,
                        "project_version": project["version"] + 1,
                    }
                )
                tx.execute(
                    "UPDATE projects SET version=version+1 WHERE id=?",
                    (str(project_id),),
                )
                self.workflow._save(
                    tx,
                    actor,
                    applied_id,
                    {
                        "action": "integration.apply",
                        "intent_id": str(intent_id),
                        "expected_version": project["version"],
                        "sources": [
                            f.source_key.model_dump(mode="json") for f in facts
                        ],
                    },
                    applied.model_dump(mode="json"),
                    project_id,
                    "integration.apply",
                    project_id,
                )
                result = result.model_copy(
                    update={"current_project_version": project["version"] + 1}
                )
            return self.result(tx, result, intent_id=intent_id, network=batch)


def prepare(tx, context, command):
    return context.exchange_service.workflow.integration_service.prepare(
        tx, context, command
    )


for model in COMMANDS:
    COMMAND_REGISTRY.register(
        model, roles=set(BUSINESS_ROLES), qualifications=set(), handler=prepare
    )
