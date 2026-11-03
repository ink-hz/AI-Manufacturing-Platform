from uuid import uuid4

import pytest

from manufacturing_platform.workflow.contracts import DomainError

from .test_contracts import order_payload


def test_query_first_recovers_committed_timeout_with_original_identity(rig):
    op = uuid4()
    rig.fault("sap", op, "timeout_after_commit")
    result = rig.execute(operation_id=op)
    assert result.object_id == op
    assert len(rig.rows("sap", "facts")) == 1
    rig.reopen()
    rig.retry(op)
    assert len(rig.rows("sap", "facts")) == 1
    assert len(rig.rows("sap", "operations")) == 1
    receipt = rig.source_receipt(op)
    assert rig.projection_count(receipt.source_keys[0]) == 1


def test_projection_waits_for_current_policy(rig):
    attempt = rig.begin_and_commit_source_then_revoke_actor()
    with pytest.raises(DomainError) as exc:
        rig.finish_pending(attempt)
    assert exc.value.status == 403
    assert rig.projection_count(attempt.source_key) == 0
    assert rig.source_receipt(attempt.operation_id) is not None
    assert not exc.value.fields


def test_cas_retains_source_and_explicit_recovery(rig):
    rig.registry.adapter("sap").after_commit = lambda: rig.grant(["project_owner"])
    op = uuid4()
    with pytest.raises(DomainError) as exc:
        rig.execute(operation_id=op)
    assert exc.value.code == "VERSION_CONFLICT"
    assert exc.value.fields["intent_id"] == str(op)
    assert exc.value.fields["source_committed"] is True
    assert exc.value.fields["projection_applied"] is False
    receipt = rig.source_receipt(op)
    assert rig.projection_count(receipt.source_keys[0]) == 0
    rig.retry(op)
    assert rig.projection_count(receipt.source_keys[0]) == 1
    assert len(rig.rows("sap", "operations")) == 1


def test_policy_before_any_source_io_or_intent(rig):
    rig.grant(["warehouse"])
    with pytest.raises(DomainError) as exc:
        rig.execute()
    assert exc.value.status == 403
    assert not (rig.root / "mock-systems").exists()
    with rig.workflow.store.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM integration_intents").fetchone()[0] == 0


def test_production_never_opens_mock(production_rig):
    with pytest.raises(DomainError):
        production_rig.execute()
    with pytest.raises(DomainError):
        production_rig.registry.adapter("sap")
    assert not (production_rig.root / "mock-systems").exists()


def test_network_bound_and_scoped_fault(rig):
    for _ in range(3):
        rig.execute()
    batch = rig.drain(limit=1)
    assert len(batch.receipts) == 1 and batch.pending == 2
    assert rig.drain(limit=100).pending == 0
    assert len(rig.rows("wms", "test_effects")) == 3
    assert rig.drain().receipts == []


def test_browse_no_authority_origin_inference_and_cross_project(rig):
    from manufacturing_platform.workflow.integrations import browse

    with rig.workflow.store.transaction() as tx:
        descriptors = browse.systems(tx, rig.actor, rig.project_id, rig.registry)
    assert next(d for d in descriptors if d.system == "sap").status == "unexercised"
    assert not (rig.root / "mock-systems").exists()
    result = rig.execute()
    key = rig.source_receipt(result.object_id).source_keys[0]
    with rig.workflow.store.transaction() as tx:
        with pytest.raises(DomainError) as exc:
            browse.fact(tx, rig.actor, rig.other_project_id, rig.registry, key)
        assert exc.value.status == 404
    detail = rig.workflow.integration_fact(rig.actor, rig.project_id, key)
    assert detail.fact.project_id == rig.project_id
    assert detail.projection is not None


