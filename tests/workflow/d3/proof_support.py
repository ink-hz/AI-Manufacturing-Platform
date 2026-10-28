"""Evidence from real requests, owned databases and component execution."""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

from ..scenarios.base import ROOT, EvidenceWriter, ScenarioContext, ScenarioPaths, owned_run


def reset_dataset(directory):
    manifest = owned_run(directory)
    paths = [directory / (name + suffix) for name in ("workflow.db", "authority.db") for suffix in ("", "-wal", "-shm")]
    if any(path.is_symlink() or path.resolve().parent != directory.resolve() for path in paths):
        raise ValueError("Foreign or symlink dataset refused")
    domain = directory / "workflow.db"
    if domain.exists():
        with sqlite3.connect(f"file:{domain}?mode=ro", uri=True) as db:
            metadata = db.execute("SELECT id,mode FROM dataset_metadata").fetchall()
        if metadata != [(manifest["dataset_id"], manifest["dataset_mode"])]:
            raise ValueError("Dataset reset ownership mismatch")
    for path in paths:
        path.unlink(missing_ok=True)
    return {"dataset_id": manifest["dataset_id"], "paths": list(map(str, paths)), "legacy_preserved": str(directory / "legacy.db")}


class ProofContext(ScenarioContext):
    def identifier(self, label):
        return super().identifier("D3-proof:" + label)


def reopen_context(directory):
    manifest = owned_run(directory)
    writer = EvidenceWriter(directory)
    writer.sequence = max((int(p.name[:6]) for p in directory.glob("[0-9][0-9][0-9][0-9][0-9][0-9]-*.json")), default=0)
    context = ProofContext(manifest["run_id"], manifest["case_id"], manifest["seed"], datetime.fromisoformat(manifest["business_clock"]), None, ScenarioPaths(directory / "workflow.db", directory / "authority.db", directory / "legacy.db"), writer)
    context.business_source_root = manifest["source"]["business_source_root"]
    return context


def snapshot(path):
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {table: {"rows": len(rows), "sha256": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()} for table in tables for rows in [[list(r) for r in db.execute('SELECT * FROM "' + table.replace('"', '""') + '" ORDER BY rowid')]]}


def ui_proof(context, tests, required_names, label):
    command = json.loads(os.environ["WORKFLOW_E30_COMMAND"]) if os.environ.get("WORKFLOW_E30_COMMAND") else [shutil.which("node") or "node", str(ROOT / "webui/node_modules/vitest/vitest.mjs")]
    output = context.directory / (label + "-vitest.json")
    args = [*command, "run", *tests, "--configLoader", "runner", "--reporter=json", "--outputFile=" + str(output)]
    process = subprocess.run(args, cwd=ROOT / "webui", capture_output=True, text=True, timeout=45)
    context.evidence.record("d3-ui-process", {"command": args, "node_sha256": hashlib.sha256(Path(shutil.which(command[0]) or command[0]).resolve().read_bytes()).hexdigest(), "package_lock_sha256": hashlib.sha256((ROOT / "webui/package-lock.json").read_bytes()).hexdigest(), "returncode": process.returncode, "stdout": process.stdout, "stderr": process.stderr, "boundary": "actual React/jsdom component; controlled fetch responses; no browser"})
    assert process.returncode == 0, "D3 component proof failed"
    report = json.loads(output.read_text())
    results = [r for suite in report["testResults"] for r in suite["assertionResults"]]
    for name in required_names:
        matching = [r for r in results if name in r["fullName"]]
        assert len(matching) == 1 and matching[0]["status"] == "passed", name
    context.evidence.record("d3-ui-assertions", {"required": required_names, "passed": report["numPassedTests"], "failed": report["numFailedTests"], "report": str(output)})


def api_order(api, pid, quantity):
    from datetime import timedelta
    due = (api.context.clock + timedelta(days=7)).date().isoformat()
    demand = api.command(pid, "demand.record", kind="firm", product="Camera", quantity=str(quantity), unit="piece", due_date=due, source=api.source("demand"))["object_id"]
    for dimension in ("technical", "material", "capacity", "commercial", "quality"):
        api.command(pid, "demand.review", demand_id=demand, dimension=dimension, decision="approved", evidence="Signed fixture review")
    return api.command(pid, "order.register", demand_id=demand, quantity=str(quantity), unit="piece", due_date=due, source=api.source("order_line"))["object_id"]
