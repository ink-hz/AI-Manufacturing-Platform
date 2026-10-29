"""Engineering introduction uses actual HTTP evidence and isolates public reuse."""

from uuid import uuid4

import pytest

from .conftest import BASE
from .test_quality import executed, measure


def open_npi(w, p, revision, work_order_ids=()):
    return w.command(
        p["id"],
        "npi.open",
        revision_id=revision,
        product_family="camera",
        scenario="first_introduction",
        required_checks=["engineering"],
        work_order_ids=list(work_order_ids),
    )["object_id"]


def review(w, p, npi, decision="pass"):
    return w.command(
        p["id"],
        "npi.review",
        npi_id=npi,
        checks=[
            {
                "code": "engineering",
                "required": True,
                "decision": decision,
                "evidence": "signed engineering review",
                "reason": "review decision",
            }
        ],
    )


def trial_npi(w):
    p, wo, uid, _ = executed(w)
    rev = w.object(p["id"], "work_order", wo["id"])["revision_id"]
    npi = open_npi(w, p, rev, [wo["id"]])
    return p, wo, uid, npi


def complete_trial(w, p, wo, uid, npi):
    test = measure(w, p, uid)["object_id"]
    w.command(
        p["id"],
        "npi.trial",
        npi_id=npi,
        work_order_id=wo["id"],
        test_ids=[test],
        evidence="actual trial measurements",
    )
    return test


def resolved_issue(w):
    p, wo, uid, npi = trial_npi(w)
    test = complete_trial(w, p, wo, uid, npi)
    issue = w.command(
        p["id"],
        "npi.issue",
        npi_id=npi,
        phenomenon="PRIVATE CUSTOMER DEFECT",
        risk="private risk",
        containment="isolate source unit",
    )["object_id"]
    w.command(
        p["id"],
        "npi.resolve",
        issue_id=issue,
        verified_cause="verified connector force",
        countermeasure="controlled fixture",
        verification_evidence="measured correction",
        test_ids=[test],
    )
    return p, npi, issue


CONTENT = {
    "title": "Generic fixture check",
    "category": "check",
    "product_families": ["camera"],
    "execution_content": "Inspect fixture alignment",
    "verification_method": "Measure alignment",
}


def publish(w, p, issue, **overrides):
    return w.command(
        p["id"],
        "asset.publish",
        issue_id=issue,
        content={**CONTENT, "title": "PRIVATE PROJECT METHOD"},
        **overrides,
    )["object_id"]


def test_npi_fixed_scope_review_trial_issues_and_live_bulk_gate(workflow):
    w = workflow
    p, wo, uid, npi = trial_npi(w)
    other = w.create_project()
    foreign = w.revision(other["id"])
    w.command(
        p["id"],
        "npi.open",
        revision_id=foreign["id"],
        product_family="camera",
        scenario="first_introduction",
        required_checks=["engineering"],
        expected_status=404,
    )
    w.command(
        p["id"], "npi.approve", npi_id=npi, evidence="signoff", expected_status=409
    )
    review(w, p, npi, "blocked")
    complete_trial(w, p, wo, uid, npi)
    w.command(
        p["id"], "npi.approve", npi_id=npi, evidence="signoff", expected_status=409
    )
    review(w, p, npi)
    w.command(p["id"], "npi.approve", npi_id=npi, evidence="signoff")
    assert w.object(p["id"], "npi", npi)["bulk_eligible"] is True
    issue = w.command(
        p["id"],
        "npi.issue",
        npi_id=npi,
        phenomenon="new defect",
        risk="quality",
        containment="hold",
    )["object_id"]
    assert w.object(p["id"], "npi", npi)["bulk_eligible"] is False
    blocked = w.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="bulk",
        unit_ids=[uid],
        quantity="1",
        expected_status=409,
    )
    assert "NPI" in str(blocked["blocking_reasons"])
    w.command(
        p["id"], "npi.approve", npi_id=npi, evidence="signoff", expected_status=409
    )
    assert w.object(p["id"], "npi_issue", issue)["state"] == "open"
    assert len(w.object(p["id"], "npi", npi)["approvals"]) == 1


