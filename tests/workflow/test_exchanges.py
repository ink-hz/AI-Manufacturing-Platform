"""B2: API intent and recovery against a separately committed authority."""

from uuid import uuid4

import pytest

from .conftest import BASE


def reserve(workflow, *, quantity="80"):
    p, req, supply = workflow.material_requirement(qualified="0")
    result = workflow.command(
        p["id"],
        "reservation.request",
        actor_name="planner",
        work_order_id=supply["work_order_id"],
        requirement_id=req["id"],
        lot_id=supply["lot_id"],
        quantity=quantity,
        unit="kg",
    )
    return p, req, supply, result


def authority(workflow):
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    return MockAuthorityAdapter(str(workflow.paths.authority), "workflow-test")


def stock(workflow, p, supply, quantity="100"):
    a = authority(workflow)
    # External receiving and IQC are independent authority events, never platform writes.
    a.receive(
        project_id=p["id"],
        external_id="delivery-1",
        commitment_id=supply["id"],
        lot_id=supply["lot_id"],
        material_id="steel-1",
        owner_id="Customer 1",
        quantity=quantity,
        unit="kg",
        scale=3,
        expiry="2027-12-01",
        external_actor="Warehouse robot",
        signature="WMS signed delivery",
    )
    a.inspect(
        project_id=p["id"],
        external_id="iqc-1",
        receipt_external_id="delivery-1",
        accepted=quantity,
        rejected="0",
        external_actor="External quality inspector",
        signature="QMS signed result",
    )
    return a


def act(workflow, p, result, action="exchange.dispatch", **kw):
    return workflow.command(
        p["id"], action, actor_name="planner", exchange_id=result["exchange_id"], **kw
    )


def exchange(workflow, p, result):
    return workflow.object(p["id"], "exchange", result["exchange_id"])


def test_timeout_queries_existing_reservation(workflow):
    p, req, supply, result = reserve(workflow)
    a = stock(workflow, p, supply)
    a.configure_fault("timeout_after_commit")
    act(workflow, p, result)
    assert exchange(workflow, p, result)["phase"] == "unknown"
    assert a.balance(supply["lot_id"]) == "20"
    assert workflow.balance(p["id"], req["id"])["reserved"] == "0"
    workflow.reopen()
    act(workflow, p, result, "exchange.query")
    assert workflow.balance(p["id"], req["id"])["reserved"] == "80"
    assert authority(workflow).operation_count(result["exchange_id"]) == 1
    assert exchange(workflow, p, result)["phase"] == "accepted"
    act(workflow, p, result, "exchange.query")
    assert workflow.balance(p["id"], req["id"])["reserved"] == "80"
    assert authority(workflow).balance(supply["lot_id"]) == "20"


@pytest.mark.parametrize(
    "fault,phase",
    [
        ("stale_sequence", "rejected"),
        ("wrong_unit", "rejected"),
        ("changed_detail_same_total", "rejected"),
        ("reject", "rejected"),
    ],
)
def test_invalid_or_rejected_receipts_cannot_confirm(workflow, fault, phase):
    p, req, supply, result = reserve(workflow)
    a = stock(workflow, p, supply)
    a.configure_fault(fault)
    act(workflow, p, result)
    workflow.reopen()
    assert exchange(workflow, p, result)["phase"] == phase
    assert workflow.balance(p["id"], req["id"])["reserved"] == "0"
    assert authority(workflow).operation_count(result["exchange_id"]) == 1
    assert exchange(workflow, p, result)["events"]


def test_partial_accept_and_live_dispatch_policy(workflow):
    p, req, supply, result = reserve(workflow)
    a = stock(workflow, p, supply)
    a.configure_fault("partial_quantity", "30")
    workflow.grant(p["id"], "warehouse", ["warehouse"])
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="warehouse",
        exchange_id=result["exchange_id"],
        expected_status=403,
    )
    op = str(uuid4())
    act(workflow, p, result, operation_id=op)
    assert workflow.balance(p["id"], req["id"])["reserved"] == "30"
    assert workflow.balance(p["id"], req["id"])["shortage"] == "70"
    assert a.balance(supply["lot_id"]) == "70"
    workflow.grant(p["id"], "planner", ["production"])
    act(workflow, p, result, operation_id=op, expected_status=403)
    assert a.operation_count(result["exchange_id"]) == 1