def http_client(rig, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from manufacturing_platform.workflow import api

    monkeypatch.setattr(api, "WorkflowService", lambda *a, **kw: rig.workflow)
    router = api.build_workflow_router(
        database_path=str(rig.root / "workflow.sqlite3"),
        authority_database_path=str(rig.root / "erp.sqlite3"),
        assets_dir=str(rig.root),
        authenticate=lambda request, write=False: rig.actor.model_dump(),
        resolve_subject=lambda uid: True,
        release="test",
        dataset=rig.workflow.store.dataset,
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_http_cas_recovery_and_replay_are_explicit(rig, monkeypatch):
    client = http_client(rig, monkeypatch)
    root = f"/api/v1/manufacturing/workflow/projects/{rig.project_id}"
    op = uuid4()
    payload = dict(
        action="mock_system.execute",
        operation_id=str(op),
        expected_version=rig.version(),
        system="sap",
        payload=order_payload(),
    )
    rig.registry.adapter("sap").after_commit = lambda: rig.grant(["project_owner"])
    response = client.post(root + "/commands", json=payload)
    assert response.status_code == 409, response.text
    fields = response.json()["fields"]
    assert fields["intent_id"] == str(op) and fields["source_committed"] is True
    assert (
        fields["projection_applied"] is False and fields["receipt_phase"] == "accepted"
    )
    replay = client.post(root + "/commands", json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["integration"]["intent_id"] == str(op)
    assert replay.json()["integration"]["projection_applied"] is False
    recovery = client.post(
        root + "/commands",
        json=dict(
            action="mock_system.retry",
            intent_id=str(op),
            operation_id=str(uuid4()),
            expected_version=rig.version(),
        ),
    )
    assert recovery.status_code == 200, recovery.text
    assert recovery.json()["integration"]["projection_applied"] is True
    assert len(rig.rows("sap", "operations")) == 1
    assert len(rig.rows("sap", "facts")) == 1


def test_http_revocation_after_source_has_no_evidence_leak(rig, monkeypatch):
    client = http_client(rig, monkeypatch)
    rig.registry.adapter("sap").after_commit = lambda: rig.grant(["warehouse"])
    op = uuid4()
    response = client.post(
        f"/api/v1/manufacturing/workflow/projects/{rig.project_id}/commands",
        json=dict(
            action="mock_system.execute",
            operation_id=str(op),
            expected_version=rig.version(),
            system="sap",
            payload=order_payload(),
        ),
    )
    assert response.status_code == 403, response.text
    assert response.json()["fields"] == {}
    assert (
        "source_committed" not in response.text and "test signed" not in response.text
    )
    receipt = rig.source_receipt(op)
    assert receipt and rig.projection_count(receipt.source_keys[0]) == 0
    with rig.workflow.store.transaction() as tx:
        assert (
            tx.execute("SELECT COUNT(*) FROM integration_receipts").fetchone()[0] == 1
        )


def test_pending_response_and_live_browse_http(rig, monkeypatch):
    client = http_client(rig, monkeypatch)
    op = uuid4()
    rig.fault("sap", op, "timeout_after_commit")
    result = rig.execute(operation_id=op)
    assert result.integration.phase == "unknown"
    assert result.integration.source_committed is None
    assert result.integration.projection_applied is False
    root = f"/api/v1/manufacturing/workflow/projects/{rig.project_id}"
    response = client.get(
        root + "/systems/sap/facts", params=dict(object_type="order", limit=1)
    )
    assert response.status_code == 200 and len(response.json()["records"]) == 1
    assert response.json()["projections"] == []
    assert (
        client.get(
            root + "/systems/sap/facts", params=dict(object_type="order", limit=201)
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/v1/manufacturing/workflow/projects/{rig.other_project_id}/systems/sap/facts",
            params=dict(object_type="order"),
        ).status_code
        == 404
    )


def test_source_detail_reports_exact_committed_origin_even_before_projection(
    rig, monkeypatch
):
    client = http_client(rig, monkeypatch)
    op = uuid4()
    rig.fault("sap", op, "timeout_after_commit")
    rig.execute(operation_id=op)
    response = client.get(
        f"/api/v1/manufacturing/workflow/projects/{rig.project_id}/systems/sap/facts/order/{op}",
        params={"version": 1},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["origin"]["kind"] == "operation"
    assert data["origin"]["operation_receipt"]["operation_id"] == str(op)
    assert data["source_accepted"] is True and data["workflow_projected"] is False
    assert data["consumer_delivered"] is False
    assert data["pending_deliveries"] == 1
    assert data["sap_posted"] is None


def test_object_links_are_bounded_and_authorize_exact_target(rig, monkeypatch):
    from manufacturing_platform.workflow.contracts import ObjectKind
    from manufacturing_platform.workflow.integrations.contracts import ObjectRef

    from .support import NOW, test_projector

    target = rig.command(
        "demand.record",
        kind="firm",
        product="P",
        quantity="2",
        unit="piece",
        due_date="2027-01-01",
        source=dict(
            system="customer",
            object_type="demand",
            external_id="D1",
            version=1,
            mode="manual",
            occurred_at=NOW.isoformat(),
            collected_at=NOW.isoformat(),
            evidence="Customer demand",
        ),
    )
    old = rig.registry._bindings["sap"]

    def projector(tx, context, fact):
        result = test_projector(tx, context, fact)
        result.targets = [
            ObjectRef(
                project_id=context.project_id,
                kind=ObjectKind.demand,
                id=target.object_id,
            )
        ]
        return result

    rig.registry._bindings["sap"] = (old[0], projector, old[2])
    for _ in range(3):
        rig.execute()
    client = http_client(rig, monkeypatch)
    url = f"/api/v1/manufacturing/workflow/projects/{rig.project_id}/integration-links"
    monkeypatch.setattr(
        rig.registry,
        "adapter",
        lambda system: pytest.fail("Object links scanned source systems"),
    )
    response = client.get(
        url, params=dict(target_kind="demand", target_id=str(target.object_id), limit=2)
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert (
        len(data["records"]) == 2
        and data["continuation"] is not None
        and data["complete"] is False
    )
    assert all(
        r["projection"]["targets"][0]["id"] == str(target.object_id)
        for r in data["records"]
    )
    assert (
        client.get(
            url, params=dict(target_kind="demand", target_id=str(uuid4()))
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/manufacturing/workflow/projects/{rig.other_project_id}/integration-links",
            params=dict(target_kind="demand", target_id=str(target.object_id)),
        ).status_code
        == 404
    )


def test_network_crash_between_commits_reopens_and_reports_duplicate(rig, monkeypatch):
    from manufacturing_platform.workflow.integrations.store import SystemStore

    rig.execute()
    original = SystemStore.acknowledge

    def crash(*args, **kwargs):
        raise OSError("test crash before producer ack")

    monkeypatch.setattr(SystemStore, "acknowledge", crash)
    first = rig.drain()
    assert first.pending == 1 and first.receipts[0].phase == "pending"
    assert len(rig.rows("wms", "test_effects")) == 1
    monkeypatch.setattr(SystemStore, "acknowledge", original)
    rig.reopen()
    second = rig.drain()
    assert second.pending == 0 and second.duplicate == 1 and second.delivered == 1
    assert second.cursor is not None
    assert len(rig.rows("wms", "test_effects")) == 1


def test_exact_release_variant_and_oa_target_policy_before_intent(rig):
    from .test_contracts import valid_payload

    for tag in ("mes.release", "oa.decide_approval"):
        payload = valid_payload(tag)
        if tag == "mes.release":
            payload["kind"] = "quality"
        else:
            from manufacturing_platform.workflow.integrations.enterprise_models import (
                QualityTarget,
            )

            from .test_contracts import sample_from_schema

            schema = QualityTarget.model_json_schema()
            payload["target"] = sample_from_schema(schema, schema.get("$defs", {}))
            payload["target"]["disposition"] = "scrap"
        rig.grant(["production", "engineering"])
        with pytest.raises(DomainError) as exc:
            rig.execute(tag.split(".")[0], payload)
        assert exc.value.status == 403
    assert not (rig.root / "mock-systems").exists()
    with rig.workflow.store.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM integration_intents").fetchone()[0] == 0


def test_no_adapter_io_in_workflow_transactions(rig, monkeypatch):
    from contextlib import contextmanager

    original = rig.workflow.store.transaction
    active = []

    @contextmanager
    def transaction(*args, **kwargs):
        with original(*args, **kwargs) as tx:
            active.append(True)
            try:
                yield tx
            finally:
                active.pop()

    monkeypatch.setattr(rig.workflow.store, "transaction", transaction)
    from .support import TestAdapter

    for method in ("execute", "query", "fact", "facts"):
        previous = getattr(TestAdapter, method)

        def guarded(self, *args, _original=previous, **kwargs):
            assert not active, "Source I/O occurred inside workflow transaction"
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(TestAdapter, method, guarded)
    result = rig.execute()
    rig.query(result.object_id)
    rig.workflow.integration_facts(rig.actor, rig.project_id, "sap", "order")
    rig.workflow.integration_fact(
        rig.actor, rig.project_id, rig.source_receipt(result.object_id).source_keys[0]
    )


def test_projection_changes_project_version_and_is_audited(rig):
    before = rig.version()
    result = rig.execute()
    assert result.project_version == before + 1
    assert result.current_project_version == before + 2
    assert rig.version() == before + 2
    with rig.workflow.store.transaction() as tx:
        events = tx.execute(
            "SELECT typed_payload FROM audit_events WHERE project_id=? AND action='integration.apply'",
            (str(rig.project_id),),
        ).fetchall()
    assert len(events) == 1
    assert str(result.object_id) in events[0][0]


def test_revocation_during_query_prevents_new_source_execution(rig, monkeypatch):
    adapter = rig.registry.adapter("sap")
    original = adapter.query

    def query(pid, op):
        result = original(pid, op)
        rig.grant(["warehouse"])
        return result

    monkeypatch.setattr(adapter, "query", query)
    with pytest.raises(DomainError) as exc:
        rig.execute()
    assert exc.value.status == 403
    assert len(rig.rows("sap", "operations")) == 0
    assert len(rig.rows("sap", "facts")) == 0


def test_missing_consumer_receipt_never_acknowledges_success(rig, monkeypatch):
    rig.execute()
    monkeypatch.setattr(rig.registry.adapter("wms"), "consume", lambda d: None)
    batch = rig.drain()
    assert batch.pending == 1 and batch.delivered == 0
    assert rig.rows("sap", "acknowledgments") == []


def test_stale_receipt_sequence_keeps_source_recoverable_without_projection(
    rig, monkeypatch
):
    adapter = rig.registry.adapter("sap")
    original = adapter.execute
    op = uuid4()

    def execute(value):
        return original(value).model_copy(update={"sequence": 0})

    monkeypatch.setattr(adapter, "execute", execute)
    with pytest.raises(DomainError) as exc:
        rig.execute(operation_id=op)
    assert exc.value.code == "SOURCE_CONFLICT"
    receipt = rig.source_receipt(op)
    assert receipt and rig.projection_count(receipt.source_keys[0]) == 0
    rig.retry(op)
    assert rig.projection_count(receipt.source_keys[0]) == 1
    assert len(rig.rows("sap", "operations")) == 1


def test_exchange_facade_requires_explicit_separate_registration(rig):
    adapter = rig.registry.adapter("sap")
    adapter.submit = lambda request: pytest.fail(
        "source adapter used as exchange facade"
    )
    with pytest.raises(DomainError) as exc:
        rig.registry.exchange_adapter("sap")
    assert exc.value.code == "SOURCE_UNAVAILABLE"
    sentinel = object()
    rig.registry.register_exchange_adapter("sap", lambda registry: sentinel)
    assert rig.registry.exchange_adapter("sap") is sentinel
    assert rig.registry.adapter("sap") is adapter


def test_consumer_return_without_durable_inbox_is_not_delivery(rig, monkeypatch):
    from manufacturing_platform.workflow.integrations.contracts import DeliveryReceipt

    from .support import NOW

    rig.execute()

    def fabricated(d):
        return DeliveryReceipt(
            delivery_id=d.delivery_id,
            project_id=d.project_id,
            consumer=d.consumer,
            source_key=d.fact.source_key,
            payload_hash=d.payload_hash,
            phase="accepted",
            received_at=NOW,
        )

    monkeypatch.setattr(rig.registry.adapter("wms"), "consume", fabricated)
    batch = rig.drain()
    assert batch.pending == 1 and batch.delivered == 0
    assert rig.rows("sap", "acknowledgments") == []


def test_pull_pins_observation_and_does_not_repeat_projection(rig):
    original = rig.execute()
    receipt = rig.source_receipt(original.object_id)
    key = receipt.source_keys[0]
    pulled = rig.pull(key)
    assert pulled.integration.projection_applied is True
    assert rig.projection_count(key) == 1
    rig.retry(pulled.object_id)
    assert rig.projection_count(key) == 1
    assert len(rig.rows("sap", "operations")) == 1


def test_pull_exact_oa_variant_is_authorized_before_intent(rig):
    from manufacturing_platform.workflow.integrations.contracts import IntegrationFact
    from manufacturing_platform.workflow.integrations.enterprise_models import (
        QualityTarget,
    )

    from .support import NOW, TestAdapter, test_authorize, test_projector
    from .test_contracts import sample_from_schema, valid_payload

    rig.registry.register(
        "oa", factory=TestAdapter, projector=test_projector, authorize=test_authorize
    )
    data = valid_payload("oa.decide_approval")
    data.pop("operation")
    schema = QualityTarget.model_json_schema()
    data["target"] = sample_from_schema(schema, schema.get("$defs", {}))
    data["target"]["disposition"] = "scrap"
    fact = IntegrationFact(
        project_id=rig.project_id,
        source=dict(
            system="oa",
            object_type="approval_decision",
            external_id="Q1",
            version=1,
            occurred_at=NOW,
            collected_at=NOW,
            evidence="quality approval",
        ),
        payload=dict(fact_type="oa.approval_decision", **data),
        external_actor="OA quality",
        evidence="quality approval",
    )
    store = rig.registry.source_store("oa")
    with store.transaction(write=True) as tx:
        store.append_fact(tx, fact)
    rig.grant(["engineering"])
    with pytest.raises(DomainError) as exc:
        rig.pull(fact.source_key)
    assert exc.value.status == 403
    with rig.workflow.store.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM integration_intents").fetchone()[0] == 0


def test_all_closed_fact_types_have_explicit_fixed_policy():
    from manufacturing_platform.workflow.integrations.contracts import FACT_ADAPTER
    from manufacturing_platform.workflow.integrations.operations import FACT_POLICIES

    tags = set(FACT_ADAPTER.json_schema()["discriminator"]["mapping"])
    assert set(FACT_POLICIES) == tags
    with pytest.raises(TypeError):
        FACT_POLICIES["fabricated.fact"] = "order.register"


def test_explicit_query_advances_bounded_network_for_already_applied_intent(rig):
    result = rig.execute()
    assert rig.registry.source_store("sap").pending_count(rig.project_id) == 1
    rig.query(result.object_id)
    assert rig.registry.source_store("sap").pending_count(rig.project_id) == 0
    assert len(rig.rows("wms", "test_effects")) == 1
    assert len(rig.rows("sap", "operations")) == 1


def test_system_status_includes_actual_pending_deliveries_and_release_variants(rig):
    from .support import TestAdapter, test_authorize, test_projector

    rig.registry.register(
        "mes", factory=TestAdapter, projector=test_projector, authorize=test_authorize
    )
    result = rig.execute()
    cards = rig.workflow.integration_systems(rig.actor, rig.project_id)
    sap = next(c for c in cards if c.system == "sap")
    assert sap.status == "pending" and sap.pending_count == 1
    assert (
        "mes.release"
        not in next(c for c in cards if c.system == "mes").permitted_operations
    )
    rig.query(result.object_id)
    sap = next(
        c
        for c in rig.workflow.integration_systems(rig.actor, rig.project_id)
        if c.system == "sap"
    )
    assert sap.status == "connected-mock" and sap.pending_count == 0


def test_untracked_source_fact_is_readable_but_cannot_project_as_accepted(rig):
    from .test_store_network import fact

    observed = fact(rig.project_id, external_id=str(uuid4()))
    store = rig.registry.source_store("sap")
    with store.transaction(write=True) as tx:
        store.append_fact(tx, observed)
    detail = rig.workflow.integration_fact(
        rig.actor, rig.project_id, observed.source_key
    )
    assert detail.origin.kind == "untracked" and detail.source_accepted is None
    with pytest.raises(DomainError) as exc:
        rig.pull(observed.source_key)
    assert exc.value.code == "SOURCE_CONFLICT"
    assert rig.projection_count(observed.source_key) == 0


def test_connected_status_requires_current_adapter_round_trip(rig, monkeypatch):
    result = rig.execute()
    rig.query(result.object_id)
    monkeypatch.setattr(rig.registry.adapter("sap"), "query", lambda pid, op: None)
    card = next(
        c
        for c in rig.workflow.integration_systems(rig.actor, rig.project_id)
        if c.system == "sap"
    )
    assert card.status == "degraded"


def test_legacy_descriptor_uses_legacy_receipt_without_relabelling_it(workflow):
    from ..conftest import BASE
    from ..test_exchanges import act, reserve, stock

    project, _req, supply, result = reserve(workflow)
    stock(workflow, project, supply)
    act(workflow, project, result)
    response = workflow.client("planner").get(
        f"{BASE}/projects/{project['id']}/systems"
    )
    assert response.status_code == 200, response.text
    card = next(c for c in response.json() if c["system"] == "erp")
    assert card["maturity"] == "legacy" and card["status"] == "connected-mock"
    assert card["last_receipt"] is None
    assert not (workflow.paths.domain.parent / "mock-systems").exists()


def test_production_network_drain_fails_closed_without_source_files(production_rig):
    with pytest.raises(DomainError) as exc:
        production_rig.drain()
    assert exc.value.code == "SOURCE_UNAVAILABLE"
    assert not (production_rig.root / "mock-systems").exists()