def test_trial_retains_failed_results_and_rejects_claimed_foreign_evidence(workflow):
    w = workflow
    p, wo, uid, npi = trial_npi(w)
    w.command(
        p["id"],
        "npi.trial",
        npi_id=npi,
        work_order_id=wo["id"],
        test_ids=[str(uuid4())],
        evidence="claimed pass",
        expected_status=409,
    )
    failed = measure(w, p, uid, value="12")["object_id"]
    w.command(
        p["id"],
        "npi.trial",
        npi_id=npi,
        work_order_id=wo["id"],
        test_ids=[failed],
        evidence="failed trial",
    )
    history = w.object(p["id"], "npi", npi)["trials"]
    assert history[0]["outcome"] == "fail" and not history[0]["qualified"]
    review(w, p, npi)
    w.command(
        p["id"],
        "npi.approve",
        npi_id=npi,
        evidence="failed cannot qualify",
        expected_status=409,
    )
    repair = w.rework(p["id"], failed)
    passed = w.test(p["id"], uid, measured="5", rework_order_id=repair["id"])
    w.command(
        p["id"],
        "rework.complete",
        actor_name="quality",
        rework_order_id=repair["id"],
        execution_event_ids=passed["execution_event_ids"],
        test_ids=[passed["id"]],
    )
    w.command(
        p["id"],
        "npi.trial",
        npi_id=npi,
        work_order_id=wo["id"],
        test_ids=[passed["id"]],
        evidence="actual repaired trial",
    )
    w.command(p["id"], "npi.approve", npi_id=npi, evidence="passing repaired trial")
    history = w.object(p["id"], "npi", npi)["trials"]
    assert [t["outcome"] for t in history] == ["fail", "pass"]
    assert history[-1]["qualified"]
    p2, wo2, uid2, _ = trial_npi(w)
    good = measure(w, p2, uid2)["object_id"]
    w.command(
        p["id"],
        "npi.trial",
        npi_id=npi,
        work_order_id=wo2["id"],
        test_ids=[good],
        evidence="foreign trial",
        expected_status=404,
    )
    w.command(
        p["id"],
        "npi.trial",
        npi_id=npi,
        work_order_id=wo["id"],
        test_ids=[good],
        evidence="foreign test",
        expected_status=409,
    )


def test_public_asset_snapshot_revision_applicability_and_no_source_leaks(workflow):
    w = workflow
    p, _, issue = resolved_issue(w)
    private = publish(w, p, issue)
    public = publish(w, p, issue, public_content=CONTENT)
    target = w.create_project()
    rev = w.revision(target["id"])
    npi = open_npi(w, target, rev["id"])
    w.grant(target["id"], "planner", ["engineering"])
    w.grant(p["id"], "planner", [], active=False)
    client = w.client("planner")
    page = client.get(BASE + "/reusable-assets?limit=1")
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 1 and len(page.json()["items"]) == 1
    assert (
        "private" not in page.text.lower()
        and p["id"] not in page.text
        and issue not in page.text
    )
    assert (
        client.get(
            f"{BASE}/projects/{p['id']}/objects/reusable_asset/{public}"
        ).status_code
        == 404
    )
    assert client.get(BASE + "/reusable-assets?limit=201").status_code == 422
    assert w.client("outsider").get(BASE + "/reusable-assets").status_code == 403
    assert w._client.get(BASE + "/reusable-assets").status_code == 401
    error = w.command(
        target["id"],
        "asset.apply",
        actor_name="planner",
        npi_id=npi,
        asset_revision_id=private,
        required=True,
        expected_status=404,
    )
    assert p["id"] not in str(error) and issue not in str(error)
    use = w.command(
        target["id"],
        "asset.apply",
        actor_name="planner",
        npi_id=npi,
        asset_revision_id=public,
        required=True,
    )["object_id"]
    detail = client.get(f"{BASE}/projects/{target['id']}/objects/asset_use/{use}")
    assert detail.status_code == 200
    assert (
        p["id"] not in detail.text
        and issue not in detail.text
        and "PRIVATE" not in detail.text
    )
    first = detail.json()["value"]["snapshot"]
    w.command(
        target["id"],
        "asset.verify",
        actor_name="planner",
        asset_use_id=use,
        decision="pass",
        evidence="independent target fixture measurement",
    )
    assert (
        w.object(target["id"], "asset_use", use)["verifications"][0]["decision"]
        == "pass"
    )
    second = publish(
        w,
        p,
        issue,
        public_content={**CONTENT, "execution_content": "New generic instruction"},
        supersedes_id=public,
    )
    assert second != public
    assert w.object(target["id"], "asset_use", use)["snapshot"] == first
    w.command(
        target["id"],
        "npi.open",
        revision_id=rev["id"],
        product_family="printer",
        scenario="change_validation",
        required_checks=["engineering"],
    )
    printer = (
        w.client()
        .get(f"{BASE}/projects/{target['id']}/objects/npi")
        .json()["items"][-1]["id"]
    )
    w.command(
        target["id"],
        "asset.apply",
        npi_id=printer,
        asset_revision_id=public,
        required=True,
        expected_status=409,
    )
    w.grant(target["id"], "planner", [], active=False)
    assert client.get(BASE + "/reusable-assets").status_code == 403