def test_manual_iqc_does_not_create_authority_inventory(workflow):
    p, req, supply = workflow.material_requirement(qualified="100")
    result = workflow.command(
        p["id"],
        "reservation.request",
        actor_name="planner",
        work_order_id=supply["work_order_id"],
        requirement_id=req["id"],
        lot_id=supply["lot_id"],
        quantity="80",
        unit="kg",
    )
    act(workflow, p, result)
    assert exchange(workflow, p, result)["phase"] == "rejected"
    assert workflow.balance(p["id"], req["id"])["reserved"] == "0"


def test_unknown_and_unsubmitted_intents_hold_lineage_budget(workflow):
    p, req, supply, result = reserve(workflow)
    a = stock(workflow, p, supply, quantity="200")
    for uncertain in (False, True):
        if uncertain:
            a.configure_fault("timeout_after_commit")
            act(workflow, p, result)
        workflow.command(
            p["id"],
            "reservation.request",
            actor_name="planner",
            work_order_id=supply["work_order_id"],
            requirement_id=req["id"],
            lot_id=supply["lot_id"],
            quantity="80",
            unit="kg",
            expected_status=409,
        )
        assert workflow.balance(p["id"], req["id"])["reserved"] == "0"
    assert a.balance(supply["lot_id"]) == "120"
    assert a.operation_count() == 1


def test_read_only_and_revoked_query_never_touches_authority(workflow):
    p, _req, supply, result = reserve(workflow)
    a = stock(workflow, p, supply)
    workflow.read_only.add("planner")
    act(workflow, p, result, expected_status=403)
    workflow.read_only.clear()
    workflow.grant(p["id"], "planner", [], active=False)
    response = workflow.client("planner").post(
        f"{BASE}/projects/{p['id']}/commands",
        json={
            "action": "exchange.query",
            "operation_id": str(uuid4()),
            "expected_version": 1,
            "exchange_id": result["exchange_id"],
        },
    )
    assert response.status_code == 404
    assert a.operation_count() == 0


def test_production_never_constructs_mock_adapter(tmp_path, monkeypatch):
    from manufacturing_platform.workflow import exchanges
    from manufacturing_platform.workflow.service import WorkflowService
    from manufacturing_platform.workflow.store import WorkflowStore

    def forbidden(*args, **kwargs):
        raise AssertionError("production instantiated mock adapter")

    monkeypatch.setattr(exchanges, "MockAuthorityAdapter", forbidden)
    service = WorkflowService(
        WorkflowStore(
            str(tmp_path / "p.db"),
            str(tmp_path / "a.db"),
            {"id": "prod", "mode": "production", "label": "Production"},
        ),
        lambda _: True,
    )
    assert service.exchange_service.adapter is None
    assert not (tmp_path / "a.db").exists()


def test_dispatch_releases_sqlite_writer_and_asgi_event_loop(workflow, monkeypatch):
    import asyncio
    import sqlite3
    from threading import Event

    import httpx

    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    p, _, supply, result = reserve(workflow)
    stock(workflow, p, supply)
    entered, release = Event(), Event()
    original = MockAuthorityAdapter.submit

    def blocked(self, request):
        # Independent writer succeeds while the external adapter is running.
        with sqlite3.connect(workflow.paths.domain, timeout=0.05) as db:
            db.execute("BEGIN IMMEDIATE")
        entered.set()
        if not release.wait(2):
            raise AssertionError("ASGI event loop blocked by synchronous adapter")
        return original(self, request)

    monkeypatch.setattr(MockAuthorityAdapter, "submit", blocked)
    version = workflow.client().get(f"{BASE}/projects/{p['id']}").json()["version"]

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=workflow.app), base_url="http://test"
        ) as client:
            headers = {"x-test-actor": "planner", "x-csrf-token": "trusted-test-csrf"}
            task = asyncio.create_task(
                client.post(
                    f"{BASE}/projects/{p['id']}/commands",
                    headers=headers,
                    json={
                        "action": "exchange.dispatch",
                        "operation_id": str(uuid4()),
                        "expected_version": version,
                        "exchange_id": result["exchange_id"],
                    },
                )
            )
            try:
                assert await asyncio.to_thread(entered.wait, 1)
                response = await asyncio.wait_for(
                    client.get(BASE + "/access", headers=headers), 1
                )
                assert response.status_code == 200
            finally:
                release.set()
            assert (await task).status_code == 200

    asyncio.run(run())


