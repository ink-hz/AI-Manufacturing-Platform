"""Private E33 runner contracts; process calls are isolated from real runtimes."""

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from .scenarios import material_task_references as runner
from .scenarios.base import EvidenceWriter


@pytest.fixture
def journey(tmp_path, monkeypatch):
    root = tmp_path / "source"
    (root / "webui").mkdir(parents=True)
    (root / "webui/package-lock.json").write_text('{"fixture":true}')
    directory = tmp_path / "evidence"
    directory.mkdir()
    context = SimpleNamespace(directory=directory, clock=datetime(2026, 11, 12, tzinfo=UTC),
                              evidence=EvidenceWriter(directory))
    sessions = {actor: (SimpleNamespace(addheaders=[("Cookie", "synthetic-session")]),
                        "synthetic-csrf", {"user_id": actor}) for actor in ("supply", "warehouse")}
    api = SimpleNamespace(base="https://127.0.0.1:1", sessions=sessions)
    node = tmp_path / "runtime/bin/node"
    node.parent.mkdir(parents=True)
    node.write_bytes(b"private pinned runtime fixture")
    node.chmod(0o700)
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.delenv("WORKFLOW_E30_COMMAND", raising=False)
    return context, api, node


def test_e33_uses_entire_pinned_argv_without_node_in_path(journey, monkeypatch):
    context, api, node = journey
    pinned = [str(node), "/private/runtime/vitest.mjs", "--config", "/private/evidence/vitest.config.mjs"]
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("WORKFLOW_E30_COMMAND", json.dumps(pinned))
    versions, launches = [], []
    monkeypatch.setattr(runner.subprocess, "check_output", lambda command, **kwargs: versions.append(command) or "v26.5.0\n")

    def launch(command, **kwargs):
        private = context.directory / "e33-session.json"
        assert private.stat().st_mode & 0o777 == 0o600
        assert kwargs["env"]["WORKFLOW_E33_SESSION"] == str(private)
        assert kwargs["timeout"] == 60
        launches.append(command)
        (context.directory / "e33-react-evidence.json").write_text('{"actual_react":true}')
        return SimpleNamespace(returncode=0, stdout="isolated process", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", launch)
    assert runner.react_journey(context, api, "project") == {"actual_react": True}
    assert launches == [[*pinned, "run", "src/workflow/acceptanceMaterialReferencesHttp.test.tsx",
                         "--configLoader", "runner", "--reporter=json",
                         "--outputFile=" + str(context.directory / "e33-vitest.json")]]
    assert versions == [[str(node), "--version"]]
    runtime = json.loads(next(context.directory.glob("*-ui-runtime.json")).read_text())["value"]
    assert runtime["command"] == launches[0]
    assert runtime["node_binary_sha256"] == hashlib.sha256(node.read_bytes()).hexdigest()
    assert runtime["node_version"] == "v26.5.0"
    assert not (context.directory / "e33-session.json").exists()


def test_e33_unavailable_pin_fails_without_falling_back_to_path_node(journey, monkeypatch):
    context, api, node = journey
    monkeypatch.setenv("PATH", str(node.parent))
    monkeypatch.setenv("WORKFLOW_E30_COMMAND", json.dumps([str(node.parent / "missing-node"), "/private/vitest.mjs"]))
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *a, **kw: pytest.fail("unavailable pin must not launch PATH Node"))
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **kw: pytest.fail("unavailable pin must not launch Vitest"))
    with pytest.raises(RuntimeError, match="E33 private pinned Node runtime unavailable"):
        runner.react_journey(context, api, "project")
    assert not (context.directory / "e33-session.json").exists()


@pytest.mark.parametrize("failure", ["permissions", "metadata", "launch"])
def test_e33_removes_private_session_on_setup_metadata_and_launch_failure(journey, monkeypatch, failure):
    context, api, node = journey
    monkeypatch.setenv("PATH", str(node.parent))
    monkeypatch.setenv("WORKFLOW_E30_COMMAND", json.dumps([str(node), "/private/vitest.mjs"]))
    real_chmod = Path.chmod

    def chmod(path, mode, *args, **kwargs):
        if failure == "permissions" and path.name == "e33-session.json":
            raise OSError("fixture permissions failure")
        return real_chmod(path, mode, *args, **kwargs)

    def version(*args, **kwargs):
        if failure == "metadata":
            raise OSError("fixture metadata failure")
        return "v26.5.0\n"

    def launch(*args, **kwargs):
        raise OSError("fixture launch failure")

    monkeypatch.setattr(Path, "chmod", chmod)
    monkeypatch.setattr(runner.subprocess, "check_output", version)
    monkeypatch.setattr(runner.subprocess, "run", launch)
    with pytest.raises(OSError, match=f"fixture {failure} failure"):
        runner.react_journey(context, api, "project")
    assert not (context.directory / "e33-session.json").exists()


def test_e33_resolves_named_pin_for_runtime_hash_and_version(journey, monkeypatch):
    context, api, node = journey
    monkeypatch.setenv("PATH", str(node.parent))
    monkeypatch.setenv("WORKFLOW_E30_COMMAND", json.dumps(["node", "/private/vitest.mjs"]))
    versions = []
    monkeypatch.setattr(runner.subprocess, "check_output", lambda command, **kwargs: versions.append(command) or "v26.5.0\n")

    def launch(*args, **kwargs):
        (context.directory / "e33-react-evidence.json").write_text('{}')
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", launch)
    assert runner.react_journey(context, api, "project") == {}
    assert versions == [[str(node), "--version"]]
    runtime = json.loads(next(context.directory.glob("*-ui-runtime.json")).read_text())["value"]
    assert runtime["node_binary_sha256"] == hashlib.sha256(node.read_bytes()).hexdigest()
    assert not (context.directory / "e33-session.json").exists()
