"""Real equipment, owned original artifacts and external evidence."""

import hashlib
import json
from uuid import uuid4

import pytest
from manufacturing_platform.workflow.contracts import DomainError
from .support import NOW


@pytest.fixture
def rig(network_rig):
    return network_rig


def test_plc_observation_binds_actual_mes_process_request(rig):
    assert rig.registry.available("plc"), "PLC producer is not configured"
    refs = rig.start_ready()
    key = refs.start_payload["equipment"]
    from manufacturing_platform.workflow.integrations.core_models import SourceKey

    detail = rig.workflow.integration_fact(
        rig.actor, rig.project_id, SourceKey.model_validate(key)
    )
    assert detail.auxiliary_records[0].kind == "equipment"
    assert detail.auxiliary_records[0].equipment == "EQ1"
    assert detail.fact.caused_by
    rig.execute("mes", refs.start_payload)
    assert rig.pass_unit(refs).payload.result == "pass"


def prepare_run(rig):
    refs = rig.start_ready()
    rig.execute("mes", refs.start_payload)
    refs.execution = rig.pass_unit(refs)
    refs.run = rig.command(
        "test_run.start", plan_id=str(refs.test_plan), unit_id=refs.units[0]["unit_id"]
    ).object_id
    return refs


def test_artifact_preparation_is_owned_immutable_and_does_not_finish_run(rig):
    assert rig.registry.available("product_test"), (
        "Product-test producer is not configured"
    )
    refs = prepare_run(rig)
    prepared = rig.result_fact(
        rig.execute(
            "product_test",
            dict(
                operation="product_test.prepare_artifact",
                run_id=str(refs.run),
                template="pass-v1",
            ),
        )
    )
    p = prepared.payload.prepared
    content = rig.workflow.integration_artifact(
        rig.actor, rig.project_id, p.artifact_ref, p.artifact_checksum
    )
    assert hashlib.sha256(content).hexdigest() == p.artifact_checksum
    with rig.workflow.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT finish_json FROM test_runs WHERE id=?", (str(refs.run),)
            ).fetchone()[0]
            is None
        )
    payload = p.model_dump(mode="json", exclude={"kind"})
    fact = rig.result_fact(
        rig.execute("product_test", dict(operation="product_test.run", **payload))
    )
    assert rig.target(fact, "test_run") == refs.run
    with rig.workflow.store.transaction() as tx:
        finish = json.loads(
            tx.execute(
                "SELECT finish_json FROM test_runs WHERE id=?", (str(refs.run),)
            ).fetchone()[0]
        )
    assert finish["source"]["mode"] == "mock"
    assert finish["source"]["external_id"] == fact.source.external_id
    assert finish["outcome"] == "pass"
    assert finish["raw_digest"] != p.artifact_checksum


def measured(rig):
    refs = prepare_run(rig)
    prepared = rig.result_fact(
        rig.execute(
            "product_test",
            dict(
                operation="product_test.prepare_artifact",
                run_id=str(refs.run),
                template="pass-v1",
            ),
        )
    )
    refs.test = rig.result_fact(
        rig.execute(
            "product_test",
            dict(
                operation="product_test.run",
                **prepared.payload.prepared.model_dump(mode="json", exclude={"kind"}),
            ),
        )
    )
    return refs


