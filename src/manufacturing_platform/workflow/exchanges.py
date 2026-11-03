"""Durable outbox: intent commit, independent authority I/O, then validated apply."""

from .clock import business_time

import base64
import binascii
import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import ValidationError

from .adapters.mock import MockAuthorityAdapter, canonical, digest
from .authorization import require_action, require_project
from .commands import COMMAND_REGISTRY, CommandContext
from .contracts import (
    Dataset,
    DomainError,
    MutationResult,
    ObjectDetail,
    ObjectKind,
    ObjectRelation,
    ObjectSummary,
)
from .exchange_models import (
    AuthoritySnapshot,
    DispatchExchange,
    EcoSwitchPayload,
    ExchangeValue,
    ExternalReceipt,
    ExternalRequest,
    ImportFile,
    ImportSource,
    PullSource,
    QueryExchange,
    ReconcileExchange,
    RequestReservation,
    ReservationValue,
    ReservePayload,
    ResumePayload,
    ShipPayload,
    StartPayload,
    StopPayload,
)
from .imports import SOURCE_POLICIES, admit_records, ingest, parse_import, record_scope
from .orders import _history_rows, own
from .queries import OBJECT_REGISTRY
from .supply import amount, atoms, available, current_plan_id, fail

ALL_ROLES = {
    "project_owner",
    "engineering",
    "planner",
    "supply",
    "production",
    "quality",
    "warehouse",
}


# Only server-authored diagnostic text is public. Adapter exception/error strings
# may contain another tenant's identifiers, even when the typed envelope is local.
PUBLIC_REASONS = frozenset(
    {
        "",
        "Awaiting authoritative acceptance",
        "Authority rejected request",
        "Authority response unavailable",
        "Authority response schema invalid",
        "Source is not connected",
        "Configured authority is not connected",
        "Source snapshot identity mismatch",
        "Source record unavailable",
        "Adapter provenance mismatch",
        "Authority receipt binding or scope mismatch",
        "Receipt business key mismatch",
        "No authoritative operation found; dispatch may now retry the same business key",
        "Authority outcome unknown",
        "Intent committed; query authoritative business key before submission",
        "Authoritative source received",
        "Source identity and domain detail validated",
        "External actor and signature retained",
        "Authoritative source attached without duplicate quantities",
        "Receipt received",
        "Receipt identity already applied to different detail",
        "Receipt hash, source object or version mismatch",
        "Rejected receipt claims accepted quantity",
        "Stale receipt sequence",
        "Future receipt clock",
        "Receipt detail keys differ",
        "Receipt detail identity, owner or unit mismatch",
        "Receipt detail quantity differs from requested total",
        "Receipt quantity precision invalid",
        "Accepted receipt contains no quantity",
        "Reservation already confirmed",
        "Identity, version, sequence and keyed quantities validated",
        "Authority confirmed containment state",
        "Awaiting authoritative containment",
        "Stale freeze source version or sequence",
        "Stale or invalid freeze receipt",
        "Authority approved reservation",
        "Authority approved production transition",
        "MES accepted transition; local safety hold requires scoped stop and replan",
        "Readiness changed before authority acceptance",
        "File evidence received",
        "Entire bounded batch validated; no authority acceptance inferred",
        "Authoritative correction appended",
        "Original manual fact retained; authoritative correction appended",
        "Keyed receipt detail reconciled",
        "Keyed receipt detail discrepancy; equal totals do not prove equality",
        "Inbound record does not match requested type or scope",
        "Inbound source identity or provenance mismatch",
        "Inspection link does not match referenced receipt",
        "Workflow resource not found",
        "Referenced receipt must be pulled first",
        "Customer scope mismatch",
        "Invalid source clock",
        "Invalid source type or provenance",
        "Source identity has changed detail",
        "Manual receipt differs from authoritative detail; retain evidence and resolve discrepancy",
        "Inspection event differs from authoritative detail",
        "IQC quantity exceeds effective receipt",
        "Inspection event identity or version conflicts",
        "Explicit inspection link conflicts with source event",
        "Inspection already belongs to another source event",
        "Ambiguous manual inspections require an explicit scoped link",
        "Inspection source event belongs to another receipt",
        "Initiating business action permission denied",
    }
)


def public_reason(reason):
    from .freeze import AUTHORITY_CONTAINMENT_REASONS

    return (
        reason
        if reason in PUBLIC_REASONS or reason in AUTHORITY_CONTAINMENT_REASONS
        else "Exchange evidence requires reconciliation"
    )


