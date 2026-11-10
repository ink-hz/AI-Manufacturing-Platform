"""Bounded native reads and safe evidence resolution; authorization belongs to service."""

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from threading import BoundedSemaphore
from urllib.parse import unquote, urlsplit

from ..workflow.contracts import DomainError
from .contracts import (
    EvidenceObject,
    ProductionQuery,
    SourceResult,
    SourceScope,
    valid_source_id,
)
from .queries import (
    CATALOG_TABLES,
    LOG_TABLES,
    compile_query,
    directory_statement,
    evidence_statement,
)

MAX_BYTES = 2 * 1024 * 1024
MAX_ATTACHMENT = 10 * 1024 * 1024
REDACTED = {"url", "url1", "url2", "url3", "data", "updatedata", "launcherdata"}
CREDENTIAL_MARKERS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "accesskey",
    "privatekey",
    "authorization",
    "connectionstring",
)


def error(code="SOURCE_UNAVAILABLE", status=503):
    return DomainError(
        code,
        status,
        {
            "SOURCE_UNAVAILABLE": "Production source is unavailable",
            "SOURCE_SCHEMA_INVALID": "Production source returned invalid data",
            "SOURCE_LIMIT_EXCEEDED": "Production source limit exceeded",
            "SOURCE_NOT_FOUND": "Source evidence is unavailable",
            "SOURCE_BUSY": "Production source is busy",
            "SOURCE_INVALID_QUERY": "Invalid production source query",
        }[code],
    )


def normalize(value, redactions):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise error("SOURCE_SCHEMA_INVALID")
            marker = re.sub(r"[^a-z0-9]", "", key.lower())
            if marker in REDACTED or any(part in marker for part in CREDENTIAL_MARKERS):
                redactions.add(key)
            else:
                result[key] = normalize(item, redactions)
        return result
    if isinstance(value, (list, tuple)):
        return [normalize(item, redactions) for item in value]
    if isinstance(value, datetime):
        return (
            value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
            if value.tzinfo is None
            else value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        )
    if isinstance(value, Decimal):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise error("SOURCE_SCHEMA_INVALID")


