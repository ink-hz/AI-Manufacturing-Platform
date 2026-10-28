"""Private historical corruption witnesses; business records originate in APIs."""

import json
import sqlite3
import pytest
from .conftest import BASE
from .test_orders import record
from .test_execution import running_execution


def poison_audit(workflow, action, project_id, object_id, mutation):
    with sqlite3.connect(workflow.paths.domain) as db:
        row = db.execute("SELECT id,typed_payload FROM audit_events WHERE action=? AND project_id=? AND object_id=? ORDER BY id LIMIT 1", (action, project_id, object_id)).fetchone()
        payload = json.loads(row[1])
        payload["source"]["external_id"] = "foreign-secret-source"
        payload["source"]["evidence"] = "foreign-secret-evidence"
        if mutation == "missing_source":
            payload.pop("source")
            payload["evidence"] = "foreign-secret-evidence"
        elif mutation == "foreign_project":
            payload["project_id"] = "00000000-0000-4000-8000-000000000999"
        elif mutation == "wrong_action":
            payload["action"] = "demand.review"
        raw = json.dumps(payload)
        db.execute("UPDATE audit_events SET typed_payload=? WHERE id=?", (raw, row[0]))
    return row[0], raw


@pytest.mark.parametrize("kind", ["demand", "work_order", "unit"])
@pytest.mark.parametrize("mutation", ["changed_source", "missing_source", "foreign_project", "wrong_action"])
def test_remaining_source_histories_bind_original_operation_and_object(workflow, kind, mutation):
    if kind == "demand":
        pid = workflow.create_project()["id"]
        ident = record(workflow, pid)
        action = "demand.record"
    elif kind == "work_order":
        project, _, wo, _ = workflow.order_workorder()
        pid, ident, action = project["id"], wo["id"], "work_order.register"
    else:
        project, wo, unit, authority, body = running_execution(workflow)
        source = workflow.source("history-execution", object_type="execution", system="mes")
        source["occurred_at"] = body["occurred_at"]
        result = workflow.command(project["id"], "execution.record", actor_name="production", source=source, **body)
        pid, ident, action = project["id"], result["object_id"], "execution.record"
    url = f"{BASE}/projects/{pid}/objects/{kind}/{ident}"
    original = workflow.client().get(url).json()
    event = next(e for e in original["history"] if e["action"] == action)
    assert event["evidence"] and event["evidence"][0]["source"] is not None
    # Historical evidence does not borrow current author qualification.
    if kind == "unit":
        workflow.grant(pid, "production", ["production"], active=False)
        assert next(e for e in workflow.client().get(url).json()["history"] if e["action"] == action)["evidence"] == event["evidence"]
    event_id, private_raw = poison_audit(workflow, action, pid, ident, mutation)
    safe = workflow.client().get(url)
    assert safe.status_code == 200, safe.text
    assert "foreign-secret" not in safe.text
    after = next(e for e in safe.json()["history"] if e["event_id"] == event_id)
    assert {k: after[k] for k in ("event_id", "actor_id", "action", "occurred_at", "recorded_at")} == {k: event[k] for k in ("event_id", "actor_id", "action", "occurred_at", "recorded_at")}
    with workflow.db() as db:
        assert db.execute("SELECT typed_payload FROM audit_events WHERE id=?", (event_id,)).fetchone()[0] == private_raw