def receipt_scope(tx, row, receipt):
    """Receipt evidence is visible only after binding all identities to the request."""
    if row["action"] == "freeze.request":
        from .freeze import receipt_scope as freeze_scope

        return freeze_scope(tx, row, receipt)
    if row["action"] == "shipment.request":
        from .delivery import receipt_scope as shipment_receipt_scope

        return shipment_receipt_scope(tx, row, receipt)
    if row["action"] == "eco.switch":
        from .eco import receipt_scope as eco_receipt_scope

        return eco_receipt_scope(tx, row, receipt)
    if row["action"] in {
        "production.start",
        "production.interrupt",
        "production.resume",
    }:
        request = ExternalRequest.model_validate_json(row["request_json"])
        payload = request.typed_payload
        source_id = str(
            payload.start_id
            if isinstance(payload, StartPayload)
            else payload.interruption_id
        )
        if (
            receipt.business_key != row["business_key"]
            or receipt.request_hash != row["request_hash"]
            or receipt.source_object_id != source_id
        ):
            return False
        if tx.execute(
            "SELECT 1 FROM exchange_receipts WHERE receipt_id=? AND exchange_id<>? AND valid=1",
            (str(receipt.receipt_id), row["id"]),
        ).fetchone():
            return False
        if isinstance(payload, StartPayload):
            scoped = tx.execute(
                "SELECT 1 FROM start_requests WHERE id=? AND project_id=? AND work_order_id=? AND exchange_id=?",
                (
                    str(payload.start_id),
                    row["project_id"],
                    str(payload.work_order_id),
                    row["id"],
                ),
            ).fetchone()
            expected = {(str(uid), sn) for uid, sn in payload.units}
            actual = {
                (d.key, str(d.unit_id), d.sn)
                for d in receipt.details
                if hasattr(d, "unit_id")
            }
            local = {
                (r["id"], r["sn"])
                for r in tx.execute(
                    "SELECT u.id,u.sn FROM start_units su JOIN units u ON u.id=su.unit_id AND u.project_id=su.project_id WHERE su.start_id=? AND su.project_id=?",
                    (str(payload.start_id), row["project_id"]),
                )
            }
            expected_details = {(str(uid), str(uid), sn) for uid, sn in payload.units}
            return (
                bool(scoped)
                and local == expected
                and not any(not hasattr(d, "unit_id") for d in receipt.details)
                and actual <= expected_details
                and len(actual) == len(receipt.details)
            )
        scoped = tx.execute(
            """SELECT 1 FROM interruptions i JOIN interruption_actions ia ON ia.interruption_id=i.id AND ia.project_id=i.project_id WHERE i.id=? AND i.project_id=? AND i.work_order_id=? AND ia.exchange_id=? AND ia.kind=?""",
            (
                source_id,
                row["project_id"],
                str(payload.work_order_id),
                row["id"],
                "stop" if isinstance(payload, StopPayload) else "resume",
            ),
        ).fetchone()
        start_scoped = True
        if isinstance(payload, StopPayload) and payload.start_id:
            start_scoped = bool(
                tx.execute(
                    "SELECT 1 FROM start_requests WHERE id=? AND project_id=? AND work_order_id=? AND accepted_receipt_id IS NOT NULL",
                    (
                        str(payload.start_id),
                        row["project_id"],
                        str(payload.work_order_id),
                    ),
                ).fetchone()
            )
        if isinstance(payload, ResumePayload) and receipt.phase == "accepted":
            if not receipt.details and payload.scope == "all":
                return bool(scoped)  # v7 immutable whole-WO receipt
            return (
                bool(scoped)
                and len(receipt.details) == 1
                and all(
                    getattr(d, "work_order_id", None) == payload.work_order_id
                    and getattr(d, "scope", None) == payload.scope
                    and d.key == source_id
                    and getattr(d, "state", None)
                    == ("partial" if payload.scope == "trial" else "running")
                    for d in receipt.details
                )
            )
        return bool(scoped) and start_scoped and not receipt.details
    if row["action"] != "reservation.request":
        return False
    request = ExternalRequest.model_validate_json(row["request_json"])
    payload = request.typed_payload
    if (
        receipt.business_key != row["business_key"]
        or receipt.request_hash != row["request_hash"]
        or receipt.source_object_id != str(payload.reservation_id)
        or len(receipt.details) != 1
    ):
        return False
    detail = receipt.details[0]
    if (detail.key, str(detail.lot_id), detail.owner_id, detail.unit) != (
        str(payload.requirement_id),
        str(payload.lot_id),
        payload.owner_id,
        payload.unit,
    ):
        return False
    if detail.stock_basis is not None:
        from .supply import atoms

        seen = set()
        total = 0
        try:
            for basis in detail.stock_basis:
                key = (basis.system.strip().casefold(), basis.external_id.strip())
                if (
                    basis.project_id != request.project_id
                    or basis.lot_id != payload.lot_id
                    or basis.owner_id != payload.owner_id
                    or basis.unit != payload.unit
                    or key[0] != row["system"].strip().casefold()
                    or not key[1]
                    or key in seen
                ):
                    return False
                seen.add(key)
                q = atoms(basis.quantity, basis.unit, payload.unit, payload.scale)
                source_q = atoms(
                    basis.source_quantity, basis.unit, payload.unit, payload.scale
                )
                if q > source_q:
                    return False
                prior_q = 0
                for prior in tx.execute(
                    "SELECT e.project_id,b.value FROM reservations r JOIN exchanges e ON e.id=r.exchange_id,json_each(e.receipt_json,'$.details[0].stock_basis') b WHERE r.authority_receipt_id IS NOT NULL AND e.id<>? AND lower(trim(json_extract(b.value,'$.system')))=? AND trim(json_extract(b.value,'$.external_id'))=?",
                    (row["id"], *key),
                ):
                    b = json.loads(prior["value"])
                    if (
                        prior["project_id"] != row["project_id"]
                        or b["lot_id"] != str(payload.lot_id)
                        or b["owner_id"] != payload.owner_id
                        or b["unit"] != payload.unit
                        or b["source_version"] != basis.source_version
                        or Decimal(b["source_quantity"]) != basis.source_quantity
                    ):
                        return False
                    prior_q += atoms(
                        Decimal(b["quantity"]), basis.unit, payload.unit, payload.scale
                    )
                if prior_q + q > source_q:
                    return False
                total += q
                local = tx.execute(
                    "SELECT project_id,material_lot_id,unit,source_version,q_atoms FROM effective_supply_receipts WHERE source_system=? AND source_external_id=?",
                    key,
                ).fetchone()
                if local and (
                    local["project_id"] != row["project_id"]
                    or local["material_lot_id"] != str(payload.lot_id)
                    or local["unit"] != payload.unit
                    or local["source_version"] != basis.source_version
                    or local["q_atoms"] != source_q
                ):
                    return False
            if total != atoms(
                detail.quantity, detail.unit, payload.unit, payload.scale
            ):
                return False
        except DomainError:
            return False
    scoped = tx.execute(
        """SELECT 1 FROM reservations r JOIN requirements q ON q.id=r.requirement_id AND q.project_id=r.project_id
        JOIN material_lots l ON l.id=r.material_lot_id AND l.project_id=r.project_id
        WHERE r.project_id=? AND r.id=? AND r.requirement_id=? AND r.work_order_id=? AND r.material_lot_id=?""",
        (
            row["project_id"],
            str(payload.reservation_id),
            str(payload.requirement_id),
            str(payload.work_order_id),
            str(payload.lot_id),
        ),
    ).fetchone()
    return (
        bool(scoped)
        and not tx.execute(
            "SELECT 1 FROM reservations WHERE authority_receipt_id=? AND project_id<>?",
            (str(receipt.receipt_id), row["project_id"]),
        ).fetchone()
    )


def public_receipt(receipt):
    from .freeze import AUTHORITY_CONTAINMENT_REASONS

    error = (
        receipt.error
        if receipt.error in AUTHORITY_CONTAINMENT_REASONS
        else "Authority rejected request"
    )
    return receipt.model_copy(
        update={"error": error if receipt.phase == "rejected" else None}
    )


def event(tx, row, phase, reason, payload=None):
    reason = public_reason(reason)
    tx.execute(
        "INSERT INTO exchange_events(exchange_id,project_id,phase,reason,payload_json,created_at) VALUES (?,?,?,?,?,?)",
        (
            row["id"],
            row["project_id"],
            phase,
            reason,
            canonical(payload or {}),
            business_time(tx).isoformat(),
        ),
    )
    tx.execute(
        "UPDATE exchanges SET phase=?,reason=? WHERE id=?", (phase, reason, row["id"])
    )


authorize_policy = require_action


