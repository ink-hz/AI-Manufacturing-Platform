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


# Review wave: source-envelope admission, event identity and receipt conservation.
def review_receipt(workflow, p, supply, quantity="100"):
    a = authority(workflow)
    return a.receive(
        project_id=p["id"],
        external_id="review-delivery",
        commitment_id=supply["id"],
        lot_id=supply["lot_id"],
        material_id="steel-1",
        owner_id="Customer 1",
        quantity=quantity,
        unit="kg",
        scale=3,
        expiry="2027-12-01",
        external_actor="WMS receiving",
        signature="Signed receiving",
    )


def review_iqc(workflow, p, external_id, accepted, rejected="0", manual_iqc_id=None):
    return authority(workflow).inspect(
        project_id=p["id"],
        external_id=external_id,
        receipt_external_id="review-delivery",
        accepted=accepted,
        rejected=rejected,
        external_actor="QMS inspector",
        signature="Signed " + external_id,
        manual_iqc_id=manual_iqc_id,
    )


def review_import(workflow, p, row, actor, **updates):
    body = row.model_dump(mode="json")
    body.update(updates)
    body["source"]["mode"] = "file"
    return workflow.command(
        p["id"],
        "source.import",
        actor_name=actor,
        object_type=body["object_type"],
        rows=[body],
    )


def review_pull(workflow, p, kind, external, actor):
    return workflow.command(
        p["id"],
        "source.pull",
        actor_name=actor,
        system="erp",
        object_type=kind,
        external_id=external,
    )


def review_correct(
    workflow, p, pulled, kind, external, actor="quality", expected_status=200
):
    return workflow.command(
        p["id"],
        "exchange.reconcile",
        actor_name=actor,
        exchange_id=pulled["exchange_id"],
        source=workflow.source(external, object_type=kind),
        object_type=kind,
        source_version=1,
        details=[],
        resolution="accept_authority",
        evidence="Scoped authority detail checked",
        expected_status=expected_status,
    )


@pytest.mark.parametrize("hidden_kind", ["iqc", "customer_approval"])
def test_review_snapshot_record_cannot_borrow_receipt_policy(
    workflow, monkeypatch, hidden_kind
):
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter
    from manufacturing_platform.workflow.exchange_models import AuthoritySnapshot

    p, req, supply, _ = reserve(workflow)
    receipt = review_receipt(workflow, p, supply)
    review_import(workflow, p, receipt, "supply")
    hidden = (
        review_iqc(workflow, p, "hidden-event", "30")
        if hidden_kind == "iqc"
        else authority(workflow).customer_approval(
            project_id=p["id"],
            external_id="hidden-event",
            revision_id=supply["revision_id"],
            customer_id="Customer 1",
            decision="approved",
            external_actor="Customer",
            signature="Signed approval",
        )
    )
    monkeypatch.setattr(
        MockAuthorityAdapter,
        "snapshot",
        lambda *args: AuthoritySnapshot(
            system="erp", object_type="receipt", sequence=2, records=[hidden]
        ),
    )
    pulled = review_pull(workflow, p, "receipt", "hidden-event", "supply")
    assert (
        workflow.object(p["id"], "exchange", pulled["exchange_id"])["phase"]
        == "rejected"
    )
    assert workflow.balance(p["id"], req["id"])["qualified"] == "0"
    with workflow.db() as db:
        assert db.execute("SELECT COUNT(*) FROM customer_approvals").fetchone()[0] == 0
        assert (
            db.execute(
                "SELECT COUNT(*) FROM exchange_events WHERE exchange_id=? AND json_type(payload_json,'$.records')='array'",
                (pulled["exchange_id"],),
            ).fetchone()[0]
            == 0
        )


def test_review_partial_cross_mode_iqc_uses_exact_event_identity(workflow):
    p, req, supply, _ = reserve(workflow)
    receipt = review_receipt(workflow, p, supply)
    first = review_iqc(workflow, p, "iqc-one", "30")
    second = review_iqc(workflow, p, "iqc-two", "20")
    review_import(workflow, p, receipt, "supply")
    review_import(workflow, p, first, "quality", accepted="20")
    review_import(workflow, p, second, "quality")
    pulled = review_pull(workflow, p, "iqc", "iqc-one", "quality")
    assert (
        workflow.object(p["id"], "exchange", pulled["exchange_id"])["phase"]
        == "rejected"
    )
    assert workflow.balance(p["id"], req["id"])["qualified"] == "40"
    review_correct(workflow, p, pulled, "iqc", "iqc-one")
    assert workflow.balance(p["id"], req["id"])["qualified"] == "50"
    with workflow.db() as db:
        assert db.execute("SELECT COUNT(*) FROM iqc_results").fetchone()[0] == 2
        rows = db.execute(
            "SELECT external_id,COUNT(DISTINCT fact_id) FROM source_confirmations WHERE object_type='iqc' GROUP BY external_id ORDER BY external_id"
        ).fetchall()
        assert [tuple(r) for r in rows] == [("iqc-one", 1), ("iqc-two", 1)]


