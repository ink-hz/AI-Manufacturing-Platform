"""Real loopback HTTP; synthetic sessions/transports, real host policy and grants."""

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from threading import Event
from time import monotonic
from uuid import UUID, uuid4

import httpx
import pytest

BASE = "/api/v1/manufacturing/workflow"
MEMBER = UUID("00000000-0000-4000-8000-000000000006")
OWNER = UUID("00000000-0000-4000-8000-000000000001")
OUTSIDER = UUID("00000000-0000-4000-8000-000000000008")
PARAMS = {"start": "2026-11-09T00:00:00Z", "end": "2026-11-10T00:00:00Z"}


def serve(directory, project_id, port, configured):
    """Child process fixture. No real provider, SDK, or external source is contacted."""
    from datetime import UTC, datetime
    from io import BytesIO

    import uvicorn
    from app.control_plane.authorization import AuthorizationService
    from app.control_plane.middleware import IdentitySecurityMiddleware
    from app.control_plane.models import AuthContext, IdentityMode, Role
    from app.manufacturing import authorize_workflow_identity
    from fastapi import FastAPI

    from manufacturing_platform import build_workflow_router
    from manufacturing_platform.production_tools.contracts import (
        EvidenceObject,
        ProductionToolsConfig,
        SourceBinding,
    )
    from manufacturing_platform.production_tools.source import NativeProductionSource

    class Auth:
        mode = IdentityMode.PRODUCTION
        route_prefix = "/"
        cookie_name = "socket-session"
        csrf_cookie_name = "socket-csrf"
        public_base_url = "https://agent.example.test"

        def authenticate(self, token):
            contexts = {
                "owner": (OWNER, Role.PLATFORM_OWNER, False),
                "member": (MEMBER, Role.MEMBER, False),
                "readonly": (MEMBER, Role.MANAGEMENT_VIEWER, False),
                "outsider": (OUTSIDER, Role.MEMBER, False),
            }
            if token in contexts:
                uid, role, stale = contexts[token]
                return AuthContext(uid, role, UUID(int=123), stale), "socket-csrf"
            return None

    class Grants:
        def permits(self, *args):
            return False

    calls = directory / "calls.json"
    calls.write_text("[]")

    class Reader:
        def select(self, statement):
            history = json.loads(calls.read_text())
            history.append(statement.name)
            calls.write_text(json.dumps(history))
            if statement.name.endswith("_statistics"):
                return [
                    {
                        "records": 2,
                        "distinct_sn": 1,
                        "pass_records": 2,
                        "fail_records": 0,
                    }
                ]
            if statement.name == "evidence_object":
                return [
                    {
                        "id": 1,
                        "projuectid": 10001,
                        "del": 0,
                        "url": "https://example.invalid/logs/10001/test.log",
                    }
                ]
            if statement.backend == "mysql":
                return [
                    {"id": i, "projuectid": 10001, "del": 0, "name": "synthetic"}
                    for i in (2, 1)
                ]
            duplicate = {
                "projuectid": "10001",
                "sn": "synthetic",
                "status": "1",
                "timestamp": datetime(2026, 11, 9, tzinfo=UTC),
            }
            return [duplicate.copy(), duplicate.copy()]

    class Objects:
        def open(self, key, *, max_bytes):
            assert key == "logs/10001/test.log"
            return EvidenceObject(BytesIO(b"synthetic evidence"), 18, "test.log")

    source = NativeProductionSource(
        Reader(),
        Reader(),
        Objects(),
        allowed_object_host="example.invalid",
        clock=lambda: datetime.now(UTC),
    )
    binding = SourceBinding(
        "workflow-test", UUID(project_id), "synthetic", "10001", "v1", "logs/10001/"
    )
    config = (
        ProductionToolsConfig(
            source, {binding.project_id: binding}, str(directory / "snapshots.db")
        )
        if configured
        else None
    )
    app = FastAPI()
    app.include_router(
        build_workflow_router(
            database_path=str(directory / "domain.db"),
            authority_database_path=str(directory / "authority.db"),
            assets_dir=str(directory),
            authenticate=authorize_workflow_identity,
            resolve_subject=lambda uid: uid in {OWNER, MEMBER, OUTSIDER},
            release="socket-test",
            dataset={"id": "workflow-test", "mode": "test", "label": "Workflow test"},
            production_tools=config,
        )
    )
    app.add_middleware(
        IdentitySecurityMiddleware,
        auth=Auth(),
        authorization=AuthorizationService(Grants()),
        routes=app.routes,
        public_assets=frozenset(),
    )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error", access_log=False)


