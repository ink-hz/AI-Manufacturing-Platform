"""Query engine bounds are enforced at the reader/SQLite boundary."""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4, uuid5

import pytest
from pydantic import ValidationError

from manufacturing_platform.workflow import contracts, queries
from manufacturing_platform.workflow.service import WorkflowService
from manufacturing_platform.workflow.store import WorkflowStore

from .conftest import USERS


@pytest.mark.parametrize("field", ["occurred_at", "recorded_at"])
@pytest.mark.parametrize(
    "value",
    ["2026-10-28T12:34:56", datetime(2026, 10, 28, 12, 34, 56)],  # noqa: DTZ001 - invalid input regression
)
def test_history_rejects_each_naive_timestamp(field, value):
    body = {
        "event_id": 1,
        "actor_id": uuid4(),
        "action": "demand.record",
        "occurred_at": "2026-10-28T12:34:56+08:00",
        "recorded_at": "2026-10-28T04:34:56Z",
    }
    body[field] = value
    with pytest.raises(ValidationError) as error:
        contracts.ObjectHistory(**body)
    assert error.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize(
    "value",
    ["2026-10-28T12:34:56+08:00", datetime.fromisoformat("2026-10-28T12:34:56-04:00")],
)
def test_history_preserves_aware_timestamp_offsets(value):
    history = contracts.ObjectHistory(
        event_id=1,
        actor_id=uuid4(),
        action="demand.record",
        occurred_at=value,
        recorded_at=value,
    )
    assert history.occurred_at.utcoffset() is not None
    assert history.recorded_at.utcoffset() == history.occurred_at.utcoffset()
    assert (
        contracts.ObjectHistory.model_validate_json(history.model_dump_json())
        == history
    )


def test_pages_and_dashboard_bound_source_reads_and_count_all_authorized_rows(workflow):
    # Test readers project real API-generated audit rows. No test business table or
    # fake successful domain action is installed in the production registry.
    projects = [workflow.create_project(), workflow.create_project()]
    for project in projects:
        for _ in range(60):
            workflow.grant(project["id"], "planner", ["planner"])
    project_ids = sorted(UUID(project["id"]) for project in projects)
    registry = queries.ObjectRegistry()
    reads, counts, sql_statements = [], [], []

    class DemandValue(contracts.DomainValue):
        kind: Literal["demand"]

    class OrderValue(contracts.DomainValue):
        kind: Literal["order_line"]

    def register_reader(kind, model):
        def count(tx, project_id):
            counts.append((project_id, kind))
            return tx.execute(
                "SELECT COUNT(*) FROM audit_events WHERE project_id=?",
                (str(project_id),),
            ).fetchone()[0]

        def summaries(tx, project_id, limit, offset):
            reads.append((project_id, kind, limit, offset))
            tx.set_trace_callback(sql_statements.append)
            rows = tx.execute(
                "SELECT id, action FROM audit_events WHERE project_id=? ORDER BY id LIMIT ? OFFSET ?",
                (str(project_id), limit, offset),
            ).fetchall()
            tx.set_trace_callback(None)
            return [
                contracts.ObjectSummary(
                    id=uuid5(project_id, str(row["id"])),
                    project_id=project_id,
                    kind=kind,
                    title=row["action"],
                    state="recorded",
                    version=1,
                )
                for row in rows
            ]

        registry.register(
            kind,
            model,
            count=count,
            summaries=summaries,
            detail=lambda tx, pid, oid: None,
        )

    register_reader(contracts.ObjectKind.demand, DemandValue)
    register_reader(contracts.ObjectKind.order_line, OrderValue)
    store = WorkflowStore(
        str(workflow.paths.domain),
        str(workflow.paths.authority),
        {"id": "workflow-test", "mode": "test", "label": "Workflow test"},
    )
    service = WorkflowService(store, lambda uid: True, object_registry=registry)
    actor = contracts.Actor(
        user_id=USERS["owner"],
        display_name="owner",
        configuration_admin=True,
        read_only=False,
    )
    page = service.objects(
        actor, project_ids[0], contracts.ObjectKind.demand, limit=7, offset=50
    )
    assert page.total == 61
    assert len(page.items) == 7
    assert reads == [(project_ids[0], contracts.ObjectKind.demand, 7, 50)]
    assert len(sql_statements) == 1 and "LIMIT 7 OFFSET 50" in sql_statements[0]
    with workflow.db() as db:
        row_id = db.execute(
            "SELECT id FROM audit_events WHERE project_id=? ORDER BY id LIMIT 1 OFFSET 50",
            (str(project_ids[0]),),
        ).fetchone()[0]
    assert page.items[0].id == uuid5(project_ids[0], str(row_id))

    reads.clear()
    counts.clear()
    sql_statements.clear()
    board = service.dashboard(actor)
    assert board.counts == {"demand": 122, "order_line": 122}
    assert board.project_count == 2 and len(board.cards) == 100
    assert counts == [(pid, kind) for pid in project_ids for kind in registry.kinds]
    assert reads == [
        (project_ids[0], contracts.ObjectKind.demand, 100, 0),
        (project_ids[0], contracts.ObjectKind.order_line, 39, 0),
    ]
    assert len(sql_statements) == 2
    assert "LIMIT 100 OFFSET 0" in sql_statements[0]
    assert "LIMIT 39 OFFSET 0" in sql_statements[1]

    reads.clear()
    scoped = service.dashboard(actor, project_ids[1])
    assert scoped.counts == {"demand": 61, "order_line": 61}
    assert len(scoped.cards) == 100
    assert all(read[0] == project_ids[1] for read in reads)
    empty = service.objects(
        actor, project_ids[0], contracts.ObjectKind.demand, limit=7, offset=1000
    )
    assert empty.total == 61 and empty.items == []


def test_registry_rejects_reader_that_exceeds_requested_page(workflow):
    class Value(contracts.DomainValue):
        kind: Literal["demand"]

    registry = queries.ObjectRegistry()
    project_id = UUID(workflow.create_project()["id"])
    summary = contracts.ObjectSummary(
        id=uuid4(),
        project_id=project_id,
        kind="demand",
        title="test reader",
        state="recorded",
        version=1,
    )
    registry.register(
        contracts.ObjectKind.demand,
        Value,
        count=lambda tx, pid: 2,
        summaries=lambda tx, pid, limit, offset: [summary, summary],
        detail=lambda tx, pid, oid: None,
    )
    with workflow.db() as tx, pytest.raises(ValueError, match="page limit"):
        registry.summaries(
            tx, project_id, contracts.ObjectKind.demand, limit=1, offset=0
        )
