"""Trusted extensions use the production registry, never shipped test actions."""

import logging
from typing import Literal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from manufacturing_platform.workflow import commands, contracts, queries
from manufacturing_platform.workflow.service import WorkflowService
from manufacturing_platform.workflow.store import WorkflowStore

from .conftest import BASE, USERS


def test_extension_contracts_exist_and_production_registry_contains_only_real_actions():
    assert hasattr(commands, "CommandRegistry")
    assert hasattr(commands, "CommandContext")
    assert hasattr(contracts, "MutationResult")
    assert hasattr(queries, "ObjectRegistry")
    assert hasattr(contracts, "DomainValue")
    assert set(commands.COMMAND_REGISTRY._entries) == {
        "project.stage",
        "mock_system.execute", "mock_system.query", "mock_system.retry", "integration.pull",
        "material_handoff.record", "material_handoff.receive", "material_handoff.resolve", "material_handoff.cancel",
        "authority.register", "authority.verify", "arrival.record", "arrival.match",
        "test_plan.publish", "test_run.start", "test_run.finish",
        "calibration.record", "calibration.confirm", "component.install", "component.remove", "unit.alias",
        "npi.open", "npi.review", "npi.trial", "npi.issue", "npi.resolve", "npi.approve",
        "asset.publish", "asset.apply", "asset.verify",
        "freeze.request", "rma.open", "capa.update", "capa.close",
        "shipment.request", "delivery.sign", "delivery.accept", "delivery.resolve_issue",
        "closure.record", "ownership.reconcile", "ownership.movement", "stock_basis.reconcile",
        "demand.record",
        "demand.review",
        "order.register",
        "order.change",
        "order.resolve_change",
        "order.allocate",
        "engineering.revision",
        "contract.agree",
        "engineering.handoff",
        "engineering.customer_approval",
        "work_order.register",
        "readiness.record",
        "material.define",
        "plan.receive",
        "supply.commit",
        "supply.receive",
        "supply.inspect",
        "reservation.request", "exchange.dispatch", "exchange.query",
        "source.pull", "source.import", "source.import_file", "exchange.reconcile",
        "unit.register", "production.start", "production.interrupt", "production.resume",
        "execution.record", "first_article.record",
        "eco.open", "eco.disposition", "eco.switch", "eco.close",
        "test.record", "nonconformance.open", "nonconformance.disposition", "rework.complete", "release.decide",
    }


