"""Native SDK transports. Enforced session controls cannot be overridden."""

from .contracts import EvidenceObject
from .queries import validate_statement
from .source import BoundedStream, error

MYSQL_KEYS = {"host", "port", "user", "password", "database"}
QUESTDB_KEYS = {"host", "port", "user", "password", "dbname"}


def validate_options(options, allowed):
    if not isinstance(options, dict) or set(options) - allowed:
        raise ValueError("invalid native source options")
    for key, value in options.items():
        if key == "port":
            if type(value) is not int or not 1 <= value <= 65535:
                raise ValueError("invalid native source options")
        elif not isinstance(value, str) or not value:
            raise ValueError("invalid native source options")
    return dict(options)


class MySqlReader:
    def __init__(self, options, *, connect=None):
        self._options = validate_options(options, MYSQL_KEYS)
        self._connect = connect

    def select(self, statement):
        validate_statement(statement)
        if statement.backend != "mysql":
            raise ValueError("wrong source backend")
        connection = None
        failed = False
        rows = None
        try:
            connect = self._connect
            if connect is None:
                import pymysql

                connect = pymysql.connect
                options = {"cursorclass": pymysql.cursors.DictCursor, **self._options}
            else:
                options = self._options
            connection = connect(
                connect_timeout=5,
                read_timeout=10,
                write_timeout=10,
                local_infile=False,
                autocommit=False,
                **options,
            )
            with connection.cursor() as cursor:
                cursor.execute("START TRANSACTION READ ONLY")
                cursor.execute(statement.sql, statement.params)
                rows = cursor.fetchmany(statement.max_rows)
        except Exception:  # noqa: BLE001 - Sanitize all SDK/private configuration errors.
            failed = True
        finally:
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:  # noqa: BLE001 - Sanitize all SDK/private configuration errors.
                    failed = True
                finally:
                    try:
                        connection.close()
                    except Exception:  # noqa: BLE001 - Sanitize all SDK/private configuration errors.
                        failed = True
        if failed:
            raise error() from None
        return list(rows)


class QuestDbReader:
    def __init__(self, options, *, connect=None):
        self._options = validate_options(options, QUESTDB_KEYS)
        self._connect = connect

    def select(self, statement):
        validate_statement(statement)
        if statement.backend != "questdb":
            raise ValueError("wrong source backend")
        try:
            connect = self._connect
            if connect is None:
                import psycopg
                from psycopg.rows import dict_row

                connect = psycopg.connect
                options = {"row_factory": dict_row, **self._options}
            else:
                options = self._options
            with (
                connect(
                    autocommit=True,
                    prepare_threshold=None,
                    connect_timeout=5,
                    options="-c statement_timeout=10000",
                    **options,
                ) as connection,
                connection.cursor() as cursor,
            ):
                cursor.execute(statement.sql, statement.params)
                rows = cursor.fetchmany(statement.max_rows)
            return list(rows)
        except Exception:  # noqa: BLE001 - Sanitize all SDK/private configuration errors.
            raise error() from None


class OssObjectReader:
    def __init__(self, bucket):
        self._bucket = bucket

    def open(self, key, *, max_bytes):
        if (
            not isinstance(key, str)
            or any(part in {"", ".", ".."} for part in key.split("/"))
            or any(c in key for c in ("\\", "%", "\x00"))
        ):
            raise ValueError("invalid object key")
        if type(max_bytes) is not int or not 0 < max_bytes <= 10 * 1024 * 1024:
            raise ValueError("invalid object bound")
        stream = None
        try:
            stream = self._bucket.get_object(key)
            size = stream.content_length
            if type(size) is not int or not 0 <= size <= max_bytes:
                raise error("SOURCE_LIMIT_EXCEEDED", 422)
            return EvidenceObject(
                BoundedStream(stream, size, max_bytes), size, key.rsplit("/", 1)[-1]
            )
        except Exception as exc:
            if stream is not None:
                try:
                    stream.close()
                except Exception:  # noqa: BLE001, S110 - Cleanup must not expose SDK errors.
                    pass
            from ..workflow.contracts import DomainError

            if isinstance(exc, DomainError):
                raise
            raise error() from None


