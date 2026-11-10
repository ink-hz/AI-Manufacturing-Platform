"""Live workflow authorization around optional external observation reads."""

from collections.abc import Callable
from datetime import datetime
from typing import get_args
from uuid import UUID

from ..workflow.authorization import require_project
from ..workflow.contracts import Actor, DomainError
from ..workflow.store import WorkflowStore
from .contracts import (
    EvidenceObject,
    ProductionQuery,
    ProductionToolsConfig,
    SourceKind,
)
from .source import error
from .store import SnapshotStore, validate_snapshot_path


class ProductionToolsService:
    def __init__(
        self,
        workflow_store: WorkflowStore,
        config: ProductionToolsConfig | None,
        *,
        clock: Callable[[], datetime],
    ):
        self.workflow_store = workflow_store
        self.config = config
        self.snapshots = None
        if config is not None:
            validate_snapshot_path(
                config.snapshot_path,
                (workflow_store.database_path, workflow_store.authority_database_path),
            )
            if any(
                binding.dataset_id != workflow_store.dataset["id"]
                for binding in config.bindings.values()
            ):
                raise ValueError("production binding dataset mismatch")
            self.snapshots = SnapshotStore(
                config.snapshot_path, workflow_store.dataset, clock=clock
            )

    def _authorize(self, actor, project_id):
        with self.workflow_store.transaction() as tx:
            require_project(tx, actor, project_id)

    def _binding_for(self, project_id):
        binding = self.config.bindings.get(project_id) if self.config else None
        if binding is None:
            raise DomainError(
                "PRODUCTION_TOOLS_UNCONFIGURED",
                503,
                "Production tools are not configured for this project",
            )
        return binding

    def _require_current_binding(self, project_id, binding):
        if self.config is None or self.config.bindings.get(project_id) != binding:
            raise DomainError("NOT_FOUND", 404, "Workflow resource not found")

    def _reauthorize(self, actor, project_id, binding):
        self._authorize(actor, project_id)
        self._require_current_binding(project_id, binding)

    def _authorized_binding(self, actor, project_id):
        self._authorize(actor, project_id)
        return self._binding_for(project_id)

    def status(self, actor: Actor, project_id: UUID) -> dict:
        self._authorize(actor, project_id)
        binding = self.config.bindings.get(project_id) if self.config else None
        configured = binding is not None
        supported = self.config.source.capabilities if configured else frozenset()
        capabilities = {}
        for kind in (*get_args(SourceKind), "evidence_content"):
            available = kind in supported and (
                kind != "evidence_content" or bool(binding.object_prefix)
            )
            capabilities[kind] = {
                "available": available,
                "reason": None
                if available
                else "SOURCE_UNAVAILABLE"
                if configured
                else "PRODUCTION_TOOLS_UNCONFIGURED",
            }
        return {
            "project_id": str(project_id),
            "configured": configured,
            "capabilities": capabilities,
        }

    def query(self, actor: Actor, project_id: UUID, query: ProductionQuery) -> dict:
        binding = self._authorized_binding(actor, project_id)
        if query.kind not in self.config.source.capabilities:
            raise error()
        try:
            result = self.config.source.query(binding, query)
            self._reauthorize(actor, project_id, binding)
            snapshot_id = self.snapshots.put(binding, result)
            return self.snapshot(actor, project_id, snapshot_id)
        except DomainError:
            raise
        except Exception:  # noqa: BLE001 - Sanitize SDK/storage errors at the connector boundary.
            raise error() from None

    def snapshot(
        self, actor: Actor, project_id: UUID, snapshot_id: UUID, *, offset=0, limit=50
    ) -> dict:
        self._authorize(actor, project_id)
        if self.config is None or project_id not in self.config.bindings:
            raise DomainError("NOT_FOUND", 404, "Workflow resource not found")
        binding = self._binding_for(project_id)
        try:
            page = self.snapshots.get(
                project_id, snapshot_id, binding, offset=offset, limit=limit
            )
            self._reauthorize(actor, project_id, binding)
            return page
        except DomainError:
            raise
        except Exception:  # noqa: BLE001 - Sanitize SDK/storage errors at the connector boundary.
            raise error() from None

    def evidence(
        self, actor: Actor, project_id: UUID, source_log_id: int
    ) -> EvidenceObject:
        binding = self._authorized_binding(actor, project_id)
        if (
            "evidence_content" not in self.config.source.capabilities
            or not binding.object_prefix
        ):
            raise error()
        opened = None
        try:
            opened = self.config.source.evidence(
                binding,
                source_log_id,
                before_open=lambda: self._reauthorize(actor, project_id, binding),
            )
            self._reauthorize(actor, project_id, binding)
            return opened
        except Exception as exc:
            if opened is not None:
                try:
                    opened.stream.close()
                except Exception:  # noqa: BLE001, S110 - SDK cleanup must not expose private errors.
                    pass
            if isinstance(exc, DomainError):
                raise
            raise error() from None
