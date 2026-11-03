"""Fixed TEST-ONLY family: exercises actual stores/orchestration, no production outcomes."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from manufacturing_platform.workflow.contracts import Actor, GrantChange, ProjectCreate
from manufacturing_platform.workflow.integrations.contracts import (
    AuxiliaryRef,
    IntegrationFact,
    ProjectionResult,
    SystemReceipt,
)
from manufacturing_platform.workflow.integrations.routing import assign_profile
from manufacturing_platform.workflow.integrations.store import canonical_hash
from manufacturing_platform.workflow.service import WorkflowService
from manufacturing_platform.workflow.store import WorkflowStore

from .test_contracts import order_payload

NOW = datetime(2026, 11, 3, tzinfo=UTC)


class TestAdapter:
    __test__ = False

    def __init__(self, store):
        self.store = store
        self.after_commit = None

    def query(self, project_id, operation_id):
        return self.store.query(project_id, operation_id)

    def query_delivery(self, project_id, delivery_id):
        return self.store.query_delivery(project_id, delivery_id)

    def facts(self, *args):
        return self.store.list_facts(*args)

    def fact(self, project_id, key):
        return self.store.get_fact(project_id, key)

    def execute(self, op):
        fault = self.store.take_fault(op.project_id, op.operation_id)

        def apply(tx, operation):
            data = operation.payload.model_dump(mode="json")
            data.pop("operation")
            f = IntegrationFact(
                project_id=operation.project_id,
                source=dict(
                    system="sap",
                    object_type="order",
                    external_id=str(operation.operation_id),
                    version=1,
                    occurred_at=NOW,
                    collected_at=NOW,
                    evidence="test signed",
                ),
                payload=dict(fact_type="sap.order", **data),
                external_actor="test source",
                evidence="test signed",
            )
            seq = self.store.append_fact(tx, f)
            self.store.enqueue(tx, f, "wms")
            return SystemReceipt(
                operation_id=operation.operation_id,
                system="sap",
                request_hash=canonical_hash(operation),
                phase="accepted",
                source_keys=[f.source_key],
                sequence=seq,
                occurred_at=NOW,
                received_at=NOW,
            )

        receipt = self.store.execute(op, apply)
        if self.after_commit:
            fn, self.after_commit = self.after_commit, None
            fn()
        if fault == "timeout_after_commit":
            raise TimeoutError("test crash after source commit")
        return receipt

    def consume(self, delivery):
        def apply(tx, d):
            tx.execute(
                "CREATE TABLE IF NOT EXISTS test_effects(project_id TEXT,delivery_id TEXT UNIQUE)"
            )
            tx.execute(
                "INSERT INTO test_effects VALUES (?,?)",
                (str(d.project_id), str(d.delivery_id)),
            )

        return self.store.consume(delivery, apply)


def test_projector(tx, context, f):
    return ProjectionResult(
        project_id=f.project_id,
        source_key=f.source_key,
        payload_hash=canonical_hash(f),
        targets=[],
        auxiliary=[
            AuxiliaryRef(
                project_id=f.project_id,
                kind="network_context",
                id=UUID(f.source.external_id),
            )
        ],
    )


def test_authorize(tx, actor, pid, value):
    pass


class MockRig:
    def __init__(self, root, mode="test"):
        self.root = Path(root)
        self.mode = mode
        self.admin = Actor(
            user_id=uuid4(),
            display_name="fixture admin",
            configuration_admin=True,
            read_only=False,
        )
        self.actor = Actor(
            user_id=uuid4(),
            display_name="fixture planner",
            configuration_admin=False,
            read_only=False,
        )
        self.reopen()
        self.project_id = self.create_project("A")
        self.other_project_id = self.create_project("B")
        if mode != "production":
            with self.workflow.store.transaction(write=True) as tx:
                assign_profile(tx, self.project_id, "oem-network-v1")
                assign_profile(tx, self.other_project_id, "oem-network-v1")
        self.grant(["project_owner"])

    def reopen(self):
        self.workflow = WorkflowService(
            WorkflowStore(
                str(self.root / "workflow.sqlite3"),
                str(self.root / "erp.sqlite3"),
                dict(id="integration-test", mode=self.mode, label="test"),
                business_clock=lambda: NOW,
            ),
            lambda uid: True,
        )
        self.registry = self.workflow.system_registry
        for system in ("sap", "wms"):
            self.registry.register(
                system,
                factory=TestAdapter,
                projector=test_projector,
                authorize=test_authorize,
            )
        return self

    def create_project(self, name):
        p = ProjectCreate(
            operation_id=uuid4(),
            name=name,
            line_id="L",
            product="P",
            customer_id="C",
            mode="oem",
            unit=dict(code="piece", scale=0),
            quantity="10",
            contract=dict(
                customer_approval_required=False,
                customer_release_required=False,
                acceptance_required=False,
                customer_revision="A",
                internal_revision="A",
                material_ownership_rules="customer",
            ),
        )
        return self.workflow.create_project(self.admin, p).id

    def version(self):
        return self.workflow.detail(
            self.admin, self.project_id, include_progress=False
        ).version

    def grant(self, roles):
        self.workflow.change_grant(
            self.admin,
            self.project_id,
            self.actor.user_id,
            GrantChange(
                operation_id=uuid4(),
                expected_version=self.version(),
                scope=dict(kind="project", project_id=self.project_id),
                roles=roles,
                qualifications=[],
                active=True,
                evidence="explicit test grant",
            ),
        )

    def command(self, action, **fields):
        actor = fields.pop("actor", self.actor)
        return self.workflow.execute(
            actor,
            self.project_id,
            dict(
                action=action,
                operation_id=str(uuid4()),
                expected_version=self.version(),
            )
            | fields,
        )

    def execute(self, system="sap", payload=None, *, operation_id=None, actor=None):
        return self.command(
            "mock_system.execute",
            system=system,
            payload=payload or order_payload(),
            **({"operation_id": str(operation_id)} if operation_id else {}),
            actor=actor or self.actor,
        )

    def query(self, intent_id):
        return self.command("mock_system.query", intent_id=str(intent_id))

    def retry(self, intent_id):
        return self.command("mock_system.retry", intent_id=str(intent_id))

    def pull(self, source_key):
        return self.command(
            "integration.pull", source_key=source_key.model_dump(mode="json")
        )

    def drain(self, limit=100):
        from manufacturing_platform.workflow.integrations.network import MockNetwork

        return MockNetwork(self.registry).drain(self.project_id, limit=limit)

    def fault(self, system, operation_id, name):
        self.registry.adapter(system).store.configure_fault(
            self.project_id, operation_id, name
        )

    def rows(self, system, table):
        assert table in {
            "facts",
            "operations",
            "inbox",
            "outbox",
            "acknowledgments",
            "test_effects",
        }
        with self.registry.adapter(system).store.transaction() as tx:
            return [dict(r) for r in tx.execute(f"SELECT * FROM {table}")]

    def begin_and_commit_source_then_revoke_actor(self):
        original = self.workflow.integration_service.perform
        self.workflow.integration_service.perform = lambda actor, pid, command, result: (
            SimpleNamespace(actor=actor, pid=pid, command=command, result=result)
        )
        attempt = self.execute()
        self.workflow.integration_service.perform = original
        with self.workflow.store.transaction() as tx:
            row = tx.execute(
                "SELECT payload_json FROM integration_intents WHERE id=?",
                (str(attempt.command.operation_id),),
            ).fetchone()
        from manufacturing_platform.workflow.integrations.contracts import (
            SystemOperation,
        )

        operation = SystemOperation.model_validate_json(row[0])
        receipt = self.registry.adapter("sap").execute(operation)
        attempt.operation_id = operation.operation_id
        attempt.source_key = receipt.source_keys[0]
        self.grant(["warehouse"])
        return attempt

    def finish_pending(self, a):
        return self.workflow.integration_service.perform(
            a.actor, a.pid, a.command, a.result
        )

    def projection_count(self, key):
        with self.workflow.store.transaction() as tx:
            return tx.execute(
                "SELECT COUNT(*) FROM integration_projections WHERE project_id=? AND system=? AND object_type=? AND external_id=? AND version=?",
                (
                    str(self.project_id),
                    key.system,
                    key.object_type,
                    key.external_id,
                    key.version,
                ),
            ).fetchone()[0]

    def source_receipt(self, op):
        return self.registry.adapter("sap").query(self.project_id, op)
