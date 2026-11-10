"""Independent native HTTP contract, with only external transports replaced."""

from datetime import UTC, datetime

from manufacturing_platform.production_tools.contracts import ProductionToolsConfig
from manufacturing_platform.production_tools.source import NativeProductionSource

BASE = "/api/v1/manufacturing/workflow/production-tools"


class DirectoryReader:
    def __init__(self):
        self.calls = []

    def select(self, statement):
        self.calls.append(statement)
        return [{"id": 7, "name": "Source seven"}]


def test_admin_directory_without_manufacturing_projects(workflow):
    reader = DirectoryReader()
    source = NativeProductionSource(
        reader, None, None, allowed_object_host="", clock=lambda: datetime.now(UTC)
    )
    workflow.production_tools = ProductionToolsConfig(
        source, "native", "v2", {}, str(workflow.paths.domain.parent / "native.db")
    )
    workflow.reopen()
    client = workflow.client()
    admin = {"X-Test-Actor": "owner"}
    response = client.get(BASE + "/projects", headers=admin)
    assert response.status_code == 200
    assert response.json()["items"] == [{"id": "7", "name": "Source seven"}]
    assert (
        client.get("/api/v1/manufacturing/workflow/projects", headers=admin).json()[
            "items"
        ]
        == []
    )


def test_source_snapshot_provenance_is_independent(workflow):
    import json
    import sqlite3

    from .test_api import configure, url

    configure(workflow)
    page = workflow.client().get(url(None, "catalog/software")).json()
    assert page["source_namespace"] == "native"
    assert page["source_project_id"] == "1"
    assert "project_id" not in page
    with sqlite3.connect(workflow.production_tools.snapshot_path) as conn:
        payload = json.loads(
            conn.execute("SELECT payload_json FROM snapshots").fetchone()[0]
        )
    assert payload["source_namespace"] == "native"
    assert payload["source_project_id"] == "1"
    assert "dataset" not in payload


import pytest

from manufacturing_platform.production_tools.queries import validate_statement


class Transport:
    def __init__(self, rows=None, failure=None):
        self.rows = rows if rows is not None else [{"id": 7, "name": "Source seven"}]
        self.failure = failure
        self.calls = []

    def select(self, statement):
        validate_statement(statement)
        self.calls.append(statement)
        if self.failure:
            raise self.failure
        if statement.name.startswith("source_project"):
            rows = [row for row in self.rows if not row.get("del")]
            if statement.name == "source_project":
                rows = [
                    row for row in rows if str(row["id"]) == str(statement.params[0])
                ]
            elif statement.name == "source_projects_before":
                rows = [row for row in rows if int(row["id"]) < statement.params[0]]
            return [
                {k: v for k, v in row.items() if k != "del"}
                for row in rows[: statement.max_rows]
            ]
        return [{"id": 1, "projuectid": 7, "name": "Observation"}]


def install(workflow, reader):
    workflow.production_tools = ProductionToolsConfig(
        NativeProductionSource(
            reader,
            reader,
            None,
            allowed_object_host="",
            clock=lambda: datetime.now(UTC),
        ),
        "native",
        "v2",
        {},
        str(workflow.paths.domain.parent / "native.db"),
    )
    workflow.reopen()
    return workflow.client()


def test_zero_workflow_projects_admin_reads_source_and_snapshot_offline(workflow):
    reader = Transport()
    client = install(workflow, reader)
    response = client.get(BASE + "/projects/7/catalog/software")
    assert response.status_code == 200
    page = response.json()
    assert page["items"] == [{"id": "1", "projuectid": 7, "name": "Observation"}]
    assert [s.name for s in reader.calls] == ["source_project", "software"]
    reader.failure = RuntimeError("secret source offline")
    before = list(reader.calls)
    assert (
        client.get(BASE + "/projects/7/snapshots/" + page["snapshot_id"]).json() == page
    )
    assert reader.calls == before
    assert (
        client.get(BASE + "/projects/8/snapshots/" + page["snapshot_id"]).status_code
        == 404
    )
    assert client.get("/api/v1/manufacturing/workflow/projects").json()["items"] == []


def test_ordinary_workflow_member_denied_before_source_io(workflow):
    project = workflow.create_project()
    workflow.grant(project["id"], "quality", ["quality"])
    reader = Transport()
    install(workflow, reader)
    for suffix in (
        "/status",
        "/projects",
        "/projects/7/status",
        "/projects/7/catalog/software",
        "/projects/7/evidence/1/content",
    ):
        response = workflow.client("quality").get(BASE + suffix)
        assert response.status_code == 403
        assert response.headers["cache-control"] == "private, no-store"
    assert reader.calls == []


def test_directory_pages_deleted_and_unknown_projects(workflow):
    reader = Transport(
        [{"id": i, "name": str(i), "del": int(i == 104)} for i in range(104, 0, -1)]
    )
    client = install(workflow, reader)
    page = client.get(BASE + "/projects").json()
    assert page == {
        "items": [{"id": str(i), "name": str(i)} for i in range(103, 3, -1)],
        "limit": 100,
        "has_more": True,
        "next_before_id": "4",
    }
    assert reader.calls[0].params == (101,)
    following = client.get(
        BASE + "/projects", params={"before_id": page["next_before_id"]}
    ).json()
    assert following["items"] == [
        {"id": str(i), "name": str(i)} for i in range(3, 0, -1)
    ]
    assert following["next_before_id"] is None and not following["has_more"]
    assert reader.calls[1].params == (4, 101)
    for source_id in ("104", "105"):
        assert (
            client.get(BASE + f"/projects/{source_id}/catalog/software").status_code
            == 404
        )
    assert all(s.name.startswith("source_project") for s in reader.calls)