def test_calibration_requires_independent_matching_plc_readback(rig):
    refs = measured(rig)
    prepared = rig.result_fact(
        rig.execute(
            "product_test",
            dict(
                operation="product_test.prepare_artifact",
                run_id=str(refs.run),
                template="calibration-v1",
            ),
        )
    )
    write = rig.result_fact(
        rig.execute(
            "product_test",
            dict(
                operation="product_test.calibrate",
                **prepared.payload.prepared.model_dump(mode="json", exclude={"kind"}),
            ),
        )
    )
    cid = rig.target(write, "calibration")
    payload = dict(
        operation="plc.readback",
        calibration=write.source_key.model_dump(),
        run_id=str(refs.run),
        unit_id=refs.units[0]["unit_id"],
        equipment="EQ1",
        source_identity="PLC-read-1",
        source_version="1",
        parameters=[
            dict(name="gain", value="1", unit="ratio"),
            dict(name="offset", value="0", unit="V"),
        ],
        observed_at=NOW.isoformat(),
        evidence="Independent PLC parameter observation",
    )
    for override in [
        dict(source_identity=write.payload.source_identity),
        dict(source_version="2"),
        dict(equipment="wrong"),
    ]:
        before = len(rig.rows("plc", "facts"))
        with pytest.raises(DomainError):
            rig.execute("plc", dict(payload, **override))
        assert len(rig.rows("plc", "facts")) == before
        with rig.workflow.store.transaction() as tx:
            assert (
                tx.execute(
                    "SELECT confirmation_json FROM calibrations WHERE id=?", (str(cid),)
                ).fetchone()[0]
                is None
            )
    mismatch = rig.result_fact(
        rig.execute(
            "plc",
            dict(
                payload,
                source_identity="PLC-failed-value",
                parameters=[
                    dict(name="gain", value="2", unit="ratio"),
                    dict(name="offset", value="0", unit="V"),
                ],
            ),
        )
    )
    observation = rig.workflow.integration_fact(
        rig.actor, rig.project_id, mismatch.source_key
    )
    assert observation.source_accepted is True
    assert observation.auxiliary_records[0].confirmation_state == "mismatched"
    assert not observation.projection.targets
    with rig.workflow.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT confirmation_json FROM calibrations WHERE id=?", (str(cid),)
            ).fetchone()[0]
            is None
        )
    before = len(rig.rows("plc", "facts"))
    with pytest.raises(DomainError):
        rig.execute("plc", dict(payload, source_identity="PLC-failed-value"))
    assert len(rig.rows("plc", "facts")) == before
    unit_mismatch = rig.result_fact(
        rig.execute(
            "plc",
            dict(
                payload,
                source_identity="PLC-failed-units",
                parameters=[
                    dict(name="gain", value="1", unit="V"),
                    dict(name="offset", value="0", unit="V"),
                ],
            ),
        )
    )
    assert unit_mismatch.payload.confirmation_matches is False
    read = rig.result_fact(rig.execute("plc", payload))
    assert rig.target(read, "calibration") == cid
    detail = rig.workflow.integration_fact(rig.actor, rig.project_id, read.source_key)
    assert detail.auxiliary_records[0].parameter_digest
    assert (
        rig.workflow.integration_fact(
            rig.actor, rig.project_id, mismatch.source_key
        ).fact
        == mismatch
    )
    with rig.workflow.store.transaction() as tx:
        confirmation = json.loads(
            tx.execute(
                "SELECT confirmation_json FROM calibrations WHERE id=?", (str(cid),)
            ).fetchone()[0]
        )
    assert confirmation["source_identity"] == "PLC-read-1"


def shipped(rig):
    refs = measured(rig)
    for kind in ("manufacturing", "quality"):
        rig.execute(
            "mes",
            dict(
                operation="mes.release",
                work_order_id=str(refs.work_order),
                units=refs.units,
                kind=kind,
                decision="approved",
                test_sources=[refs.test.source_key.model_dump()],
                evidence="Qualified release",
            ),
        )
    result = rig.command(
        "shipment.request",
        order_line_id=str(refs.order_line),
        unit_ids=[u["unit_id"] for u in refs.units],
        quantity=str(len(refs.units)),
        unit="piece",
    )
    rig.command("exchange.dispatch", exchange_id=str(result.exchange_id))
    rig.drain()
    refs.shipment = (
        rig.registry.adapter("wms")
        .facts(rig.project_id, "shipment", 0, 200)
        .records[-1]
    )
    rig.pull(refs.shipment.source_key)
    return refs


def claim_payload(refs, operation, **extra):
    return dict(
        operation=operation,
        shipment_id=str(refs.shipment.payload.shipment_id),
        shipment=refs.shipment.source_key.model_dump(),
        units=refs.units,
        amount=dict(quantity=str(len(refs.units)), unit="piece", scale=0),
        customer_id="C",
        external_signer="External recipient",
        reason="Delivery claim",
        signed_evidence="Signed shipment evidence",
        occurred_at=NOW.isoformat(),
        **extra,
    )


def test_external_receipt_acceptance_and_return_preserve_shipped_quantity(rig):
    refs = shipped(rig)
    receipt = rig.result_fact(
        rig.execute(
            "overseas",
            claim_payload(refs, "overseas.receive_shipment", decision="accepted"),
        )
    )
    acceptance = rig.result_fact(
        rig.execute(
            "customer",
            claim_payload(refs, "customer.confirm_delivery", decision="accepted"),
        )
    )
    for fact in (receipt, acceptance):
        assert rig.target(fact, "shipment") == refs.shipment.payload.shipment_id
        assert any(k.object_type == "delivery_context" for k in fact.caused_by)
    returned = rig.result_fact(
        rig.execute("crm", claim_payload(refs, "crm.open_return"))
    )
    rid = rig.target(returned, "rma")
    rig.drain()
    with rig.workflow.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT count(*) FROM shipment_items WHERE project_id=?",
                (str(rig.project_id),),
            ).fetchone()[0]
            == 1
        )
        rma = tx.execute("SELECT * FROM rmas WHERE id=?", (str(rid),)).fetchone()
        from manufacturing_platform.workflow.feedback import admitted_source

        assert (
            admitted_source(tx, rig.project_id, rma).external_id
            == returned.source.external_id
        )
        assert rma["source_system"] == "platform-derived"
    holds = (
        rig.registry.adapter("mes").facts(rig.project_id, "containment", 0, 200).records
    )
    assert any(
        h.payload.cause == returned.source_key
        and set(map(str, h.payload.unit_ids)) == {u["unit_id"] for u in refs.units}
        for h in holds
    )


