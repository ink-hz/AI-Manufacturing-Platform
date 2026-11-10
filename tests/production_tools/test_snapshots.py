import json
import os
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from manufacturing_platform.production_tools.contracts import (
    SourceBinding,
    SourceResult,
)
from manufacturing_platform.production_tools.store import SnapshotStore
from manufacturing_platform.workflow.contracts import DomainError

PROJECT = uuid4()
DATASET = {"id": "test", "mode": "test", "label": "Test"}
NOW = datetime(2026, 11, 10, tzinfo=UTC)


def binding(**changes):
    return replace(
        SourceBinding("test", PROJECT, "native", "1", "v1", "project/"), **changes
    )


def result(items=None):
    return SourceResult(
        "production",
        items if items is not None else [{"sn": "SN-1", "status": "1"}],
        NOW,
        {"sn": "SN-1"},
        True,
        None,
        None,
    )


def test_snapshot_is_immutable_and_binding_scoped(tmp_path):
    store = SnapshotStore(str(tmp_path / "observations.db"), DATASET, clock=lambda: NOW)
    scope, rows = binding(), result()
    sid = store.put(scope, rows)
    rows.items[0]["status"] = "2"
    page = store.get(PROJECT, sid, scope)
    assert page["items"][0]["status"] == "1"
    assert page["filters"] == {"sn": "SN-1"}
    assert page["captured_count"] == 1
    for changed in [
        replace(scope, revision="v2"),
        replace(scope, object_prefix="other/"),
        replace(scope, source_namespace="other"),
        replace(scope, source_project_id="2"),
    ]:
        with pytest.raises(DomainError) as exc:
            store.get(PROJECT, sid, changed)
        assert exc.value.status == 404
    with pytest.raises(DomainError) as exc:
        store.get(uuid4(), sid, scope)
    assert exc.value.status == 404
    assert os.stat(store.path).st_mode & 0o077 == 0


def test_dataset_expiry_checksum_and_paging(tmp_path):
    now = [NOW]
    path = str(tmp_path / "observations.db")
    store = SnapshotStore(path, DATASET, clock=lambda: now[0])
    sid = store.put(binding(), result([{"sn": str(i)} for i in range(102)]))
    page = store.get(PROJECT, sid, binding(), offset=100, limit=2)
    assert page["items"] == [{"sn": "100"}, {"sn": "101"}]
    assert page["captured_count"] == 102 and not page["has_more"]
    for offset, limit in [(-1, 50), (0, 0), (0, 101)]:
        with pytest.raises(DomainError) as exc:
            store.get(PROJECT, sid, binding(), offset=offset, limit=limit)
        assert exc.value.status == 422
    with pytest.raises((ValueError, DomainError)):
        SnapshotStore(path, {**DATASET, "id": "other"}, clock=lambda: NOW).get(
            PROJECT, sid, binding()
        )
    now[0] += timedelta(hours=24)
    with pytest.raises(DomainError) as exc:
        store.get(PROJECT, sid, binding())
    assert exc.value.code == "SNAPSHOT_EXPIRED"
    now[0] = NOW
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE snapshots SET payload_json=?", (json.dumps({"items": []}),)
        )
    with pytest.raises(DomainError) as exc:
        store.get(PROJECT, sid, binding())
    assert exc.value.status == 503


def test_caps_redactions_and_snapshot_quota(tmp_path):
    store = SnapshotStore(str(tmp_path / "observations.db"), DATASET, clock=lambda: NOW)
    sid = store.put(
        binding(),
        result(
            [
                {"sn": str(i), "url": "private", "api_token": "secret"}
                for i in range(1001)
            ]
        ),
    )
    page = store.get(PROJECT, sid, binding())
    assert page["captured_count"] == 1000
    assert not page["complete"] and page["truncation_reason"] == "row_limit"
    assert page["items"][0] == {"sn": "0"}
    assert set(page["redacted_fields"]) == {"url", "api_token"}
    sid = store.put(binding(), result([{"v": "x" * 1024 * 1024}] * 3))
    page = store.get(PROJECT, sid, binding())
    assert page["captured_count"] == 1 and page["truncation_reason"] == "byte_limit"
    with sqlite3.connect(store.path) as conn:
        assert (
            max(
                len(row[0].encode())
                for row in conn.execute("SELECT payload_json FROM snapshots")
            )
            <= 2 * 1024 * 1024
        )
    with pytest.raises(DomainError) as exc:
        store.put(binding(), result([{"v": "x" * 2 * 1024 * 1024}]))
    assert exc.value.code == "SOURCE_LIMIT_EXCEEDED"
    for _ in range(98):
        store.put(binding(), result([]))
    with pytest.raises(DomainError) as exc:
        store.put(binding(), result([]))
    assert exc.value.status == 503