def test_review_equal_quantity_distinct_source_events_are_not_deduplicated(workflow):
    p, req, supply, _ = reserve(workflow)
    receipt = review_receipt(workflow, p, supply)
    first = review_iqc(workflow, p, "iqc-one", "20")
    review_iqc(workflow, p, "iqc-two", "20")
    review_import(workflow, p, receipt, "supply")
    review_import(workflow, p, first, "quality")
    review_pull(workflow, p, "iqc", "iqc-two", "quality")
    assert workflow.balance(p["id"], req["id"])["qualified"] == "40"
    with workflow.db() as db:
        assert db.execute("SELECT COUNT(*) FROM iqc_results").fetchone()[0] == 2


def test_review_explicit_manual_id_allows_quantity_correction(workflow):
    p, req, supply, _ = reserve(workflow)
    receipt = review_receipt(workflow, p, supply)
    local = review_import(workflow, p, receipt, "supply")
    workflow.inspect(p["id"], local["object_id"], accepted="80", rejected="20")
    with workflow.db() as db:
        manual_id = db.execute("SELECT id FROM iqc_results").fetchone()[0]
    review_iqc(workflow, p, "iqc-explicit", "100", manual_iqc_id=manual_id)
    pulled = review_pull(workflow, p, "iqc", "iqc-explicit", "quality")
    assert (
        workflow.object(p["id"], "exchange", pulled["exchange_id"])["phase"]
        == "rejected"
    )
    review_correct(workflow, p, pulled, "iqc", "iqc-explicit")
    assert workflow.balance(p["id"], req["id"])["qualified"] == "100"
    with workflow.db() as db:
        assert tuple(
            db.execute(
                "SELECT accepted_atoms,rejected_atoms FROM iqc_results WHERE id=?",
                (manual_id,),
            ).fetchone()
        ) == (80000, 20000)
        assert (
            db.execute("SELECT iqc_id FROM source_corrections").fetchone()[0]
            == manual_id
        )


def test_review_correction_counts_other_trusted_and_manual_inspections(workflow):
    from .conftest import BASE

    p, req, supply, _ = reserve(workflow)
    receipt = review_receipt(workflow, p, supply, "200")
    review_iqc(workflow, p, "iqc-first", "60")
    review_iqc(workflow, p, "iqc-next", "100")
    local = review_import(workflow, p, receipt, "supply", quantity="100")
    review_pull(workflow, p, "iqc", "iqc-first", "quality")
    workflow.inspect(p["id"], local["object_id"], accepted="20", rejected="0")
    pulled = review_pull(workflow, p, "iqc", "iqc-next", "quality")
    before = workflow.client().get(f"{BASE}/projects/{p['id']}").json()["version"]
    review_correct(workflow, p, pulled, "iqc", "iqc-next", expected_status=409)
    assert (
        workflow.client().get(f"{BASE}/projects/{p['id']}").json()["version"] == before
    )
    assert workflow.balance(p["id"], req["id"])["qualified"] == "80"
    with workflow.db() as db:
        assert db.execute("SELECT COUNT(*) FROM source_corrections").fetchone()[0] == 0
    # Reconcile the actual receipt first, then the same retained IQC event can be corrected.
    received = review_pull(workflow, p, "receipt", "review-delivery", "supply")
    review_correct(workflow, p, received, "receipt", "review-delivery", "supply")
    review_correct(workflow, p, pulled, "iqc", "iqc-next")
    assert workflow.balance(p["id"], req["id"])["qualified"] == "160"
    assert (
        workflow.object(p["id"], "receipt", local["object_id"])["uninspected"] == "40"
    )


@pytest.mark.parametrize("entry", ["source.import", "source.import_file"])
def test_review_import_envelope_cannot_admit_another_business_type(workflow, entry):
    p, req, supply, _ = reserve(workflow)
    receipt = review_receipt(workflow, p, supply)
    review_import(workflow, p, receipt, "supply")
    iqc = review_iqc(workflow, p, "hidden-import", "20").model_dump(mode="json")
    iqc["source"]["mode"] = "file"
    fields = (
        {"rows": [iqc]}
        if entry == "source.import"
        else {
            "format": "json",
            "content_base64": base64.b64encode(json.dumps([iqc]).encode()).decode(),
        }
    )
    workflow.command(
        p["id"],
        entry,
        actor_name="supply",
        object_type="receipt",
        expected_status=422,
        **fields,
    )
    assert workflow.balance(p["id"], req["id"])["qualified"] == "0"