def test_bi_refresh_derives_immutable_cohort_and_replay_does_not_inflate(rig):
    refs = measured(rig)
    rig.drain()
    before = len(rig.rows("wms", "facts"))
    snapshot = rig.result_fact(rig.execute("bi", dict(operation="bi.refresh")))
    metrics = {m.metric: m for m in snapshot.payload.metrics}
    assert (
        metrics["first_pass_yield"].numerator,
        metrics["first_pass_yield"].denominator,
    ) == (1, 1)
    original = snapshot.model_dump_json()
    rig.replay_delivery(refs.test.source_key, "bi")
    fresh = rig.result_fact(rig.execute("bi", dict(operation="bi.refresh")))
    assert fresh.payload.snapshot_version == snapshot.payload.snapshot_version + 1
    assert fresh.payload.metrics == snapshot.payload.metrics
    assert (
        rig.registry.observe_fact(rig.project_id, snapshot.source_key).model_dump_json()
        == original
    )
    assert len(rig.rows("wms", "facts")) == before
    detail = rig.workflow.integration_fact(
        rig.actor, rig.project_id, snapshot.source_key
    )
    assert detail.auxiliary_records[0].kind == "snapshot"
    assert detail.auxiliary_records[0].snapshot.source_vector


def test_customer_design_approval_and_serial_mapping_keep_external_identity(rig):
    refs = shipped(rig)
    revision = (
        rig.registry.adapter("pdm").facts(rig.project_id, "revision", 0, 200).records[0]
    )
    approved = rig.result_fact(
        rig.execute(
            "customer",
            dict(
                operation="customer.approve_revision",
                revision_id=str(refs.revision),
                revision=revision.source_key.model_dump(),
                customer_id="C",
                decision="approved",
                external_signer="Customer engineering",
                signed_at=NOW.isoformat(),
                evidence="Signed design approval",
            ),
        )
    )
    assert rig.target(approved, "revision") == refs.revision
    mapped = rig.result_fact(
        rig.execute(
            "customer",
            dict(
                operation="customer.map_serial",
                unit_id=refs.units[0]["unit_id"],
                shipment=refs.shipment.source_key.model_dump(),
                customer_id="C",
                customer_serial="CUSTOMER-SN1",
                external_signer="Customer receiving",
                evidence="Scanned external serial",
            ),
        )
    )
    assert str(rig.target(mapped, "unit")) == refs.units[0]["unit_id"]
    with rig.workflow.store.transaction() as tx:
        from manufacturing_platform.workflow.engineering import fixed_revision

        approval = fixed_revision(tx, rig.project_id, refs.revision).customer_approvals[
            -1
        ]
        assert approval.method == "mock"
        assert approval.recorded_by == rig.actor.user_id
        assert approval.external_signatory == "Customer engineering"


@pytest.mark.parametrize(
    "system,operation",
    [("crm", "crm.open_return"), ("overseas", "overseas.report_return")],
)
def test_multi_work_order_claim_has_two_honest_derived_rmas_and_full_context(
    rig, system, operation
):
    from .network_scenarios import multi_work_order_shipment, synchronize

    refs = multi_work_order_shipment(rig)
    claim = rig.result_fact(rig.execute(system, claim_payload(refs, operation)))
    assert len([k for k in claim.caused_by if k.object_type == "delivery_context"]) == 2
    detail = rig.workflow.integration_fact(rig.actor, rig.project_id, claim.source_key)
    rmas = [t for t in detail.projection.targets if t.kind == "rma"]
    assert len(rmas) == 2 and len({t.id for t in rmas}) == 2
    with rig.workflow.store.transaction() as tx:
        from manufacturing_platform.workflow.feedback import admitted_source

        rows = tx.execute(
            "SELECT * FROM rmas WHERE project_id=?", (str(rig.project_id),)
        ).fetchall()
        assert {r["unit_id"] for r in rows} == {u["unit_id"] for u in refs.units}
        assert all(
            admitted_source(tx, rig.project_id, r).model_dump()
            == claim.source.model_dump()
            for r in rows
        )
        for row, other in ((rows[0], rows[1]), (rows[1], rows[0])):
            swapped = dict(row, unit_id=other["unit_id"])
            assert admitted_source(tx, rig.project_id, swapped) is None
    synchronize(rig)
    holds = (
        rig.registry.adapter("mes").facts(rig.project_id, "containment", 0, 200).records
    )
    assert len(holds) == 1 and set(map(str, holds[0].payload.unit_ids)) == {
        u["unit_id"] for u in refs.units
    }
    rig.replay_delivery(claim.source_key, "mes")
    assert (
        len(
            rig.registry.adapter("mes")
            .facts(rig.project_id, "containment", 0, 200)
            .records
        )
        == 1
    )


