from dataclasses import replace

import pytest
from test_queries import binding, timed

from manufacturing_platform.production_tools.contracts import (
    ProductionQuery,
)
from manufacturing_platform.production_tools.queries import compile_query
from manufacturing_platform.production_tools.transports import (
    MySqlReader,
    OssObjectReader,
    QuestDbReader,
)
from manufacturing_platform.workflow.contracts import DomainError


class Cursor:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if self.fail == "execute":
            raise RuntimeError("SECRET endpoint")

    def fetchmany(self, count):
        if self.fail == "fetch":
            raise RuntimeError("SECRET endpoint")
        return [{"id": 1}]


class Connection:
    def __init__(self, fail=None):
        self.cur = Cursor(fail)
        self.closed = False
        self.rolled = False
        self.fail = fail

    def cursor(self):
        return self.cur

    def rollback(self):
        self.rolled = True
        if self.fail == "rollback":
            raise RuntimeError("SECRET endpoint")

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@pytest.mark.parametrize(
    "backend,reader_cls", [("mysql", MySqlReader), ("questdb", QuestDbReader)]
)
@pytest.mark.parametrize("fail", ["execute", "fetch", None])
def test_native_lifetime_and_enforced_controls(backend, reader_cls, fail):
    connection = Connection(fail)
    calls = []

    def connect(**kw):
        calls.append(kw)
        return connection

    reader = reader_cls({"host": "fixture", "user": "reader"}, connect=connect)
    statement = compile_query(
        binding(), ProductionQuery(kind="software") if backend == "mysql" else timed()
    )
    if fail:
        with pytest.raises(DomainError) as error:
            reader.select(statement)
        assert "SECRET" not in str(error.value)
    else:
        assert reader.select(statement) == [{"id": 1}]
    assert connection.closed and connection.cur.closed
    assert calls[0]["connect_timeout"] == 5
    if backend == "mysql":
        assert (
            connection.rolled
            and calls[0]["read_timeout"] == 10
            and calls[0]["write_timeout"] == 10
        )
        assert calls[0]["local_infile"] is False and calls[0]["autocommit"] is False
        assert connection.cur.calls[0] == ("START TRANSACTION READ ONLY", None)
        assert not any("COMMIT" in sql for sql, _ in connection.cur.calls)
    else:
        assert calls[0]["options"] == "-c statement_timeout=10000"
        assert calls[0]["autocommit"] is True and calls[0]["prepare_threshold"] is None
        assert not connection.rolled


@pytest.mark.parametrize(
    "reader_cls,query",
    [(MySqlReader, ProductionQuery(kind="software")), (QuestDbReader, timed())],
)
def test_statement_rejected_before_connection(reader_cls, query):
    calls = []
    reader = reader_cls({}, connect=lambda **kw: calls.append(kw))
    statement = compile_query(binding(), query)
    for changed in [
        replace(statement, name="arbitrary"),
        replace(statement, sql="SELECT secret FROM other"),
        replace(statement, max_rows=9999),
        replace(statement, sql=statement.sql + "; SELECT 1"),
    ]:
        with pytest.raises(ValueError):
            reader.select(changed)
    assert not calls


@pytest.mark.parametrize("reader_cls", [MySqlReader, QuestDbReader])
def test_connect_errors_sanitized(reader_cls):
    def connect(**kw):
        raise RuntimeError("SECRET private endpoint")

    reader = reader_cls({}, connect=connect)
    with pytest.raises(DomainError) as error:
        reader.select(
            compile_query(
                binding(),
                ProductionQuery(kind="software")
                if reader_cls is MySqlReader
                else timed(),
            )
        )
    assert "SECRET" not in str(error.value) and error.value.__suppress_context__


@pytest.mark.parametrize(
    "option",
    [
        "autocommit",
        "connect_timeout",
        "read_timeout",
        "write_timeout",
        "local_infile",
        "client_flag",
        "options",
        "prepare_threshold",
        "init_command",
        "cursorclass",
        "row_factory",
    ],
)
@pytest.mark.parametrize("reader_cls", [MySqlReader, QuestDbReader])
def test_enforced_option_collisions_rejected(reader_cls, option):
    with pytest.raises(ValueError):
        reader_cls({option: True}, connect=lambda **kw: None)


def test_rollback_error_does_not_prevent_close():
    connection = Connection("rollback")
    with pytest.raises(DomainError):
        MySqlReader({}, connect=lambda **kw: connection).select(
            compile_query(binding(), ProductionQuery(kind="software"))
        )
    assert connection.closed


def test_oss_only_get_and_safe_key():
    class Bucket:
        def __init__(self):
            self.keys = []

        def get_object(self, key):
            from io import BytesIO

            self.keys.append(key)
            stream = BytesIO(b"abc")
            stream.content_length = 3
            return stream

    bucket = Bucket()
    reader = OssObjectReader(bucket)
    result = reader.open("logs/10001/x", max_bytes=10)
    assert result.stream.read() == b"abc" and bucket.keys == ["logs/10001/x"]
    for key in ["../x", "/x", "a//b", "a/%2e%2e/x", "a\\b"]:
        with pytest.raises(ValueError):
            reader.open(key, max_bytes=10)


