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
            "admin",
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
        self.configuration_admins = {"owner", "admin"}
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
                "configuration_admin": name in self.configuration_admins,
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
                resolve_subject_profiles=lambda ids: [dict(user_id=str(uid), display_name="Quality Engineer" if name=="quality" else name.title()) for name,uid in USERS.items() if uid in ids and name not in self.inactive],
                release="test",
                dataset={
                    "id": "workflow-test",
                    "mode": "test",
                    "label": "Workflow test",
                },
                test_evidence_reader=getattr(self, "test_evidence_reader", None),
                business_clock=getattr(self, "business_clock", None),
                production_tools=getattr(self, "production_tools", None),
                sap_access_service=getattr(self, "sap_access_service", None),
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
        from datetime import UTC, datetime
        current = datetime.now(UTC).isoformat() if object_type == "execution" else None
        return {
            "system": system,
            "object_type": object_type,
            "external_id": external_id,
            "version": version,
            "mode": mode,
            "occurred_at": current or "2026-10-28T08:00:00+00:00",
            "collected_at": current or "2026-10-28T08:01:00+00:00",
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


def _order_workorder(self, *, quantity="5", trial_quantity="1", contract=None, mode="internal"):
    p = self.create_project(mode=mode, **({"contract": contract} if contract else {}))
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
        trial_quantity=trial_quantity,
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


def _material_requirement(self, *, required="100", qualified="80", unit="kg", scale=3, scope="trial", mode="internal"):
    from datetime import UTC, datetime, timedelta

    p, order, wo, rev = self.order_workorder(quantity="5", mode=mode)
    self.grant(p["id"], "supply", ["supply"])
    self.grant(p["id"], "quality", ["quality"], ["inspection"])
    now = datetime.now(UTC)
    source = self.source(f"material-{uuid4()}", object_type="material_lot")
    lot = self.command(
        p["id"], "material.define", actor_name="supply",
        material_id="steel-1", lot_id="lot-1", owner_id="Customer 1",
        unit=unit, scale=scale, expiry=(now + timedelta(days=90)).date().isoformat(), source=source,
    )
    plan_source = self.source(f"plan-{uuid4()}", object_type="plan")
    plan_source.update(
        occurred_at=(now - timedelta(minutes=2)).isoformat(),
        collected_at=(now - timedelta(minutes=1)).isoformat(),
        cutoff=(now - timedelta(minutes=2)).isoformat(),
    )
    with self.db() as db:
        order_version = db.execute("SELECT source_version FROM order_lines WHERE id=?", (order["id"],)).fetchone()[0]
    plan = self.command(
        p["id"], "plan.receive", actor_name="planner", source=plan_source,
        input_revision_ids=[rev["id"]],
        input_order_versions=[{"order_line_id": order["id"], "version": order_version}],
        requirements=[{
            "work_order_id": wo["id"], "execution_scope": scope,
            "material_id": "steel-1", "owner_id": "Customer 1", "quantity": required, "unit": unit,
        }],
    )
    plan_detail = self.object(p["id"], "plan", plan["object_id"])
    requirement = {"id": plan_detail["requirement_ids"][0]}
    commitment = self.command(
        p["id"], "supply.commit", actor_name="supply", requirement_id=requirement["id"],
        type="customer", owner_id="Customer 1", quantity=required, unit=unit,
        original_due=(now + timedelta(days=1)).date().isoformat(),
        current_due=(now + timedelta(days=1)).date().isoformat(),
        source=self.source(f"promise-{uuid4()}", object_type="commitment"),
    )
    if qualified != "0":
        receipt = self.receive(p["id"], commitment["object_id"], quantity=qualified, lot_id=lot["object_id"])
        self.inspect(p["id"], receipt["object_id"], accepted=qualified, rejected="0")
    return p, requirement, {"id": commitment["object_id"], "lot_id": lot["object_id"], "work_order_id": wo["id"], "order_id": order["id"], "revision_id": rev["id"]}


def _receive(self, project_id, commitment_id, *, quantity, lot_id=None, source=None):
    if lot_id is None:
        lot_id = self.object(project_id, "commitment", commitment_id)["material_lot_ids"][0]
    return self.command(
        project_id, "supply.receive", actor_name="supply", commitment_id=commitment_id,
        material_lot_id=lot_id, quantity=quantity, unit="kg",
        source=source or self.source(f"receipt-{uuid4()}", object_type="receipt"),
    )


def _inspect(self, project_id, receipt_id, *, accepted, rejected):
    return self.command(
        project_id, "supply.inspect", actor_name="quality", receipt_id=receipt_id,
        accepted=accepted, rejected=rejected, evidence="IQC signed result",
    )


def _balance(self, project_id, requirement_id):
    return self.object(project_id, "requirement", requirement_id)["balance"]


WorkflowHarness.material_requirement = _material_requirement
WorkflowHarness.receive = _receive
WorkflowHarness.inspect = _inspect
WorkflowHarness.balance = _balance


def _executed_unit(self):
    """A real accepted unit for C1; business facts always use public actions."""
    from uuid import uuid4
    from .test_execution import running_execution

    p, _, units, _, event = running_execution(self)
    self.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=self.source(str(uuid4()), object_type="execution"),
        **event,
    )
    self.grant(
        p["id"],
        "quality",
        ["quality"],
        ["inspection", "disposition", "quality_release"],
    )
    return p, self.object(p["id"], "unit", units[0])