def test_public_publish_requires_admin_and_resolved_issue(workflow):
    w = workflow
    p, wo, uid, npi = trial_npi(w)
    issue = w.command(
        p["id"],
        "npi.issue",
        npi_id=npi,
        phenomenon="defect",
        risk="risk",
        containment="isolate",
    )["object_id"]
    w.command(
        p["id"], "asset.publish", issue_id=issue, content=CONTENT, expected_status=409
    )
    w.command(
        p["id"],
        "npi.resolve",
        issue_id=issue,
        verified_cause="cause",
        countermeasure="fix",
        verification_evidence="assertion",
        test_ids=[str(uuid4())],
        expected_status=409,
    )
    test = complete_trial(w, p, wo, uid, npi)
    w.command(
        p["id"],
        "npi.resolve",
        issue_id=issue,
        verified_cause="cause",
        countermeasure="fix",
        verification_evidence="measured",
        test_ids=[test],
    )
    w.command(
        p["id"],
        "asset.publish",
        actor_name="engineering",
        issue_id=issue,
        content=CONTENT,
        public_content=CONTENT,
        expected_status=403,
    )
    w.command(
        p["id"],
        "asset.publish",
        actor_name="engineering",
        issue_id=issue,
        content=CONTENT,
    )


def test_npi_readiness_projection_and_adopted_checks_require_reapproval(workflow):
    w = workflow
    source, _, issue = resolved_issue(w)
    asset = publish(w, source, issue, public_content=CONTENT)
    p, wo, uid, npi = trial_npi(w)
    complete_trial(w, p, wo, uid, npi)
    review(w, p, npi)
    use = w.command(
        p["id"], "asset.apply", npi_id=npi, asset_revision_id=asset, required=True
    )["object_id"]
    w.command(
        p["id"], "npi.approve", npi_id=npi, evidence="signoff", expected_status=409
    )
    w.command(
        p["id"],
        "asset.verify",
        asset_use_id=use,
        decision="pass",
        evidence="target test",
    )
    w.command(p["id"], "npi.approve", npi_id=npi, evidence="signoff")
    readiness = w.object(p["id"], "work_order", wo["id"])["bulk_readiness"]
    assert (
        next(c for c in readiness["checks"] if c["kind"] == "npi")["status"] == "ready"
    )
    review(w, p, npi, "blocked")
    readiness = w.object(p["id"], "work_order", wo["id"])["bulk_readiness"]
    assert (
        next(c for c in readiness["checks"] if c["kind"] == "npi")["status"]
        == "blocked"
    )
    review(w, p, npi)
    assert not w.object(p["id"], "npi", npi)["bulk_eligible"]
    w.command(p["id"], "npi.approve", npi_id=npi, evidence="reapproval")
    assert w.object(p["id"], "npi", npi)["bulk_eligible"]
    measure(w, p, uid, attempt=2)
    assert not w.object(p["id"], "npi", npi)["bulk_eligible"]


def test_npi_action_hints_and_security_apply_to_new_actions(workflow):
    w = workflow
    p = w.create_project()
    revision = w.revision(p["id"])
    npi = open_npi(w, p, revision["id"])
    detail = w.client().get(f"{BASE}/projects/{p['id']}/objects/npi/{npi}").json()
    assert "npi.review" in detail["summary"]["next_actions"]
    version = w.client().get(f"{BASE}/projects/{p['id']}").json()["version"]
    body = {
        "action": "npi.review",
        "operation_id": str(uuid4()),
        "expected_version": version,
        "npi_id": npi,
        "checks": [
            {
                "code": "engineering",
                "required": True,
                "decision": "pass",
                "evidence": "review",
                "reason": "review",
            }
        ],
    }
    url = f"{BASE}/projects/{p['id']}/commands"
    assert (
        w.client().post(url, json=body, headers={"x-csrf-token": ""}).status_code == 403
    )
    assert w.client().post(url, json=body).status_code == 200
    assert w.client().post(url, json=body).json()["replayed"]
    assert (
        w.client().post(url, json={**body, "operation_id": str(uuid4())}).status_code
        == 409
    )
    w.read_only.add("owner")
    assert w.client().post(url, json=body).status_code == 403
    w.read_only.clear()
    w.grant(p["id"], "engineering", [], active=False)
    assert w.client("engineering").post(url, json=body).status_code == 404


