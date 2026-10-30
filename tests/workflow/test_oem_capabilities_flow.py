"""OEM integration uses real socket HTTP, independently authenticated roles and facts."""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from .scenarios.base import OWNER, EvidenceWriter, ScenarioContext, ScenarioPaths
from .scenarios.fixtures import BusinessHTTP

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))


class HTTPSeed:
    """Adapter of the existing isolated HTTP transport to the demo command recipe."""

    def __init__(self, api):
        self.api = api
        self.manifest = {"started_at": api.context.clock.isoformat(), "projects": []}
        self.config = {"owner_ids": []}
        self.actors = {}
        for name in (
            "owner",
            "engineering",
            "planner",
            "supply",
            "production",
            "quality",
            "warehouse",
        ):
            identity = api.login(name)
            self.actors["maintenance" if name == "owner" else name] = SimpleNamespace(
                user_id=identity["user_id"]
            )

    def ident(self, key):
        return self.api.context.identifier(key)

    def checkpoint(self):
        pass

    def source(self, key, kind):
        return self.api.source(kind, self.ident(key))

    def command(self, key, pid, action, actor="maintenance", **fields):
        return self.api.command(
            pid, action, actor="owner" if actor == "maintenance" else actor, **fields
        )

    def obj(self, pid, kind, oid):
        return self.api.object(pid, kind, oid)

    def objects(self, pid, kind):
        return [self.obj(pid, kind, x["id"]) for x in self.api.objects(pid, kind)]

    def step(self, key, kind, payload, **kwargs):
        if kind == "project":
            return self.api.post("/projects", payload)
        return self.api.authority(kind, **payload)

    def grant(self, key, pid, target, roles, qualifications=()):
        actor = next(k for k, v in self.actors.items() if v.user_id == target)
        return self.api.grant(pid, actor, roles, qualifications)


def socket_context(tmp_path):
    directory = tmp_path / "oem-http"
    directory.mkdir(mode=0o700)
    ctx = ScenarioContext(
        "oem-integration",
        "OEM",
        5,
        datetime.now(UTC),
        None,
        ScenarioPaths(
            directory / "workflow.db",
            directory / "authority.db",
            directory / "legacy.db",
        ),
        EvidenceWriter(directory),
    )
    runtime_root = os.environ.get("WORKFLOW_MANUFACTURING_RUNTIME_ROOT")
    ctx.business_source_root = str(
        (Path(runtime_root) if runtime_root else Path(__file__).resolve().parents[2]) / "src"
    )
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "owner": OWNER,
                "directory": str(directory),
                "dataset_id": ctx.dataset_id,
                "dataset_mode": "test",
                "business_source_root": ctx.business_source_root,
            }
        )
    )
    return ctx


