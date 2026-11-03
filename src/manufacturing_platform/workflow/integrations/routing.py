"""Server-only profile initialization; never reinterpret persisted intent routing."""

from collections.abc import Callable
from sqlite3 import Connection
from typing import Protocol
from uuid import UUID

from ..adapters.base import AuthorityAdapter
from ..commands import CommandContext
from ..contracts import Actor, DomainError
from .contracts import IntegrationFact, ProjectionResult, SystemAdapter, SystemOperation
from .core_models import ProfileId, SourceKey, SystemId
from .store import SystemStore


class SourceAdapter(SystemAdapter, Protocol):
    def fact(self, project_id: UUID, key: SourceKey) -> IntegrationFact: ...


AdapterFactory = Callable[[SystemStore], SourceAdapter]
Projector = Callable[[Connection, CommandContext, IntegrationFact], ProjectionResult]
FamilyAuthorizer = Callable[
    [Connection, Actor, UUID, SystemOperation | IntegrationFact], None
]


_ROUTES = {
    "reservation.request": "wms",
    "stock.proof": "wms",
    "stock_basis.reconcile": "wms",
    "shipment.request": "wms",
    "production.start": "mes",
    "production.interrupt": "mes",
    "production.resume": "mes",
    "eco.switch": "mes",
    "freeze.request": "mes",
}


def profile_for(tx, project_id: UUID) -> ProfileId:
    row = tx.execute(
        "SELECT profile FROM project_integration_profiles WHERE project_id=?",
        (str(project_id),),
    ).fetchone()
    return row[0] if row else "legacy-erp-v1"


def assign_profile(tx, project_id: UUID, profile: ProfileId) -> None:
    if profile not in {"legacy-erp-v1", "oem-network-v1"}:
        raise ValueError("unknown integration profile")
    metadata = tx.execute("SELECT mode FROM dataset_metadata").fetchone()
    if not metadata or metadata[0] not in {"demo", "test"}:
        raise DomainError(
            "MOCK_UNAVAILABLE",
            403,
            "profile initialization is demo/test maintenance only",
        )
    pid = str(project_id)
    if not tx.execute("SELECT 1 FROM projects WHERE id=?", (pid,)).fetchone():
        raise DomainError("NOT_FOUND", 404, "project not found")
    previous = tx.execute(
        "SELECT profile FROM project_integration_profiles WHERE project_id=?", (pid,)
    ).fetchone()
    if previous:
        if previous[0] == profile:
            return
        raise DomainError(
            "PROFILE_IMMUTABLE", 409, "project integration profile is immutable"
        )
    used = tx.execute(
        "SELECT 1 FROM audit_events WHERE project_id=? AND action!='project.create' LIMIT 1",
        (pid,),
    ).fetchone()
    used = (
        used
        or tx.execute(
            "SELECT 1 FROM exchanges WHERE project_id=? LIMIT 1", (pid,)
        ).fetchone()
    )
    used = (
        used
        or tx.execute(
            "SELECT 1 FROM integration_intents WHERE project_id=? LIMIT 1", (pid,)
        ).fetchone()
    )
    if used:
        raise DomainError("PROFILE_IMMUTABLE", 409, "project already has domain intent")
    tx.execute(
        "INSERT INTO project_integration_profiles(project_id,profile) VALUES (?,?)",
        (pid, profile),
    )


def route(profile: ProfileId, action: str) -> str:
    if profile == "legacy-erp-v1":
        return "erp"
    if profile != "oem-network-v1" or action not in _ROUTES:
        raise ValueError("unsupported profile or routed action")
    return _ROUTES[action]