def test_partial_and_rejected_external_claims_never_count_all_units(rig):
    from .network_scenarios import multi_work_order_shipment

    refs = multi_work_order_shipment(rig)
    rig.execute(
        "overseas",
        claim_payload(refs, "overseas.receive_shipment", decision="accepted"),
    )
    partial = rig.result_fact(
        rig.execute(
            "customer",
            claim_payload(
                refs,
                "customer.confirm_delivery",
                decision="partial",
                accepted_unit_ids=[refs.units[0]["unit_id"]],
            ),
        )
    )
    assert partial.payload.accepted_unit_ids
    rejected = rig.result_fact(
        rig.execute(
            "customer",
            claim_payload(refs, "customer.confirm_delivery", decision="rejected"),
        )
    )
    with rig.workflow.store.transaction() as tx:
        from manufacturing_platform.workflow.delivery import remaining

        balance = remaining(tx, rig.project_id, refs.order_line)
        assert (balance.shipped, balance.signed, balance.accepted) == (2, 2, 1)
    detail = rig.workflow.integration_fact(
        rig.actor, rig.project_id, rejected.source_key
    )
    assert len(detail.auxiliary_records[0].issue_unit_ids) == 2
    with pytest.raises(DomainError, match="already confirmed"):
        rig.execute(
            "customer",
            claim_payload(refs, "customer.confirm_delivery", decision="accepted"),
        )


def test_original_artifact_replacement_is_forbidden_and_manual_finish_rejects_mock(rig):
    import sqlite3
    from pydantic import ValidationError
    from manufacturing_platform.workflow.laboratory_models import FinishTestRun

    refs = prepare_run(rig)
    prepared = rig.result_fact(
        rig.execute(
            "product_test",
            dict(
                operation="product_test.prepare_artifact",
                run_id=str(refs.run),
                template="pass-v1",
            ),
        )
    )
    p = prepared.payload.prepared
    store = rig.registry.adapter("product_test").store
    with store.transaction() as tx:
        row = tuple(tx.execute("SELECT * FROM original_artifacts").fetchone())
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with store.transaction(write=True) as tx:
            tx.execute(
                "INSERT OR REPLACE INTO original_artifacts VALUES (?,?,?,?,?,?)", row
            )
    value = p.model_dump(mode="json", exclude={"kind"})
    with pytest.raises(DomainError, match="original artifact"):
        changed = dict(
            value,
            measurements=[
                dict(name="voltage", unit="V", lower="4", upper="6", value="5.5")
            ],
        )
        rig.execute("product_test", dict(operation="product_test.run", **changed))
    fact = rig.result_fact(
        rig.execute("product_test", dict(operation="product_test.run", **value))
    )
    with pytest.raises(ValidationError):
        FinishTestRun(
            operation_id=uuid4(),
            expected_version=rig.version(),
            action="test_run.finish",
            run_id=refs.run,
            state="completed",
            source=fact.source,
            measurements=[m.model_dump(mode="json") for m in p.measurements],
            raw=p.raw.model_dump(mode="json"),
        )


