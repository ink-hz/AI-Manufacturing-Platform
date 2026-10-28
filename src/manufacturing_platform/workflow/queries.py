"""Typed domain readers shared by object pages, details and dashboard counts."""

from collections.abc import Callable
from dataclasses import dataclass
from sqlite3 import Connection
from typing import Annotated, Generic, TypeVar, Union
from uuid import UUID

from pydantic import Field, TypeAdapter

from .commands import literal_tag
from .contracts import DomainValue, ObjectDetail, ObjectKind, ObjectSummary

V = TypeVar("V", bound=DomainValue)


@dataclass(frozen=True)
class ObjectRegistration(Generic[V]):
    model: type[V]
    summaries: Callable[[Connection, UUID], list[ObjectSummary]]
    detail: Callable[[Connection, UUID, UUID], ObjectDetail[V] | None]


class ObjectRegistry:
    def __init__(self):
        self._entries: dict[ObjectKind, ObjectRegistration] = {}
        self._value_adapter: TypeAdapter | None = None

    def register(
        self,
        kind: ObjectKind,
        model: type[V],
        *,
        summaries: Callable[[Connection, UUID], list[ObjectSummary]],
        detail: Callable[[Connection, UUID, UUID], ObjectDetail[V] | None],
    ):
        kind = ObjectKind(kind)
        if (
            not issubclass(model, DomainValue)
            or literal_tag(model, "kind", set(ObjectKind)) != kind
        ):
            raise ValueError("domain value must declare the registered kind")
        if kind in self._entries:
            raise ValueError("duplicate object kind")
        self._entries[kind] = ObjectRegistration(model, summaries, detail)
        models = tuple(entry.model for entry in self._entries.values())
        self._value_adapter = TypeAdapter(
            Annotated[Union[models], Field(discriminator="kind")]  # noqa: UP007 - runtime union
        )

    @property
    def kinds(self) -> tuple[ObjectKind, ...]:
        return tuple(self._entries)

    def summaries(
        self, tx: Connection, project_id: UUID, kind: ObjectKind
    ) -> list[ObjectSummary]:
        entry = self._entries.get(kind)
        if entry is None:
            return []
        values = [
            ObjectSummary.model_validate(v) for v in entry.summaries(tx, project_id)
        ]
        if any(v.project_id != project_id or v.kind != kind for v in values):
            raise ValueError("object reader scope mismatch")
        return values

    def detail(
        self, tx: Connection, project_id: UUID, kind: ObjectKind, object_id: UUID
    ) -> ObjectDetail | None:
        entry = self._entries.get(kind)
        if entry is None:
            return None
        result = entry.detail(tx, project_id, object_id)
        if result is None:
            return None
        # Revalidate the exact registered DTO; generic serialization must retain domain fields.
        result = ObjectDetail[entry.model].model_validate(
            result.model_dump(mode="json")
        )
        self._value_adapter.validate_python(result.value.model_dump(mode="json"))
        if (
            result.summary.project_id != project_id
            or result.summary.id != object_id
            or result.summary.kind != kind
        ):
            raise ValueError("object detail scope mismatch")
        return result


OBJECT_REGISTRY = ObjectRegistry()
