"""Live checkout provenance or externally pinned, independently hashed exports."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_FILES = 20000
SOURCE_KEYS = {
    "provenance_kind",
    "manufacturing_commit",
    "platform_commit",
    "manufacturing_tree",
    "platform_tree",
    "dependency_symlink",
    "release_hash",
    "files",
    "build_files",
    "roots",
    "business_source_root",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def release_digest(files, build_files):
    return hashlib.sha256(
        json.dumps(
            {"files": files, "build_files": build_files}, sort_keys=True
        ).encode()
    ).hexdigest()


def checked_files(root, values):
    if not isinstance(values, dict) or not 1 <= len(values) <= MAX_FILES:
        raise ValueError("Pinned file map must be nonempty and bounded")
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("Pinned runtime root must be an absolute nonsymlink directory")
    for name, expected in values.items():
        if not isinstance(name, str) or "\\" in name:
            raise ValueError("Unsafe pinned file path")
        relative = PurePosixPath(name)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or str(relative) != name
            or not relative.parts
        ):
            raise ValueError("Unsafe pinned file path")
        if not isinstance(expected, str) or not re.fullmatch("[0-9a-f]{64}", expected):
            raise ValueError("Invalid pinned file digest")
        path = root
        for part in relative.parts:
            path = path / part
            if path.is_symlink():
                raise ValueError("Pinned symlink path refused")
        if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError("Missing or foreign pinned file")
        if digest(path) != expected:
            raise ValueError("Pinned file SHA256 mismatch: " + name)


def pinned(root, path):
    expected = os.environ.get("WORKFLOW_SOURCE_MANIFEST_SHA256", "")
    if not re.fullmatch("[0-9a-f]{64}", expected):
        raise ValueError("Expected pinned manifest SHA256 is required")
    if (
        not path.is_absolute()
        or path.is_symlink()
        or path.stat().st_size > MAX_MANIFEST_BYTES
    ):
        raise ValueError("Invalid pinned manifest file")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("Pinned manifest SHA256 mismatch")
    envelope = json.loads(raw)
    if (
        not isinstance(envelope, dict)
        or set(envelope)
        != {"version", "source", "manufacturing_runtime", "platform_runtime"}
        or type(envelope["version"]) is not int
        or envelope["version"] != 1
    ):
        raise ValueError("Unsupported pinned manifest schema")
    source = envelope["source"]
    if (
        not isinstance(source, dict)
        or set(source) != SOURCE_KEYS
        or source["provenance_kind"] != "live_git"
    ):
        raise ValueError("Invalid source export schema")
    for field in ("manufacturing_commit", "platform_commit"):
        if not isinstance(source[field], str) or not re.fullmatch(
            "[0-9a-f]{40}", source[field]
        ):
            raise ValueError("Invalid exported commit")
    if not all(
        isinstance(source[field], str)
        for field in ("manufacturing_tree", "platform_tree")
    ):
        raise ValueError("Invalid exported tree state")
    if not isinstance(source["roots"], dict) or set(source["roots"]) != {
        "manufacturing",
        "platform",
    }:
        raise ValueError("Invalid exported roots")
    if not all(
        isinstance(v, str) and Path(v).is_absolute() for v in source["roots"].values()
    ):
        raise ValueError("Invalid exported root values")
    if source["dependency_symlink"] is not None and not isinstance(
        source["dependency_symlink"], str
    ):
        raise ValueError("Invalid exported dependency boundary")
    if (
        not isinstance(source["business_source_root"], str)
        or not Path(source["business_source_root"]).is_absolute()
    ):
        raise ValueError("Invalid exported business root")
    checked_files(root, source["files"])
    checked_files(root, source["build_files"])
    if source["release_hash"] != release_digest(source["files"], source["build_files"]):
        raise ValueError("Pinned release hash mismatch")
    mf = envelope["manufacturing_runtime"]
    pf = envelope["platform_runtime"]
    if not isinstance(mf, dict) or set(mf) != {"files"}:
        raise ValueError("Invalid manufacturing runtime map")
    required = {
        k: v
        for k, v in source["files"].items()
        if k.startswith("src/") or k == "docs/manufacturing-system-handbook.md"
    }
    required.update(source["build_files"])
    if mf["files"] != required:
        raise ValueError(
            "Actual manufacturing runtime must match every exported business/handbook/build file"
        )
    mf_root = Path(os.environ.get("WORKFLOW_MANUFACTURING_RUNTIME_ROOT", ""))
    pf_root = Path(os.environ.get("WORKFLOW_PLATFORM_RUNTIME_ROOT", ""))
    checked_files(mf_root, mf["files"])
    if not isinstance(pf, dict) or set(pf) != {
        "target_commit",
        "baseline_image",
        "approved_overlay",
        "files",
    }:
        raise ValueError("Invalid platform runtime provenance")
    if (
        pf["target_commit"] != source["platform_commit"]
        or not isinstance(pf["baseline_image"], str)
        or not re.fullmatch("sha256:[0-9a-f]{64}", pf["baseline_image"])
    ):
        raise ValueError("Invalid platform target/baseline provenance")
    if not isinstance(pf["approved_overlay"], str) or not re.fullmatch(
        "[0-9a-f]{40}|[0-9a-f]{64}", pf["approved_overlay"]
    ):
        raise ValueError("Invalid approved platform overlay")
    checked_files(pf_root, pf["files"])
    if not any(k.endswith("/manufacturing.py") for k in pf["files"]) or not any(
        k.endswith("/control_plane/middleware.py") for k in pf["files"]
    ):
        raise ValueError(
            "Applicable platform manufacturing and identity middleware files required"
        )
    return {
        **source,
        "provenance_kind": "pinned_export",
        "export_provenance": source,
        "pinned_manifest_sha256": expected,
        "manufacturing_runtime": {"root": str(mf_root), "files": mf["files"]},
        "platform_runtime": {"root": str(pf_root), **pf},
        "business_source_root": str(mf_root / "src"),
    }


def source_manifest(root):
    configured = os.environ.get("WORKFLOW_SOURCE_MANIFEST")
    if configured:
        return pinned(root, Path(configured))
    platform = Path(
        os.environ.get(
            "TEST_PLATFORM_SOURCE_ROOT",
            str(root.parents[2] / "AI-Agent-Platform" / ".worktrees" / "full-workflow"),
        )
    )

    def git(directory, *args):
        return subprocess.check_output(
            ["git", "-C", str(directory), *args], text=True
        ).strip()

    files = git(
        root,
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "src",
        "webui",
        "docs/manufacturing-system-handbook.md",
        "docs/testing/manufacturing-full-workflow-acceptance.md",
        "tests/workflow",
        "scripts/run_workflow_acceptance.py",
    ).splitlines()
    hashes = {name: digest(root / name) for name in files if (root / name).is_file()}
    build = {
        name: digest(root / name)
        for name in ("webui/dist/manufacturing.js", "webui/dist/manufacturing.css")
        if (root / name).is_file()
    }
    return {
        "provenance_kind": "live_git",
        "manufacturing_commit": git(root, "rev-parse", "HEAD"),
        "platform_commit": git(platform, "rev-parse", "HEAD"),
        "manufacturing_tree": git(root, "status", "--porcelain=v1"),
        "platform_tree": git(platform, "status", "--porcelain=v1"),
        "dependency_symlink": os.readlink(root / "webui/node_modules")
        if (root / "webui/node_modules").is_symlink()
        else None,
        "release_hash": release_digest(hashes, build),
        "files": hashes,
        "build_files": build,
        "roots": {"manufacturing": str(root), "platform": str(platform)},
        "business_source_root": str(root / "src"),
    }
