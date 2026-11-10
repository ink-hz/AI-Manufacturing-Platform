from datetime import UTC, datetime, timedelta

import pytest

from manufacturing_platform.production_tools.contracts import (
    ProductionQuery,
    SourceScope,
)
from manufacturing_platform.production_tools.queries import (
    compile_query,
    validate_statement,
)

PROJECT = "10001"
NOW = datetime(2026, 11, 10, tzinfo=UTC)


def binding():
    return SourceScope("fixture", "10001", "v1", "logs/10001/")


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
        ("evidence", {"status": "1"}),
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
        SourceScope("fixture", "10001", "v1", prefix)


@pytest.mark.parametrize(
    "start_us,end_us,expected_ms",
    [
        (1, 1001, (1, 2)),
        (0, 1000, (0, 1)),
        (999, 1000, (1, 1)),
        (-1001, -1, (-1, 0)),
        (-1000, 0, (-1, 0)),
        (-1, 1, (0, 1)),
    ],
)
@pytest.mark.parametrize("base", [datetime(1970, 1, 1, tzinfo=UTC), NOW])
def test_evidence_integer_millisecond_bounds_preserve_exact_half_open_interval(
    start_us, end_us, expected_ms, base
):
    start = base + timedelta(microseconds=start_us)
    end = base + timedelta(microseconds=end_us)
    statement = compile_query(
        binding(), ProductionQuery(kind="evidence", start=start, end=end)
    )
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    base_ms = (base - epoch).days * 86400000
    lower, upper = statement.params[1:3]
    assert (lower - base_ms, upper - base_ms) == expected_ms
    assert type(lower) is int and type(upper) is int
    # Compare the actual predicates against representable source timestamps.
    candidates = range(-2, 3)
    assert [n for n in candidates if lower <= base_ms + n < upper] == [
        n for n in candidates if start <= base + timedelta(milliseconds=n) < end
    ]
    validate_statement(statement)


def test_evidence_native_device_and_tool_name_are_bound():
    statement=compile_query(binding(),timed("evidence",device="PC",tool_name="Tool' OR 1=1"))
    assert "devicename = %s" in statement.sql and "toolsname = %s" in statement.sql
    assert "Tool' OR 1=1" not in statement.sql
    assert statement.params[-3:-1]==("PC","Tool' OR 1=1")
    validate_statement(statement)


def test_legacy_shape_registry_is_cached_and_immutable():
    from manufacturing_platform.production_tools.queries import _approved_templates
    first=_approved_templates('production_statistics')
    assert isinstance(first,frozenset)
    assert first is _approved_templates('production_statistics')
