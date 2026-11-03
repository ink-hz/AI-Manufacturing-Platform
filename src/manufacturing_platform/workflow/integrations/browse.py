"""Serialize authorized, project-scoped observations. Source I/O belongs to service."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from ..authorization import effective_permissions, require_project
from ..commands import COMMAND_REGISTRY
from ..contracts import DomainError, StrictModel
from .catalog import OPERATIONS, SYSTEM_IDS
from .contracts import (
    DeliveryReceipt,
    FactPage,
    IntegrationFact,
    ObjectRef,
    ProjectionResult,
    SourceKey,
    SystemDescriptor,
    SystemReceipt,
)
from .core_models import SystemId
from .routing import profile_for
from .store import canonical_hash, identity


class OperationOrigin(StrictModel):
    kind: Literal["operation"] = "operation"
    operation_receipt: SystemReceipt


class InboxOrigin(StrictModel):
    kind: Literal["inbox"] = "inbox"
    inbox_receipt: DeliveryReceipt


class UntrackedOrigin(StrictModel):
    kind: Literal["untracked"] = "untracked"


SourceOrigin = Annotated[
    OperationOrigin | InboxOrigin | UntrackedOrigin, Field(discriminator="kind")
]


class CausalDeliveryStatus(StrictModel):
    delivery_id: UUID
    consumer: SystemId
    receipt: DeliveryReceipt | None


class FactLink(StrictModel):
    source_key: SourceKey
    projection: ProjectionResult
    relation: Literal["projected"] = "projected"


class FactLinkPage(StrictModel):
    coverage: Literal["registered-projections"] = "registered-projections"
    link_cutoff: int = Field(ge=0)
    target: ObjectRef
    records: list[FactLink] = Field(max_length=200)
    continuation: int | None
    complete: bool


class ConsumerActivity(StrictModel):
    accepted_count: int = Field(strict=True, ge=0)
    rejected_count: int = Field(strict=True, ge=0)
    last_receipt: DeliveryReceipt
    healthy: bool


class ObservedSystemDescriptor(SystemDescriptor):
    consumer_activity: ConsumerActivity | None = None


class FactDetail(StrictModel):
    fact: IntegrationFact
    origin: SourceOrigin = Field(default_factory=UntrackedOrigin)
    source_accepted: bool | None = None
    consumer_delivered: bool | None = None
    workflow_projected: bool = False
    sap_posted: bool | None = None
    pending_deliveries: int = 0
    delivery_states: list[CausalDeliveryStatus] = Field(
        default_factory=list, max_length=15
    )
    projection: ProjectionResult | None = None
    predecessors: list[IntegrationFact] = Field(default_factory=list, max_length=1000)
    receipts: list[SystemReceipt] = Field(default_factory=list, max_length=200)


def authorize(tx, actor, project_id, registry, system=None):
    require_project(tx, actor, project_id)
    if registry.workflow_store.dataset["mode"] not in {"demo", "test"}:
        raise DomainError("SOURCE_UNAVAILABLE", 503, "Mock source unavailable")
    if profile_for(tx, project_id) != "oem-network-v1":
        raise DomainError(
            "SOURCE_UNAVAILABLE", 503, "Project has no OEM source profile"
        )
    if system:
        registry.require_available(system)


def systems(
    tx,
    actor,
    project_id,
    registry,
    *,
    healthy_systems=(),
    network_pending=None,
    legacy_healthy=False,
    consumer_activity=None,
):
    require_project(tx, actor, project_id)
    profile = profile_for(tx, project_id)
    mode = registry.workflow_store.dataset["mode"]
    permissions = effective_permissions(tx, actor, project_id)
    legacy_pending = tx.execute(
        "SELECT COUNT(*) FROM exchanges WHERE project_id=? AND system='erp' AND phase NOT IN ('accepted','posted','rejected')",
        (str(project_id),),
    ).fetchone()[0]
    legacy_used = (
        tx.execute(
            "SELECT 1 FROM exchanges WHERE project_id=? AND system='erp' LIMIT 1",
            (str(project_id),),
        ).fetchone()
        is not None
    )
    legacy_status = "unconfigured"
    if profile == "legacy-erp-v1":
        legacy_status = (
            "unavailable"
            if mode == "production"
            else "pending"
            if legacy_pending
            else "connected-mock"
            if legacy_healthy
            else "degraded"
            if legacy_used
            else "unexercised"
        )
    descriptors = [
        ObservedSystemDescriptor(
            system="erp",
            profile=profile,
            mode=mode,
            maturity="legacy",
            status=legacy_status,
            capabilities=[],
            permitted_operations=[],
            pending_count=legacy_pending if profile == "legacy-erp-v1" else 0,
        )
    ]
    for system in SYSTEM_IDS:
        capabilities = [
            tag for tag, spec in OPERATIONS.items() if spec.system == system
        ]
        permitted = []
        for tag in capabilities:
            spec = OPERATIONS[tag]
            actions = [a for _, a in spec.target_policies] or [spec.underlying_action]
            if not actor.read_only and any(
                COMMAND_REGISTRY.permits(
                    COMMAND_REGISTRY.registration(a),
                    permissions.roles,
                    permissions.qualifications,
                )
                for a in actions
            ):
                if tag == "mes.release":
                    from ..quality import release_kinds

                    if not {"manufacturing", "quality"} & set(
                        release_kinds(permissions.roles, permissions.qualifications)
                    ):
                        continue
                permitted.append(tag)
        row = tx.execute(
            "SELECT r.receipt_json FROM integration_receipts r JOIN integration_intents i ON i.project_id=r.project_id AND i.id=r.intent_id WHERE i.project_id=? AND i.system=? ORDER BY r.rowid DESC LIMIT 1",
            (str(project_id), system),
        ).fetchone()
        last = SystemReceipt.model_validate_json(row[0]) if row else None
        pending = tx.execute(
            "SELECT COUNT(*) FROM integration_intents WHERE project_id=? AND system=? AND phase NOT IN ('applied','rejected')",
            (str(project_id), system),
        ).fetchone()[0]
        pending += (network_pending or {}).get(system, 0)
        activity = (consumer_activity or {}).get(system)
        if activity and (
            activity.last_receipt.project_id != project_id
            or activity.last_receipt.consumer != system
        ):
            raise DomainError("NOT_FOUND", 404, "Consumer activity not found")
        configured = profile == "oem-network-v1" and registry.available(system)
        status = "unexercised" if configured else "unconfigured"
        if mode == "production":
            status = "unavailable"
        elif configured and last and system not in healthy_systems:
            status = "degraded"
        elif configured and pending:
            status = "pending"
        elif configured and last:
            status = (
                "connected-mock"
                if last.phase == "accepted" and system in healthy_systems
                else "degraded"
            )
        if configured and last is None and activity:
            status = (
                "pending"
                if pending
                else "connected-mock"
                if activity.healthy and activity.last_receipt.phase == "accepted"
                else "degraded"
            )
        descriptors.append(
            ObservedSystemDescriptor(
                system=system,
                profile=profile,
                mode=mode,
                maturity="planned" if system == "srm" else "modeled",
                status=status,
                capabilities=capabilities,
                permitted_operations=permitted if configured else [],
                pending_count=pending,
                last_receipt=last,
                consumer_activity=activity,
            )
        )
    return descriptors


def projection(tx, project_id, record):
    row = tx.execute(
        "SELECT payload_hash,result_json FROM integration_projections WHERE project_id=? AND system=? AND object_type=? AND external_id=? AND version=?",
        identity(project_id, record.source_key),
    ).fetchone()
    if not row:
        return None
    if row["payload_hash"] != canonical_hash(record):
        raise DomainError(
            "SOURCE_CONFLICT", 409, "Source differs from admitted projection"
        )
    result = ProjectionResult.model_validate_json(row["result_json"])
    if (
        result.project_id != project_id
        or result.source_key != record.source_key
        or result.payload_hash != canonical_hash(record)
    ):
        raise DomainError("SOURCE_CONFLICT", 409, "Projection link identity mismatch")
    return result


def facts(tx, actor, project_id, registry, system, object_type, *, observation):
    authorize(tx, actor, project_id, registry, system)
    page = FactPage.model_validate(observation)
    if page.project_id != project_id or any(
        r.source.system != system or r.source.object_type != object_type
        for r in page.records
    ):
        raise DomainError("NOT_FOUND", 404, "Source fact not found")
    page.projections = [
        p for r in page.records if (p := projection(tx, project_id, r)) is not None
    ]
    return page


def fact(
    tx,
    actor,
    project_id,
    registry,
    key: SourceKey,
    *,
    observation=None,
    predecessors=(),
    origin=None,
    delivery_states=(),
):
    authorize(tx, actor, project_id, registry, key.system)
    if observation is None:
        raise DomainError("NOT_FOUND", 404, "Source observation not found")
    record = IntegrationFact.model_validate(observation)
    if record.project_id != project_id or record.source_key != key:
        raise DomainError("NOT_FOUND", 404, "Source fact not found")
    for predecessor in predecessors:
        if (
            predecessor.project_id != project_id
            or predecessor.source_key not in record.caused_by
        ):
            raise DomainError("NOT_FOUND", 404, "Causal predecessor not found")
    rows = tx.execute(
        "SELECT receipt_json FROM integration_receipts WHERE project_id=? AND EXISTS(SELECT 1 FROM json_each(receipt_json,'$.source_keys') k WHERE json_extract(k.value,'$.system')=? AND json_extract(k.value,'$.object_type')=? AND json_extract(k.value,'$.external_id')=? AND json_extract(k.value,'$.version')=?) ORDER BY rowid DESC LIMIT 200",
        identity(project_id, key),
    ).fetchall()
    origin = origin or UntrackedOrigin()
    if isinstance(origin, OperationOrigin):
        if (
            key not in origin.operation_receipt.source_keys
            or origin.operation_receipt.system != key.system
        ):
            raise DomainError("SOURCE_CONFLICT", 409, "Producer receipt mismatch")
    elif isinstance(origin, InboxOrigin):
        if (
            origin.inbox_receipt.project_id != project_id
            or origin.inbox_receipt.consumer != key.system
            or origin.inbox_receipt.source_key not in record.caused_by
        ):
            raise DomainError("SOURCE_CONFLICT", 409, "Consumer origin mismatch")
    for state in delivery_states:
        receipt = state.receipt
        if receipt and (
            receipt.project_id != project_id
            or receipt.source_key != key
            or receipt.delivery_id != state.delivery_id
            or receipt.consumer != state.consumer
            or receipt.payload_hash != canonical_hash(record)
        ):
            raise DomainError("SOURCE_CONFLICT", 409, "Causal acknowledgment mismatch")
    projected = projection(tx, project_id, record)
    source_receipt = (
        origin.operation_receipt
        if isinstance(origin, OperationOrigin)
        else origin.inbox_receipt
        if isinstance(origin, InboxOrigin)
        else None
    )
    return FactDetail(
        fact=record,
        projection=projected,
        predecessors=list(predecessors),
        receipts=[SystemReceipt.model_validate_json(r[0]) for r in rows],
        origin=origin,
        source_accepted=source_receipt.phase == "accepted" if source_receipt else None,
        consumer_delivered=all(
            s.receipt and s.receipt.phase == "accepted" for s in delivery_states
        )
        if delivery_states
        else None,
        workflow_projected=projected is not None,
        sap_posted=True
        if key.system == "sap"
        and getattr(record.payload, "posted_at", None) is not None
        and (
            (
                isinstance(origin, OperationOrigin)
                and origin.operation_receipt.phase == "accepted"
            )
            or (
                isinstance(origin, InboxOrigin)
                and origin.inbox_receipt.phase == "accepted"
            )
        )
        else None,
        pending_deliveries=sum(s.receipt is None for s in delivery_states),
        delivery_states=list(delivery_states),
    )


def links(
    tx,
    actor,
    project_id,
    object_registry,
    target_kind,
    target_id,
    *,
    cursor=0,
    limit=50,
):
    require_project(tx, actor, project_id)
    if object_registry.detail(tx, project_id, target_kind, target_id) is None:
        raise DomainError("NOT_FOUND", 404, "Workflow resource not found")
    if (
        type(cursor) is not int
        or cursor < 0
        or type(limit) is not int
        or not 1 <= limit <= 200
    ):
        raise DomainError("INVALID_PAGINATION", 422, "Invalid link pagination")
    cutoff = tx.execute(
        "SELECT COALESCE(MAX(rowid),0) FROM integration_object_links WHERE project_id=? AND target_kind=? AND target_id=?",
        (str(project_id), target_kind.value, str(target_id)),
    ).fetchone()[0]
    rows = tx.execute(
        "SELECT l.rowid cursor,l.system,l.object_type,l.external_id,l.version,l.relation,p.result_json FROM integration_object_links l JOIN integration_projections p ON p.project_id=l.project_id AND p.system=l.system AND p.object_type=l.object_type AND p.external_id=l.external_id AND p.version=l.version WHERE l.project_id=? AND l.target_kind=? AND l.target_id=? AND l.rowid>? ORDER BY l.rowid LIMIT ?",
        (str(project_id), target_kind.value, str(target_id), cursor, limit + 1),
    ).fetchall()
    records = []
    for row in rows[:limit]:
        result = ProjectionResult.model_validate_json(row["result_json"])
        key = SourceKey(
            system=row["system"],
            object_type=row["object_type"],
            external_id=row["external_id"],
            version=row["version"],
        )
        target = ObjectRef(project_id=project_id, kind=target_kind, id=target_id)
        if (
            result.project_id != project_id
            or result.source_key != key
            or target not in result.targets
        ):
            raise DomainError("NOT_FOUND", 404, "Source link not found")
        records.append(
            FactLink(source_key=key, projection=result, relation=row["relation"])
        )
    return FactLinkPage(
        target=ObjectRef(project_id=project_id, kind=target_kind, id=target_id),
        records=records,
        continuation=rows[limit - 1]["cursor"] if len(rows) > limit else None,
        complete=len(rows) <= limit,
        link_cutoff=cutoff,
    )
