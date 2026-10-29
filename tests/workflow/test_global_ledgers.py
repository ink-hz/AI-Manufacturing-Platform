"""Actor-scoped global reads preserve registry bounds and live authorization."""

from uuid import UUID, uuid4

import pytest

from manufacturing_platform.workflow import contracts
from manufacturing_platform.workflow.service import WorkflowService
from manufacturing_platform.workflow.store import WorkflowStore

from .conftest import BASE, USERS


def demand(workflow, pid, number):
    return workflow.command(
        pid,
        "demand.record",
        kind="firm",
        product="Camera",
        quantity="100",
        unit="piece",
        due_date="2026-12-01",
        source=workflow.source(number),
    )["object_id"]


def service(workflow):
    return WorkflowService(
        WorkflowStore(
            str(workflow.paths.domain),
            str(workflow.paths.authority),
            {"id": "workflow-test", "mode": "test", "label": "Workflow test"},
        ),
        lambda uid: True,
    )


def test_global_objects_visible_scopes_boundary_and_real_source(workflow):
    projects = sorted([workflow.create_project()["id"] for _ in range(3)])
    for i, pid in enumerate(projects):
        for n in range(3):
            demand(workflow, pid, f"{i}-{n}")
    for pid in projects[:2]:
        workflow.grant(pid, "planner", ["planner"])
    client = workflow.client("planner")
    expected = [
        item
        for pid in projects[:2]
        for item in client.get(f"{BASE}/projects/{pid}/objects/demand").json()["items"]
    ]
    response = client.get(BASE + "/objects/demand?limit=3&offset=2")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "items": expected[2:5],
        "total": 6,
        "limit": 3,
        "offset": 2,
    }
    assert response.json()["items"][0]["source"]["object_type"] == "demand"
    filtered = client.get(
        BASE + "/objects/demand", params={"project_id": projects[1]}
    ).json()
    assert filtered["items"] == expected[3:] and filtered["total"] == 3
    assert (
        client.get(
            BASE + "/objects/demand", params={"project_id": projects[2]}
        ).status_code
        == 404
    )
    assert client.get(BASE + "/objects/demand?offset=999").json()["items"] == []
    workflow.read_only.add("planner")
    assert all(
        not i["next_actions"] and not i["action_capabilities"]
        for i in client.get(BASE + "/objects/demand").json()["items"]
    )
    workflow.grant(projects[0], "planner", [], active=False)
    assert client.get(BASE + "/objects/demand").json()["total"] == 3
    # An administrator's explicit membership can be revoked without affecting others.
    workflow.grant(projects[2], "owner", [], active=False)
    assert workflow.client().get(BASE + "/objects/demand").json()["total"] == 6
    assert (
        workflow.client()
        .get(BASE + "/objects/demand", params={"project_id": projects[2]})
        .status_code
        == 404
    )


@pytest.mark.parametrize("path", ["/objects/demand", "/tasks"])
def test_empty_global_scopes_and_unauthorized_filter(workflow, path):
    pid = workflow.create_project()["id"]
    c = workflow.client("outsider")
    response = c.get(BASE + path)
    assert response.status_code == 200
    assert response.json()["items"] == [] and response.json()["total"] == 0
    assert c.get(BASE + path, params={"project_id": pid}).status_code == 404
    assert c.get(BASE + path, params={"project_id": str(uuid4())}).status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/objects/no-such-kind",
        "/objects/demand?limit=0",
        "/objects/demand?limit=201",
        "/objects/demand?offset=-1",
        "/objects/demand?project_id=invalid",
        "/tasks?limit=0",
        "/tasks?limit=201",
        "/tasks?offset=-1",
        "/tasks?limit=no",
        "/tasks?project_id=invalid",
    ],
)
def test_auth_precedes_global_validation(workflow, path):
    assert workflow._client.get(BASE + path).status_code == 401
    response = workflow.client().get(BASE + path)
    assert response.status_code == 422
    assert response.headers["cache-control"] == "private, no-store"


