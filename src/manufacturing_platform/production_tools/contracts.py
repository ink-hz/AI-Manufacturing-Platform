"""Public contracts for bounded, project-scoped external observations."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, BinaryIO, Literal, Protocol
from uuid import UUID

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
    parent_id: int | None = Field(default=None, ge=1, strict=True)
    before_id: int | None = Field(default=None, ge=1, strict=True)

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
class SourceBinding:
    dataset_id: str
    project_id: UUID
    source_namespace: str
    source_project_id: str
    revision: str
    object_prefix: str

    def __post_init__(self):
        if not all(
            isinstance(v, str) and v.strip()
            for v in (self.dataset_id, self.source_namespace, self.revision)
        ):
            raise ValueError("invalid source binding")
        if (
            not isinstance(self.project_id, UUID)
            or not isinstance(self.source_project_id, str)
            or not re.fullmatch(r"[1-9][0-9]{0,19}", self.source_project_id)
        ):
            raise ValueError("invalid source binding")
        if self.object_prefix != "" and not canonical_prefix(self.object_prefix):
            raise ValueError("invalid object prefix")


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
    def query(self, binding: SourceBinding, query: ProductionQuery) -> SourceResult: ...
    def evidence(
        self, binding: SourceBinding, source_log_id: int
    ) -> EvidenceObject: ...


@dataclass(frozen=True)
class ProductionToolsConfig:
    source: ProductionSource
    bindings: Mapping[UUID, SourceBinding]
    snapshot_path: str

    def __post_init__(self):
        from types import MappingProxyType

        copied = dict(self.bindings)
        if any(key != value.project_id for key, value in copied.items()):
            raise ValueError("binding key mismatch")
        if len({value.dataset_id for value in copied.values()}) > 1:
            raise ValueError("binding dataset mismatch")
        if not isinstance(self.snapshot_path, str) or not self.snapshot_path.strip():
            raise ValueError("snapshot path required")
        object.__setattr__(self, "bindings", MappingProxyType(copied))
