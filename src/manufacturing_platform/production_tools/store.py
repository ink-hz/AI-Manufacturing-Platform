"""Dataset-bound immutable observation cache, independent of workflow schemas."""

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from ..workflow.clock import checked_time
from ..workflow.contracts import DomainError
from .contracts import SourceBinding, SourceResult
from .queries import CATALOG_TABLES
from .source import MAX_BYTES, error, normalize


def validate_snapshot_path(path: str, protected_paths: Iterable[str] = ()) -> None:
    candidate = Path(path)
    if (
        not path
        or not candidate.is_absolute()
        or candidate.is_symlink()
        or (candidate.exists() and not candidate.is_file())
    ):
        raise ValueError("invalid snapshot path")
    for protected in protected_paths:
        other = Path(protected)
        if candidate.resolve() == other.resolve() or (
            candidate.exists() and other.exists() and candidate.samefile(other)
        ):
            raise ValueError("snapshot path must be isolated")


def _json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _public_value(value):
    """Project exact observations to JSON values a JavaScript reader can retain."""
    if type(value) is int and abs(value) > 9007199254740991:
        return str(value)
    if isinstance(value, dict):
        return {key: _public_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_public_value(item) for item in value]
    return value


def _public_row(row):
    projected = _public_value(row)
    if type(row.get("id")) is int:
        projected["id"] = str(row["id"])
    return projected


def _retained_cursor(source_kind, items):
    if source_kind not in CATALOG_TABLES:
        return None
    candidate = items[-1].get("id")
    if type(candidate) is not int or candidate <= 0:
        raise error("SOURCE_SCHEMA_INVALID")
    return candidate


def _fingerprint(binding):
    return hashlib.sha256(
        _json({key: str(value) for key, value in vars(binding).items()}).encode()
    ).hexdigest()


def _missing():
    return DomainError("NOT_FOUND", 404, "Workflow resource not found")


