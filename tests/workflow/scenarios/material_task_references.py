"""E33: actual PF HTTPS/identity/loader and React; owned synthetic data only."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from .base import ROOT
from ..d3.pf_client import PlatformHTTP, PREFIX


FACT_TABLES = ("requirements", "supply_commitments", "material_lots", "supply_receipts",
               "iqc_results", "reservations", "material_consumption", "material_handoffs",
               "exchanges", "integration_intents", "integration_receipts", "integration_projections", "integration_object_links",
               "source_corrections", "source_confirmations")


def facts(api):
    """Read-only evidence: exact rows, not merely counts or claimed quantities."""
    with api.db() as db:
        return {t: [tuple(r) for r in db.execute(f'SELECT * FROM "{t}" ORDER BY rowid')]
                for t in FACT_TABLES}


def react_journey(context, api, project):
    sessions = {}
    for actor in ("supply", "warehouse"):
        opener, csrf, identity = api.sessions[actor]
        sessions[actor] = {"cookie": dict(opener.addheaders)["Cookie"], "csrf": csrf, "identity": identity}
    private = context.directory / "e33-session.json"
    try:
        private.write_text(json.dumps({"base": api.base, "prefix": PREFIX,
            "ca": str(context.directory / "loopback-cert.pem"), "sessions": sessions, "clock": context.clock.isoformat(),
            "project_id": project, "evidence": str(context.directory / "e33-react-evidence.json")}))
        private.chmod(0o600)
        command = (json.loads(os.environ["WORKFLOW_E30_COMMAND"]) if os.environ.get("WORKFLOW_E30_COMMAND")
                   else [shutil.which("node") or "node", str(ROOT / "webui/node_modules/vitest/vitest.mjs")])
        node = Path(shutil.which(command[0]) or command[0]).resolve()
        if not node.is_file():
            raise RuntimeError("E33 private pinned Node runtime unavailable; actual React evidence required")
        command = [*command, "run", "src/workflow/acceptanceMaterialReferencesHttp.test.tsx", "--configLoader", "runner",
                   "--reporter=json", "--outputFile=" + str(context.directory / "e33-vitest.json")]
        context.evidence.record("ui-runtime", {"command": command,
            "node_binary_sha256": hashlib.sha256(node.read_bytes()).hexdigest(),
            "node_version": subprocess.check_output([str(node), "--version"], text=True).strip(),
            "package_lock_sha256": hashlib.sha256((ROOT / "webui/package-lock.json").read_bytes()).hexdigest(),
            "boundary": "actual WorkflowApp/jsdom -> scoped-CA HTTPS -> actual PF create_app/preview/auth/loader; synthetic identity"})
        result = subprocess.run(command, cwd=ROOT / "webui", env={**os.environ, "WORKFLOW_E33_SESSION": str(private)},
                                capture_output=True, text=True, timeout=60)
        context.evidence.record("ui-process", {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        assert result.returncode == 0, "Actual E33 React/PF HTTPS failed; inspect ui-process artifact"
        return json.loads((context.directory / "e33-react-evidence.json").read_text())
    finally:
        private.unlink(missing_ok=True)


def e33(context):
    api = context.client = PlatformHTTP(context)
    pid = api.project("2", product="E33 empty OEM", mode="oem")
    before = facts(api)
    assert not api.objects(pid, "requirement")
    url = f"/projects/{pid}/material-task-references"
    api.get(url, anonymous=True, expected=401)
    api.get(url, actor="outsider", expected=404)
    assert api.get(url, actor="supply")["items"] == []
    api.grant(pid, "viewer", ["supply"])
    assert api.get(url, actor="viewer")["items"] == []
    api.control("supply", hard_stale=True)
    assert api.get(url, actor="supply")["items"] == []
    api.control("supply", hard_stale=False)
    result = react_journey(context, api, pid)
    value = api.object(pid, "material_task", result["task_id"])
    assert value["state"] == "closed" and value["closure"]["outcome"] == "identity_verified"
    assert value["requirement_id"] is None and value["receipt_id"] is None
    assert value["assignee_id"] == api.sessions["warehouse"][2]["user_id"]
    assert value["reference"]["reference"]["id"] == result["arrival_id"]
    assert len(value["history"]) == 4
    assert facts(api) == before
    context.evidence.record("e33-accounting-invariant", {"tables": list(before), "before": before, "after": facts(api)})
    for actor, status in (("viewer", 403), ("supply", 503)):
        if actor == "supply": api.control(actor, hard_stale=True)
        page = api.get(url, actor=actor)
        assert page["items"] and page["items"][0]["can_open"] is False
        api.command(pid, "material_task.open", actor=actor, expected=status, task_kind="verify",
                    reference={"kind": "arrival", "id": result["arrival_id"], "version": 1},
                    assignee_id=api.sessions["warehouse"][2]["user_id"], note="Read-only denied")
        if actor == "supply": api.control(actor, hard_stale=False)
    api.post(url, {}, actor="supply", expected=403)
    api.get(url + "/extra", actor="supply", expected=403)
    assert facts(api) == before
    persisted_reference_journeys(context, api, pid)
    context.actual.update(arrival_id=result["arrival_id"], task_id=result["task_id"],
                          empty_requirement_workflow=True, accounting_unchanged=True, host="actual PF HTTPS")


def persisted_reference_journeys(context, api, empty_project):
    from uuid import uuid4
    from .material_reference_seeds import seed_mes, seed_mock_receipt

    pid, reference, fake = seed_mes(context)
    before = facts(api)
    page = api.get(f"/projects/{pid}/material-task-references?kind=mes_component")
    item = page["items"][0]
    assert item["reference"] == reference
    assert item["evidence"]["origin"] == "native" and item["evidence"]["environment"] == "test"
    task = api.command(pid, "material_task.open", actor="supply", task_kind="verify", reference=reference,
                       assignee_id=api.sessions["warehouse"][2]["user_id"], note="Verify persisted FakeMes component")["object_id"]
    assert api.object(pid, "material_task", task)["requirement_id"] is None
    api.command(empty_project, "material_task.open", task_kind="verify", reference=reference,
                assignee_id=api.sessions["warehouse"][2]["user_id"], note="Foreign component rejected", expected=404)
    assert not api.objects(pid, "requirement") and fake.calls == 1
    assert facts(api) == before

    pid, receipt, requirement, source_reference, other, wrong_plan = seed_mock_receipt(context)
    api.grant(pid, "quality", ["quality"], ["inspection"])
    api.grant(other, "quality", ["quality"], ["inspection"])
    wrong_requirement = api.object(pid, "plan", wrong_plan)["requirement_ids"][0]
    before = facts(api)
    exact = api.get(f"/projects/{pid}/material-task-references?task_kind=iqc&receipt_id={receipt}&limit=1")
    assert exact["total"] == 1
    item = exact["items"][0]
    assert item["reference"] == source_reference
    assert item["evidence"]["origin"] == "mock" and item["evidence"]["environment"] == "mock"
    assignee = api.sessions["quality"][2]["user_id"]
    task = api.command(pid, "material_task.open", task_kind="iqc", reference=source_reference,
                       assignee_id=assignee, note="Direct admitted mock receipt IQC")["object_id"]
    value = api.object(pid, "material_task", task)
    assert value["receipt_id"] == receipt and value["requirement_id"] == requirement
    alias = api.command(pid, "material_task.open", task_kind="iqc", reference={"kind": "receipt", "id": receipt},
                        assignee_id=assignee, note="Same receipt alias")
    assert alias["object_id"] == task
    tasks_before = api.objects(pid, "material_task")
    foreign_tasks_before = api.objects(other, "material_task")
    missing = {**source_reference, "source_key": {**source_reference["source_key"], "external_id": str(uuid4())}}
    for project, ref in ((pid, missing), (other, source_reference)):
        api.command(project, "material_task.open", task_kind="iqc", reference=ref, assignee_id=assignee,
                    note="Unadmitted or foreign receipt rejected", expected=409)
    api.command(pid, "material_task.open", task_kind="iqc", reference=source_reference,
                requirement_id=wrong_requirement, assignee_id=assignee, note="Wrong association rejected", expected=422)
    assert api.objects(pid, "material_task") == tasks_before
    assert api.objects(other, "material_task") == foreign_tasks_before
    assert facts(api) == before
    context.evidence.record("e33-accounting-invariant", {"phase": "admitted receipt dispatch and rejected references",
        "tables": list(before), "before_sha256": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
        "after_sha256": hashlib.sha256(json.dumps(facts(api), sort_keys=True).encode()).hexdigest(),
        "row_counts": {table: len(rows) for table, rows in before.items()}})
    context.actual.update(persisted_native_test_component=True, admitted_mock_receipt=True,
                          exact_receipt_dedup=True, missing_foreign_wrong_rejected=True,
                          source_seed_boundary="owned service commands/FakeMes/MockRig actual admission; no production source")
