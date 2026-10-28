import base64
import json

import pytest

from .test_exchanges import authority, reserve, stock


def test_pull_real_receipt_and_iqc_no_double_manual_count(workflow):
    p, req, supply, _ = reserve(workflow)
    stock(workflow, p, supply)
    source = workflow.source("delivery-1", object_type="receipt")
    workflow.receive(
        p["id"], supply["id"], quantity="100", lot_id=supply["lot_id"], source=source
    )
    for kind, external_id, actor in [
        ("receipt", "delivery-1", "supply"),
        ("iqc", "iqc-1", "quality"),
    ]:
        workflow.command(
            p["id"],
            "source.pull",
            actor_name=actor,
            system="erp",
            object_type=kind,
            external_id=external_id,
        )
        workflow.command(
            p["id"],
            "source.pull",
            actor_name=actor,
            system="erp",
            object_type=kind,
            external_id=external_id,
        )
    assert workflow.balance(p["id"], req["id"])["received"] == "100"
    assert workflow.balance(p["id"], req["id"])["qualified"] == "100"
    with workflow.db() as db:
        assert db.execute("SELECT COUNT(*) FROM supply_receipts").fetchone()[0] == 1
        assert (
            json.loads(
                db.execute("SELECT source_json FROM supply_receipts").fetchone()[0]
            )["mode"]
            == "manual"
        )
        assert (
            db.execute("SELECT COUNT(*) FROM source_confirmations").fetchone()[0] == 2
        )
    workflow.reopen()
    assert authority(workflow).balance(supply["lot_id"]) == "100"


@pytest.mark.parametrize(
    "format,content",
    [
        ("json", b'[{"broken": true}]'),
        ("csv", b"unexpected\nfoo\n"),
        ("json", b"x" * (1024 * 1024 + 1)),
    ],
)
def test_file_parse_rejection_has_no_success(workflow, format, content):
    p = workflow.create_project()
    workflow.grant(p["id"], "supply", ["supply"])
    with workflow.db() as db:
        before = db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    workflow.command(
        p["id"],
        "source.import_file",
        actor_name="supply",
        expected_status=422,
        object_type="receipt",
        format=format,
        content_base64=base64.b64encode(content).decode(),
    )
    with workflow.db() as db:
        assert db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == before


def record(workflow, p, supply, external_id="file-delivery", quantity="10"):
    return {
        "object_type": "receipt",
        "project_id": p["id"],
        "source": workflow.source(external_id, object_type="receipt", mode="file"),
        "external_actor": "Supplier Jane",
        "signature": "Supplier signed slip",
        "commitment_id": supply["id"],
        "material_lot_id": supply["lot_id"],
        "quantity": quantity,
        "unit": "kg",
    }


def test_all_rows_use_domain_validators_and_rollback_before_success(workflow):
    p, req, supply, _ = reserve(workflow)
    first = record(workflow, p, supply)
    bad = {**record(workflow, p, supply, "other"), "unit": "wrong"}
    for action, fields in [
        ("source.import", {"rows": [first, bad]}),
        (
            "source.import_file",
            {
                "format": "json",
                "content_base64": base64.b64encode(
                    json.dumps([first, bad]).encode()
                ).decode(),
            },
        ),
    ]:
        response = workflow.command(
            p["id"],
            action,
            actor_name="supply",
            object_type="receipt",
            expected_status=409,
            **fields,
        )
        assert response["fields"]["line"] == 2
        assert workflow.balance(p["id"], req["id"])["received"] == "0"
    workflow.command(
        p["id"],
        "source.import",
        actor_name="supply",
        object_type="receipt",
        rows=[first],
    )
    assert workflow.balance(p["id"], req["id"])["received"] == "10"
    assert authority(workflow).balance(supply["lot_id"]) == "0"
    with workflow.db() as db:
        assert (
            json.loads(
                db.execute("SELECT source_json FROM supply_receipts").fetchone()[0]
            )["mode"]
            == "file"
        )


def test_forged_api_mock_import_and_wrong_role_rejected(workflow):
    p, req, supply, _ = reserve(workflow)
    for mode in ("api", "mock"):
        value = record(workflow, p, supply)
        value["source"]["mode"] = mode
        response = workflow.command(
            p["id"],
            "source.import",
            actor_name="supply",
            object_type="receipt",
            rows=[value],
            expected_status=422,
        )
        assert response["code"] == "IMPORT_INVALID"
    workflow.command(
        p["id"],
        "source.import",
        actor_name="planner",
        object_type="receipt",
        rows=[record(workflow, p, supply)],
        expected_status=403,
    )
    assert workflow.balance(p["id"], req["id"])["received"] == "0"