class BoundedStream:
    """Never returns bytes beyond the declared size or policy cap, even for lying streams."""

    def __init__(self, stream, size, max_bytes, release=None):
        self._stream, self._size, self._max, self._release = (
            stream,
            size,
            max_bytes,
            release,
        )
        self._read = 0
        self.closed = False

    def read(self, size=-1):
        if self.closed:
            raise ValueError("closed evidence stream")
        remaining = min(self._size, self._max) - self._read
        requested = (
            remaining + 1 if size is None or size < 0 else min(size, remaining + 1)
        )
        try:
            data = self._stream.read(requested)
            if not isinstance(data, bytes) or len(data) > remaining:
                raise error("SOURCE_LIMIT_EXCEEDED", 422)
            self._read += len(data)
            if len(data) < requested and self._read != self._size:
                raise error("SOURCE_SCHEMA_INVALID")
            return data
        except DomainError:
            self.close()
            raise
        except Exception:  # noqa: BLE001 - Sanitize all SDK/private configuration errors.
            self.close()
            raise error() from None

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self._stream.close()
            except Exception:  # noqa: BLE001, S110 - Cleanup must not expose SDK errors.
                pass
            finally:
                if self._release is not None:
                    self._release()
                    self._release = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class NativeProductionSource:
    def __init__(self, mysql, questdb, objects, *, allowed_object_host, clock):
        self.mysql, self.questdb, self.objects = mysql, questdb, objects
        self.allowed_object_host, self.clock = allowed_object_host, clock
        self._slots = BoundedSemaphore(4)

    @property
    def capabilities(self):
        result = set(CATALOG_TABLES) if self.mysql is not None else set()
        if self.questdb is not None:
            result.update(LOG_TABLES)
            result.update({"production_statistics", "stopover_statistics"})
        if (
            self.mysql is not None
            and self.objects is not None
            and self.allowed_object_host
        ):
            result.add("evidence_content")
        return frozenset(result)

    def _select(self, statement):
        reader = self.mysql if statement.backend == "mysql" else self.questdb
        if reader is None:
            raise error()
        try:
            return reader.select(statement)
        except DomainError:
            raise
        except Exception:  # noqa: BLE001 - Sanitize all SDK/private configuration errors.
            raise error() from None

    def _directory(self, *, before_id=None, source_project_id=None):
        try:
            statement = directory_statement(
                before_id=before_id, source_project_id=source_project_id
            )
        except ValueError:
            raise error("SOURCE_INVALID_QUERY", 422) from None
        if not self._slots.acquire(blocking=False):
            raise error("SOURCE_BUSY")
        try:
            rows = self._select(statement)
            if not isinstance(rows, list) or len(rows) > statement.max_rows:
                raise error("SOURCE_SCHEMA_INVALID")
            items, previous = [], int(before_id) if before_id else None
            for row in rows:
                if not isinstance(row, dict) or set(row) != {"id", "name"}:
                    raise error("SOURCE_SCHEMA_INVALID")
                identifier = row["id"]
                if type(identifier) not in (str, int) or not valid_source_id(
                    str(identifier)
                ):
                    raise error("SOURCE_SCHEMA_INVALID")
                identifier = str(identifier)
                if (previous is not None and int(identifier) >= previous) or (
                    source_project_id is not None and identifier != source_project_id
                ):
                    raise error("SOURCE_SCHEMA_INVALID")
                name = row["name"]
                if not isinstance(name, str) or len(name.encode("utf-8")) > 4096:
                    raise error("SOURCE_SCHEMA_INVALID")
                previous = int(identifier)
                items.append({"id": identifier, "name": name})
            return items
        except (UnicodeError, ValueError, TypeError):
            raise error("SOURCE_SCHEMA_INVALID") from None
        finally:
            self._slots.release()

    def projects(self, *, before_id=None):
        items = self._directory(before_id=before_id)
        return {
            "items": items[:100],
            "limit": 100,
            "has_more": len(items) > 100,
            "next_before_id": items[99]["id"] if len(items) > 100 else None,
        }

    def project(self, source_project_id):
        items = self._directory(source_project_id=source_project_id)
        if not items:
            raise error("SOURCE_NOT_FOUND", 404)
        if len(items) != 1:
            raise error("SOURCE_SCHEMA_INVALID")
        return items[0]

    def query(
        self, binding: SourceScope, query: ProductionQuery, *, cap: int = 1000
    ) -> SourceResult:
        try:
            statement = compile_query(binding, query, cap=cap)
        except ValueError:
            raise error("SOURCE_INVALID_QUERY", 422) from None
        if not self._slots.acquire(blocking=False):
            raise error("SOURCE_BUSY")
        try:
            rows = self._select(statement)
            if not isinstance(rows, list) or len(rows) > statement.max_rows:
                raise error("SOURCE_SCHEMA_INVALID")
            redactions = set()
            items = []
            item_bytes = 2
            captured_at = self.clock().astimezone(UTC)
            filters = query.model_dump(mode="json", exclude_none=True)
            statistics = query.kind.endswith("_statistics")
            if statistics and len(rows) != 1:
                raise error("SOURCE_SCHEMA_INVALID")
            previous_id = None
            for row in rows:
                if not isinstance(row, dict):
                    raise error("SOURCE_SCHEMA_INVALID")
                if (
                    not statistics
                    and str(row.get("projuectid")) != binding.source_project_id
                ):
                    raise error("SOURCE_SCHEMA_INVALID")
                if statement.backend == "mysql":
                    row_id = row.get("id")
                    if (
                        type(row_id) is not int
                        or row_id <= 0
                        or (previous_id is not None and row_id > previous_id)
                    ):
                        raise error("SOURCE_SCHEMA_INVALID")
                    previous_id = row_id
            reason = "row_limit" if len(rows) > cap else None
            for row in rows[:cap]:
                candidate_redactions = set(redactions)
                item = normalize(row, candidate_redactions)
                if statistics:
                    try:
                        aliases = (
                            "records",
                            "distinct_sn",
                            "pass_records",
                            "fail_records",
                        )
                        if any(key not in row for key in aliases):
                            raise ValueError()
                        values = {key: row[key] for key in aliases}
                        if any(
                            type(values[key]) is not int
                            for key in ("records", "distinct_sn")
                        ):
                            raise ValueError()
                        if any(
                            value is not None and (type(value) is not int)
                            for value in values.values()
                        ):
                            raise ValueError()
                        item = {key: value or 0 for key, value in values.items()}
                        if (
                            any(value < 0 for value in item.values())
                            or item["pass_records"] + item["fail_records"]
                            > item["records"]
                            or item["distinct_sn"] > item["records"]
                        ):
                            raise ValueError()
                        item["consistency"] = "single_query"
                        item["unknown_records"] = (
                            item["records"]
                            - item["pass_records"]
                            - item["fail_records"]
                        )
                        item["record_pass_ratio"] = (
                            item["pass_records"] / item["records"]
                            if item["records"]
                            else None
                        )
                    except (TypeError, ValueError, OverflowError):
                        raise error("SOURCE_SCHEMA_INVALID") from None
                try:
                    row_bytes = len(
                        json.dumps(
                            item,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            allow_nan=False,
                        ).encode("utf-8")
                    )
                    envelope = {
                        "source_kind": query.kind,
                        "items": [],
                        "captured_at": captured_at.isoformat(),
                        "filters": filters,
                        "complete": False,
                        "truncation_reason": "byte_limit",
                        "next_before_id": item.get("id")
                        if statement.backend == "mysql"
                        else None,
                        "redacted_fields": sorted(candidate_redactions),
                    }
                    byte_size = (
                        item_bytes
                        + row_bytes
                        + bool(items)
                        - 2
                        + len(
                            json.dumps(
                                envelope,
                                ensure_ascii=False,
                                separators=(",", ":"),
                                allow_nan=False,
                            ).encode("utf-8")
                        )
                    )
                except (TypeError, ValueError, UnicodeError):
                    raise error("SOURCE_SCHEMA_INVALID") from None
                if byte_size > MAX_BYTES:
                    if not items:
                        raise error("SOURCE_LIMIT_EXCEEDED", 422)
                    reason = "byte_limit"
                    break
                items.append(item)
                item_bytes += row_bytes + (len(items) > 1)
                redactions = candidate_redactions
            next_id = None
            if reason and statement.backend == "mysql" and items:
                candidate = items[-1].get("id")
                if type(candidate) is not int or candidate <= 0:
                    raise error("SOURCE_SCHEMA_INVALID")
                next_id = candidate
            return SourceResult(
                query.kind,
                items,
                captured_at,
                filters,
                reason is None,
                reason,
                next_id,
                tuple(sorted(redactions)),
            )
        finally:
            self._slots.release()

    def analysis(self, scope, filters, view):
        from .analytics import analysis
        return analysis(self, scope, filters, view)

    def availability(self, scope):
        from .analytics import availability
        return availability(self, scope)

    def overview(self, namespace, filters, *, before_id=None):
        from .analytics import overview
        return overview(self, namespace, filters, before_id=before_id)

    def evidence(
        self,
        binding: SourceScope,
        source_log_id: int,
        *,
        before_open: Callable[[], None] | None = None,
    ) -> EvidenceObject:
        if (
            self.objects is None
            or not self.allowed_object_host
            or not binding.object_prefix
        ):
            raise error("SOURCE_NOT_FOUND", 404)
        try:
            statement = evidence_statement(binding, source_log_id)
        except ValueError:
            raise error("SOURCE_INVALID_QUERY", 422) from None
        if not self._slots.acquire(blocking=False):
            raise error("SOURCE_BUSY")
        release = True
        opened = None
        try:
            rows = self._select(statement)
            if not isinstance(rows, list) or any(
                not isinstance(row, dict) for row in rows
            ):
                raise error("SOURCE_SCHEMA_INVALID")
            if len(rows) != 1:
                raise error("SOURCE_NOT_FOUND", 404)
            row = rows[0]
            if (
                str(row.get("projuectid")) != binding.source_project_id
                or row.get("del") != 0
                or row.get("id") != source_log_id
            ):
                raise error("SOURCE_NOT_FOUND", 404)
            try:
                url = row.get("url")
                if not isinstance(url, str) or any(ord(c) < 32 for c in url):
                    raise ValueError()
                parsed = urlsplit(url)
                if (
                    parsed.scheme != "https"
                    or parsed.hostname != self.allowed_object_host
                    or parsed.netloc != self.allowed_object_host
                    or parsed.query
                    or parsed.fragment
                    or "?" in url
                    or "#" in url
                ):
                    raise ValueError()
                key = unquote(parsed.path, errors="strict").removeprefix("/")
                if (
                    "%" in key
                    or "\\" in key
                    or any(ord(c) < 32 for c in key)
                    or any(part in {"", ".", ".."} for part in key.split("/"))
                    or not key.startswith(binding.object_prefix)
                ):
                    raise ValueError()
            except (ValueError, UnicodeError):
                raise error("SOURCE_NOT_FOUND", 404) from None
            if before_open is not None:
                before_open()
            try:
                opened = self.objects.open(key, max_bytes=MAX_ATTACHMENT)
            except DomainError:
                raise
            except Exception:  # noqa: BLE001 - Sanitize all SDK/private configuration errors.
                raise error() from None
            if type(opened.size) is not int or not 0 <= opened.size <= MAX_ATTACHMENT:
                raise error("SOURCE_LIMIT_EXCEEDED", 422)
            stream = BoundedStream(
                opened.stream, opened.size, MAX_ATTACHMENT, self._slots.release
            )
            release = False
            return EvidenceObject(stream, opened.size, key.rsplit("/", 1)[-1])
        except Exception:
            if opened is not None:
                try:
                    opened.stream.close()
                except Exception:  # noqa: BLE001, S110 - Cleanup must not expose SDK errors.
                    pass
            raise
        finally:
            if release:
                self._slots.release()