def test_explicit_scope_required_and_must_match_path(workflow):
    p = workflow.create_project()
    body = {
        "operation_id": str(uuid4()),
        "expected_version": 1,
        "roles": ["planner"],
        "qualifications": [],
        "active": True,
        "evidence": "grant",
    }
    url = f"{BASE}/projects/{p['id']}/members/{USERS['planner']}"
    assert workflow.client().put(url, json=body).status_code == 422
    body["scope"] = {"kind": "project", "project_id": str(uuid4())}
    response = workflow.client().put(url, json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "SCOPE_MISMATCH"
    body["scope"]["project_id"] = p["id"]
    assert workflow.client().put(url, json=body).json()["scope"] == body["scope"]
    members = (
        workflow.client().get(f"{BASE}/projects/{p['id']}/members").json()["items"]
    )
    assert all(m["scope"] == body["scope"] for m in members)


def test_denials_are_bounded_structured_and_do_not_write_success(workflow, caplog):
    with caplog.at_level(
        logging.WARNING, logger="manufacturing_platform.workflow.security"
    ):
        r = workflow._client.post(
            BASE + "/projects",
            content="secret-body",
            headers={"cookie": "session=secret-cookie"},
        )
    assert r.status_code == 401
    assert not workflow.paths.domain.exists()
    assert len(caplog.records) == 1
    event = caplog.records[0].workflow_security
    assert event["status"] == 401
    assert event["route"] == BASE + "/projects"
    assert "secret" not in str(event)
    caplog.clear()
    p = workflow.create_project()
    with workflow.db() as db:
        before = db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
    with caplog.at_level(
        logging.WARNING, logger="manufacturing_platform.workflow.security"
    ):
        workflow.client("outsider").get(f"{BASE}/projects/{p['id']}")
        workflow.client().post(
            f"{BASE}/projects/{p['id']}/commands", json={"action": "secret" * 10000}
        )
    assert len(caplog.records) == 2
    assert all(len(str(r.workflow_security)) < 1024 for r in caplog.records)
    assert all("secret" not in str(r.workflow_security) for r in caplog.records)
    with workflow.db() as db:
        assert db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == before


def extension(workflow):
    class Rename(commands.WorkflowCommand):
        action: Literal["demand.record"]
        title: str
        fail: bool = False

    registry = commands.CommandRegistry()

    def mutate(tx, context, command):
        tx.execute(
            "UPDATE projects SET name=? WHERE id=?",
            (command.title, str(context.project_id)),
        )
        if command.fail:
            raise contracts.DomainError("PRECONDITION_FAILED", 409, "Rejected")
        return contracts.MutationResult(
            object_type=contracts.ObjectKind.demand, object_id=context.project_id
        )

    registry.register(
        Rename, roles={"planner"}, qualifications={"inspection"}, handler=mutate
    )
    store = WorkflowStore(
        str(workflow.paths.domain),
        str(workflow.paths.authority),
        {"id": "workflow-test", "mode": "test", "label": "Workflow test"},
    )
    service = WorkflowService(store, lambda uid: True, command_registry=registry)
    actor = contracts.Actor(
        user_id=USERS["planner"],
        display_name="planner",
        read_only=False,
        configuration_admin=False,
    )
    return registry, service, actor


def test_central_dispatch_atomic_replay_current_permissions_and_cas(workflow):
    assert hasattr(commands, "CommandRegistry")
    p = workflow.create_project()
    workflow.grant(p["id"], "planner", ["planner"], ["inspection"])
    registry, service, actor = extension(workflow)
    raw = {
        "action": "demand.record",
        "operation_id": str(uuid4()),
        "expected_version": 2,
        "title": "Changed",
    }
    value = registry.parse(raw)
    result = service.execute(actor, UUID(p["id"]), value)
    assert result.project_version == 3
    assert service.execute(actor, UUID(p["id"]), value).replayed is True
    with pytest.raises(contracts.DomainError, match="Operation ID"):
        service.execute(
            actor, UUID(p["id"]), registry.parse({**raw, "title": "Different"})
        )
    with pytest.raises(contracts.DomainError) as stale:
        service.execute(
            actor, UUID(p["id"]), registry.parse({**raw, "operation_id": str(uuid4())})
        )
    assert stale.value.code == "VERSION_CONFLICT"
    with pytest.raises(contracts.DomainError):
        service.execute(
            actor,
            UUID(p["id"]),
            registry.parse(
                {
                    **raw,
                    "operation_id": str(uuid4()),
                    "expected_version": 3,
                    "title": "Rollback",
                    "fail": True,
                }
            ),
        )
    assert service.detail(actor, UUID(p["id"])).name == "Changed"
    with workflow.db() as db:
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 3
    workflow.grant(p["id"], "planner", ["planner"], [])
    with pytest.raises(contracts.DomainError) as revoked:
        service.execute(actor, UUID(p["id"]), value)
    assert revoked.value.status == 403
    with pytest.raises(ValidationError):
        registry.parse({**raw, "unexpected": True})
    with pytest.raises(ValidationError):
        registry.parse({**raw, "operation_id": "bad"})
    with pytest.raises(contracts.DomainError):
        registry.parse({**raw, "action": "invented"})


def test_registered_typed_detail_and_dashboard_use_same_queries(workflow, monkeypatch):
    assert hasattr(queries, "ObjectRegistry")
    p = workflow.create_project()

    class Value(contracts.DomainValue):
        kind: Literal["demand"]
        title: str

    registry = queries.ObjectRegistry()

    def count(tx, project_id):
        return tx.execute(
            "SELECT COUNT(*) FROM projects WHERE id=?", (str(project_id),)
        ).fetchone()[0]

    def summaries(tx, project_id, limit, offset):
        rows = tx.execute(
            "SELECT * FROM projects WHERE id=? ORDER BY id LIMIT ? OFFSET ?",
            (str(project_id), limit, offset),
        ).fetchall()
        return [
            contracts.ObjectSummary(
                id=row["id"],
                project_id=row["id"],
                kind="demand",
                title=row["name"],
                state="recorded",
                version=row["version"],
            )
            for row in rows
        ]

    def detail(tx, project_id, object_id):
        if project_id != object_id:
            return None
        return contracts.ObjectDetail[Value](
            summary=summaries(tx, project_id, 1, 0)[0],
            value=Value(kind="demand", title="typed"),
            relations=[],
            evidence=[],
            history=[],
        )

    registry.register(
        contracts.ObjectKind.demand,
        Value,
        count=count,
        summaries=summaries,
        detail=detail,
    )
    _, service, actor = extension(workflow)
    service.object_registry = registry
    owner = actor.model_copy(update={"user_id": USERS["owner"]})
    result = service.object_detail(
        owner, UUID(p["id"]), contracts.ObjectKind.demand, UUID(p["id"])
    )
    from manufacturing_platform.workflow import service as service_module

    monkeypatch.setattr(service_module, "OBJECT_REGISTRY", registry)
    workflow.reopen()
    wire = workflow.client().get(f"{BASE}/projects/{p['id']}/objects/demand/{p['id']}")
    assert wire.status_code == 200
    assert wire.json()["value"] == {"kind": "demand", "title": "typed"}
    assert set(wire.json()) == {"summary", "value", "relations", "evidence", "history"}
    assert result.value.title == "typed"
    assert result.model_dump()["value"]["kind"] == "demand"
    board = service.dashboard(owner)
    assert board.counts == {contracts.ObjectKind.demand: 1}
    assert (
        board.cards
        == service.objects(owner, UUID(p["id"]), contracts.ObjectKind.demand).items
    )
    assert board.project_count == 1
    with pytest.raises(ValueError):
        registry.register(
            contracts.ObjectKind.order_line,
            Value,
            count=count,
            summaries=summaries,
            detail=detail,
        )
    assert service.dashboard(
        contracts.Actor(
            user_id=USERS["outsider"],
            display_name="",
            read_only=False,
            configuration_admin=False,
        )
    ).counts == {"demand": 0}


def test_http_uses_trusted_registry_and_unregistered_actions_remain_unsupported(
    workflow, monkeypatch
):
    from manufacturing_platform.workflow import service as service_module

    registry, _, _ = extension(workflow)
    monkeypatch.setattr(service_module, "COMMAND_REGISTRY", registry)
    workflow.reopen()
    p = workflow.create_project()
    workflow.grant(p["id"], "planner", ["planner"], ["inspection"])
    response = workflow.command(
        p["id"], "demand.record", actor_name="planner", title="HTTP rename"
    )
    assert response["project_version"] == 3
    assert (
        workflow.command(
            p["id"], "order.allocate", actor_name="planner", expected_status=422
        )["code"]
        == "UNSUPPORTED_ACTION"
    )
    workflow.grant(p["id"], "engineering", ["planner"])
    assert workflow.command(
        p["id"], "demand.record", actor_name="engineering",
        title="Unqualified ordinary member", expected_status=403,
    )["code"] == "FORBIDDEN"
    workflow.command(
        p["id"], "demand.record",
        title="Trusted administrator has all registered action qualifications",
    )
    response = workflow.client("outsider").post(
        f"{BASE}/projects/{p['id']}/commands", content="broken json"
    )
    assert response.status_code == 404
    with workflow.db() as db:
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 5


def test_atomic_rollback_when_success_audit_storage_fails(workflow, monkeypatch):
    import sqlite3

    p = workflow.create_project()
    workflow.grant(p["id"], "planner", ["planner"], ["inspection"])
    registry, service, actor = extension(workflow)
    save = service._save

    def fail_after_save(*args):
        save(*args)
        raise sqlite3.OperationalError("isolated audit failure")

    monkeypatch.setattr(service, "_save", fail_after_save)
    with pytest.raises(sqlite3.OperationalError):
        service.execute(
            actor,
            UUID(p["id"]),
            registry.parse(
                {
                    "action": "demand.record",
                    "operation_id": str(uuid4()),
                    "expected_version": 2,
                    "title": "Must roll back",
                }
            ),
        )
    assert service.detail(actor, UUID(p["id"])).name == "Camera"
    assert service.detail(actor, UUID(p["id"])).version == 2
    with workflow.db() as db:
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 2


def test_two_writers_only_one_can_apply_same_version(workflow):
    from concurrent.futures import ThreadPoolExecutor

    p = workflow.create_project()
    workflow.grant(p["id"], "planner", ["planner"], ["inspection"])
    registry, service, actor = extension(workflow)

    def write(title):
        try:
            return service.execute(
                actor,
                UUID(p["id"]),
                registry.parse(
                    {
                        "action": "demand.record",
                        "operation_id": str(uuid4()),
                        "expected_version": 2,
                        "title": title,
                    }
                ),
            ).project_version
        except contracts.DomainError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, ["First", "Second"]))
    assert set(results) == {3, "VERSION_CONFLICT"}
    with workflow.db() as db:
        assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 3