def test_bi_first_attempt_cohort_does_not_turn_successful_retest_into_first_pass(rig):
    refs = prepare_run(rig)
    prepared = rig.result_fact(
        rig.execute(
            "product_test",
            dict(
                operation="product_test.prepare_artifact",
                run_id=str(refs.run),
                template="fail-v1",
            ),
        )
    )
    failed = rig.result_fact(
        rig.execute(
            "product_test",
            dict(
                operation="product_test.run",
                **prepared.payload.prepared.model_dump(mode="json", exclude={"kind"}),
            ),
        )
    )
    failed_detail = rig.workflow.integration_fact(
        rig.actor, rig.project_id, failed.source_key
    )
    assert (
        failed_detail.source_accepted
        and failed_detail.workflow_projected
        and failed.payload.result == "fail"
    )
    before = rig.result_fact(rig.execute("bi", dict(operation="bi.refresh")))
    nc = rig.command(
        "nonconformance.open",
        test_id=str(rig.target(failed, "test")),
        defect="Voltage high",
        evidence="Measured failure",
    ).object_id
    target = dict(
        target_type="quality",
        source_key=failed.source_key.model_dump(),
        nonconformance_id=str(nc),
        work_order_id=str(refs.work_order),
        disposition="rework",
        route_id="R2",
        route_steps=[dict(station="assembly", instruction_version="S2")],
    )
    request = rig.result_fact(
        rig.execute(
            "oa",
            dict(
                operation="oa.request_approval",
                target=target,
                requested_by="Quality engineer",
                evidence="Independent rework requested",
            ),
        )
    )
    decision = rig.result_fact(
        rig.execute(
            "oa",
            dict(
                operation="oa.decide_approval",
                target=target,
                request=request.source_key.model_dump(),
                decision="approved",
                external_signer="Quality approver",
                signed_at=NOW.isoformat(),
                evidence="Approved independent route",
            ),
        )
    )
    assert decision.payload.target.target_type == "quality"
    with rig.workflow.store.transaction() as tx:
        rw = tx.execute(
            "SELECT id FROM rework_orders WHERE nonconformance_id=?", (str(nc),)
        ).fetchone()[0]
    execution = refs.execution.payload.model_dump(mode="json", exclude={"fact_type"})
    execution.update(operation="mes.pass", route_version="S2", rework_order_id=rw)
    rework_event = rig.result_fact(rig.execute("mes", execution))
    run = rig.command(
        "test_run.start",
        plan_id=str(refs.test_plan),
        unit_id=refs.units[0]["unit_id"],
        rework_order_id=rw,
    ).object_id
    prepared = rig.result_fact(
        rig.execute(
            "product_test",
            dict(
                operation="product_test.prepare_artifact",
                run_id=str(run),
                template="pass-v1",
            ),
        )
    )
    passed = rig.result_fact(
        rig.execute(
            "product_test",
            dict(
                operation="product_test.run",
                **prepared.payload.prepared.model_dump(mode="json", exclude={"kind"}),
            ),
        )
    )
    with rig.workflow.store.transaction() as tx:
        event_id = tx.execute(
            "SELECT id FROM execution_events WHERE source_system=? AND source_external_id=?",
            ("mes", rework_event.source.external_id),
        ).fetchone()[0]
    rig.command(
        "rework.complete",
        rework_order_id=rw,
        test_ids=[str(rig.target(passed, "test"))],
        execution_event_ids=[event_id],
    )
    after = rig.result_fact(rig.execute("bi", dict(operation="bi.refresh")))
    metrics = {m.metric: m for m in after.payload.metrics}
    assert (
        metrics["first_pass_yield"].numerator,
        metrics["first_pass_yield"].denominator,
    ) == (0, 1)
    assert (metrics["final_yield"].numerator, metrics["final_yield"].denominator) == (
        1,
        1,
    )
    assert (
        rig.registry.observe_fact(rig.project_id, before.source_key).model_dump_json()
        == before.model_dump_json()
    )


def test_owned_artifact_download_is_authenticated_and_project_bound(rig, monkeypatch):
    from .test_operation_boundary import http_client

    refs = prepare_run(rig)
    prepared = rig.result_fact(
        rig.execute(
            "product_test",
            dict(
                operation="product_test.prepare_artifact",
                run_id=str(refs.run),
                template="pass-v1",
            ),
        )
    )
    p = prepared.payload.prepared
    with http_client(rig, monkeypatch) as client:
        path = f"/api/v1/manufacturing/workflow/projects/{rig.project_id}/systems/product_test/artifacts/{p.artifact_ref.artifact_id}"
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert hashlib.sha256(response.content).hexdigest() == p.artifact_checksum
        assert client.get(
            path.replace(str(rig.project_id), str(rig.other_project_id))
        ).status_code in (404, 409)


def test_delivery_read_provenance_requires_exact_persisted_source_columns(rig):
    from manufacturing_platform.workflow.delivery import admitted_source

    refs = shipped(rig)
    fact = rig.result_fact(
        rig.execute(
            "overseas",
            claim_payload(refs, "overseas.receive_shipment", decision="accepted"),
        )
    )
    with rig.workflow.store.transaction() as tx:
        row = dict(
            tx.execute(
                "SELECT * FROM delivery_facts WHERE source_external_id=?",
                (fact.source.external_id,),
            ).fetchone()
        )
        assert (
            admitted_source(tx, rig.project_id, row, "delivery_sign").model_dump()
            == fact.source.model_dump()
        )
        for column in ("source_system", "source_type", "source_external_id"):
            assert (
                admitted_source(
                    tx, rig.project_id, {**row, column: "forged"}, "delivery_sign"
                )
                is None
            )


