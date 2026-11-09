"""Owned demo startup and strict host/origin/CSRF boundary, without employee sessions.

The three renderer/demo/socket integration tests opt in through
TEST_PLATFORM_SOURCE_ROOT=/absolute/path/to/AI-Agent-Platform. Before opting in,
install the existing webui dependencies with `npm ci` in both repositories and
build this repository's business bundle with `cd webui && npm run build`.
Node, esbuild (local webui), jsdom (local webui), and the external Platform's
renderer source/styles and dependencies must be available. Run from this repo:

    TEST_PLATFORM_SOURCE_ROOT=/absolute/path/to/AI-Agent-Platform PYTHONPATH=src \
        python -m pytest tests/workflow/test_preview_manufacturing.py -q -rs

Without the opt-in, only those integrations skip with an explicit reason.
An explicitly configured invalid source, missing build/dependency, or failed
renderer build is a test failure. Independent path/security checks use synthetic
local files and need no external Platform checkout or built JavaScript bundle.
"""

import hashlib
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    import preview_manufacturing as preview

    platform = os.environ.get("TEST_PLATFORM_SOURCE_ROOT")
    if platform is None:
        pytest.skip(
            "Renderer integration requires TEST_PLATFORM_SOURCE_ROOT and installed "
            "webui dependencies in both repositories plus the built business bundle; "
            "see this test module's prerequisite instructions"
        )
    root = tmp_path_factory.mktemp("preview-parent") / "demo"
    result = preview.prepare(root, Path(platform))
    return preview, root, result


def test_renderer_integration_requires_explicit_platform_source(
    monkeypatch, tmp_path_factory
):
    monkeypatch.delenv("TEST_PLATFORM_SOURCE_ROOT", raising=False)
    with pytest.raises(pytest.skip.Exception, match="TEST_PLATFORM_SOURCE_ROOT"):
        prepared.__wrapped__(tmp_path_factory)


def test_configured_invalid_renderer_source_is_a_hard_failure(
    monkeypatch, tmp_path_factory, tmp_path
):
    monkeypatch.setenv("TEST_PLATFORM_SOURCE_ROOT", str(tmp_path / "missing-platform"))
    with pytest.raises(FileNotFoundError):
        prepared.__wrapped__(tmp_path_factory)


@pytest.fixture
def local_bundle(tmp_path, monkeypatch):
    """Local preparation inputs; no external renderer or JavaScript tools needed."""
    import preview_manufacturing as preview

    repository = tmp_path / "repository"
    assets = repository / "webui/dist"
    assets.mkdir(parents=True)
    for name in ("manufacturing.js", "manufacturing.css"):
        (assets / name).write_text("local business bundle")
    (repository / "docs").mkdir()
    (repository / "docs/manufacturing-system-handbook.md").write_text("Synthetic handbook")
    monkeypatch.setattr(preview, "ROOT", repository)
    return preview, repository


@pytest.mark.parametrize("name", ["manufacturing.js", "manufacturing.css"])
@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo"])
def test_prepare_rejects_nonregular_build_inputs_before_writes(
    local_bundle, tmp_path, name, kind
):
    preview, repository = local_bundle
    source = repository / "webui/dist" / name
    source.unlink()
    outside = tmp_path / "outside-built-asset"
    outside.write_bytes(b"outside sentinel")
    if kind == "symlink":
        source.symlink_to(outside)
    elif kind == "directory":
        source.mkdir()
    else:
        os.mkfifo(source)
    root = tmp_path / "demo"
    try:
        with pytest.raises(ValueError):
            preview.prepare(root, tmp_path)
    finally:
        assert outside.read_bytes() == b"outside sentinel"
    assert not root.exists()


@pytest.mark.parametrize("directory", ["webui", "webui/dist"])
def test_prepare_rejects_linked_asset_directories_before_writes(
    local_bundle, tmp_path, directory
):
    preview, repository = local_bundle
    source = repository / directory
    outside = tmp_path / "outside-assets"
    source.rename(outside)
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"outside directory sentinel")
    source.symlink_to(outside, target_is_directory=True)
    root = tmp_path / "demo"
    try:
        with pytest.raises(ValueError):
            preview.prepare(root, tmp_path)
    finally:
        assert sentinel.read_bytes() == b"outside directory sentinel"
        assert sorted(p.name for p in outside.iterdir()) == (
            ["dist", "sentinel"]
            if directory == "webui"
            else ["manufacturing.css", "manufacturing.js", "sentinel"]
        )
    assert not root.exists()


