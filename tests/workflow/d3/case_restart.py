"""E31 actual PF critical checkpoints and genuine A1 immutable replay."""

from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
from ..scenarios.base import ROOT, ScenarioContext
from ..scenarios import business as b
from ..scenarios.delivery_recovery_cases import checkpoint
from ..scenarios.orders_supply_cases import material_case
from .pf_client import PlatformHTTP
from .historical import create_historical
from .proof_support import api_order, snapshot


def host_checkpoint(flow, name):
    api, pid = flow.api, flow.project
    dashboard = api.get("/dashboard?project_id=" + pid)
    with api.db() as db:
        for kind, table in (("demand", "demands"), ("order_line", "order_lines"), ("work_order", "work_orders"), ("unit", "units"), ("shipment", "shipments"), ("exchange", "exchanges")):
            assert dashboard["counts"][kind] == db.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (pid,)).fetchone()[0]
    authority_before = snapshot(api.paths.authority) if api.paths.authority.exists() else None
    checkpoint(flow, name)
    assert api.get("/dashboard?project_id=" + pid) == dashboard
    authority_after = snapshot(api.paths.authority) if api.paths.authority.exists() else None
    assert authority_after == authority_before
    api.context.evidence.record("pf-checkpoint-consistency", {"phase": name, "project_id": pid, "dashboard": dashboard, "authority_before": authority_before, "authority_after": authority_after})


def historical_replay(context):
    child = ScenarioContext.isolated(context.directory / "historical", case_id="E31", seed=context.seed, clock=context.clock)
    from uuid import NAMESPACE_URL, uuid5
    owner = str(uuid5(NAMESPACE_URL, f"fixture:{context.seed}:owner"))
    body = {"operation_id": child.identifier("a1-create"), "name": "Historical Camera", "line_id": "Line 1", "product": "Camera", "customer_id": "Customer 1", "mode": "internal", "unit": {"code": "piece", "scale": 0}, "quantity": "100", "contract": {key: "unknown" for key in ("customer_approval_required", "customer_release_required", "acceptance_required", "customer_revision", "internal_revision", "material_ownership_rules")}}
    old = create_historical(child.directory, ROOT, {"database_root": str(child.directory), "body": body, "actor": {"user_id": owner, "display_name": "owner", "read_only": False, "configuration_admin": True}, "dataset": {"id": child.dataset_id, "mode": "test", "label": "Simulated workflow acceptance"}})["result"]
    (child.directory / "domain.db").rename(child.paths.domain)
    from manufacturing_platform.workflow.contracts import ProjectCreate, ProjectDetail
    from manufacturing_platform.workflow.service import digest
    from pydantic import ValidationError
    request = ProjectCreate.model_validate(body)
    try:
        ProjectDetail.model_validate(old)
    except ValidationError as error:
        assert {(tuple(v["loc"]), v["type"]) for v in error.errors()} == {(("summary",), "missing"), (("stages",), "missing")}
    else:
        raise AssertionError("Actual A1 snapshot unexpectedly matches current result schema")
    with sqlite3.connect(child.paths.domain) as db:
        assert db.execute("SELECT version FROM schema_version").fetchone() == (1,)
        operation = db.execute("SELECT * FROM operations").fetchall()
        audits = db.execute("SELECT * FROM audit_events").fetchall()
        assert operation[0][3] == digest({"action": "project.create", **request.model_dump(mode="json")})
    api = PlatformHTTP(child)
    try:
        api.get("/projects/" + old["id"])
        replay = api.post("/projects", body)
        assert {k: replay[k] for k in old} == old
        api_order(api, old["id"], 100)
        assert api.get("/projects/" + old["id"])["summary"]["current_order_quantity"] == "100"
        assert api.post("/projects", body) == replay and replay["summary"]["current_order_quantity"] == "0"
        conflict = api.post("/projects", {**body, "name": "Changed"}, expected=409)
        assert conflict["code"] == "IDEMPOTENCY_CONFLICT"
        api.grant(old["id"], "owner", ["project_owner"], active=False)
        with api.db() as db:
            command_body = json.loads(db.execute(
                "SELECT typed_payload FROM audit_events WHERE project_id=? AND actor_id=? AND action='demand.record' ORDER BY id LIMIT 1",
                (old["id"], owner),
            ).fetchone()[0])
        command_body.pop("project_id")
        # A responsibility grant is not the trusted host's global admin role.
        # Replay must retain the frozen result and never duplicate business writes.
        revocation_before = snapshot(child.paths.domain)
        revoked_replay = api.post("/projects", body)
        assert revoked_replay == replay and {k: revoked_replay[k] for k in old} == old
        revoked_conflict = api.post("/projects", {**body, "name": "Changed after revocation"}, expected=409)
        assert revoked_conflict["code"] == "IDEMPOTENCY_CONFLICT"
        command_path = "/projects/" + old["id"] + "/commands"
        command_replay = api.post(command_path, command_body)
        assert command_replay["replayed"] is True
        revocation_after = snapshot(child.paths.domain)
        assert revocation_after == revocation_before
        # Change the actual trusted provider role; headers/payload cannot demote
        # or elevate the server-owned actor. The same accepted operations deny.
        demotion_before = snapshot(child.paths.domain)
        api.control("owner", role="member")
        demoted_access = api.get("/access")
        assert demoted_access["configuration_admin"] is False
        assert demoted_access["project_ids"] == []
        api.get("/projects/" + old["id"], expected=404)
        api.post("/projects", body, expected=403)
        api.post("/projects", {**body, "name": "Changed after demotion"}, expected=403)
        api.post(command_path, command_body, expected=404)
        demotion_after = snapshot(child.paths.domain)
        assert demotion_after == demotion_before
        with api.db() as db:
            assert list(map(tuple, db.execute("SELECT * FROM operations WHERE operation_id=?", (body["operation_id"],)))) == operation
            assert list(map(tuple, db.execute("SELECT * FROM audit_events WHERE action='project.create'"))) == audits
        child.evidence.record_db_snapshot(child.paths.domain)
        child.evidence.record("historical-replay", {
            "old_result": old, "replay": replay, "live_order_quantity": "100",
            "payload_conflict": conflict, "original_operations": operation, "original_audits": audits,
            "revoked_replay_status": 200, "revoked_replay": revoked_replay,
            "revoked_payload_conflict": revoked_conflict, "command_replay": command_replay,
            "revocation_before": revocation_before, "revocation_after": revocation_after,
            "demoted_access": demoted_access, "demoted_create_status": 403,
            "demoted_read_status": 404, "demoted_command_replay_status": 404,
            "demotion_before": demotion_before, "demotion_after": demotion_after,
        })
    finally:
        api.close()


