"""MES shortages share the expedite lifecycle without moving stock or accounting."""

import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from manufacturing_platform.workflow.contracts import DomainError, GrantChange
from manufacturing_platform.workflow.integrations.contracts import (
    OPERATION_ADAPTER,
    NetworkDelivery,
    SystemOperation,
)

from .support import NOW, MockRig


@pytest.fixture
def rig(tmp_path):
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    value = MockRig(tmp_path, core=True)
    legacy = MockAuthorityAdapter(
        str(value.root / "erp.sqlite3"), "integration-test", business_clock=lambda: NOW
    )
    legacy.receive(
        project_id=value.project_id,
        external_id="legacy-sentinel-receipt",
        commitment_id=uuid4(),
        lot_id=uuid4(),
        material_id="LEGACY",
        owner_id="C",
        quantity="5",
        unit="piece",
        scale=0,
        expiry="2027-01-01",
        external_actor="Legacy WMS",
        signature="Existing legacy inventory",
    )
    legacy.inspect(
        project_id=value.project_id,
        external_id="legacy-sentinel-iqc",
        receipt_external_id="legacy-sentinel-receipt",
        accepted="4",
        rejected="1",
        external_actor="Legacy IQC",
        signature="Existing legacy qualification",
    )
    return value


def shortage(requirement):
    return {
        "operation": "mes.shortage",
        "requirement_id": str(requirement),
        "reason": "供应商延期",
        "impact": "工单上线受阻",
    }