class SocketHost:
    def __init__(self, directory, project_id, configured):
        platform = os.environ.get("TEST_PLATFORM_SOURCE_ROOT")
        if not platform:
            pytest.fail(
                "TEST_PLATFORM_SOURCE_ROOT must select the isolated host checkout"
            )
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.base = f"http://127.0.0.1:{port}"
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                (
                    str(Path(platform) / "backend"),
                    str(Path(__file__).parents[2] / "src"),
                )
            ),
        }
        self.log = (directory / "socket-process.log").open("w+")
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                str(directory),
                project_id,
                str(port),
                str(int(configured)),
            ],
            env=env,
            stdout=self.log,
            stderr=self.log,
        )
        self.client = httpx.Client(base_url=self.base, timeout=3, trust_env=False)
        try:
            deadline = monotonic() + 15
            while monotonic() < deadline:
                assert self.process.poll() is None, "synthetic socket process exited"
                try:
                    if self.request("GET", "/access", actor=None).status_code == 401:
                        return
                except httpx.TransportError:
                    pass
                Event().wait(min(0.03, max(0, deadline - monotonic())))
            raise AssertionError("synthetic socket process readiness timeout")
        except BaseException:
            self.close()
            raise

    def request(self, method, path, *, actor="owner", **kwargs):
        headers = {
            "Origin": "https://agent.example.test",
            "X-CSRF-Token": "socket-csrf",
        }
        if actor:
            headers["Cookie"] = f"socket-session={actor}; socket-csrf=socket-csrf"
        return self.client.request(method, BASE + path, headers=headers, **kwargs)

    def close(self):
        self.client.close()
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.log.close()


def test_real_socket_native_reads_live_grants_and_unconfigured_isolation(workflow):
    # Setup uses real workflow project creation; all acceptance reads and grant
    # transitions below use HTTP to a separate uvicorn process, never TestClient.
    project = workflow.create_project()
    pid = project["id"]
    directory = workflow.paths.domain.parent
    host = SocketHost(directory, pid, True)
    tools = f"/projects/{pid}/production-tools"
    try:
        assert host.request("GET", tools + "/status", actor=None).status_code == 401
        assert (
            host.request("GET", tools + "/status", actor="outsider").status_code == 404
        )
        assert host.request("GET", tools + "/status").json()["configured"] is True

        def grant(active):
            version = host.request("GET", f"/projects/{pid}").json()["version"]
            result = host.request(
                "PUT",
                f"/projects/{pid}/members/{MEMBER}",
                json={
                    "operation_id": str(uuid4()),
                    "expected_version": version,
                    "scope": {"kind": "project", "project_id": pid},
                    "roles": ["quality"] if active else [],
                    "qualifications": [],
                    "active": active,
                    "evidence": "Synthetic socket grant",
                },
            )
            assert result.status_code == 200, result.text

        grant(True)
        for actor in ("member", "readonly"):
            assert (
                host.request("GET", tools + "/status", actor=actor).status_code == 200
            )
        history = lambda: json.loads((directory / "calls.json").read_text())
        for suffix, params in (
            ("/observations", {**PARAMS, "kind": "production"}),
            ("/catalog/software", {}),
            ("/evidence", PARAMS),
            ("/statistics", {**PARAMS, "kind": "stopover"}),
        ):
            before = history()
            assert (
                host.request(
                    "GET", tools + suffix, actor="outsider", params=params
                ).status_code
                == 404
            )
            assert history() == before
            response = host.request(
                "GET", tools + suffix, actor="member", params=params
            )
            assert response.status_code == 200, response.text
            assert "no-store" in response.headers["cache-control"]
            page = response.json()
            snapshot = tools + "/snapshots/" + page["snapshot_id"]
            assert host.request("GET", snapshot, actor="readonly").json() == page
            if suffix == "/observations":
                assert (
                    page["captured_count"] == 2 and page["items"][0] == page["items"][1]
                )
                retained_snapshot = snapshot
            if suffix == "/statistics":
                assert page["items"][0]["consistency"] == "single_query"
        before = history()
        assert (
            host.request(
                "GET", tools + "/evidence/1/content", actor="outsider"
            ).status_code
            == 404
        )
        assert history() == before
        evidence = host.request("GET", tools + "/evidence/1/content", actor="readonly")
        assert evidence.status_code == 200 and evidence.content == b"synthetic evidence"
        assert evidence.headers["x-content-type-options"] == "nosniff"
        assert "no-store" in evidence.headers["cache-control"]
        assert (
            host.request(
                "GET", tools + "/catalog/software", params={"cap": 1}
            ).status_code
            == 422
        )
        assert host.request("POST", tools + "/status", json={}).status_code in (
            403,
            404,
            405,
        )
        assert host.request("GET", tools + "/unknown").status_code in (403, 404)
        grant(False)
        assert host.request("GET", retained_snapshot, actor="member").status_code == 404
        assert host.request("GET", f"/projects/{pid}").status_code == 200
    finally:
        host.close()
    host = SocketHost(directory, pid, False)
    try:
        assert host.request("GET", tools + "/status").json()["configured"] is False
        assert host.request("GET", tools + "/catalog/software").status_code == 503
        assert host.request("GET", f"/projects/{pid}").status_code == 200
        assert json.loads((directory / "calls.json").read_text()) == []
    finally:
        host.close()


if __name__ == "__main__":
    serve(Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]), bool(int(sys.argv[4])))
