from decimal import Decimal
from io import BytesIO

import pytest
from test_queries import NOW, binding, timed

from manufacturing_platform.production_tools.contracts import (
    EvidenceObject,
    ProductionQuery,
)
from manufacturing_platform.production_tools.source import NativeProductionSource
from manufacturing_platform.workflow.contracts import DomainError


class RecordingReader:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def select(self, statement):
        self.calls.append(statement)
        return self.rows[: statement.max_rows]


class Objects:
    def __init__(self, data=b"abc", size=3):
        self.data, self.size, self.keys = data, size, []

    def open(self, key, *, max_bytes):
        self.keys.append(key)
        self.stream = BytesIO(self.data)
        return EvidenceObject(self.stream, self.size, "unsafe-name")


def source(rows, objects=None):
    reader = RecordingReader(rows)
    return NativeProductionSource(
        reader,
        reader,
        objects,
        allowed_object_host="example.invalid",
        clock=lambda: NOW,
    )


def row(**kw):
    return {
        "id": 5,
        "projuectid": "10001",
        "timestamp": NOW,
        "sn": "SN",
        "status": "1",
        **kw,
    }


def test_duplicate_rows_preserved_and_row_truncation_honest():
    result = source([row() for _ in range(1001)]).query(binding(), timed())
    assert len(result.items) == 1000 and result.items[0] == result.items[1]
    assert not result.complete and result.truncation_reason == "row_limit"
    assert result.next_before_id is None


def test_normalization_redaction_and_raw_status():
    result = source(
        [
            row(
                data="private",
                updatedata="private",
                launcherdata="private",
                access_key_secret="private",
                Password="private",
                url="https://private",
                voltage=Decimal("1.2300"),
                nullable=None,
            )
        ]
    ).query(binding(), timed())
    item = result.items[0]
    assert (
        item["voltage"] == "1.2300"
        and item["nullable"] is None
        and item["status"] == "1"
    )
    assert item["timestamp"] == "2026-11-10T00:00:00Z"
    assert set(result.redacted_fields) == {
        "data",
        "updatedata",
        "launcherdata",
        "access_key_secret",
        "Password",
        "url",
    }
    assert "private" not in str(item)


@pytest.mark.parametrize("rows", [[row(projuectid="999")], [{"id": 1}]])
def test_wrong_or_missing_scope_rejected(rows):
    with pytest.raises(DomainError) as error:
        source(rows).query(binding(), timed())
    assert error.value.code == "SOURCE_SCHEMA_INVALID"


def test_unicode_bytes_and_first_row_overflow():
    result = source([row(id=i, text="汉" * 240000) for i in (3, 2, 1)]).query(
        binding(), ProductionQuery(kind="software")
    )
    assert len(result.items) == 2 and not result.complete
    assert result.truncation_reason == "byte_limit" and result.next_before_id == 2
    with pytest.raises(DomainError) as error:
        source([row(text="汉" * 800000)]).query(binding(), timed())
    assert error.value.code == "SOURCE_LIMIT_EXCEEDED"


def test_statistics_normalize_nulls_and_ratio():
    result = source(
        [{"records": 4, "distinct_sn": 2, "pass_records": 1, "fail_records": None}]
    ).query(binding(), timed("production_statistics"))
    assert result.items == [
        {
            "records": 4,
            "distinct_sn": 2,
            "pass_records": 1,
            "fail_records": 0,
            "unknown_records": 3,
            "record_pass_ratio": 0.25,
        }
    ]
    empty = source(
        [{"records": 0, "distinct_sn": 0, "pass_records": None, "fail_records": None}]
    ).query(binding(), timed("production_statistics"))
    assert empty.items[0]["record_pass_ratio"] is None


def test_evidence_reads_scoped_metadata_and_bounded_object():
    objects = Objects()
    src = source(
        [row(**{"del": 0}, url="https://example.invalid/logs/10001/file%20name.log")],
        objects,
    )
    evidence = src.evidence(binding(), 5)
    assert objects.keys == ["logs/10001/file name.log"]
    assert evidence.filename == "file name.log" and evidence.stream.read() == b"abc"
    evidence.stream.close()
    assert objects.stream.closed


@pytest.mark.parametrize(
    "override",
    [
        {"projuectid": 9},
        {"del": 1},
        {"id": 6},
        {"url": "https://other.invalid/logs/10001/x"},
        {"url": "https://example.invalid/logs/10001/x?q=1"},
        {"url": "https://example.invalid/logs/10001/%2e%2e/x"},
        {"url": "https://example.invalid/logs/10001/%252e%252e/x"},
        {"url": "https://example.invalid/else/x"},
        {"url": "https://example.invalid:443/logs/10001/x"},
        {"url": "https://user@example.invalid/logs/10001/x"},
    ],
)
def test_evidence_rejects_scope_deleted_or_unsafe_url(override):
    objects = Objects()
    with pytest.raises(DomainError):
        source(
            [
                row(
                    **{"del": 0},
                    url="https://example.invalid/logs/10001/x",
                    **{k: v for k, v in override.items() if k not in {"del", "url"}},
                )
                | override
            ],
            objects,
        ).evidence(binding(), 5)
    assert not objects.keys


