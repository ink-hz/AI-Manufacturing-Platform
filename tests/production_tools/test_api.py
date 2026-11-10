from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO
from threading import Event, Thread
from typing import get_args
from uuid import UUID, uuid4

import pytest

from manufacturing_platform.production_tools.contracts import (
    EvidenceObject,
    ProductionToolsConfig,
    SourceBinding,
    SourceKind,
    SourceResult,
)
from manufacturing_platform.workflow.contracts import DomainError

BASE = "/api/v1/manufacturing/workflow/projects"
PARAMS = {"start": "2026-11-09T00:00:00Z", "end": "2026-11-10T00:00:00Z"}


class FakeSource:
    capabilities = frozenset((*get_args(SourceKind), "evidence_content"))

    def __init__(self):
        self.calls = []
        self.pause = None
        self.stream = BytesIO(b"evidence bytes")
        self.opened = False
        self.size = None
        self.failure = None

    def query(self, binding, query):
        self.calls.append((binding, query))
        if self.pause:
            self.pause()
        if self.failure:
            raise self.failure
        return SourceResult(
            query.kind,
            [{"sn": "SN-1"}],
            datetime.now(UTC),
            query.model_dump(mode="json", exclude_none=True),
            True,
            None,
            None,
        )

    def evidence(self, binding, source_log_id, *, before_open=None):
        self.calls.append((binding, source_log_id))
        if self.pause:
            self.pause()
        if before_open:
            before_open()
        if source_log_id != 1:
            raise DomainError("SOURCE_NOT_FOUND", 404, "Source evidence is unavailable")
        self.opened = True
        return EvidenceObject(self.stream, self.size, "untrusted\r\nfilename.html")


def configure(workflow, project, source=None, **binding_changes):
    source = source or FakeSource()
    scope = replace(
        SourceBinding(
            "workflow-test", UUID(project["id"]), "native", "1", "v1", "project/"
        ),
        **binding_changes,
    )
    workflow.production_tools = ProductionToolsConfig(
        source,
        {scope.project_id: scope},
        str(workflow.paths.domain.parent / "observations.db"),
    )
    workflow.reopen()
    return source


def url(project, suffix):
    return f"{BASE}/{project['id']}/production-tools/{suffix}"


def test_unconfigured_status_is_still_project_scoped(workflow):
    project = workflow.create_project()
    path = url(project, "status")
    assert workflow.client("outsider").get(path).status_code == 404
    response = workflow.client().get(path)
    assert response.status_code == 200
    assert response.json() == {
        "project_id": project["id"],
        "configured": False,
        "capabilities": {
            kind: {"available": False, "reason": "PRODUCTION_TOOLS_UNCONFIGURED"}
            for kind in (*get_args(SourceKind), "evidence_content")
        },
    }
    assert "no-store" in response.headers["cache-control"]