import json

from manufacturing_platform.production_tools.transports import build_native_config


def config_payload():
    return {
        "dataset_id": "test",
        "mysql": {
            "host": "fixture",
            "port": 3306,
            "user": "reader",
            "password": "SECRET",
            "database": "fixture",
        },
        "bindings": [
            {
                "dataset_id": "test",
                "project_id": str(binding().project_id),
                "source_namespace": "fixture",
                "source_project_id": "10001",
                "revision": "v1",
                "object_prefix": "logs/10001/",
            }
        ],
    }


def config_file(tmp_path, payload=None):
    path = tmp_path / "native.json"
    path.write_text(json.dumps(config_payload() if payload is None else payload))
    path.chmod(0o600)
    return path


def test_factory_builds_standalone_config_without_connecting(tmp_path):
    config = build_native_config(
        str(config_file(tmp_path)),
        str(tmp_path / "snapshots.sqlite"),
        {"id": "test", "mode": "live", "label": "test"},
    )
    assert config.bindings[binding().project_id] == binding()
    assert config.source.capabilities == frozenset(
        {
            "software",
            "software_versions",
            "configs",
            "config_versions",
            "review_orders",
            "evidence",
        }
    )
    assert "SECRET" not in repr(config)


@pytest.mark.parametrize(
    "change",
    [
        "dataset",
        "duplicate",
        "mapping_dataset",
        "unknown",
        "collision",
        "prefix",
        "revision",
        "project",
        "objects",
        "password_type",
    ],
)
def test_factory_rejects_bad_config_without_secret_errors(tmp_path, change):
    payload = config_payload()
    if change == "dataset":
        payload["dataset_id"] = "other"
    elif change == "duplicate":
        payload["bindings"] *= 2
    elif change == "mapping_dataset":
        payload["bindings"][0]["dataset_id"] = "other"
    elif change == "unknown":
        payload["bridge_url"] = "SECRET"
    elif change == "collision":
        payload["mysql"]["client_flag"] = 1
    elif change == "prefix":
        payload["bindings"][0]["object_prefix"] = "../SECRET/"
    elif change == "revision":
        payload["bindings"][0]["revision"] = ""
    elif change == "project":
        payload["bindings"][0]["project_id"] = "SECRET"
    elif change == "objects":
        payload["objects"] = {"endpoint": "https://SECRET@host"}
    elif change == "password_type":
        payload["mysql"]["password"] = {"SECRET": "value"}
    with pytest.raises(ValueError) as error:
        build_native_config(
            str(config_file(tmp_path, payload)),
            str(tmp_path / "snapshots.sqlite"),
            {"id": "test"},
        )
    assert "SECRET" not in str(error.value)


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o660])
def test_factory_requires_private_regular_owned_absolute_file(tmp_path, mode):
    path = config_file(tmp_path)
    path.chmod(mode)
    with pytest.raises(ValueError):
        build_native_config(str(path), str(tmp_path / "snapshot"), {"id": "test"})


def test_factory_rejects_symlink_relative_and_duplicate_json_keys(tmp_path):
    path = config_file(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(path)
    for candidate in [str(link), "relative.json", str(tmp_path)]:
        with pytest.raises(ValueError):
            build_native_config(candidate, str(tmp_path / "snapshot"), {"id": "test"})
    path.write_text('{"dataset_id":"test","dataset_id":"test","bindings":[]}')
    with pytest.raises(ValueError):
        build_native_config(str(path), str(tmp_path / "snapshot"), {"id": "test"})


@pytest.mark.parametrize("sdk", ["pymysql", "psycopg", "oss2"])
def test_sdk_versions_import_in_isolated_probe_environment(sdk):
    pytest.importorskip(sdk)


def test_configured_oss_enforces_connect_and_read_timeouts(monkeypatch):
    import sys
    from io import BytesIO
    from types import SimpleNamespace

    from manufacturing_platform.production_tools.transports import _ConfiguredOssReader

    calls = []

    class Bucket:
        def __init__(self, *args, **kwargs):
            calls.append(kwargs)

        def get_object(self, key):
            stream = BytesIO(b"a")
            stream.content_length = 1
            return stream

    monkeypatch.setitem(
        sys.modules, "oss2", SimpleNamespace(Auth=lambda *args: None, Bucket=Bucket)
    )
    reader = _ConfiguredOssReader(
        {
            "access_key_id": "fixture",
            "access_key_secret": "SECRET",
            "endpoint": "https://example.invalid",
            "bucket": "fixture",
        }
    )
    result = reader.open("logs/10001/x", max_bytes=10)
    assert result.stream.read() == b"a"
    result.stream.close()
    assert calls == [{"connect_timeout": (5, 10)}]


def test_mysql_cursor_setup_failure_is_sanitized_and_closed():
    connection = Connection()

    def cursor():
        raise RuntimeError("SECRET")

    connection.cursor = cursor
    with pytest.raises(DomainError) as error:
        MySqlReader({}, connect=lambda **kw: connection).select(
            compile_query(binding(), ProductionQuery(kind="software"))
        )
    assert connection.closed and connection.rolled and "SECRET" not in str(error.value)
