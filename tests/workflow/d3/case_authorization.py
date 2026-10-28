"""E29 actual host policy matrix plus retired-client component proof."""

import hashlib
import json
from pathlib import Path
from ..scenarios.base import ROOT, ScenarioContext
from ..scenarios.fixtures import BASE
from .pf_client import PlatformHTTP
from .historical import historical_source
from .proof_support import snapshot, ui_proof


def scope_write_matrix(api, projects):
    """Well-formed commands separate project visibility from role/schema denial."""
    context = api.context
    own = projects["own"]["id"]
    api.grant(own, "planner", ["planner", "project_owner"])
    fields = {"kind": "firm", "product": "Camera", "quantity": "1", "unit": "piece", "due_date": "2026-12-01"}
    api.command(own, "demand.record", actor="planner", **fields, source=api.source("demand"))
    positive_response = context.evidence.artifacts[-1]
    denied = []
    for label, target, actor, anonymous, status in (
        ("anonymous", own, "planner", True, 401),
        ("outsider", own, "outsider", False, 404),
        ("other_same_customer", projects["same_customer"]["id"], "planner", False, 404),
        ("other_customer", projects["other_customer"]["id"], "planner", False, 404),
    ):
        # Trusted fixture reads the actual version; the denied actor does not
        # need a successful preliminary GET, malformed command or missing FK.
        with api.db() as db:
            versions = dict(db.execute("SELECT id,version FROM projects"))
        body = {"action": "demand.record", "operation_id": context.identifier("scope-write-" + label), "expected_version": versions[target], **fields, "source": api.source("demand")}
        paths = [context.directory / name for name in ("workflow.db", "authority.db", "legacy.db")]
        before = {path.name: snapshot(path) for path in paths if path.exists()}
        context.evidence.record("scope-write-before", {"case": label, "project_id": target, "project_versions": versions, "tables": before})
        try:
            reply = api.post(f"/projects/{target}/commands", body, actor=actor, anonymous=anonymous, expected=status)
        finally:
            after = {path.name: snapshot(path) for path in paths if path.exists()}
            context.evidence.record("scope-write-after", {"case": label, "tables": after})
        response_path = context.evidence.artifacts[-2]
        response = json.loads(Path(response_path).read_text())["value"]
        entry = {"case": label, "project_id": target, "status": response["status"], "request": response["request_artifact"], "response": response_path, "project_versions": versions, "before": before, "after": after}
        context.evidence.record("scope-write-denied", entry)
        assert before == after, "Denied scope write changed business state: " + label
        if status == 404:
            assert reply == {"blocking_reasons": [], "code": "NOT_FOUND", "fields": {}, "message": "Workflow resource not found"}
        assert all(project["id"] not in json.dumps(reply) for project in projects.values())
        denied.append(entry)
    context.evidence.record("scope-write-matrix", {"projects": projects, "positive_response": positive_response, "denied": denied})
    # Preserve the later planner-only role denial checks in this same E29 case.
    api.grant(own, "planner", ["planner"])


