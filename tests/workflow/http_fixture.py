"""Disposable real HTTP host, executable only by tests. No runtime imports here."""

import argparse
import json
import secrets
import socket
from pathlib import Path
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response

from manufacturing_platform import build_workflow_router


def serve(root: Path):
    config = json.loads((root / "fixture.json").read_text())
    identities = {
        name: {
            "user_id": str(uuid4()),
            "display_name": name,
            "read_only": False,
            "configuration_admin": name == "owner",
        }
        for name in (
            "owner",
            "engineering",
            "planner",
            "supply",
            "production",
            "quality",
            "warehouse",
        )
    }
    sessions = {}
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
        if current is None:
            raise HTTPException(401, "Fixture session required")
        identity, csrf = current
        if write and (
            request.headers.get("origin") != str(request.base_url).rstrip("/")
            or not secrets.compare_digest(request.headers.get("x-csrf-token", ""), csrf)
        ):
            raise HTTPException(403, "Fixture Origin and CSRF required")
        return identity

    @app.post("/fixture/authority")
    async def authority(request: Request):
        authenticate(request, write=True)
        from manufacturing_platform.workflow.adapters.mock import MockAuthorityAdapter

        body = await request.json()
        if body.get("action") not in {"receive", "inspect"}:
            raise HTTPException(422, "Unsupported fixture source fact")
        adapter = MockAuthorityAdapter(str(root / "authority.db"), "http-" + root.name)
        return getattr(adapter, body["action"])(**body["fields"])

    app.include_router(
        build_workflow_router(
            database_path=str(root / "workflow.db"),
            authority_database_path=str(root / "authority.db"),
            assets_dir=str(root),
            authenticate=authenticate,
            resolve_subject=lambda uid: any(
                str(uid) == v["user_id"] for v in identities.values()
            ),
            resolve_subject_profiles=lambda ids: [
                {"user_id": v["user_id"], "display_name": v["display_name"]}
                for v in identities.values()
                if v["user_id"] in set(map(str, ids))
            ],
            release="fixture",
            dataset={
                "id": "http-" + root.name,
                "mode": "test",
                "label": "Disposable HTTP fixture",
            },
        )
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    print(json.dumps({"port": sock.getsockname()[1]}), flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False)).run(
        sockets=[sock]
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    serve(parser.parse_args().root.resolve())
