import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from . import (  # noqa: F401 - trusted domain registration
    agreements,
    delivery,
    eco,
    engineering,
    exchanges,
    execution,
    feedback,
    freeze,
    orders,
    ownership,
    progress,
    quality,
    stock_proofs,
    supply,
)
from .authorization import (
    effective_permissions,
    project_ids,
    require_project,
    responsible_member,
)
from .clock import business_time
from .commands import COMMAND_REGISTRY, CommandContext, WorkflowCommand
from .contracts import (
    ActionCapability,
    ActionVariant,
    Actor,
    ActorTaskPage,
    CommandResult,
    Dashboard,
    Dataset,
    DomainError,
    GrantChange,
    MutationResult,
    ObjectDetail,
    ObjectKind,
    ObjectPage,
    ObjectSummary,
    OwnedTask,
    ProjectCreate,
    ProjectDetail,
    ProjectQualitySummary,
    ScopeGrantView,
)
from .queries import OBJECT_REGISTRY
from .result_versions import authorize_creation_replay, project_creation_result


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def project(row, tx):
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
        stages=progress.hints(tx, row["id"]),
        summary=orders.project_summary(tx, row),
    )


class WorkflowService:
    def __init__(
        self,
        store,
        resolve_subject,
        *,
        command_registry=None,
        object_registry=None,
        test_evidence_reader=None,
        resolve_subject_profiles=None,
    ):
        self.store, self.resolve_subject = store, resolve_subject
        self.resolve_subject_profiles = resolve_subject_profiles
        self.exchange_service = exchanges.ExchangeService(self)
        self.test_evidence_reader = test_evidence_reader or quality
        self.store.bind_test_evidence_reader(self.test_evidence_reader)
        self.command_registry = (
            COMMAND_REGISTRY if command_registry is None else command_registry
        )
        self.object_registry = (
            OBJECT_REGISTRY if object_registry is None else object_registry
        )

    def _replay(self, tx, actor, operation, payload, *, authorize_result=None):
        row = tx.execute(
            "SELECT payload_hash,result_json FROM operations WHERE dataset=? AND actor_id=? AND operation_id=?",
            (self.store.dataset["id"], str(actor.user_id), str(operation)),
        ).fetchone()
        if row:
            if authorize_result is not None:
                result = json.loads(row["result_json"])
                authorize_result(row, result)
            if row["payload_hash"] != digest(payload):
                raise DomainError(
                    "IDEMPOTENCY_CONFLICT", 409, "Operation ID already used"
                )
            return result if authorize_result is not None else json.loads(row["result_json"])
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
            replay = self._replay(
                tx, actor, value.operation_id, payload,
                authorize_result=lambda saved, result: authorize_creation_replay(
                    tx, actor, value.operation_id, saved, result
                ),
            )
            if replay is not None:
                return project_creation_result(tx, actor, payload, replay)
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
                tx.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone(), tx
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
        payload = {
            "action": "grant.change",
            "project_id": str(project_id),
            "user_id": str(user_id),
            **value.model_dump(mode="json"),
        }
        # Authorize the initiating actor before canonical replay. Target liveness
        # applies only to a new active grant, never to an accepted result.
        with self.store.transaction() as tx:
            require_project(tx, actor, project_id)
            replay = self._replay(tx, actor, value.operation_id, payload)
            if replay is not None:
                return replay
            known_grant = tx.execute(
                "SELECT 1 FROM project_grants WHERE project_id=? AND user_id=?",
                (str(project_id), str(user_id)),
            ).fetchone() is not None
        target_valid, target_error = True, None
        # A new inactive configuration still needs a known directory identity;
        # revoking an existing grant does not depend on target liveness.
        if value.active or not known_grant:
            try:
                target_valid = self.resolve_subject(user_id)
            except Exception as exc:  # noqa: BLE001 - host failure retained until authorized canonical replay
                target_error = exc
        with self.store.transaction(write=True) as tx:
            row = require_project(tx, actor, project_id)
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
            if target_error is not None:
                raise DomainError("DIRECTORY_UNAVAILABLE", 503, "Subject directory unavailable") from target_error
            if not target_valid:
                raise DomainError("INVALID_SUBJECT", 422, "Unknown or inactive subject")
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

    @staticmethod
    def _pagination(limit, offset):
        if not 1 <= limit <= 200 or offset < 0:
            raise DomainError("INVALID_PAGINATION", 422, "Invalid pagination")

    @staticmethod
    def _project_ids(tx, actor, project_id=None):
        if project_id is not None:
            require_project(tx, actor, project_id)
            return [UUID(str(project_id))]
        return [UUID(pid) for pid in project_ids(tx, actor)]

    def project_ids(self, actor):
        with self.store.transaction() as tx:
            return [str(pid) for pid in self._project_ids(tx, actor)]

    def _progress(self, tx, actor, project_id):
        value = progress.aggregate(tx, project_id)
        value.blocking_objects = [
            self._actions(tx, actor, item) for item in value.blocking_objects
        ]
        return value

    def detail(
        self, actor: Actor, project_id: UUID, *, include_progress=True
    ) -> ProjectDetail:
        with self.store.transaction() as tx:
            value = project(require_project(tx, actor, project_id), tx)
            permissions = effective_permissions(tx, actor, project_id)
            value.allowed_actions = (
                []
                if actor.read_only
                else self.command_registry.allowed_actions(
                    permissions.roles, permissions.qualifications,
                )
            )
            value.release_kinds = (
                []
                if actor.read_only
                else quality.release_kinds(
                    permissions.roles, permissions.qualifications,
                )
            )
            if not value.release_kinds and "release.decide" in value.allowed_actions:
                value.allowed_actions.remove("release.decide")
            if (
                "delivery.resolve_issue" in value.allowed_actions
                and not delivery.can_resolve_issue(tx, actor, project_id)
            ):
                value.allowed_actions.remove("delivery.resolve_issue")
            if include_progress:
                value.progress = self._progress(tx, actor, project_id)
                value.tasks, value.tasks_truncated = self._tasks(
                    tx, actor, value.id, value.version, value.progress
                )
            value.quality_summary = ProjectQualitySummary.model_validate(
                quality.quality_summary(tx, project_id).model_dump(mode="json")
            )
            return value

    def _actions(self, tx, actor, item, detail=None):
        """Read capabilities use the same live registry and variant authorization."""
        permissions = effective_permissions(tx, actor, item.project_id)
        allowed = (
            set()
            if actor.read_only
            else set(
                self.command_registry.allowed_actions(
                    permissions.roles, permissions.qualifications,
                )
            )
        )
        release_variants = (
            quality.release_kinds(
                permissions.roles, permissions.qualifications,
            )
            if "release.decide" in allowed
            else []
        )
        if not release_variants:
            allowed.discard("release.decide")
        candidates = list(item.next_actions)
        # Context associations are not a permission matrix. Every candidate is
        # intersected with the live command policy below, just like execute().
        related = {
            "unit": ["test.record", "release.decide", "freeze.request"],
            "demand": ["demand.review", "order.register"],
            "order_line": ["order.change", "order.allocate", "shipment.request"],
            "revision": [
                "engineering.handoff",
                "engineering.customer_approval",
                "work_order.register",
            ],
            "work_order": ["readiness.record", "production.start", "unit.register"],
            "requirement": ["supply.commit", "reservation.request"],
            "commitment": ["supply.receive"],
            "receipt": ["supply.inspect"],
            "material_lot": [
                "ownership.movement",
                "ownership.reconcile",
                "freeze.request",
            ],
            "test": ["nonconformance.open"],
            "nonconformance": ["nonconformance.disposition"],
            "rework": ["execution.record", "test.record", "rework.complete"],
            "shipment": [
                "delivery.sign",
                "delivery.accept",
                "delivery.resolve_issue",
                "rma.open",
            ],
            "rma": ["capa.update"],
            "capa": ["capa.update", "capa.close"],
        }
        candidates.extend(related.get(item.kind.value, []))
        if item.kind == ObjectKind.exchange:
            row = tx.execute(
                "SELECT policy_action FROM exchanges WHERE project_id=? AND id=?",
                (str(item.project_id), str(item.id)),
            ).fetchone()
            if not row or row["policy_action"] not in allowed:
                candidates = []
            else:
                candidates.append("exchange.reconcile")
        if "delivery.resolve_issue" in candidates and not delivery.can_resolve_issue(
            tx, actor, item.project_id
        ):
            candidates.remove("delivery.resolve_issue")
        item.next_actions = list(dict.fromkeys(a for a in candidates if a in allowed))
        item.action_capabilities = [
            ActionCapability(action=a) for a in item.next_actions
        ]
        for capability in item.action_capabilities:
            if (
                detail is not None
                and item.kind == ObjectKind.work_order
                and capability.action == "production.start"
            ):
                capability.variants = {
                    mode: ActionVariant(
                        ready=getattr(detail, mode + "_readiness").ready,
                        blocking_reasons=[
                            c.reason
                            for c in getattr(detail, mode + "_readiness").checks
                            if c.required and c.status == "blocked"
                        ],
                    )
                    for mode in ("trial", "bulk")
                }
            if capability.action == "release.decide":
                capability.variants = {
                    kind: ActionVariant()
                    for kind in release_variants
                }
            if (
                detail is not None
                and item.kind == ObjectKind.capa
                and capability.action == "capa.close"
            ):
                capability.variants = {
                    "verification": ActionVariant(
                        ready=not detail.blocking_reasons and detail.state == "open",
                        blocking_reasons=detail.blocking_reasons
                        or (["Already closed"] if detail.state == "closed" else []),
                    )
                }
        return item

    def _tasks(self, tx, actor, project_id, version, project_progress):
        if actor.read_only:
            return [], False
        pid = str(project_id)
        tasks = []
        # Explicit responsibility rows are selected in SQL before materialization.
        for r in tx.execute(
            """SELECT i.title,i.owner_id,i.owner_name,i.shipment_id id,'shipment' kind,'acceptance' category FROM acceptance_issues i
            WHERE i.project_id=? AND i.owner_id=? AND i.required=1 AND NOT EXISTS(SELECT 1 FROM acceptance_resolutions r WHERE r.issue_id=i.id)
            UNION ALL SELECT d.reason,d.owner_id,d.owner_name,d.exchange_id,'exchange','source' FROM exchange_discrepancies d JOIN exchanges e ON e.id=d.exchange_id
            WHERE d.project_id=? AND d.owner_id=? AND d.resolves_seq IS NULL AND e.phase NOT IN ('accepted','posted') AND d.reason<>'Authority rejected request' AND NOT EXISTS(SELECT 1 FROM exchange_discrepancies r WHERE r.resolves_seq=d.seq)
            ORDER BY category,id LIMIT 51""",
            (pid, str(actor.user_id), pid, str(actor.user_id)),
        ):
            target = self._actions(
                tx,
                actor,
                ObjectSummary(
                    id=r["id"],
                    kind=r["kind"],
                    project_id=pid,
                    title=r["title"],
                    state="blocked",
                    version=version,
                    blocking_reasons=[r["title"]],
                ),
            )
            tasks.append(
                OwnedTask(
                    category=r["category"],
                    title=r["title"],
                    target=target,
                    owner_id=r["owner_id"],
                    owner_name=r["owner_name"],
                )
            )
        existing = {(t.target.kind, t.target.id) for t in tasks}
        for item in project_progress.blocking_objects:
            if item.next_actions and (item.kind, item.id) not in existing:
                tasks.append(
                    OwnedTask(
                        category="readiness"
                        if item.kind == ObjectKind.work_order
                        else "business",
                        title=item.blocking_reasons[0],
                        target=item,
                        owner_id=None,
                        owner_name="Current authorized responsibility",
                    )
                )
        return tasks[:50], len(tasks) > 50 or project_progress.blockers_truncated

    def member_profiles(self, actor, project_id, ids):
        if len(ids) > 50:
            raise DomainError("INVALID_SUBJECT", 422, "Too many responsible members")
        with self.store.transaction() as tx:
            require_project(tx, actor, project_id)
            for uid in ids:
                if not responsible_member(tx, actor, project_id, uid):
                    raise DomainError(
                        "INVALID_SUBJECT",
                        422,
                        "Responsible owner must be an active project member",
                    )
        if not self.resolve_subject_profiles:
            return {}
        # Trusted bounded host lookup, outside every workflow transaction.
        profiles = self.resolve_subject_profiles([UUID(str(uid)) for uid in ids])
        if not isinstance(profiles, list) or len(profiles) > len(ids):
            raise DomainError(
                "INVALID_SUBJECT", 422, "Invalid project member profile response"
            )
        result = {}
        for raw in profiles:
            from .delivery_models import MemberProfile

            profile = MemberProfile.model_validate(raw)
            if (
                str(profile.user_id) not in set(map(str, ids))
                or str(profile.user_id) in result
            ):
                raise DomainError(
                    "INVALID_SUBJECT", 422, "Invalid project member profile scope"
                )
            result[str(profile.user_id)] = profile.display_name
        return result

    def members(self, actor, project_id, *, limit=50, offset=0, user_id=None):
        if not 1 <= limit <= 50 or offset < 0:
            raise DomainError("INVALID_PAGINATION", 422, "Invalid pagination")
        with self.store.transaction() as tx:
            require_project(tx, actor, project_id)
            rows = [
                dict(r)
                for r in tx.execute(
                    "SELECT * FROM project_grants WHERE project_id=? "
                    + ("AND user_id=? " if user_id is not None else "")
                    + "ORDER BY user_id LIMIT ? OFFSET ?",
                    (
                        str(project_id),
                        *((str(user_id),) if user_id is not None else ()),
                        limit,
                        0 if user_id is not None else offset,
                    ),
                )
            ]
        ids = [
            r["user_id"] for r in rows if r["active"] and json.loads(r["roles_json"])
        ]
        profiles = self.member_profiles(actor, project_id, ids) if ids else {}
        return [
            ScopeGrantView.model_validate(
                {
                    "scope": {"kind": "project", "project_id": str(project_id)},
                    "user_id": r["user_id"],
                    "roles": json.loads(r["roles_json"]),
                    "qualifications": json.loads(r["qualifications_json"]),
                    "active": bool(r["active"]),
                    "display_name": profiles.get(r["user_id"]),
                }
            )
            for r in rows
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
        self._pagination(limit, offset)
        project_id = UUID(str(project_id))
        with self.store.transaction() as tx:
            require_project(tx, actor, project_id)
            total = self.object_registry.count(tx, project_id, kind)
            values = self.object_registry.summaries(
                tx, project_id, kind, limit=limit, offset=offset
            )
            return ObjectPage(
                items=[self._actions(tx, actor, item) for item in values],
                total=total,
                limit=limit,
                offset=offset,
            )

    def ledger(
        self, actor: Actor, kind: ObjectKind, *, limit: int = 50,
        offset: int = 0, project_id: UUID | None = None,
    ) -> ObjectPage:
        """Stable project-ID groups, preserving each registry reader's SQL order."""
        self._pagination(limit, offset)
        with self.store.transaction() as tx:
            scopes = [
                (pid, self.object_registry.count(tx, pid, kind))
                for pid in self._project_ids(tx, actor, project_id)
            ]
            items, skip = [], offset
            for pid, count in scopes:
                if skip >= count:
                    skip -= count
                    continue
                remaining = limit - len(items)
                if not remaining:
                    break
                items.extend(self.object_registry.summaries(
                    tx, pid, kind, limit=min(remaining, count - skip), offset=skip
                ))
                skip = 0
            return ObjectPage(
                items=[self._actions(tx, actor, item) for item in items],
                total=sum(count for _, count in scopes), limit=limit, offset=offset,
            )

    def tasks(
        self, actor: Actor, *, limit: int = 50, offset: int = 0,
        project_id: UUID | None = None,
    ) -> ActorTaskPage:
        """Page the available task scope; truncation describes underlying bounds."""
        self._pagination(limit, offset)
        with self.store.transaction() as tx:
            ids = self._project_ids(tx, actor, project_id)
            items, total, truncated = [], 0, False
            if not actor.read_only:
                for pid in ids:
                    row = require_project(tx, actor, pid)
                    available, incomplete = self._tasks(
                        tx, actor, pid, row["version"], self._progress(tx, actor, pid)
                    )
                    start = max(0, offset - total)
                    items.extend(available[start:start + limit - len(items)])
                    total += len(available)
                    truncated = truncated or incomplete
            return ActorTaskPage(
                items=items, total=total, limit=limit, offset=offset,
                truncated=truncated,
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
            result.summary = self._actions(tx, actor, result.summary, result.value)
            return result

    def trace(self, actor, project_id, *, sn=None, material_lot_id=None, limit=500):
        from .trace import query

        with self.store.transaction() as tx:
            require_project(tx, actor, project_id)
            return query(
                tx, project_id, sn=sn, material_lot_id=material_lot_id, limit=limit
            )

    def dashboard(self, actor: Actor, project_id: UUID | None = None) -> Dashboard:
        with self.store.transaction() as tx:
            ids = self._project_ids(tx, actor, project_id)
            counts = {kind: 0 for kind in self.object_registry.kinds}
            cards = []
            for pid in ids:
                for kind in self.object_registry.kinds:
                    counts[kind] += self.object_registry.count(tx, pid, kind)
                    remaining = 100 - len(cards)
                    if remaining:
                        cards.extend(
                            self.object_registry.summaries(
                                tx, pid, kind, limit=remaining, offset=0
                            )
                        )
            return Dashboard(
                cards=[self._actions(tx, actor, item) for item in cards],
                project_ids=ids,
                project_count=len(ids),
                counts=counts,
            )

    def execute(
        self, actor: Actor, project_id: UUID, command: WorkflowCommand
    ) -> CommandResult:
        if actor.read_only:
            raise DomainError("FORBIDDEN", 403, "Workflow is read-only")
        project_id = UUID(str(project_id))
        # Visibility precedes schema errors; permissions are checked again in the write transaction.
        self.detail(actor, project_id, include_progress=False)
        command = self.command_registry.parse(command)
        entry = self.command_registry.registration(command.action)
        payload = {"project_id": str(project_id), **command.model_dump(mode="json")}
        profiles = None
        profile_error = None
        if command.action == "delivery.accept" and command.issues:
            # Policy before exposing even a scoped identity lookup.
            with self.store.transaction() as tx:
                from .authorization import require_action

                require_action(tx, actor, project_id, command.action)
                row = require_project(tx, actor, project_id)
                replay = self._replay(tx, actor, command.operation_id, payload)
                if replay is not None:
                    return CommandResult.model_validate(
                        {
                            **replay,
                            "replayed": True,
                            "current_project_version": row["version"],
                        }
                    )
                if row["version"] != command.expected_version:
                    raise DomainError(
                        "VERSION_CONFLICT",
                        409,
                        "Project version changed",
                        {"current_version": row["version"]},
                    )
            try:
                profiles = self.member_profiles(
                    actor,
                    project_id,
                    list(dict.fromkeys(i.owner_id for i in command.issues)),
                )
            except Exception as exc:
                # A competing identical request may have committed during host I/O.
                # Live actor policy and canonical replay still precede lookup failure.
                profile_error = exc
        with self.store.transaction(write=True) as tx:
            row = require_project(tx, actor, project_id)
            permissions = effective_permissions(tx, actor, project_id)
            if not self.command_registry.permits(
                entry,
                permissions.roles, permissions.qualifications,
            ):
                raise DomainError("FORBIDDEN", 403, "Action permission denied")
            delivery.authorize(tx, actor, project_id, command)
            if command.action == "release.decide":
                quality.authorize_release(tx, actor, project_id, command)
            self.exchange_service.authorize(tx, actor, project_id, command)
            replay = self._replay(tx, actor, command.operation_id, payload)
            if replay is not None:
                return CommandResult.model_validate(
                    {
                        **replay,
                        "replayed": True,
                        "current_project_version": row["version"],
                    }
                )
            if row["version"] != command.expected_version:
                raise DomainError(
                    "VERSION_CONFLICT",
                    409,
                    "Project version changed",
                    {"current_version": row["version"]},
                )
            if profile_error is not None:
                raise profile_error
            context = CommandContext(
                actor,
                project_id,
                row["version"],
                business_time(tx),
                Dataset.model_validate(self.store.dataset),
                self.exchange_service,
                profiles,
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
        if isinstance(
            command,
            (exchanges.DispatchExchange, exchanges.QueryExchange, exchanges.PullSource),
        ):
            return self.exchange_service.perform(actor, project_id, command, result)
        return result