@pytest.fixture
def owned_files(tmp_path):
    """File-boundary checks fail before opening databases or using the renderer."""
    import preview_manufacturing as preview

    root = tmp_path / "owned-demo"
    root.mkdir(mode=0o700)
    for directory in sorted(preview.DIRECTORIES):
        (root / directory).mkdir(mode=0o700)
    for name in preview.BASE_FILES - {"manifest.json"}:
        (root / name).write_bytes(b"synthetic local file")
    manifest = {
        "owner": preview.OWNER,
        "directory": str(root),
        "complete": True,
        "dataset": {"mode": "demo"},
        "assets": {
            name: hashlib.sha256((root / "webui/dist" / name).read_bytes()).hexdigest()
            for name in preview.ASSETS
        },
    }
    preview.write_json(root / "manifest.json", manifest)
    assert preview.load_owned(root) == manifest
    return preview, root, manifest


def test_prepare_refuses_unowned_paths_before_writes(tmp_path):
    import preview_manufacturing as preview

    target = tmp_path / "existing"
    target.mkdir()
    sentinel = target / "workflow.db"
    sentinel.write_bytes(b"user-owned")
    with pytest.raises(ValueError):
        preview.prepare(target, tmp_path)
    assert sentinel.read_bytes() == b"user-owned"
    linked = tmp_path / "linked"
    linked.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError):
        preview.prepare(linked, tmp_path)
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


def test_owned_root_rejects_added_links_and_changed_manifest(owned_files, tmp_path):
    preview, root, manifest = owned_files
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


def test_preview_synthetic_actor_keeps_real_project_permissions(prepared):
    preview, root, manifest = prepared
    subject = next(s for s in manifest["synthetic_subjects"] if s["display_name"].endswith("production"))
    app = preview.build_app(root, 19221, actor_id=subject["user_id"])
    with TestClient(app, base_url="http://127.0.0.1:19221") as client:
        response = client.get("/preview-bootstrap")
        assert response.status_code == 200
        body = response.json()
        assert body["user"]["displayName"] == subject["display_name"]
        assert body["bootstrap"]["configuration_admin"] is False


def test_preview_rejects_actor_outside_owned_synthetic_directory(prepared):
    preview, root, _ = prepared
    with pytest.raises(ValueError, match="synthetic"):
        preview.build_app(root, 19221, actor_id=str(uuid4()))


def test_owned_mock_source_storage_survives_preview_reopen(prepared):
    from datetime import UTC, datetime
    from manufacturing_platform.workflow.integrations.store import SystemStore

    preview, root, manifest = prepared
    store = SystemStore(root / "mock-systems", manifest["dataset"]["id"], "mes", clock=lambda: datetime.now(UTC))
    with store.transaction(write=True):
        pass
    guards = store.path.parent / "guards"
    guards.mkdir(exist_ok=True)
    (guards / f"{uuid4()}.lock").touch(mode=0o600)
    assert preview.load_owned(root)["dataset"] == manifest["dataset"]


@pytest.mark.parametrize("name", ["foreign-dataset", "foreign.sqlite3", "guards/not-a-uuid.lock"])
def test_preview_mock_storage_still_rejects_unlisted_entries(prepared, name):
    preview, root, manifest = prepared
    base = root / "mock-systems" / manifest["dataset"]["id"]
    base.mkdir(parents=True, exist_ok=True)
    entry = (root / "mock-systems" / name) if name == "foreign-dataset" else base / name
    entry.parent.mkdir(parents=True, exist_ok=True)
    if name == "foreign-dataset":
        entry.mkdir()
    else:
        entry.touch()
    try:
        with pytest.raises(ValueError, match="Unexpected preview"):
            preview.load_owned(root)
    finally:
        entry.rmdir() if entry.is_dir() else entry.unlink()


@pytest.mark.parametrize("alias", ["symlink", "hardlink"])
def test_preview_mock_source_file_aliases_remain_forbidden(prepared, tmp_path, alias):
    preview, root, manifest = prepared
    base = root / "mock-systems" / manifest["dataset"]["id"]
    base.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "outside.sqlite3"
    target.write_bytes(b"outside sentinel")
    linked = base / "hr_beisen.sqlite3"
    if alias == "symlink":
        linked.symlink_to(target)
    else:
        os.link(target, linked)
    try:
        with pytest.raises(ValueError):
            preview.load_owned(root)
        assert target.read_bytes() == b"outside sentinel"
    finally:
        linked.unlink()


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


def test_allowed_database_cannot_be_a_symlink_or_hardlink(owned_files, tmp_path):
    preview, root, _ = owned_files
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


def test_failed_preparation_is_preserved_and_never_auto_reset(
    local_bundle, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    preview, _ = local_bundle
    root = tmp_path / "failed-demo"
    monkeypatch.setattr(
        preview.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stderr="deliberate renderer failure"
        ),
    )
    with pytest.raises(ValueError, match="Renderer build failed"):
        preview.prepare(root, tmp_path)
    failed = (root / "manifest.json").read_bytes()
    assert json.loads(failed)["complete"] is False
    assert not (root / "workflow.db").exists()
    with pytest.raises(ValueError, match="new directory"):
        preview.prepare(root, tmp_path)
    assert (root / "manifest.json").read_bytes() == failed
    with pytest.raises(ValueError, match="Complete owned"):
        preview.build_app(root, 8765)