def test_existing_unknown_file_is_never_adopted(tmp_path):
    path = tmp_path / "unknown.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE private(x)")
    original = path.read_bytes()
    with pytest.raises((ValueError, DomainError)):
        SnapshotStore(str(path), DATASET, clock=lambda: NOW).put(binding(), result())
    assert path.read_bytes() == original
    empty = tmp_path / "empty.db"
    empty.touch()
    with pytest.raises((ValueError, DomainError)):
        SnapshotStore(str(empty), DATASET, clock=lambda: NOW).put(binding(), result())


def test_snapshot_path_validator_rejects_domain_authority_and_legacy_aliases(tmp_path):
    from manufacturing_platform.production_tools import validate_snapshot_path

    for name in ("domain.db", "authority.db", "legacy.db"):
        protected = tmp_path / name
        protected.write_bytes(b"protected storage")
        for candidate in (
            protected,
            tmp_path / ("hard-" + name),
            tmp_path / ("sym-" + name),
        ):
            if candidate.name.startswith("hard-"):
                os.link(protected, candidate)
            elif candidate.name.startswith("sym-"):
                candidate.symlink_to(protected)
            with pytest.raises(ValueError):
                validate_snapshot_path(str(candidate), (str(protected),))
        assert protected.read_bytes() == b"protected storage"
    with pytest.raises(ValueError):
        validate_snapshot_path("relative.db")


def test_metadata_is_checked_on_every_open_and_cleanup_is_bounded(tmp_path):
    now = [NOW]
    store = SnapshotStore(
        str(tmp_path / "observations.db"), DATASET, clock=lambda: now[0]
    )
    sid = store.put(binding(), result())
    with sqlite3.connect(store.path) as conn:
        conn.execute("UPDATE metadata SET dataset_label=?", ("Changed",))
    with pytest.raises(ValueError):
        store.get(PROJECT, sid, binding())
    with sqlite3.connect(store.path) as conn:
        conn.execute("UPDATE metadata SET dataset_label=?", (DATASET["label"],))
        original = conn.execute("SELECT * FROM snapshots").fetchone()
        for _ in range(150):
            conn.execute(
                "INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?)",
                (str(uuid4()), *original[1:]),
            )
    now[0] += timedelta(hours=25)
    store.put(binding(), result())
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 52


def test_snapshot_payload_contains_binding_dataset_and_query_provenance(tmp_path):
    store = SnapshotStore(str(tmp_path / "observations.db"), DATASET, clock=lambda: NOW)
    store.put(binding(), result())
    with sqlite3.connect(store.path) as conn:
        payload = json.loads(
            conn.execute("SELECT payload_json FROM snapshots").fetchone()[0]
        )
        assert payload["dataset"] == DATASET
        assert payload["query_version"] == 1
        assert len(payload["binding_fingerprint"]) == 64


def test_absolute_snapshot_paths_preserve_uri_special_characters(tmp_path):
    store = SnapshotStore(
        str(tmp_path / "observations?#.db"), DATASET, clock=lambda: NOW
    )
    sid = store.put(binding(), result())
    assert store.get(PROJECT, sid, binding())["captured_count"] == 1


def test_existing_database_requires_complete_dedicated_snapshot_schema(tmp_path):
    path = tmp_path / "foreign.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE metadata(version,dataset_id,dataset_mode,dataset_label)"
        )
        conn.execute(
            "INSERT INTO metadata VALUES (1,?,?,?)",
            tuple(DATASET[key] for key in ("id", "mode", "label")),
        )
        conn.execute("CREATE TABLE private(x)")
    original = path.read_bytes()
    with pytest.raises(ValueError):
        SnapshotStore(str(path), DATASET, clock=lambda: NOW)
    assert path.read_bytes() == original
