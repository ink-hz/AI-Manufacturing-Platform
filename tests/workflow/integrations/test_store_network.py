import os
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from manufacturing_platform.workflow.contracts import DomainError
from manufacturing_platform.workflow.integrations.contracts import (
    IntegrationFact,
    NetworkDelivery,
    SystemOperation,
    SystemReceipt,
)
from manufacturing_platform.workflow.integrations.store import (
    SystemStore,
    canonical_hash,
)

from .test_contracts import order_payload

NOW = datetime(2026, 11, 3, tzinfo=UTC)


def fact(pid=None, external_id="order-1"):
    payload = order_payload()
    payload.pop("operation")
    return IntegrationFact(
        project_id=pid or uuid4(),
        source=dict(
            system="sap",
            object_type="order",
            external_id=external_id,
            version=1,
            occurred_at=NOW,
            collected_at=NOW,
            evidence="signed source",
        ),
        payload=dict(fact_type="sap.order", **payload),
        external_actor="SAP operator",
        evidence="signed source",
    )


def store(tmp_path, system="sap", dataset="test-dataset"):
    return SystemStore(tmp_path, dataset, system, clock=lambda: NOW)


def test_independent_metadata_and_aliases(tmp_path):
    a, b = store(tmp_path), store(tmp_path, "wms")
    with a.transaction(write=True):
        pass
    with b.transaction(write=True):
        pass
    assert a.path != b.path and not a.path.samefile(b.path)
    with sqlite3.connect(a.path) as tx:
        tx.execute("UPDATE metadata SET dataset_id='wrong'")
    with pytest.raises(ValueError):
        with a.transaction():
            pass
    b.path.unlink()
    os.link(a.path, b.path)
    with pytest.raises(ValueError):
        with b.transaction():
            pass


def test_operation_idempotency_and_immutable_facts(tmp_path):
    s = store(tmp_path)
    f = fact()
    op = SystemOperation(
        operation_id=uuid4(),
        system="sap",
        project_id=f.project_id,
        payload=order_payload(),
    )

    def apply(tx, operation):
        s.append_fact(tx, f)
        return SystemReceipt(
            operation_id=operation.operation_id,
            system="sap",
            request_hash=canonical_hash(operation),
            phase="accepted",
            source_keys=[f.source_key],
            sequence=1,
            occurred_at=NOW,
            received_at=NOW,
        )

    receipt = s.execute(op, apply)
    assert s.execute(op, apply) == receipt
    changed = op.model_copy(
        update={"payload": op.payload.model_copy(update={"customer_id": "C2"})}
    )
    with pytest.raises(DomainError) as exc:
        s.execute(changed, apply)
    assert exc.value.code == "IDEMPOTENCY_CONFLICT"
    with s.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 1
        assert tx.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            tx.execute("UPDATE facts SET payload_hash='bad'")
    with s.transaction(write=True) as tx:
        with pytest.raises(DomainError):
            s.append_fact(tx, f.model_copy(update={"evidence": "altered"}))


def test_consumer_commit_then_producer_ack_restart(tmp_path):
    a, b = store(tmp_path), store(tmp_path, "wms")
    f = fact()
    with a.transaction(write=True) as tx:
        a.append_fact(tx, f)
        delivery = a.enqueue(tx, f, "wms")

    def apply(tx, received):
        tx.execute("CREATE TABLE IF NOT EXISTS effects (id TEXT PRIMARY KEY)")
        tx.execute("INSERT INTO effects VALUES (?)", (str(received.delivery_id),))

    first = b.consume(delivery, apply)
    # Simulated process death: the producer has not acknowledged the committed inbox.
    a, b = store(tmp_path), store(tmp_path, "wms")
    assert a.pending(f.project_id, 10) == [delivery]
    second = b.consume(delivery, apply)
    assert second == first
    a.acknowledge(delivery.delivery_id, second)
    assert not a.pending(f.project_id, 10)
    with b.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 1
        assert tx.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] == 1


