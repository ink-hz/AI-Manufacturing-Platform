"""Owned demo startup and strict host/origin/CSRF boundary, without employee sessions."""

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
PLATFORM = Path(
    os.environ.get(
        "TEST_PLATFORM_SOURCE_ROOT", "/Users/neo/Developer/work/AI-Agent-Platform"
    )
)


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    import preview_manufacturing as preview

    root = tmp_path_factory.mktemp("preview-parent") / "demo"
    result = preview.prepare(root, PLATFORM)
    return preview, root, result


def test_prepare_refuses_unowned_paths_before_writes(tmp_path):
    import preview_manufacturing as preview

    target = tmp_path / "existing"
    target.mkdir()
    sentinel = target / "workflow.db"
    sentinel.write_bytes(b"user-owned")
    with pytest.raises(ValueError):
        preview.prepare(target, PLATFORM)
    assert sentinel.read_bytes() == b"user-owned"
    linked = tmp_path / "linked"
    linked.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError):
        preview.prepare(linked, PLATFORM)
    assert sorted(p.name for p in target.iterdir()) == ["workflow.db"]


def test_prepared_demo_and_guarded_real_commands(prepared):
    preview, root, manifest = prepared
    app = preview.build_app(root, 8765)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        shell = client.get("/")
        assert shell.status_code == 200 and "【模拟】" in shell.text
        assert "PreviewMarkdown.createManufacturingMarkdownRenderer" in shell.text
        assert "OrbbecManufacturing.mount" in shell.text
        assert shell.headers["cache-control"] == "private, no-store"
        bootstrap = client.get("/preview-bootstrap").json()
        token = bootstrap["csrfToken"]
        assert bootstrap["bootstrap"]["configuration_admin"]
        assert bootstrap["bootstrap"]["dataset"]["mode"] == "demo"
        base = "/api/v1/manufacturing/workflow"
        projects = client.get(base + "/projects").json()["items"]
        assert len(projects) == 2 and all("【模拟】" in p["name"] for p in projects)
        pid = manifest["examples"]["robot"]["project_id"]

        def body():
            version = client.get(base + "/projects/" + pid).json()["version"]
            return {
                "action": "asset.verify",
                "operation_id": str(uuid4()),
                "expected_version": version,
                "asset_use_id": manifest["examples"]["robot"]["asset_use_id"],
                "decision": "pass",
                "evidence": "【模拟】preview target inspection",
            }

        path = base + "/projects/" + pid + "/commands"
        for headers in (
            {},
            {"origin": "https://evil.example", "x-csrf-token": token},
            {"origin": "http://127.0.0.1:8765"},
            {"origin": "http://127.0.0.1:8765", "x-csrf-token": "wrong"},
        ):
            assert client.post(path, json=body(), headers=headers).status_code == 403
        assert (
            client.post(
                path,
                json=body(),
                headers={"origin": "http://127.0.0.1:8765", "x-csrf-token": token},
            ).status_code
            == 200
        )
        for host in (
            "evil.example",
            "localhost:8765",
            "127.0.0.1:9999",
            "127.0.0.1:8765.evil",
        ):
            response = client.get("/", headers={"host": host})
            assert (
                response.status_code == 403
                and response.headers["cache-control"] == "private, no-store"
            )
        for path in (
            "/fixture/login",
            "/fixture/authority",
            "/reset",
            "/docs",
            "/openapi.json",
            "/assets/workflow.db",
            "/assets/../manifest.json",
        ):
            assert client.get(path).status_code == 404
        for name in (
            "manufacturing.js",
            "manufacturing.css",
            "preview-renderer.js",
            "preview.css",
        ):
            assert client.get("/assets/" + name).status_code == 200
        css = client.get("/assets/preview.css").text
        assert ".article-markdown" in css
        import re

        assert not re.search(
            r"(?:^|[\n}])\s*\.(?:article-markdown|article-table-scroll|mermaid-)", css
        ), "All copied renderer selectors must be scoped"
        assert client.get(base + "/handbook").status_code == 200
        assert (
            client.get(base + "/assets/manifest.json?release=preview").status_code
            == 404
        )
    # Reopen retains current data; no seeding/reset occurs.
    reopened = preview.load_owned(root)
    assert reopened["dataset"] == manifest["dataset"]
    assert root.stat().st_mode & 0o077 == 0
    assert (root / "manifest.json").stat().st_mode & 0o077 == 0
    assert manifest["renderer"]["source"].endswith("/src/manufacturingMarkdown.tsx")
    assert len(manifest["renderer"]["sha256"]) == 64


def test_owned_root_rejects_added_links_and_changed_manifest(prepared, tmp_path):
    preview, root, manifest = prepared
    target = tmp_path / "sentinel"
    target.write_text("unchanged")
    link = root / "unexpected"
    link.symlink_to(target)
    try:
        with pytest.raises(ValueError):
            preview.build_app(root, 8765)
    finally:
        link.unlink()
    old = (root / "manifest.json").read_bytes()
    try:
        (root / "manifest.json").write_text(
            json.dumps({**manifest, "directory": str(tmp_path)})
        )
        with pytest.raises(ValueError):
            preview.build_app(root, 8765)
    finally:
        (root / "manifest.json").write_bytes(old)
    assert target.read_text() == "unchanged"