def test_wrong_business_key_receipt_cannot_apply_another_exchange(
    workflow, monkeypatch
):
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    p, req, supply, result = reserve(workflow)
    a = stock(workflow, p, supply)
    original = MockAuthorityAdapter.submit

    def wrong(self, request):
        return original(self, request).model_copy(update={"business_key": str(uuid4())})

    monkeypatch.setattr(MockAuthorityAdapter, "submit", wrong)
    act(workflow, p, result)
    assert exchange(workflow, p, result)["phase"] == "rejected"
    assert workflow.balance(p["id"], req["id"])["reserved"] == "0"
    assert a.balance(supply["lot_id"]) == "20"
    workflow.command(
        p["id"],
        "reservation.request",
        actor_name="planner",
        work_order_id=supply["work_order_id"],
        requirement_id=req["id"],
        lot_id=supply["lot_id"],
        quantity="80",
        unit="kg",
        expected_status=409,
    )
    monkeypatch.setattr(MockAuthorityAdapter, "submit", original)
    act(workflow, p, result, "exchange.query")
    assert workflow.balance(p["id"], req["id"])["reserved"] == "80"
    assert a.operation_count() == 1


def test_query_hash_replay_and_same_total_different_keys_reconciliation(workflow):
    p, req, supply, result = reserve(workflow)
    a = stock(workflow, p, supply)
    op = str(uuid4())
    first = act(workflow, p, result, operation_id=op)
    repeated = act(
        workflow,
        p,
        result,
        operation_id=op,
        expected_version=first["project_version"] - 1,
    )
    assert repeated["replayed"]
    act(workflow, p, result, "exchange.query", operation_id=op, expected_status=409)
    receipt = exchange(workflow, p, result)["receipt"]
    details = receipt["details"]
    details[0]["key"] = str(uuid4())
    workflow.command(
        p["id"],
        "exchange.reconcile",
        actor_name="planner",
        exchange_id=result["exchange_id"],
        source=workflow.source(result["exchange_id"], object_type="reservation"),
        object_type="reservation",
        source_version=receipt["source_version"],
        details=details,
        evidence="Same total but wrong requirement",
    )
    value = exchange(workflow, p, result)
    assert "discrepancy" in value["events"][0]["reason"]
    assert workflow.balance(p["id"], req["id"])["reserved"] == "80"
    assert a.operation_count() == 1


def test_rejected_receipt_query_is_idempotent_and_source_evidence_is_not_spoofable(
    workflow,
):
    p, _, supply, result = reserve(workflow)
    a = stock(workflow, p, supply)
    a.configure_fault("reject")
    act(workflow, p, result)
    act(workflow, p, result, "exchange.query")
    value = exchange(workflow, p, result)
    assert "Stale" not in value["reason"]
    source = workflow.source(
        result["exchange_id"], object_type="reservation", mode="api"
    )
    workflow.command(
        p["id"],
        "exchange.reconcile",
        actor_name="planner",
        expected_status=409,
        exchange_id=result["exchange_id"],
        source=source,
        object_type="reservation",
        source_version=1,
        details=value["receipt"]["details"],
        evidence="Forged api label",
    )
    assert value["discrepancies"][0]["owner_name"] == "planner"


def test_apply_returns_fresh_version_metadata_without_rewriting_intent(workflow):
    import json

    p, _, supply, result = reserve(workflow)
    stock(workflow, p, supply)
    op = str(uuid4())
    dispatched = act(workflow, p, result, operation_id=op)
    current = workflow.client().get(f"{BASE}/projects/{p['id']}").json()["version"]
    assert (
        dispatched["current_project_version"]
        == current
        == dispatched["project_version"] + 1
    )
    with workflow.db() as db:
        saved = json.loads(
            db.execute(
                "SELECT result_json FROM operations WHERE operation_id=?", (op,)
            ).fetchone()[0]
        )
        assert saved["project_version"] == dispatched["project_version"]
        assert saved.get("current_project_version") is None
    replay = act(
        workflow,
        p,
        result,
        operation_id=op,
        expected_version=dispatched["project_version"] - 1,
    )
    assert replay["project_version"] == dispatched["project_version"]
    assert replay["current_project_version"] == current