def test_review_ambiguous_manual_rows_require_explicit_link(workflow):
    p, req, supply, _ = reserve(workflow)
    receipt = review_receipt(workflow, p, supply)
    local = review_import(workflow, p, receipt, "supply")
    workflow.inspect(p["id"], local["object_id"], accepted="20", rejected="0")
    workflow.inspect(p["id"], local["object_id"], accepted="20", rejected="0")
    review_iqc(workflow, p, "ambiguous-event", "20")
    pulled = review_pull(workflow, p, "iqc", "ambiguous-event", "quality")
    assert (
        workflow.object(p["id"], "exchange", pulled["exchange_id"])["phase"]
        == "rejected"
    )
    review_correct(workflow, p, pulled, "iqc", "ambiguous-event", expected_status=409)
    assert workflow.balance(p["id"], req["id"])["qualified"] == "40"
    with workflow.db() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM source_confirmations WHERE object_type='iqc'"
            ).fetchone()[0]
            == 0
        )


def test_review_normalized_event_identity_binds_exact_partial_fact(workflow):
    p, req, supply, _ = reserve(workflow)
    receipt = review_receipt(workflow, p, supply)
    review_import(workflow, p, receipt, "supply")
    record = review_iqc(workflow, p, "CaseSensitive-IQC", "30")
    file = record.model_copy(deep=True)
    file.source.system = " ERP "
    file.source.object_type = " IQC "
    file.source.external_id = " CaseSensitive-IQC "
    review_import(workflow, p, file, "quality", accepted="20")
    pulled = review_pull(workflow, p, "iqc", "CaseSensitive-IQC", "quality")
    assert workflow.balance(p["id"], req["id"])["qualified"] == "20"
    assert (
        workflow.object(p["id"], "exchange", pulled["exchange_id"])["phase"]
        == "rejected"
    )
    review_correct(workflow, p, pulled, "iqc", "CaseSensitive-IQC")
    assert workflow.balance(p["id"], req["id"])["qualified"] == "30"
    with workflow.db() as db:
        assert db.execute("SELECT COUNT(*) FROM iqc_results").fetchone()[0] == 1


def test_review_inspection_invariant_applies_to_file_batch_after_corrections(workflow):
    from .conftest import BASE

    p, req, supply, _ = reserve(workflow)
    receipt = review_receipt(workflow, p, supply, "200")
    local = review_import(workflow, p, receipt, "supply", quantity="100")
    record = review_iqc(workflow, p, "file-partial", "60")
    review_import(workflow, p, record, "quality", accepted="20")
    pulled = review_pull(workflow, p, "iqc", "file-partial", "quality")
    review_correct(workflow, p, pulled, "iqc", "file-partial")
    rows = []
    for external, q in [("batch-one", "30"), ("batch-two", "20")]:
        row = record.model_dump(mode="json")
        row["source"].update(mode="file", external_id=external)
        row["accepted"] = q
        rows.append(row)
    before = workflow.client().get(f"{BASE}/projects/{p['id']}").json()["version"]
    bad = workflow.command(
        p["id"],
        "source.import",
        actor_name="quality",
        object_type="iqc",
        rows=rows,
        expected_status=409,
    )
    assert bad["fields"]["line"] == 2
    assert (
        workflow.client().get(f"{BASE}/projects/{p['id']}").json()["version"] == before
    )
    assert workflow.balance(p["id"], req["id"])["qualified"] == "60"
    # Correcting the receipt to200 makes the same complete file batch valid.
    received = review_pull(workflow, p, "receipt", "review-delivery", "supply")
    review_correct(workflow, p, received, "receipt", "review-delivery", "supply")
    workflow.command(
        p["id"],
        "source.import_file",
        actor_name="quality",
        object_type="iqc",
        format="json",
        content_base64=base64.b64encode(json.dumps(rows).encode()).decode(),
    )
    assert (
        workflow.object(p["id"], "receipt", local["object_id"])["uninspected"] == "90"
    )
    workflow.command(
        p["id"],
        "supply.inspect",
        actor_name="quality",
        receipt_id=local["object_id"],
        accepted="91",
        rejected="0",
        evidence="Too much after corrections",
        expected_status=409,
    )