def test_consume_rejects_changed_hash_and_wrong_target_without_effect(tmp_path):
    s = store(tmp_path, "wms")
    f = fact()
    d = NetworkDelivery(
        delivery_id=uuid4(),
        project_id=f.project_id,
        consumer="wms",
        fact=f,
        payload_hash=canonical_hash(f),
    )

    def forbidden(tx, delivery):
        raise AssertionError("unexpected state mutation")

    bad = d.model_copy(update={"payload_hash": "0" * 64})
    receipt = s.consume(bad, forbidden)
    assert receipt.phase == "rejected"
    assert s.consume(bad, forbidden) == receipt
    with pytest.raises(DomainError):
        s.consume(d.model_copy(update={"consumer": "mes"}), forbidden)
    with pytest.raises(DomainError):
        s.consume(d.model_copy(update={"project_id": uuid4()}), forbidden)
    with s.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] == 1


def test_fact_page_is_project_scoped_and_bounded(tmp_path):
    s = store(tmp_path)
    pid = uuid4()
    with s.transaction(write=True) as tx:
        for n in range(7):
            s.append_fact(tx, fact(pid, f"order-{n}"))
        s.append_fact(tx, fact())
    page = s.list_facts(pid, "order", 0, 3)
    assert len(page.records) == 3 and page.continuation == 3
    assert page.source_cutoff == 7
    assert len(s.list_facts(pid, "order", page.continuation, 3).records) == 3
    with pytest.raises(DomainError):
        s.list_facts(pid, "order", 0, 201)


def test_changed_causal_envelope_cannot_replay_old_ack(tmp_path):
    s = store(tmp_path, "wms")
    f = fact()
    d = NetworkDelivery(
        delivery_id=uuid4(),
        project_id=f.project_id,
        consumer="wms",
        fact=f,
        payload_hash=canonical_hash(f),
    )
    s.consume(d, lambda tx, d: None)
    altered = d.model_copy(
        update={"fact": f.model_copy(update={"evidence": "changed source detail"})}
    )
    with pytest.raises(DomainError) as exc:
        s.consume(altered, lambda tx, d: None)
    assert exc.value.code == "SOURCE_CONFLICT"


def test_symlink_and_wrong_system_metadata_rejected(tmp_path):
    s = store(tmp_path)
    with s.transaction():
        pass
    with sqlite3.connect(s.path) as tx:
        tx.execute("UPDATE metadata SET system_id='wms'")
    with pytest.raises(ValueError):
        with s.transaction():
            pass
    other = store(tmp_path, "wms")
    other.path.symlink_to(s.path)
    with pytest.raises(ValueError):
        with other.transaction():
            pass


def test_fault_is_exact_project_system_operation_and_one_shot(tmp_path):
    a, b = store(tmp_path), store(tmp_path, "wms")
    p, q = uuid4(), uuid4()
    op, other = uuid4(), uuid4()
    a.configure_fault(p, op, "timeout_after_commit")
    assert a.take_fault(q, op) == "none"
    assert a.take_fault(p, other) == "none"
    assert b.take_fault(p, op) == "none"
    assert a.take_fault(p, op) == "timeout_after_commit"
    assert a.take_fault(p, op) == "none"


def test_stale_version_durably_rejected_and_pending_ack_not_accepted(tmp_path):
    a, b = store(tmp_path), store(tmp_path, "wms")
    f = fact()
    newer = f.model_copy(update={"source": f.source.model_copy(update={"version": 2})})
    with a.transaction(write=True) as tx:
        a.append_fact(tx, newer)
        d2 = a.enqueue(tx, newer, "wms")
        a.append_fact(tx, f)
        d1 = a.enqueue(tx, f, "wms")
    accepted = b.consume(d2, lambda tx, d: None)
    rejected = b.consume(d1, lambda tx, d: pytest.fail("stale version applied"))
    assert accepted.phase == "accepted" and rejected.phase == "rejected"
    assert (
        b.consume(d1, lambda tx, d: pytest.fail("rejected replay applied")) == rejected
    )
    with pytest.raises(DomainError):
        a.acknowledge(d2.delivery_id, accepted.model_copy(update={"phase": "pending"}))
    assert a.pending_count(f.project_id) == 2