def run(context):
    api = PlatformHTTP(context)
    context.client = api
    p = api.project("100")
    original = api.get("/projects/" + p)
    projects = {"own": {"id": p, "customer_id": original["customer_id"]}}
    for label, customer in (("same_customer", original["customer_id"]), ("other_customer", "Customer 2")):
        created = api.post("/projects", {**{k: original[k] for k in ("name", "line_id", "product", "mode", "unit", "quantity", "contract")}, "operation_id": context.identifier(label), "customer_id": customer})
        projects[label] = {"id": created["id"], "customer_id": created["customer_id"]}
    q = projects["other_customer"]["id"]
    scope_write_matrix(api, projects)
    api.get("/projects/" + projects["same_customer"]["id"], actor="planner", expected=404)
    api.get("/projects/" + p, anonymous=True, expected=401)
    api.get("/projects/" + p, actor="outsider", expected=404)
    api.get("/projects/" + q, actor="planner", expected=404)
    api.get("/projects/" + p, actor="planner")
    assert api.get("/access", actor="outsider")["allowed"] is False
    api.get("/assets/manufacturing.js?release=development", actor="outsider", expected=403)
    for asset in ("manufacturing.js", "manufacturing.css"):
        actual = api.get("/assets/" + asset + "?release=development", actor="planner")
        assert actual.encode() == (ROOT / "webui/dist" / asset).read_bytes()
    handbook = api.get("/handbook", actor="planner")
    assert handbook["markdown"].encode() == (ROOT / "docs/manufacturing-system-handbook.md").read_bytes()
    assert handbook["sha256"] == hashlib.sha256(handbook["markdown"].encode()).hexdigest()
    shell = api.request("GET", "/manufacturing/", actor="planner")
    assert "Disposable synthetic host" in shell
    shell_headers = json.loads(Path(context.evidence.artifacts[-1]).read_text())["value"]["headers"]
    csp = next(value for key, value in shell_headers.items() if key.lower() == "content-security-policy")
    assert "script-src" in csp and "connect-src" in csp and "default-src 'none'" in csp
    # Host policy protects every legacy endpoint, regardless of frontend role headers.
    for path in ("/projects", "/catalog", "/collaboration", "/systems", "/dashboard"):
        api.request("GET", "/api/v1/manufacturing" + path, actor="planner", headers={"X-Role": "platform_owner", "X-User-ID": api.login("owner")["user_id"]}, expected=403)
    api.request("GET", "/api/v1/manufacturing/projects")
    api.request("GET", "/api/v1/manufacturing/projects", actor="admin")
    api.request("GET", "/api/v1/manufacturing/projects", actor="viewer", expected=403)
    api.get("/unknown-template", actor="planner", expected=403)
    api.request("DELETE", BASE + "/projects", actor="planner", expected=403)
    stage = {"operation_id": context.identifier("stage"), "expected_version": api.get("/projects/" + p)["version"], "action": "project.stage", "stage": "S1", "status": "active", "reason": "Fixture review"}
    for headers in ({"Origin": "https://foreign.invalid"}, {"X-CSRF-Token": "invalid"}):
        api.post(f"/projects/{p}/commands", stage, headers=headers, expected=403)
    api.post(f"/projects/{p}/commands", stage, actor="planner", headers={"X-Role": "platform_owner"}, expected=403)
    api.post(f"/projects/{p}/commands", {**stage, "user_id": api.login("owner")["user_id"]}, expected=422)
    # Admin/manufacturing permission never implies quality qualification.
    api.grant(p, "admin", ["quality"])
    quality = {"action": "first_article.record", "work_order_id": context.identifier("missing-wo"), "unit_ids": [context.identifier("unit")], "test_ids": [context.identifier("test")], "inspection_id": "Synthetic FAI"}
    for actor in ("admin", "production", "owner"):
        api.command(p, actor=actor, expected=403, **quality)
    api.command(p, actor="quality", expected=404, **quality)
    api.grant(p, "quality", ["quality"])
    api.command(p, actor="quality", expected=403, **quality)
    api.grant(p, "quality", ["quality"], ["inspection", "disposition", "quality_release"])
    api.grant(p, "viewer", ["project_owner"])
    api.request("PUT", f"{BASE}/projects/{p}/members/{api.login('planner')['user_id']}", actor="viewer", body={"operation_id": context.identifier("viewer-write"), "expected_version": api.get("/projects/" + p)["version"], "scope": {"kind": "project", "project_id": p}, "roles": ["planner"], "qualifications": [], "active": True, "evidence": "denied"}, expected=403)
    api.control("planner", hard_stale=True)
    api.command(p, "demand.record", actor="planner", expected=503, kind="firm", product="Camera", quantity="1", unit="piece", due_date="2026-12-01", source=api.source("demand"))
    api.control("planner", hard_stale=False)
    api.grant(p, "planner", ["planner", "project_owner"])
    accepted = api.command(p, "demand.record", actor="planner", kind="firm", product="Camera", quantity="1", unit="piece", due_date="2026-12-01", source=api.source("demand"))
    with api.db() as db:
        replay = json.loads(db.execute("SELECT typed_payload FROM audit_events WHERE project_id=? AND object_id=?", (p, accepted["object_id"])).fetchone()[0])
    replay.pop("project_id")
    api.grant(p, "planner", ["planner"], active=False)
    api.post(f"/projects/{p}/commands", replay, actor="planner", expected=404)
    api.control("quality", revoked=True)
    api.get("/projects/" + p, actor="quality", expected=401)
    with api.db() as db:
        assert db.execute("SELECT COUNT(*) FROM audit_events WHERE project_id=? AND action='first_article.record'", (p,)).fetchone()[0] == 0
    api.close()
    # Each bootstrap uses an independent owned DB and real create_app/middleware.
    for variant in ("disabled", "unavailable", "legacy"):
        child = ScenarioContext.isolated(context.directory / "bootstrap", case_id="E29", seed=context.seed, clock=context.clock)
        historical = None
        if variant == "legacy":
            historical = historical_source(child.directory, ROOT, commit="ec41b39bdf8c0b5cc6b0193ed646a44050106ca3", prefix="WORKFLOW_LEGACY_SOURCE", label="legacy")
        probe = PlatformHTTP(child, bootstrap=variant, package_source=historical)
        try:
            result = probe.get("/access", expected=503 if variant == "unavailable" else 200)
            if variant != "unavailable":
                assert result["workflow_available"] is False and result["legacy_access"] is True
                probe.request("GET", "/api/v1/manufacturing/projects")
            probe.get("/projects", expected=503)
            probe.request("GET", "/api/v1/manufacturing/projects", actor="planner", expected=403)
        finally:
            probe.close()
    ui_proof(context, ["src/workflow/api.test.ts", "src/workflow/orders.test.tsx"], ["uses one workflow prefix with CSRF and retires late responses", "retires directory results after leaving the member workspace", "retires pending workflow responses and dirty edits on authentication loss"], "e29-retired")