def accounting(rig, refs):
    with rig.workflow.store.transaction() as tx:
        rows = {
            table: [
                tuple(row)
                for row in tx.execute(f"SELECT * FROM {table} ORDER BY rowid")
            ]
            for table in (
                "material_lots",
                "supply_receipts",
                "iqc_results",
                "reservations",
                "requirements",
                "material_consumption",
                "source_corrections",
                "source_confirmations",
                "handoffs",
            )
        }
    with sqlite3.connect(rig.root / "erp.sqlite3") as tx:
        rows["legacy_authority"] = {
            row[0]: tx.execute(f'SELECT * FROM "{row[0]}" ORDER BY rowid').fetchall()
            for row in tx.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    rows["wms_facts"] = rig.rows("wms", "facts")
    rows["sap_facts"] = rig.rows("sap", "facts")
    rows["physical_balance"] = rig.physical_balance(refs.lot)
    rows["accounting_balance"] = rig.accounting_balance(refs.lot)
    return rows


def cases(rig):
    with rig.workflow.store.transaction() as tx:
        return [
            dict(row)
            for row in tx.execute("SELECT * FROM material_expedites ORDER BY seq")
        ]


def staged_source(rig, monkeypatch, payload):
    """Pause after durable intent preparation, then commit the actual MES source."""
    with monkeypatch.context() as patch:
        patch.setattr(
            rig.workflow.integration_service,
            "perform",
            lambda actor, pid, command, result: SimpleNamespace(
                actor=actor, pid=pid, command=command, result=result
            ),
        )
        pending = rig.command("mock_system.execute", system="mes", payload=payload)
    with rig.workflow.store.transaction() as tx:
        operation = SystemOperation.model_validate_json(
            tx.execute(
                "SELECT payload_json FROM integration_intents WHERE id=?",
                (str(pending.command.operation_id),),
            ).fetchone()[0]
        )
    receipt = rig.registry.adapter("mes").execute(operation)
    assert receipt.phase == "accepted"
    return pending, rig.registry.observe_fact(rig.project_id, receipt.source_keys[0])


def test_shortage_source_delivery_projection_and_closed_replay_are_exactly_once(
    rig, monkeypatch
):
    refs = rig.core_ready()
    rig.drain()
    before = accounting(rig, refs)
    pending, fact = staged_source(rig, monkeypatch, shortage(refs.requirement))
    assert cases(rig) == [] and accounting(rig, refs) == before
    deliveries = [
        NetworkDelivery.model_validate_json(row["delivery_json"])
        for row in rig.rows("mes", "outbox")
    ]
    delivery = next(d for d in deliveries if d.fact.source_key == fact.source_key)
    assert delivery.consumer == "wms"
    batch = rig.drain()
    ack = next(r for r in batch.receipts if r.delivery_id == delivery.delivery_id)
    assert ack.phase == "accepted"
    assert cases(rig) == [] and accounting(rig, refs) == before
    result = rig.retry(pending.command.operation_id)
    assert result.integration.phase == "applied"
    assert fact.payload.fact_type == "mes.shortage"
    assert fact.payload.requirement_id == refs.requirement
    assert (fact.payload.reason, fact.payload.impact) == ("供应商延期", "工单上线受阻")
    ident = rig.target(fact, "material_expedite")
    detail = rig.workflow.object_detail(
        rig.actor, rig.project_id, "material_expedite", ident
    )
    assert detail.value.state == "open"
    assert detail.value.source.model_dump(mode="json") == fact.source.model_dump(
        mode="json"
    )
    assert (
        detail.summary.source.mode == "mock" and detail.summary.source.system == "mes"
    )
    assert "mes/mock" in detail.summary.title
    assert detail.value.requirement_id == refs.requirement
    assert detail.value.work_order_id == refs.work_order
    evidence = rig.workflow.integration_fact(rig.actor, rig.project_id, fact.source_key)
    assert evidence.projection.targets[0].id == ident
    assert accounting(rig, refs) == before
    inbox_before = rig.rows("wms", "inbox")
    assert rig.replay_delivery(fact.source_key, "wms") == ack
    assert rig.rows("wms", "inbox") == inbox_before
    rig.pull(fact.source_key)
    assert len(cases(rig)) == 1 and rig.projection_count(fact.source_key) == 1
    assert (
        rig.workflow.integration_fact(
            rig.actor, rig.project_id, fact.source_key
        ).projection
        == evidence.projection
    )
    assert accounting(rig, refs) == before
    rig.command("expedite.progress", expedite_id=str(ident), note="已联系供应商")
    rig.command(
        "expedite.close", expedite_id=str(ident), outcome="fulfilled", reason="补料完成"
    )
    rig.pull(fact.source_key)
    rig.retry(result.integration.intent_id)
    rig.replay_delivery(fact.source_key, "wms")
    assert len(cases(rig)) == 1 and cases(rig)[0]["state"] == "closed"
    assert rig.target(fact, "material_expedite") == ident
    assert (
        rig.workflow.integration_fact(
            rig.actor, rig.project_id, fact.source_key
        ).projection
        == evidence.projection
    )
    assert accounting(rig, refs) == before
    rig.reopen()
    assert rig.replay_delivery(fact.source_key, "wms") == ack
    rig.pull(fact.source_key)
    assert len(cases(rig)) == 1 and cases(rig)[0]["state"] == "closed"
    assert accounting(rig, refs) == before


@pytest.mark.parametrize("rejection", ["non_oem", "cross_project", "open_conflict"])
def test_shortage_source_rejections_are_immutable_and_have_no_business_effect(
    rig, rejection
):
    refs = rig.core_ready()
    rig.drain()
    payload = shortage(refs.requirement)
    if rejection == "non_oem":
        with rig.workflow.store.transaction(write=True) as tx:
            tx.execute(
                "UPDATE projects SET mode='internal' WHERE id=?", (str(rig.project_id),)
            )
        expected_code, message = "INVALID_COMMAND", "OEM"
    elif rejection == "cross_project":
        with rig.workflow.store.transaction(write=True) as tx:
            tx.execute(
                "UPDATE requirements SET project_id=? WHERE id=?",
                (str(rig.other_project_id), str(refs.requirement)),
            )
        expected_code, message = "NOT_FOUND", "not found"
    else:
        rig.execute("mes", payload)
        rig.drain()
        expected_code, message = "PRECONDITION_FAILED", "open expedite"
    before, original_cases = accounting(rig, refs), cases(rig)
    source_counts = (len(rig.rows("mes", "facts")), len(rig.rows("mes", "outbox")))
    opid = uuid4()
    result = rig.command(
        "mock_system.execute", system="mes", payload=payload, operation_id=str(opid)
    )
    assert (
        result.integration.phase == "rejected"
        and result.integration.source_committed is False
    )
    adapter = rig.registry.adapter("mes")
    receipt = adapter.query(rig.project_id, opid)
    assert receipt.phase == "rejected" and receipt.source_keys == []
    assert receipt.error.code == expected_code and message in receipt.error.message
    original = rig.original_receipt_bytes("mes", opid)
    operation = SystemOperation(
        operation_id=opid, project_id=rig.project_id, system="mes", payload=payload
    )
    assert adapter.execute(operation) == receipt
    rig.retry(opid)
    assert rig.original_receipt_bytes("mes", opid) == original
    assert (
        len(rig.rows("mes", "facts")),
        len(rig.rows("mes", "outbox")),
    ) == source_counts
    assert cases(rig) == original_cases and accounting(rig, refs) == before


@pytest.mark.parametrize("change", ["open_conflict", "non_oem", "cross_project"])
def test_projection_rechecks_business_admission_after_source_commit(
    rig, monkeypatch, change
):
    refs = rig.core_ready()
    rig.drain()
    pending, fact = staged_source(rig, monkeypatch, shortage(refs.requirement))
    if change == "open_conflict":
        rig.command(
            "expedite.open",
            requirement_id=str(refs.requirement),
            reason="manual",
            impact="risk",
        )
        status = 409
    else:
        with rig.workflow.store.transaction(write=True) as tx:
            if change == "non_oem":
                tx.execute(
                    "UPDATE projects SET mode='internal' WHERE id=?",
                    (str(rig.project_id),),
                )
                status = 422
            else:
                tx.execute(
                    "UPDATE requirements SET project_id=? WHERE id=?",
                    (str(rig.other_project_id), str(refs.requirement)),
                )
                status = 404
    before, original_cases = accounting(rig, refs), cases(rig)
    with pytest.raises(DomainError) as exc:
        rig.retry(pending.command.operation_id)
    assert exc.value.status == status
    assert (
        rig.registry.adapter("mes")
        .query(rig.project_id, pending.command.operation_id)
        .phase
        == "accepted"
    )
    assert rig.projection_count(fact.source_key) == 0
    assert cases(rig) == original_cases and accounting(rig, refs) == before


def test_shortage_roles_revocation_and_read_only_are_enforced_before_apply(
    rig, monkeypatch
):
    refs = rig.core_ready()
    rig.drain()
    before = accounting(rig, refs)
    rig.grant(["production"])
    opid = uuid4()
    with pytest.raises(DomainError) as exc:
        rig.execute("mes", shortage(refs.requirement), operation_id=opid)
    assert exc.value.status == 403
    assert rig.registry.adapter("mes").query(rig.project_id, opid) is None
    rig.grant(["supply"])
    pending, fact = staged_source(rig, monkeypatch, shortage(refs.requirement))
    rig.workflow.change_grant(
        rig.admin,
        rig.project_id,
        rig.actor.user_id,
        GrantChange(
            operation_id=uuid4(),
            expected_version=rig.version(),
            scope={"kind": "project", "project_id": rig.project_id},
            roles=["supply"],
            qualifications=[],
            active=False,
            evidence="Access revoked",
        ),
    )
    with pytest.raises(DomainError) as exc:
        rig.retry(pending.command.operation_id)
    assert exc.value.status == 404 and not exc.value.fields
    assert rig.projection_count(fact.source_key) == 0 and cases(rig) == []
    rig.grant(["supply"])
    read_only = rig.actor.model_copy(update={"read_only": True})
    with pytest.raises(DomainError) as exc:
        rig.command(
            "integration.pull", source_key=fact.source_key.model_dump(), actor=read_only
        )
    assert exc.value.status == 403
    rig.retry(pending.command.operation_id)
    assert len(cases(rig)) == 1
    rig.grant(["warehouse"])
    with pytest.raises(DomainError) as exc:
        rig.pull(fact.source_key)
    assert exc.value.status == 403
    assert accounting(rig, refs) == before


def test_client_cannot_spoof_shortage_or_manual_expedite_source(rig, monkeypatch):
    refs = rig.core_ready()
    rig.drain()
    before = accounting(rig, refs)
    source = rig.manual_source("shortage") | {"system": "mes", "mode": "mock"}
    with pytest.raises(ValidationError):
        OPERATION_ADAPTER.validate_python(
            shortage(refs.requirement) | {"source": source}
        )
    from .test_operation_boundary import http_client

    with http_client(rig, monkeypatch) as client:
        response = client.post(
            f"/api/v1/manufacturing/workflow/projects/{rig.project_id}/commands",
            json={
                "action": "expedite.open",
                "operation_id": str(uuid4()),
                "expected_version": rig.version(),
                "requirement_id": str(refs.requirement),
                "reason": "r",
                "impact": "i",
                "source": source,
            },
        )
    assert response.status_code == 422, response.text
    assert cases(rig) == [] and accounting(rig, refs) == before


def test_changed_source_observation_cannot_replace_existing_shortage_projection(
    rig, monkeypatch
):
    refs = rig.core_ready()
    rig.drain()
    fact = rig.result_fact(rig.execute("mes", shortage(refs.requirement)))
    rig.drain()
    before, original_cases = accounting(rig, refs), cases(rig)
    forged = fact.model_copy(
        update={
            "payload": fact.payload.model_copy(update={"reason": "Replaced evidence"})
        }
    )
    monkeypatch.setattr(rig.registry.adapter("mes"), "fact", lambda *_: forged)
    with pytest.raises(DomainError) as exc:
        rig.pull(fact.source_key)
    assert exc.value.status == 409 and exc.value.code == "SOURCE_CONFLICT"
    assert rig.projection_count(fact.source_key) == 1
    assert cases(rig) == original_cases and accounting(rig, refs) == before