def test_configured_reads_and_all_seven_routes_are_protected(workflow):
    project = workflow.create_project()
    workflow.grant(project["id"], "quality", ["quality"])
    workflow.read_only.add("quality")
    source = configure(workflow, project)
    with workflow.db() as db:
        before = {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("test_runs", "quality_releases", "audit_events")
        }
    status = workflow.client("quality").get(url(project, "status"))
    assert status.json()["configured"] is True
    assert all(
        item == {"available": True, "reason": None}
        for item in status.json()["capabilities"].values()
    )
    assert source.calls == []
    routes = [
        ("observations", {**PARAMS, "kind": "production"}),
        ("catalog/software", {}),
        ("evidence", PARAMS),
        ("statistics", {**PARAMS, "kind": "stopover"}),
    ]
    for path, params in routes:
        count = len(source.calls)
        assert (
            workflow.client("outsider")
            .get(url(project, path), params=params)
            .status_code
            == 404
        )
        assert len(source.calls) == count
        response = workflow.client("quality").get(url(project, path), params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        assert set(page) == {
            "snapshot_id",
            "project_id",
            "source_kind",
            "captured_at",
            "complete",
            "truncation_reason",
            "next_before_id",
            "filters",
            "redacted_fields",
            "items",
            "offset",
            "limit",
            "captured_count",
            "has_more",
            "expires_at",
        }
        assert page["captured_count"] == 1
        snapshot = url(project, f"snapshots/{page['snapshot_id']}")
        assert workflow.client("outsider").get(snapshot).status_code == 404
        assert workflow.client("quality").get(snapshot).json() == page
    assert (
        workflow.client("outsider").get(url(project, "evidence/1/content")).status_code
        == 404
    )
    assert not source.opened
    response = workflow.client("quality").get(url(project, "evidence/1/content"))
    assert response.status_code == 200 and response.content == b"evidence bytes"
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "attachment;" in response.headers["content-disposition"]
    assert "no-store" in response.headers["cache-control"]
    assert source.stream.closed
    with workflow.db() as db:
        assert before == {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in before
        }


def test_snapshot_revocation_rebinding_and_wrong_project(workflow):
    project, other = workflow.create_project(), workflow.create_project()
    workflow.grant(project["id"], "quality", ["quality"])
    configure(workflow, project)
    response = workflow.client("quality").get(url(project, "catalog/software"))
    sid = response.json()["snapshot_id"]
    assert workflow.client().get(url(other, f"snapshots/{sid}")).status_code == 404
    assert (
        workflow.client().get(url(project, f"snapshots/{uuid4()}")).status_code == 404
    )
    workflow.grant(project["id"], "quality", [], active=False)
    assert (
        workflow.client("quality").get(url(project, f"snapshots/{sid}")).status_code
        == 404
    )
    configure(workflow, project, revision="v2")
    assert workflow.client().get(url(project, f"snapshots/{sid}")).status_code == 404
    assert workflow.client().get(url(project, "evidence/2/content")).status_code == 404


def test_slow_query_rechecks_live_grants_before_persistence(workflow):
    project = workflow.create_project()
    workflow.grant(project["id"], "quality", ["quality"])
    source = configure(workflow, project)
    source.pause = lambda: workflow.grant(project["id"], "quality", [], active=False)
    response = workflow.client("quality").get(url(project, "catalog/software"))
    assert response.status_code == 404
    import sqlite3

    with sqlite3.connect(workflow.production_tools.snapshot_path) as db:
        assert db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0


def test_metadata_revocation_prevents_object_open(workflow):
    project = workflow.create_project()
    workflow.grant(project["id"], "quality", ["quality"])
    source = configure(workflow, project)
    paused, resume = Event(), Event()

    def pause():
        paused.set()
        assert resume.wait(10)

    source.pause = pause
    responses = []
    thread = Thread(
        target=lambda: responses.append(
            workflow.client("quality").get(url(project, "evidence/1/content"))
        )
    )
    thread.start()
    try:
        assert paused.wait(10)
        workflow.grant(project["id"], "quality", [], active=False)
    finally:
        resume.set()
        thread.join(10)
    assert not thread.is_alive()
    assert responses[0].status_code == 404
    assert not source.opened


def test_buffering_revocation_prevents_any_attachment_bytes(workflow):
    project = workflow.create_project()
    workflow.grant(project["id"], "quality", ["quality"])
    source = configure(workflow, project)

    class RevokingStream(BytesIO):
        def read(self, size=-1):
            workflow.grant(project["id"], "quality", [], active=False)
            return super().read(size)

    source.stream = RevokingStream(b"private evidence bytes")
    response = workflow.client("quality").get(url(project, "evidence/1/content"))
    assert response.status_code == 404
    assert b"private evidence bytes" not in response.content
    assert source.stream.closed


@pytest.mark.parametrize(
    "size, payload",
    [(10 * 1024 * 1024 + 1, b"x"), (None, b"x" * (10 * 1024 * 1024 + 1))],
    ids=["declared-oversize", "unknown-length-oversize"],
)
def test_attachment_cap_is_checked_before_emission_and_stream_closed(
    workflow, size, payload
):
    project = workflow.create_project()
    source = configure(workflow, project)
    source.size, source.stream = size, BytesIO(payload)
    response = workflow.client().get(url(project, "evidence/1/content"))
    assert response.status_code == 422
    assert source.stream.closed


def test_failures_capabilities_and_validation_do_not_become_empty_success(workflow):
    project = workflow.create_project()
    source = configure(workflow, project, object_prefix="")
    source.failure = RuntimeError("secret-source-endpoint")
    response = workflow.client().get(url(project, "catalog/software"))
    assert response.status_code == 503 and "secret-source-endpoint" not in response.text
    assert workflow.client().get(url(project, "status")).json()["capabilities"][
        "evidence_content"
    ] == {"available": False, "reason": "SOURCE_UNAVAILABLE"}
    assert workflow.client().get(url(project, "evidence/1/content")).status_code == 503
    for path, params in [
        ("observations", {**PARAMS, "kind": "software"}),
        (
            "observations",
            {"kind": "production", "start": "2026-11-09", "end": "2026-11-10"},
        ),
        ("catalog/software", {"sql": "private"}),
        ("catalog/software", {"parent_id": "0"}),
        ("evidence", {**PARAMS, "device": "bad"}),
        ("snapshots/" + str(uuid4()), {"limit": "101"}),
        ("evidence/0/content", {}),
        ("evidence/100000000000000000000/content", {}),
    ]:
        assert (
            workflow.client().get(url(project, path), params=params).status_code == 422
        )


@pytest.mark.parametrize("target", ["domain", "authority", "foreign", "wrong_dataset"])
def test_invalid_connector_storage_isolated_from_workflow(workflow, target):
    from pathlib import Path

    project = workflow.create_project()
    source = configure(workflow, project)
    if target in {"domain", "authority"}:
        original = getattr(workflow.paths, target)
        if not original.exists():
            original.write_bytes(b"untouched authority file")
        path = original.parent / ("alias-" + target + ".db")
        import os

        os.link(original, path)
    elif target == "foreign":
        path = workflow.paths.domain.parent / "foreign.db"
        path.write_bytes(b"untouched foreign file")
    else:
        path = Path(workflow.production_tools.snapshot_path)
    config = workflow.production_tools
    if target == "wrong_dataset":
        scope = replace(next(iter(config.bindings.values())), dataset_id="other")
        config = replace(config, bindings={scope.project_id: scope})
    workflow.production_tools = replace(config, snapshot_path=str(path))
    workflow.reopen()
    response = workflow.client().get(url(project, "status"))
    assert response.status_code == 200 and response.json()["configured"] is False
    assert workflow.client().get(url(project, "catalog/software")).status_code == 503
    assert workflow.client().get(f"{BASE}/{project['id']}").status_code == 200
    assert source.calls == []
    if target == "foreign":
        assert path.read_bytes() == b"untouched foreign file"


def test_missing_backend_is_reported_without_status_or_query_io(workflow):
    project = workflow.create_project()
    source = FakeSource()
    source.capabilities = frozenset({"software"})
    configure(workflow, project, source)
    response = workflow.client().get(url(project, "status"))
    assert response.json()["configured"] is True
    assert response.json()["capabilities"]["software"] == {
        "available": True,
        "reason": None,
    }
    assert response.json()["capabilities"]["production"] == {
        "available": False,
        "reason": "SOURCE_UNAVAILABLE",
    }
    response = workflow.client().get(
        url(project, "observations"), params={**PARAMS, "kind": "production"}
    )
    assert response.status_code == 503 and source.calls == []


def test_slow_source_binding_change_invalidates_result(workflow):
    from manufacturing_platform.production_tools.contracts import ProductionQuery
    from manufacturing_platform.production_tools.service import ProductionToolsService
    from manufacturing_platform.workflow.contracts import Actor
    from manufacturing_platform.workflow.store import WorkflowStore

    project = workflow.create_project()
    source = configure(workflow, project)
    store = WorkflowStore(
        str(workflow.paths.domain),
        str(workflow.paths.authority),
        {"id": "workflow-test", "mode": "test", "label": "Workflow test"},
    )
    service = ProductionToolsService(
        store, workflow.production_tools, clock=lambda: datetime.now(UTC)
    )
    binding = next(iter(workflow.production_tools.bindings.values()))

    def remap():
        service.config = replace(
            service.config,
            bindings={binding.project_id: replace(binding, revision="v2")},
        )

    source.pause = remap
    with pytest.raises(DomainError) as exc:
        service.query(
            Actor(
                user_id=uuid4(),
                display_name="Admin",
                configuration_admin=True,
                read_only=False,
            ),
            UUID(project["id"]),
            ProductionQuery(kind="software"),
        )
    assert exc.value.status == 404


def test_attachment_read_failure_is_sanitized_and_closed(workflow):
    project = workflow.create_project()
    source = configure(workflow, project)

    class BrokenStream(BytesIO):
        def read(self, size=-1):
            raise RuntimeError("private-storage-address")

    source.stream = BrokenStream()
    response = workflow.client().get(url(project, "evidence/1/content"))
    assert response.status_code == 503
    assert "private-storage-address" not in response.text
    assert source.stream.closed


def test_large_ids_survive_api_json_and_javascript_keyset_roundtrip(workflow):
    import json
    import sqlite3
    import subprocess

    from .test_lossless_paging import KeysetReader, native

    large, maximum = 9007199254740993, 99999999999999999999
    rows = [{"id": n, "projuectid": "1"} for n in range(large + 999, large - 2, -1)]
    source = configure(workflow, workflow.create_project(), native(KeysetReader(rows)))
    scope = next(iter(workflow.production_tools.bindings.values()))
    path = f"{BASE}/{scope.project_id}/production-tools/catalog/software_versions"
    response = workflow.client().get(
        path, params={"parent_id": str(maximum), "before_id": str(maximum)}
    )
    assert response.status_code == 200, response.text
    parsed = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            """
            let body = '';
            for await (const chunk of process.stdin) body += chunk;
            const page = JSON.parse(body);
            process.stdout.write(JSON.stringify({
                cursor: page.next_before_id,
                cursorType: typeof page.next_before_id,
                firstIdType: typeof page.items[0].id,
                parent: page.filters.parent_id,
                before: page.filters.before_id,
            }));
        """,
        ],
        input=response.text,
        text=True,
        capture_output=True,
        check=True,
    )
    wire = json.loads(parsed.stdout)
    assert wire == {
        "cursor": str(large),
        "cursorType": "string",
        "firstIdType": "string",
        "parent": str(maximum),
        "before": str(maximum),
    }
    assert source.mysql.calls[0].params == (1, maximum, maximum, 1001)
    following = workflow.client().get(
        path, params={"parent_id": wire["parent"], "before_id": wire["cursor"]}
    )
    assert following.status_code == 200, following.text
    assert following.json()["items"][0]["id"] == "9007199254740992"
    assert source.mysql.calls[1].params == (1, large, maximum, 1001)
    with sqlite3.connect(workflow.production_tools.snapshot_path) as conn:
        captured = [
            json.loads(row[0])
            for row in conn.execute("SELECT payload_json FROM snapshots")
        ]
    assert captured[0]["next_before_id"] == large
    assert captured[0]["filters"]["parent_id"] == maximum
    assert captured[0]["items"][-1]["id"] == large
    snapshot = f"{BASE}/{scope.project_id}/production-tools/snapshots/{response.json()['snapshot_id']}"
    assert workflow.client().get(snapshot).json() == response.json()


