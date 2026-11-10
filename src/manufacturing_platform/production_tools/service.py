"""Current-request administrator authorization for independent source reads."""

from collections.abc import Callable
from datetime import datetime
from typing import get_args
from uuid import UUID

from ..workflow.contracts import Actor, DomainError
from .contracts import (
    EvidenceObject,
    ProductionQuery,
    ProductionToolsConfig,
    SourceKind,
    SourceScope,
    valid_source_id,
)
from .source import error
from .store import SnapshotStore, validate_snapshot_path


class ProductionToolsService:
    def __init__(
        self, config: ProductionToolsConfig | None, *, clock: Callable[[], datetime]
    ):
        if config:
            independent = config.investigation_path or config.snapshot_path + ".investigations.sqlite3"
            validate_snapshot_path(config.snapshot_path, (*config.protected_paths, independent))
        self.config = config
        self.snapshots = (
            SnapshotStore(config.snapshot_path, clock=clock) if config else None
        )

    def _authorize(self, actor):
        if not actor.configuration_admin:
            raise DomainError(
                "FORBIDDEN", 403, "Production tools require administrator access"
            )

    def _scope_for(self, source_project_id):
        if not valid_source_id(source_project_id):
            raise error("SOURCE_INVALID_QUERY", 422)
        if self.config is None:
            raise DomainError(
                "PRODUCTION_TOOLS_UNCONFIGURED",
                503,
                "Production tools are not configured",
            )
        return SourceScope(
            self.config.source_namespace,
            source_project_id,
            self.config.revision,
            self.config.object_prefixes.get(source_project_id, ""),
        )

    def _reauthorize(self, actor, source_project_id, scope):
        self._authorize(actor)
        if self.config is None or self._scope_for(source_project_id) != scope:
            raise DomainError("NOT_FOUND", 404, "Production snapshot not found")

    def _authorized_scope(self, actor, source_project_id):
        self._authorize(actor)
        return self._scope_for(source_project_id)

    def projects(self, actor: Actor, *, before_id=None):
        self._authorize(actor)
        if before_id is not None and not valid_source_id(before_id):
            raise error("SOURCE_INVALID_QUERY", 422)
        if self.config is None:
            raise DomainError(
                "PRODUCTION_TOOLS_UNCONFIGURED",
                503,
                "Production tools are not configured",
            )
        try:
            return self.config.source.projects(before_id=before_id)
        except DomainError:
            raise
        except Exception:  # noqa: BLE001 - Sanitize source errors.
            raise error() from None

    def status(self, actor: Actor, source_project_id=None) -> dict:
        self._authorize(actor)
        if source_project_id is not None and not valid_source_id(source_project_id):
            raise error("SOURCE_INVALID_QUERY", 422)
        configured = self.config is not None
        supported = self.config.source.capabilities if configured else frozenset()
        prefix = (
            self.config.object_prefixes.get(source_project_id, "") if configured else ""
        )
        capabilities = {}
        for kind in (*get_args(SourceKind), "evidence_content"):
            available = kind in supported and (
                kind != "evidence_content" or source_project_id is None or bool(prefix)
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
            "source_namespace": self.config.source_namespace if configured else None,
            "source_project_id": source_project_id,
            "configured": configured,
            "capabilities": capabilities,
        }

    def query(
        self, actor: Actor, source_project_id: str, query: ProductionQuery
    ) -> dict:
        scope = self._authorized_scope(actor, source_project_id)
        if query.kind not in self.config.source.capabilities:
            raise error()
        try:
            self.config.source.project(source_project_id)
            result = self.config.source.query(scope, query)
            self._reauthorize(actor, source_project_id, scope)
            snapshot_id = self.snapshots.put(scope, result)
            return self.snapshot(actor, source_project_id, snapshot_id)
        except DomainError:
            raise
        except Exception:  # noqa: BLE001 - Sanitize source/storage errors.
            raise error() from None

    def snapshot(
        self,
        actor: Actor,
        source_project_id: str,
        snapshot_id: UUID,
        *,
        offset=0,
        limit=50,
    ) -> dict:
        self._authorize(actor)
        if self.config is None:
            raise DomainError("NOT_FOUND", 404, "Production snapshot not found")
        scope = self._scope_for(source_project_id)
        try:
            page = self.snapshots.get(
                source_project_id, snapshot_id, scope, offset=offset, limit=limit
            )
            self._reauthorize(actor, source_project_id, scope)
            return page
        except DomainError:
            raise
        except Exception:  # noqa: BLE001 - Sanitize source/storage errors.
            raise error() from None

    def evidence(
        self, actor: Actor, source_project_id: str, source_log_id: str
    ) -> EvidenceObject:
        scope = self._authorized_scope(actor, source_project_id)
        if not valid_source_id(source_log_id):
            raise error("SOURCE_INVALID_QUERY", 422)
        if (
            "evidence_content" not in self.config.source.capabilities
            or not scope.object_prefix
        ):
            raise error()
        opened = None
        try:
            self.config.source.project(source_project_id)
            opened = self.config.source.evidence(
                scope,
                int(source_log_id),
                before_open=lambda: self._reauthorize(actor, source_project_id, scope),
            )
            self._reauthorize(actor, source_project_id, scope)
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