def test_oem_cross_project_socket_flow_and_current_bulk_projection(tmp_path):
    from workflow_demo.oem_preview import populate

    context = socket_context(tmp_path)
    api = BusinessHTTP(context)
    api.login("admin")
    try:
        result = populate(HTTPSeed(api))
        a, b = result["camera"], result["robot"]
        pid = b["project_id"]

        def detail():
            return api.get("/projects/" + pid)

        stages = detail()["progress"]["stages"]
        assert "NPI" in stages[4]["reason"], stages
        assert stages[4]["status"] == "blocked"
        assert "NPI" not in stages[1]["reason"]
        assert not api.object(pid, "npi", b["npi_id"])["bulk_eligible"]
        api.command(
            pid,
            "npi.approve",
            npi_id=b["npi_id"],
            evidence="【模拟】premature",
            expected=409,
        )
        api.grant(a["project_id"], "quality", ["quality"], ["inspection"], active=False)
        public = api.get("/reusable-assets", actor="quality")
        serialized = json.dumps(public)
        assert a["project_id"] not in serialized and a["issue_id"] not in serialized
        assert "PRIVATE-CAMERA" not in serialized
        api.get(
            f"/projects/{a['project_id']}/objects/npi_issue/{a['issue_id']}",
            actor="quality",
            expected=404,
        )
        api.command(
            pid,
            "asset.verify",
            actor="quality",
            asset_use_id=b["asset_use_id"],
            decision="pass",
            evidence="【模拟】robot independent fixture inspection",
        )
        api.command(
            pid,
            "npi.approve",
            npi_id=b["npi_id"],
            evidence="【模拟】target review signed",
        )
        assert api.object(pid, "npi", b["npi_id"])["bulk_eligible"]
        assert "NPI" not in detail()["progress"]["stages"][4]["reason"]
        assert detail()["progress"]["stages"][4]["status"] != "blocked"
        body = {
            "action": "npi.issue",
            "operation_id": context.identifier("replay"),
            "expected_version": detail()["version"],
            "npi_id": b["npi_id"],
            "phenomenon": "【模拟】later vibration",
            "risk": "【模拟】requalification",
            "containment": "【模拟】hold bulk",
        }
        accepted = api.post(f"/projects/{pid}/commands", body, actor="quality")
        issue_total = api.get(f"/projects/{pid}/objects/npi_issue")["total"]
        assert (
            api.post(f"/projects/{pid}/commands", body, actor="quality")["object_id"]
            == accepted["object_id"]
        )
        assert api.get(f"/projects/{pid}/objects/npi_issue")["total"] == issue_total
        api.post(
            f"/projects/{pid}/commands",
            {**body, "phenomenon": "changed"},
            actor="quality",
            expected=409,
        )
        api.post(
            f"/projects/{pid}/commands",
            {**body, "operation_id": context.identifier("stale")},
            actor="quality",
            expected=409,
        )
        assert not api.object(pid, "npi", b["npi_id"])["bulk_eligible"]
        assert "NPI" in detail()["progress"]["stages"][4]["reason"]
        api.grant(pid, "quality", ["quality"], ["inspection"], active=False)
        api.post(f"/projects/{pid}/commands", body, actor="quality", expected=404)
        api.get("/projects/" + pid, actor="quality", expected=404)
        # The owner/admin session predates this project and has no project grants.
        fresh = api.post(
            "/projects",
            {**result["future_project"], "operation_id": context.identifier("future")},
        )
        api.command(
            fresh["id"],
            "project.stage",
            actor="admin",
            stage="S2",
            status="active",
            reason="【模拟】future project admin",
        )
        unit = api.object(a["project_id"], "unit", a["unit_id"])
        assert unit["sn"] == a["sn"] and unit["aliases"]
        assert [c["state"] for c in unit["components"]] == ["removed", "installed"]
        assert [
            api.object(a["project_id"], "test_run", rid)["state"] for rid in a["runs"]
        ] == ["aborted", "completed", "completed"]
        assert (
            api.object(a["project_id"], "calibration", a["calibration_id"])["state"]
            == "pending"
        )
        for identity, value in [
            ("camera-calculation", "1.25"),
            ("camera-readback", "1.26"),
        ]:
            api.command(
                a["project_id"],
                "calibration.confirm",
                calibration_id=a["calibration_id"],
                readback=[{"name": "gain", "value": value, "unit": "ratio"}],
                origin="demo",
                source_identity=identity,
                source_version="1",
                evidence="【模拟】invalid readback",
                expected=409,
            )
        api.command(
            a["project_id"],
            "calibration.confirm",
            calibration_id=a["calibration_id"],
            readback=[{"name": "gain", "value": "1.250", "unit": "ratio"}],
            origin="demo",
            source_identity="camera-readback",
            source_version="1",
            evidence="【模拟】separate matched observation",
        )
        assert (
            api.object(a["project_id"], "calibration", a["calibration_id"])["state"]
            == "confirmed"
        )
        assert api.get(f"/projects/{a['project_id']}/objects/release")["total"] == 0
        context.evidence.record_db_snapshot(context.paths.domain)
    finally:
        api.close()


def test_s5_unlinked_npi_preserves_legacy_progress(workflow):
    from .test_execution import ready_for_trial
    from .test_introduction import open_npi

    p, wo, _, _ = ready_for_trial(workflow, quantity="2", trial_quantity="1")
    base = "/api/v1/manufacturing/workflow/projects/" + p["id"]
    before = workflow.client().get(base).json()["progress"]["stages"]
    revision = workflow.object(p["id"], "work_order", wo["id"])["revision_id"]
    open_npi(workflow, p, revision)
    after = workflow.client().get(base).json()["progress"]["stages"]
    assert before == after
    assert "NPI" not in after[1]["reason"] and "NPI" not in after[4]["reason"]
