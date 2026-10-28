"""Durable outbox: intent commit, independent authority I/O, then validated apply."""

import base64
import binascii
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import ValidationError

from .adapters.mock import MockAuthorityAdapter, canonical, digest
from .authorization import require_project
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
)
from .imports import ingest, parse_import, validate_record
from .orders import _history_rows, own
from .queries import OBJECT_REGISTRY
from .supply import amount, atoms, available, current_plan_id, fail

SOURCE_POLICIES = {
    "receipt": "supply.receive",
    "iqc": "supply.inspect",
    "customer_approval": "engineering.customer_approval",
}
ALL_ROLES = {
    "project_owner",
    "engineering",
    "planner",
    "supply",
    "production",
    "quality",
    "warehouse",
}


def event(tx, row, phase, reason, payload=None):
    tx.execute(
        "INSERT INTO exchange_events(exchange_id,project_id,phase,reason,payload_json,created_at) VALUES (?,?,?,?,?,?)",
        (
            row["id"],
            row["project_id"],
            phase,
            reason,
            canonical(payload or {}),
            datetime.now(UTC).isoformat(),
        ),
    )
    tx.execute(
        "UPDATE exchanges SET phase=?,reason=? WHERE id=?", (phase, reason, row["id"])
    )


def authorize_policy(tx, actor, project_id, policy):
    require_project(tx, actor, project_id)
    grant = tx.execute(
        "SELECT * FROM project_grants WHERE project_id=? AND user_id=? AND active=1",
        (str(project_id), str(actor.user_id)),
    ).fetchone()
    entry = COMMAND_REGISTRY.registration(policy)
    if actor.read_only or not COMMAND_REGISTRY.permits(
        entry, json.loads(grant["roles_json"]), json.loads(grant["qualifications_json"])
    ):
        raise DomainError(
            "FORBIDDEN", 403, "Initiating business action permission denied"
        )


