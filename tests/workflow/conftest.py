"""Trusted, isolated host for workflow API regressions and later domain tasks."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from manufacturing_platform import build_workflow_router

USERS = {
    name: UUID(f"00000000-0000-4000-8000-{number:012d}")
    for number, name in enumerate(
        (
            "owner",
            "engineering",
            "planner",
            "supply",
            "production",
            "quality",
            "warehouse",
            "outsider",
        ),
        1,
    )
}
BASE = "/api/v1/manufacturing/workflow"


@dataclass(frozen=True)
class WorkflowPaths:
    legacy: Path
    domain: Path
    authority: Path


class WorkflowHarness:
    def __init__(self, root: Path):
        self.paths = WorkflowPaths(
            root / "legacy.db", root / "domain.db", root / "authority.db"
        )
        self.paths.legacy.write_bytes(b"untouched legacy sentinel")
        self.read_only = set()
        self.hard_stale = set()
        self.inactive = set()
        self.reopen()

    def reopen(self):
        if hasattr(self, "_client"):
            self._client.close()

        def authenticate(request: Request, write=False):
            name = request.headers.get("x-test-actor")
            if name not in USERS:
                raise HTTPException(401, "authentication required")
            if write and request.headers.get("x-csrf-token") != "trusted-test-csrf":
                raise HTTPException(403, "CSRF required")
            if write and name in self.hard_stale:
                raise HTTPException(503, "hard_stale_read_only")
            return {
                "user_id": USERS[name],
                "display_name": name,
                "read_only": name in self.read_only,
                "configuration_admin": name == "owner",
            }

        app = FastAPI()
        app.include_router(
            build_workflow_router(
                database_path=str(self.paths.domain),
                authority_database_path=str(self.paths.authority),
                assets_dir=str(self.paths.domain.parent),
                authenticate=authenticate,
                resolve_subject=lambda uid: (
                    uid in USERS.values()
                    and uid not in {USERS[n] for n in self.inactive}
                ),
                release="test",
                dataset={
                    "id": "workflow-test",
                    "mode": "test",
                    "label": "Workflow test",
                },
            )
        )
        self._client = TestClient(app)
        self.app = app
        return self

    def client(self, actor_name="owner"):
        class ActorClient:
            def __init__(self, client, actor):
                self._client, self._actor = client, actor

            def request(self, method, url, **kwargs):
                headers = {
                    "x-test-actor": self._actor,
                    "x-csrf-token": "trusted-test-csrf",
                }
                headers.update(kwargs.pop("headers", {}))
                return self._client.request(method, url, headers=headers, **kwargs)

            def get(self, url, **kwargs):
                return self.request("GET", url, **kwargs)

            def post(self, url, **kwargs):
                return self.request("POST", url, **kwargs)

            def put(self, url, **kwargs):
                return self.request("PUT", url, **kwargs)

        return ActorClient(self._client, actor_name)

    def create_project(self, **overrides):
        body = {
            "operation_id": str(uuid4()),
            "name": "Camera",
            "line_id": "Line 1",
            "product": "Camera",
            "customer_id": "Customer 1",
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
        body.update(overrides)
        response = self.client().post(BASE + "/projects", json=body)
        assert response.status_code == 200, response.text
        return response.json()

    def grant(
        self,
        project_id,
        actor_name,
        roles,
        qualifications=(),
        *,
        active=True,
        **overrides,
    ):
        version = self.client().get(f"{BASE}/projects/{project_id}").json()["version"]
        body = {
            "operation_id": str(uuid4()),
            "expected_version": version,
            "scope": {"kind": "project", "project_id": str(project_id)},
            "roles": list(roles),
            "qualifications": list(qualifications),
            "active": active,
            "evidence": "test grant",
        }
        body.update(overrides)
        response = self.client().put(
            f"{BASE}/projects/{project_id}/members/{USERS[actor_name]}", json=body
        )
        assert response.status_code == 200, response.text
        return response.json()

    def source(
        self,
        external_id,
        system="erp",
        version=1,
        *,
        object_type="demand",
        mode="manual",
    ):
        return {
            "system": system,
            "object_type": object_type,
            "external_id": external_id,
            "version": version,
            "mode": mode,
            "occurred_at": "2026-10-28T08:00:00+00:00",
            "collected_at": "2026-10-28T08:01:00+00:00",
            "cutoff": "2026-10-28T08:00:00+00:00",
            "evidence": f"manual entry: {external_id}",
        }

    def command(
        self, project_id, action, *, actor_name="owner", expected_status=200, **fields
    ):
        version = (
            self.client(actor_name)
            .get(f"{BASE}/projects/{project_id}")
            .json()["version"]
        )
        response = self.client(actor_name).post(
            f"{BASE}/projects/{project_id}/commands",
            json={
                "operation_id": str(uuid4()),
                "expected_version": version,
                "action": action,
                **fields,
            },
        )
        assert response.status_code == expected_status, response.text
        return response.json()

    def db(self):
        connection = sqlite3.connect(f"file:{self.paths.domain}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection


@pytest.fixture
def workflow(tmp_path):
    harness = WorkflowHarness(tmp_path)
    yield harness
    harness._client.close()


def _revision(self, project_id, *, internal_revision="M1", customer_revision="C1"):
    self.grant(project_id, "engineering", ["engineering"], ["readiness_verification"])
    result = self.command(
        project_id,
        "engineering.revision",
        actor_name="engineering",
        package_id="package-camera",
        revision=internal_revision,
        customer_revision=customer_revision,
        internal_revision=internal_revision,
        items=[
            {
                "id": "drawing",
                "kind": "drawing",
                "title": "Camera drawing",
                "revision": internal_revision,
                "status": "verified",
                "evidence": "signed design",
            }
        ],
        route_steps=[{"station": "assembly", "instruction_version": "S1"}],
        test_spec={
            "version": "T1",
            "program_version": "P1",
            "measurements": [
                {"name": "voltage", "unit": "V", "lower": "4", "upper": "6"}
            ],
        },
        firmware_version="F1",
    )
    return {"id": result["object_id"]}


def _order_workorder(self, *, quantity="5", contract=None):
    p = self.create_project(**({"contract": contract} if contract else {}))
    demand = self.command(
        p["id"],
        "demand.record",
        kind="firm",
        product="Camera",
        quantity=quantity,
        unit="piece",
        due_date="2026-12-01",
        source=self.source(f"demand-{uuid4()}"),
    )["object_id"]
    for dimension in ("technical", "material", "capacity", "commercial", "quality"):
        self.command(
            p["id"],
            "demand.review",
            demand_id=demand,
            dimension=dimension,
            decision="approved",
            evidence=f"{dimension} reviewed",
        )
    order = self.command(
        p["id"],
        "order.register",
        demand_id=demand,
        source=self.source(f"order-{uuid4()}", object_type="order_line"),
        quantity=quantity,
        unit="piece",
        due_date="2026-12-01",
    )
    rev = self.revision(
        p["id"], customer_revision=contract["customer_revision"] if contract else "C1"
    )
    self.command(
        p["id"],
        "engineering.handoff",
        actor_name="engineering",
        revision_id=rev["id"],
        to_system="MES",
        received_revision="M1",
        decision="accepted",
        evidence="MES package acknowledgement",
    )
    self.grant(p["id"], "planner", ["planner"])
    wo = self.command(
        p["id"],
        "work_order.register",
        actor_name="planner",
        order_line_id=order["object_id"],
        revision_id=rev["id"],
        source=self.source(f"wo-{uuid4()}", object_type="work_order"),
        quantity=quantity,
        unit="piece",
        purpose="trial",
        trial_quantity="1",
        planned_start="2026-12-01T00:00:00+00:00",
        planned_end="2026-12-02T00:00:00+00:00",
    )
    return p, {"id": order["object_id"]}, {"id": wo["object_id"]}, rev


def _object(self, project_id, kind, object_id):
    response = self.client().get(
        f"{BASE}/projects/{project_id}/objects/{kind}/{object_id}"
    )
    assert response.status_code == 200, response.text
    return response.json()["value"]


WorkflowHarness.revision = _revision
WorkflowHarness.order_workorder = _order_workorder
WorkflowHarness.object = _object
