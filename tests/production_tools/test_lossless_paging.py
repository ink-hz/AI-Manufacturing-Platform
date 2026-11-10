"""Regression coverage for native capture, canonical storage and browser boundaries."""

import json
import sqlite3
from dataclasses import replace

import pytest

from manufacturing_platform.production_tools.contracts import ProductionQuery
from manufacturing_platform.production_tools.source import NativeProductionSource
from manufacturing_platform.production_tools.store import SnapshotStore
from manufacturing_platform.workflow.contracts import DomainError

from .test_queries import NOW, PROJECT, binding, timed
from .test_snapshots import DATASET, result


class KeysetReader:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def select(self, statement):
        self.calls.append(statement)
        rows = self.rows
        if "id < %s" in statement.sql:
            cursor_index = statement.sql.split("id < %s")[0].count("%s")
            rows = [row for row in rows if row["id"] < statement.params[cursor_index]]
        return rows[: statement.max_rows]


def native(reader):
    return NativeProductionSource(
        reader, reader, None, allowed_object_host="", clock=lambda: NOW
    )


@pytest.mark.parametrize("source_partial", [False, True])
@pytest.mark.parametrize("kind", ["software", "evidence"])
def test_native_mysql_snapshot_trim_continues_from_actual_retained_prefix(
    tmp_path, source_partial, kind
):
    rows = [{"id": n, "projuectid": "10001", "text": "x" * 698904} for n in (3, 2, 1)]
    reader = KeysetReader(rows)
    # A valid fourth source row acts as the sentinel for the partial capture.
    if source_partial:
        reader.rows = [dict(row, id=row["id"] + 1) for row in rows] + [
            {"id": 1, "projuectid": "10001"}
        ]
    src = native(reader)
    query = timed("evidence") if kind == "evidence" else ProductionQuery(kind=kind)
    captured = src.query(binding(), query, cap=3)
    assert len(captured.items) == 3
    assert captured.complete is not source_partial
    assert captured.next_before_id == (2 if source_partial else None)
    store = SnapshotStore(str(tmp_path / "snapshots.db"), DATASET, clock=lambda: NOW)
    sid = store.put(binding(), captured)
    page = store.get(PROJECT, sid, binding())
    retained = [str(row["id"]) for row in captured.items[:2]]
    assert page["next_before_id"] == retained[-1]
    assert [row["id"] for row in page["items"]] == retained
    assert page["captured_count"] == 2
    assert page["complete"] is False
    assert page["truncation_reason"] == "byte_limit"
    assert page["filters"] == captured.filters
    assert page["captured_at"] == "2026-11-10T00:00:00Z"
    following = src.query(
        binding(),
        query.model_copy(update={"before_id": int(page["next_before_id"])}),
    )
    assert following.items[0]["id"] == captured.items[2]["id"]
    assert store.get(PROJECT, sid, binding()) == page


def test_questdb_snapshot_trim_has_no_source_continuation(tmp_path):
    captured = native(
        KeysetReader(
            [{"id": n, "projuectid": "10001", "text": "x" * 698880} for n in (3, 2, 1)]
        )
    ).query(binding(), timed())
    assert captured.complete and len(captured.items) == 3
    store = SnapshotStore(str(tmp_path / "snapshots.db"), DATASET, clock=lambda: NOW)
    page = store.get(PROJECT, store.put(binding(), captured), binding())
    assert page["captured_count"] == 2
    assert page["truncation_reason"] == "byte_limit"
    assert page["next_before_id"] is None


@pytest.mark.parametrize("bad_id", [None, True, 0, -1, "private-invalid-id"])
def test_snapshot_mysql_trim_rejects_malformed_retained_cursor(tmp_path, bad_id):
    captured = replace(
        result(
            [
                {"id": 3, "text": "x" * 700000},
                {"id": bad_id, "text": "x" * 700000},
                {"id": 1, "text": "x" * 700000},
            ]
        ),
        source_kind="software",
    )
    store = SnapshotStore(str(tmp_path / "snapshots.db"), DATASET, clock=lambda: NOW)
    with pytest.raises(DomainError) as caught:
        store.put(binding(), captured)
    assert caught.value.code == "SOURCE_SCHEMA_INVALID"
    assert "private-invalid-id" not in str(caught.value)


def test_public_projection_is_lossless_without_mutating_canonical_snapshot(tmp_path):
    large, maximum = 9007199254740993, 99999999999999999999
    captured = replace(
        result(
            [
                {
                    "id": large,
                    "voltage": 12,
                    "fraction": 1.5,
                    "flag": True,
                    "null": None,
                    "nested": {
                        "count": maximum,
                        "negative": -large,
                        "safe": 9007199254740991,
                    },
                    "samples": [large, False],
                    "password": "SECRET",
                },
                {"id": 2},
                {"id": "source-text"},
                {"id": None},
                {"id": maximum},
            ]
        ),
        source_kind="software_versions",
        complete=False,
        truncation_reason="row_limit",
        next_before_id=large,
        filters={"parent_id": maximum, "before_id": large},
    )
    store = SnapshotStore(str(tmp_path / "snapshots.db"), DATASET, clock=lambda: NOW)
    sid = store.put(binding(), captured)
    with sqlite3.connect(store.path) as conn:
        raw = conn.execute("SELECT payload_json FROM snapshots").fetchone()[0]
    canonical = json.loads(raw)
    assert canonical["items"][0]["id"] == large
    assert canonical["items"][4]["id"] == maximum
    assert canonical["items"][0]["nested"]["count"] == maximum
    assert canonical["next_before_id"] == large
    assert canonical["filters"] == captured.filters
    page = store.get(PROJECT, sid, binding())
    assert page["items"] == [
        {
            "id": str(large),
            "voltage": 12,
            "fraction": 1.5,
            "flag": True,
            "null": None,
            "nested": {
                "count": str(maximum),
                "negative": str(-large),
                "safe": 9007199254740991,
            },
            "samples": [str(large), False],
        },
        {"id": "2"},
        {"id": "source-text"},
        {"id": None},
        {"id": str(maximum)},
    ]
    assert page["next_before_id"] == str(large)
    assert page["filters"] == {"parent_id": str(maximum), "before_id": str(large)}
    assert (page["offset"], page["limit"], page["captured_count"]) == (0, 50, 5)
    assert page["redacted_fields"] == ["password"]
    assert "SECRET" not in raw and "SECRET" not in json.dumps(page)
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("SELECT payload_json FROM snapshots").fetchone()[0] == raw


@pytest.mark.parametrize("field", ["parent_id", "before_id"])
def test_query_model_bounds_ids_at_twenty_digits(field):
    maximum = 99999999999999999999
    query = ProductionQuery(kind="software_versions", **{field: maximum})
    assert getattr(query, field) == maximum
    with pytest.raises(ValueError):
        ProductionQuery(kind="software_versions", **{field: maximum + 1})


def test_snapshot_mysql_row_cap_also_uses_retained_boundary(tmp_path):
    captured = replace(
        result([{"id": n} for n in range(1001, 0, -1)]),
        source_kind="software",
        complete=False,
        truncation_reason="row_limit",
        next_before_id=1,
    )
    store = SnapshotStore(str(tmp_path / "snapshots.db"), DATASET, clock=lambda: NOW)
    page = store.get(PROJECT, store.put(binding(), captured), binding())
    assert page["captured_count"] == 1000
    assert page["next_before_id"] == "2"
    assert page["truncation_reason"] == "row_limit"
    assert page["complete"] is False