def _test(
    self, project_id, unit_id, *, measured, lower="4", upper="6", rework_order_id=None
):
    from datetime import UTC, datetime
    from uuid import uuid4

    unit = self.object(project_id, "unit", unit_id)
    source = self.source(str(uuid4()), object_type="test")
    now = datetime.now(UTC).isoformat()
    source.update(occurred_at=now, collected_at=now)
    result = self.command(
        project_id,
        "test.record",
        actor_name="quality",
        unit_id=unit_id,
        attempt=unit["test_total"] + 1,
        program_version="P1",
        limit_version="T1",
        firmware_version="F1",
        source=source,
        measurements=[
            dict(name="voltage", value=measured, unit="V", lower=lower, upper=upper)
        ],
        rework_order_id=rework_order_id,
    )
    return self.object(project_id, "test", result["object_id"])


def _rework(self, project_id, test_id):
    """Qualified repair and actual B3 execution; retest remains a separate action."""
    from datetime import UTC, datetime
    from uuid import uuid4

    test = self.object(project_id, "test", test_id)
    unit = self.object(project_id, "unit", test["unit_id"])
    nc = self.command(
        project_id,
        "nonconformance.open",
        actor_name="quality",
        test_id=test_id,
        defect="measured failure",
        evidence="failed measurement",
    )
    rw = self.command(
        project_id,
        "nonconformance.disposition",
        actor_name="quality",
        nonconformance_id=nc["object_id"],
        decision="rework",
        route_id="RW-1",
        route_steps=[dict(station="repair", instruction_version="RW-S1")],
        evidence="qualified repair route",
    )
    lot = unit["execution_events"][0]["material_uses"][0]["lot_id"]
    self.command(
        project_id,
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
        rework_order_id=rw["object_id"],
        occurred_at=datetime.now(UTC).isoformat(),
        source=self.source(str(uuid4()), object_type="execution"),
    )
    return self.object(project_id, "rework", rw["object_id"])


WorkflowHarness.executed_unit = _executed_unit
WorkflowHarness.test = _test
WorkflowHarness.rework = _rework