class SystemRegistry:
    """Server composition only; construction and capability reads never open sources."""

    def __init__(self, workflow_store):
        from pathlib import Path

        self.workflow_store = workflow_store
        self.root = Path(workflow_store.database_path).parent / "mock-systems"
        self._bindings = {}
        self._adapters = {}
        self._legacy = None
        self._exchange_factories = {}
        self._exchange_adapters = {}

    def register(
        self,
        system: SystemId,
        *,
        factory: AdapterFactory,
        projector: Projector,
        authorize: FamilyAuthorizer,
    ):
        """A family must supply a typed adapter, transaction projector and live gate.

        No factories or paths are deserialized from commands. Registration is fixed
        Python composition. Until family modules register, operations fail closed.
        """
        from .catalog import SYSTEM_IDS

        if system not in SYSTEM_IDS or system in self._bindings:
            raise ValueError("invalid or duplicate source registration")
        if not all(callable(f) for f in (factory, projector, authorize)):
            raise TypeError("all family boundaries are required")
        self._bindings[system] = (factory, projector, authorize)

    def available(self, system):
        return (
            self.workflow_store.dataset["mode"] in {"demo", "test"}
            and system in self._bindings
        )

    def require_available(self, system):
        if not self.available(system):
            raise DomainError(
                "SOURCE_UNAVAILABLE", 503, "Configured source adapter is unavailable"
            )

    def adapter(self, system):
        self.require_available(system)
        if system not in self._adapters:
            from .store import SystemStore

            store = SystemStore(
                self.root,
                self.workflow_store.dataset["id"],
                system,
                clock=self.workflow_store.business_clock,
            )
            self._adapters[system] = self._bindings[system][0](store)
        return self._adapters[system]

    def source_store(self, system):
        from .store import SystemStore

        self.require_available(system)
        return SystemStore(
            self.root,
            self.workflow_store.dataset["id"],
            system,
            clock=self.workflow_store.business_clock,
        )

    def observe_fact(self, project_id, key):
        from .contracts import IntegrationFact
        from .store import canonical, canonical_hash, conflict

        observation = self.adapter(key.system).fact(project_id, key)
        observation = IntegrationFact.model_validate_json(canonical(observation))
        if observation.project_id != project_id or observation.source_key != key:
            raise DomainError("NOT_FOUND", 404, "Source fact not found")
        stored = self.source_store(key.system).get_fact(project_id, key)
        if canonical_hash(stored) != canonical_hash(observation):
            conflict("Source observation differs from immutable original")
        return observation

    def observe_page(self, project_id, system, object_type, cursor, limit):
        from .contracts import FactPage
        from .store import canonical, canonical_hash, conflict

        observation = self.adapter(system).facts(project_id, object_type, cursor, limit)
        observation = FactPage.model_validate_json(canonical(observation))
        stored = self.source_store(system).list_facts(
            project_id, object_type, cursor, limit
        )
        if canonical_hash(stored) != canonical_hash(observation):
            conflict("Source page differs from immutable originals")
        return observation

    def validate_receipt(self, operation, receipt):
        from .store import canonical_hash, conflict

        stored = self.source_store(operation.system).query(
            operation.project_id, operation.operation_id
        )
        if stored is None or canonical_hash(stored) != canonical_hash(receipt):
            conflict("Receipt differs from durable source operation")

    def existing_stores(self):
        from .catalog import SYSTEM_IDS

        if self.workflow_store.dataset["mode"] not in {"demo", "test"}:
            return []
        return [
            s
            for system in SYSTEM_IDS
            if self.available(system) and (s := self.source_store(system)).path.exists()
        ]

    def authorize(self, tx, actor, project_id, value):
        system = value.system if hasattr(value, "system") else value.source.system
        self.require_available(system)
        self._bindings[system][2](tx, actor, project_id, value)

    def project(self, tx, context, fact):
        self.require_available(fact.source.system)
        return self._bindings[fact.source.system][1](tx, context, fact)

    def legacy_adapter(self):
        if self.workflow_store.dataset["mode"] not in {"demo", "test"}:
            return None
        if self._legacy is None:
            from ..adapters.mock import MockAuthorityAdapter

            self._legacy = MockAuthorityAdapter(
                self.workflow_store.authority_database_path,
                self.workflow_store.dataset["id"],
                business_clock=self.workflow_store.business_clock,
            )
        return self._legacy

    def register_exchange_adapter(
        self, system: SystemId, factory: Callable[["SystemRegistry"], AuthorityAdapter]
    ):
        from .catalog import SYSTEM_IDS

        if (
            system not in SYSTEM_IDS
            or system in self._exchange_factories
            or not callable(factory)
        ):
            raise ValueError("invalid or duplicate authority facade registration")
        self._exchange_factories[system] = factory

    def exchange_adapter(self, system):
        if system == "erp":
            return self.legacy_adapter()
        self.require_available(system)
        if system not in self._exchange_factories:
            raise DomainError(
                "SOURCE_UNAVAILABLE", 503, "Source exchange facade is unavailable"
            )
        if system not in self._exchange_adapters:
            self._exchange_adapters[system] = self._exchange_factories[system](self)
        return self._exchange_adapters[system]

    route = staticmethod(route)