def test_insert_replace_cannot_erase_causal_history_via_alternate_keys(tmp_path):
    a, b = store(tmp_path), store(tmp_path, "wms")
    f = fact()
    with a.transaction(write=True) as tx:
        a.append_fact(tx, f)
        d = a.enqueue(tx, f, "wms")
    b.consume(d, lambda tx, d: None)
    with a.transaction(write=True) as tx:
        with pytest.raises(sqlite3.IntegrityError):
            tx.execute(
                "INSERT OR REPLACE INTO facts SELECT sequence,project_id,system,object_type,'changed',version,payload_hash,fact_json FROM facts"
            )
        with pytest.raises(sqlite3.IntegrityError):
            tx.execute(
                "INSERT OR REPLACE INTO outbox SELECT 'replacement',project_id,consumer,system,object_type,external_id,version,payload_hash,delivery_json FROM outbox"
            )
    with b.transaction(write=True) as tx:
        with pytest.raises(sqlite3.IntegrityError):
            tx.execute(
                "INSERT OR REPLACE INTO inbox SELECT project_id,producer,object_type,'changed',version,delivery_id,payload_hash,fact_hash,receipt_json FROM inbox"
            )


def test_transient_consume_rolls_back_effect_and_leaves_pending(tmp_path):
    a, b = store(tmp_path), store(tmp_path, "wms")
    f = fact()
    with a.transaction(write=True) as tx:
        a.append_fact(tx, f)
        d = a.enqueue(tx, f, "wms")

    def unavailable(tx, d):
        tx.execute("CREATE TABLE forbidden_effect(id TEXT)")
        raise DomainError("SOURCE_UNAVAILABLE", 503, "try later")

    with pytest.raises(DomainError):
        b.consume(d, unavailable)
    with b.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] == 0
        assert (
            tx.execute(
                "SELECT 1 FROM sqlite_master WHERE name='forbidden_effect'"
            ).fetchone()
            is None
        )
    assert a.pending_count(f.project_id) == 1


@pytest.mark.parametrize(
    "name",
    [
        "SapBomRequest",
        "SapPurchaseRequirement",
        "WmsCustody",
        "WmsQualification",
        "MesProcessRequest",
        "MesTestRequest",
        "MesDeliveryContext",
        "MesReturnRequirement",
        "MesApprovalRequest",
    ],
)
def test_context_facts_have_closed_policy_and_scoped_durable_delivery(tmp_path, name):
    from manufacturing_platform.workflow.integrations import contracts
    from manufacturing_platform.workflow.integrations.catalog import EDGES
    from manufacturing_platform.workflow.integrations.operations import fact_policy

    from .test_contracts import sample_from_schema

    model = getattr(contracts, name)
    schema = model.model_json_schema()
    data = sample_from_schema(schema, schema.get("$defs", {}))
    if name == "WmsQualification":
        data["receipt"].update(system="wms", object_type="receipt")
    payload = model.model_validate(data)
    system, kind = payload.fact_type.split(".")
    f = IntegrationFact(
        project_id=uuid4(),
        source=dict(
            system=system,
            object_type=kind,
            external_id="context-1",
            version=1,
            occurred_at=NOW,
            collected_at=NOW,
            evidence="context signature",
        ),
        payload=payload,
        external_actor="Context producer",
        evidence="context signature",
    )
    assert fact_policy(f)
    edge = next(
        e for e in EDGES if e.producer == system and payload.fact_type in e.fact_types
    )
    source = store(tmp_path, system)
    target = store(tmp_path, edge.consumer)
    with source.transaction(write=True) as tx:
        source.append_fact(tx, f)
        d = source.enqueue(tx, f, edge.consumer)
    assert target.consume(d, lambda tx, d: None).phase == "accepted"
    with pytest.raises(DomainError):
        target.consume(
            d.model_copy(update={"project_id": uuid4()}),
            lambda tx, d: pytest.fail("cross-project effect"),
        )
    from pydantic import ValidationError

    required = next(iter(schema["required"]))
    invalid = data.copy()
    invalid.pop(required)
    with pytest.raises(ValidationError):
        model.model_validate(invalid)


def test_simultaneous_first_open_and_same_operation_commit_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    s = store(tmp_path)
    f = fact()
    op = SystemOperation(
        operation_id=uuid4(),
        system="sap",
        project_id=f.project_id,
        payload=order_payload(),
    )
    barrier = Barrier(4)

    def apply(tx, operation):
        seq = s.append_fact(tx, f)
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

    def run(_):
        barrier.wait()
        return s.execute(op, apply)

    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(run, range(4)))
    assert all(r == receipts[0] for r in receipts)
    with s.transaction() as tx:
        assert tx.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 1
        assert tx.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 1
