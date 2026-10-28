"""Final-review grant replay and nonblocking HTTP regressions."""

import asyncio
import threading
from uuid import UUID, uuid4

import httpx

from manufacturing_platform.workflow.service import WorkflowService

from .conftest import BASE, USERS


def grant_body(pid, version=1):
    return {
        "operation_id": str(uuid4()),
        "expected_version": version,
        "scope": {"kind": "project", "project_id": pid},
        "roles": ["planner"],
        "qualifications": [],
        "active": True,
        "evidence": "Named grant instruction",
    }


def test_grant_replay_inactive_target_revocation_and_actor_authorization(
    workflow, monkeypatch
):
    pid = workflow.create_project()["id"]
    body = grant_body(pid)
    url = f"{BASE}/projects/{pid}/members/{USERS['planner']}"
    accepted = workflow.client().put(url, json=body)
    assert accepted.status_code == 200
    assert set(accepted.json()) == {"scope", "user_id", "roles", "qualifications", "active", "project_version"}
    workflow.inactive.add("planner")
    assert workflow.client().put(url, json=body).json() == accepted.json()
    changed = {**body, "evidence": "Changed content"}
    assert workflow.client().put(url, json=changed).status_code == 409
    revoke = {**grant_body(pid, 2), "active": False, "roles": []}
    assert workflow.client().put(url, json=revoke).status_code == 200
    invalid = grant_body(pid, 3)
    assert workflow.client().put(url, json=invalid).status_code == 422
    workflow.inactive.clear()
    assert workflow.client("planner").get(f"{BASE}/projects/{pid}").status_code == 404
    # Live actor project grant must precede historical replay.
    workflow.grant(pid, "owner", [], active=False)
    assert workflow.client().put(url, json=body).status_code == 404


def test_grant_canonical_replay_does_not_query_unavailable_directory(
    workflow, monkeypatch
):
    pid = workflow.create_project()["id"]
    body = grant_body(pid)
    url = f"{BASE}/projects/{pid}/members/{USERS['planner']}"
    accepted = workflow.client().put(url, json=body)
    original = WorkflowService.change_grant

    def unavailable(self, *args):
        self.resolve_subject = lambda _: (_ for _ in ()).throw(
            RuntimeError("directory offline")
        )
        return original(self, *args)

    monkeypatch.setattr(WorkflowService, "change_grant", unavailable)
    assert workflow.client().put(url, json=body).json() == accepted.json()


def test_grant_directory_wait_does_not_block_asgi_loop(workflow, monkeypatch):
    pid = workflow.create_project()["id"]
    original = WorkflowService.change_grant
    entered, release = threading.Event(), threading.Event()

    def held(self, *args):
        resolver = self.resolve_subject

        def resolve(uid):
            entered.set()
            assert release.wait(3), "resolver was not released by concurrent request"
            return resolver(uid)

        self.resolve_subject = resolve
        return original(self, *args)

    monkeypatch.setattr(WorkflowService, "change_grant", held)

    @workflow.app.get("/lightweight")
    async def lightweight():
        release.set()
        return {"ok": True}

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=workflow.app), base_url="http://test"
        ) as client:
            mutation = asyncio.create_task(
                client.put(
                    f"{BASE}/projects/{pid}/members/{USERS['planner']}",
                    json=grant_body(pid),
                    headers={
                        "x-test-actor": "owner",
                        "x-csrf-token": "trusted-test-csrf",
                    },
                )
            )
            assert await asyncio.to_thread(entered.wait, 2)
            assert (await client.get("/lightweight")).json() == {"ok": True}
            assert (await mutation).status_code == 200

    asyncio.run(check())
    with workflow.db() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM audit_events WHERE action='grant.change'"
            ).fetchone()[0]
            == 1
        )


def test_directory_result_wait_rechecks_actor_and_canonical_racing_acceptance(workflow):
    from concurrent.futures import ThreadPoolExecutor

    from manufacturing_platform.workflow.contracts import Actor, GrantChange
    from manufacturing_platform.workflow.store import WorkflowStore

    pid = workflow.create_project()["id"]
    body = grant_body(pid)
    value = GrantChange.model_validate(body)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def resolver(_uid):
        calls.append(True)
        if len(calls) == 1:
            entered.set()
            assert release.wait(3)
            raise RuntimeError("late directory outage")
        return True

    store = WorkflowStore(
        str(workflow.paths.domain),
        str(workflow.paths.authority),
        {"id": "workflow-test", "mode": "test", "label": "Workflow test"},
    )
    service = WorkflowService(store, resolver)
    actor = Actor(
        user_id=USERS["owner"],
        display_name="owner",
        configuration_admin=True,
        read_only=False,
    )
    with ThreadPoolExecutor() as pool:
        waiting = pool.submit(
            service.change_grant, actor, UUID(pid), USERS["planner"], value
        )
        assert entered.wait(2)
        accepted = service.change_grant(actor, UUID(pid), USERS["planner"], value)
        release.set()
        assert waiting.result(timeout=3) == accepted
    with workflow.db() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM audit_events WHERE action='grant.change'"
            ).fetchone()[0]
            == 1
        )
    assert set(accepted) == {
        "scope",
        "user_id",
        "roles",
        "qualifications",
        "active",
        "project_version",
    }


def test_cancelled_http_wait_cannot_duplicate_grant_mutation(workflow, monkeypatch):
    pid = workflow.create_project()["id"]
    body = grant_body(pid)
    url = f"{BASE}/projects/{pid}/members/{USERS['planner']}"
    original = WorkflowService.change_grant
    entered, release, completed = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )

    def held(self, *args):
        resolver = self.resolve_subject

        def resolve(uid):
            entered.set()
            assert release.wait(3)
            return resolver(uid)

        self.resolve_subject = resolve
        try:
            return original(self, *args)
        finally:
            completed.set()

    monkeypatch.setattr(WorkflowService, "change_grant", held)

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=workflow.app), base_url="http://test"
        ) as client:
            headers = {"x-test-actor": "owner", "x-csrf-token": "trusted-test-csrf"}
            task = asyncio.create_task(client.put(url, json=body, headers=headers))
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            release.set()
            assert await asyncio.to_thread(completed.wait, 2)
            assert (
                await client.put(url, json=body, headers=headers)
            ).status_code == 200

    asyncio.run(check())
    with workflow.db() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM audit_events WHERE action='grant.change'"
            ).fetchone()[0]
            == 1
        )