@pytest.mark.parametrize("recursive_triggers", [0, 1])
def test_return_lineage_cannot_replace_same_claim_unit_with_another_rma(
    recursive_triggers,
):
    import sqlite3
    from manufacturing_platform.workflow.integrations.schema import initialize_claims

    tx = sqlite3.connect(":memory:")
    tx.execute("PRAGMA foreign_keys=ON")
    tx.execute(f"PRAGMA recursive_triggers={recursive_triggers}")
    tx.executescript("""
        CREATE TABLE projects(id TEXT PRIMARY KEY);
        CREATE TABLE units(id TEXT PRIMARY KEY);
        CREATE TABLE rmas(id TEXT PRIMARY KEY);
        CREATE TABLE integration_projections(
            project_id TEXT, system TEXT, object_type TEXT, external_id TEXT,
            version INTEGER,
            PRIMARY KEY(project_id,system,object_type,external_id,version)
        );
        INSERT INTO projects VALUES ('project');
        INSERT INTO units VALUES ('unit');
        INSERT INTO rmas VALUES ('original-rma'),('different-rma');
        INSERT INTO integration_projections VALUES ('project','crm','return_claim','claim',1),
            ('project','crm','return_claim','other-claim',1);
    """)
    initialize_claims(tx)
    original = (
        "project",
        "crm",
        "return_claim",
        "claim",
        1,
        "hash",
        "unit",
        "original-rma",
    )
    tx.execute(
        "INSERT INTO integration_return_units VALUES (?,?,?,?,?,?,?,?)", original
    )
    for replacement in (
        (*original[:-1], "different-rma"),
        (*original[:3], "other-claim", *original[4:]),
    ):
        with pytest.raises(
            sqlite3.IntegrityError, match="immutable return claim lineage"
        ):
            tx.execute(
                "INSERT OR REPLACE INTO integration_return_units VALUES (?,?,?,?,?,?,?,?)",
                replacement,
            )
        assert (
            tx.execute("SELECT * FROM integration_return_units").fetchone() == original
        )
    tx.close()


@pytest.mark.parametrize("boundary", ["service", "http"])
@pytest.mark.parametrize("revocation", ["roles", "active"])
def test_review_artifact_reauthorizes_after_source_read(
    rig, monkeypatch, boundary, revocation
):
    from contextlib import contextmanager
    from manufacturing_platform.workflow.contracts import GrantChange
    from manufacturing_platform.workflow.integrations import test_artifacts
    from .test_operation_boundary import http_client

    refs = prepare_run(rig)
    prepared = rig.result_fact(
        rig.execute(
            "product_test",
            dict(
                operation="product_test.prepare_artifact",
                run_id=str(refs.run),
                template="pass-v1",
            ),
        )
    )
    p = prepared.payload.prepared
    original_resolve = test_artifacts.resolve
    original_transaction = rig.workflow.store.transaction
    depth = 0
    resolved = []

    @contextmanager
    def tracked_transaction(*args, **kwargs):
        nonlocal depth
        with original_transaction(*args, **kwargs) as tx:
            depth += 1
            try:
                yield tx
            finally:
                depth -= 1

    def resolve_then_revoke(*args):
        assert depth == 0, "Source I/O must remain outside workflow transactions"
        content = original_resolve(*args)
        resolved.append(content)
        rig.workflow.change_grant(
            rig.admin,
            rig.project_id,
            rig.actor.user_id,
            GrantChange(
                operation_id=uuid4(),
                expected_version=rig.version(),
                scope=dict(kind="project", project_id=rig.project_id),
                roles=[] if revocation == "roles" else ["project_owner"],
                qualifications=[],
                active=revocation != "active",
                evidence="Revoke current app grant during original artifact read",
            ),
        )
        return content

    monkeypatch.setattr(rig.workflow.store, "transaction", tracked_transaction)
    monkeypatch.setattr(test_artifacts, "resolve", resolve_then_revoke)
    if boundary == "service":
        with pytest.raises(DomainError) as exc:
            rig.workflow.integration_artifact(
                rig.actor, rig.project_id, p.artifact_ref, p.artifact_checksum
            )
        assert (exc.value.code, exc.value.status) == ("NOT_FOUND", 404)
    else:
        with http_client(rig, monkeypatch) as client:
            response = client.get(
                f"/api/v1/manufacturing/workflow/projects/{rig.project_id}/systems/product_test/artifacts/{p.artifact_ref.artifact_id}"
            )
        assert response.status_code == 404, response.text
        assert response.content != resolved[0]
        assert "ETag" not in response.headers
        assert p.artifact_checksum not in response.text
    assert (
        len(resolved) == 1
        and hashlib.sha256(resolved[0]).hexdigest() == p.artifact_checksum
    )
    with pytest.raises(DomainError) as exc:
        rig.workflow.integration_fact(rig.actor, rig.project_id, prepared.source_key)
    assert exc.value.status == 404


