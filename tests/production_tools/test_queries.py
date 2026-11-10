from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from manufacturing_platform.production_tools.contracts import (
    ProductionQuery,
    SourceBinding,
)
from manufacturing_platform.production_tools.queries import (
    compile_query,
    validate_statement,
)

PROJECT = UUID("00000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 11, 10, tzinfo=UTC)


def binding():
    return SourceBinding("test", PROJECT, "fixture", "10001", "v1", "logs/10001/")


def timed(kind="production", **kw):
    return ProductionQuery(kind=kind, start=NOW - timedelta(days=1), end=NOW, **kw)


def test_sn_is_bound_and_scoped():
    statement = compile_query(binding(), timed(sn="x' OR 1=1 --"))
    assert statement.backend == "questdb"
    assert "x' OR 1=1 --" not in statement.sql
    assert "x' OR 1=1 --" in statement.params
    assert "10001" in statement.params
    assert "projuectid = %s" in statement.sql
    assert statement.max_rows == 1001
    validate_statement(statement)


@pytest.mark.parametrize(
    "kind,table",
    [
        ("software", "softwarelists"),
        ("software_versions", "softwareversions"),
        ("configs", "configlists"),
        ("config_versions", "configlogs"),
        ("review_orders", "orderlists"),
    ],
)
def test_catalog_keyset(kind, table):
    statement = compile_query(binding(), ProductionQuery(kind=kind, before_id=42))
    assert f"FROM {table}" in statement.sql
    assert "WHERE del = 0 AND projuectid = %s" in statement.sql
    assert "id < %s" in statement.sql and "ORDER BY id DESC" in statement.sql
    assert statement.params == (10001, 42, 1001)
    validate_statement(statement)


@pytest.mark.parametrize(
    "kind,kwargs",
    [
        ("software", {"sn": "x"}),
        ("software", {"parent_id": 1}),
        ("production", {"parent_id": 1}),
        ("evidence", {"device": "x"}),
        ("configs", {"order_id": "1"}),
        ("production", {"before_id": 1}),
    ],
)
def test_unsupported_filters_rejected(kind, kwargs):
    with pytest.raises(ValueError):
        query = (
            timed(kind, **kwargs)
            if kind in {"production", "evidence"}
            else ProductionQuery(kind=kind, **kwargs)
        )
        compile_query(binding(), query)


@pytest.mark.parametrize("cap", [0, 1001, True, 1.5])
def test_cap_bounds(cap):
    with pytest.raises(ValueError):
        compile_query(binding(), timed(), cap=cap)


def test_statistics_fixed_aggregate_without_capture_limit():
    statement = compile_query(binding(), timed("production_statistics", sn="SN"))
    assert "count_distinct(CASE WHEN sn <> '' THEN sn ELSE null END)" in statement.sql
    assert "LIMIT" not in statement.sql
    assert statement.max_rows == 1
    validate_statement(statement)


def test_evidence_milliseconds_and_parent_binding():
    statement = compile_query(binding(), timed("evidence", sn="SN", order_id="8"))
    assert "createtime >= %s AND createtime < %s" in statement.sql
    assert "csn = %s" in statement.sql
    assert isinstance(statement.params[1], int)
    parent = compile_query(
        binding(), ProductionQuery(kind="config_versions", parent_id=8)
    )
    assert "configid = %s" in parent.sql


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start": NOW.replace(tzinfo=None), "end": NOW},
        {"start": NOW - timedelta(days=32), "end": NOW},
        {"start": NOW, "end": NOW},
        {"end": NOW},
    ],
)
def test_window_validation(kwargs):
    with pytest.raises(ValueError):
        ProductionQuery(kind="production", **kwargs)


def test_window_is_bounded_in_elapsed_utc_time_across_dst():
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("America/New_York")
    with pytest.raises(ValueError):
        ProductionQuery(
            kind="production",
            start=datetime(2026, 10, 10, tzinfo=zone),
            end=datetime(2026, 11, 10, tzinfo=zone),
        )


@pytest.mark.parametrize(
    "prefix", ["logs//x/", "/logs/x/", "logs/../x/", "logs/%2e/", "logs/x\n/"]
)
def test_binding_prefix_is_canonical(prefix):
    with pytest.raises(ValueError):
        SourceBinding("test", PROJECT, "fixture", "10001", "v1", prefix)