@pytest.mark.parametrize("bad_target", ["wrong_receipt", "foreign_project"])
def test_review_explicit_iqc_link_must_be_scoped_before_retention(workflow, bad_target):
    p, _req, supply, _ = reserve(workflow)
    receipt = review_receipt(workflow, p, supply)
    review_import(workflow, p, receipt, "supply")
    if bad_target == "foreign_project":
        other, _, _other_supply = workflow.material_requirement(qualified="20")
        with workflow.db() as db:
            bad_id = db.execute(
                "SELECT id FROM iqc_results WHERE project_id=?", (other["id"],)
            ).fetchone()[0]
    else:
        other = workflow.receive(
            p["id"], supply["id"], quantity="20", lot_id=supply["lot_id"]
        )
        workflow.inspect(p["id"], other["object_id"], accepted="20", rejected="0")
        with workflow.db() as db:
            bad_id = db.execute(
                "SELECT id FROM iqc_results WHERE receipt_id=?", (other["object_id"],)
            ).fetchone()[0]
    review_iqc(workflow, p, "bad-target", "20", manual_iqc_id=bad_id)
    pulled = review_pull(workflow, p, "iqc", "bad-target", "quality")
    value = workflow.object(p["id"], "exchange", pulled["exchange_id"])
    assert value["phase"] == "rejected" and value["source"] is None
    with workflow.db() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM exchange_events WHERE exchange_id=? AND json_type(payload_json,'$.records')='array'",
                (pulled["exchange_id"],),
            ).fetchone()[0]
            == 0
        )
        assert (
            db.execute(
                "SELECT COUNT(*) FROM source_confirmations WHERE external_id='bad-target'"
            ).fetchone()[0]
            == 0
        )


def test_review_explicit_correction_keeps_other_manual_and_trusted_rows(workflow):
    from .conftest import BASE

    p, req, supply, _ = reserve(workflow)
    receipt = review_receipt(workflow, p, supply, "200")
    local = review_import(workflow, p, receipt, "supply", quantity="100")
    review_iqc(workflow, p, "trusted-first", "60")
    review_pull(workflow, p, "iqc", "trusted-first", "quality")
    workflow.inspect(p["id"], local["object_id"], accepted="20", rejected="0")
    with workflow.db() as db:
        target = db.execute(
            "SELECT id FROM iqc_results WHERE accepted_atoms=20000"
        ).fetchone()[0]
    workflow.inspect(p["id"], local["object_id"], accepted="10", rejected="0")
    review_iqc(workflow, p, "explicit-next", "40", manual_iqc_id=target)
    pulled = review_pull(workflow, p, "iqc", "explicit-next", "quality")
    version = workflow.client().get(f"{BASE}/projects/{p['id']}").json()["version"]
    review_correct(workflow, p, pulled, "iqc", "explicit-next", expected_status=409)
    assert (
        workflow.client().get(f"{BASE}/projects/{p['id']}").json()["version"] == version
    )
    assert workflow.balance(p["id"], req["id"])["qualified"] == "90"
    received = review_pull(workflow, p, "receipt", "review-delivery", "supply")
    review_correct(workflow, p, received, "receipt", "review-delivery", "supply")
    review_correct(workflow, p, pulled, "iqc", "explicit-next")
    assert workflow.balance(p["id"], req["id"])["qualified"] == "110"
    with workflow.db() as db:
        assert db.execute("SELECT COUNT(*) FROM iqc_results").fetchone()[0] == 3
        assert (
            db.execute(
                "SELECT COUNT(*) FROM source_corrections WHERE iqc_id=?", (target,)
            ).fetchone()[0]
            == 1
        )


def test_review_newer_version_of_same_iqc_event_never_adds_an_inspection(
    workflow, monkeypatch
):
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

    p, req, supply, _ = reserve(workflow)
    receipt = review_receipt(workflow, p, supply)
    review_import(workflow, p, receipt, "supply")
    record = review_iqc(workflow, p, "versioned-iqc", "20")
    review_import(workflow, p, record, "quality")
    advanced = record.model_dump(mode="json")
    advanced["source"].update(mode="file", version=2)
    advanced["accepted"] = "30"
    workflow.command(
        p["id"],
        "source.import",
        actor_name="quality",
        object_type="iqc",
        rows=[advanced],
        expected_status=409,
    )
    original = MockAuthorityAdapter.snapshot

    def newer(self, system, kind):
        snapshot = original(self, system, kind)
        if kind == "iqc":
            snapshot.records[0].source.version = 2
        return snapshot

    monkeypatch.setattr(MockAuthorityAdapter, "snapshot", newer)
    pulled = review_pull(workflow, p, "iqc", "versioned-iqc", "quality")
    assert (
        workflow.object(p["id"], "exchange", pulled["exchange_id"])["phase"]
        == "rejected"
    )
    assert workflow.balance(p["id"], req["id"])["qualified"] == "20"
    with workflow.db() as db:
        assert db.execute("SELECT COUNT(*) FROM iqc_results").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM source_corrections").fetchone()[0] == 0
        assert (
            db.execute(
                "SELECT COUNT(*) FROM source_confirmations WHERE object_type='iqc'"
            ).fetchone()[0]
            == 1
        )