@pytest.mark.parametrize(
    "identifier", ["0", "01", "-1", "1.0", "１２", "100000000000000000000"]
)
def test_malformed_source_ids_rejected_before_io(workflow, identifier):
    reader = Transport()
    client = install(workflow, reader)
    for suffix, params in [
        ("/projects", {"before_id": identifier}),
        (f"/projects/{identifier}/catalog/software", {}),
        (f"/projects/7/evidence/{identifier}/content", {}),
    ]:
        assert client.get(BASE + suffix, params=params).status_code == 422
    assert reader.calls == []


@pytest.mark.parametrize(
    "params",
    [
        [("before_id", "7"), ("before_id", "6")],
        {"limit": "1"},
        {"sql": "SELECT private"},
    ],
)
def test_directory_rejects_unknown_and_duplicate_parameters(workflow, params):
    reader = Transport()
    client = install(workflow, reader)
    assert client.get(BASE + "/projects", params=params).status_code == 422
    assert reader.calls == []


def test_directory_failure_is_sanitized_and_status_never_claims_connectivity(workflow):
    reader = Transport(failure=RuntimeError("secret-private-address"))
    client = install(workflow, reader)
    assert client.get(BASE + "/status").json()["configured"] is True
    assert client.get(BASE + "/projects/7/status").json()["source_project_id"] == "7"
    assert reader.calls == []
    response = client.get(BASE + "/projects")
    assert response.status_code == 503
    assert response.json()["code"] == "SOURCE_UNAVAILABLE"
    assert "secret-private-address" not in response.text


@pytest.mark.parametrize(
    "rows",
    [
        [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}],
        [{"id": 1, "name": "a"}, {"id": 1, "name": "b"}],
        [{"id": True, "name": "a"}],
        [{"id": "01", "name": "a"}],
        [{"id": "100000000000000000000", "name": "a"}],
        [{"id": 1, "name": None}],
        [{"id": 1, "name": "x" * 4097}],
        [{"id": 1, "name": "a", "password": "SECRET"}],
        [{"id": i, "name": "a"} for i in range(102, 0, -1)],
    ],
)
def test_directory_rejects_unbounded_malformed_transport_rows(workflow, rows):
    reader = DirectoryReader()
    reader.select = lambda statement: rows
    response = install(workflow, reader).get(BASE + "/projects")
    assert response.status_code == 503
    assert response.json()["code"] == "SOURCE_SCHEMA_INVALID"
    assert "SECRET" not in response.text


def test_directory_twenty_digit_id_stays_exact(workflow):
    maximum = "99999999999999999999"
    reader = Transport([{"id": maximum, "name": "Large source"}])
    client = install(workflow, reader)
    assert client.get(BASE + "/projects").json()["items"][0]["id"] == maximum
    assert (
        client.get(BASE + "/projects", params={"before_id": maximum}).json()["items"]
        == []
    )
    assert reader.calls[-1].params == (int(maximum), 101)


def test_exact_native_and_investigation_routes_and_no_legacy_route(workflow):
    native = {
        path: methods
        for path, methods in workflow.app.openapi()["paths"].items()
        if "/production-tools" in path
    }
    expected = {
        "/status": {"get"},
        "/projects": {"get"},
        "/projects/{source_project_id}/status": {"get"},
        "/projects/{source_project_id}/observations": {"get"},
        "/projects/{source_project_id}/catalog/{kind}": {"get"},
        "/projects/{source_project_id}/evidence": {"get"},
        "/projects/{source_project_id}/statistics": {"get"},
        "/projects/{source_project_id}/snapshots/{snapshot_id}": {"get"},
        "/projects/{source_project_id}/evidence/{source_log_id}/content": {"get"},
        "/projects/{source_project_id}/investigations": {"get", "post"},
        "/projects/{source_project_id}/investigations/{investigation_id}": {"get", "put"},
        "/projects/{source_project_id}/investigations/{investigation_id}/resolve": {"get"},
        "/projects/{source_project_id}/investigations/{investigation_id}/handoffs": {"post"},
        "/handoffs/{handoff_id}": {"get"},
        "/handoffs/{handoff_id}/resolve": {"get"},
        "/handoffs/{handoff_id}/fork": {"post"},
    }
    assert {path: set(methods) for path, methods in native.items()} == {
        BASE + suffix: methods for suffix, methods in expected.items()
    }
    project = workflow.create_project()
    assert (
        workflow.client()
        .get(
            f"/api/v1/manufacturing/workflow/projects/{project['id']}/production-tools/status"
        )
        .status_code
        == 404
    )


def test_legacy_snapshot_cache_rejected_without_mutation(tmp_path):
    import sqlite3

    from manufacturing_platform.production_tools.store import SnapshotStore

    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            'CREATE TABLE metadata(version,dataset_id,dataset_mode,dataset_label); INSERT INTO metadata VALUES(1,"demo","demo","Demo"); CREATE TABLE snapshots(id,project_id,binding_revision,source_namespace,source_project_id,source_kind,captured_at,expires_at,payload_json,payload_sha256);'
        )
    original = path.read_bytes()
    with pytest.raises(ValueError):
        SnapshotStore(str(path), clock=lambda: datetime.now(UTC))
    assert path.read_bytes() == original
