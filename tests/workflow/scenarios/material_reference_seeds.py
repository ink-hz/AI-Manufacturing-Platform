"""E33 seed boundary: real commands/admission in the owned store, no source connection."""
from datetime import timedelta
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

from manufacturing_platform.workflow.contracts import Actor
from manufacturing_platform.workflow.service import WorkflowService
from manufacturing_platform.workflow.store import WorkflowStore
from .base import owned_run
from .business import order, revision, work_order
from ..integrations.support import MockRig


class E33Mes:
    """Explicit FakeMes collector; native-shaped evidence is test, never production."""
    def __init__(self):
        self.calls = 0

    def order_materials_configuration(self):
        return {"namespace": "e33-isolated", "fingerprint": "e33-no-source"}

    def configuration_matches(self, fingerprint):
        return fingerprint == "e33-no-source"

    def collect_order_materials(self, order, actor):
        self.calls += 1
        return {**self.order_materials_configuration(), "environment": "test", "site_code": "1000",
                "request_ids": ["E33-FakeMes"], "total": 1, "components": [{"component_key": "R:1",
                "material_id": "E33-M", "required_quantity": "1.00000000000000001",
                "withdrawn_quantity": "0", "unit": "EA", "storage_location": None}]}


def owned_store(context):
    owned_run(context.directory)
    return WorkflowStore(str(context.paths.domain), str(context.paths.authority),
                         dict(id=context.dataset_id, mode="test", label="Simulated workflow acceptance"),
                         business_clock=lambda: context.clock)


def owner(context):
    return Actor(user_id=uuid5(NAMESPACE_URL, f"fixture:{context.seed}:owner"), display_name="owner",
                 configuration_admin=True, read_only=False)


def seed_mes(context):
    # All order prerequisites use the already-running real PF HTTPS commands.
    flow = order(context, quantity=2, product="E33 FakeMes", mode="oem")
    revision(flow)
    wid = work_order(flow, 2)
    assert not flow.api.objects(flow.project, "requirement")
    fake = E33Mes()
    service = WorkflowService(owned_store(context), lambda uid: True, mes_access_service=fake)
    actor, pid = owner(context), UUID(flow.project)
    service.execute(actor, pid, {"action": "mes_order.bind", "operation_id": str(uuid4()),
        "expected_version": service.detail(actor, pid).version, "work_order_id": wid,
        "shop_order": "E33-FakeMes-ORDER", "replace_binding_id": None, "reason": None})
    snapshot = service.mes_materials(actor, pid, UUID(wid))
    reference = {"kind": "mes_component", "binding_id": snapshot["binding"]["id"],
                 "snapshot_id": snapshot["snapshot"]["id"], "component_key": "R:1"}
    context.evidence.record("e33-seed", {"boundary": "actual PF HTTPS order prerequisites; isolated WorkflowService mes_order.bind -> explicit FakeMes collector -> actual snapshot persistence",
        "project": flow.project, "work_order": wid, "reference": reference, "source_calls": fake.calls,
        "environment": "test", "production_access": False})
    return flow.project, reference, fake


def seed_mock_receipt(context):
    # Reuse real mock/admission orchestration. No test endpoint or production injection.
    rig = MockRig(context.directory, core=True, workflow_store=owned_store(context),
                  admin=owner(context), actor=owner(context), now=context.clock)
    refs = rig.core_ready()
    fact = rig.result_fact(rig.execute("wms", dict(operation="wms.receive", commitment_id=str(refs.commitment),
        material_lot_id=str(refs.lot), lot_id="LOT", material_id="M", owner_id="C",
        amount=dict(quantity="2", unit="piece", scale=0), location="receiving", custodian="warehouse",
        supplier_batch="E33-B2", expiry=(context.clock + timedelta(days=30)).date().isoformat())))
    receipt = rig.target(fact, "receipt")
    rig.command("material.define", material_id="WRONG-MATERIAL", lot_id="WRONG-LOT", owner_id="C",
        unit="piece", scale=0, expiry=(context.clock + timedelta(days=30)).date().isoformat(),
        source=rig.manual_source("material_lot"))
    wrong_plan = rig.command("plan.receive", source={**rig.manual_source("plan"), "cutoff": context.clock.isoformat()},
        input_revision_ids=[str(refs.revision)],
        input_order_versions=[{"order_line_id": str(refs.order_line), "version": 1}],
        requirements=[{"work_order_id": str(refs.work_order), "execution_scope": "common",
                       "material_id": "WRONG-MATERIAL", "owner_id": "C", "quantity": "1", "unit": "piece"}])
    reference = {"kind": "source_receipt", "source_key": fact.source_key.model_dump(mode="json")}
    context.evidence.record("e33-seed", {"boundary": "owned MockRig core commands -> explicit mock source execution -> real enterprise admission/projection; subsequent reads/dispatch through actual PF HTTPS",
        "project": rig.project_id, "receipt": receipt, "reference": reference, "production_access": False})
    return str(rig.project_id), str(receipt), str(refs.requirement), reference, str(rig.other_project_id), str(wrong_plan.object_id)
