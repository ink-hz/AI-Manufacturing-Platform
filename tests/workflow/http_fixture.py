"""Disposable real HTTP host, executable only by tests. No runtime imports here."""

import argparse
import json
import secrets
import socket
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5
from datetime import datetime

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response

from manufacturing_platform import build_workflow_router
if __package__:
    from .scenarios.base import owned_run
else:
    from scenarios.base import owned_run


def build_app(root: Path):
    manifest = owned_run(root)
    path = root / "fixture.json"
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError("Private test dataset secret required")
    config = json.loads(path.read_text())
    if config.get("dataset_mode") != "test" or config.get("dataset_id") != manifest["dataset_id"] or manifest["dataset_mode"] != "test":
        raise ValueError("Only the explicit owned test dataset is allowed")
    if any((root / name).is_symlink() for name in ("workflow.db", "authority.db")):
        raise ValueError("Symlink test dataset refused")
    identities = {
        name: {
            "user_id": str(uuid5(NAMESPACE_URL, f"fixture:{config.get('seed', root.name)}:{name}")),
            "display_name": name,
            "read_only": False,
            "configuration_admin": name in {"owner", "admin"},
        }
        for name in (
            "owner",
            "engineering",
            "planner",
            "supply",
            "production",
            "quality",
            "warehouse",
            "outsider",
            "admin",
        )
    }
    sessions = {}
    inactive = set()
    clock = datetime.fromisoformat(config["business_clock"]) if config.get("business_clock") else None
    dataset_id = config.get("dataset_id", "http-" + root.name)
    dataset_label = config.get("dataset_label", "Disposable HTTP fixture")
    app = FastAPI()

    @app.post("/fixture/login")
    async def login(request: Request, response: Response):
        body = await request.json()
        if (
            not secrets.compare_digest(str(body.get("secret", "")), config["secret"])
            or body.get("name") not in identities
        ):
            raise HTTPException(401, "Invalid fixture credentials")
        session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        sessions[session] = (identities[body["name"]], csrf)
        response.set_cookie(
            "workflow_fixture", session, httponly=True, samesite="strict"
        )
        return {"csrf": csrf, "identity": identities[body["name"]]}

    def authenticate(request: Request, write=False):
        current = sessions.get(request.cookies.get("workflow_fixture", ""))
        if current is None or current[0]["display_name"] in inactive:
            raise HTTPException(401, "Fixture session required")
        identity, csrf = current
        if write and (
            request.headers.get("origin") != str(request.base_url).rstrip("/")
            or not secrets.compare_digest(request.headers.get("x-csrf-token", ""), csrf)
        ):
            raise HTTPException(403, "Fixture Origin and CSRF required")
        return identity

    @app.post("/fixture/revoke")
    async def revoke(request: Request):
        identity = authenticate(request, write=True)
        if not identity["configuration_admin"]:
            raise HTTPException(403, "Fixture owner required")
        body = await request.json()
        inactive.add(body["name"])
        return {"revoked": body["name"]}

    @app.post("/fixture/authority")
    async def authority(request: Request):
        authenticate(request, write=True)
        from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

        body = await request.json()
        if body.get("action") not in {"receive", "inspect", "customer_approval", "configure_fault", "balance", "operation_count", "snapshot", "submit"}:
            raise HTTPException(422, "Unsupported fixture source fact")
        adapter = MockAuthorityAdapter(str(root / "authority.db"), dataset_id, business_clock=(lambda: clock) if clock else None)
        if body["action"] == "submit":
            from manufacturing_platform.workflow.exchange_models import ExternalRequest
            from starlette.concurrency import run_in_threadpool
            return await run_in_threadpool(adapter.submit, ExternalRequest.model_validate(body["fields"]["request"]))
        return getattr(adapter, body["action"])(**body["fields"])

    @app.post("/fixture/network-fault")
    async def network_fault(request: Request):
        identity = authenticate(request, write=True)
        if not identity["configuration_admin"] or clock is None:
            raise HTTPException(403, "Owned clock-pinned fixture owner required")
        from uuid import UUID
        from manufacturing_platform.workflow.contracts import Actor
        from manufacturing_platform.workflow.service import WorkflowService
        from manufacturing_platform.workflow.store import WorkflowStore
        body = await request.json()
        if body.get("fault") != "timeout_after_commit":
            raise HTTPException(422, "Unsupported fixture fault")
        workflow = WorkflowService(WorkflowStore(str(root / "workflow.db"), str(root / "authority.db"), dict(id=dataset_id, mode="test", label=dataset_label), business_clock=lambda: clock), lambda uid: any(str(uid) == v["user_id"] for v in identities.values()))
        pid = UUID(body["project_id"])
        workflow.detail(Actor(**identity), pid)
        workflow.system_registry.source_store(body["system"]).configure_fault(pid, UUID(body["intent_id"]), body["fault"])
        return {"configured": True}

    @app.post("/fixture/network")
    async def network_fixture(request: Request):
        identity = authenticate(request, write=True)
        if not identity["configuration_admin"] or clock is None:
            raise HTTPException(403, "Owned clock-pinned fixture owner required")
        from uuid import UUID
        from manufacturing_platform.workflow.contracts import Actor
        from manufacturing_platform.workflow.service import WorkflowService
        from manufacturing_platform.workflow.store import WorkflowStore
        from manufacturing_platform.workflow.integrations.routing import assign_profile
        if __package__:
            from .integrations.support import MockRig
            from .integrations.network_scenarios import synchronize
        else:
            from integrations.support import MockRig
            from integrations.network_scenarios import synchronize
        body = await request.json()
        if body.get("scenario") not in {"empty", "supply", "execution"}:
            raise HTTPException(422, "Unsupported owned fixture scenario")
        rig = MockRig.__new__(MockRig)
        rig.now = clock
        rig.core = rig.network = True
        rig.root, rig.mode = root, "test"
        rig.project_id = UUID(body["project_id"])
        rig.actor = rig.admin = Actor(**identity)
        rig.workflow = WorkflowService(WorkflowStore(str(root / "workflow.db"), str(root / "authority.db"), dict(id=dataset_id, mode="test", label=dataset_label), business_clock=lambda: clock), lambda uid: any(str(uid) == v["user_id"] for v in identities.values()))
        rig.registry = rig.workflow.system_registry
        # Authorization precedes maintenance profile assignment; routing refuses
        # reassignment and any project that already has business operations.
        rig.workflow.detail(rig.actor, rig.project_id)
        with rig.workflow.store.transaction(write=True) as tx:
            assign_profile(tx, rig.project_id, "oem-network-v1")
        rig.grant(["project_owner", "planner", "engineering", "production", "warehouse", "quality", "supply"], ["inspection", "disposition", "quality_release", "readiness_verification"])
        refs = None
        if body["scenario"] == "supply":
            refs = rig.core_ready()
        elif body["scenario"] == "execution":
            refs = rig.start_ready()
        synchronize(rig)
        from fastapi.encoders import jsonable_encoder
        return jsonable_encoder(dict(project_id=rig.project_id, business_clock=clock, refs=vars(refs) if refs else None))

    app.include_router(
        build_workflow_router(
            database_path=str(root / "workflow.db"),
            authority_database_path=str(root / "authority.db"),
            assets_dir=config.get("assets_dir") or str(root),
            authenticate=authenticate,
            resolve_subject=lambda uid: any(
                str(uid) == v["user_id"] and v["display_name"] not in inactive for v in identities.values()
            ),
            resolve_subject_profiles=lambda ids: [
                {"user_id": v["user_id"], "display_name": v["display_name"]}
                for v in identities.values()
                if v["user_id"] in set(map(str, ids))
            ],
            release="fixture",
            business_clock=(lambda: clock) if clock else None,
            dataset={
                "id": dataset_id,
                "mode": "test",
                "label": dataset_label,
            },
        )
    )
    return app


def serve(root: Path):
    app = build_app(root)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    print(json.dumps({"port": sock.getsockname()[1]}), flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False)).run(
        sockets=[sock]
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    serve(parser.parse_args().root)