def run(context):
    api = PlatformHTTP(context)
    context.client = api
    pid = api.project("100")
    flow = b.Flow(api, pid, "", 100, "Camera")
    host_checkpoint(flow, "pending-order-and-grants")
    flow.order = api_order(api, pid, 100)
    # Two genuine concurrent project mutations use one captured CAS version.
    version = api.get("/projects/" + pid)["version"]
    def edit(index):
        return api.post(f"/projects/{pid}/commands", {"operation_id": context.identifier("concurrent-edit-" + str(index)), "expected_version": version, "action": "project.stage", "stage": "S1", "status": "active", "reason": "Concurrent editor " + str(index)}, expected=(200, 409))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, (1, 2)))
    assert sum(r.get("code") == "VERSION_CONFLICT" for r in results) == 1
    context.evidence.record("concurrent-project-cas", {"version": version, "results": results})
    rid = b.revision(flow)
    wid = b.work_order(flow, 100, rid)
    b.prepare(flow)
    # Full source-backed first article, then fresh host before bulk continuation.
    b.start(flow, wid, flow.units[:1])
    b.execution(flow, flow.units[0], flow.lots[0])
    b.measure(flow, flow.units[0])
    api.command(pid, "first_article.record", actor="quality", work_order_id=wid, unit_ids=flow.units[:1], test_ids=[flow.tests[flow.units[0]]], inspection_id=context.identifier("FAI"))
    host_checkpoint(flow, "first-article-before-bulk")
    b.start(flow, wid, flow.units[1:], mode="bulk")
    for uid in flow.units[1:]:
        b.execution(flow, uid, flow.lots[0])
        b.measure(flow, uid)
    b.release(flow)
    shipment = b.ship(flow, flow.units[:60])["object_id"]
    assert api.object(pid, "order_line", flow.order)["shipped"] == "60"
    assert api.object(pid, "order_line", flow.order)["accepted"] == "0"
    host_checkpoint(flow, "shipment60-before-acceptance")
    b.accept(flow, shipment, 60)
    second = b.ship(flow, flow.units[60:])["object_id"]
    b.accept(flow, second, 40)
    assert api.object(pid, "order_line", flow.order)["accepted"] == "100"
    # Separate original 80 reservation checkpoint: actual authority commits,
    # platform receives no receipt, fresh host queries and resumes exactly once.
    reserved, req, lid, _ = material_case(context, qualified="80")
    intent = b.reserve(reserved, req, lid, "80", dispatch=False)
    api.authority("configure_fault", name="timeout_after_commit")
    api.command(reserved.project, "exchange.dispatch", actor="planner", exchange_id=intent["exchange_id"])
    unresolved = api.object(reserved.project, "exchange", intent["exchange_id"])
    assert unresolved["phase"] == "unknown"
    with api.db() as db:
        request = json.loads(db.execute("SELECT request_json FROM exchanges WHERE id=?", (intent["exchange_id"],)).fetchone()[0])
    api.authority("configure_fault", name="none")
    # Concurrent retries at the real stateful external-system boundary.
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _: api.authority("submit", request=request), range(2)))
    assert receipts[0] == receipts[1]
    host_checkpoint(reserved, "authority-commit-before-platform-receipt")
    api.command(reserved.project, "exchange.query", actor="planner", exchange_id=intent["exchange_id"])
    assert api.object(reserved.project, "exchange", intent["exchange_id"])["phase"] == "accepted"
    count = api.authority("operation_count", business_key=request["business_key"])
    assert count == 1
    assert api.object(reserved.project, "reservation", intent["object_id"])["confirmed"] == "80"
    context.evidence.record("idempotent-resume", {"project": reserved.project, "exchange": intent["exchange_id"], "business_key": request["business_key"], "authority_count": count, "quantity": "80", "concurrent_receipts": receipts})
    context.evidence.record_db_snapshot(context.paths.domain)
    context.evidence.record_authority_snapshot(context.paths.authority)
    api.close()
    historical_replay(context)
