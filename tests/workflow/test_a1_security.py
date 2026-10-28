import hashlib
from uuid import uuid4

from .conftest import BASE, USERS


def test_scope_revocation_reopen_and_legacy_file_untouched(workflow):
    before = hashlib.sha256(workflow.paths.legacy.read_bytes()).digest()
    first = workflow.create_project()
    other = workflow.create_project(name="Unrelated")
    workflow.grant(first["id"], "planner", ["planner"])
    planner = workflow.client("planner")
    assert planner.get(BASE + "/access").json()["project_ids"] == [first["id"]]
    assert planner.get(f"{BASE}/projects/{other['id']}").status_code == 404
    workflow.reopen()
    assert (
        workflow.client("planner").get(f"{BASE}/projects/{first['id']}").status_code
        == 200
    )
    workflow.grant(first["id"], "planner", [], active=False)
    assert (
        workflow.client("planner").get(f"{BASE}/projects/{first['id']}").status_code
        == 404
    )
    assert hashlib.sha256(workflow.paths.legacy.read_bytes()).digest() == before


def test_active_grant_without_a_business_role_does_not_confer_project_access(workflow):
    project = workflow.create_project()
    workflow.grant(project["id"], "planner", [])
    assert (
        workflow.client("planner").get(BASE + "/access").json()["workflow_access"]
        is False
    )
    assert (
        workflow.client("planner").get(f"{BASE}/projects/{project['id']}").status_code
        == 404
    )


def test_unauthorized_requests_do_not_parse_body_or_initialize_store(workflow):
    assert not workflow.paths.domain.exists()
    response = workflow.client("outsider").post(
        BASE + "/projects", content=b"broken json"
    )
    assert response.status_code == 403
    assert not workflow.paths.domain.exists()
    response = workflow._client.get(BASE + "/access")
    assert response.status_code == 401
    assert not workflow.paths.domain.exists()


def test_read_only_and_hard_stale_block_mutations(workflow):
    project = workflow.create_project()
    workflow.grant(project["id"], "planner", ["planner"])
    workflow.read_only.add("planner")
    assert (
        workflow.command(
            project["id"], "demand.record", actor_name="planner"
        ).status_code
        == 403
    )
    workflow.read_only.clear()
    workflow.hard_stale.add("planner")
    assert (
        workflow.command(
            project["id"], "demand.record", actor_name="planner"
        ).status_code
        == 503
    )
    assert (
        workflow.client("planner").get(f"{BASE}/projects/{project['id']}").status_code
        == 200
    )


def test_project_and_grant_operations_are_atomic_cas_and_audited(workflow):
    project = workflow.create_project()
    workflow.grant(project["id"], "planner", ["planner"])
    with workflow.db() as db:
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 2
        assert (
            db.execute("SELECT action FROM audit_events ORDER BY id").fetchall()[1][0]
            == "grant.change"
        )
        assert (
            db.execute(
                "SELECT version FROM projects WHERE id=?", (project["id"],)
            ).fetchone()[0]
            == 2
        )
    stale = {
        "operation_id": str(uuid4()),
        "expected_version": 1,
        "roles": ["quality"],
        "qualifications": ["quality_release"],
        "active": True,
        "evidence": "late",
    }
    response = workflow.client().put(
        f"{BASE}/projects/{project['id']}/members/{USERS['quality']}", json=stale
    )
    assert response.status_code == 409
    with workflow.db() as db:
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 2


def test_assets_require_exact_name_and_release(workflow, tmp_path):
    workflow.create_project()
    (tmp_path / "manufacturing.js").write_text("const safe = true")
    assert (
        workflow.client()
        .get(BASE + "/assets/manufacturing.js?release=test")
        .status_code
        == 200
    )
    assert (
        workflow.client()
        .get(BASE + "/assets/manufacturing.js?release=wrong")
        .status_code
        == 409
    )
    assert workflow.client().get(BASE + "/assets/manufacturing.js").status_code == 409
    assert (
        workflow.client().get(BASE + "/assets/secrets.txt?release=test").status_code
        == 404
    )
