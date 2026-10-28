from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from .test_exchanges import authority, reserve, stock


def test_authority_atomic_competition_and_changed_hash(workflow):
    p, _, supply, result = reserve(workflow)
    a = stock(workflow, p, supply)
    import json
    from uuid import uuid4

    from manufacturing_platform.workflow.contracts import DomainError
    from manufacturing_platform.workflow.exchange_models import ExternalRequest

    with workflow.db() as db:
        body = json.loads(
            db.execute(
                "SELECT request_json FROM exchanges WHERE id=?",
                (result["exchange_id"],),
            ).fetchone()[0]
        )
    first = ExternalRequest.model_validate(body)
    second = first.model_copy(
        update={
            "id": uuid4(),
            "business_key": str(uuid4()),
            "typed_payload": first.typed_payload.model_copy(
                update={"reservation_id": uuid4(), "work_order_id": uuid4()}
            ),
        }
    )
    barrier = Barrier(2)

    def submit(request):
        adapter = authority(workflow)  # Independent connection per call.
        barrier.wait()
        return adapter.submit(request)

    with ThreadPoolExecutor(2) as pool:
        receipts = list(pool.map(submit, [first, second]))
    assert sorted(r.phase for r in receipts) == ["accepted", "rejected"]
    assert a.balance(supply["lot_id"]) == "20"
    assert a.operation_count() == 2
    for request, receipt in zip([first, second], receipts):
        assert a.submit(request) == receipt
    with pytest.raises(DomainError, match="different payload"):
        a.submit(first.model_copy(update={"source_version": first.source_version + 1}))
    workflow.reopen()
    assert authority(workflow).operation_count() == 2
    assert authority(workflow).balance(supply["lot_id"]) == "20"


@pytest.mark.parametrize(
    "field,value",
    [("owner_id", "Other owner"), ("unit", "piece"), ("material_id", "Other material")],
)
def test_authority_rejects_wrong_stock_identity_without_changing_balance(
    workflow, field, value
):
    import json
    from uuid import uuid4

    from manufacturing_platform.workflow.exchange_models import ExternalRequest

    p, _, supply, result = reserve(workflow)
    a = stock(workflow, p, supply)
    with workflow.db() as db:
        body = json.loads(
            db.execute(
                "SELECT request_json FROM exchanges WHERE id=?",
                (result["exchange_id"],),
            ).fetchone()[0]
        )
    body["typed_payload"][field] = value
    body["business_key"] = str(uuid4())
    receipt = a.submit(ExternalRequest.model_validate(body))
    assert receipt.phase == "rejected" and receipt.accepted_quantity == 0
    assert a.balance(supply["lot_id"]) == "100"
    assert a.operation_count() == 1


def test_authority_receiving_never_overflows_integer_atoms(workflow):
    import sqlite3

    from manufacturing_platform.workflow.contracts import DomainError

    p, _, supply, _ = reserve(workflow)
    a = authority(workflow)
    fields = {
        "project_id": p["id"],
        "commitment_id": supply["id"],
        "lot_id": supply["lot_id"],
        "material_id": "steel-1",
        "owner_id": "Customer 1",
        "unit": "kg",
        "scale": 3,
        "expiry": "2027-12-01",
        "external_actor": "External receiving",
        "signature": "Signed slip",
    }
    a.receive(external_id="large-1", quantity="9223372036854775.807", **fields)
    with pytest.raises(DomainError):
        a.receive(external_id="large-2", quantity="1", **fields)
    with sqlite3.connect(workflow.paths.authority) as db:
        assert (
            db.execute("SELECT typeof(received) FROM inventory").fetchone()[0]
            == "integer"
        )
        assert db.execute("SELECT COUNT(*) FROM source_events").fetchone()[0] == 1
