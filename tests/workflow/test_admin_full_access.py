"""Trusted global administrators use real facts without project grant seeding."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from manufacturing_platform.workflow.commands import COMMAND_REGISTRY

from .conftest import BASE, USERS
from .test_delivery import source_now


def snapshot(workflow):
    with workflow.db() as db:
        names = [
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        return {
            name: [
                tuple(r) for r in db.execute(f'SELECT * FROM "{name}" ORDER BY rowid')
            ]
            for name in names
        }


def demand(workflow, project_id):
    return {
        "action": "demand.record",
        "operation_id": str(uuid4()),
        "expected_version": workflow.client()
        .get(f"{BASE}/projects/{project_id}")
        .json()["version"],
        "kind": "firm",
        "product": "Camera",
        "quantity": "1",
        "unit": "piece",
        "due_date": "2026-12-01",
        "source": workflow.source(str(uuid4())),
    }


@pytest.mark.parametrize("actor", ["admin", "owner"])
def test_admin_sees_existing_and_new_projects_without_active_grants(workflow, actor):
    first = workflow.create_project()
    if actor == "owner":
        workflow.grant(first["id"], actor, [], active=False)
    client = workflow.client(actor)
    assert first["id"] in client.get(BASE + "/access").json()["project_ids"]
    second = workflow.create_project(name="Created later")
    assert set(client.get(BASE + "/access").json()["project_ids"]) == {
        first["id"],
        second["id"],
    }
    for project in (first, second):
        detail = client.get(f"{BASE}/projects/{project['id']}")
        assert detail.status_code == 200, detail.text
        # Resolve is contextual and appears only with a real unresolved issue.
        assert set(detail.json()["allowed_actions"]) == set(
            COMMAND_REGISTRY._entries
        ) - {"delivery.resolve_issue", "material_handoff.record", "material_handoff.receive",
             "material_handoff.resolve", "material_handoff.cancel",
             "expedite.open", "expedite.progress", "expedite.close"}
        assert detail.json()["release_kinds"] == [
            "manufacturing",
            "quality",
            "customer",
        ]
    if actor == "admin":
        with workflow.db() as db:
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM project_grants WHERE user_id=?",
                    (str(USERS[actor]),),
                ).fetchone()[0]
                == 0
            )
        assert all(
            row["user_id"] != str(USERS[actor])
            for row in client.get(f"{BASE}/projects/{first['id']}/members").json()[
                "items"
            ]
        )


def test_admin_real_write_audit_replay_cas_and_live_demotion(workflow):
    p = workflow.create_project()["id"]
    body = demand(workflow, p)
    url = f"{BASE}/projects/{p}/commands"
    client = workflow.client("admin")
    response = client.post(url, json=body)
    assert response.status_code == 200, response.text
    ident = response.json()["object_id"]
    accepted = snapshot(workflow)
    replay = client.post(url, json=body)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert snapshot(workflow) == accepted
    for changes, status in (
        ({"quantity": "2"}, 409),
        ({"operation_id": str(uuid4())}, 409),
    ):
        assert client.post(url, json={**body, **changes}).status_code == status
        assert snapshot(workflow) == accepted
    with workflow.db() as db:
        row = db.execute(
            "SELECT actor_id FROM audit_events WHERE object_id=?", (ident,)
        ).fetchone()
        assert row[0] == str(USERS["admin"])
    assert client.get(f"{BASE}/objects/demand").json()["items"][0]["id"] == ident
    assert client.get(f"{BASE}/projects/{p}/objects/demand/{ident}").status_code == 200
    assert client.get(BASE + "/dashboard").status_code == 200
    assert client.get(BASE + "/tasks").status_code == 200
    workflow.configuration_admins.remove("admin")
    assert client.get(f"{BASE}/projects/{p}").status_code == 404
    assert client.post(url, json=body).status_code == 404
    assert snapshot(workflow) == accepted
    workflow.grant(p, "admin", ["planner"])
    assert (
        "readiness.record"
        not in client.get(f"{BASE}/projects/{p}").json()["allowed_actions"]
    )
    assert client.post(url, json=demand(workflow, p)).status_code == 403


def test_admin_restrictions_and_nonadmin_scope_preserve_every_table(workflow):
    p = workflow.create_project()["id"]
    body = demand(workflow, p)
    client = workflow.client("admin")
    url = f"{BASE}/projects/{p}/commands"
    before = snapshot(workflow)
    workflow.read_only.add("admin")
    detail = client.get(f"{BASE}/projects/{p}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["allowed_actions"] == detail.json()["release_kinds"] == []
    assert client.post(url, json=body).status_code == 403
    workflow.read_only.clear()
    workflow.hard_stale.add("admin")
    assert client.post(url, json=body).status_code == 503
    workflow.hard_stale.clear()
    assert (
        client.post(url, json=body, headers={"x-csrf-token": "forged"}).status_code
        == 403
    )
    outsider = workflow.client("outsider")
    assert (
        outsider.post(
            url,
            json=body,
            headers={"X-Role": "platform_admin", "X-User-ID": str(USERS["admin"])},
        ).status_code
        == 404
    )
    assert outsider.get(BASE + "/access").json()["project_ids"] == []
    assert (
        client.post(url, json={**body, "configuration_admin": True}).status_code == 422
    )
    assert (
        client.post(url, json={**body, "action": "invented.action"}).status_code == 422
    )
    assert client.get(f"{BASE}/projects/{uuid4()}").status_code == 404
    assert (
        client.get(f"{BASE}/projects/{p}/objects/demand/{uuid4()}").status_code == 404
    )
    assert snapshot(workflow) == before


def test_admin_quality_qualification_release_variants_and_business_guards(workflow):
    p, unit = workflow.executed_unit()
    pid, uid = p["id"], unit["id"]
    client = workflow.client("admin")
    detail = client.get(f"{BASE}/projects/{pid}/objects/unit/{uid}")
    assert detail.status_code == 200, detail.text
    release = next(
        c
        for c in detail.json()["summary"]["action_capabilities"]
        if c["action"] == "release.decide"
    )
    assert set(release["variants"]) == {"manufacturing", "quality", "customer"}
    before = snapshot(workflow)
    workflow.command(
        pid,
        "release.decide",
        actor_name="admin",
        kind="quality",
        unit_ids=[uid],
        decision="approved",
        evidence="unmeasured",
        expected_status=409,
    )
    assert snapshot(workflow) == before
    source = workflow.source(str(uuid4()), object_type="test")
    source.update(
        occurred_at=datetime.now(UTC).isoformat(),
        collected_at=datetime.now(UTC).isoformat(),
    )
    measured = workflow.command(
        pid,
        "test.record",
        actor_name="admin",
        unit_id=uid,
        attempt=1,
        program_version="P1",
        limit_version="T1",
        firmware_version="F1",
        measurements=[
            {"name": "voltage", "value": "5", "unit": "V", "lower": "4", "upper": "6"}
        ],
        source=source,
    )
    workflow.command(
        pid,
        "first_article.record",
        actor_name="admin",
        work_order_id=unit["work_order_id"],
        unit_ids=[uid],
        test_ids=[measured["object_id"]],
        inspection_id="Admin measured FAI",
    )
    for kind in ("manufacturing", "quality", "customer"):
        extra = (
            {}
            if kind != "customer"
            else {
                "customer_id": "Customer 1",
                "revision_id": unit["revision_id"],
                "customer_revision": "C1",
                "external_signatory": "Customer QE",
                "method": "manual",
                "source": source_now(workflow, "customer_release"),
            }
        )
        workflow.command(
            pid,
            "release.decide",
            actor_name="admin",
            kind=kind,
            unit_ids=[uid],
            decision="approved",
            evidence="actual measured release",
            **extra,
        )
    assert (
        client.get(
            f"{BASE}/projects/{pid}/trace", params={"sn": unit["sn"]}
        ).status_code
        == 200
    )
    with workflow.db() as db:
        assert {
            r[0]
            for r in db.execute(
                "SELECT actor_id FROM quality_releases WHERE project_id=?", (pid,)
            )
        } == {str(USERS["admin"])}
        assert (
            db.execute(
                "SELECT COUNT(*) FROM project_grants WHERE user_id=?",
                (str(USERS["admin"]),),
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize("self_owner", [False, True])
def test_admin_delivery_responsibility_uses_real_profiles_and_can_resolve_other_owner(
    workflow, self_owner
):
    p, order, units = workflow.released_order(quantity="1")
    pid = p["id"]
    shipment = workflow.ship(pid, order["id"], [units[0]["id"]])
    workflow.command(
        pid,
        "delivery.sign",
        actor_name="admin",
        shipment_id=shipment["id"],
        quantity="1",
        source=source_now(workflow, "delivery_sign"),
        external_signatory="Customer receiver",
    )
    issue_owner = "admin" if self_owner else "quality"
    fields = {
        "shipment_id": shipment["id"],
        "quantity": "1",
        "source": source_now(workflow, "delivery_accept"),
        "external_signatory": "Customer QE",
        "issues": [
            {
                "title": "Packing evidence",
                "owner_id": str(USERS[issue_owner]),
                "required": True,
            }
        ],
    }
    before = snapshot(workflow)
    workflow.command(
        pid,
        "delivery.accept",
        actor_name="admin",
        expected_status=422,
        **{
            **fields,
            "issues": [
                {
                    "title": "Unscoped",
                    "owner_id": str(USERS["outsider"]),
                    "required": True,
                }
            ],
        },
    )
    assert snapshot(workflow) == before
    if self_owner:
        workflow.inactive.add("admin")
        workflow.command(
            pid, "delivery.accept", actor_name="admin", expected_status=409, **fields
        )
        assert snapshot(workflow) == before
        workflow.inactive.clear()
    workflow.command(pid, "delivery.accept", actor_name="admin", **fields)
    issue = workflow.object(pid, "shipment", shipment["id"])["issues"][0]
    assert issue["owner_name"] == ("Admin" if self_owner else "Quality Engineer")
    detail = workflow.client("admin").get(f"{BASE}/projects/{pid}").json()
    assert "delivery.resolve_issue" in detail["allowed_actions"]
    tasks = workflow.client("admin").get(BASE + "/tasks").json()["items"]
    assert any(
        t["target"]["id"] == shipment["id"]
        and "delivery.resolve_issue" in t["target"]["next_actions"]
        for t in tasks
    )
    workflow.command(
        pid,
        "delivery.resolve_issue",
        actor_name="admin",
        issue_id=issue["id"],
        evidence="Packing report received",
    )
    with workflow.db() as db:
        assert db.execute(
            "SELECT actor_id FROM acceptance_resolutions WHERE issue_id=?",
            (issue["id"],),
        ).fetchone()[0] == str(USERS["admin"])
        assert (
            db.execute(
                "SELECT COUNT(*) FROM project_grants WHERE user_id=?",
                (str(USERS["admin"]),),
            ).fetchone()[0]
            == 0
        )


def test_admin_exchange_and_inbound_source_policy_share_implicit_permissions(workflow):
    from .test_exchanges import stock

    p, requirement, supply = workflow.material_requirement(qualified="0")
    authority = stock(workflow, p, supply)
    for kind, external_id in (("receipt", "delivery-1"), ("iqc", "iqc-1")):
        workflow.command(
            p["id"],
            "source.pull",
            actor_name="admin",
            system="erp",
            object_type=kind,
            external_id=external_id,
        )
    assert workflow.balance(p["id"], requirement["id"])["qualified"] == "100"
    reservation = workflow.command(
        p["id"],
        "reservation.request",
        actor_name="admin",
        work_order_id=supply["work_order_id"],
        requirement_id=requirement["id"],
        lot_id=supply["lot_id"],
        quantity="80",
        unit="kg",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="admin",
        exchange_id=reservation["exchange_id"],
    )
    assert (
        workflow.object(p["id"], "exchange", reservation["exchange_id"])["phase"]
        == "accepted"
    )
    assert workflow.balance(p["id"], requirement["id"])["reserved"] == "80"
    assert authority.balance(supply["lot_id"]) == "20"
    with workflow.db() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM project_grants WHERE user_id=?",
                (str(USERS["admin"]),),
            ).fetchone()[0]
            == 0
        )


def test_admin_disposition_keeps_failed_measurement_and_scrap_blocks_release(workflow):
    p, unit = workflow.executed_unit()
    pid, uid = p["id"], unit["id"]
    source = workflow.source(str(uuid4()), object_type="test")
    source.update(
        occurred_at=datetime.now(UTC).isoformat(),
        collected_at=datetime.now(UTC).isoformat(),
    )
    measured = workflow.command(
        pid,
        "test.record",
        actor_name="admin",
        unit_id=uid,
        attempt=1,
        program_version="P1",
        limit_version="T1",
        firmware_version="F1",
        measurements=[
            {"name": "voltage", "value": "7", "unit": "V", "lower": "4", "upper": "6"}
        ],
        source=source,
    )
    assert workflow.object(pid, "test", measured["object_id"])["outcome"] == "fail"
    nc = workflow.command(
        pid,
        "nonconformance.open",
        actor_name="admin",
        test_id=measured["object_id"],
        defect="Measured over limit",
        evidence="Actual failed reading",
    )
    workflow.command(
        pid,
        "nonconformance.disposition",
        actor_name="admin",
        nonconformance_id=nc["object_id"],
        decision="scrap",
        evidence="Qualified disposition",
    )
    before = snapshot(workflow)
    workflow.command(
        pid,
        "release.decide",
        actor_name="admin",
        kind="quality",
        unit_ids=[uid],
        decision="approved",
        evidence="Scrap cannot pass",
        expected_status=409,
    )
    assert snapshot(workflow) == before
    with workflow.db() as db:
        assert db.execute(
            "SELECT actor_id FROM quality_dispositions WHERE project_id=?", (pid,)
        ).fetchone()[0] == str(USERS["admin"])
