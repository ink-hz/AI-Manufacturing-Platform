"""Fixed TEST-ONLY family: exercises actual stores/orchestration, no production outcomes."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Literal
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

from .payloads import order_payload

if TYPE_CHECKING:
    from .network_scenarios import ScenarioRefs

NOW = datetime(2026, 11, 3, tzinfo=UTC)


@dataclass
class CoreRefs:
    order: object
    order_line: UUID
    revision: UUID
    work_order: UUID
    requirement: UUID
    commitment: UUID
    lot: UUID
    receipt: object
    units: list
    qualification: object
    quantity: int = 12


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
    def __init__(self, root, mode="test", *, core=False, network=False):
        self.core = core or network
        self.network = network
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
            configure_systems=None if self.network else lambda registry: None,
        )
        self.registry = self.workflow.system_registry
        if self.network:
            return self
        if self.core:
            from manufacturing_platform.workflow.integrations.core_systems import (
                register_core,
            )

            register_core(self.registry)
            for name in (
                "pdm",
                "hr_sap",
                "hr_beisen",
                "hr_dingtalk",
                "plc",
                "product_test",
                "oa",
            ):
                self.registry.register(
                    name,
                    factory=lambda store: PrerequisiteAdapter(store, self.registry),
                    projector=prerequisite_projector,
                    authorize=test_authorize,
                )
        for system in () if self.core else ("sap", "wms"):
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

    def grant(self, roles, qualifications=None):
        self.workflow.change_grant(
            self.admin,
            self.project_id,
            self.actor.user_id,
            GrantChange(
                operation_id=uuid4(),
                expected_version=self.version(),
                scope=dict(kind="project", project_id=self.project_id),
                roles=roles,
                qualifications=qualifications or [],
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
        if self.core and payload and payload.get("kind") == "wms.reserve":
            with self.workflow.store.transaction() as tx:
                req = tx.execute(
                    "SELECT work_order_id FROM requirements WHERE project_id=? AND id=?",
                    (str(self.project_id), payload["requirement_id"]),
                ).fetchone()
                lot = tx.execute(
                    "SELECT * FROM material_lots WHERE project_id=? AND id=?",
                    (str(self.project_id), payload["lot_id"]),
                ).fetchone()
            qualification = next(
                f.source_key
                for f in self.registry.adapter("wms")
                .facts(self.project_id, "qualification", 0, 200)
                .records
                if str(f.payload.material_lot_id) == payload["lot_id"]
            )
            payload = dict(
                operation="wms.reserve",
                requirement_id=payload["requirement_id"],
                work_order_id=req["work_order_id"],
                allocations=[
                    dict(
                        material_lot_id=payload["lot_id"],
                        material_id=lot["material_id"],
                        owner_id=lot["owner_id"],
                        amount=dict(
                            quantity=payload["quantity"],
                            unit=payload["unit"],
                            scale=lot["scale"],
                        ),
                        qualification=qualification.model_dump(),
                    )
                ],
            )
        result = self.command(
            "mock_system.execute",
            system=system,
            payload=payload or order_payload(),
            **({"operation_id": str(operation_id)} if operation_id else {}),
            actor=actor or self.actor,
        )
        if self.core and result.integration.phase == "rejected":
            from manufacturing_platform.workflow.contracts import DomainError

            receipt = self.registry.adapter(system).query(
                self.project_id, result.integration.intent_id
            )
            raise DomainError(receipt.error.code, 409, receipt.error.message)
        return result

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

    def manual_source(self, object_type):
        return dict(
            system="fixture-human",
            object_type=object_type,
            external_id=str(uuid4()),
            version=1,
            mode="manual",
            occurred_at=NOW.isoformat(),
            collected_at=NOW.isoformat(),
            evidence="Documented fixture prerequisite",
        )

    def result_fact(self, result):
        intent_id = result.integration.intent_id
        with self.workflow.store.transaction() as tx:
            row = tx.execute(
                "SELECT system FROM integration_intents WHERE id=?", (str(intent_id),)
            ).fetchone()
        receipt = self.registry.adapter(row[0]).query(self.project_id, intent_id)
        assert receipt.phase == "accepted", receipt
        return self.registry.observe_fact(self.project_id, receipt.source_keys[0])

    def target(self, fact, kind):
        with self.workflow.store.transaction() as tx:
            row = tx.execute(
                "SELECT result_json FROM integration_projections WHERE project_id=? AND system=? AND object_type=? AND external_id=? AND version=?",
                (
                    str(self.project_id),
                    fact.source.system,
                    fact.source.object_type,
                    fact.source.external_id,
                    fact.source.version,
                ),
            ).fetchone()
        return next(
            t.id
            for t in ProjectionResult.model_validate_json(row[0]).targets
            if t.kind == kind
        )

    def core_ready(
        self, *, quantity=12, received=10, accepted=8, work_order_quantity=None
    ):
        self.grant(
            [
                "project_owner",
                "planner",
                "engineering",
                "production",
                "warehouse",
                "quality",
                "supply",
            ],
            ["inspection", "disposition", "quality_release", "readiness_verification"],
        )
        wo_quantity = quantity if work_order_quantity is None else work_order_quantity
        due = (NOW + timedelta(days=7)).date().isoformat()
        if self.network:
            demand_fact = self.result_fact(
                self.execute(
                    "crm",
                    dict(
                        operation="crm.publish_demand",
                        customer_id="C",
                        demand_kind="firm",
                        product="P",
                        amount=dict(quantity=str(quantity), unit="piece", scale=0),
                        due_date=due,
                    ),
                )
            )
            demand = self.target(demand_fact, "demand")
        else:
            demand = self.command(
                "demand.record",
                kind="firm",
                product="P",
                quantity=str(quantity),
                unit="piece",
                due_date=due,
                source=self.manual_source("demand"),
            ).object_id
        for dimension in ("technical", "material", "capacity", "commercial", "quality"):
            self.command(
                "demand.review",
                demand_id=str(demand),
                dimension=dimension,
                decision="approved",
                evidence="Signed fixture review",
            )
        order = self.result_fact(
            self.execute(
                "sap",
                dict(
                    operation="sap.release_order",
                    demand_id=str(demand),
                    customer_id="C",
                    product="P",
                    amount=dict(quantity=str(quantity), unit="piece", scale=0),
                    due_date=due,
                ),
            )
        )
        oid = self.target(order, "order_line")
        revision = self.result_fact(
            self.execute(
                "pdm",
                dict(
                    operation="pdm.publish_revision",
                    bom_materials=[
                        dict(
                            material_id="M",
                            per_unit=dict(quantity="1", unit="piece", scale=0),
                        )
                    ],
                    package_id="PKG",
                    revision="A",
                    customer_revision="A",
                    internal_revision="A",
                    firmware_version="F1",
                    items=[
                        dict(
                            id="drawing",
                            kind="drawing",
                            title="Drawing",
                            revision="A",
                            status="verified",
                            evidence="Released drawing",
                        )
                    ],
                    route_steps=[dict(station="assembly", instruction_version="S1")],
                    test_spec=dict(
                        version="T1",
                        program_version="P1",
                        measurements=[
                            dict(name="voltage", unit="V", lower="4", upper="6")
                        ],
                    ),
                    released_at=NOW.isoformat(),
                ),
            )
        )
        rid = self.target(revision, "revision")
        wo = self.result_fact(
            self.execute(
                "sap",
                dict(
                    operation="sap.release_work_order",
                    order_line_id=str(oid),
                    revision_id=str(rid),
                    released_revision=revision.source_key.model_dump(),
                    amount=dict(quantity=str(wo_quantity), unit="piece", scale=0),
                    trial_amount=dict(quantity="1", unit="piece", scale=0),
                    purpose="production",
                    planned_start=NOW.isoformat(),
                    planned_end=(NOW + timedelta(days=1)).isoformat(),
                ),
            )
        )
        wid = self.target(wo, "work_order")
        self.command(
            "order.allocate",
            order_line_id=str(oid),
            work_order_id=str(wid),
            quantity=str(wo_quantity),
            unit="piece",
        )
        expiry = (NOW + timedelta(days=30)).date().isoformat()
        lid = self.command(
            "material.define",
            material_id="M",
            lot_id="LOT",
            owner_id="C",
            unit="piece",
            scale=0,
            expiry=expiry,
            source=self.manual_source("material_lot"),
        ).object_id
        self.drain()
        self.drain()
        reqid = uuid4()
        self.result_fact(
            self.execute(
                "sap",
                dict(
                    operation="sap.publish_plan",
                    input_revision_ids=[str(rid)],
                    input_order_versions=[dict(order_line_id=str(oid), version=1)],
                    requirements=[
                        dict(
                            requirement_id=str(reqid),
                            work_order_id=str(wid),
                            execution_scope="common",
                            material_id="M",
                            owner_id="C",
                            amount=dict(
                                quantity=str(wo_quantity), unit="piece", scale=0
                            ),
                        )
                    ],
                    cutoff=NOW.isoformat(),
                ),
            )
        )
        if self.network:
            purchase = next(
                f
                for f in self.registry.adapter("sap")
                .facts(self.project_id, "purchase_requirement", 0, 200)
                .records
                if f.payload.requirement_id == reqid
            )
            commitment = uuid4()
            promise = self.result_fact(
                self.execute(
                    "srm",
                    dict(
                        operation="srm.promise",
                        requirement_id=str(reqid),
                        purchase_requirement=purchase.source_key.model_dump(),
                        commitment_id=str(commitment),
                        supplier_id="Supplier",
                        owner_id="C",
                        supply_type="customer",
                        amount=dict(quantity=str(wo_quantity), unit="piece", scale=0),
                        original_due=due,
                        current_due=due,
                        evidence="Confirmed source promise",
                    ),
                )
            )
            self.execute(
                "srm",
                dict(
                    operation="srm.announce_arrival",
                    commitment_id=str(commitment),
                    promise=promise.source_key.model_dump(),
                    material_id="M",
                    supplier_batch="B1",
                    supplier_id="Supplier",
                    amount=dict(quantity=str(wo_quantity), unit="piece", scale=0),
                    expected_at=NOW.isoformat(),
                    coa_reference="COA1",
                    coa_evidence="Expected certificate",
                ),
            )
        else:
            commitment = self.command(
                "supply.commit",
                requirement_id=str(reqid),
                type="customer",
                owner_id="C",
                quantity=str(wo_quantity),
                unit="piece",
                original_due=due,
                current_due=due,
                source=self.manual_source("commitment"),
            ).object_id
        receipt = self.result_fact(
            self.execute(
                "wms",
                dict(
                    operation="wms.receive",
                    commitment_id=str(commitment),
                    material_lot_id=str(lid),
                    lot_id="LOT",
                    material_id="M",
                    owner_id="C",
                    amount=dict(quantity=str(received), unit="piece", scale=0),
                    location="receiving",
                    custodian="warehouse",
                    supplier_batch="B1",
                    expiry=expiry,
                ),
            )
        )
        self.result_fact(
            self.execute(
                "mes",
                dict(
                    operation="mes.inspect",
                    receipt=receipt.source_key.model_dump(),
                    accepted=dict(quantity=str(accepted), unit="piece", scale=0),
                    rejected=dict(
                        quantity=str(received - accepted), unit="piece", scale=0
                    ),
                    evidence="Receipt-specific IQC",
                ),
            )
        )
        self.drain()
        qualification = (
            self.registry.adapter("wms")
            .facts(self.project_id, "qualification", 0, 200)
            .records[0]
        )
        return CoreRefs(
            order=order.source_key,
            order_line=oid,
            revision=rid,
            work_order=wid,
            requirement=reqid,
            commitment=commitment,
            lot=lid,
            receipt=receipt.source_key,
            units=[],
            qualification=qualification.source_key,
            quantity=wo_quantity,
        )

    def connected_scenario(
        self, name: Literal["completion", "shortage", "ecn_return"]
    ) -> "ScenarioRefs":
        from .network_scenarios import connected_scenario

        return connected_scenario(self, name)

    def all_visible_systems(self):
        return self.workflow.integration_systems(self.actor, self.project_id)

    def completed_operations(self, system):
        return sum(
            SystemReceipt.model_validate_json(r["receipt_json"]).phase == "accepted"
            for r in self.rows(system, "operations")
            if r["project_id"] == str(self.project_id)
        )

    def visible_fact_count(self, system):
        from manufacturing_platform.workflow.integrations.catalog import OPERATIONS

        tags = {
            tag.split(".")[1]
            for spec in OPERATIONS.values()
            if spec.system == system
            for tag in spec.output_fact_types
        }
        return sum(
            len(
                self.workflow.integration_facts(
                    self.actor, self.project_id, system, tag, limit=200
                ).records
            )
            for tag in tags
        )

    def edge_evidence(self, edge_id):
        from manufacturing_platform.workflow.integrations.catalog import EDGES
        from manufacturing_platform.workflow.integrations.contracts import (
            NetworkDelivery,
        )

        edge = next(e for e in EDGES if e.id == edge_id)
        for row in self.rows(edge.producer, "outbox"):
            d = NetworkDelivery.model_validate_json(row["delivery_json"])
            if (
                d.project_id != self.project_id
                or d.consumer != edge.consumer
                or d.fact.payload.fact_type not in edge.fact_types
            ):
                continue
            receipt = self.registry.adapter(edge.consumer).query_delivery(
                self.project_id, d.delivery_id
            )
            if receipt and receipt.phase == "accepted":
                detail = self.workflow.integration_fact(
                    self.actor, self.project_id, d.fact.source_key
                )
                if detail.projection:
                    return SimpleNamespace(
                        producer_key=d.fact.source_key,
                        consumer_receipt=receipt,
                        projection_refs=detail.projection.targets
                        + detail.projection.auxiliary,
                    )
        raise AssertionError("No durable projected delivery for " + edge_id)

    def physical_balance(self, lot):
        return self.registry.adapter("wms").balance(self.project_id, lot)

    def original_receipt_bytes(self, system, operation_id):
        with self.registry.adapter(system).store.transaction() as tx:
            return tx.execute(
                "SELECT receipt_json FROM operations WHERE project_id=? AND id=?",
                (str(self.project_id), str(operation_id)),
            ).fetchone()[0]

    def accounting_balance(self, lot):
        from decimal import Decimal

        totals = dict(
            received=Decimal(0),
            picked=Decimal(0),
            returned=Decimal(0),
            consumed=Decimal(0),
            adjustment=Decimal(0),
        )
        with self.registry.adapter("sap").store.transaction() as tx:
            facts = [
                IntegrationFact.model_validate_json(r[0])
                for r in tx.execute(
                    "SELECT fact_json FROM facts WHERE project_id=?",
                    (str(self.project_id),),
                )
            ]
        for fact in facts:
            p = fact.payload
            if p.fact_type == "sap.receipt_posting" and p.material_lot_id == lot:
                totals["received"] += p.amount.quantity
            elif p.fact_type == "sap.variance_posting" and p.material_lot_id == lot:
                totals["adjustment"] += p.counted.quantity - p.expected.quantity
            elif p.fact_type == "sap.accounting_entry":
                field = {
                    "pick": "picked",
                    "return": "returned",
                    "execution": "consumed",
                }.get(p.cause.object_type)
                if field:
                    totals[field] += sum(
                        a.amount.quantity
                        for a in p.allocations
                        if a.material_lot_id == lot
                    )
        return SimpleNamespace(**totals)

    def pick_qualified(self, refs, *, quantity):
        allocation = dict(
            material_lot_id=str(refs.lot),
            material_id="M",
            owner_id="C",
            amount=dict(quantity=str(quantity), unit="piece", scale=0),
            qualification=refs.qualification.model_dump(),
        )
        reservation = self.result_fact(
            self.execute(
                "wms",
                dict(
                    operation="wms.reserve",
                    requirement_id=str(refs.requirement),
                    work_order_id=str(refs.work_order),
                    allocations=[allocation],
                ),
            )
        )
        allocation["reservation"] = reservation.source_key.model_dump()
        return self.result_fact(
            self.execute(
                "wms",
                dict(
                    operation="wms.pick",
                    work_order_id=str(refs.work_order),
                    allocations=[allocation],
                    source_custody=dict(location="receiving", custodian="warehouse"),
                    destination_custody=dict(location="line", custodian="production"),
                    cause=reservation.source_key.model_dump(),
                    evidence="Physical picking",
                ),
            )
        )

    def replay_delivery(self, key, consumer):
        from manufacturing_platform.workflow.integrations.contracts import (
            NetworkDelivery,
        )

        with self.registry.adapter(key.system).store.transaction() as tx:
            row = tx.execute(
                "SELECT delivery_json FROM outbox WHERE project_id=? AND consumer=? AND system=? AND object_type=? AND external_id=? AND version=?",
                (
                    str(self.project_id),
                    consumer,
                    key.system,
                    key.object_type,
                    key.external_id,
                    key.version,
                ),
            ).fetchone()
        return self.registry.adapter(consumer).consume(
            NetworkDelivery.model_validate_json(row[0])
        )

    def sap_post_count(self, key):
        return sum(
            getattr(f.payload, "cause", None) == key
            for tag in (
                "accounting_entry",
                "receipt_posting",
                "shipment_posting",
                "variance_posting",
            )
            for f in self.registry.adapter("sap")
            .facts(self.project_id, tag, 0, 200)
            .records
        )

    def start_ready(self, refs=None, *, sn="SN1"):
        refs = refs or self.core_ready(quantity=12, received=12, accepted=12)
        self.pick_qualified(refs, quantity=refs.quantity)
        with self.workflow.store.transaction() as tx:
            internal_revision = tx.execute(
                "SELECT internal_revision FROM engineering_revisions WHERE id=?",
                (str(refs.revision),),
            ).fetchone()[0]
        self.command(
            "engineering.handoff",
            revision_id=str(refs.revision),
            to_system="MES",
            received_revision=internal_revision,
            decision="accepted",
            evidence="Fixed revision handoff",
        )
        for kind in ("people", "equipment"):
            self.command(
                "readiness.record",
                work_order_id=str(refs.work_order),
                kind=kind,
                reference=kind,
                evidence="Verified readiness",
                decision="verified",
                valid_until=(NOW + timedelta(days=30)).isoformat(),
            )
        self.command("unit.register", work_order_id=str(refs.work_order), sns=[sn])
        with self.workflow.store.transaction() as tx:
            refs.units = [
                dict(unit_id=r["id"], sn=r["sn"])
                for r in tx.execute(
                    "SELECT id,sn FROM units WHERE project_id=? AND work_order_id=?",
                    (str(self.project_id), str(refs.work_order)),
                )
            ]
        refs.test_plan = self.command(
            "test_plan.publish",
            revision_id=str(refs.revision),
            level="final",
            station="assembly",
            equipment="EQ1",
            fixture="FX1",
            algorithm_version="ALG1",
        ).object_id
        refs.preparation = self.result_fact(
            self.execute(
                "mes",
                dict(
                    operation="mes.prepare",
                    work_order_id=str(refs.work_order),
                    unit_ids=[u["unit_id"] for u in refs.units],
                    test_plan_id=str(refs.test_plan),
                    equipment_id="EQ1",
                ),
            )
        )
        employee = self.result_fact(
            self.execute(
                "hr_sap",
                dict(
                    operation="hr_sap.publish_employee",
                    employee_id="E1",
                    display_name="External operator",
                    organization="Factory",
                    position="Assembly",
                    active=True,
                ),
            )
        )
        self.result_fact(
            self.execute(
                "hr_beisen",
                dict(
                    operation="hr_beisen.publish_qualification",
                    employee=employee.source_key.model_dump(),
                    qualification="assembly",
                    training_reference="TRAIN1",
                    valid_from=(NOW - timedelta(days=1)).isoformat(),
                    valid_until=(NOW + timedelta(days=1)).isoformat(),
                    evidence="Actual fixture training",
                ),
            )
        )
        shift = self.result_fact(
            self.execute(
                "hr_dingtalk",
                dict(
                    operation="hr_dingtalk.assign_shift",
                    employee=employee.source_key.model_dump(),
                    work_order_id=str(refs.work_order),
                    shift_id="SHIFT1",
                    starts_at=(NOW - timedelta(hours=1)).isoformat(),
                    ends_at=(NOW + timedelta(hours=8)).isoformat(),
                    attendance="present",
                ),
            )
        )
        request = (
            self.registry.adapter("mes")
            .facts(self.project_id, "process_request", 0, 200)
            .records[-1]
        )
        equipment = self.result_fact(
            self.execute(
                "plc",
                dict(
                    operation="plc.set_state",
                    equipment="EQ1",
                    state="available",
                    program_version="P1",
                    process_request=request.source_key.model_dump(),
                    observed_at=NOW.isoformat(),
                    evidence="Physical equipment ready",
                ),
            )
        )
        self.drain()
        refs.start_payload = dict(
            operation="mes.start",
            work_order_id=str(refs.work_order),
            revision_id=str(refs.revision),
            mode="trial",
            units=refs.units,
            operator=employee.source_key.model_dump(),
            shift=shift.source_key.model_dump(),
            equipment=equipment.source_key.model_dump(),
            occurred_at=NOW.isoformat(),
        )
        return refs

    def pass_unit(self, refs):
        reservation = next(
            f
            for f in self.registry.adapter("wms")
            .facts(self.project_id, "reservation", 0, 200)
            .records
            if f.payload.work_order_id == refs.work_order
        )
        allocation = reservation.payload.allocations[0].model_dump(mode="json")
        allocation.update(
            amount=dict(quantity="1", unit="piece", scale=0),
            reservation=reservation.source_key.model_dump(),
        )
        return self.result_fact(
            self.execute(
                "mes",
                dict(
                    operation="mes.pass",
                    work_order_id=str(refs.work_order),
                    unit=refs.units[0],
                    revision_id=str(refs.revision),
                    operator=refs.start_payload["operator"],
                    shift=refs.start_payload["shift"],
                    equipment=refs.start_payload["equipment"],
                    station="assembly",
                    route_version="S1",
                    program_version="P1",
                    firmware_version="F1",
                    occurred_at=NOW.isoformat(),
                    material_uses=[allocation],
                    result="pass",
                ),
            )
        )

    def measured_ready(self, refs=None, *, sn="SN1"):
        import hashlib, json

        refs = self.start_ready(refs, sn=sn)
        self.execute("mes", refs.start_payload)
        refs.execution = self.pass_unit(refs)
        run = self.command(
            "test_run.start",
            plan_id=str(refs.test_plan),
            unit_id=refs.units[0]["unit_id"],
        )
        request = (
            self.registry.adapter("mes")
            .facts(self.project_id, "test_request", 0, 200)
            .records[-1]
        )
        if self.network:
            prepared = self.result_fact(
                self.execute(
                    "product_test",
                    dict(
                        operation="product_test.prepare_artifact",
                        run_id=str(run.object_id),
                        template="pass-v1",
                    ),
                )
            )
            refs.test = self.result_fact(
                self.execute(
                    "product_test",
                    dict(
                        operation="product_test.run",
                        **prepared.payload.prepared.model_dump(
                            mode="json", exclude={"kind"}
                        ),
                    ),
                )
            )
            refs.run = run.object_id
            self.drain()
            return refs
        artifact_id = uuid4()
        raw = dict(origin="demo", curves=[], logs=["VOLTAGE 5 V"])
        original = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        store = self.registry.adapter("product_test").store
        with store.transaction(write=True) as tx:
            tx.execute(
                "CREATE TABLE IF NOT EXISTS fixture_artifacts(project_id TEXT,artifact_id TEXT,version INTEGER,content BLOB,PRIMARY KEY(project_id,artifact_id,version))"
            )
            tx.execute(
                "INSERT INTO fixture_artifacts VALUES (?,?,1,?)",
                (str(self.project_id), str(artifact_id), original),
            )
        refs.test = self.result_fact(
            self.execute(
                "product_test",
                dict(
                    operation="product_test.run",
                    work_order_id=str(refs.work_order),
                    unit_id=refs.units[0]["unit_id"],
                    revision_id=str(refs.revision),
                    plan_id=str(refs.test_plan),
                    run_id=str(run.object_id),
                    request=request.source_key.model_dump(),
                    station="assembly",
                    test_version="T1",
                    program_version="P1",
                    firmware_version="F1",
                    algorithm_version="ALG1",
                    equipment="EQ1",
                    fixture="FX1",
                    attempt=1,
                    result="pass",
                    measurements=[
                        dict(name="voltage", unit="V", value="5", lower="4", upper="6")
                    ],
                    raw=raw,
                    occurred_at=NOW.isoformat(),
                    artifact_ref=dict(
                        system="product_test",
                        project_id=str(self.project_id),
                        artifact_id=str(artifact_id),
                        version=1,
                        reference="run1",
                    ),
                    artifact_checksum=hashlib.sha256(original).hexdigest(),
                ),
            )
        )
        self.drain()
        return refs

    def change_ready(self, refs):
        revision = (
            self.registry.adapter("pdm")
            .facts(self.project_id, "revision", 0, 200)
            .records[0]
        )
        payload = revision.payload.model_dump(mode="json", exclude={"fact_type"})
        payload.update(revision="B", internal_revision="B")
        payload["items"][0]["revision"] = "B"
        new = self.result_fact(
            self.execute("pdm", dict(operation="pdm.publish_revision", **payload))
        )
        rid = self.target(new, "revision")
        self.command(
            "engineering.handoff",
            revision_id=str(rid),
            to_system="MES",
            received_revision="B",
            decision="accepted",
            evidence="New version handoff",
        )
        self.command(
            "unit.register", work_order_id=str(refs.work_order), sns=["UNSTARTED"]
        )
        with self.workflow.store.transaction() as tx:
            boundary = tx.execute(
                "SELECT id FROM units WHERE project_id=? AND work_order_id=? AND sn='UNSTARTED'",
                (str(self.project_id), str(refs.work_order)),
            ).fetchone()[0]
        change = self.result_fact(
            self.execute(
                "pdm",
                dict(
                    operation="pdm.issue_change",
                    work_order_id=str(refs.work_order),
                    from_revision_id=str(refs.revision),
                    to_revision_id=str(rid),
                    released_revision=new.source_key.model_dump(),
                    boundary_unit_ids=[boundary],
                    reason="Released engineering change",
                ),
            )
        )
        npi = self.command(
            "npi.open",
            revision_id=str(rid),
            product_family="P",
            scenario="change_validation",
            required_checks=["change"],
            work_order_ids=[],
        )
        target = dict(
            target_type="engineering",
            source_key=new.source_key.model_dump(),
            npi_id=str(npi.object_id),
            revision_id=str(rid),
            checks=[
                dict(
                    code="change",
                    required=True,
                    decision="pass",
                    evidence="Approved change check",
                    reason="Verified",
                )
            ],
        )
        request = self.result_fact(
            self.execute(
                "oa",
                dict(
                    operation="oa.request_approval",
                    target=target,
                    requested_by="Engineering",
                    evidence="Version-bound review request",
                ),
            )
        )
        approval = self.result_fact(
            self.execute(
                "oa",
                dict(
                    operation="oa.decide_approval",
                    target=target,
                    request=request.source_key.model_dump(),
                    decision="approved",
                    external_signer="External engineering approver",
                    signed_at=NOW.isoformat(),
                    evidence="Signed change approval",
                ),
            )
        )
        if self.network:
            eco = SimpleNamespace(object_id=self.target(change, "eco"))
        else:
            eco = self.command(
                "eco.open",
                old_revision_id=str(refs.revision),
                new_revision_id=str(rid),
                effective_work_order_ids=[str(refs.work_order)],
                reason="Switch remaining scope to B",
            )
        return SimpleNamespace(
            revision=rid,
            source=new.source_key,
            change=change.source_key,
            approval=approval.source_key,
            eco=eco.object_id,
        )


from manufacturing_platform.workflow.integrations.core_systems import CoreSystem


class PrerequisiteAdapter(CoreSystem):
    """TEST ONLY: concrete released PDM data until Task4 real adapter is available."""

    def consume_fact(self, tx, delivery, observations):
        if self.store.system == "pdm":
            from manufacturing_platform.workflow.integrations.bom_sync import (
                emit_confirmation,
            )

            emit_confirmation(self, tx, delivery, observations)

    def transition(self, tx, operation, facts, observations):
        if operation.payload.operation == "product_test.run":
            import hashlib, json
            from manufacturing_platform.workflow.integrations.core_guards import require

            p = operation.payload
            artifact = tx.execute(
                "SELECT content FROM fixture_artifacts WHERE project_id=? AND artifact_id=? AND version=?",
                (
                    str(operation.project_id),
                    str(p.artifact_ref.artifact_id),
                    p.artifact_ref.version,
                ),
            ).fetchone()
            require(
                artifact is not None
                and hashlib.sha256(artifact[0]).hexdigest() == p.artifact_checksum
                and json.loads(artifact[0]) == p.raw.model_dump(mode="json"),
                "Owned original artifact checksum mismatch",
            )
            cause = observations.fact(p.request)
            require(
                cause.payload.fact_type == "mes.test_request"
                and cause.payload.unit_id == p.unit_id,
                "Test request unit mismatch",
            )
            facts[0] = facts[0].model_copy(update={"caused_by": [p.request]})
            return
        assert operation.payload.operation in {
            "pdm.publish_revision",
            "hr_sap.publish_employee",
            "hr_beisen.publish_qualification",
            "hr_dingtalk.assign_shift",
            "plc.set_state",
            "pdm.issue_change",
            "oa.request_approval",
            "oa.decide_approval",
        }


def prerequisite_projector(tx, context, fact):
    from manufacturing_platform.workflow.engineering import record_revision
    from manufacturing_platform.workflow.engineering_models import RecordRevision
    from manufacturing_platform.workflow.integrations.contracts import ObjectRef

    if fact.source.system == "product_test":
        from manufacturing_platform.workflow.integrations.core_admission import (
            project_test_fact,
        )

        return project_test_fact(tx, context, fact)
    if fact.payload.fact_type != "pdm.revision":
        return test_projector(tx, context, fact)
    payload = fact.payload.model_dump(
        mode="json", exclude={"fact_type", "released_at", "bom_materials"}
    )
    result = record_revision(
        tx,
        context,
        RecordRevision(
            operation_id=uuid4(),
            expected_version=context.project_version,
            action="engineering.revision",
            **payload,
        ),
    )
    return ProjectionResult(
        project_id=context.project_id,
        source_key=fact.source_key,
        payload_hash=canonical_hash(fact),
        targets=[
            ObjectRef(
                project_id=context.project_id,
                kind=result.object_type,
                id=result.object_id,
            )
        ],
    )
