"""Parent rechecks available proof facts, independent of subprocess pass labels."""

import hashlib
import json
from pathlib import Path
from .proof_support import snapshot
from ..scenarios.base import ROOT


def verify(context, proof):
    descriptor = proof["artifact_index"]
    path = context.directory / descriptor["path"]
    assert path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(context.directory.resolve())
    assert hashlib.sha256(path.read_bytes()).hexdigest() == descriptor["sha256"]
    index = json.loads(path.read_text())
    assert len(index["artifacts"]) >= 10
    source = json.loads((context.directory / "manifest.json").read_text())["source"]
    for name, expected in source["files"].items():
        if name.startswith(("tests/workflow/d3/", "tests/workflow/scenarios/")):
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, "Proof dependency source changed: " + name
    actual_host = False
    for name, expected in index["artifacts"].items():
        relative = Path(name)
        artifact = context.directory / relative
        assert not relative.is_absolute() and ".." not in relative.parts
        assert not any(p.is_symlink() for p in (artifact, *artifact.parents) if p.is_relative_to(context.directory))
        assert artifact.is_file() and hashlib.sha256(artifact.read_bytes()).hexdigest() == expected
        if artifact.name.startswith("pf-loaded-"):
            loaded = json.loads(artifact.read_text())
            allowed_root = source.get("platform_runtime", {}).get("root", source["roots"]["platform"])
            assert loaded["root"] == allowed_root
            required = {"backend/app/main.py", "backend/app/manufacturing.py", "backend/app/control_plane/middleware.py", "backend/app/control_plane/authorization.py"}
            assert required <= set(loaded["files"])
            for file, digest in loaded["files"].items():
                actual = Path(allowed_root) / file
                assert actual.resolve().is_relative_to(Path(allowed_root).resolve()) and not actual.is_symlink()
                assert hashlib.sha256(actual.read_bytes()).hexdigest() == digest
            actual_host = True
        if "-pf-manufacturing-release.json" in artifact.name:
            release = json.loads(artifact.read_text())["value"]
            root = Path(release["root"])
            assert root.is_relative_to(context.directory) and not root.is_symlink()
            historical = None
            if release["source_override"]:
                historical = json.loads((root.parent / "legacy-provenance.json").read_text())
                assert historical["commit"] == "ec41b39bdf8c0b5cc6b0193ed646a44050106ca3"
            for filename, expected in release["files"].items():
                actual = root / filename
                assert actual.resolve().is_relative_to(root.resolve()) and not actual.is_symlink()
                assert hashlib.sha256(actual.read_bytes()).hexdigest() == expected
                if filename == "handbook-metadata.json":
                    continue
                bound = historical["files"].get(filename) if historical and filename.startswith("src/") else source["files"].get(filename, source["build_files"].get(filename))
                assert bound == expected, "Executed manufacturing release differs from provenance"
    assert actual_host, "No actual create_app middleware runtime evidence"
    facts = json.loads((context.directory / index["final_facts"]).read_text())["value"]
    for name, expected in facts.items():
        assert name in {"workflow.db", "authority.db", "legacy.db"}
        assert snapshot(context.directory / name) == expected, "Parent database evidence mismatch"
