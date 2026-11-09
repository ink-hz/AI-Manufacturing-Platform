#!/usr/bin/env python3
"""Prepare/serve a new isolated simulated OEM preview. No production configuration accepted."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import socket
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from seed_workflow_demo import Importer
from workflow_demo.oem_preview import populate

from manufacturing_platform import build_workflow_router

ROOT = Path(__file__).resolve().parents[1]
OWNER = "manufacturing-oem-preview-v1"
ASSETS = {
    "manufacturing.js": "text/javascript",
    "manufacturing.css": "text/css",
    "preview-renderer.js": "text/javascript",
    "preview.css": "text/css",
}
BASE_FILES = {
    "manifest.json",
    "seed.json",
    "workflow.db",
    "authority.db",
    "preview.lock",
    "handbook-metadata.json",
    "docs/manufacturing-system-handbook.md",
    *("webui/dist/" + name for name in ASSETS),
}
DB_SIDECARS = {
    name + suffix
    for name in ("workflow.db", "authority.db")
    for suffix in ("-wal", "-shm", "-journal")
}
DIRECTORIES = {"webui", "webui/dist", "docs"}


def write_json(path, value):
    # Root is already exclusively owned; atomic manifest publication never follows a link.
    temporary = path.with_name(".manifest-new")
    with temporary.open("x") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def safe_root(root):
    root = Path(root)
    if not root.is_absolute() or root != root.resolve() or root.is_symlink():
        raise ValueError("An absolute non-symlink preview directory is required")
    return root


def regular(path):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.getuid()
    ):
        raise ValueError("Owned regular file required: " + path.name)
    return path


def load_owned(root):
    root = safe_root(root)
    info = root.stat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise ValueError("Private owned preview directory required")
    manifest_path = regular(root / "manifest.json")
    if manifest_path.stat().st_mode & 0o077:
        raise ValueError("Private manifest required")
    manifest = json.loads(manifest_path.read_text())
    if (
        manifest.get("owner") != OWNER
        or manifest.get("directory") != str(root)
        or manifest.get("dataset", {}).get("mode") != "demo"
        or not manifest.get("complete")
    ):
        raise ValueError("Complete owned simulated preview manifest required")
    mock_directories, mock_files, guard_directory = set(), set(), None
    dataset_id = manifest["dataset"].get("id")
    if isinstance(dataset_id, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", dataset_id):
        from manufacturing_platform.workflow.integrations.catalog import SYSTEM_IDS

        scope = "mock-systems/" + dataset_id
        guard_directory = scope + "/guards"
        mock_directories = {"mock-systems", scope, guard_directory}
        mock_files = {
            scope + "/" + system + ".sqlite3" + suffix
            for system in SYSTEM_IDS
            for suffix in ("", "-wal", "-shm", "-journal")
        }
    for entry in root.rglob("*"):
        name = entry.relative_to(root).as_posix()
        if entry.is_symlink():
            raise ValueError("Preview links are forbidden")
        if entry.is_dir():
            if name not in DIRECTORIES | mock_directories:
                raise ValueError("Unexpected preview directory")
        else:
            allowed_guard = False
            if entry.parent.relative_to(root).as_posix() == guard_directory and entry.suffix == ".lock":
                try:
                    allowed_guard = str(UUID(entry.stem)) == entry.stem
                except ValueError:
                    pass
            if name not in BASE_FILES | DB_SIDECARS | mock_files and not allowed_guard:
                raise ValueError("Unexpected preview file")
            regular(entry)
    for name in BASE_FILES:
        regular(root / name)
    for name, digest in manifest["assets"].items():
        if (
            name not in ASSETS
            or hashlib.sha256((root / "webui/dist" / name).read_bytes()).hexdigest()
            != digest
        ):
            raise ValueError("Preview asset changed")
    if set(manifest["assets"]) != set(ASSETS):
        raise ValueError("Preview asset inventory incomplete")
    return manifest


def prepare(root, platform_root):
    root = safe_root(root)
    if root.exists():
        raise ValueError(
            "Preparation requires a new directory; existing data is never reseeded"
        )
    platform_root = Path(platform_root).resolve(strict=True)
    sources = {
        name: ROOT / "webui/dist" / name
        for name in ("manufacturing.js", "manufacturing.css")
    }
    for directory in (ROOT / "webui", ROOT / "webui/dist"):
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError(
                "A non-symlink build directory is required: " + str(directory)
            )
    for source in sources.values():
        if source.is_symlink() or not source.is_file():
            raise ValueError(
                "A non-symlink regular build file is required; "
                "build the business bundle first: cd webui && npm run build"
            )
    root.mkdir(mode=0o700)
    manifest = {
        "owner": OWNER,
        "directory": str(root),
        "complete": False,
        "created_at": datetime.now(UTC).isoformat(),
        "dataset": {
            "id": "oem-preview-" + uuid4().hex,
            "mode": "demo",
            "label": "【模拟】隔离相机与机器人验证",
        },
        "admin_id": str(uuid4()),
    }
    write_json(root / "manifest.json", manifest)
    try:
        (root / "preview.lock").touch(mode=0o600)
        for directory in ("webui", "webui/dist", "docs"):
            (root / directory).mkdir(mode=0o700)
        for name, source in sources.items():
            target = root / "webui/dist" / name
            target.write_bytes(source.read_bytes())
            target.chmod(0o600)
        document = ROOT / "docs/manufacturing-system-handbook.md"
        data = document.read_bytes()
        (root / "docs/manufacturing-system-handbook.md").write_bytes(data)
        write_json(
            root / "handbook-metadata.json",
            {
                "files": {
                    "docs/manufacturing-system-handbook.md": {
                        "updated_at": datetime.now(UTC).isoformat(),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                }
            },
        )
        build = subprocess.run(
            [
                "node",
                str(ROOT / "scripts/build_preview_renderer.mjs"),
                str(platform_root),
                str(root),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if build.returncode:
            raise ValueError("Renderer build failed: " + build.stderr[-4000:])
        manifest["renderer"] = json.loads(build.stdout)
        seed = Importer(
            workflow_db=str(root / "workflow.db"),
            authority_db=str(root / "authority.db"),
            dataset=manifest["dataset"],
            owner_ids=[manifest["admin_id"]],
            manifest=str(root / "seed.json"),
        )
        seed.manifest = {
            "config": seed.config,
            "started_at": datetime.now(UTC).isoformat(),
            "steps": {},
            "project_versions": {},
            "projects": [],
            "complete": False,
        }
        seed.checkpoint()
        manifest["examples"] = populate(seed)
        seed.manifest["complete"] = True
        seed.checkpoint()
        seed.verify()
        manifest["synthetic_subjects"] = [
            {"user_id": str(a.user_id), "display_name": a.display_name}
            for a in seed.actors.values()
        ]
        manifest["assets"] = {
            name: hashlib.sha256((root / "webui/dist" / name).read_bytes()).hexdigest()
            for name in ASSETS
        }
        manifest["complete"] = True
        write_json(root / "manifest.json", manifest)
        return load_owned(root)
    except Exception as exc:
        manifest["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        write_json(root / "manifest.json", manifest)
        raise


SHELL = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>【模拟】制造工作台本地预览</title><link rel="stylesheet" href="/assets/manufacturing.css"><link rel="stylesheet" href="/assets/preview.css"></head><body class="preview-shell"><div class="preview-notice">【模拟】隔离本地演示 · 合成本地管理员 · 无真实客户、员工会话、设备或ERP连接。数据仅在本预览目录保存。</div><main id="workbench"></main><script src="/assets/manufacturing.js"></script><script src="/assets/preview-renderer.js"></script><script>
(async()=>{try{const response=await fetch('/preview-bootstrap');if(!response.ok)throw new Error('预览启动失败');const options=await response.json();const renderer=PreviewMarkdown.createManufacturingMarkdownRenderer();const mounted=OrbbecManufacturing.mount(document.getElementById('workbench'),{...options,renderMarkdown:renderer.renderMarkdown});window.addEventListener('pagehide',()=>{mounted.unmount();renderer.unmount()},{once:true});}catch(error){document.getElementById('workbench').textContent=String(error);}})();
</script></body></html>"""


