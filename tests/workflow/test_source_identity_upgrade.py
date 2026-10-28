"""Canonical A2/A3 identity remains distinct from immutable source evidence."""

from .conftest import BASE
from .test_orders import approve, record, register
from manufacturing_platform.workflow.contracts import SourceRef


def old_database(tmp_path, *, collision):
    """Genuine pre-D3 API execution, never fabricated successful SQL rows."""
    import io
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys
    import tarfile
    from uuid import uuid4
    from .conftest import USERS
    repository = Path(__file__).resolve().parents[2]
    source = tmp_path / "d2-source"
    source.mkdir()
    archive = subprocess.check_output(["git", "-C", str(repository), "archive", "a96aa66e3fc00ca099c08e2177eae19939a5696b", "src"])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(source, filter="data")
    body = {"operation_id": str(uuid4()), "name": "Old", "line_id": "Line", "product": "Camera", "customer_id": "Customer", "mode": "internal", "unit": {"code": "piece", "scale": 0}, "quantity": "100", "contract": {key: "unknown" for key in ("customer_approval_required", "customer_release_required", "acceptance_required", "customer_revision", "internal_revision", "material_ownership_rules")}}
    sources = [{"system": " ERP ", "object_type": "demand", "external_id": " Old-Demand ", "version": 1, "mode": "manual", "occurred_at": "2026-10-28T00:00:00Z", "collected_at": "2026-10-28T00:00:00Z", "evidence": "Original source evidence"}]
    if collision:
        sources.append({**sources[0], "system": "erp", "external_id": "Old-Demand"})
    config = {"database_root": str(tmp_path), "body": body, "actor": {"user_id": str(USERS["owner"]), "display_name": "owner", "read_only": False, "configuration_admin": True}, "dataset": {"id": "workflow-test", "mode": "test", "label": "Workflow test"}, "demands": [{"operation_id": str(uuid4()), "action": "demand.record", "kind": "firm", "product": "Camera", "quantity": "100", "unit": "piece", "due_date": "2026-12-01", "source": source} for source in sources]}
    path = tmp_path / "d2-input.json"
    path.write_text(json.dumps(config))
    result = subprocess.run([sys.executable, str(Path(__file__).with_name("d3") / "historical_api.py"), str(path), str(tmp_path / "d2-output.json")], env={**os.environ, "PYTHONPATH": str(source / "src"), "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return tmp_path / "domain.db"


def test_actual_schema15_key_upgrade_preserves_raw_business_history(tmp_path):
    import sqlite3
    from manufacturing_platform.workflow.store import WorkflowStore
    path = old_database(tmp_path, collision=False)
    with sqlite3.connect(path) as db:
        before = {t: db.execute(f"SELECT * FROM {t}").fetchall() for t in ("operations", "audit_events")}
        source = db.execute("SELECT source_json FROM demands").fetchall()
        assert db.execute("SELECT version FROM schema_version").fetchone() == (15,)
    store = WorkflowStore(str(path), str(tmp_path / "authority.db"), {"id": "workflow-test", "mode": "test", "label": "Workflow test"})
    with store.transaction() as db:
        assert tuple(db.execute("SELECT source_system,source_type,source_external_id FROM demands").fetchone()) == ("erp", "demand", "Old-Demand")
        assert db.execute("SELECT version FROM schema_version").fetchone()[0] == 17
        for table, rows in before.items():
            assert list(map(tuple, db.execute(f"SELECT * FROM {table}"))) == rows
        assert list(map(tuple, db.execute("SELECT source_json FROM demands"))) == source


def test_actual_schema15_collision_refuses_entire_migration(tmp_path):
    import sqlite3
    import pytest
    from manufacturing_platform.workflow.store import WorkflowStore
    path = old_database(tmp_path, collision=True)
    with sqlite3.connect(path) as db:
        before = list(db.iterdump())
    store = WorkflowStore(str(path), str(tmp_path / "authority.db"), {"id": "workflow-test", "mode": "test", "label": "Workflow test"})
    with pytest.raises(ValueError, match="canonical source identity collision"):
        with store.transaction():
            pass
    with sqlite3.connect(path) as db:
        assert list(db.iterdump()) == before


def test_demand_alias_identity_conflicts_and_raw_source_is_preserved(workflow):
    pid = workflow.create_project()["id"]
    source = workflow.source(" Demand-X ", system=" ERP ")
    first = workflow.command(pid, "demand.record", kind="firm", product="Camera", quantity="100", unit="piece", due_date="2026-12-01", source=source)
    duplicate = workflow.command(pid, "demand.record", kind="firm", product="Camera", quantity="100", unit="piece", due_date="2026-12-01", source=workflow.source("Demand-X", system="erp", version=2), expected_status=409)
    assert duplicate["code"] == "SOURCE_CONFLICT"
    with workflow.db() as db:
        row = db.execute("SELECT * FROM demands WHERE id=?", (first["object_id"],)).fetchone()
        assert (row["source_system"], row["source_type"], row["source_external_id"]) == ("erp", "demand", "Demand-X")
    detail = workflow.client().get(f"{BASE}/projects/{pid}/objects/demand/{first['object_id']}").json()
    assert detail["value"]["source"] == SourceRef.model_validate(source).model_dump(mode="json")
    # external IDs preserve case: a distinct real source remains distinct.
    record(workflow, pid, external_id="demand-x")


def test_order_amendment_accepts_canonical_alias_but_uuid_payload_remains_exact(workflow):
    pid = workflow.create_project()["id"]
    demand = record(workflow, pid)
    approve(workflow, pid, demand)
    oid = register(workflow, pid, demand)
    source = workflow.source(" order-1 ", system=" ERP ", object_type=" ORDER_LINE ", version=2)
    changed = workflow.command(pid, "order.change", order_line_id=oid, new_quantity="90", new_due_date="2026-12-01", cancel=False, reason="Documented amendment", source=source)
    assert changed["object_type"] == "commitment_change"
    with workflow.db() as db:
        row = db.execute("SELECT typed_payload FROM audit_events WHERE action='order.change'").fetchone()
    import json
    payload = json.loads(row[0])
    payload.pop("project_id")
    payload["source"]["system"] = "erp"
    response = workflow.client().post(f"{BASE}/projects/{pid}/commands", json=payload)
    assert response.status_code == 409 and response.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_work_order_alias_identity_conflicts(workflow):
    pid, order, wo, revision = workflow.order_workorder(quantity="5")
    # A second project has spare demand capacity but cannot reuse the first source.
    other = workflow.create_project()
    demand = record(workflow, other["id"], external_id="other-demand")
    approve(workflow, other["id"], demand)
    other_order = register(workflow, other["id"], demand, external_id="other-order")
    other_revision = workflow.revision(other["id"])
    workflow.grant(other["id"], "planner", ["planner"])
    original = workflow.object(pid["id"], "work_order", wo["id"])
    source = original["source"]
    alias = {**source, "system": " " + source["system"].upper() + " ", "external_id": " " + source["external_id"] + " ", "version": 2}
    result = workflow.command(other["id"], "work_order.register", actor_name="planner", order_line_id=other_order, revision_id=other_revision["id"], quantity="1", unit="piece", purpose="production", trial_quantity="1", planned_start=original["planned_start"], planned_end=original["planned_end"], source=alias, expected_status=409)
    assert result["code"] == "SOURCE_CONFLICT"