@pytest.mark.parametrize("invalidate_before_dispatch", [False, True])
def test_approved_npi_allows_real_bulk_and_trial_retains_existing_rules(
    workflow, invalidate_before_dispatch
):
    w = workflow
    p, wo, uid, npi = trial_npi(w)
    test = complete_trial(w, p, wo, uid, npi)
    review(w, p, npi)
    w.command(
        p["id"],
        "first_article.record",
        actor_name="quality",
        work_order_id=wo["id"],
        unit_ids=[uid],
        test_ids=[test],
        inspection_id="actual NPI first article",
    )
    units = w.client().get(f"{BASE}/projects/{p['id']}/objects/unit").json()["items"]
    unstarted = [u["id"] for u in units if u["id"] != uid]
    w.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="bulk",
        unit_ids=unstarted,
        quantity="4",
        expected_status=409,
    )
    w.command(p["id"], "npi.approve", npi_id=npi, evidence="verified signoff")
    start = w.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="bulk",
        unit_ids=unstarted,
        quantity="4",
    )
    if invalidate_before_dispatch:
        w.command(
            p["id"],
            "npi.issue",
            npi_id=npi,
            phenomenon="new blocker before dispatch",
            risk="quality",
            containment="hold before external effect",
        )
    w.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=start["exchange_id"],
    )
    if invalidate_before_dispatch:
        from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

        authority = MockAuthorityAdapter(str(w.paths.authority), "workflow-test")
        assert authority.operation_count(start["exchange_id"]) == 0
    expected_state = "start_pending" if invalidate_before_dispatch else "running"
    assert all(
        w.object(p["id"], "unit", u)["state"] == expected_state for u in unstarted
    )


def test_schema17_upgrade_is_additive_and_preserves_existing_facts(workflow):
    import sqlite3

    w = workflow
    p, _order, wo, rev = w.order_workorder()
    tables = [
        "projects",
        "engineering_revisions",
        "work_orders",
        "operations",
        "audit_events",
    ]
    with w.db() as tx:
        before = {
            t: [tuple(r) for r in tx.execute(f"SELECT * FROM {t} ORDER BY rowid")]
            for t in tables
        }
    w._client.close()
    with sqlite3.connect(w.paths.domain) as tx:
        for t in [
            "asset_verifications",
            "asset_uses",
            "reusable_assets",
            "npi_issues",
            "npi_records",
            "npi_work_orders",
            "npis",
        ]:
            tx.execute(f"DROP TABLE {t}")
        tx.execute("UPDATE schema_version SET version=17")
    w.reopen()
    assert w.object(p["id"], "work_order", wo["id"])["revision_id"] == rev["id"]
    with w.db() as tx:
        assert tx.execute("SELECT version FROM schema_version").fetchone()[0] == 18
        assert {
            t: [tuple(r) for r in tx.execute(f"SELECT * FROM {t} ORDER BY rowid")]
            for t in tables
        } == before
    open_npi(w, p, rev["id"], [wo["id"]])


def test_process_issue_can_resolve_with_signed_inspection_without_unit_test(workflow):
    w = workflow
    p = w.create_project()
    rev = w.revision(p["id"])
    npi = open_npi(w, p, rev["id"])
    issue = w.command(
        p["id"],
        "npi.issue",
        npi_id=npi,
        phenomenon="incoming fixture dimensions",
        risk="assembly interference",
        containment="quarantine fixtures",
    )["object_id"]
    w.command(
        p["id"],
        "npi.resolve",
        issue_id=issue,
        verified_cause="dimensional inspection found worn jig",
        countermeasure="replace jig",
        verification_evidence="signed incoming dimensional report INS-42",
    )
    asset = publish(w, p, issue)
    assert w.object(p["id"], "reusable_asset", asset)["issue_id"] == issue
    w.command(
        p["id"],
        "npi.approve",
        npi_id=npi,
        evidence="still requires real trial",
        expected_status=409,
    )


def test_public_publication_replay_requires_current_admin_authority(workflow):
    w = workflow
    p, _, issue = resolved_issue(w)
    version = w.client().get(f"{BASE}/projects/{p['id']}").json()["version"]
    body = {
        "action": "asset.publish",
        "operation_id": str(uuid4()),
        "expected_version": version,
        "issue_id": issue,
        "content": CONTENT,
        "public_content": CONTENT,
    }
    url = f"{BASE}/projects/{p['id']}/commands"
    assert w.client("admin").post(url, json=body).status_code == 200
    assert w.client("admin").post(url, json=body).json()["replayed"]
    w.read_only.add("admin")
    assert w.client("admin").post(url, json=body).status_code == 403
    w.read_only.clear()
    w.grant(p["id"], "admin", ["engineering"])
    w.configuration_admins.remove("admin")
    assert w.client("admin").post(url, json=body).status_code == 403
    current = w.client().get(f"{BASE}/projects/{p['id']}").json()["version"]
    assert (
        w.client("admin")
        .post(
            url,
            json={**body, "operation_id": str(uuid4()), "expected_version": current},
        )
        .status_code
        == 403
    )
    w.grant(p["id"], "admin", [], active=False)
    assert w.client("admin").post(url, json=body).status_code == 404