def test_manual_iqc_confirmation_and_external_customer_actor(workflow):
    p, req, supply, _ = reserve(workflow)
    a = stock(workflow, p, supply)
    received = workflow.receive(
        p["id"],
        supply["id"],
        quantity="100",
        lot_id=supply["lot_id"],
        source=workflow.source("delivery-1", object_type="receipt"),
    )
    workflow.inspect(p["id"], received["object_id"], accepted="100", rejected="0")
    for kind, external, actor in [
        ("receipt", "delivery-1", "supply"),
        ("iqc", "iqc-1", "quality"),
    ]:
        workflow.command(
            p["id"],
            "source.pull",
            actor_name=actor,
            system="erp",
            object_type=kind,
            external_id=external,
        )
    assert workflow.balance(p["id"], req["id"])["qualified"] == "100"
    with workflow.db() as db:
        assert db.execute("SELECT COUNT(*) FROM iqc_results").fetchone()[0] == 1
    a.customer_approval(
        project_id=p["id"],
        external_id="approval-1",
        revision_id=supply["revision_id"],
        customer_id="Customer 1",
        decision="approved",
        external_actor="Customer Alice",
        signature="Customer signed C1",
    )
    workflow.command(
        p["id"],
        "source.pull",
        system="erp",
        object_type="customer_approval",
        external_id="approval-1",
    )
    approval = workflow.object(p["id"], "revision", supply["revision_id"])[
        "customer_approvals"
    ][-1]
    assert (
        approval["method"] == "mock"
        and approval["external_signatory"] == "Customer Alice"
    )


def test_mismatched_manual_quantity_can_be_resolved_by_trusted_correction_event(
    workflow,
):
    p, req, supply, _ = reserve(workflow)
    stock(workflow, p, supply)
    received = workflow.receive(
        p["id"],
        supply["id"],
        quantity="80",
        lot_id=supply["lot_id"],
        source=workflow.source("delivery-1", object_type="receipt"),
    )
    pull = workflow.command(
        p["id"],
        "source.pull",
        actor_name="supply",
        system="erp",
        object_type="receipt",
        external_id="delivery-1",
    )
    assert (
        workflow.object(p["id"], "exchange", pull["exchange_id"])["phase"] == "rejected"
    )
    workflow.command(
        p["id"],
        "exchange.reconcile",
        actor_name="supply",
        exchange_id=pull["exchange_id"],
        source=workflow.source("delivery-1", object_type="receipt"),
        object_type="receipt",
        source_version=1,
        details=[],
        resolution="accept_authority",
        evidence="Warehouse checked original slip; manual count corrected by external record",
    )
    assert workflow.balance(p["id"], req["id"])["received"] == "100"
    assert (
        workflow.object(p["id"], "receipt", received["object_id"])["source"]["mode"]
        == "manual"
    )
    with workflow.db() as db:
        assert db.execute("SELECT q_atoms FROM supply_receipts").fetchone()[0] == 80000
        assert db.execute("SELECT COUNT(*) FROM source_corrections").fetchone()[0] == 1


def test_file_then_trusted_pull_confirms_same_identity_without_double_iqc(workflow):
    p, req, supply, _ = reserve(workflow)
    a = stock(workflow, p, supply)
    receipt = a.snapshot("erp", "receipt").records[0].model_dump(mode="json")
    iqc = a.snapshot("erp", "iqc").records[0].model_dump(mode="json")
    for row, actor in [(receipt, "supply"), (iqc, "quality")]:
        row["source"]["mode"] = "file"
        workflow.command(
            p["id"],
            "source.import",
            actor_name=actor,
            object_type=row["object_type"],
            rows=[row],
        )
        pulled = workflow.command(
            p["id"],
            "source.pull",
            actor_name=actor,
            system="erp",
            object_type=row["object_type"],
            external_id=row["source"]["external_id"],
        )
        assert (
            workflow.object(p["id"], "exchange", pulled["exchange_id"])["phase"]
            == "accepted"
        )
    assert workflow.balance(p["id"], req["id"])["received"] == "100"
    assert workflow.balance(p["id"], req["id"])["qualified"] == "100"


def test_mismatched_manual_iqc_reconciles_without_mutating_original(workflow):
    p, req, supply, _ = reserve(workflow)
    stock(workflow, p, supply)
    received = workflow.receive(
        p["id"],
        supply["id"],
        quantity="100",
        lot_id=supply["lot_id"],
        source=workflow.source("delivery-1", object_type="receipt"),
    )
    workflow.inspect(p["id"], received["object_id"], accepted="80", rejected="20")
    pull = workflow.command(
        p["id"],
        "source.pull",
        actor_name="quality",
        system="erp",
        object_type="iqc",
        external_id="iqc-1",
    )
    assert (
        workflow.object(p["id"], "exchange", pull["exchange_id"])["phase"] == "rejected"
    )
    workflow.command(
        p["id"],
        "exchange.reconcile",
        actor_name="quality",
        exchange_id=pull["exchange_id"],
        source=workflow.source("iqc-1", object_type="iqc"),
        object_type="iqc",
        source_version=1,
        details=[],
        resolution="accept_authority",
        evidence="Signed IQC confirms 100 accepted",
    )
    assert workflow.balance(p["id"], req["id"])["qualified"] == "100"
    assert workflow.balance(p["id"], req["id"])["rejected"] == "0"
    with workflow.db() as db:
        assert tuple(
            db.execute(
                "SELECT accepted_atoms,rejected_atoms FROM iqc_results"
            ).fetchone()
        ) == (80000, 20000)


