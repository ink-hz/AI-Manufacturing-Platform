import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from .authorization import require_project
from .contracts import Dashboard, DomainError, ObjectPage, ProjectDetail


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
    def __init__(self, store, resolve_subject):
        self.store, self.resolve_subject = store, resolve_subject

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

    def create_project(self, actor, value):
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

    def change_grant(self, actor, project_id, user_id, value):
        if actor.read_only or not actor.configuration_admin:
            raise DomainError("FORBIDDEN", 403, "Permission denied")
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

    def detail(self, actor, project_id):
        with self.store.transaction() as tx:
            return project(require_project(tx, actor, project_id))

    def members(self, actor, project_id):
        with self.store.transaction() as tx:
            require_project(tx, actor, project_id)
            return [
                {
                    "user_id": r["user_id"],
                    "roles": json.loads(r["roles_json"]),
                    "qualifications": json.loads(r["qualifications_json"]),
                    "active": bool(r["active"]),
                }
                for r in tx.execute(
                    "SELECT * FROM project_grants WHERE project_id=?",
                    (str(project_id),),
                )
            ]

    def objects(self, actor, project_id, kind, *, limit=50, offset=0):
        self.detail(actor, project_id)
        return ObjectPage(items=[], total=0, limit=limit, offset=offset)

    def object_detail(self, actor, project_id, kind, object_id):
        self.detail(actor, project_id)
        raise DomainError("NOT_FOUND", 404, "Workflow resource not found")

    def dashboard(self, actor, project_id=None):
        if project_id is not None:
            self.detail(actor, project_id)
        return Dashboard(
            cards=[],
            project_ids=[project_id] if project_id else self.project_ids(actor),
        )

    def execute(self, actor, project_id, command):
        self.detail(actor, project_id)
        raise DomainError("UNSUPPORTED_ACTION", 422, "Unsupported action")