class _ConfiguredOssReader:
    """Delay SDK loading until this capability is used; never provision a bucket."""

    def __init__(self, options):
        self._options = options

    def open(self, key, *, max_bytes):
        try:
            import oss2

            auth = oss2.Auth(
                self._options["access_key_id"], self._options["access_key_secret"]
            )
            bucket = oss2.Bucket(
                auth,
                self._options["endpoint"],
                self._options["bucket"],
                connect_timeout=(5, 10),
            )
            return OssObjectReader(bucket).open(key, max_bytes=max_bytes)
        except Exception as exc:
            from ..workflow.contracts import DomainError

            if isinstance(exc, DomainError):
                raise
            # SDK construction errors may contain credentials or private endpoints.
            raise error() from None


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid native source configuration")
        result[key] = value
    return result


def _object_options(options):
    from urllib.parse import urlsplit

    required = {
        "endpoint",
        "bucket",
        "access_key_id",
        "access_key_secret",
        "allowed_host",
    }
    options = validate_options(options, required)
    if set(options) != required:
        raise ValueError("invalid native source configuration")
    host = options["allowed_host"]
    parsed_host = urlsplit("https://" + host)
    endpoint = urlsplit(options["endpoint"])
    if (
        parsed_host.hostname != host
        or parsed_host.netloc != host
        or parsed_host.path
        or parsed_host.query
        or parsed_host.fragment
        or ":" in host
        or not host
        or any(c.isspace() for c in host)
        or endpoint.scheme != "https"
        or endpoint.netloc != endpoint.hostname
        or endpoint.path not in {"", "/"}
        or endpoint.query
        or endpoint.fragment
    ):
        raise ValueError("invalid native source configuration")
    return options


def build_native_config(config_path: str, snapshot_path: str, *, investigation_path: str | None = None):
    """Load private trusted JSON. Raw credentials remain inside native readers only."""
    import json
    import os
    import stat
    from datetime import UTC, datetime

    from .contracts import ProductionToolsConfig
    from .source import NativeProductionSource

    descriptor = None
    try:
        if not isinstance(config_path, str) or not os.path.isabs(config_path):
            raise ValueError()
        descriptor = os.open(config_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid not in {0, os.geteuid()}
            or info.st_mode & 0o077
            or info.st_size > 128 * 1024
        ):
            raise ValueError()
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            descriptor = None
            raw = json.load(stream, object_pairs_hook=_no_duplicate_keys)
        if not isinstance(raw, dict) or set(raw) - {
            "version",
            "source_namespace",
            "revision",
            "mysql",
            "questdb",
            "objects",
            "object_prefixes",
        }:
            raise ValueError()
        if type(raw.get("version")) is not int or raw["version"] != 2:
            raise ValueError()
        if not isinstance(raw.get("object_prefixes"), dict):
            raise ValueError()  # noqa: TRY004 - Configuration errors share one safe type.
        readers = {}
        for key, allowed, reader_class in [
            ("mysql", MYSQL_KEYS, MySqlReader),
            ("questdb", QUESTDB_KEYS, QuestDbReader),
        ]:
            if key in raw:
                options = validate_options(raw[key], allowed)
                if key == "questdb":
                    options.setdefault("dbname", "qdb")
                if set(options) != allowed:
                    raise ValueError()
                readers[key] = reader_class(options)
        objects, host = None, ""
        if "objects" in raw:
            options = _object_options(raw["objects"])
            objects, host = _ConfiguredOssReader(options), options["allowed_host"]
        source = NativeProductionSource(
            readers.get("mysql"),
            readers.get("questdb"),
            objects,
            allowed_object_host=host,
            clock=lambda: datetime.now(UTC),
        )
        from .store import validate_snapshot_path
        independent_path = investigation_path or snapshot_path + ".investigations.sqlite3"
        validate_snapshot_path(snapshot_path, (config_path, independent_path))
        validate_snapshot_path(independent_path, (config_path, snapshot_path))
        return ProductionToolsConfig(
            source,
            raw["source_namespace"],
            raw["revision"],
            raw["object_prefixes"],
            snapshot_path,
            investigation_path,
            (config_path,),
        )
    except Exception:  # noqa: BLE001 - Sanitize all SDK/private configuration errors.
        raise ValueError("invalid native source configuration") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