def test_project_stage_result_is_a_project_reference():
    result = contracts.MutationResult(object_type="project", object_id=uuid4())
    assert result.object_type == "project"


def test_registry_discriminates_multiple_strict_commands_and_rejects_invalid_extensions():
    class First(commands.WorkflowCommand):
        action: Literal["demand.record"]
        title: str

    class Second(commands.WorkflowCommand):
        action: Literal["demand.review"]
        approved: bool

    class Invented(commands.WorkflowCommand):
        action: Literal["invented.action"]

    registry = commands.CommandRegistry()
    handler = lambda tx, context, command: None
    registry.register(
        First, roles={"project_owner"}, qualifications=set(), handler=handler
    )
    registry.register(
        Second, roles={"quality"}, qualifications={"inspection"}, handler=handler
    )
    common = {"operation_id": str(uuid4()), "expected_version": 1}
    assert isinstance(
        registry.parse({**common, "action": "demand.review", "approved": True}), Second
    )
    with pytest.raises(ValidationError):
        registry.parse({**common, "action": "demand.review", "title": "wrong branch"})
    with pytest.raises(ValueError):
        registry.register(
            Invented, roles={"project_owner"}, qualifications=set(), handler=handler
        )
    with pytest.raises(ValueError):
        registry.register(
            First, roles={"project_owner"}, qualifications=set(), handler=handler
        )
