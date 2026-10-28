"""Pinned candidate provenance must be checked before a case owns business state."""

import hashlib
import json
import pytest
from .scenarios import base


def test_pinned_manifest_hash_mismatch_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    path.write_text("{}")
    monkeypatch.setenv("WORKFLOW_SOURCE_MANIFEST", str(path))
    monkeypatch.setenv("WORKFLOW_SOURCE_MANIFEST_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="manifest SHA256"):
        base.source_manifest()


def export_fixture(tmp_path, monkeypatch):
    from .scenarios.provenance import release_digest

    private = tmp_path / "private"
    runtime = tmp_path / "runtime"
    platform = tmp_path / "platform"
    files = {
        "src/manufacturing_platform/workflow/api.py": "business source",
        "tests/workflow/scenarios/__init__.py": "private registry",
        "docs/manufacturing-system-handbook.md": "whole handbook",
    }
    build = {"webui/dist/manufacturing.js": "compiled bundle"}
    pf_files = {
        "app/manufacturing.py": "approved overlay",
        "app/control_plane/middleware.py": "baseline identity middleware",
    }

    def materialize(root, values):
        result = {}
        for name, content in values.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    hashes = materialize(private, files)
    built = materialize(private, build)
    runtime_files = materialize(
        runtime,
        {
            **{
                k: v
                for k, v in files.items()
                if k.startswith("src/") or k.startswith("docs/")
            },
            **build,
        },
    )
    platform_files = materialize(platform, pf_files)
    source = {
        "provenance_kind": "live_git",
        "manufacturing_commit": "a" * 40,
        "platform_commit": "b" * 40,
        "manufacturing_tree": " M original-export-state",
        "platform_tree": "",
        "dependency_symlink": None,
        "release_hash": release_digest(hashes, built),
        "files": hashes,
        "build_files": built,
        "roots": {"manufacturing": "/host/mf", "platform": "/host/pf"},
        "business_source_root": "/host/mf/src",
    }
    envelope = {
        "version": 1,
        "source": source,
        "manufacturing_runtime": {"files": runtime_files},
        "platform_runtime": {
            "target_commit": "b" * 40,
            "baseline_image": "sha256:" + "c" * 64,
            "approved_overlay": "b" * 40,
            "files": platform_files,
        },
    }
    path = tmp_path / "pinned.json"

    def save():
        path.write_text(json.dumps(envelope))
        monkeypatch.setenv(
            "WORKFLOW_SOURCE_MANIFEST_SHA256",
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )

    save()
    monkeypatch.setenv("WORKFLOW_SOURCE_MANIFEST", str(path))
    monkeypatch.setenv("WORKFLOW_MANUFACTURING_RUNTIME_ROOT", str(runtime))
    monkeypatch.setenv("WORKFLOW_PLATFORM_RUNTIME_ROOT", str(platform))
    return private, runtime, platform, envelope, save


def test_pinned_export_checks_both_mf_trees_and_layered_actual_pf_without_git(
    tmp_path, monkeypatch
):
    from .scenarios import provenance

    private, runtime, platform, envelope, save = export_fixture(tmp_path, monkeypatch)

    def no_git(*args, **kwargs):
        raise AssertionError("git must not run inside candidate")

    monkeypatch.setattr(provenance.subprocess, "check_output", no_git)
    value = provenance.source_manifest(private)
    assert value["provenance_kind"] == "pinned_export"
    assert value["manufacturing_tree"] == " M original-export-state"
    assert value["business_source_root"] == str(runtime / "src")
    assert value["platform_runtime"]["target_commit"] == "b" * 40


@pytest.mark.parametrize("target", ["private", "runtime", "platform"])
def test_pinned_file_tampering_is_rejected_before_case_state(
    tmp_path, monkeypatch, target
):
    private, runtime, platform, envelope, save = export_fixture(tmp_path, monkeypatch)
    root = {"private": private, "runtime": runtime, "platform": platform}[target]
    file = next(p for p in root.rglob("*.py"))
    file.write_text("tampered source")
    monkeypatch.setattr(base, "ROOT", private)
    output = tmp_path / "not-created"
    with pytest.raises(ValueError, match="file SHA256"):
        base.ScenarioContext.isolated(output, case_id="F01", seed=1)
    assert not output.exists()


@pytest.mark.parametrize(
    "bad", ["../outside", "/absolute", "src/../outside", "src\\outside"]
)
def test_pinned_relative_paths_cannot_escape(tmp_path, monkeypatch, bad):
    from .scenarios.provenance import source_manifest

    private, _, _, envelope, save = export_fixture(tmp_path, monkeypatch)
    envelope["source"]["files"][bad] = "0" * 64
    save()
    with pytest.raises(ValueError, match="path"):
        source_manifest(private)


def test_pinned_symlink_input_refused(tmp_path, monkeypatch):
    from .scenarios.provenance import source_manifest

    private, _, _, _, _ = export_fixture(tmp_path, monkeypatch)
    path = private / "src/manufacturing_platform/workflow/api.py"
    actual = tmp_path / "elsewhere.py"
    actual.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(actual)
    with pytest.raises(ValueError, match="symlink"):
        source_manifest(private)


@pytest.mark.parametrize(
    "section", ["source", "manufacturing_runtime", "platform_runtime"]
)
def test_pinned_empty_file_maps_refused(tmp_path, monkeypatch, section):
    from .scenarios.provenance import source_manifest

    private, _, _, envelope, save = export_fixture(tmp_path, monkeypatch)
    envelope[section]["files"] = {}
    save()
    with pytest.raises(ValueError):
        source_manifest(private)