def test_registry_only_materializes_selected_cross_project_page(workflow, monkeypatch):
    projects = sorted([workflow.create_project()["id"] for _ in range(3)])
    for pid in projects:
        for n in range(3):
            demand(workflow, pid, f"{pid}-{n}")
    for pid in projects[:2]:
        workflow.grant(pid, "planner", ["planner"])
    svc = service(workflow)
    original_count, original_read = (
        svc.object_registry.count,
        svc.object_registry.summaries,
    )
    counts, reads, transactions = [], [], []

    def count(tx, pid, kind):
        counts.append(pid)
        transactions.append(tx)
        return original_count(tx, pid, kind)

    def read(tx, pid, kind, *, limit, offset):
        reads.append((pid, limit, offset))
        transactions.append(tx)
        return original_read(tx, pid, kind, limit=limit, offset=offset)

    monkeypatch.setattr(svc.object_registry, "count", count)
    monkeypatch.setattr(svc.object_registry, "summaries", read)
    actor = contracts.Actor(
        user_id=USERS["planner"],
        display_name="Planner",
        configuration_admin=True,
        read_only=False,
    )
    page = svc.ledger(actor, contracts.ObjectKind.demand, limit=3, offset=2)
    assert page.total == 6 and len(page.items) == 3
    assert counts == list(map(UUID, projects[:2]))
    assert reads == [(UUID(projects[0]), 1, 2), (UUID(projects[1]), 2, 0)]
    assert all(tx is transactions[0] for tx in transactions)
    reads.clear()
    assert svc.ledger(actor, contracts.ObjectKind.demand, offset=999).items == []
    assert reads == []


def test_global_tasks_match_actor_project_tasks_and_pagination(workflow):
    projects = sorted([workflow.order_workorder()[0]["id"] for _ in range(2)])
    for pid in projects:
        workflow.grant(pid, "planner", ["planner", "production"])
    private = workflow.order_workorder()[0]["id"]
    workflow.grant(private, "planner", [], active=False)
    client = workflow.client("planner")
    expected = [
        task
        for pid in projects
        for task in client.get(f"{BASE}/projects/{pid}").json()["tasks"]
    ]
    assert len(expected) >= 4
    response = client.get(BASE + "/tasks?limit=2&offset=1")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": expected[1:3],
        "total": len(expected),
        "limit": 2,
        "offset": 1,
        "truncated": False,
    }
    assert client.get(BASE + "/tasks?offset=999").json()["total"] == len(expected)
    filtered = client.get(BASE + "/tasks", params={"project_id": projects[1]}).json()
    assert all(t["target"]["project_id"] == projects[1] for t in filtered["items"])
    workflow.read_only.add("planner")
    assert client.get(BASE + "/tasks").json() == {
        "items": [],
        "total": 0,
        "limit": 50,
        "offset": 0,
        "truncated": False,
    }


def test_global_tasks_reports_underlying_bound_not_pagination_as_truncation(workflow):
    pid = workflow.create_project()["id"]
    did = demand(workflow, pid, "bounded-tasks")
    for dimension in ("technical", "material", "capacity", "commercial", "quality"):
        workflow.command(
            pid,
            "demand.review",
            demand_id=did,
            dimension=dimension,
            decision="approved",
            evidence="reviewed",
        )
    for n in range(51):
        workflow.command(
            pid,
            "order.register",
            demand_id=did,
            source=workflow.source(f"order-{n}", object_type="order_line"),
            quantity="1",
            unit="piece",
            due_date="2026-12-01",
        )
    response = workflow.client().get(BASE + "/tasks?limit=3&offset=49")
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["total"] == 50 and len(value["items"]) == 1
    assert value["truncated"] is True
    assert workflow.client().get(BASE + "/tasks?offset=999").json()["truncated"] is True


def test_assigned_source_tasks_preserve_actual_owner_and_role_capabilities(workflow):
    from .test_exchanges import act, reserve, stock

    p, _, supply, intent = reserve(workflow)
    authority = stock(workflow, p, supply)
    authority.configure_fault("wrong_unit")
    act(workflow, p, intent)
    workflow.grant(p["id"], "production", ["planner"])
    assigned = workflow.client("planner").get(BASE + "/tasks").json()
    source_tasks = [t for t in assigned["items"] if t["category"] == "source"]
    assert len(source_tasks) == 1
    assert source_tasks[0]["owner_id"] == str(USERS["planner"])
    assert source_tasks[0]["owner_name"] == "planner"
    assert source_tasks[0]["target"]["id"] == intent["exchange_id"]
    other = workflow.client("production").get(BASE + "/tasks").json()
    assert not any(t["category"] == "source" for t in other["items"])
    assert assigned["truncated"] is False