@pytest.mark.parametrize("scope", ["disjoint", "overlap", "aggregate_only"])
def test_review_customer_acceptance_requires_exact_signed_serial_subset(rig, scope):
    from .network_scenarios import multi_work_order_shipment

    refs = multi_work_order_shipment(rig)
    first, second = [u["unit_id"] for u in refs.units]
    signature = None
    if scope != "aggregate_only":
        signature = rig.result_fact(
            rig.execute(
                "overseas",
                claim_payload(
                    refs,
                    "overseas.receive_shipment",
                    decision="partial",
                    accepted_unit_ids=[first],
                ),
            )
        )
    if scope in {"overlap", "aggregate_only"}:
        rig.command(
            "delivery.sign",
            shipment_id=str(refs.shipment.payload.shipment_id),
            quantity="1" if scope == "overlap" else "2",
            source=rig.manual_source("delivery_sign"),
            external_signatory="Manual aggregate receipt",
        )
    invalid = claim_payload(
        refs,
        "customer.confirm_delivery",
        decision="accepted" if scope == "overlap" else "partial",
        **(
            {}
            if scope == "overlap"
            else {"accepted_unit_ids": [second if scope == "disjoint" else first]}
        ),
    )
    before = len(rig.rows("customer", "facts"))
    operation_id = uuid4()
    with pytest.raises(DomainError, match="signed serial"):
        rig.execute("customer", invalid, operation_id=operation_id)
    assert len(rig.rows("customer", "facts")) == before
    assert (
        rig.registry.adapter("customer").query(rig.project_id, operation_id).phase
        == "rejected"
    )
    if signature:
        accepted = rig.result_fact(
            rig.execute(
                "customer",
                claim_payload(
                    refs,
                    "customer.confirm_delivery",
                    decision="partial",
                    accepted_unit_ids=[first],
                ),
            )
        )
        assert signature.source_key in accepted.caused_by
        with pytest.raises(DomainError):
            rig.execute(
                "customer",
                claim_payload(
                    refs,
                    "customer.confirm_delivery",
                    decision="partial",
                    accepted_unit_ids=[first],
                ),
            )
    with rig.workflow.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT count(*) FROM shipment_items WHERE shipment_id=?",
                (str(refs.shipment.payload.shipment_id),),
            ).fetchone()[0]
            == 2
        )
        sums = dict(
            tx.execute(
                "SELECT action, sum(q_atoms) FROM delivery_facts WHERE shipment_id=? GROUP BY action",
                (str(refs.shipment.payload.shipment_id),),
            ).fetchall()
        )
        assert sums.get("accept", 0) == (1 if signature else 0)
        assert sums["sign"] == (1 if scope == "disjoint" else 2)
    if scope == "disjoint":
        second_signature = rig.result_fact(
            rig.execute(
                "overseas",
                claim_payload(
                    refs,
                    "overseas.receive_shipment",
                    decision="partial",
                    accepted_unit_ids=[second],
                ),
            )
        )
        final = rig.result_fact(
            rig.execute(
                "customer",
                claim_payload(
                    refs,
                    "customer.confirm_delivery",
                    decision="partial",
                    accepted_unit_ids=[second],
                ),
            )
        )
        assert second_signature.source_key in final.caused_by
        with rig.workflow.store.transaction() as tx:
            assert dict(
                tx.execute(
                    "SELECT action,sum(q_atoms) FROM delivery_facts WHERE shipment_id=? GROUP BY action",
                    (str(refs.shipment.payload.shipment_id),),
                ).fetchall()
            ) == {"sign": 2, "accept": 2}
            assert (
                tx.execute(
                    "SELECT count(*) FROM shipment_items WHERE shipment_id=?",
                    (str(refs.shipment.payload.shipment_id),),
                ).fetchone()[0]
                == 2
            )