def test_cli_socket_host_uses_guarded_business_router(prepared):
    import select
    import subprocess
    import time
    import urllib.error
    import urllib.request

    preview, root, manifest = prepared
    process = subprocess.Popen(
        [sys.executable, str(Path(preview.__file__)), "serve", "--root", str(root)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert select.select([process.stdout], [], [], 15)[0], "preview startup timeout"
        line = process.stdout.readline()
        assert line, process.stderr.read()
        url = json.loads(line)["url"]

        def request(path, data=None, headers=None):
            payload = json.dumps(data).encode() if data is not None else None
            req = urllib.request.Request(
                url + path,
                data=payload,
                headers={"content-type": "application/json", **(headers or {})},
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as exc:
                return exc.code, json.load(exc)

        deadline = time.monotonic() + 10
        while True:
            try:
                status, bootstrap = request("/preview-bootstrap")
                break
            except urllib.error.URLError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.025)
        assert status == 200
        path = "/api/v1/manufacturing/workflow/projects"
        data = {**manifest["examples"]["future_project"], "operation_id": str(uuid4())}
        assert request(path, data)[0] == 403
        status, created = request(
            path, data, {"origin": url, "x-csrf-token": bootstrap["csrfToken"]}
        )
        assert status == 200 and created["name"].startswith("【模拟】")
        assert request(path, headers={"host": "evil.example"})[0] == 403
        assert (
            request(
                "/fixture/authority",
                {},
                {"origin": url, "x-csrf-token": bootstrap["csrfToken"]},
            )[0]
            == 404
        )
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()


def test_exact_renderer_bundle_renders_gfm_and_releases_owned_roots(prepared):
    import subprocess

    preview, root, _ = prepared
    script = r"""
const {createRequire}=require('node:module');
const requireUI=createRequire(process.argv[1]+'/webui/package.json');
const {JSDOM}=requireUI('jsdom');
const fs=require('node:fs');
const dom=new JSDOM('<!doctype html><body><div id="article"></div></body>',{runScripts:'dangerously',url:'http://127.0.0.1:8765'});
dom.window.eval(fs.readFileSync(process.argv[2]+'/webui/dist/preview-renderer.js','utf8'));
(async()=>{
const renderer=dom.window.PreviewMarkdown.createManufacturingMarkdownRenderer();
const node=dom.window.document.getElementById('article');
const first=renderer.renderMarkdown(node,{markdown:'# Handbook\n\n| Name | State |\n| --- | --- |\n| Camera | Simulated |\n\n```js\nconst value = 1;\n```'});
await new Promise(r=>setTimeout(r,80));
if(!node.querySelector('h1')||!node.querySelector('table')||!node.querySelector('pre code'))throw Error('Exact renderer must render heading/table/code');
const second=renderer.renderMarkdown(node,{markdown:'## Replacement'});
first.unmount();
await new Promise(r=>setTimeout(r,40));
if(node.querySelector('h2')?.textContent!=='Replacement')throw Error('Old handle cleared new owned root');
second.unmount();renderer.unmount();
if(node.children.length)throw Error('Renderer owned child leaked');
dom.window.close();
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run(
        [
            "node",
            "-e",
            script,
            str(Path(preview.__file__).resolve().parents[1]),
            str(root),
        ],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_allowed_database_cannot_be_a_symlink_or_hardlink(prepared, tmp_path):
    preview, root, _ = prepared
    database = root / "workflow.db"
    held = tmp_path / "held-workflow.db"
    database.rename(held)
    before = held.read_bytes()
    try:
        database.symlink_to(held)
        with pytest.raises(ValueError):
            preview.build_app(root, 8765)
        database.unlink()
        os.link(held, database)
        with pytest.raises(ValueError):
            preview.build_app(root, 8765)
        database.unlink()
        assert held.read_bytes() == before
    finally:
        database.unlink(missing_ok=True)
        held.rename(database)


def test_failed_preparation_is_preserved_and_never_auto_reset(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import preview_manufacturing as preview

    root = tmp_path / "failed-demo"
    monkeypatch.setattr(
        preview.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stderr="deliberate renderer failure"
        ),
    )
    with pytest.raises(ValueError, match="Renderer build failed"):
        preview.prepare(root, PLATFORM)
    failed = (root / "manifest.json").read_bytes()
    assert json.loads(failed)["complete"] is False
    assert not (root / "workflow.db").exists()
    with pytest.raises(ValueError, match="new directory"):
        preview.prepare(root, PLATFORM)
    assert (root / "manifest.json").read_bytes() == failed
    with pytest.raises(ValueError, match="Complete owned"):
        preview.build_app(root, 8765)
