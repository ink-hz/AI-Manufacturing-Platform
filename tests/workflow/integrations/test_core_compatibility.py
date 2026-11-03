"""Core composition and the separate immutable legacy ERP authority boundary."""

from manufacturing_platform.workflow.service import WorkflowService
from manufacturing_platform.workflow.store import WorkflowStore


def test_runtime_registers_core_factories_without_opening_sources(tmp_path):
    service = WorkflowService(
        WorkflowStore(
            str(tmp_path / "workflow.sqlite3"),
            str(tmp_path / "erp.sqlite3"),
            dict(id="composition", mode="test", label="Test"),
        ),
        lambda _: True,
    )
    assert all(service.system_registry.available(s) for s in ("sap", "wms", "mes"))
    assert not (tmp_path / "mock-systems").exists()
    assert not (tmp_path / "erp.sqlite3").exists()


def test_production_constructs_no_mock_adapters_or_sources(tmp_path):
    service = WorkflowService(
        WorkflowStore(
            str(tmp_path / "workflow.sqlite3"),
            str(tmp_path / "erp.sqlite3"),
            dict(id="composition", mode="production", label="Production"),
        ),
        lambda _: True,
    )
    assert not any(service.system_registry.available(s) for s in ("sap", "wms", "mes"))
    assert not (tmp_path / "mock-systems").exists()
    assert not (tmp_path / "erp.sqlite3").exists()


def test_source22_original_wire_and_stock_proof_survive_schema23(tmp_path):
    import sqlite3
    from manufacturing_platform.workflow.exchange_models import ExternalRequest
    from manufacturing_platform.workflow.integrations.routing import profile_for
    from .legacy22_authority import GOLDEN
    from .test_profile_migration import freeze22, store, PID

    freeze22(tmp_path)
    source = sqlite3.connect(tmp_path / "authority.sqlite3")
    source.executescript(GOLDEN["sql"])
    source.close()
    workflow_store = store(tmp_path)
    service = WorkflowService(workflow_store, lambda _: True)
    with workflow_store.transaction() as tx:
        assert profile_for(tx, PID) == "legacy-erp-v1"
        assert tx.execute("SELECT version FROM schema_version").fetchone()[0] == 23
    adapter = service.system_registry.exchange_adapter("erp")
    request = ExternalRequest.model_validate_json(GOLDEN["request"])
    assert (
        adapter.query("erp", request.business_key).model_dump_json()
        == GOLDEN["receipt"]
    )
    assert adapter.submit(request).model_dump_json() == GOLDEN["receipt"]
    proof = adapter.stock_basis(
        ExternalRequest.model_validate_json(GOLDEN["proof_request"])
    )
    assert proof.model_dump_json() == GOLDEN["proof"]
    with adapter.store.transaction() as tx:
        row = tx.execute(
            "SELECT request_json,receipt_json,request_hash FROM authority_operations WHERE business_key=?",
            (request.business_key,),
        ).fetchone()
        assert tuple(row) == (
            GOLDEN["request"],
            GOLDEN["receipt"],
            GOLDEN["request_hash"],
        )
        assert (
            tx.execute(
                "SELECT COUNT(*) FROM authority_operations WHERE business_key=?",
                (request.business_key,),
            ).fetchone()[0]
            == 1
        )


def test_new_profile_pins_original_erp_work_order_and_stock_proof_routing(tmp_path):
    from uuid import uuid4
    from datetime import timedelta
    from .support import MockRig, NOW
    from manufacturing_platform.workflow.exchange_models import (
        ExternalRequest,
        StopPayload,
        StockProofPayload,
    )
    from manufacturing_platform.workflow.integrations.routing import route_request

    rig = MockRig(tmp_path, core=True)
    refs = rig.core_ready()
    due = (NOW + timedelta(days=7)).date().isoformat()
    demand = rig.command(
        "demand.record",
        kind="firm",
        product="P",
        quantity="12",
        unit="piece",
        due_date=due,
        source=rig.manual_source("demand"),
    ).object_id
    for dimension in ("technical", "material", "capacity", "commercial", "quality"):
        rig.command(
            "demand.review",
            demand_id=str(demand),
            dimension=dimension,
            decision="approved",
            evidence="Reviewed original ERP order",
        )
    order = rig.command(
        "order.register",
        demand_id=str(demand),
        quantity="12",
        unit="piece",
        due_date=due,
        source=rig.manual_source("order_line"),
    )
    source = rig.manual_source("work_order") | {"system": "erp"}
    old = rig.command(
        "work_order.register",
        source=source,
        order_line_id=str(order.object_id),
        revision_id=str(refs.revision),
        quantity="12",
        unit="piece",
        purpose="production",
        trial_quantity="1",
        planned_start=NOW.isoformat(),
        planned_end=(NOW + timedelta(days=1)).isoformat(),
    )
    request = ExternalRequest(
        id=uuid4(),
        system="erp",
        action="production.interrupt",
        business_key="pinned-stop",
        source_version=1,
        project_id=rig.project_id,
        typed_payload=StopPayload(
            interruption_id=uuid4(),
            work_order_id=old.object_id,
            reason="Existing authority control",
        ),
    )
    proof = ExternalRequest(
        id=uuid4(),
        system="erp",
        action="stock_basis.reconcile",
        business_key="pinned-proof",
        source_version=1,
        project_id=rig.project_id,
        typed_payload=StockProofPayload(
            eco_id=uuid4(),
            reservation_id=uuid4(),
            original_exchange_id=uuid4(),
            original_business_key="original",
            original_receipt_hash="a" * 64,
            original_opening_hash="b" * 64,
            original_accounted_atoms=0,
        ),
    )
    with rig.workflow.store.transaction() as tx:
        assert route_request(tx, rig.project_id, request) == "erp"
        assert route_request(tx, rig.project_id, proof) == "erp"


def test_existing_schema23_initializes_additive_release_ledger_and_net_view(tmp_path):
    from .test_profile_migration import store

    workflow = store(tmp_path)
    with workflow.transaction() as tx:
        assert tx.execute("SELECT version FROM schema_version").fetchone()[0] == 23
        tx.execute("DROP VIEW effective_reservations")
        tx.execute("DROP TABLE integration_reservation_releases")
    reopened = store(tmp_path)
    with reopened.transaction() as tx:
        assert tx.execute("SELECT version FROM schema_version").fetchone()[0] == 23
        assert (
            tx.execute("SELECT COUNT(*) FROM effective_reservations").fetchone()[0] == 0
        )
        assert (
            tx.execute(
                "SELECT COUNT(*) FROM integration_reservation_releases"
            ).fetchone()[0]
            == 0
        )