@pytest.mark.parametrize("field", ["parent_id", "before_id"])
@pytest.mark.parametrize(
    "value", ["100000000000000000000", "0", "-1", "1.0", "１２", "01"]
)
def test_api_rejects_out_of_contract_source_ids_before_io(workflow, field, value):
    project = workflow.create_project()
    source = configure(workflow, project)
    response = workflow.client().get(
        url(project, "catalog/software_versions"), params={field: value}
    )
    assert response.status_code == 422
    assert source.calls == []


def test_public_api_preserves_large_statistics_and_measurements(workflow):
    import json
    import sqlite3

    from .test_lossless_paging import KeysetReader, native

    maximum, large = 99999999999999999999, 9007199254740993
    reader = KeysetReader(
        [
            {
                "records": maximum,
                "distinct_sn": large,
                "pass_records": maximum - 1,
                "fail_records": 1,
            }
        ]
    )
    project = workflow.create_project()
    configure(workflow, project, native(reader))
    response = workflow.client().get(
        url(project, "statistics"), params={**PARAMS, "kind": "production"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == [
        {
            "records": str(maximum),
            "distinct_sn": str(large),
            "pass_records": str(maximum - 1),
            "fail_records": 1,
            "unknown_records": 0,
            "record_pass_ratio": (maximum - 1) / maximum,
            "consistency": "single_query",
        }
    ]
    reader.rows = [
        {
            "id": maximum,
            "projuectid": "1",
            "measurement": large,
            "negative_measurement": -large,
            "voltage": 12,
            "ratio": 1.5,
            "flag": True,
            "nullable": None,
            "api_token": "SECRET",
        }
    ]
    response = workflow.client().get(
        url(project, "observations"), params={**PARAMS, "kind": "production"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == [
        {
            "id": str(maximum),
            "projuectid": "1",
            "measurement": str(large),
            "negative_measurement": str(-large),
            "voltage": 12,
            "ratio": 1.5,
            "flag": True,
            "nullable": None,
        }
    ]
    assert response.json()["redacted_fields"] == ["api_token"]
    with sqlite3.connect(workflow.production_tools.snapshot_path) as conn:
        canonical = [
            json.loads(row[0])
            for row in conn.execute("SELECT payload_json FROM snapshots")
        ]
    assert canonical[0]["items"][0]["records"] == maximum
    assert canonical[1]["items"][0]["measurement"] == large
    assert "SECRET" not in response.text


def test_full_twenty_digit_evidence_id_reaches_protected_download_exactly(workflow):
    maximum = 99999999999999999999
    project = workflow.create_project()
    source = configure(workflow, project)

    def evidence(binding, source_log_id, *, before_open=None):
        assert type(source_log_id) is int and source_log_id == maximum
        source.calls.append((binding, source_log_id))
        if before_open:
            before_open()
        return EvidenceObject(BytesIO(b"exact evidence"), 14, "evidence.log")

    source.evidence = evidence
    response = workflow.client().get(url(project, f"evidence/{maximum}/content"))
    assert response.status_code == 200
    assert response.content == b"exact evidence"
    assert source.calls[0][1] == maximum