def test_review_pending_signature_cannot_supply_serial_coverage(rig):
    from .network_scenarios import multi_work_order_shipment

    refs = multi_work_order_shipment(rig)
    first = refs.units[0]["unit_id"]
    rig.command(
        "delivery.sign",
        shipment_id=str(refs.shipment.payload.shipment_id),
        quantity="1",
        source=rig.manual_source("delivery_sign"),
        external_signatory="Aggregate receipt without serial membership",
    )
    signature_id = uuid4()
    rig.fault("overseas", signature_id, "timeout_after_commit")
    pending = rig.execute(
        "overseas",
        claim_payload(
            refs,
            "overseas.receive_shipment",
            decision="partial",
            accepted_unit_ids=[first],
        ),
        operation_id=signature_id,
    )
    assert pending.integration.phase == "unknown"
    receipt = rig.registry.adapter("overseas").query(rig.project_id, signature_id)
    assert receipt.phase == "accepted"
    assert rig.projection_count(receipt.source_keys[0]) == 0
    accept = claim_payload(
        refs, "customer.confirm_delivery", decision="partial", accepted_unit_ids=[first]
    )
    before = len(rig.rows("customer", "facts"))
    with pytest.raises(DomainError, match="signed serial"):
        rig.execute("customer", accept)
    assert len(rig.rows("customer", "facts")) == before
    rig.retry(signature_id)
    assert rig.projection_count(receipt.source_keys[0]) == 1
    accepted = rig.result_fact(rig.execute("customer", accept))
    assert receipt.source_keys[0] in accepted.caused_by
    assert (
        rig.registry.adapter("overseas").query(rig.project_id, signature_id) == receipt
    )
    with rig.workflow.store.transaction() as tx:
        assert dict(
            tx.execute(
                "SELECT action,sum(q_atoms) FROM delivery_facts WHERE shipment_id=? GROUP BY action",
                (str(refs.shipment.payload.shipment_id),),
            ).fetchall()
        ) == {"sign": 2, "accept": 1}
        assert (
            tx.execute(
                "SELECT count(*) FROM shipment_items WHERE shipment_id=?",
                (str(refs.shipment.payload.shipment_id),),
            ).fetchone()[0]
            == 2
        )


def test_review_domestic_customer_sign_then_accept_needs_no_overseas_receipt(rig):
    refs = shipped(rig)
    signed = rig.result_fact(
        rig.execute(
            "customer",
            claim_payload(refs, "customer.receive_shipment", decision="accepted"),
        )
    )
    accepted = rig.result_fact(
        rig.execute(
            "customer",
            claim_payload(refs, "customer.confirm_delivery", decision="accepted"),
        )
    )
    assert signed.payload.fact_type == "customer.delivery_receipt"
    assert signed.source_key in accepted.caused_by
    assert (
        not rig.registry.adapter("overseas")
        .facts(rig.project_id, "delivery_receipt", 0, 200)
        .records
    )
    rig.drain()
    detail = rig.workflow.integration_fact(rig.actor, rig.project_id, signed.source_key)
    assert detail.workflow_projected and detail.auxiliary_records[0].accepted_unit_ids
    assert any(
        d.consumer == "mes" and d.receipt and d.receipt.phase == "accepted"
        for d in detail.delivery_states
    )
    with rig.workflow.store.transaction() as tx:
        assert dict(
            tx.execute(
                "SELECT action,sum(q_atoms) FROM delivery_facts WHERE shipment_id=? GROUP BY action",
                (str(refs.shipment.payload.shipment_id),),
            ).fetchall()
        ) == {"sign": 1, "accept": 1}
        assert (
            tx.execute(
                "SELECT count(*) FROM shipment_items WHERE shipment_id=?",
                (str(refs.shipment.payload.shipment_id),),
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize("first_system", ["customer", "overseas"])
def test_review_mixed_signers_deduplicate_serials_and_cover_both_work_orders(
    rig, first_system
):
    from .network_scenarios import multi_work_order_shipment

    refs = multi_work_order_shipment(rig)
    first, second = [u["unit_id"] for u in refs.units]
    second_system = "overseas" if first_system == "customer" else "customer"
    signed = rig.result_fact(
        rig.execute(
            first_system,
            claim_payload(
                refs,
                first_system + ".receive_shipment",
                decision="partial",
                accepted_unit_ids=[first],
            ),
        )
    )
    before = len(rig.rows(second_system, "facts"))
    with pytest.raises(DomainError, match="already confirmed"):
        rig.execute(
            second_system,
            claim_payload(
                refs,
                second_system + ".receive_shipment",
                decision="partial",
                accepted_unit_ids=[first],
            ),
        )
    assert len(rig.rows(second_system, "facts")) == before
    operation_id = uuid4()
    other = rig.result_fact(
        rig.execute(
            second_system,
            claim_payload(
                refs,
                second_system + ".receive_shipment",
                decision="partial",
                accepted_unit_ids=[second],
            ),
            operation_id=operation_id,
        )
    )
    rig.retry(operation_id)
    accepted = rig.result_fact(
        rig.execute(
            "customer",
            claim_payload(refs, "customer.confirm_delivery", decision="accepted"),
        )
    )
    assert (
        signed.source_key in accepted.caused_by
        and other.source_key in accepted.caused_by
    )
    with rig.workflow.store.transaction() as tx:
        assert dict(
            tx.execute(
                "SELECT action,sum(q_atoms) FROM delivery_facts WHERE shipment_id=? GROUP BY action",
                (str(refs.shipment.payload.shipment_id),),
            ).fetchall()
        ) == {"sign": 2, "accept": 2}
        assert (
            tx.execute(
                "SELECT count(*) FROM shipment_items WHERE shipment_id=?",
                (str(refs.shipment.payload.shipment_id),),
            ).fetchone()[0]
            == 2
        )