@pytest.mark.parametrize(
    "size,data", [(None, b"abc"), (10 * 1024 * 1024 + 1, b"abc"), (2, b"abc")]
)
def test_evidence_missing_oversized_or_lying_length_closes(size, data):
    objects = Objects(data, size)
    src = source(
        [row(**{"del": 0}, url="https://example.invalid/logs/10001/x")], objects
    )
    with pytest.raises(DomainError):
        result = src.evidence(binding(), 5)
        result.stream.read()
    assert objects.stream.closed


def test_missing_capability_only_affects_selected_backend():
    src = NativeProductionSource(
        RecordingReader([row()]), None, None, allowed_object_host="", clock=lambda: NOW
    )
    assert src.query(binding(), ProductionQuery(kind="software")).complete
    with pytest.raises(DomainError):
        src.query(binding(), timed())


def test_query_concurrency_is_bounded():
    src = source([])
    for _ in range(4):
        assert src._slots.acquire(blocking=False)
    with pytest.raises(DomainError) as error:
        src.query(binding(), timed())
    assert error.value.code == "SOURCE_BUSY"
    for _ in range(4):
        src._slots.release()


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"records": "garbage"}],
        [{"records": 1, "pass_records": 2}],
        [{"records": 1.5}],
    ],
)
def test_bad_aggregate_schema_is_rejected(rows):
    with pytest.raises(DomainError) as error:
        source(rows).query(binding(), timed("production_statistics"))
    assert error.value.code == "SOURCE_SCHEMA_INVALID"


def test_stream_failure_closes_and_is_sanitized():
    class FailingStream(BytesIO):
        def read(self, size=-1):
            raise RuntimeError("SECRET endpoint")

    objects = Objects()

    def opened(key, *, max_bytes):
        objects.stream = FailingStream()
        return EvidenceObject(objects.stream, 3, "x")

    objects.open = opened
    result = source(
        [row(**{"del": 0}, url="https://example.invalid/logs/10001/x")], objects
    ).evidence(binding(), 5)
    with pytest.raises(DomainError) as error:
        result.stream.read()
    assert "SECRET" not in str(error.value) and objects.stream.closed


def test_credential_marker_redaction_is_normalized_and_recursive():
    result = source(
        [
            row(
                config={"Private-Key": "SECRET", "safe": 2},
                Connection_String="SECRET",
                Authorization="SECRET",
            )
        ]
    ).query(binding(), timed())
    assert result.items[0]["config"] == {"safe": 2}
    assert set(result.redacted_fields) == {
        "Private-Key",
        "Connection_String",
        "Authorization",
    }


@pytest.mark.parametrize(
    "mysql,questdb,objects,expected",
    [
        (
            True,
            False,
            False,
            {
                "software",
                "software_versions",
                "configs",
                "config_versions",
                "review_orders",
                "evidence",
            },
        ),
        (
            False,
            True,
            True,
            {"production", "stopover", "production_statistics", "stopover_statistics"},
        ),
        (
            True,
            False,
            True,
            {
                "software",
                "software_versions",
                "configs",
                "config_versions",
                "review_orders",
                "evidence",
                "evidence_content",
            },
        ),
        (False, False, True, set()),
    ],
)
def test_capabilities_truthfully_follow_available_transports(
    mysql, questdb, objects, expected
):
    reader = RecordingReader([])
    src = NativeProductionSource(
        reader if mysql else None,
        reader if questdb else None,
        Objects() if objects else None,
        allowed_object_host="example.invalid",
        clock=lambda: NOW,
    )
    assert src.capabilities == frozenset(expected)


def test_byte_cap_includes_redaction_metadata():
    with pytest.raises(DomainError) as error:
        source([row(**{"password" + "a" * (2 * 1024 * 1024): "SECRET"})]).query(
            binding(), timed()
        )
    assert error.value.code == "SOURCE_LIMIT_EXCEEDED"


def test_byte_cap_counts_the_result_envelope():
    import json
    from dataclasses import asdict

    from manufacturing_platform.production_tools.source import MAX_BYTES

    src = source([row(text="x" * (MAX_BYTES - 180))])
    try:
        result = src.query(binding(), timed())
    except DomainError as error:
        assert error.code == "SOURCE_LIMIT_EXCEEDED"
    else:
        payload = asdict(result)
        payload["captured_at"] = result.captured_at.isoformat()
        assert (
            len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
            <= MAX_BYTES
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://example.invalid//logs/10001/x",
        "https://example.invalid/logs/10001/x#",
        "https://example.invalid/logs/10001/x?",
        "https://example.invalid/logs/10001/a%00x",
        "https://example.invalid/logs/10001/",
    ],
)
def test_evidence_rejects_noncanonical_keys_and_empty_suffix(url):
    objects = Objects()
    with pytest.raises(DomainError):
        source([row(**{"del": 0}, url=url)], objects).evidence(binding(), 5)
    assert not objects.keys


def test_catalog_invalid_order_cannot_produce_skipping_continuation():
    with pytest.raises(DomainError) as error:
        source([row(id=2), row(id=3)]).query(
            binding(), ProductionQuery(kind="software")
        )
    assert error.value.code == "SOURCE_SCHEMA_INVALID"


@pytest.mark.parametrize("rows", [None, [None], [{"id": 5, "projuectid": "10001"}]])
def test_malformed_evidence_metadata_is_sanitized(rows):
    src = source([], Objects())
    src.mysql = type("Reader", (), {"select": lambda self, statement: rows})()
    with pytest.raises(DomainError):
        src.evidence(binding(), 5)
