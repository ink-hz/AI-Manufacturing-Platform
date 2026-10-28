import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from .authorization import require_project
from .commands import COMMAND_REGISTRY, CommandContext, WorkflowCommand
from .contracts import (
    Actor,
    CommandResult,
    Dashboard,
    Dataset,
    DomainError,
    GrantChange,
    MutationResult,
    ObjectDetail,
    ObjectKind,
    ObjectPage,
    ProjectCreate,
    ProjectDetail,
    ScopeGrantView,
)
from .queries import OBJECT_REGISTRY


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def project(row):
    return ProjectDetail(
        id=row["id"],
        version=row["version"],
        name=row["name"],
        line_id=row["line_id"],
        product=row["product"],
        customer_id=row["customer_id"],
        mode=row["mode"],
        unit={"code": row["unit_code"], "scale": row["unit_scale"]},
        quantity=str(Decimal(row["q_atoms"]).scaleb(-row["unit_scale"])),
        contract=json.loads(row["contract_json"]),
        legacy_project_id=row["legacy_project_id"],
    )


class WorkflowService:
    def __init__(
        self, store, resolve_subject, *, command_registry=None, object_registry=None
    ):
        self.store, self.resolve_subject = store, resolve_subject
        self.command_registry = (
            COMMAND_REGISTRY if command_registry is None else command_registry
        )
        self.object_registry = (
            OBJECT_REGISTRY if object_registry is None else object_registry
        )

    def _replay(self, tx, actor, operation, payload):
        row = tx.execute(
            "SELECT payload_hash,result_json FROM operations WHERE dataset=? AND actor_id=? AND operation_id=?",
            (self.store.dataset["id"], str(actor.user_id), str(operation)),
        ).fetchone()
        if row:
            if row["payload_hash"] != digest(payload):
                raise DomainError(
                    "IDEMPOTENCY_CONFLICT", 409, "Operation ID already used"
                )
            return json.loads(row["result_json"])
        return None

    def _save(
        self, tx, actor, operation, payload, result, project_id, action, object_id
    ):
        tx.execute(
            "INSERT INTO operations VALUES (?,?,?,?,?)",
            (
                self.store.dataset["id"],
                str(actor.user_id),
                str(operation),
                digest(payload),
                canonical(result),
            ),
        )
        now = datetime.now(UTC).isoformat()
        tx.execute(
            "INSERT INTO audit_events(project_id,actor_id,action,object_id,occurred_at,recorded_at,typed_payload) VALUES (?,?,?,?,?,?,?)",
            (
                str(project_id),
                str(actor.user_id),
                action,
                str(object_id),
                now,
                now,
                canonical(payload),
            ),
        )

    def create_project(self, actor: Actor, value: ProjectCreate) -> ProjectDetail:
        if actor.read_only or not actor.configuration_admin:
            raise DomainError("FORBIDDEN", 403, "Permission denied")
        if value.legacy_project_id is not None and not actor.configuration_admin:
            raise DomainError("FORBIDDEN", 403, "Permission denied")
        payload = {"action": "project.create", **value.model_dump(mode="json")}
        with self.store.transaction(write=True) as tx:
            replay = self._replay(tx, actor, value.operation_id, payload)
            if replay is not None:
                require_project(tx, actor, replay["id"])
                return ProjectDetail.model_validate(replay)
            pid = str(uuid4())
            tx.execute(
                "INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    pid,
                    1,
                    value.name,
                    value.line_id,
                    value.product,
                    value.customer_id,
                    value.mode,
                    value.unit.code,
                    value.unit.scale,
                    int(value.quantity * (10**value.unit.scale)),
                    canonical(value.contract.model_dump(mode="json")),
                    str(value.legacy_project_id) if value.legacy_project_id else None,
                ),
            )
            tx.execute(
                "INSERT INTO project_grants VALUES (?,?,?,?,?,?)",
                (
                    pid,
                    str(actor.user_id),
                    canonical(["project_owner"]),
                    "[]",
                    1,
                    "project creator",
                ),
            )
            result = project(
                tx.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
            ).model_dump(mode="json")
            self._save(
                tx,
                actor,
                value.operation_id,
                payload,
                result,
                pid,
                "project.create",
                pid,
            )
            return ProjectDetail.model_validate(result)

    def change_grant(
        self, actor: Actor, project_id: UUID, user_id: UUID, value: GrantChange
    ):
        if actor.read_only or not actor.configuration_admin:
            raise DomainError("FORBIDDEN", 403, "Permission denied")
        if value.scope.project_id != project_id:
            raise DomainError(
                "SCOPE_MISMATCH", 422, "Grant scope must match project path"
            )
        if not self.resolve_subject(user_id):
            raise DomainError("INVALID_SUBJECT", 422, "Unknown or inactive subject")
        payload = {
            "action": "grant.change",
            "project_id": str(project_id),
            "user_id": str(user_id),
            **value.model_dump(mode="json"),
        }
        with self.store.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT * FROM projects WHERE id=?", (str(project_id),)
            ).fetchone()
            if not row:
                raise DomainError("NOT_FOUND", 404, "Workflow resource not found")
            replay = self._replay(tx, actor, value.operation_id, payload)
            if replay is not None:
                return replay
            if row["version"] != value.expected_version:
                raise DomainError(
                    "VERSION_CONFLICT",
                    409,
                    "Project version changed",
                    {"current_version": row["version"]},
                )
            tx.execute(
                "INSERT INTO project_grants VALUES (?,?,?,?,?,?) ON CONFLICT(project_id,user_id) DO UPDATE SET roles_json=excluded.roles_json, qualifications_json=excluded.qualifications_json,active=excluded.active,evidence=excluded.evidence",
                (
                    str(project_id),
                    str(user_id),
                    canonical(value.roles),
                    canonical(value.qualifications),
                    int(value.active),
                    value.evidence,
                ),
            )
            tx.execute(
                "UPDATE projects SET version=version+1 WHERE id=?", (str(project_id),)
            )
            result = {
                "scope": value.scope.model_dump(mode="json"),
                "user_id": str(user_id),
                "roles": value.roles,
                "qualifications": value.qualifications,
                "active": value.active,
                "project_version": row["version"] + 1,
            }
            self._save(
                tx,
                actor,
                value.operation_id,
                payload,
                result,
                project_id,
                "grant.change",
                user_id,
            )
            return result

    def project_ids(self, actor):
        with self.store.transaction() as tx:
            return [
                r[0]
                for r in tx.execute(
                    "SELECT project_id FROM project_grants WHERE user_id=? AND active=1 AND roles_json!='[]' ORDER BY project_id",
                    (str(actor.user_id),),
                )
            ]

    def detail(self, actor: Actor, project_id: UUID) -> ProjectDetail:
        with self.store.transaction() as tx:
            return project(require_project(tx, actor, project_id))

    def members(self, actor, project_id):
        with self.store.transaction() as tx:
            require_project(tx, actor, project_id)
            return [
                ScopeGrantView.model_validate(
                    {
                        "scope": {"kind": "project", "project_id": str(project_id)},
                        "user_id": r["user_id"],
                        "roles": json.loads(r["roles_json"]),
                        "qualifications": json.loads(r["qualifications_json"]),
                        "active": bool(r["active"]),
                    }
                )
                for r in tx.execute(
                    "SELECT * FROM project_grants WHERE project_id=?",
                    (str(project_id),),
                )
            ]

    def objects(
        self,
        actor: Actor,
        project_id: UUID,
        kind: ObjectKind,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> ObjectPage:
        if not 1 <= limit <= 200 or offset < 0:
            raise DomainError("INVALID_PAGINATION", 422, "Invalid pagination")
        project_id = UUID(str(project_id))
        with self.store.transaction() as tx:
            require_project(tx, actor, project_id)
            values = self.object_registry.summaries(tx, project_id, kind)
            return ObjectPage(
                items=values[offset : offset + limit],
                total=len(values),
                limit=limit,
                offset=offset,
            )

    def object_detail(
        self, actor: Actor, project_id: UUID, kind: ObjectKind, object_id: UUID
    ) -> ObjectDetail:
        project_id, object_id = UUID(str(project_id)), UUID(str(object_id))
        with self.store.transaction() as tx:
            require_project(tx, actor, project_id)
            result = self.object_registry.detail(tx, project_id, kind, object_id)
            if result is None:
                raise DomainError("NOT_FOUND", 404, "Workflow resource not found")
            return result

    def dashboard(self, actor: Actor, project_id: UUID | None = None) -> Dashboard:
        with self.store.transaction() as tx:
            if project_id is not None:
                require_project(tx, actor, project_id)
                ids = [UUID(str(project_id))]
            else:
                ids = [
                    UUID(r[0])
                    for r in tx.execute(
                        "SELECT project_id FROM project_grants WHERE user_id=? AND active=1 AND roles_json!='[]' ORDER BY project_id",
                        (str(actor.user_id),),
                    )
                ]
            counts = {kind: 0 for kind in self.object_registry.kinds}
            cards = []
            for pid in ids:
                for kind in self.object_registry.kinds:
                    values = self.object_registry.summaries(tx, pid, kind)
                    counts[kind] += len(values)
                    cards.extend(values[: max(0, 100 - len(cards))])
            return Dashboard(
                cards=cards, project_ids=ids, project_count=len(ids), counts=counts
            )

    def execute(
        self, actor: Actor, project_id: UUID, command: WorkflowCommand
    ) -> CommandResult:
        if actor.read_only:
            raise DomainError("FORBIDDEN", 403, "Workflow is read-only")
        project_id = UUID(str(project_id))
        # Visibility precedes schema errors; permissions are checked again in the write transaction.
        self.detail(actor, project_id)
        command = self.command_registry.parse(command)
        entry = self.command_registry.registration(command.action)
        payload = {"project_id": str(project_id), **command.model_dump(mode="json")}
        with self.store.transaction(write=True) as tx:
            row = require_project(tx, actor, project_id)
            grant = tx.execute(
                "SELECT roles_json, qualifications_json FROM project_grants WHERE project_id=? AND user_id=? AND active=1",
                (str(project_id), str(actor.user_id)),
            ).fetchone()
            if not entry.roles.intersection(
                json.loads(grant["roles_json"])
            ) or not entry.qualifications.issubset(
                json.loads(grant["qualifications_json"])
            ):
                raise DomainError("FORBIDDEN", 403, "Action permission denied")
            replay = self._replay(tx, actor, command.operation_id, payload)
            if replay is not None:
                return CommandResult.model_validate({**replay, "replayed": True})
            if row["version"] != command.expected_version:
                raise DomainError(
                    "VERSION_CONFLICT",
                    409,
                    "Project version changed",
                    {"current_version": row["version"]},
                )
            context = CommandContext(
                actor,
                project_id,
                row["version"],
                datetime.now(UTC),
                Dataset.model_validate(self.store.dataset),
            )
            mutation = entry.handler(tx, context, command)
            if not isinstance(mutation, MutationResult):
                raise TypeError("domain handler must return MutationResult")
            result = CommandResult(
                operation_id=command.operation_id,
                project_id=project_id,
                project_version=row["version"] + 1,
                object_type=mutation.model_dump(mode="json")["object_type"],
                object_id=mutation.object_id,
                exchange_id=mutation.exchange_id,
            )
            tx.execute(
                "UPDATE projects SET version=version+1 WHERE id=?", (str(project_id),)
            )
            self._save(
                tx,
                actor,
                command.operation_id,
                payload,
                result.model_dump(mode="json"),
                project_id,
                command.action,
                mutation.object_id,
            )
            return result
