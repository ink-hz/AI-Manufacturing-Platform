#!/usr/bin/env python3
"""Reviewed pytest-independent implementation of the D2 mandatory D3 hook."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "src")]
from workflow.scenarios.delivery_recovery_cases import HOST_ASSERTIONS
from workflow.d3.proof_support import reopen_context, snapshot
from workflow.d3 import case_authorization, case_restart, case_isolation


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=tuple(HOST_ASSERTIONS), required=True)
    parser.add_argument("--case-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    context = reopen_context(args.case_directory)
    if context.case_id != args.case or args.output != context.directory / "d3-proof.json" or args.output.exists():
        raise ValueError("Proof must name exact owned case/output")
    start = time.monotonic()
    try:
        {"E29": case_authorization.run, "E31": case_restart.run, "E32": case_isolation.run}[args.case](context)
    except BaseException as error:
        context.evidence.record("d3-first-failure", {"type": type(error).__name__, "message": str(error), "frames": [{"file": f.filename, "line": f.lineno, "function": f.name} for f in traceback.extract_tb(error.__traceback__)]})
        raise
    finally:
        if context.client:
            context.client.close()
    facts = {name: snapshot(context.directory / name) for name in ("workflow.db", "authority.db", "legacy.db") if (context.directory / name).exists()}
    fact_path = context.evidence.record("d3-final-facts", facts)
    # Digest all concrete request/response, restart, source, runtime and SQL
    # artifacts, including child processes. Credentials/private TLS keys excluded.
    artifacts = {}
    for path in context.directory.rglob("*.json"):
        if path.name in {"identity-control.json", "fixture.json", "pf-fixture.json", "d3-proof.json"} or "pf-release-" in str(path) or path.is_symlink():
            continue
        artifacts[str(path.relative_to(context.directory))] = digest(path)
    index = context.directory / "d3-artifact-index.json"
    index.write_text(json.dumps({"artifacts": artifacts, "final_facts": str(fact_path.relative_to(context.directory)), "duration_seconds": time.monotonic() - start}, sort_keys=True))
    command = json.loads(os.environ["WORKFLOW_D3_PROOF_COMMAND"])
    runner_files = {part: digest(Path(part)) for part in command if Path(part).is_absolute() and Path(part).is_file() and not Path(part).is_symlink()}
    manifest = json.loads((context.directory / "manifest.json").read_text())
    witnesses = [{"path": str(index.relative_to(context.directory)), "sha256": digest(index)}, {"path": str(fact_path.relative_to(context.directory)), "sha256": digest(fact_path)}]
    proof = {"case_id": args.case, "dataset_id": context.dataset_id, "seed": context.seed, "release_hash": manifest["source"]["release_hash"], "runner_files": runner_files, "artifact_index": witnesses[0], "assertions": {name: {"passed": True, "evidence": witnesses} for name in HOST_ASSERTIONS[args.case]}}
    if args.case == "E29":
        matrices = list(context.directory.glob("*-scope-write-matrix.json"))
        assert len(matrices) == 1, "E29 requires concrete negative write matrix evidence"
        proof["assertions"]["project-customer-action-acl"]["evidence"] = [
            *witnesses, {"path": str(matrices[0].relative_to(context.directory)), "sha256": digest(matrices[0])}
        ]
    args.output.write_text(json.dumps(proof, sort_keys=True))
    print(json.dumps({"case": args.case, "duration_seconds": time.monotonic() - start, "artifact_count": len(artifacts)}))


if __name__ == "__main__":
    main()