def build_app(root, port, *, actor_id=None):
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("An actual loopback port is required")
    root = safe_root(root)
    manifest = load_owned(root)
    host = f"127.0.0.1:{port}"
    origin = "http://" + host
    csrf = secrets.token_urlsafe(32)
    subjects = {s["user_id"]: s for s in manifest["synthetic_subjects"]}
    subjects[manifest["admin_id"]] = {
        "user_id": manifest["admin_id"],
        "display_name": "【模拟】本地预览管理员",
    }
    selected = manifest["admin_id"] if actor_id is None else str(actor_id)
    if selected not in subjects:
        raise ValueError("Owned preview synthetic actor required")
    actor = {
        **subjects[selected],
        "read_only": False,
        "configuration_admin": selected == manifest["admin_id"],
    }
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard(request, call_next):
        if request.headers.getlist("host") != [host]:
            response = JSONResponse(
                {"detail": "Exact preview Host required"}, status_code=403
            )
        elif request.method not in {"GET", "HEAD", "OPTIONS"} and (
            request.headers.getlist("origin") != [origin]
            or len(request.headers.getlist("x-csrf-token")) != 1
            or not secrets.compare_digest(request.headers.get("x-csrf-token", ""), csrf)
        ):
            response = JSONResponse(
                {"detail": "Preview Origin and CSRF required"}, status_code=403
            )
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    router = build_workflow_router(
        database_path=str(root / "workflow.db"),
        authority_database_path=str(root / "authority.db"),
        assets_dir=str(root / "webui/dist"),
        authenticate=lambda request, write=False: actor,
        resolve_subject=lambda uid: str(uid) in subjects,
        resolve_subject_profiles=lambda ids: [
            subjects[str(uid)] for uid in ids if str(uid) in subjects
        ],
        release="preview",
        dataset=manifest["dataset"],
    )
    app.include_router(router)
    access_endpoint = next(
        route.endpoint for route in router.routes if route.path.endswith("/access")
    )
    assets = {name: (root / "webui/dist" / name).read_bytes() for name in ASSETS}

    @app.get("/")
    def shell():
        return HTMLResponse(SHELL)

    @app.get("/preview-bootstrap")
    def bootstrap(request: Request):
        from manufacturing_platform.workflow.contracts import Actor

        request.state.workflow_actor = Actor.model_validate(actor)
        return {
            "bootstrap": access_endpoint(request),
            "csrfToken": csrf,
            "apiBase": "/api/v1/manufacturing",
            "readOnly": False,
            "user": {
                "displayName": actor["display_name"],
                "roleLabel": "【模拟】本地全权限" if actor["configuration_admin"] else "【模拟】项目角色权限",
            },
        }

    @app.get("/assets/{name}")
    def asset(name: str):
        if name not in assets:
            raise HTTPException(404, "Asset not found")
        return Response(assets[name], media_type=ASSETS[name])

    return app


def serve(root, port=0, *, actor_id=None):
    root = safe_root(root)
    load_owned(root)
    with (root / "preview.lock").open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))
            actual = sock.getsockname()[1]
            app = build_app(root, actual, actor_id=actor_id)
            print(
                json.dumps(
                    {
                        "url": f"http://127.0.0.1:{actual}",
                        "directory": str(root),
                        "simulated": True,
                    }
                ),
                flush=True,
            )
            uvicorn.Server(
                uvicorn.Config(
                    app, log_level="warning", access_log=False, proxy_headers=False
                )
            ).run(sockets=[sock])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "serve"])
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--platform-root", type=Path)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--actor-id", help="Owned preview synthetic subject; grants remain enforced")
    args = parser.parse_args()
    if args.action == "prepare":
        if args.platform_root is None:
            parser.error("--platform-root is required for renderer preparation")
        result = prepare(args.root, args.platform_root)
        print(
            json.dumps(
                {
                    "directory": result["directory"],
                    "dataset": result["dataset"],
                    "simulated": True,
                },
                ensure_ascii=False,
            )
        )
    else:
        serve(args.root, args.port, actor_id=args.actor_id)


if __name__ == "__main__":
    main()