def _released_order(self, *, quantity="100", mode="internal"):
    """C2 success factory: every platform fact passes the public API."""
    from datetime import UTC, datetime
    from .test_execution import ready_for_trial

    p, wo, _, _ = ready_for_trial(
        self,
        quantity=quantity,
        trial_quantity=quantity,
        project_mode=mode,
        contract_override={
            "customer_release_required": False,
            "acceptance_required": True,
        },
    )
    units = []
    for offset in range(0, int(quantity), 50):
        units.extend(
            self.client()
            .get(f"{BASE}/projects/{p['id']}/objects/unit?limit=50&offset={offset}")
            .json()["items"]
        )
    self.grant(
        p["id"],
        "quality",
        ["quality"],
        ["inspection", "disposition", "quality_release"],
    )
    self.grant(p["id"], "warehouse", ["warehouse"])
    workorder = self.object(p["id"], "work_order", wo["id"])
    order = {"id": workorder["order_line_id"]}
    self.command(
        p["id"],
        "order.allocate",
        actor_name="planner",
        order_line_id=order["id"],
        work_order_id=wo["id"],
        quantity=quantity,
        unit="piece",
    )
    start = self.command(
        p["id"],
        "production.start",
        actor_name="production",
        work_order_id=wo["id"],
        mode="trial",
        unit_ids=[u["id"] for u in units],
        quantity=quantity,
    )
    self.command(
        p["id"],
        "exchange.dispatch",
        actor_name="production",
        exchange_id=start["exchange_id"],
    )
    lot = (
        self.client()
        .get(f"{BASE}/projects/{p['id']}/objects/material_lot?limit=1")
        .json()["items"][0]["id"]
    )
    for unit in units:
        detail = self.object(p["id"], "unit", unit["id"])
        self.command(
            p["id"],
            "execution.record",
            actor_name="production",
            source=self.source(str(uuid4()), object_type="execution"),
            work_order_id=wo["id"],
            sn=detail["sn"],
            station="assembly",
            route_version="S1",
            program_version="P1",
            firmware_version="F1",
            material_uses=[dict(lot_id=lot, quantity="0.001", unit="kg")],
            result="pass",
            occurred_at=datetime.now(UTC).isoformat(),
        )
        self.test(p["id"], unit["id"], measured="5")
    for actor, kind in [("production", "manufacturing"), ("quality", "quality")]:
        self.command(
            p["id"],
            "release.decide",
            actor_name=actor,
            kind=kind,
            unit_ids=[u["id"] for u in units],
            decision="approved",
            evidence="independent measured release",
        )
    return p, order, units


def _ship(
    self,
    project_id,
    order_id,
    unit_ids,
    *,
    expected_status=200,
    dispatch=True,
    **overrides,
):
    body = dict(
        order_line_id=order_id,
        unit_ids=unit_ids,
        boxes=[],
        quantity=str(len(unit_ids)),
        unit="piece",
    )
    body.update(overrides)
    result = self.command(
        project_id,
        "shipment.request",
        actor_name="warehouse",
        expected_status=expected_status,
        **body,
    )
    if expected_status != 200:
        return result
    if dispatch:
        self.command(
            project_id,
            "exchange.dispatch",
            actor_name="warehouse",
            exchange_id=result["exchange_id"],
        )
    return self.object(project_id, "shipment", result["object_id"])


def _sign_and_accept(self, project_id, shipment_id, *, quantity):
    from datetime import UTC, datetime

    for action, kind in [
        ("delivery.sign", "delivery_sign"),
        ("delivery.accept", "delivery_accept"),
    ]:
        source = self.source(str(uuid4()), object_type=kind)
        now = datetime.now(UTC).isoformat()
        source.update(occurred_at=now, collected_at=now)
        self.command(
            project_id,
            action,
            actor_name="warehouse",
            shipment_id=shipment_id,
            quantity=quantity,
            source=source,
            external_signatory="Customer receiver Alice",
            **({"issues": []} if kind == "delivery_accept" else {}),
        )


WorkflowHarness.released_order = _released_order
WorkflowHarness.ship = _ship
WorkflowHarness.sign_and_accept = _sign_and_accept
