"""Stateful simulator. These boundary methods are server/fixture APIs, never HTTP commands."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from ..contracts import DomainError
from ..exchange_models import (
    AuthoritySnapshot,
    ExternalReceipt,
    ExternalRequest,
    InboundApproval,
    InboundIQC,
    InboundReceipt,
    ResumePayload,
    StartPayload,
    StopPayload,
)
from ..execution_models import sn_key
from ..supply import amount, atoms
from .mock_store import MockStore


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class MockAuthorityAdapter:
    mode = "mock"

    def __init__(self, database_path, dataset_id):
        self.store = MockStore(database_path, dataset_id)

    @staticmethod
    def _system(system):
        if system.strip().casefold() != "erp":
            raise DomainError("SOURCE_UNAVAILABLE", 503, "Source is not connected")
        return "erp"

    def configure_fault(self, name, value=None):
        if name not in {
            "timeout_after_commit",
            "reject",
            "partial_quantity",
            "duplicate",
            "stale_sequence",
            "wrong_unit",
            "changed_detail_same_total",
            "none",
        }:
            raise ValueError("unknown authority fault")
        with self.store.transaction(write=True) as tx:
            tx.execute("DELETE FROM faults")
            if name != "none":
                tx.execute("INSERT INTO faults VALUES (?,?)", (name, value))

    def submit(self, request: ExternalRequest) -> ExternalReceipt:
        request = ExternalRequest.model_validate(request.model_dump(mode="json"))
        system = self._system(request.system)
        body = request.model_dump(mode="json")
        h = digest(body)
        with self.store.transaction(write=True) as tx:
            prior = tx.execute(
                "SELECT * FROM authority_operations WHERE system=? AND business_key=?",
                (system, request.business_key),
            ).fetchone()
            if prior:
                if prior["request_hash"] != h:
                    raise DomainError(
                        "IDEMPOTENCY_CONFLICT",
                        409,
                        "Business key has different payload",
                    )
                return ExternalReceipt.model_validate_json(prior["receipt_json"])
            sequence = tx.execute(
                "INSERT INTO authority_operations(system,business_key,request_hash,request_json) VALUES (?,?,?,?)",
                (system, request.business_key, h, canonical(body)),
            ).lastrowid
            fault = tx.execute("SELECT name,value FROM faults").fetchone()
            fault_name, fault_value = tuple(fault) if fault else (None, None)
            if request.action == "reservation.request":
                result = self._reserve(
                    tx, request, h, sequence, fault_name, fault_value
                )
            elif request.action in {
                "production.start",
                "production.interrupt",
                "production.resume",
            }:
                result = self._submit_execution(tx, request, h, sequence, fault_name)
                tx.execute(
                    "UPDATE authority_operations SET receipt_json=? WHERE seq=?",
                    (result.model_dump_json(), sequence),
                )
            else:
                raise DomainError(
                    "UNSUPPORTED_ACTION", 422, "Unknown authority operation"
                )
        # The operation committed before a response can be lost.
        if fault_name == "timeout_after_commit":
            raise TimeoutError("authority committed; reply lost")
        return result

    def _reserve(self, tx, request, h, sequence, fault_name, fault_value):
        payload = request.typed_payload
        lot = tx.execute(
            "SELECT * FROM inventory WHERE lot_id=?", (str(payload.lot_id),)
        ).fetchone()
        requested = atoms(payload.quantity, payload.unit, payload.unit, payload.scale)
        eligible = (
            lot
            and (
                lot["project_id"],
                lot["material_id"],
                lot["owner_id"],
                lot["unit"],
                lot["scale"],
            )
            == (
                str(request.project_id),
                payload.material_id,
                payload.owner_id,
                payload.unit,
                payload.scale,
            )
            and lot["state"] == "active"
            and lot["expiry"] >= datetime.now(UTC).date().isoformat()
        )
        accepted, error = 0, "Ineligible or insufficient quality stock"
        target = requested
        if fault_name == "partial_quantity":
            target = min(
                requested,
                atoms(Decimal(fault_value), payload.unit, payload.unit, payload.scale),
            )
        if (
            eligible
            and 0 < target <= lot["qualified"] - lot["reserved"]
            and fault_name != "reject"
        ):
            accepted, error = target, None
            tx.execute(
                "UPDATE inventory SET reserved=reserved+?,version=version+1 WHERE lot_id=?",
                (accepted, str(payload.lot_id)),
            )
            tx.execute(
                "INSERT INTO authority_reservations VALUES (?,?,?,?,?)",
                (
                    str(payload.reservation_id),
                    str(payload.lot_id),
                    str(request.project_id),
                    request.business_key,
                    accepted,
                ),
            )
        receipt = ExternalReceipt(
            receipt_id=uuid4(),
            business_key=request.business_key,
            request_hash=h,
            source_object_id=str(payload.reservation_id),
            source_version=request.source_version,
            sequence=sequence,
            phase="accepted" if accepted else "rejected",
            accepted_quantity=amount(accepted, payload.scale),
            rejected_quantity=amount(requested - accepted, payload.scale),
            details=[
                {
                    "key": str(payload.requirement_id),
                    "lot_id": payload.lot_id,
                    "owner_id": payload.owner_id,
                    "quantity": amount(accepted, payload.scale),
                    "unit": payload.unit,
                }
            ],
            occurred_at=datetime.now(UTC),
            error=error,
        )
        if fault_name == "stale_sequence":
            receipt.sequence = 0
        if fault_name == "wrong_unit":
            receipt.details[0].unit = "wrong-unit"
        if fault_name == "changed_detail_same_total":
            receipt.details[0].key = str(uuid4())
        tx.execute(
            "UPDATE authority_operations SET receipt_json=? WHERE seq=?",
            (receipt.model_dump_json(), sequence),
        )
        return receipt

    def _submit_execution(self, tx, request, h, sequence, fault_name):
        payload = request.typed_payload
        accepted = False
        reason = "Authority production scope rejected"
        details = []
        if isinstance(payload, StartPayload):
            wo = tx.execute(
                "SELECT * FROM authority_work_orders WHERE project_id=? AND work_order_id=?",
                (str(request.project_id), str(payload.work_order_id)),
            ).fetchone()
            if wo and (wo["revision_id"], wo["total_units"], wo["trial_units"]) != (
                str(payload.revision_id),
                payload.work_order_quantity,
                payload.trial_quantity,
            ):
                reason = "Authority work order basis changed"
            elif (not wo or wo["state"] == "running") and fault_name != "reject":
                count = len(payload.units)
                used = wo["started_units"] if wo else 0
                trial_used = wo["started_trial"] if wo else 0
                repeated = any(
                    tx.execute(
                        "SELECT 1 FROM authority_start_units WHERE unit_id=? OR sn_key=?",
                        (str(uid), sn_key(sn)),
                    ).fetchone()
                    for uid, sn in payload.units
                )
                if (
                    not repeated
                    and used + count <= payload.work_order_quantity
                    and (
                        payload.mode != "trial"
                        or trial_used + count <= payload.trial_quantity
                    )
                ):
                    if not wo:
                        tx.execute(
                            "INSERT INTO authority_work_orders VALUES (?,?,?,?,?,0,0,'running')",
                            (
                                str(request.project_id),
                                str(payload.work_order_id),
                                str(payload.revision_id),
                                payload.work_order_quantity,
                                payload.trial_quantity,
                            ),
                        )
                    tx.execute(
                        "UPDATE authority_work_orders SET started_units=started_units+?,started_trial=started_trial+? WHERE project_id=? AND work_order_id=?",
                        (
                            count,
                            count if payload.mode == "trial" else 0,
                            str(request.project_id),
                            str(payload.work_order_id),
                        ),
                    )
                    for uid, sn in payload.units:
                        tx.execute(
                            "INSERT INTO authority_start_units VALUES (?,?,?,?,?,?)",
                            (
                                str(request.project_id),
                                str(payload.work_order_id),
                                str(uid),
                                sn_key(sn),
                                payload.mode,
                                str(payload.start_id),
                            ),
                        )
                        details.append(
                            {
                                "key": str(uid),
                                "unit_id": uid,
                                "sn": sn,
                                "state": "running",
                            }
                        )
                    accepted = True
            source_object = str(payload.start_id)
            quantity = str(len(payload.units))
        elif isinstance(payload, StopPayload):
            wo = tx.execute(
                "SELECT * FROM authority_work_orders WHERE project_id=? AND work_order_id=?",
                (str(request.project_id), str(payload.work_order_id)),
            ).fetchone()
            if (
                wo
                and wo["started_units"] > 0
                and wo["state"] == "running"
                and fault_name != "reject"
            ):
                tx.execute(
                    "INSERT INTO authority_interruptions VALUES (?,?,?,?,0)",
                    (
                        str(payload.interruption_id),
                        str(request.project_id),
                        str(payload.work_order_id),
                        1,
                    ),
                )
                tx.execute(
                    "UPDATE authority_work_orders SET state='stopped' WHERE project_id=? AND work_order_id=?",
                    (str(request.project_id), str(payload.work_order_id)),
                )
                accepted = True
            source_object = str(payload.interruption_id)
            quantity = "1"
        elif isinstance(payload, ResumePayload):
            stop = tx.execute(
                "SELECT * FROM authority_interruptions WHERE id=? AND project_id=? AND work_order_id=?",
                (
                    str(payload.interruption_id),
                    str(request.project_id),
                    str(payload.work_order_id),
                ),
            ).fetchone()
            wo = tx.execute(
                "SELECT * FROM authority_work_orders WHERE project_id=? AND work_order_id=?",
                (str(request.project_id), str(payload.work_order_id)),
            ).fetchone()
            if (
                stop
                and stop["stopped"]
                and not stop["resumed"]
                and wo
                and wo["state"] == "stopped"
                and fault_name != "reject"
            ):
                tx.execute(
                    "UPDATE authority_interruptions SET resumed=1 WHERE id=?",
                    (str(payload.interruption_id),),
                )
                tx.execute(
                    "UPDATE authority_work_orders SET state='running' WHERE project_id=? AND work_order_id=?",
                    (str(request.project_id), str(payload.work_order_id)),
                )
                accepted = True
            source_object = str(payload.interruption_id)
            quantity = "1"
        else:
            raise DomainError("UNSUPPORTED_ACTION", 422, "Unknown authority operation")
        receipt = ExternalReceipt(
            receipt_id=uuid4(),
            business_key=request.business_key,
            request_hash=h,
            source_object_id=source_object,
            source_version=request.source_version,
            sequence=sequence,
            phase="accepted" if accepted else "rejected",
            accepted_quantity=quantity if accepted else "0",
            rejected_quantity="0" if accepted else quantity,
            details=details,
            occurred_at=datetime.now(UTC),
            error=None if accepted else reason,
        )
        if fault_name == "stale_sequence":
            receipt.sequence = 0
        if fault_name == "wrong_unit" and receipt.details:
            receipt.details[0].sn = "wrong-SN"
        if fault_name == "changed_detail_same_total" and receipt.details:
            receipt.details[0].key = str(uuid4())
        return receipt

    def query(self, system, business_key):
        system = self._system(system)
        with self.store.transaction() as tx:
            row = tx.execute(
                "SELECT receipt_json FROM authority_operations WHERE system=? AND business_key=?",
                (system, business_key),
            ).fetchone()
            return ExternalReceipt.model_validate_json(row[0]) if row else None

    def snapshot(self, system, object_type):
        system = self._system(system)
        with self.store.transaction() as tx:
            rows = tx.execute(
                "SELECT seq,payload_json FROM source_events WHERE system=? AND object_type=? ORDER BY seq LIMIT 501",
                (system, object_type),
            ).fetchall()
            if len(rows) > 500:
                raise DomainError(
                    "SOURCE_LIMIT",
                    409,
                    "Source snapshot exceeds bounded batch; configure a narrower source",
                )
            return AuthoritySnapshot(
                system=system,
                object_type=object_type,
                sequence=max((r["seq"] for r in rows), default=0),
                records=[json.loads(r["payload_json"]) for r in rows],
            )

    @staticmethod
    def _source(object_type, external_id, signature):
        now = datetime.now(UTC).isoformat()
        return {
            "system": "erp",
            "object_type": object_type,
            "external_id": external_id,
            "version": 1,
            "mode": "mock",
            "occurred_at": now,
            "collected_at": now,
            "evidence": signature,
        }

    @staticmethod
    def _append(tx, record):
        body = record.model_dump(mode="json")
        key = ("erp", record.object_type, record.source.external_id.strip())
        prior = tx.execute(
            "SELECT payload_json FROM source_events WHERE system=? AND object_type=? AND external_id=?",
            key,
        ).fetchone()
        if prior:
            raise DomainError("SOURCE_CONFLICT", 409, "External event already recorded")
        tx.execute(
            "INSERT INTO source_events(system,object_type,external_id,project_id,version,payload_json,payload_hash) VALUES (?,?,?,?,?,?,?)",
            (
                *key,
                str(record.project_id),
                record.source.version,
                canonical(body),
                digest(body),
            ),
        )

    def receive(
        self,
        *,
        project_id,
        external_id,
        commitment_id,
        lot_id,
        material_id,
        owner_id,
        quantity,
        unit,
        scale,
        expiry,
        external_actor,
        signature,
    ):
        record = InboundReceipt(
            project_id=project_id,
            source=self._source("receipt", external_id, signature),
            external_actor=external_actor,
            signature=signature,
            commitment_id=commitment_id,
            material_lot_id=lot_id,
            quantity=quantity,
            unit=unit,
        )
        q = atoms(record.quantity, unit, unit, scale)
        with self.store.transaction(write=True) as tx:
            old = tx.execute(
                "SELECT * FROM inventory WHERE lot_id=?", (str(lot_id),)
            ).fetchone()
            identity = (str(project_id), material_id, owner_id, unit, scale, expiry)
            if (
                old
                and tuple(
                    old[k]
                    for k in (
                        "project_id",
                        "material_id",
                        "owner_id",
                        "unit",
                        "scale",
                        "expiry",
                    )
                )
                != identity
            ):
                raise DomainError(
                    "STOCK_IDENTITY_CONFLICT", 409, "Lot identity changed"
                )
            if old and old["received"] > 2**63 - 1 - q:
                raise DomainError(
                    "PRECONDITION_FAILED",
                    409,
                    "Authority stock exceeds integer atom range",
                )
            self._append(tx, record)
            if old:
                tx.execute(
                    "UPDATE inventory SET received=received+?,version=version+1 WHERE lot_id=?",
                    (q, str(lot_id)),
                )
            else:
                tx.execute(
                    "INSERT INTO inventory(lot_id,project_id,material_id,owner_id,unit,scale,expiry,state,received) VALUES (?,?,?,?,?,?,?,?,?)",
                    (str(lot_id), *identity, "active", q),
                )
        return record

    def inspect(
        self,
        *,
        project_id,
        external_id,
        receipt_external_id,
        accepted,
        rejected,
        external_actor,
        signature,
        manual_iqc_id=None,
    ):
        record = InboundIQC(
            project_id=project_id,
            source=self._source("iqc", external_id, signature),
            external_actor=external_actor,
            signature=signature,
            receipt_system="erp",
            receipt_external_id=receipt_external_id,
            accepted=accepted,
            rejected=rejected,
            evidence=signature,
            manual_iqc_id=manual_iqc_id,
        )
        with self.store.transaction(write=True) as tx:
            receipt = tx.execute(
                "SELECT payload_json FROM source_events WHERE object_type='receipt' AND external_id=? AND project_id=?",
                (receipt_external_id, str(project_id)),
            ).fetchone()
            if not receipt:
                raise DomainError("NOT_FOUND", 404, "External receipt missing")
            received = InboundReceipt.model_validate_json(receipt[0])
            lot = tx.execute(
                "SELECT * FROM inventory WHERE lot_id=?",
                (str(received.material_lot_id),),
            ).fetchone()
            checked = Decimal(0)
            for row in tx.execute(
                "SELECT payload_json FROM source_events WHERE object_type='iqc' AND project_id=?",
                (str(project_id),),
            ):
                prior = InboundIQC.model_validate_json(row[0])
                if prior.receipt_external_id == receipt_external_id:
                    checked += prior.accepted + prior.rejected
            if (
                record.accepted + record.rejected <= 0
                or checked + record.accepted + record.rejected > received.quantity
            ):
                raise DomainError(
                    "PRECONDITION_FAILED", 409, "External inspection exceeds receipt"
                )
            self._append(tx, record)
            tx.execute(
                "UPDATE inventory SET qualified=qualified+?,version=version+1 WHERE lot_id=?",
                (
                    atoms(record.accepted, lot["unit"], lot["unit"], lot["scale"]),
                    lot["lot_id"],
                ),
            )
        return record

    def customer_approval(
        self,
        *,
        project_id,
        external_id,
        revision_id,
        customer_id,
        decision,
        external_actor,
        signature,
    ):
        record = InboundApproval(
            project_id=project_id,
            source=self._source("customer_approval", external_id, signature),
            external_actor=external_actor,
            signature=signature,
            revision_id=revision_id,
            customer_id=customer_id,
            decision=decision,
            evidence=signature,
        )
        with self.store.transaction(write=True) as tx:
            self._append(tx, record)
        return record

    def balance(self, lot_id):
        with self.store.transaction() as tx:
            row = tx.execute(
                "SELECT * FROM inventory WHERE lot_id=?", (str(lot_id),)
            ).fetchone()
            return (
                amount(row["qualified"] - row["reserved"], row["scale"]) if row else "0"
            )

    def operation_count(self, business_key=None):
        with self.store.transaction() as tx:
            return tx.execute(
                "SELECT COUNT(*) FROM authority_operations"
                + (" WHERE business_key=?" if business_key else ""),
                (str(business_key),) if business_key else (),
            ).fetchone()[0]