class ExchangeService:
    def __init__(self, workflow):
        self.workflow = workflow
        # Compatibility handle for legacy test/seeder callers; OEM routing never uses it.
        self.adapter = workflow.system_registry.legacy_adapter()

    def authorize(self, tx, actor, project_id, command):
        if isinstance(command, (DispatchExchange, QueryExchange, ReconcileExchange)):
            row = own(tx, "exchanges", project_id, command.exchange_id)
            authorize_policy(tx, actor, project_id, row["policy_action"])
        elif isinstance(command, (PullSource, ImportSource, ImportFile)):
            authorize_policy(
                tx, actor, project_id, SOURCE_POLICIES[command.object_type]
            )

    def prepare(self, tx, context, request: ExternalRequest) -> UUID:
        authorize_policy(tx, context.actor, context.project_id, request.action)
        from .integrations.routing import profile_for

        request = request.model_copy(
            update={
                "system": self.workflow.system_registry.route(
                    profile_for(tx, context.project_id),
                    request.action,
                ),
            }
        )
        if request.project_id != context.project_id:
            fail("Exchange project mismatch")
        tx.execute(
            """INSERT INTO exchanges(id,project_id,reservation_id,action,policy_action,system,business_key,mode,request_json,request_hash,phase,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(request.id),
                str(context.project_id),
                str(request.typed_payload.reservation_id)
                if isinstance(request.typed_payload, ReservePayload)
                else None,
                request.action,
                request.action,
                request.system,
                request.business_key,
                (self.adapter.mode if self.adapter else "unavailable")
                if request.system == "erp"
                else (
                    "mock"
                    if self.workflow.store.dataset["mode"] in {"demo", "test"}
                    else "unavailable"
                ),
                request.model_dump_json(),
                digest(request.model_dump(mode="json")),
                "requested",
                context.now.isoformat(),
            ),
        )
        event(
            tx,
            own(tx, "exchanges", context.project_id, request.id),
            "requested",
            "Awaiting authoritative acceptance",
        )
        return request.id

    def dispatch(self, actor, project_id, exchange_id):
        return self._command(actor, project_id, exchange_id, "exchange.dispatch")

    def query(self, actor, project_id, exchange_id):
        return self._command(actor, project_id, exchange_id, "exchange.query")

    def _command(self, actor, project_id, exchange_id, action):
        return self.workflow.execute(
            actor,
            project_id,
            {
                "action": action,
                "operation_id": str(uuid4()),
                "expected_version": self.workflow.detail(actor, project_id).version,
                "exchange_id": str(exchange_id),
            },
        )

    def perform(self, actor, project_id, command, result):
        """Called only after the intent transaction has committed and closed."""
        with self.workflow.store.transaction() as tx:
            row = dict(own(tx, "exchanges", project_id, result.exchange_id))
            authorize_policy(tx, actor, project_id, row["policy_action"])
        if row["phase"] in {"accepted", "posted"} and row["action"] != "source.pull":
            return result
        adapter = self.adapter if row["system"] == "erp" else None
        receipt, records, problem, stock_proof = None, None, None, None
        rejected_boundary = False
        try:
            if row["system"] != "erp":
                adapter = self.workflow.system_registry.exchange_adapter(row["system"])
            if adapter is None:
                raise DomainError(
                    "SOURCE_UNAVAILABLE", 503, "Configured authority is not connected"
                )
            if row["action"] == "stock_basis.reconcile":
                from .exchange_models import StockBasisProof

                query = getattr(adapter, "stock_basis", None)
                if query is None:
                    raise DomainError(
                        "SOURCE_UNAVAILABLE",
                        503,
                        "Configured authority is not connected",
                    )
                request = ExternalRequest.model_validate_json(row["request_json"])
                raw = query(request)
                stock_proof = StockBasisProof.model_validate(
                    raw.model_dump(mode="json")
                    if isinstance(raw, StockBasisProof)
                    else raw
                )
            elif row["action"] == "source.pull":
                pull = PullSource.model_validate_json(row["request_json"])
                snapshot = adapter.snapshot(pull.system, pull.object_type)
                snapshot = AuthoritySnapshot.model_validate(
                    snapshot.model_dump(mode="json")
                    if isinstance(snapshot, AuthoritySnapshot)
                    else snapshot
                )
                if (
                    snapshot.system.strip().casefold() != pull.system.strip().casefold()
                    or snapshot.object_type != pull.object_type
                ):
                    raise DomainError(
                        "SOURCE_DISCREPANCY", 409, "Source snapshot identity mismatch"
                    )
                records = [
                    record
                    for record in snapshot.records
                    if record.source.external_id.strip() == pull.external_id.strip()
                    and record.project_id == UUID(str(project_id))
                ]
                if len(records) != 1:
                    raise DomainError(
                        "SOURCE_NOT_FOUND", 404, "Source record unavailable"
                    )
                if (
                    records[0].source.mode != adapter.mode
                    or records[0].source.system.strip().casefold()
                    != pull.system.strip().casefold()
                ):
                    raise DomainError(
                        "SOURCE_DISCREPANCY", 409, "Adapter provenance mismatch"
                    )
            else:
                request = ExternalRequest.model_validate_json(row["request_json"])
                # Even the first dispatch queries; a crash after submission can never blindly resend.
                receipt = adapter.query(request.system, request.business_key)
                if receipt is None and isinstance(command, DispatchExchange):
                    if isinstance(request.typed_payload, (StartPayload, ResumePayload)):
                        from .execution import outbound_execution_ready

                        with self.workflow.store.transaction() as live_tx:
                            live_row = own(
                                live_tx, "exchanges", project_id, result.exchange_id
                            )
                            authorize_policy(
                                live_tx, actor, project_id, live_row["policy_action"]
                            )
                            ready = outbound_execution_ready(
                                live_tx,
                                project_id,
                                request.typed_payload,
                                business_time(live_tx),
                            )
                    elif request.action == "reservation.request":
                        from .freeze import lot_hold

                        with self.workflow.store.transaction() as live_tx:
                            live_row = own(
                                live_tx, "exchanges", project_id, result.exchange_id
                            )
                            authorize_policy(
                                live_tx, actor, project_id, live_row["policy_action"]
                            )
                            ready = not lot_hold(
                                live_tx, project_id, request.typed_payload.lot_id
                            )
                    elif request.action == "shipment.request":
                        from .delivery import current_shipment_reasons

                        with self.workflow.store.transaction() as live_tx:
                            live_row = own(
                                live_tx, "exchanges", project_id, result.exchange_id
                            )
                            authorize_policy(
                                live_tx, actor, project_id, live_row["policy_action"]
                            )
                            ready = not current_shipment_reasons(
                                live_tx, project_id, request.typed_payload.shipment_id
                            )
                    elif request.action == "eco.switch":
                        from .eco import revision_ready

                        with self.workflow.store.transaction() as live_tx:
                            live_row = own(
                                live_tx, "exchanges", project_id, result.exchange_id
                            )
                            authorize_policy(
                                live_tx, actor, project_id, live_row["policy_action"]
                            )
                            ready = True
                            if request.typed_payload.new_revision_id:
                                try:
                                    revision_ready(
                                        live_tx,
                                        project_id,
                                        request.typed_payload.new_revision_id,
                                    )
                                except DomainError:
                                    ready = False
                    else:
                        ready = True
                    if ready:
                        receipt = adapter.submit(request)
                    else:
                        problem = "Current readiness blocks authority submission; restore and dispatch this intent"
                elif receipt is None:
                    problem = "No authoritative operation found; dispatch may now retry the same business key"
                if receipt is not None:
                    receipt = ExternalReceipt.model_validate(
                        receipt.model_dump(mode="json")
                        if isinstance(receipt, ExternalReceipt)
                        else receipt
                    )
        except (TimeoutError, OSError):
            receipt, records = None, None
            problem = "Authority response unavailable"
        except ValidationError:
            receipt, records = None, None
            problem = "Authority response schema invalid"
            rejected_boundary = True
        except DomainError as exc:
            receipt, records = None, None
            problem = public_reason(exc.message)
            rejected_boundary = exc.status != 503
        # Internal apply is another audited, UUID-idempotent command boundary. Revalidate current policy.
        with self.workflow.store.transaction(write=True) as tx:
            project = require_project(tx, actor, project_id)
            row = own(tx, "exchanges", project_id, result.exchange_id)
            authorize_policy(tx, actor, project_id, row["policy_action"])
            # CAS includes concurrent policy/grant/business writes; recovery is explicit if it moved.
            if project["version"] != result.project_version:
                raise DomainError(
                    "VERSION_CONFLICT",
                    409,
                    "Project changed while authority was responding",
                    {"current_version": project["version"]},
                )
            context = CommandContext(
                actor,
                UUID(str(project_id)),
                project["version"],
                business_time(tx),
                Dataset.model_validate(self.workflow.store.dataset),
                self,
            )
            if stock_proof is not None:
                from .stock_proofs import apply_proof

                try:
                    apply_proof(tx, context, row, stock_proof, adapter.mode)
                except DomainError as exc:
                    self._reject(tx, context, row, exc.message)
            elif receipt is not None:
                if not receipt_scope(tx, row, receipt):
                    self._reject(
                        tx,
                        context,
                        row,
                        "Authority receipt binding or scope mismatch",
                        receipt_hash=digest(receipt.model_dump(mode="json")),
                    )
                else:
                    self.apply(tx, context, public_receipt(receipt))
            elif records is not None:
                pull = PullSource.model_validate_json(row["request_json"])
                try:
                    admit_records(
                        tx,
                        context,
                        records,
                        object_type=pull.object_type,
                        trusted=True,
                        system=pull.system,
                        external_id=pull.external_id,
                        mode=adapter.mode,
                    )
                except DomainError as exc:
                    self._reject(tx, context, row, exc.message)
                else:
                    event(
                        tx,
                        row,
                        "received",
                        "Authoritative source received",
                        {"records": [r.model_dump(mode="json") for r in records]},
                    )
                    tx.execute("SAVEPOINT inbound_batch")
                    try:
                        ingest(
                            tx,
                            context,
                            records,
                            object_type=pull.object_type,
                            trusted=True,
                            system=pull.system,
                            external_id=pull.external_id,
                            mode=adapter.mode,
                        )
                        event(
                            tx,
                            row,
                            "validated",
                            "Source identity and domain detail validated",
                        )
                        event(
                            tx, row, "approved", "External actor and signature retained"
                        )
                        event(
                            tx,
                            row,
                            "accepted",
                            "Authoritative source attached without duplicate quantities",
                        )
                        tx.execute("RELEASE inbound_batch")
                    except DomainError as exc:
                        tx.execute("ROLLBACK TO inbound_batch")
                        tx.execute("RELEASE inbound_batch")
                        self._reject(tx, context, row, exc.message)
            elif rejected_boundary:
                self._reject(tx, context, row, problem)
            else:
                event(tx, row, "unknown", problem or "Authority outcome unknown")
            applied_id = uuid4()
            applied = result.model_copy(
                update={
                    "operation_id": applied_id,
                    "project_version": project["version"] + 1,
                }
            )
            tx.execute(
                "UPDATE projects SET version=version+1 WHERE id=?", (str(project_id),)
            )
            self.workflow._save(
                tx,
                actor,
                applied_id,
                {
                    "exchange_id": row["id"],
                    "intent_operation_id": str(command.operation_id),
                    "expected_version": project["version"],
                    "action": "exchange.apply",
                },
                applied.model_dump(mode="json"),
                project_id,
                "exchange.apply",
                result.exchange_id,
            )
        # Live response metadata is separate from the immutable intent result.
        return result.model_copy(
            update={"current_project_version": project["version"] + 1}
        )

    @staticmethod
    def _reject(tx, context, row, reason, *, receipt_hash=None):
        from .freeze import AUTHORITY_CONTAINMENT_REASONS

        reason = public_reason(reason)
        # Keep the existing no-effect closure classification. The owned reason
        # remains visible in the event/current reason and discrepancy evidence.
        no_effect = reason in AUTHORITY_CONTAINMENT_REASONS
        event(
            tx,
            row,
            "rejected",
            reason,
            {"receipt_hash": receipt_hash} if receipt_hash else None,
        )
        tx.execute(
            "INSERT INTO exchange_discrepancies(exchange_id,project_id,owner_id,owner_name,reason,evidence) VALUES (?,?,?,?,?,?)",
            (
                row["id"],
                str(context.project_id),
                str(context.actor.user_id),
                context.actor.display_name,
                "Authority rejected request" if no_effect else reason,
                reason if no_effect else "Rejected outcome recorded for reconciliation",
            ),
        )

    def apply(self, tx, context, receipt: ExternalReceipt) -> MutationResult:
        receipt = ExternalReceipt.model_validate(receipt.model_dump(mode="json"))
        row = tx.execute(
            "SELECT * FROM exchanges WHERE business_key=? AND project_id=?",
            (receipt.business_key, str(context.project_id)),
        ).fetchone()
        if not row:
            fail("Unknown receipt business key")
        authorize_policy(tx, context.actor, context.project_id, row["policy_action"])
        if not receipt_scope(tx, row, receipt):
            self._reject(
                tx,
                context,
                row,
                "Authority receipt binding or scope mismatch",
                receipt_hash=digest(receipt.model_dump(mode="json")),
            )
            return MutationResult(
                object_type="exchange",
                object_id=UUID(row["id"]),
                exchange_id=UUID(row["id"]),
            )
        receipt = public_receipt(receipt)
        request = ExternalRequest.model_validate_json(row["request_json"])
        payload = request.typed_payload
        if request.action == "freeze.request":
            from .freeze import apply as apply_freeze

            return apply_freeze(self, tx, context, row, request, receipt)
        if request.action == "shipment.request":
            from .delivery import apply_shipment

            return apply_shipment(self, tx, context, row, request, receipt)
        if request.action == "eco.switch":
            from .eco import apply_switch

            return apply_switch(self, tx, context, row, request, receipt)
        if request.action in {
            "production.start",
            "production.interrupt",
            "production.resume",
        }:
            return self._apply_execution(tx, context, row, request, receipt)
        reason = ""
        if (
            receipt.phase == "rejected"
            and row["receipt_json"] == receipt.model_dump_json()
        ):
            event(tx, row, "rejected", receipt.error or "Authority rejected request")
            return MutationResult(
                object_type="exchange",
                object_id=UUID(row["id"]),
                exchange_id=UUID(row["id"]),
            )
        existing = tx.execute(
            "SELECT * FROM reservations WHERE authority_receipt_id=?",
            (str(receipt.receipt_id),),
        ).fetchone()
        if existing:
            if (
                existing["id"] == str(payload.reservation_id)
                and row["receipt_json"] == receipt.model_dump_json()
            ):
                return MutationResult(
                    object_type="exchange",
                    object_id=UUID(row["id"]),
                    exchange_id=UUID(row["id"]),
                )
            reason = "Receipt identity already applied to different detail"
        elif (
            receipt.request_hash != row["request_hash"]
            or receipt.source_object_id != str(payload.reservation_id)
            or receipt.source_version != request.source_version
        ):
            reason = "Receipt hash, source object or version mismatch"
        elif receipt.phase == "rejected" and receipt.accepted_quantity != 0:
            reason = "Rejected receipt claims accepted quantity"
        elif receipt.sequence <= row["source_sequence"] or receipt.sequence < 1:
            reason = "Stale receipt sequence"
        elif (
            receipt.occurred_at > context.now.replace(microsecond=999999)
            and (receipt.occurred_at - context.now).total_seconds() > 300
        ):
            reason = "Future receipt clock"
        elif len(receipt.details) != 1:
            reason = "Receipt detail keys differ"
        else:
            detail = receipt.details[0]
            if (detail.key, str(detail.lot_id), detail.owner_id, detail.unit) != (
                str(payload.requirement_id),
                str(payload.lot_id),
                payload.owner_id,
                payload.unit,
            ):
                reason = "Receipt detail identity, owner or unit mismatch"
            elif (
                receipt.accepted_quantity + receipt.rejected_quantity
                != payload.quantity
                or detail.quantity != receipt.accepted_quantity
            ):
                reason = "Receipt detail quantity differs from requested total"
            else:
                try:
                    atoms(
                        receipt.accepted_quantity,
                        payload.unit,
                        payload.unit,
                        payload.scale,
                    )
                    atoms(
                        receipt.rejected_quantity,
                        payload.unit,
                        payload.unit,
                        payload.scale,
                    )
                except DomainError:
                    reason = "Receipt quantity precision invalid"
        tx.execute(
            "INSERT OR IGNORE INTO exchange_receipts(exchange_id,project_id,receipt_id,payload_json,valid,reason) VALUES (?,?,?,?,?,?)",
            (
                row["id"],
                str(context.project_id),
                str(receipt.receipt_id),
                receipt.model_dump_json(),
                int(not reason),
                reason,
            ),
        )
        event(tx, row, "received", "Receipt received", receipt.model_dump(mode="json"))
        if reason:
            self._reject(tx, context, row, reason)
        elif receipt.phase == "rejected":
            self._reject(
                tx, context, row, receipt.error or "Authority rejected request"
            )
            tx.execute(
                "UPDATE exchanges SET receipt_json=?,source_sequence=? WHERE id=?",
                (receipt.model_dump_json(), receipt.sequence, row["id"]),
            )
        elif receipt.phase in {"accepted", "posted"}:
            if receipt.accepted_quantity <= 0:
                self._reject(tx, context, row, "Accepted receipt contains no quantity")
            else:
                # Links and ownership were checked in prepare; immutable snapshots bind the acceptance.
                reservation = own(
                    tx, "reservations", context.project_id, payload.reservation_id
                )
                if reservation["confirmed_atoms"]:
                    self._reject(tx, context, row, "Reservation already confirmed")
                else:
                    event(
                        tx,
                        row,
                        "validated",
                        "Identity, version, sequence and keyed quantities validated",
                    )
                    event(tx, row, "approved", "Authority approved reservation")
                    tx.execute(
                        "UPDATE reservations SET confirmed_atoms=?,authority_receipt_id=?,accepted_sequence=?,source_version=? WHERE id=?",
                        (
                            atoms(
                                receipt.accepted_quantity,
                                payload.unit,
                                payload.unit,
                                payload.scale,
                            ),
                            str(receipt.receipt_id),
                            receipt.sequence,
                            receipt.source_version,
                            reservation["id"],
                        ),
                    )
                    tx.execute(
                        "UPDATE exchanges SET receipt_json=?,source_sequence=? WHERE id=?",
                        (receipt.model_dump_json(), receipt.sequence, row["id"]),
                    )
                    event(tx, row, receipt.phase, receipt.error or "")
        else:
            event(
                tx,
                row,
                receipt.phase,
                receipt.error or "Awaiting authoritative acceptance",
            )
        return MutationResult(
            object_type="exchange",
            object_id=UUID(row["id"]),
            exchange_id=UUID(row["id"]),
        )

    def _apply_execution(self, tx, context, row, request, receipt):
        payload = request.typed_payload
        source_id = str(
            payload.start_id
            if isinstance(payload, StartPayload)
            else payload.interruption_id
        )
        requested = len(payload.units) if isinstance(payload, StartPayload) else 1
        reason = ""
        if (
            receipt.source_version != request.source_version
            or receipt.sequence < 1
            or receipt.sequence <= row["source_sequence"]
        ):
            reason = "Receipt hash, source object or version mismatch"
        elif receipt.accepted_quantity + receipt.rejected_quantity != requested:
            reason = "Receipt detail quantity differs from requested total"
        elif receipt.phase == "accepted" and receipt.accepted_quantity != requested:
            reason = "Accepted receipt contains no quantity"
        elif receipt.phase == "rejected" and receipt.accepted_quantity != 0:
            reason = "Rejected receipt claims accepted quantity"
        elif (
            isinstance(payload, StartPayload)
            and receipt.phase == "accepted"
            and (
                len(receipt.details) != requested
                or {
                    (d.key, str(d.unit_id), d.sn, d.state)
                    for d in receipt.details
                    if hasattr(d, "unit_id")
                }
                != {(str(uid), str(uid), sn, "running") for uid, sn in payload.units}
            )
        ):
            reason = "Receipt detail keys differ"
        elif (
            receipt.occurred_at > context.now
            and (receipt.occurred_at - context.now).total_seconds() > 300
        ):
            reason = "Future receipt clock"
        if row["receipt_json"] == receipt.model_dump_json() and row["phase"] in {
            "accepted",
            "rejected",
        }:
            return MutationResult(
                object_type="exchange",
                object_id=UUID(row["id"]),
                exchange_id=UUID(row["id"]),
            )
        tx.execute(
            "INSERT OR IGNORE INTO exchange_receipts(exchange_id,project_id,receipt_id,payload_json,valid,reason) VALUES (?,?,?,?,?,?)",
            (
                row["id"],
                str(context.project_id),
                str(receipt.receipt_id),
                receipt.model_dump_json(),
                int(not reason),
                reason,
            ),
        )
        event(tx, row, "received", "Receipt received", receipt.model_dump(mode="json"))
        if reason:
            self._reject(tx, context, row, reason)
        elif receipt.phase == "rejected":
            self._reject(
                tx, context, row, receipt.error or "Authority rejected request"
            )
            tx.execute(
                "UPDATE exchanges SET receipt_json=?,source_sequence=? WHERE id=?",
                (receipt.model_dump_json(), receipt.sequence, row["id"]),
            )
            if isinstance(payload, StartPayload):
                tx.execute("DELETE FROM start_units WHERE start_id=?", (source_id,))
                tx.execute(
                    "UPDATE units SET state='registered',mode=NULL WHERE id IN (SELECT json_each.value FROM json_each(?)) AND accepted_start_id IS NULL",
                    (json.dumps([str(uid) for uid, _ in payload.units]),),
                )
        elif receipt.phase == "accepted":
            from .execution import (
                current_resume_interruption,
                project_production_controls,
            )
            from .readiness import evaluate
            from .supply import current_plan_id

            held = False
            if isinstance(payload, (StartPayload, ResumePayload)):
                if isinstance(payload, StartPayload):
                    modes = [payload.mode]
                    plan_matches = True
                    safe_to_start = not tx.execute(
                        "SELECT 1 FROM interruptions WHERE project_id=? AND work_order_id=? AND resolved_at IS NULL AND superseded_by IS NULL LIMIT 1",
                        (str(context.project_id), str(payload.work_order_id)),
                    ).fetchone()
                else:
                    modes = [
                        r[0]
                        for r in tx.execute(
                            "SELECT DISTINCT s.mode FROM start_requests s JOIN exchanges e ON e.id=s.exchange_id WHERE s.project_id=? AND s.work_order_id=? AND (s.accepted_receipt_id IS NOT NULL OR e.phase!='rejected' OR e.receipt_json IS NULL) AND (?='all' OR s.mode='trial')",
                            (
                                str(context.project_id),
                                str(payload.work_order_id),
                                payload.scope,
                            ),
                        )
                    ]
                    plan_matches = current_plan_id(
                        tx, context.project_id, payload.work_order_id
                    ) == str(payload.plan_id)
                    safe_to_start = (
                        current_resume_interruption(tx, context.project_id, payload)
                        is not None
                    )
                held = (
                    not plan_matches
                    or not safe_to_start
                    or not all(
                        evaluate(
                            tx,
                            context.project_id,
                            payload.work_order_id,
                            mode,
                            context.now,
                        ).ready
                        for mode in modes
                    )
                )
            event(
                tx,
                row,
                "validated",
                "Identity, version, sequence and keyed quantities validated",
            )
            tx.execute(
                "UPDATE exchanges SET receipt_json=?,source_sequence=? WHERE id=?",
                (receipt.model_dump_json(), receipt.sequence, row["id"]),
            )
            if isinstance(payload, StartPayload):
                tx.execute(
                    "UPDATE start_requests SET accepted_receipt_id=?,accepted_seq=? WHERE id=?",
                    (str(receipt.receipt_id), receipt.sequence, source_id),
                )
                for uid, _ in payload.units:
                    tx.execute(
                        "UPDATE units SET state=?,accepted_start_id=? WHERE id=? AND project_id=?",
                        (
                            "start_pending" if held else "running",
                            source_id,
                            str(uid),
                            str(context.project_id),
                        ),
                    )
            else:
                tx.execute(
                    "INSERT INTO production_controls VALUES (?,?,?,?,?,?,?)",
                    (
                        row["id"],
                        str(context.project_id),
                        str(payload.work_order_id),
                        receipt.sequence,
                        "stop" if isinstance(payload, StopPayload) else "resume",
                        "all" if isinstance(payload, StopPayload) else payload.scope,
                        int(held),
                    ),
                )
                if isinstance(payload, StopPayload):
                    tx.execute(
                        "UPDATE interruptions SET authority_stopped_at=? WHERE id=? AND project_id=?",
                        (
                            receipt.occurred_at.isoformat(),
                            source_id,
                            str(context.project_id),
                        ),
                    )
                elif payload.scope == "trial":
                    tx.execute(
                        "UPDATE interruptions SET trial_resumed_at=? WHERE id=? AND project_id=?",
                        (
                            receipt.occurred_at.isoformat(),
                            source_id,
                            str(context.project_id),
                        ),
                    )
                elif payload.scope == "all":
                    tx.execute(
                        "UPDATE interruptions SET resolved_at=? WHERE id=? AND project_id=?",
                        (
                            receipt.occurred_at.isoformat(),
                            source_id,
                            str(context.project_id),
                        ),
                    )
            project_production_controls(tx, context.project_id, payload.work_order_id)
            event(
                tx,
                row,
                "accepted",
                "MES accepted transition; local safety hold requires scoped stop and replan"
                if held
                else "Authority approved production transition",
            )
        else:
            event(tx, row, receipt.phase, "Awaiting authoritative acceptance")
        return MutationResult(
            object_type="exchange",
            object_id=UUID(row["id"]),
            exchange_id=UUID(row["id"]),
        )


def request_reservation(tx, context, command):
    req = own(tx, "requirements", context.project_id, command.requirement_id)
    lot = own(tx, "material_lots", context.project_id, command.lot_id)
    wo = own(tx, "work_orders", context.project_id, command.work_order_id)
    if req["work_order_id"] != wo["id"] or req["plan_id"] != current_plan_id(
        tx, context.project_id, wo["id"]
    ):
        fail("Reservation requires current plan requirement for this work order")
    plan = own(tx, "plans", context.project_id, req["plan_id"])
    from .contracts import SourceRef
    from .supply import cutoff_issue

    if cutoff_issue(SourceRef.model_validate_json(plan["source_json"]), context.now):
        fail("Current plan cutoff is stale")
    if (
        (lot["material_id"], lot["owner_id"], lot["unit"], lot["scale"])
        != (req["material_id"], req["owner_id"], req["unit"], req["scale"])
        or lot["state"] != "active"
        or lot["expiry"] < context.now.date().isoformat()
    ):
        fail("Reservation lot is ineligible")
    from .freeze import lot_hold

    if lot_hold(tx, context.project_id, lot["id"]):
        fail("Reservation lot containment pending or frozen")
    q = atoms(command.quantity, command.unit, lot["unit"], lot["scale"])
    bal = available(tx, context.project_id, req["id"], context.now)
    pending = tx.execute(
        """SELECT COALESCE(SUM(r.requested_atoms),0) FROM reservations r JOIN requirements prior ON prior.id=r.requirement_id JOIN exchanges e ON e.id=r.exchange_id WHERE r.project_id=? AND prior.lineage_id=? AND (e.phase IN ('requested','unknown','received','validated','approved') OR (e.phase='rejected' AND e.attempted=1 AND e.receipt_json IS NULL))""",
        (str(context.project_id), req["lineage_id"]),
    ).fetchone()[0]
    if q + pending > atoms(bal.shortage, command.unit, lot["unit"], lot["scale"]):
        fail("Reservation exceeds unreserved requirement")
    ident, eid = uuid4(), uuid4()
    tx.execute(
        "INSERT INTO reservations(id,project_id,requirement_id,work_order_id,material_lot_id,requested_atoms,confirmed_atoms,unit,source_version,authority_receipt_id,created_at) VALUES (?,?,?,?,?,?,0,?,1,NULL,?)",
        (
            str(ident),
            str(context.project_id),
            req["id"],
            wo["id"],
            lot["id"],
            q,
            command.unit,
            context.now.isoformat(),
        ),
    )
    request = ExternalRequest(
        id=eid,
        system="erp",
        action=command.action,
        business_key=str(eid),
        source_version=1,
        project_id=context.project_id,
        typed_payload=ReservePayload(
            reservation_id=ident,
            work_order_id=wo["id"],
            requirement_id=req["id"],
            lot_id=lot["id"],
            material_id=lot["material_id"],
            owner_id=lot["owner_id"],
            quantity=str(command.quantity),
            unit=command.unit,
            scale=lot["scale"],
            plan_id=plan["id"],
            plan_version=plan["source_version"],
        ),
    )
    context.exchange_service.prepare(tx, context, request)
    tx.execute(
        "UPDATE reservations SET exchange_id=? WHERE id=?", (str(eid), str(ident))
    )
    return MutationResult(object_type="reservation", object_id=ident, exchange_id=eid)


def prepare_io(tx, context, command):
    if isinstance(command, PullSource):
        eid = str(uuid4())
        tx.execute(
            "INSERT INTO exchanges(id,project_id,action,policy_action,system,business_key,mode,request_json,request_hash,phase,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                eid,
                str(context.project_id),
                command.action,
                SOURCE_POLICIES[command.object_type],
                command.system.strip().casefold(),
                eid,
                context.exchange_service.adapter.mode
                if context.exchange_service.adapter
                else "unavailable",
                command.model_dump_json(),
                digest(command.model_dump(mode="json")),
                "requested",
                context.now.isoformat(),
            ),
        )
        row = own(tx, "exchanges", context.project_id, eid)
    else:
        row = own(tx, "exchanges", context.project_id, command.exchange_id)
    if row["action"] not in {
        "freeze.request",
        "stock_basis.reconcile",
        "shipment.request",
        "eco.switch",
        "reservation.request",
        "source.pull",
        "production.start",
        "production.interrupt",
        "production.resume",
    }:
        fail("Imported file evidence has no authority dispatch action")
    if row["phase"] not in {"accepted", "posted"}:
        tx.execute("UPDATE exchanges SET attempted=1 WHERE id=?", (row["id"],))
        event(
            tx,
            row,
            "unknown",
            "Intent committed; query authoritative business key before submission",
        )
    return MutationResult(
        object_type="exchange", object_id=UUID(row["id"]), exchange_id=UUID(row["id"])
    )


def import_source(tx, context, command):
    if isinstance(command, ImportFile):
        try:
            content = base64.b64decode(command.content_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise DomainError("IMPORT_INVALID", 422, "Invalid base64 import") from exc
        records = parse_import(content, command.format, command.object_type)
    else:
        records = command.rows
    result = ingest(tx, context, records, object_type=command.object_type)[-1]
    eid = str(uuid4())
    tx.execute(
        "INSERT INTO exchanges(id,project_id,action,policy_action,system,business_key,mode,request_json,request_hash,phase,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            eid,
            str(context.project_id),
            command.action,
            SOURCE_POLICIES[command.object_type],
            records[0].source.system,
            eid,
            "file",
            command.model_dump_json(),
            digest(command.model_dump(mode="json")),
            "received",
            context.now.isoformat(),
        ),
    )
    row = own(tx, "exchanges", context.project_id, eid)
    event(tx, row, "received", "File evidence received")
    event(
        tx,
        row,
        "validated",
        "Entire bounded batch validated; no authority acceptance inferred",
    )
    return result.model_copy(update={"exchange_id": UUID(eid)})


def reconcile(tx, context, command):
    row = own(tx, "exchanges", context.project_id, command.exchange_id)
    from .orders import source_key
    from .supply import source_ok

    source_ok(
        command.source,
        command.object_type,
        context.now,
        source_modes={"manual", "file"},
    )
    if command.source.version != command.source_version:
        fail("Reconciliation source version mismatch")
    if row["action"] == "source.pull":
        from .imports import record_adapter
        from .orders import source_key

        saved = tx.execute(
            "SELECT payload_json FROM exchange_events WHERE exchange_id=? AND json_type(payload_json,'$.records')='array' ORDER BY seq DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        if not saved or command.resolution != "accept_authority":
            fail("Resolve source discrepancy using the retained authoritative record")
        records = [
            record_adapter.validate_python(r) for r in json.loads(saved[0])["records"]
        ]
        if (
            len(records) != 1
            or records[0].object_type != command.object_type
            or source_key(records[0].source) != source_key(command.source)
            or records[0].source.version != command.source_version
        ):
            fail("Reconciliation source identity/version mismatch")
        ingest(
            tx,
            context,
            records,
            object_type=PullSource.model_validate_json(row["request_json"]).object_type,
            system=row["system"],
            external_id=PullSource.model_validate_json(row["request_json"]).external_id,
            mode=row["mode"],
            trusted=True,
            correction_exchange=row["id"],
            correction_evidence=command.evidence,
        )
        previous = tx.execute(
            "SELECT seq FROM exchange_discrepancies WHERE exchange_id=? ORDER BY seq DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        tx.execute(
            "INSERT INTO exchange_discrepancies(exchange_id,project_id,owner_id,owner_name,reason,evidence,resolves_seq) VALUES (?,?,?,?,?,?,?)",
            (
                row["id"],
                str(context.project_id),
                str(context.actor.user_id),
                context.actor.display_name,
                "Authoritative correction appended",
                command.evidence,
                previous[0] if previous else None,
            ),
        )
        event(
            tx,
            row,
            "accepted",
            "Original manual fact retained; authoritative correction appended",
        )
        return MutationResult(
            object_type="exchange",
            object_id=UUID(row["id"]),
            exchange_id=UUID(row["id"]),
        )
    if row["action"] != "reservation.request" or not row["receipt_json"]:
        fail("Reconciliation requires an authoritative reservation receipt")
    if source_key(command.source) != (
        row["system"],
        "reservation",
        row["business_key"],
    ):
        fail("Reconciliation source identity mismatch")
    receipt = ExternalReceipt.model_validate_json(row["receipt_json"])
    expected = {d.key: d.model_dump(mode="json") for d in receipt.details}
    actual = {d.key: d.model_dump(mode="json") for d in command.details}
    matches = (
        len(actual) == len(command.details)
        and expected == actual
        and command.source_version == receipt.source_version
    )
    reason = (
        "Keyed receipt detail reconciled"
        if matches
        else "Keyed receipt detail discrepancy; equal totals do not prove equality"
    )
    last = tx.execute(
        "SELECT seq FROM exchange_discrepancies WHERE exchange_id=? ORDER BY seq DESC LIMIT 1",
        (row["id"],),
    ).fetchone()
    tx.execute(
        "INSERT INTO exchange_discrepancies(exchange_id,project_id,owner_id,owner_name,reason,evidence,resolves_seq) VALUES (?,?,?,?,?,?,?)",
        (
            row["id"],
            str(context.project_id),
            str(context.actor.user_id),
            context.actor.display_name,
            reason,
            command.evidence,
            last[0] if matches and last else None,
        ),
    )
    # Reconciliation is evidence only. It never manufactures accepted reservation quantities.
    tx.execute(
        "INSERT INTO exchange_events(exchange_id,project_id,phase,reason,payload_json,created_at) VALUES (?,?,?,?,?,?)",
        (
            row["id"],
            str(context.project_id),
            row["phase"],
            reason,
            command.model_dump_json(),
            context.now.isoformat(),
        ),
    )
    return MutationResult(
        object_type="exchange", object_id=UUID(row["id"]), exchange_id=UUID(row["id"])
    )


def summary(tx, pid, kind, row):
    if kind == "exchange":
        return ObjectSummary(
            id=row["id"],
            project_id=pid,
            kind=kind,
            title=f"{row['system']} · {row['action']} · #{row['seq']}",
            state=row["phase"],
            version=row["source_sequence"] or 1,
            next_actions=["exchange.query", "exchange.dispatch"]
            if row["phase"] not in {"accepted", "posted"}
            and row["action"]
            in {
                "freeze.request",
                "stock_basis.reconcile",
                "shipment.request",
                "eco.switch",
                "reservation.request",
                "source.pull",
                "production.start",
                "production.interrupt",
                "production.resume",
            }
            else [],
        )
    req = own(tx, "requirements", pid, row["requirement_id"])
    lot = own(tx, "material_lots", pid, row["material_lot_id"])
    return ObjectSummary(
        id=row["id"],
        project_id=pid,
        kind=kind,
        title=f"{req['material_id']} · {lot['lot_id']} 预留",
        state="accepted" if row["authority_receipt_id"] else "requested",
        quantity=amount(row["requested_atoms"], req["scale"]),
        unit=row["unit"],
        version=row["source_version"],
    )


def detail(tx, pid, kind, ident):
    table = "exchanges" if kind == "exchange" else "reservations"
    row = tx.execute(
        f"SELECT * FROM {table} WHERE project_id=? AND id=?", (str(pid), str(ident))
    ).fetchone()
    if not row:
        return None
    relations = []
    if kind == "exchange":
        received = tx.execute(
            "SELECT payload_json FROM exchange_receipts WHERE exchange_id=? ORDER BY seq DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        receipt = None
        try:
            raw_receipt = row["receipt_json"] or (received[0] if received else None)
            if raw_receipt:
                receipt = ExternalReceipt.model_validate_json(raw_receipt)
        except (ValidationError, ValueError):
            pass
        if receipt is not None:
            receipt = (
                public_receipt(receipt) if receipt_scope(tx, row, receipt) else None
            )
        req = (
            ExternalRequest.model_validate_json(row["request_json"])
            if row["action"]
            in {
                "freeze.request",
                "stock_basis.reconcile",
                "shipment.request",
                "eco.switch",
                "reservation.request",
                "production.start",
                "production.interrupt",
                "production.resume",
            }
            else None
        )
        saved = tx.execute(
            "SELECT payload_json FROM exchange_events WHERE exchange_id=? AND json_type(payload_json,'$.records')='array' ORDER BY seq DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        inbound = None
        if saved and row["action"] == "source.pull":
            from .imports import record_adapter

            try:
                stored_records = json.loads(saved[0])["records"]
                pull = PullSource.model_validate_json(row["request_json"])
                if len(stored_records) == 1:
                    stored = record_adapter.validate_python(stored_records[0])
                    record_scope(
                        tx,
                        pid,
                        stored,
                        object_type=pull.object_type,
                        system=pull.system,
                        external_id=pull.external_id,
                        mode=row["mode"],
                    )
                    inbound = stored.model_dump(mode="json")
            except (DomainError, ValidationError, ValueError, KeyError):
                pass
        proof_value = None
        if row["action"] == "stock_basis.reconcile":
            saved_proof = tx.execute(
                "SELECT proof_json FROM stock_basis_proofs WHERE exchange_id=? AND project_id=?",
                (row["id"], str(pid)),
            ).fetchone()
            if saved_proof:
                from .exchange_models import StockBasisProof
                from .stock_proofs import validate

                try:
                    candidate = StockBasisProof.model_validate_json(saved_proof[0])
                    validate(tx, pid, row, candidate, row["mode"])
                    proof_value = candidate
                except (DomainError, ValidationError, ValueError):
                    pass
        value = ExchangeValue(
            stock_basis_proof=proof_value,
            discrepancies=[
                {**dict(r), "reason": public_reason(r["reason"])}
                for r in tx.execute(
                    "SELECT seq sequence,owner_id,owner_name,reason,evidence,resolves_seq resolves_sequence FROM exchange_discrepancies WHERE exchange_id=? ORDER BY seq DESC LIMIT 100",
                    (row["id"],),
                )
            ],
            action=row["action"],
            policy_action=row["policy_action"],
            source=inbound["source"] if inbound else None,
            source_object_type=inbound["object_type"] if inbound else None,
            system=row["system"],
            business_key=row["business_key"],
            mode=row["mode"],
            phase=row["phase"],
            requested=(
                str(req.typed_payload.remaining_quantity)
                if isinstance(req.typed_payload, EcoSwitchPayload)
                else str(req.typed_payload.quantity)
                if isinstance(req.typed_payload, (ReservePayload, ShipPayload))
                else str(len(req.typed_payload.units))
                if isinstance(req.typed_payload, StartPayload)
                else "1"
            )
            if req
            else "0",
            accepted=(
                amount(
                    own(tx, "reservations", pid, row["reservation_id"])[
                        "confirmed_atoms"
                    ],
                    req.typed_payload.scale,
                )
                if isinstance(req.typed_payload, ReservePayload)
                else str(receipt.accepted_quantity)
                if receipt and row["phase"] == "accepted"
                else "0"
            )
            if req
            else "0",
            rejected=str(receipt.rejected_quantity) if receipt else "0",
            unit=req.typed_payload.unit
            if req and isinstance(req.typed_payload, (ReservePayload, ShipPayload))
            else "piece"
            if req
            else "",
            reason=public_reason(row["reason"]),
            events=[
                {**dict(r), "reason": public_reason(r["reason"])}
                for r in tx.execute(
                    "SELECT seq sequence,phase,reason FROM exchange_events WHERE exchange_id=? ORDER BY seq DESC LIMIT 100",
                    (row["id"],),
                )
            ],
            receipt=receipt,
            reservation_id=row["reservation_id"],
        )
        if row["reservation_id"]:
            relations.append(
                ObjectRelation(
                    relation="reservation",
                    project_id=pid,
                    kind="reservation",
                    id=row["reservation_id"],
                )
            )
    else:
        req = own(tx, "requirements", pid, row["requirement_id"])
        value = ReservationValue(
            requirement_id=row["requirement_id"],
            work_order_id=row["work_order_id"],
            material_lot_id=row["material_lot_id"],
            requested=amount(row["requested_atoms"], req["scale"]),
            confirmed=amount(row["confirmed_atoms"], req["scale"]),
            remaining=amount(
                row["requested_atoms"] - row["confirmed_atoms"], req["scale"]
            ),
            unit=row["unit"],
            source_version=row["source_version"],
            authority_receipt_id=row["authority_receipt_id"],
            exchange_id=row["exchange_id"],
        )
        relations = [
            ObjectRelation(relation=k, project_id=pid, kind=k, id=row[field])
            for k, field in [
                ("requirement", "requirement_id"),
                ("work_order", "work_order_id"),
                ("material_lot", "material_lot_id"),
                ("exchange", "exchange_id"),
            ]
        ]
    from .freeze import audit_evidence as freeze_audit

    return ObjectDetail(
        summary=summary(tx, pid, kind, row),
        value=value,
        relations=relations,
        history=_history_rows(
            tx.execute(
                "SELECT * FROM audit_events WHERE project_id=? AND object_id=? ORDER BY id",
                (str(pid), str(ident)),
            ).fetchall(),
            evidence_projector=(
                lambda event, payload: freeze_audit(tx, pid, event, payload)
            )
            if kind == "exchange" and row["action"] == "freeze.request"
            else None,
        ),
        evidence=[],
    )


for model, roles, handler in [
    (RequestReservation, {"planner"}, request_reservation),
    (DispatchExchange, ALL_ROLES, prepare_io),
    (QueryExchange, ALL_ROLES, prepare_io),
    (PullSource, ALL_ROLES, prepare_io),
    (ImportSource, ALL_ROLES, import_source),
    (ImportFile, ALL_ROLES, import_source),
    (ReconcileExchange, ALL_ROLES, reconcile),
]:
    COMMAND_REGISTRY.register(model, roles=roles, qualifications=set(), handler=handler)


def register_reader(kind, table, model):
    def count(tx, pid):
        return tx.execute(
            f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (str(pid),)
        ).fetchone()[0]

    def page(tx, pid, limit, offset):
        return [
            summary(tx, pid, kind, r)
            for r in tx.execute(
                (
                    "SELECT * FROM exchanges WHERE project_id=? ORDER BY seq LIMIT ? OFFSET ?"
                    if kind == "exchange"
                    else "SELECT r.* FROM reservations r JOIN exchanges e ON e.id=r.exchange_id WHERE r.project_id=? ORDER BY e.seq LIMIT ? OFFSET ?"
                ),
                (str(pid), limit, offset),
            )
        ]

    OBJECT_REGISTRY.register(
        ObjectKind(kind),
        model,
        count=count,
        summaries=page,
        detail=lambda tx, pid, ident: detail(tx, pid, kind, ident),
    )


register_reader("exchange", "exchanges", ExchangeValue)
register_reader("reservation", "reservations", ReservationValue)