def test_json_duplicate_field_is_line_specific_parse_failure(workflow):
    p, req, supply, _ = reserve(workflow)
    raw = json.dumps([record(workflow, p, supply)]).replace(
        '"quantity": "10"', '"quantity": "10", "quantity": "20"'
    )
    response = workflow.command(
        p["id"],
        "source.import_file",
        actor_name="supply",
        expected_status=422,
        object_type="receipt",
        format="json",
        content_base64=base64.b64encode(raw.encode()).decode(),
    )
    assert response["code"] == "IMPORT_INVALID"
    assert response["fields"]["line"] == 1
    assert workflow.balance(p["id"], req["id"])["received"] == "0"


def test_file_import_has_received_and_validated_stages_without_authority_acceptance(
    workflow,
):
    p, _req, supply, _ = reserve(workflow)
    result = workflow.command(
        p["id"],
        "source.import",
        actor_name="supply",
        object_type="receipt",
        rows=[record(workflow, p, supply)],
    )
    value = workflow.object(p["id"], "exchange", result["exchange_id"])
    assert value["mode"] == "file"
    assert value["phase"] == "validated"
    assert [e["phase"] for e in reversed(value["events"])] == ["received", "validated"]
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="supply",
        exchange_id=result["exchange_id"],
        expected_status=409,
    )


def test_adapter_provenance_mismatch_is_rejected_before_any_fact(workflow, monkeypatch):
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    p, req, supply, _ = reserve(workflow)
    stock(workflow, p, supply)
    original = MockAuthorityAdapter.snapshot

    def wrong(self, system, kind):
        snapshot = original(self, system, kind)
        snapshot.records[0].source.mode = "api"
        return snapshot

    monkeypatch.setattr(MockAuthorityAdapter, "snapshot", wrong)
    result = workflow.command(
        p["id"],
        "source.pull",
        actor_name="supply",
        system="erp",
        object_type="receipt",
        external_id="delivery-1",
    )
    assert workflow.balance(p["id"], req["id"])["received"] == "0"
    assert (
        workflow.object(p["id"], "exchange", result["exchange_id"])["phase"]
        == "rejected"
    )


def test_manual_customer_approval_is_confirmed_without_losing_origin(workflow):
    p, _, supply, _ = reserve(workflow)
    workflow.command(
        p["id"],
        "engineering.customer_approval",
        revision_id=supply["revision_id"],
        method="manual",
        customer_id="Customer 1",
        external_signatory="Customer Alice",
        decision="approved",
        evidence="Customer signed C1",
    )
    a = authority(workflow)
    a.customer_approval(
        project_id=p["id"],
        external_id="approval-before-pull",
        revision_id=supply["revision_id"],
        customer_id="Customer 1",
        decision="approved",
        external_actor="Customer Alice",
        signature="Customer signed C1",
    )
    workflow.command(
        p["id"],
        "source.pull",
        system="erp",
        object_type="customer_approval",
        external_id="approval-before-pull",
    )
    approvals = workflow.object(p["id"], "revision", supply["revision_id"])[
        "customer_approvals"
    ]
    assert len(approvals) == 1
    assert approvals[0]["method"] == "manual"
    assert approvals[0]["source"]["mode"] == "mock"


def test_corrected_receipt_detail_displays_original_manual_quantity(workflow):
    p, _, supply, _ = reserve(workflow)
    stock(workflow, p, supply)
    received = workflow.receive(
        p["id"],
        supply["id"],
        quantity="80",
        lot_id=supply["lot_id"],
        source=workflow.source("delivery-1", object_type="receipt"),
    )
    pull = workflow.command(
        p["id"],
        "source.pull",
        actor_name="supply",
        system="erp",
        object_type="receipt",
        external_id="delivery-1",
    )
    workflow.command(
        p["id"],
        "exchange.reconcile",
        actor_name="supply",
        exchange_id=pull["exchange_id"],
        source=workflow.source("delivery-1", object_type="receipt"),
        object_type="receipt",
        source_version=1,
        details=[],
        resolution="accept_authority",
        evidence="Retain original 80; authority confirms 100",
    )
    value = workflow.object(p["id"], "receipt", received["object_id"])
    assert value["original_quantity"] == "80" and value["quantity"] == "100"
    assert value["corrections"][0]["received_delta"] == "20"
