"""Public contracts for bounded, source-scoped external observations."""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, BinaryIO, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

SourceKind = Literal[
    "production",
    "stopover",
    "software",
    "software_versions",
    "configs",
    "config_versions",
    "review_orders",
    "evidence",
    "production_statistics",
    "stopover_statistics",
]
TIMED_KINDS = {
    "production",
    "stopover",
    "evidence",
    "production_statistics",
    "stopover_statistics",
}


class ProductionQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: SourceKind
    start: datetime | None = None
    end: datetime | None = None
    sn: str | None = Field(default=None, min_length=1, max_length=200)
    order_id: str | None = Field(default=None, pattern=r"^[1-9][0-9]{0,19}$")
    device: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["1", "2"] | None = None
    parent_id: int | None = Field(
        default=None, ge=1, le=99999999999999999999, strict=True
    )
    before_id: int | None = Field(
        default=None, ge=1, le=99999999999999999999, strict=True
    )

    @model_validator(mode="after")
    def bounded_window(self):
        if self.kind in TIMED_KINDS:
            if self.start is None or self.end is None:
                raise ValueError("time range required")
            if self.start.utcoffset() is None or self.end.utcoffset() is None:
                raise ValueError("timezone required")
            if (
                not 0
                < (
                    self.end.astimezone(UTC) - self.start.astimezone(UTC)
                ).total_seconds()
                <= 31 * 86400
            ):
                raise ValueError("time range must be within 31 days")
        elif self.start is not None or self.end is not None:
            raise ValueError("catalog does not accept a time range")
        if self.kind in TIMED_KINDS - {"evidence"} and self.before_id is not None:
            raise ValueError("source has no verified unique row key")
        return self


def canonical_prefix(value: str) -> bool:
    return (
        isinstance(value, str)
        and value.endswith("/")
        and not value.startswith("/")
        and all(part and part not in {".", ".."} for part in value[:-1].split("/"))
        and not any(c in value for c in ("\\", "%", "?", "#", "\x00"))
        and not any(ord(c) < 32 for c in value)
    )


@dataclass(frozen=True)
class SourceScope:
    source_namespace: str
    source_project_id: str
    revision: str
    object_prefix: str

    def __post_init__(self):
        if not all(valid_identifier(v) for v in (self.source_namespace, self.revision)):
            raise ValueError("invalid source scope")
        if not valid_source_id(self.source_project_id):
            raise ValueError("invalid source project id")
        if self.object_prefix != "" and not canonical_prefix(self.object_prefix):
            raise ValueError("invalid object prefix")


def valid_source_id(value):
    return (
        isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,19}", value) is not None
    )


def valid_identifier(value):
    return (
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9_-]{1,96}", value) is not None
    )


@dataclass(frozen=True)
class ReadStatement:
    name: str
    backend: Literal["mysql", "questdb"]
    sql: str
    params: tuple[Any, ...]
    max_rows: int


class SqlReader(Protocol):
    def select(self, statement: ReadStatement) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class EvidenceObject:
    stream: BinaryIO
    size: int | None
    filename: str


class ObjectReader(Protocol):
    def open(self, key: str, *, max_bytes: int) -> EvidenceObject: ...


@dataclass(frozen=True)
class SourceResult:
    source_kind: str
    items: list[dict[str, Any]]
    captured_at: datetime
    filters: dict[str, Any]
    complete: bool
    truncation_reason: str | None
    next_before_id: int | None
    redacted_fields: tuple[str, ...] = ()


class ProductionSource(Protocol):
    @property
    def capabilities(self) -> frozenset[str]: ...
    def projects(self, *, before_id: str | None = None) -> dict: ...
    def project(self, source_project_id: str) -> dict: ...
    def query(self, binding: SourceScope, query: ProductionQuery) -> SourceResult: ...
    def evidence(
        self,
        binding: SourceScope,
        source_log_id: int,
        *,
        before_open: Callable[[], None] | None = None,
    ) -> EvidenceObject: ...


@dataclass(frozen=True)
class ProductionToolsConfig:
    source: ProductionSource
    source_namespace: str
    revision: str
    object_prefixes: Mapping[str, str]
    snapshot_path: str

    def __post_init__(self):
        from types import MappingProxyType

        if not all(valid_identifier(v) for v in (self.source_namespace, self.revision)):
            raise ValueError("invalid source configuration")
        copied = dict(self.object_prefixes)
        if any(
            not valid_source_id(key) or not canonical_prefix(value)
            for key, value in copied.items()
        ):
            raise ValueError("invalid object prefixes")
        if not isinstance(self.snapshot_path, str) or not self.snapshot_path.strip():
            raise ValueError("snapshot path required")
        object.__setattr__(self, "object_prefixes", MappingProxyType(copied))
