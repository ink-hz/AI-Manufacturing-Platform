"""E32 seven real legacy API projects and non-overlapping owned reset."""

import json
import subprocess
import sys
from ..scenarios.base import ROOT, ScenarioContext
from ..scenarios import business as b
from .pf_client import PlatformHTTP
from .proof_support import snapshot, ui_proof, reset_dataset

LEGACY = "/api/v1/manufacturing"


def run(context):
    api = PlatformHTTP(context)
    context.client = api
    legacy_ids = []
    for index in range(7):
        created = api.request("POST", LEGACY + "/projects", body={"operation_id": context.identifier("legacy"), "name": "Disposable legacy " + str(index), "line_id": "cameras", "owner": "Synthetic owner", "product": "Camera", "customer": "Synthetic customer", "target_quantity": 100})
        pid = created["project"]["id"]
        legacy_ids.append(pid)
        api.request("POST", f"{LEGACY}/projects/{pid}/tasks", body={"operation_id": context.identifier("legacy-task"), "stage_id": "S1", "title": "Original legacy task"})
        package = api.request("POST", f"{LEGACY}/projects/{pid}/packages", body={"operation_id": context.identifier("legacy-package"), "title": "Original legacy control", "items": [{"id": "bom", "kind": "mbom", "title": "Original MBOM", "status": "verified", "evidence": "Original signed fixture"}]})
        api.request("GET", f"{LEGACY}/projects/{pid}/controls")
        assert package["version"] == 1
    assert len(api.request("GET", LEGACY + "/projects")["items"]) == 7
    before = snapshot(context.paths.legacy)
    context.evidence.record("legacy-before", {"ids": legacy_ids, "tables": before})
    flow = b.released(context, 2)
    shipment = b.ship(flow, flow.units)["object_id"]
    b.accept(flow, shipment, 2)
    assert api.object(flow.project, "order_line", flow.order)["accepted"] == "2"
    assert api.get("/access")["dataset"]["mode"] == "test"
    assert snapshot(context.paths.legacy) == before
    # The reset capability is scoped to one independently owned disposable run.
    disposable = ScenarioContext.isolated(context.directory / "reset-owned", case_id="E32", seed=context.seed + 11, clock=context.clock)
    reset_api = PlatformHTTP(disposable)
    try:
        reset_api.project("1")
    finally:
        reset_api.close()
    # Reset only test dataset files after checking ownership; the read-only
    # release export is retained evidence, not part of the mutable dataset.
    reset = reset_dataset(disposable.directory)
    context.evidence.record("owned-dataset-reset", reset)
    reset_api = PlatformHTTP(disposable)
    try:
        assert reset_api.get("/projects")["items"] == []
    finally:
        reset_api.close()
    assert snapshot(context.paths.legacy) == before
    # Exercise the public private-run reset command's ownership guard against
    # an outside sentinel. No shell expansion, no production filesystem paths.
    sentinel = context.directory.parent / "outside-reset-sentinel.txt"
    sentinel.write_text("Unrelated owned test sentinel")
    command = [sys.executable, str(ROOT / "scripts/run_workflow_acceptance.py"), "--delete-owned-run", str(sentinel), "--dataset-mode", "test"]
    process = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert process.returncode != 0 and sentinel.read_text() == "Unrelated owned test sentinel"
    context.evidence.record("reset-refusal", {"command": command, "returncode": process.returncode, "stderr": process.stderr, "sentinel_unchanged": True})
    from manufacturing_platform.workflow.store import WorkflowStore
    foreign = WorkflowStore(str(context.paths.domain), str(context.paths.authority), {"id": "foreign-dataset", "mode": "test", "label": "Foreign"})
    domain_before = snapshot(context.paths.domain)
    try:
        with foreign.transaction():
            raise AssertionError("Foreign dataset was accepted")
    except ValueError as error:
        assert "dataset mismatch" in str(error)
    assert snapshot(context.paths.domain) == domain_before
    after = snapshot(context.paths.legacy)
    context.evidence.record("legacy-after", {"ids": legacy_ids, "tables": after, "owned_reset_root": str(disposable.directory), "domain_project": flow.project})
    assert after == before
    context.evidence.record_db_snapshot(context.paths.legacy)
    api.close()
    # Seed/fault replay is performed by this SAME registry's mandatory local E32
    # E14 children; inspect their genuine artifacts, do not re-label a checklist.
    seeds = []
    for manifest_path in (context.directory / "seed-replays").glob("*/E14/manifest.json"):
        result = json.loads(manifest_path.with_name("result.json").read_text())
        manifest = json.loads(manifest_path.read_text())
        assert result["status"] == "passed"
        seeds.append(manifest["seed"])
    assert sorted(seeds) == [context.seed + 1, context.seed + 2]
    context.evidence.record("seed-replay-verified", {"seeds": seeds})
    ui_proof(context, ["src/workflow/supply.test.tsx"], ["exchange workspace exposes synchronization and bounded request list", "exchange detail distinguishes uncertain simulation from confirmed inventory"], "e32-simulation")