class ExchangeService:
    def __init__(self, workflow):
        self.workflow = workflow
        self.adapter = None
        # A production configuration can be available locally while its source is unconnected.
        if workflow.store.dataset["mode"] in {"test", "demo"}:
            self.adapter = MockAuthorityAdapter(
                workflow.store.authority_database_path, workflow.store.dataset["id"]
            )

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
        if request.project_id != context.project_id:
            fail("Exchange project mismatch")
        tx.execute(
            """INSERT INTO exchanges(id,project_id,reservation_id,action,policy_action,system,business_key,mode,request_json,request_hash,phase,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(request.id),
                str(context.project_id),
                str(request.typed_payload.reservation_id),
                request.action,
                request.action,
                request.system,
                request.business_key,
                self.adapter.mode if self.adapter else "unavailable",
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
        receipt, records, problem = None, None, None
        rejected_boundary = False
        try:
            if self.adapter is None:
                raise DomainError(
                    "SOURCE_UNAVAILABLE", 503, "Configured authority is not connected"
                )
            if row["action"] == "source.pull":
                pull = PullSource.model_validate_json(row["request_json"])
                snapshot = self.adapter.snapshot(pull.system, pull.object_type)
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
                    records[0].source.mode != self.adapter.mode
                    or records[0].source.system.strip().casefold()
                    != pull.system.strip().casefold()
                ):
                    raise DomainError(
                        "SOURCE_DISCREPANCY", 409, "Adapter provenance mismatch"
                    )
            else:
                request = ExternalRequest.model_validate_json(row["request_json"])
                # Even the first dispatch queries; a crash after submission can never blindly resend.
                receipt = self.adapter.query(request.system, request.business_key)
                if receipt is None and isinstance(command, DispatchExchange):
                    receipt = self.adapter.submit(request)
                elif receipt is None:
                    problem = "No authoritative operation found; dispatch may now retry the same business key"
                if receipt is not None:
                    receipt = ExternalReceipt.model_validate(
                        receipt.model_dump(mode="json")
                        if isinstance(receipt, ExternalReceipt)
                        else receipt
                    )
        except (TimeoutError, OSError) as exc:
            receipt, records = None, None
            problem = str(exc)
        except ValidationError:
            receipt, records = None, None
            problem = "Authority response schema invalid"
            rejected_boundary = True
        except DomainError as exc:
            receipt, records = None, None
            problem = exc.message
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
                datetime.now(UTC),
                Dataset.model_validate(self.workflow.store.dataset),
                self,
            )
            if receipt is not None:
                if receipt.business_key != row["business_key"]:
                    tx.execute(
                        "INSERT OR IGNORE INTO exchange_receipts(exchange_id,project_id,receipt_id,payload_json,valid,reason) VALUES (?,?,?,?,0,?)",
                        (
                            row["id"],
                            str(project_id),
                            str(receipt.receipt_id),
                            receipt.model_dump_json(),
                            "Receipt business key mismatch",
                        ),
                    )
                    self._reject(tx, context, row, "Receipt business key mismatch")
                else:
                    self.apply(tx, context, receipt)
            elif records is not None:
                event(
                    tx,
                    row,
                    "received",
                    "Authoritative source received",
                    {"records": [r.model_dump(mode="json") for r in records]},
                )
                tx.execute("SAVEPOINT inbound_batch")
                try:
                    event(tx, row, "received", "Authoritative source received")
                    ingest(tx, context, records, trusted=True)
                    event(
                        tx,
                        row,
                        "validated",
                        "Source identity and domain detail validated",
                    )
                    event(tx, row, "approved", "External actor and signature retained")
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
    def _reject(tx, context, row, reason):
        event(tx, row, "rejected", reason)
        tx.execute(
            "INSERT INTO exchange_discrepancies(exchange_id,project_id,owner_id,owner_name,reason,evidence) VALUES (?,?,?,?,?,?)",
            (
                row["id"],
                str(context.project_id),
                str(context.actor.user_id),
                context.actor.display_name,
                reason,
                "Receipt/source retained for reconciliation",
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
        request = ExternalRequest.model_validate_json(row["request_json"])
        payload = request.typed_payload
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
    if row["action"] not in {"reservation.request", "source.pull"}:
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
    for row in records:
        if row.object_type != command.object_type:
            raise DomainError("IMPORT_INVALID", 422, "Mixed import object types")
        validate_record(row, context, trusted=False)
    result = ingest(tx, context, records)[-1]
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
            and row["action"] in {"reservation.request", "source.pull"}
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
        receipt = (
            ExternalReceipt.model_validate_json(row["receipt_json"])
            if row["receipt_json"]
            else ExternalReceipt.model_validate_json(received[0])
            if received
            else None
        )
        req = (
            ExternalRequest.model_validate_json(row["request_json"])
            if row["action"] == "reservation.request"
            else None
        )
        saved = tx.execute(
            "SELECT payload_json FROM exchange_events WHERE exchange_id=? AND json_type(payload_json,'$.records')='array' ORDER BY seq DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        inbound = json.loads(saved[0])["records"][0] if saved else None
        value = ExchangeValue(
            discrepancies=[
                dict(r)
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
            requested=str(req.typed_payload.quantity) if req else "0",
            accepted=amount(
                own(tx, "reservations", pid, row["reservation_id"])["confirmed_atoms"],
                req.typed_payload.scale,
            )
            if req
            else "0",
            rejected=str(receipt.rejected_quantity) if receipt else "0",
            unit=req.typed_payload.unit if req else "",
            reason=row["reason"],
            events=[
                dict(r)
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
    return ObjectDetail(
        summary=summary(tx, pid, kind, row),
        value=value,
        relations=relations,
        history=_history_rows(
            tx.execute(
                "SELECT * FROM audit_events WHERE project_id=? AND object_id=? ORDER BY id",
                (str(pid), str(ident)),
            ).fetchall()
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