class SnapshotStore:
    def __init__(self, path: str, dataset: dict[str, str], *, clock):
        validate_snapshot_path(path)
        if (
            set(dataset) != {"id", "mode", "label"}
            or not dataset["id"]
            or not dataset["label"]
            or dataset["mode"] not in {"production", "demo", "test"}
        ):
            raise ValueError("invalid snapshot dataset")
        self.path, self.dataset, self.clock = path, dict(dataset), clock
        checked_time(clock)
        fresh = False
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
            fresh = True
        with sqlite3.connect(path) as conn:
            if fresh:
                conn.executescript("""
                    CREATE TABLE metadata(version INTEGER NOT NULL, dataset_id TEXT NOT NULL, dataset_mode TEXT NOT NULL, dataset_label TEXT NOT NULL);
                    CREATE TABLE snapshots(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, binding_revision TEXT NOT NULL, source_namespace TEXT NOT NULL, source_project_id TEXT NOT NULL, source_kind TEXT NOT NULL, captured_at TEXT NOT NULL, expires_at TEXT NOT NULL, payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL);
                    CREATE INDEX snapshots_project_expiry ON snapshots(project_id, expires_at);
                """)
                conn.execute(
                    "INSERT INTO metadata VALUES (1,?,?,?)",
                    tuple(self.dataset[key] for key in ("id", "mode", "label")),
                )
            self._validate(conn)
        os.chmod(path, 0o600)

    def _validate(self, conn):
        expected = (1, *(self.dataset[key] for key in ("id", "mode", "label")))
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if tables != {"metadata", "snapshots"}:
            raise ValueError("unrecognized snapshot database")
        expected_columns = (
            "id",
            "project_id",
            "binding_revision",
            "source_namespace",
            "source_project_id",
            "source_kind",
            "captured_at",
            "expires_at",
            "payload_json",
            "payload_sha256",
        )
        if (
            tuple(row[1] for row in conn.execute("PRAGMA table_info(snapshots)"))
            != expected_columns
        ):
            raise ValueError("unrecognized snapshot schema")
        try:
            rows = conn.execute(
                "SELECT version,dataset_id,dataset_mode,dataset_label FROM metadata"
            ).fetchall()
        except sqlite3.Error:
            raise ValueError("unrecognized snapshot database") from None
        if rows != [expected]:
            raise ValueError("snapshot dataset mismatch")

    @contextmanager
    def _transaction(self, *, write=False):
        validate_snapshot_path(self.path)
        conn = sqlite3.connect(
            f"{Path(self.path).as_uri()}?mode=rw",
            uri=True,
            timeout=5,
            isolation_level=None,
        )
        conn.row_factory = None
        try:
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            self._validate(conn)
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def put(self, binding: SourceBinding, result: SourceResult) -> UUID:
        if binding.dataset_id != self.dataset["id"]:
            raise ValueError("snapshot binding dataset mismatch")
        now = checked_time(self.clock)
        redactions = set(result.redacted_fields)
        items = normalize(result.items, redactions)
        filters = normalize(result.filters, redactions)
        captured_at = normalize(result.captured_at, set())
        reason = "row_limit" if len(items) > 1000 else result.truncation_reason
        items = items[:1000]
        payload = {
            "dataset": self.dataset,
            "binding_fingerprint": _fingerprint(binding),
            "query_version": 1,
            "source_kind": result.source_kind,
            "captured_at": captured_at,
            "filters": filters,
            "complete": result.complete and reason is None,
            "truncation_reason": reason,
            "next_before_id": (
                _retained_cursor(result.source_kind, items)
                if len(result.items) > 1000
                else result.next_before_id
            ),
            "redacted_fields": sorted(redactions),
            "items": items,
        }
        while len(_json(payload).encode()) > MAX_BYTES:
            if len(items) <= 1:
                raise error("SOURCE_LIMIT_EXCEEDED", 422)
            items.pop()
            payload.update(
                complete=False,
                truncation_reason="byte_limit",
                next_before_id=_retained_cursor(result.source_kind, items),
            )
        encoded = _json(payload)
        sid = uuid4()
        with self._transaction(write=True) as conn:
            conn.execute(
                "DELETE FROM snapshots WHERE id IN (SELECT id FROM snapshots WHERE expires_at<=? LIMIT 100)",
                (now.isoformat(),),
            )
            count = conn.execute(
                "SELECT COUNT(*) FROM snapshots WHERE project_id=? AND expires_at>?",
                (str(binding.project_id), now.isoformat()),
            ).fetchone()[0]
            if count >= 100:
                raise DomainError(
                    "SOURCE_UNAVAILABLE",
                    503,
                    "Observation retention limit reached; retry after expiry",
                )
            conn.execute(
                "INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    str(sid),
                    str(binding.project_id),
                    binding.revision,
                    binding.source_namespace,
                    binding.source_project_id,
                    result.source_kind,
                    captured_at,
                    (now + timedelta(hours=24)).isoformat(),
                    encoded,
                    hashlib.sha256(encoded.encode()).hexdigest(),
                ),
            )
        return sid

    def get(
        self,
        project_id: UUID,
        snapshot_id: UUID,
        binding: SourceBinding,
        *,
        offset=0,
        limit=50,
    ) -> dict:
        if (
            type(offset) is not int
            or offset < 0
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise error("SOURCE_INVALID_QUERY", 422)
        if binding.project_id != project_id or binding.dataset_id != self.dataset["id"]:
            raise _missing()
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT binding_revision,source_namespace,source_project_id,expires_at,payload_json,payload_sha256 FROM snapshots WHERE id=? AND project_id=?",
                (str(snapshot_id), str(project_id)),
            ).fetchone()
        if row is None or row[:3] != (
            binding.revision,
            binding.source_namespace,
            binding.source_project_id,
        ):
            raise _missing()
        if hashlib.sha256(row[4].encode()).hexdigest() != row[5]:
            raise error("SOURCE_SCHEMA_INVALID")
        try:
            payload = json.loads(row[4])
            if payload["dataset"] != self.dataset or payload[
                "binding_fingerprint"
            ] != _fingerprint(binding):
                raise _missing()
            if row[3] <= checked_time(self.clock).isoformat():
                raise DomainError(
                    "SNAPSHOT_EXPIRED", 410, "Observation snapshot expired"
                )
            items = payload["items"]
            return {
                key: payload[key]
                for key in (
                    "source_kind",
                    "captured_at",
                    "complete",
                    "truncation_reason",
                    "redacted_fields",
                )
            } | {
                "snapshot_id": str(snapshot_id),
                "project_id": str(project_id),
                "items": [_public_row(item) for item in items[offset : offset + limit]],
                "next_before_id": (
                    str(payload["next_before_id"])
                    if payload["next_before_id"] is not None
                    else None
                ),
                "filters": {
                    key: str(value)
                    if key in {"parent_id", "before_id"} and type(value) is int
                    else _public_value(value)
                    for key, value in payload["filters"].items()
                },
                "offset": offset,
                "limit": limit,
                "captured_count": len(items),
                "has_more": offset + limit < len(items),
                "expires_at": row[3],
            }
        except (ValueError, KeyError, TypeError):
            raise error("SOURCE_SCHEMA_INVALID") from None
