import json
import sqlite3
from pathlib import Path
from uuid import uuid4
from decimal import Decimal
import pytest
from pydantic import ValidationError
from manufacturing_platform.workflow.contracts import ProjectCreate, ProjectDetail
from manufacturing_platform.workflow.service import digest

from .conftest import BASE, USERS, WorkflowHarness
from .d3.historical import create_historical
from .test_orders import record, approve, register


@pytest.mark.parametrize("quantity,scale", [("100", 0), ("100", 2), ("100.00", 2)])
def test_actual_a1_api_create_upgrade_replays_original_snapshot(tmp_path, quantity, scale):
    fixture = WorkflowHarness(tmp_path)
    body = {
        "operation_id": str(uuid4()), "name": "Historical Camera", "line_id": "Line 1",
        "product": "Camera", "customer_id": "Customer 1", "mode": "internal",
        "unit": {"code": "piece", "scale": scale}, "quantity": quantity,
        "contract": {key: "unknown" for key in ("customer_approval_required", "customer_release_required", "acceptance_required", "customer_revision", "internal_revision", "material_ownership_rules")},
    }
    old = create_historical(tmp_path, Path(__file__).resolve().parents[2], {
        "database_root": str(tmp_path), "body": body,
        "actor": {"user_id": str(USERS["owner"]), "display_name": "owner", "read_only": False, "configuration_admin": True},
        "dataset": {"id": "workflow-test", "mode": "test", "label": "Workflow test"},
    })["result"]
    assert "stages" not in old and "summary" not in old
    validated_request = ProjectCreate.model_validate(body)
    with pytest.raises(ValidationError) as missing:
        ProjectDetail.model_validate(old)
    assert {(e["loc"], e["type"]) for e in missing.value.errors()} == {
        (("stages",), "missing"), (("summary",), "missing")
    }
    with sqlite3.connect(fixture.paths.domain) as db:
        assert db.execute("SELECT version FROM schema_version").fetchone() == (1,)
        operations = db.execute("SELECT * FROM operations").fetchall()
        assert operations[0][3] == digest({"action": "project.create", **validated_request.model_dump(mode="json")})
        audits = db.execute("SELECT * FROM audit_events").fetchall()
    client = fixture.client()
    assert client.get(BASE + "/projects/" + old["id"]).status_code == 200
    replay = client.post(BASE + "/projects", json=body)
    assert replay.status_code == 200, replay.text
    assert {k: replay.json()[k] for k in old} == old
    assert Decimal(replay.json()["summary"]["current_order_quantity"]) == 0
    # Later state does not turn replay into a current snapshot.
    demand = record(fixture, old["id"])
    with sqlite3.connect(fixture.paths.domain) as db:
        other_operation = json.loads(db.execute("SELECT typed_payload FROM audit_events WHERE object_id=? AND action='demand.record'", (demand,)).fetchone()[0])["operation_id"]
        conflicting_operation = db.execute("SELECT * FROM operations WHERE operation_id=?", (other_operation,)).fetchall()
        conflicting_audit = db.execute("SELECT * FROM audit_events WHERE object_id=? AND action='demand.record'", (demand,)).fetchall()
    assert client.post(BASE + "/projects", json={**body, "operation_id": other_operation}).status_code == 409
    with sqlite3.connect(fixture.paths.domain) as db:
        assert db.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
    approve(fixture, old["id"], demand)
    register(fixture, old["id"], demand)
    assert Decimal(client.get(BASE + "/projects/" + old["id"]).json()["summary"]["current_order_quantity"]) == 100
    again = client.post(BASE + "/projects", json=body)
    assert again.json() == replay.json()
    assert client.post(BASE + "/projects", json={**body, "name": "Changed"}).json()["code"] == "IDEMPOTENCY_CONFLICT"
    fixture.grant(old["id"], "owner", ["project_owner"], active=False)
    assert client.post(BASE + "/projects", json=body).json() == replay.json()
    # Current role demotion blocks replay; the frozen A1 source is unchanged.
    fixture.configuration_admins.remove("owner")
    assert client.get(BASE + "/projects/" + old["id"]).status_code == 404
    assert client.post(BASE + "/projects", json=body).status_code == 403
    assert client.post(BASE + "/projects", json={**body, "operation_id": other_operation}).status_code == 403
    assert client.post(BASE + "/projects", json={**body, "name": "Changed after revocation"}).status_code == 403
    with sqlite3.connect(fixture.paths.domain) as db:
        assert db.execute("SELECT * FROM operations WHERE operation_id=?", (body["operation_id"],)).fetchall() == operations
        assert db.execute("SELECT * FROM audit_events WHERE action='project.create'").fetchall() == audits
        assert db.execute("SELECT * FROM operations WHERE operation_id=?", (other_operation,)).fetchall() == conflicting_operation
        assert db.execute("SELECT * FROM audit_events WHERE object_id=? AND action='demand.record'", (demand,)).fetchall() == conflicting_audit


def test_pinned_actual_a1_export_runs_api_without_git_and_refuses_changed_files(tmp_path, monkeypatch):
    import hashlib
    from .d3.historical import historical_source
    exported = tmp_path / "exported"
    exported.mkdir()
    source = historical_source(exported, Path(__file__).resolve().parents[2])
    manifest = exported / "a1-provenance.json"
    monkeypatch.setenv("WORKFLOW_A1_SOURCE_MANIFEST", str(manifest))
    monkeypatch.setenv("WORKFLOW_A1_SOURCE_MANIFEST_SHA256", hashlib.sha256(manifest.read_bytes()).hexdigest())
    monkeypatch.setenv("WORKFLOW_A1_SOURCE_ROOT", str(source))
    monkeypatch.setenv("WORKFLOW_SOURCE_MANIFEST", "gitless-candidate-marker")
    target = tmp_path / "gitless"
    target.mkdir()
    body = {"operation_id": str(uuid4()), "name": "Pinned A1", "line_id": "Line", "product": "Camera", "customer_id": "Customer", "mode": "internal", "unit": {"code": "piece", "scale": 0}, "quantity": "1", "contract": {key: "unknown" for key in ("customer_approval_required", "customer_release_required", "acceptance_required", "customer_revision", "internal_revision", "material_ownership_rules")}}
    result = create_historical(target, Path("/no-git-checkout"), {"database_root": str(target), "body": body, "actor": {"user_id": str(USERS["owner"]), "display_name": "synthetic", "read_only": False, "configuration_admin": True}, "dataset": {"id": "pinned-history", "mode": "test", "label": "Pinned history"}})
    assert result["status"] == 200 and "summary" not in result["result"]
    changed = source / "src/manufacturing_platform/__init__.py"
    changed.write_text(changed.read_text() + "\n# changed fixture\n")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        historical_source(target, Path("/no-git-checkout"))
