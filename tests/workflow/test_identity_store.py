from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from manufacturing_platform import build_workflow_router


def test_project_grant_revocation_and_persistence(tmp_path):
    owner, member = uuid4(), uuid4()
    identities = {"owner": owner, "member": member}

    def authenticate(request, write=False):
        name = request.headers.get("x-test-user")
        if name not in identities:
            raise HTTPException(401)
        return {
            "user_id": str(identities[name]),
            "display_name": name,
            "read_only": False,
            "configuration_admin": name == "owner",
        }

    app = FastAPI()
    app.include_router(
        build_workflow_router(
            database_path=str(tmp_path / "domain.db"),
            authority_database_path=str(tmp_path / "authority.db"),
            assets_dir=str(tmp_path),
            authenticate=authenticate,
            resolve_subject=lambda uid: uid in identities.values(),
            release="test",
            dataset={"id": "test", "mode": "test", "label": "Test"},
        )
    )
    c = TestClient(app)
    h = {"x-test-user": "owner"}
    body = {
        "operation_id": str(uuid4()),
        "name": "Camera",
        "line_id": "line",
        "product": "camera",
        "customer_id": "customer",
        "mode": "internal",
        "unit": {"code": "piece", "scale": 0},
        "quantity": "100",
        "contract": {
            "customer_approval_required": "unknown",
            "customer_release_required": "unknown",
            "acceptance_required": "unknown",
            "customer_revision": "unknown",
            "internal_revision": "unknown",
            "material_ownership_rules": "unknown",
        },
    }
    p = c.post("/api/v1/manufacturing/workflow/projects", headers=h, json=body)
    assert p.status_code == 200, p.text
    project = p.json()
    change = {
        "operation_id": str(uuid4()),
        "expected_version": 1,
        "scope": {"kind": "project", "project_id": project["id"]},
        "roles": ["planner"],
        "qualifications": [],
        "active": True,
        "evidence": "assigned",
    }
    url = f"/api/v1/manufacturing/workflow/projects/{project['id']}/members/{member}"
    first = c.put(url, headers=h, json=change)
    assert first.status_code == 200
    assert c.put(url, headers=h, json=change).json() == first.json()
    conflict = dict(change, evidence="changed")
    assert c.put(url, headers=h, json=conflict).json()["code"] == "IDEMPOTENCY_CONFLICT"
    unknown = dict(change, operation_id=str(uuid4()), expected_version=2)
    assert (
        c.put(
            url.rsplit("/", 1)[0] + "/" + str(uuid4()), headers=h, json=unknown
        ).status_code
        == 422
    )
    stale = dict(change, operation_id=str(uuid4()))
    assert c.put(url, headers=h, json=stale).json()["code"] == "VERSION_CONFLICT"
    assert (
        c.get(
            f"/api/v1/manufacturing/workflow/projects/{project['id']}",
            headers={"x-test-user": "member"},
        ).status_code
        == 200
    )
    change.update(operation_id=str(uuid4()), expected_version=2, active=False)
    assert c.put(url, headers=h, json=change).status_code == 200
    assert (
        c.get(
            f"/api/v1/manufacturing/workflow/projects/{project['id']}",
            headers={"x-test-user": "member"},
        ).status_code
        == 404
    )


def test_configuration_rejects_colliding_databases_without_touching_file(tmp_path):
    path = tmp_path / "legacy.db"
    path.write_bytes(b"legacy data")
    app = FastAPI()
    app.include_router(
        build_workflow_router(
            database_path=str(path),
            authority_database_path=str(path),
            assets_dir=str(tmp_path),
            authenticate=lambda request, write=False: {
                "user_id": str(uuid4()),
                "display_name": "owner",
                "read_only": False,
                "configuration_admin": True,
            },
            resolve_subject=lambda uid: True,
            release="test",
            dataset={"id": "test", "mode": "test", "label": "Test"},
        )
    )
    assert (
        TestClient(app).get("/api/v1/manufacturing/workflow/access").status_code == 503
    )
    assert path.read_bytes() == b"legacy data"
