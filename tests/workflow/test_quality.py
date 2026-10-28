"""C1 measured quality through public actions; no successful SQL fixtures."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from .conftest import BASE
from .test_execution import running_execution


def executed(workflow):
    p, wo, units, authority, event = running_execution(workflow)
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=workflow.source(str(uuid4()), object_type="execution"),
        **event,
    )
    workflow.grant(
        p["id"],
        "quality",
        ["quality"],
        ["inspection", "disposition", "quality_release"],
    )
    return p, wo, units[0], event


def measure(workflow, p, uid, *, value="5", **overrides):
    body = dict(
        unit_id=uid,
        attempt=1,
        program_version="P1",
        limit_version="T1",
        firmware_version="F1",
        measurements=[
            dict(name="voltage", value=value, unit="V", lower="4", upper="6")
        ],
        source=workflow.source(str(uuid4()), object_type="test"),
    )
    now = datetime.now(UTC).isoformat()
    body["source"].update(occurred_at=now, collected_at=now)
    body.update(overrides)
    return workflow.command(p["id"], "test.record", actor_name="quality", **body)


def test_real_measured_first_article_boundary(workflow):
    p, wo, uid, _ = executed(workflow)
    test = measure(workflow, p, uid)
    detail = workflow.object(p["id"], "test", test["object_id"])
    assert detail["outcome"] == "pass"
    assert detail["measurements"][0]["value"] == "5"
    workflow.command(
        p["id"],
        "first_article.record",
        actor_name="quality",
        work_order_id=wo["id"],
        unit_ids=[uid],
        test_ids=[test["object_id"]],
        inspection_id="real measured first article",
    )


@pytest.mark.parametrize(
    "changes",
    [
        dict(measurements=[]),
        dict(
            measurements=[
                dict(name="voltage", value="12", unit="V", lower="0", upper="20")
            ]
        ),
        dict(program_version="P2"),
        dict(
            measurements=[
                dict(name="voltage", value="NaN", unit="V", lower="4", upper="6")
            ]
        ),
        dict(outcome="pass"),
    ],
)
def test_no_client_pass_or_easier_incomplete_spec(workflow, changes):
    p, _, uid, _ = executed(workflow)
    measure(workflow, p, uid, expected_status=422, **changes)


def rework(workflow, p, test):
    nc = workflow.command(
        p["id"],
        "nonconformance.open",
        actor_name="quality",
        test_id=test["object_id"],
        defect="voltage out of bounds",
        evidence="measured defect",
    )
    rw = workflow.command(
        p["id"],
        "nonconformance.disposition",
        actor_name="quality",
        nonconformance_id=nc["object_id"],
        decision="rework",
        route_id="RW-1",
        route_steps=[dict(station="repair", instruction_version="RW-S1")],
        evidence="approved repair route",
    )
    return nc, rw


def test_retest_preserves_first_failure_and_requires_real_rework_execution(workflow):
    p, _, uid, event = executed(workflow)
    first = measure(workflow, p, uid, value="12")
    nc, rw = rework(workflow, p, first)
    measure(
        workflow,
        p,
        uid,
        attempt=2,
        rework_order_id=rw["object_id"],
        expected_status=409,
    )
    event.update(
        station="repair",
        route_version="RW-S1",
        rework_order_id=rw["object_id"],
        occurred_at=datetime.now(UTC).isoformat(),
    )
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=workflow.source(str(uuid4()), object_type="execution"),
        **event,
    )
    retest = measure(workflow, p, uid, attempt=2, rework_order_id=rw["object_id"])
    unit = workflow.object(p["id"], "unit", uid)
    assert [t["outcome"] for t in unit["tests"]] == ["fail", "pass"]
    assert unit["first_pass"] is False
    workflow.command(
        p["id"],
        "rework.complete",
        actor_name="quality",
        rework_order_id=rw["object_id"],
        execution_event_ids=[unit["execution_events"][-1]["id"]],
        test_ids=[retest["object_id"]],
    )
    assert (
        workflow.object(p["id"], "nonconformance", nc["object_id"])["state"]
        == "resolved"
    )


def test_release_variants_use_live_qualification_and_customer_scope(workflow):
    p, _, uid, _ = executed(workflow)
    measure(workflow, p, uid)
    fields = dict(
        kind="quality", unit_ids=[uid], decision="approved", evidence="QA signed"
    )
    workflow.command(
        p["id"],
        "release.decide",
        actor_name="production",
        expected_status=403,
        **fields,
    )
    workflow.command(p["id"], "release.decide", expected_status=403, **fields)
    workflow.command(p["id"], "release.decide", actor_name="quality", **fields)
    project = workflow.client("production").get(f"{BASE}/projects/{p['id']}").json()
    assert project["release_kinds"] == ["manufacturing"]
    assert workflow.client("quality").get(f"{BASE}/projects/{p['id']}").json()[
        "release_kinds"
    ] == ["quality"]


def test_100_units_first96_final99_scrap1_preserve_four_failures(workflow):
    from .test_execution import ready_for_trial

    p, wo, units, _ = ready_for_trial(workflow, quantity="100", trial_quantity="100")
    units += [
        u["id"]
        for u in workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/unit?limit=50&offset=50")
        .json()["items"]
    ]
    workflow.grant(
        p["id"],
        "quality",
        ["quality"],
        ["inspection", "disposition", "quality_release"],
    )
    start = workflow.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=units,
        quantity="100",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=start["exchange_id"],
    )
    with workflow.db() as tx:
        lot = tx.execute(
            "SELECT id FROM material_lots WHERE project_id=?", (p["id"],)
        ).fetchone()[0]
    failed = []
    for i, uid in enumerate(units):
        event = dict(
            work_order_id=wo["id"],
            sn=workflow.object(p["id"], "unit", uid)["sn"],
            station="assembly",
            route_version="S1",
            program_version="P1",
            firmware_version="F1",
            material_uses=[dict(lot_id=lot, quantity="0.001", unit="kg")],
            result="pass",
            occurred_at=datetime.now(UTC).isoformat(),
        )
        workflow.command(
            p["id"],
            "execution.record",
            actor_name="production",
            source=workflow.source(str(uuid4()), object_type="execution"),
            **event,
        )
        first = measure(workflow, p, uid, value="12" if i >= 96 else "5")
        if i >= 96:
            failed.append((uid, first, event))
    summary = (
        workflow.client().get(f"{BASE}/projects/{p['id']}").json()["quality_summary"]
    )
    assert (
        summary["first_tested"],
        summary["first_passed"],
        summary["final_good"],
    ) == (100, 96, 96)
    for i, (uid, first, event) in enumerate(failed):
        nc, rw = rework(workflow, p, first)
        event.update(
            station="repair",
            route_version="RW-S1",
            rework_order_id=rw["object_id"],
            occurred_at=datetime.now(UTC).isoformat(),
        )
        workflow.command(
            p["id"],
            "execution.record",
            actor_name="production",
            source=workflow.source(str(uuid4()), object_type="execution"),
            **event,
        )
        retest = measure(
            workflow,
            p,
            uid,
            value="12" if i == 3 else "5",
            attempt=2,
            rework_order_id=rw["object_id"],
        )
        if i == 3:
            workflow.command(
                p["id"],
                "nonconformance.disposition",
                actor_name="quality",
                nonconformance_id=nc["object_id"],
                decision="scrap",
                evidence="repair retest failed; irreversible scrap",
            )
            measure(
                workflow,
                p,
                uid,
                attempt=3,
                rework_order_id=rw["object_id"],
                expected_status=409,
            )
        else:
            detail = workflow.object(p["id"], "unit", uid)
            workflow.command(
                p["id"],
                "rework.complete",
                actor_name="quality",
                rework_order_id=rw["object_id"],
                execution_event_ids=[detail["execution_events"][-1]["id"]],
                test_ids=[retest["object_id"]],
            )
    summary = (
        workflow.client().get(f"{BASE}/projects/{p['id']}").json()["quality_summary"]
    )
    assert summary == dict(
        first_tested=100,
        first_passed=96,
        final_good=99,
        scrapped=1,
        open_nonconformances=0,
    )
    assert (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}")
        .json()["summary"]["produced_good"]
        == "99"
    )
    with workflow.db() as tx:
        assert (
            tx.execute(
                "SELECT COUNT(*) FROM quality_tests WHERE attempt=1 AND outcome='fail'"
            ).fetchone()[0]
            == 4
        )


def test_historical_calibration_remains_good_but_not_fresh_first_article(workflow):
    from datetime import timedelta
    from manufacturing_platform.workflow.quality import final_good

    p, wo, uid, _ = executed(workflow)
    test = measure(workflow, p, uid)
    workflow.command(
        p["id"],
        "readiness.record",
        actor_name="engineering",
        work_order_id=wo["id"],
        kind="equipment",
        reference="routine renewal",
        evidence="new calibration",
        decision="verified",
        valid_until=(datetime.now(UTC) + timedelta(days=90)).isoformat(),
    )
    with workflow.db() as tx:
        assert final_good(tx, p["id"], uid)
    workflow.command(
        p["id"],
        "first_article.record",
        actor_name="quality",
        work_order_id=wo["id"],
        unit_ids=[uid],
        test_ids=[test["object_id"]],
        inspection_id="old measurement cannot borrow new check",
        expected_status=409,
    )


def test_customer_release_required_independent_and_exact_manual_scope(workflow):
    from manufacturing_platform.workflow.quality import shipment_eligibility

    p, _, uid, _ = executed(workflow)
    test = measure(workflow, p, uid)
    for actor, kind in [("production", "manufacturing"), ("quality", "quality")]:
        workflow.command(
            p["id"],
            "release.decide",
            actor_name=actor,
            kind=kind,
            unit_ids=[uid],
            decision="approved",
            evidence=kind + " independent signoff",
        )
    with workflow.db() as tx:
        assert not shipment_eligibility(
            tx, p["id"], [uid]
        ).allowed  # unknown contract fail-closed
    revision = workflow.object(p["id"], "test", test["object_id"])["revision_id"]
    fields = dict(
        kind="customer",
        unit_ids=[uid],
        decision="approved",
        evidence="signed receipt",
        customer_id="Customer 1",
        revision_id=revision,
        customer_revision="C1",
        external_signatory="Customer QE Alice",
        method="manual",
        source=workflow.source("customer-release-1", object_type="customer_release"),
    )
    workflow.command(p["id"], "release.decide", **fields)
    fields["customer_id"] = "Other customer"
    workflow.command(p["id"], "release.decide", expected_status=409, **fields)
    workflow.command(
        p["id"],
        "release.decide",
        actor_name="quality",
        kind="quality",
        unit_ids=[uid],
        decision="conditional",
        evidence="not an unrestricted approval",
        expected_status=409,
    )


def test_source_scope_and_live_release_revocation_before_replay(workflow):
    p, _, uid, _ = executed(workflow)
    measure(workflow, p, uid)
    project = workflow.client("quality").get(f"{BASE}/projects/{p['id']}").json()
    body = dict(
        operation_id=str(uuid4()),
        expected_version=project["version"],
        action="release.decide",
        kind="quality",
        unit_ids=[uid],
        decision="approved",
        evidence="QA",
    )
    url = f"{BASE}/projects/{p['id']}/commands"
    assert workflow.client("quality").post(url, json=body).status_code == 200
    workflow.reopen()
    assert workflow.client("quality").post(url, json=body).json()["replayed"] is True
    assert (
        workflow.client("quality")
        .post(url, json={**body, "evidence": "changed"})
        .status_code
        == 409
    )
    workflow.grant(p["id"], "quality", ["quality"], ["inspection"])
    assert workflow.client("quality").post(url, json=body).status_code == 403
    p2, _, uid2, _ = executed(workflow)
    measure(workflow, p2, uid, expected_status=404)
    measure(
        workflow,
        p2,
        uid2,
        source=workflow.source("wrong-type", object_type="execution"),
        expected_status=409,
    )


def test_old_first_article_cannot_support_bulk_after_later_failure(workflow):
    p, wo, uid, _ = executed(workflow)
    first = measure(workflow, p, uid)
    workflow.command(
        p["id"],
        "first_article.record",
        actor_name="quality",
        work_order_id=wo["id"],
        unit_ids=[uid],
        test_ids=[first["object_id"]],
        inspection_id="measured first article",
    )
    assert workflow.object(p["id"], "work_order", wo["id"])["bulk_readiness"]["ready"]
    failed = measure(workflow, p, uid, attempt=2, value="12")
    assert not workflow.object(p["id"], "work_order", wo["id"])["bulk_readiness"][
        "ready"
    ]
    nc = workflow.command(
        p["id"],
        "nonconformance.open",
        actor_name="quality",
        test_id=failed["object_id"],
        defect="late measured failure",
        evidence="new measurements",
    )
    workflow.command(
        p["id"],
        "nonconformance.disposition",
        actor_name="quality",
        nonconformance_id=nc["object_id"],
        decision="scrap",
        evidence="irreversible exclusion",
    )
    # Replay an accepted start can reproject physical state; exclusion remains quality truth.
    with workflow.db() as tx:
        exchange = tx.execute(
            "SELECT id FROM exchanges WHERE project_id=? AND action='production.start'",
            (p["id"],),
        ).fetchone()[0]
    workflow.command(
        p["id"], "exchange.query", actor_name="production", exchange_id=exchange
    )
    unit = workflow.object(p["id"], "unit", uid)
    assert unit["state"] == "running"
    assert unit["scrapped"] is True and unit["final_good"] is False
    assert not workflow.object(p["id"], "work_order", wo["id"])["bulk_readiness"][
        "ready"
    ]


def test_negative_finite_decimal_matches_frozen_limits(workflow, monkeypatch):
    original = workflow.command

    def command(pid, action, **fields):
        if action == "engineering.revision":
            fields["test_spec"] = {
                **fields["test_spec"],
                "measurements": [
                    dict(
                        name="voltage", unit="V", lower="-6.0000000", upper="-4.0000000"
                    )
                ],
            }
        return original(pid, action, **fields)

    monkeypatch.setattr(workflow, "command", command)
    p, _, uid, _ = executed(workflow)
    result = measure(
        workflow,
        p,
        uid,
        measurements=[
            dict(
                name="voltage",
                value="-5.0000000",
                unit="V",
                lower="-6.0000000",
                upper="-4.0000000",
            )
        ],
    )
    assert (
        workflow.object(p["id"], "test", result["object_id"])["measurements"][0][
            "value"
        ]
        == "-5.0000000"
    )


def test_customer_required_eligibility_needs_all_three_independent_rows(
    workflow, monkeypatch
):
    from manufacturing_platform.workflow.quality import shipment_eligibility

    create = workflow.create_project

    def create_required(**fields):
        fields["contract"] = {**fields["contract"], "customer_release_required": True}
        return create(**fields)

    monkeypatch.setattr(workflow, "create_project", create_required)
    p, _, uid, _ = executed(workflow)
    measured = measure(workflow, p, uid)
    for actor, kind in [("production", "manufacturing"), ("quality", "quality")]:
        workflow.command(
            p["id"],
            "release.decide",
            actor_name=actor,
            kind=kind,
            unit_ids=[uid],
            decision="approved",
            evidence=kind,
        )
    with workflow.db() as tx:
        assert shipment_eligibility(tx, p["id"], [uid]).qualified_quantity == 0
    revision = workflow.object(p["id"], "test", measured["object_id"])["revision_id"]
    source = workflow.source(
        "customer-required-1", system="Customer Portal", object_type="customer_release"
    )
    fields = dict(
        kind="customer",
        unit_ids=[uid],
        decision="approved",
        evidence="Customer QE signed approval",
        customer_id="Customer 1",
        revision_id=revision,
        customer_revision="C1",
        external_signatory="Named Customer QE",
        method="manual",
        source=source,
    )
    receipt = workflow.command(p["id"], "release.decide", **fields)
    with workflow.db() as tx:
        eligible = shipment_eligibility(tx, p["id"], [uid])
        assert (
            eligible.allowed
            and eligible.qualified_quantity == 1
            and len(eligible.release_ids) == 3
        )
    view = workflow.object(p["id"], "release", receipt["object_id"])
    assert (
        view["external_signatory"] == "Named Customer QE" and view["method"] == "manual"
    )
    # A second operation cannot reinterpret the same external customer decision.
    fields["source"] = {
        **source,
        "system": " customer portal ",
        "external_id": "customer-required-1 ",
    }
    workflow.command(p["id"], "release.decide", expected_status=409, **fields)


def test_trusted_reader_is_connection_scoped_nested_and_exception_safe(tmp_path):
    from manufacturing_platform.workflow import quality
    from manufacturing_platform.workflow.execution import test_reader
    from manufacturing_platform.workflow.service import WorkflowService
    from manufacturing_platform.workflow.store import WorkflowStore

    custom = object()
    dataset = dict(id="reader-test", mode="test", label="Reader isolation")
    a = WorkflowStore(str(tmp_path / "a.db"), str(tmp_path / "aa.db"), dataset)
    b = WorkflowStore(str(tmp_path / "b.db"), str(tmp_path / "ba.db"), dataset)
    WorkflowService(a, lambda uid: True, test_evidence_reader=custom)
    WorkflowService(b, lambda uid: True)
    with a.transaction() as atx:
        assert test_reader(atx) is custom
        try:
            with b.transaction() as btx:
                assert test_reader(btx) is quality
                assert (
                    test_reader(atx) is quality
                )  # another tx cannot borrow ambient fixture
                raise RuntimeError("reset on error")
        except RuntimeError:
            pass
        assert test_reader(atx) is custom
    assert test_reader(atx) is quality
    with pytest.raises(ValueError, match="already bound"):
        WorkflowService(a, lambda uid: True)


def test_production_reopen_never_trusts_provisional_first_article(workflow):
    from .test_execution import ProvisionalCompleteTest

    p, wo, uid, _ = executed(workflow)
    with workflow.db() as tx:
        revision = tx.execute(
            "SELECT revision_id FROM units WHERE id=?", (uid,)
        ).fetchone()[0]
    tid = str(uuid4())
    workflow.test_evidence_reader = ProvisionalCompleteTest(
        workflow, tid, uid, revision
    )
    workflow.reopen()
    workflow.command(
        p["id"],
        "first_article.record",
        actor_name="quality",
        work_order_id=wo["id"],
        unit_ids=[uid],
        test_ids=[tid],
        inspection_id="explicit B3 protocol fixture",
    )
    assert workflow.object(p["id"], "work_order", wo["id"])["bulk_readiness"]["ready"]
    del workflow.test_evidence_reader
    workflow.reopen()
    assert not workflow.object(p["id"], "work_order", wo["id"])["bulk_readiness"][
        "ready"
    ]


def test_new_matching_repaired_article_restores_bulk_without_erasing_first(workflow):
    p, wo, uid, event = executed(workflow)
    first = measure(workflow, p, uid)
    workflow.command(
        p["id"],
        "first_article.record",
        actor_name="quality",
        work_order_id=wo["id"],
        unit_ids=[uid],
        test_ids=[first["object_id"]],
        inspection_id="initial article",
    )
    failed = measure(workflow, p, uid, attempt=2, value="12")
    nc, rw = rework(workflow, p, failed)
    event.update(
        station="repair",
        route_version="RW-S1",
        rework_order_id=rw["object_id"],
        occurred_at=datetime.now(UTC).isoformat(),
    )
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=workflow.source(str(uuid4()), object_type="execution"),
        **event,
    )
    tested = measure(workflow, p, uid, attempt=3, rework_order_id=rw["object_id"])
    unit = workflow.object(p["id"], "unit", uid)
    workflow.command(
        p["id"],
        "rework.complete",
        actor_name="quality",
        rework_order_id=rw["object_id"],
        execution_event_ids=[unit["execution_events"][-1]["id"]],
        test_ids=[tested["object_id"]],
    )
    assert not workflow.object(p["id"], "work_order", wo["id"])["bulk_readiness"][
        "ready"
    ]
    workflow.command(
        p["id"],
        "first_article.record",
        actor_name="quality",
        work_order_id=wo["id"],
        unit_ids=[uid],
        test_ids=[tested["object_id"]],
        inspection_id="new repaired article",
    )
    assert workflow.object(p["id"], "work_order", wo["id"])["bulk_readiness"]["ready"]
    with workflow.db() as tx:
        assert tx.execute("SELECT COUNT(*) FROM first_articles").fetchone()[0] == 2
        assert (
            tx.execute(
                "SELECT COUNT(*) FROM quality_tests WHERE outcome='fail'"
            ).fetchone()[0]
            == 1
        )


def test_failed_rework_retest_cannot_reuse_old_repair_events(workflow):
    p, _, uid, event = executed(workflow)
    first = measure(workflow, p, uid, value="12")
    _, rw = rework(workflow, p, first)
    event.update(
        station="repair",
        route_version="RW-S1",
        rework_order_id=rw["object_id"],
        occurred_at=datetime.now(UTC).isoformat(),
    )
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=workflow.source(str(uuid4()), object_type="execution"),
        **event,
    )
    measure(workflow, p, uid, value="12", attempt=2, rework_order_id=rw["object_id"])
    measure(
        workflow,
        p,
        uid,
        attempt=3,
        rework_order_id=rw["object_id"],
        expected_status=409,
    )


def test_latest_failed_route_event_cannot_borrow_earlier_pass(workflow):
    p, _, uid, event = executed(workflow)
    event.update(result="fail", occurred_at=datetime.now(UTC).isoformat())
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=workflow.source(str(uuid4()), object_type="execution"),
        **event,
    )
    measure(workflow, p, uid, expected_status=409)


def test_invalid_rework_claim_retains_rejection_without_a_genealogy_edge(workflow):
    p, _, uid, event = executed(workflow)
    event.update(
        rework_order_id=str(uuid4()), occurred_at=datetime.now(UTC).isoformat()
    )
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=workflow.source(str(uuid4()), object_type="execution"),
        **event,
    )
    with workflow.db() as tx:
        row = tx.execute(
            "SELECT * FROM execution_events WHERE unit_id=? ORDER BY accepted_seq DESC LIMIT 1",
            (uid,),
        ).fetchone()
        assert row["status"] == "rejected" and row["rework_order_id"] is None


def test_later_attempt_cannot_backdate_before_first_test(workflow):
    from datetime import timedelta

    p, _, uid, _ = executed(workflow)
    first = measure(workflow, p, uid)
    first_time = workflow.object(p["id"], "test", first["object_id"])["occurred_at"]
    source = workflow.source(str(uuid4()), object_type="test")
    source.update(
        occurred_at=(
            datetime.fromisoformat(first_time) - timedelta(microseconds=1)
        ).isoformat(),
        collected_at=datetime.now(UTC).isoformat(),
    )
    measure(workflow, p, uid, attempt=2, source=source, expected_status=409)


def test_public_quality_fixture_preserves_failed_attempt(workflow):
    p, unit = workflow.executed_unit()
    first = workflow.test(p["id"], unit["id"], measured="12")
    assert first["outcome"] == "fail"
    rw = workflow.rework(p["id"], first["id"])
    workflow.test(p["id"], unit["id"], measured="5", rework_order_id=rw["id"])
    detail = workflow.object(p["id"], "unit", unit["id"])
    assert [t["outcome"] for t in detail["tests"]] == ["fail", "pass"]
    assert detail["first_pass"] is False


def test_legacy_execution_replay_keeps_original_intent_across_schema10_upgrade(
    workflow,
):
    import json
    import sqlite3

    p, _, uid, _ = executed(workflow)
    with workflow.db() as tx:
        old = tx.execute(
            "SELECT typed_payload FROM audit_events WHERE project_id=? AND action='execution.record' ORDER BY id LIMIT 1",
            (p["id"],),
        ).fetchone()[0]
        body = json.loads(old)
        body.pop("project_id")
        before = dict(
            tx.execute(
                "SELECT * FROM operations WHERE operation_id=?", (body["operation_id"],)
            ).fetchone()
        )
    workflow._client.close()
    with sqlite3.connect(workflow.paths.domain) as tx:
        tx.execute("UPDATE schema_version SET version=10")
    workflow.reopen()
    url = f"{BASE}/projects/{p['id']}/commands"
    replay = workflow.client("production").post(url, json=body)
    assert replay.status_code == 200 and replay.json()["replayed"]
    assert replay.json()["object_id"] == uid
    assert (
        workflow.client("production")
        .post(url, json={**body, "result": "fail"})
        .status_code
        == 409
    )
    with workflow.db() as tx:
        assert (
            dict(
                tx.execute(
                    "SELECT * FROM operations WHERE operation_id=?",
                    (body["operation_id"],),
                ).fetchone()
            )
            == before
        )
    workflow.grant(p["id"], "production", ["production"], active=False)
    assert workflow.client("production").post(url, json=body).status_code == 404


def test_open_rework_exposes_named_latest_route_evidence(workflow):
    p, unit = workflow.executed_unit()
    first = workflow.test(p["id"], unit["id"], measured="12")
    rw = workflow.rework(p["id"], first["id"])
    assert rw["candidate_execution_events"][0]["station"] == "repair"
    assert rw["candidate_execution_events"][0]["rework_order_id"] == rw["id"]
    assert rw["candidate_execution_events"][0]["source"]["object_type"] == "execution"


def test_rework_over_100_steps_has_complete_bounded_named_evidence(workflow):
    p, _, uid, event = executed(workflow)
    failed = measure(workflow, p, uid, value="12")
    nc = workflow.command(
        p["id"],
        "nonconformance.open",
        actor_name="quality",
        test_id=failed["object_id"],
        defect="measured failure",
        evidence="route requires 101 repair checks",
    )
    steps = [
        dict(station=f"repair-{i:03}", instruction_version="RW-S1") for i in range(101)
    ]
    rw = workflow.command(
        p["id"],
        "nonconformance.disposition",
        actor_name="quality",
        nonconformance_id=nc["object_id"],
        decision="rework",
        route_id="RW-101",
        route_steps=steps,
        evidence="qualified independent full repair route",
    )
    event.update(rework_order_id=rw["object_id"], route_version="RW-S1")
    event["material_uses"][0]["quantity"] = "0.001"
    for step in steps:
        event.update(station=step["station"], occurred_at=datetime.now(UTC).isoformat())
        workflow.command(
            p["id"],
            "execution.record",
            actor_name="production",
            source=workflow.source(str(uuid4()), object_type="execution"),
            **event,
        )
    unit = workflow.object(p["id"], "unit", uid)
    assert len(unit["execution_events"]) == 100 and unit["execution_event_total"] == 102
    detail = workflow.object(p["id"], "rework", rw["object_id"])
    candidates = detail["candidate_execution_events"]
    assert len(candidates) == 101
    assert [e["station"] for e in candidates] == [s["station"] for s in steps]
    assert all(
        e["source"] and e["rework_order_id"] == rw["object_id"] for e in candidates
    )
    tested = measure(workflow, p, uid, attempt=2, rework_order_id=rw["object_id"])
    workflow.command(
        p["id"],
        "rework.complete",
        actor_name="quality",
        rework_order_id=rw["object_id"],
        execution_event_ids=[e["id"] for e in candidates],
        test_ids=[tested["object_id"]],
    )
    assert workflow.object(p["id"], "rework", rw["object_id"])["state"] == "complete"


def test_late_resume_receipt_cannot_resurrect_scrapped_output(workflow):
    from .test_execution import review_replan
    from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter
    from manufacturing_platform.workflow.quality import shipment_eligibility

    p, wo, uid, _ = executed(workflow)
    failed = measure(workflow, p, uid, value="12")
    nc = workflow.command(
        p["id"],
        "nonconformance.open",
        actor_name="quality",
        test_id=failed["object_id"],
        defect="irreparable voltage",
        evidence="measured failed",
    )
    stop = workflow.command(
        p["id"],
        "production.interrupt",
        actor_name="production",
        work_order_id=wo["id"],
        reason="equipment stop",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=stop["exchange_id"],
    )
    plan = review_replan(workflow, p, wo)
    resume = workflow.command(
        p["id"],
        "production.resume",
        actor_name="production",
        interruption_id=stop["object_id"],
        plan_id=plan,
        evidence="physical equipment repaired",
    )
    authority = MockAuthorityAdapter(str(workflow.paths.authority), "workflow-test")
    authority.configure_fault("timeout_after_commit")
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=resume["exchange_id"],
    )
    assert (
        workflow.object(p["id"], "exchange", resume["exchange_id"])["phase"]
        == "unknown"
    )
    workflow.command(
        p["id"],
        "nonconformance.disposition",
        actor_name="quality",
        nonconformance_id=nc["object_id"],
        decision="scrap",
        evidence="irreversible serial exclusion before late receipt",
    )
    authority.configure_fault("none")
    workflow.command(
        p["id"],
        "exchange.query",
        actor_name="production",
        exchange_id=resume["exchange_id"],
    )
    value = workflow.object(p["id"], "unit", uid)
    assert value["state"] == "running" and value["scrapped"] and not value["final_good"]
    with workflow.db() as tx:
        assert not shipment_eligibility(tx, p["id"], [uid]).allowed


def test_shipment_eligible_quantity_preserves_project_scale(workflow, monkeypatch):
    from manufacturing_platform.workflow.quality import shipment_eligibility

    create = workflow.create_project

    def scaled(**fields):
        fields["unit"] = {"code": "piece", "scale": 3}
        fields["quantity"] = "100.000"
        fields["contract"] = {**fields["contract"], "customer_release_required": False}
        return create(**fields)

    monkeypatch.setattr(workflow, "create_project", scaled)
    p, _, uid, _ = executed(workflow)
    measure(workflow, p, uid)
    for actor, kind in [("production", "manufacturing"), ("quality", "quality")]:
        workflow.command(
            p["id"],
            "release.decide",
            actor_name=actor,
            kind=kind,
            unit_ids=[uid],
            decision="approved",
            evidence=kind,
        )
    with workflow.db() as tx:
        assert (
            shipment_eligibility(tx, p["id"], [uid]).model_dump(mode="json")[
                "qualified_quantity"
            ]
            == "1.000"
        )


@pytest.mark.parametrize("route_count", [2, 3])
def test_review_rework_causality_survives_interleaving_and_equal_clocks(
    workflow, monkeypatch, route_count
):
    from manufacturing_platform.workflow import service

    p, _, uid, event = executed(workflow)
    last = measure(workflow, p, uid, value="12")
    fixed = datetime.now(UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(service, "datetime", Clock)

    def test_source():
        source = workflow.source(str(uuid4()), object_type="test")
        source.update(occurred_at=fixed.isoformat(), collected_at=fixed.isoformat())
        return source

    def repair(rw, stations):
        for station in stations:
            source = workflow.source(str(uuid4()), object_type="execution")
            source.update(occurred_at=fixed.isoformat(), collected_at=fixed.isoformat())
            workflow.command(
                p["id"],
                "execution.record",
                actor_name="production",
                source=source,
                **{
                    **event,
                    "station": station,
                    "route_version": "RW-S1",
                    "rework_order_id": rw,
                    "occurred_at": fixed.isoformat(),
                    "material_uses": [
                        {**event["material_uses"][0], "quantity": "0.001"}
                    ],
                },
            )

    routes = []
    attempt = 2
    for n in range(route_count):
        nc = workflow.command(
            p["id"],
            "nonconformance.open",
            actor_name="quality",
            test_id=last["object_id"],
            defect="failed repair",
            evidence="actual measurements",
        )
        rw = workflow.command(
            p["id"],
            "nonconformance.disposition",
            actor_name="quality",
            nonconformance_id=nc["object_id"],
            decision="rework",
            route_id=f"RW-{n}",
            route_steps=[
                dict(station=s, instruction_version="RW-S1")
                for s in ["repair-a", "repair-b"]
            ],
            evidence="qualified independent route",
        )["object_id"]
        routes.append(rw)
        repair(rw, ["repair-a", "repair-b"])
        last = measure(
            workflow,
            p,
            uid,
            value="12",
            attempt=attempt,
            rework_order_id=rw,
            source=test_source(),
        )
        attempt += 1
    for rw in routes:
        rejected = measure(
            workflow,
            p,
            uid,
            attempt=attempt,
            rework_order_id=rw,
            source=test_source(),
            expected_status=409,
        )
        assert rejected["code"] == "PRECONDITION_FAILED"
        repair(rw, ["repair-a"])
        measure(
            workflow,
            p,
            uid,
            attempt=attempt,
            rework_order_id=rw,
            source=test_source(),
            expected_status=409,
        )
        repair(rw, ["repair-a", "repair-b"])
        passed = measure(
            workflow, p, uid, attempt=attempt, rework_order_id=rw, source=test_source()
        )
        evidence = workflow.object(p["id"], "test", passed["object_id"])
        workflow.command(
            p["id"],
            "rework.complete",
            actor_name="quality",
            rework_order_id=rw,
            execution_event_ids=evidence["execution_event_ids"],
            test_ids=[passed["object_id"]],
        )
        attempt += 1
    assert workflow.object(p["id"], "unit", uid)["final_good"]


def test_review_quality_preconditions_use_shared_error_contract(workflow):
    p, _, units, _, _ = running_execution(workflow)
    workflow.grant(p["id"], "quality", ["quality"], ["inspection"])
    missing = measure(workflow, p, units[0], expected_status=409)
    assert missing["code"] == "PRECONDITION_FAILED"
    assert missing["blocking_reasons"] and "execution_event_ids" in missing["fields"]
    p2, _, uid, _ = executed(workflow)
    measure(workflow, p2, uid, value="12")
    failed = measure(workflow, p2, uid, attempt=2, expected_status=409)
    assert failed["code"] == "PRECONDITION_FAILED"
    assert "rework_order_id" in failed["fields"]
    invalid = measure(
        workflow, p2, uid, attempt=2, program_version="wrong", expected_status=422
    )
    assert invalid["code"] == "INVALID_COMMAND" and "measurements" in invalid["fields"]


@pytest.mark.parametrize("unsafe", ["foreign_identity", "future_at_admission"])
def test_review_quality_source_projection_rechecks_historical_admission(
    workflow, unsafe
):
    import json
    import sqlite3

    p, _, uid, _ = executed(workflow)
    tested = measure(workflow, p, uid)
    own_view = workflow.object(p["id"], "test", tested["object_id"])
    p2, _, uid2, _ = executed(workflow)
    other = measure(workflow, p2, uid2)
    other_source = workflow.object(p2["id"], "test", other["object_id"])["source"]
    source = (
        other_source
        if unsafe == "foreign_identity"
        else {
            **own_view["source"],
            "occurred_at": "2099-01-01T00:00:00+00:00",
            "collected_at": "2099-01-01T00:00:00+00:00",
        }
    )
    # Owned storage-corruption fixture only: no claim of a public ingress bypass.
    with sqlite3.connect(workflow.paths.domain) as tx:
        tx.execute(
            "UPDATE quality_tests SET source_json=? WHERE id=?",
            (json.dumps(source), tested["object_id"]),
        )
    view = workflow.object(p["id"], "test", tested["object_id"])
    assert view["source"] is None
    assert (
        view["outcome"] == "pass" and view["measurements"] == own_view["measurements"]
    )


def test_review_customer_source_projection_and_historical_read_survive_grant_change(
    workflow,
):
    import json
    import sqlite3

    p, _, uid, _ = executed(workflow)
    measured = measure(workflow, p, uid)
    revision = workflow.object(p["id"], "test", measured["object_id"])["revision_id"]
    release = workflow.command(
        p["id"],
        "release.decide",
        kind="customer",
        unit_ids=[uid],
        decision="approved",
        evidence="named customer receipt",
        customer_id="Customer 1",
        revision_id=revision,
        customer_revision="C1",
        external_signatory="Customer QA",
        method="manual",
        source=workflow.source("read-customer", object_type="customer_release"),
    )
    workflow.grant(p["id"], "quality", ["quality"], [])
    assert workflow.object(p["id"], "test", measured["object_id"])["source"] is not None
    with sqlite3.connect(workflow.paths.domain) as tx:
        raw = json.loads(
            tx.execute(
                "SELECT payload_json FROM quality_releases WHERE id=?",
                (release["object_id"],),
            ).fetchone()[0]
        )
        raw["source"]["object_type"] = "receipt"
        tx.execute(
            "UPDATE quality_releases SET payload_json=? WHERE id=?",
            (json.dumps(raw), release["object_id"]),
        )
    view = workflow.object(p["id"], "release", release["object_id"])
    assert view["source"] is None and view["external_signatory"] == "Customer QA"


def test_review_reader_concurrent_stores_keep_exact_transaction_capability(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from manufacturing_platform.workflow import quality
    from manufacturing_platform.workflow.execution import test_reader
    from manufacturing_platform.workflow.store import WorkflowStore
    from manufacturing_platform.workflow.service import WorkflowService

    class FixtureReader:
        def complete_pass(self, *args, **kwargs):
            return True

    fixture = FixtureReader()
    stores = [
        WorkflowStore(
            str(tmp_path / f"{name}.db"),
            str(tmp_path / f"{name}-authority.db"),
            dict(id=name, mode="test", label=name),
        )
        for name in ["fixture", "real"]
    ]
    WorkflowService(stores[0], lambda uid: True, test_evidence_reader=fixture)
    WorkflowService(stores[1], lambda uid: True)
    barrier = Barrier(2)

    def read(index):
        with stores[index].transaction() as tx:
            barrier.wait(timeout=5)
            selected = test_reader(tx)
            from manufacturing_platform.workflow.execution_models import (
                TestEvidenceScope,
            )

            scope = TestEvidenceScope(
                route_fingerprint="fixture",
                test_version="T",
                program_version="P",
                firmware_version="F",
                equipment_check_id=uuid4(),
            )
            passed = selected.complete_pass(
                tx, uuid4(), uuid4(), uuid4(), uuid4(), scope=scope
            )
            barrier.wait(timeout=5)
            assert selected is (fixture if index == 0 else quality)
            assert passed is (index == 0)
        assert test_reader(tx) is quality

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(read, i) for i in range(2)]
        for result in results:
            result.result(timeout=10)


@pytest.mark.parametrize(
    "audit_fault", [None, "missing_execution", "duplicate_test", "mismatched_execution"]
)
def test_review_schema11_basis_rebuild_preserves_fresh_proof_and_fails_closed(
    workflow, monkeypatch, audit_fault
):
    import sqlite3
    from manufacturing_platform.workflow.quality import shipment_eligibility

    create = workflow.create_project

    def explicit_contract(**fields):
        fields["contract"] = {**fields["contract"], "customer_release_required": False}
        return create(**fields)

    monkeypatch.setattr(workflow, "create_project", explicit_contract)
    p, unit = workflow.executed_unit()
    first = workflow.test(p["id"], unit["id"], measured="12")
    rw = workflow.rework(p["id"], first["id"])
    workflow.test(p["id"], unit["id"], measured="12", rework_order_id=rw["id"])
    lot = unit["execution_events"][0]["material_uses"][0]["lot_id"]
    workflow.command(
        p["id"],
        "execution.record",
        actor_name="production",
        work_order_id=unit["work_order_id"],
        sn=unit["sn"],
        station="repair",
        route_version="RW-S1",
        program_version="P1",
        firmware_version="F1",
        material_uses=[dict(lot_id=lot, quantity="0.001", unit="kg")],
        result="pass",
        rework_order_id=rw["id"],
        occurred_at=datetime.now(UTC).isoformat(),
        source=workflow.source(str(uuid4()), object_type="execution"),
    )
    passed = workflow.test(p["id"], unit["id"], measured="5", rework_order_id=rw["id"])
    workflow.command(
        p["id"],
        "rework.complete",
        actor_name="quality",
        rework_order_id=rw["id"],
        execution_event_ids=passed["execution_event_ids"],
        test_ids=[passed["id"]],
    )
    workflow.command(
        p["id"],
        "first_article.record",
        actor_name="quality",
        work_order_id=unit["work_order_id"],
        unit_ids=[unit["id"]],
        test_ids=[passed["id"]],
        inspection_id="valid fresh repair article",
    )
    for actor, kind in [("production", "manufacturing"), ("quality", "quality")]:
        workflow.command(
            p["id"],
            "release.decide",
            actor_name=actor,
            kind=kind,
            unit_ids=[unit["id"]],
            decision="approved",
            evidence=kind,
        )
    workflow._client.close()
    with sqlite3.connect(workflow.paths.domain) as tx:
        tx.execute("DROP VIEW valid_quality_tests")
        tx.execute("DROP TABLE quality_test_bases")
        tx.execute("UPDATE schema_version SET version=11")
        # Explicit owned historical-audit corruption fixtures; never add a successful business fact.
        if audit_fault == "missing_execution":
            tx.execute(
                "DELETE FROM audit_events WHERE id=(SELECT MIN(id) FROM audit_events WHERE action='execution.record')"
            )
        elif audit_fault == "mismatched_execution":
            tx.execute(
                "UPDATE audit_events SET typed_payload=json_set(typed_payload,'$.station','unrelated') WHERE id=(SELECT MIN(id) FROM audit_events WHERE action='execution.record')"
            )
        elif audit_fault == "duplicate_test":
            tx.execute(
                "INSERT INTO audit_events(project_id,actor_id,action,object_id,occurred_at,recorded_at,typed_payload) SELECT project_id,actor_id,action,object_id,occurred_at,recorded_at,typed_payload FROM audit_events WHERE action='test.record' AND object_id=?",
                (passed["id"],),
            )
    tables = [
        "quality_tests",
        "execution_events",
        "audit_events",
        "operations",
        "exchanges",
        "rework_completions",
        "quality_releases",
        "quality_release_units",
        "first_articles",
    ]
    with workflow.db() as tx:
        before = {
            table: [
                tuple(row)
                for row in tx.execute(f"SELECT * FROM {table} ORDER BY rowid")
            ]
            for table in tables
        }
    workflow.reopen()
    detail = workflow.object(p["id"], "unit", unit["id"])
    assert detail["final_good"] is (audit_fault is None)
    assert workflow.object(p["id"], "work_order", unit["work_order_id"])[
        "bulk_readiness"
    ]["ready"] is (audit_fault is None)
    with workflow.db() as tx:
        assert shipment_eligibility(tx, p["id"], [unit["id"]]).allowed is (
            audit_fault is None
        )
        assert {
            table: [
                tuple(row)
                for row in tx.execute(f"SELECT * FROM {table} ORDER BY rowid")
            ]
            for table in tables
        } == before
        assert tx.execute("SELECT version FROM schema_version").fetchone()[0] == 13
    if audit_fault is not None:
        refused = measure(workflow, p, unit["id"], attempt=4, expected_status=409)
        assert refused["code"] == "PRECONDITION_FAILED"


def test_review_quality_history_suppresses_unbound_audit_source(workflow):
    import json
    import sqlite3

    p, _, uid, _ = executed(workflow)
    tested = measure(workflow, p, uid)
    p2, _, uid2, _ = executed(workflow)
    foreign = measure(workflow, p2, uid2)
    source = workflow.object(p2["id"], "test", foreign["object_id"])["source"]
    # Owned unsafe historical-audit fixture; original measurement stays untouched.
    with sqlite3.connect(workflow.paths.domain) as tx:
        row = tx.execute(
            "SELECT id,typed_payload FROM audit_events WHERE object_id=? AND action='test.record'",
            (tested["object_id"],),
        ).fetchone()
        payload = json.loads(row[1])
        payload["source"] = source
        tx.execute(
            "UPDATE audit_events SET typed_payload=? WHERE id=?",
            (json.dumps(payload), row[0]),
        )
    response = workflow.client().get(
        f"{BASE}/projects/{p['id']}/objects/test/{tested['object_id']}"
    )
    assert response.status_code == 200
    assert response.json()["value"]["source"] is not None
    assert source["external_id"] not in response.text
    assert response.json()["history"][0]["evidence"] == []
