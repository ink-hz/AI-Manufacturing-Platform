"""Actual A1 source export and isolated original-router invocation."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from ..scenarios.provenance import checked_files

A1_COMMIT = "b7397b4c0acd2bb9d32cafade8e885e4b9e7c732"


def historical_source(destination, repository, *, commit=A1_COMMIT, prefix="WORKFLOW_A1_SOURCE", label="a1"):
    configured = os.environ.get(prefix + "_MANIFEST")
    if configured:
        path = Path(configured)
        if not path.is_absolute() or path.is_symlink():
            raise ValueError("Historical manifest must be absolute and nonsymlink")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != os.environ.get(prefix + "_MANIFEST_SHA256"):
            raise ValueError("Historical manifest SHA256 mismatch")
        manifest = json.loads(raw)
        if set(manifest) != {"version", "commit", "files"} or manifest["version"] != 1 or manifest["commit"] != commit:
            raise ValueError("Unexpected historical source provenance")
        root = Path(os.environ.get(prefix + "_ROOT", ""))
    else:
        if os.environ.get("WORKFLOW_SOURCE_MANIFEST"):
            raise ValueError("Gitless candidate requires separately pinned A1 source")
        root = destination / (label + "-source")
        root.mkdir()
        names = subprocess.check_output(["git", "-C", str(repository), "ls-tree", "-r", "--name-only", commit, "src"], text=True).splitlines()
        files = {}
        for name in names:
            raw = subprocess.check_output(["git", "-C", str(repository), "show", f"{commit}:{name}"])
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            files[name] = hashlib.sha256(raw).hexdigest()
        manifest = {"version": 1, "commit": commit, "files": files}
    checked_files(root, manifest["files"])
    # Reject injected Python files, not merely edits to the pinned ones.
    actual = {str(p.relative_to(root)) for p in (root / "src").rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    if actual != set(manifest["files"]):
        raise ValueError("Historical source file inventory mismatch")
    (destination / (label + "-provenance.json")).write_text(json.dumps(manifest, sort_keys=True))
    return root


def create_historical(destination, repository, config):
    source = historical_source(destination, repository)
    config_path = destination / "a1-input.json"
    config_path.write_text(json.dumps(config))
    output = destination / "a1-output.json"
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("historical_api.py")), str(config_path), str(output)],
        env={**os.environ, "PYTHONPATH": str(source / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
        cwd=destination, capture_output=True, text=True, timeout=30,
    )
    (destination / "a1-process.json").write_text(json.dumps({"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}))
    assert result.returncode == 0, result.stderr
    return json.loads(output.read_text())
