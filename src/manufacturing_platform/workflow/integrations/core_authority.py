"""Immutable existing exchange wire receipts backed by core source effects."""

from uuid import NAMESPACE_URL, uuid5

from ..adapters.mock import digest
from ..exchange_models import ExternalReceipt, ReceiptDetail, StockBasis
from .core_guards import require


WIRE_DDL = """CREATE TABLE IF NOT EXISTS core_authority_receipts(
 project_id TEXT NOT NULL, business_key TEXT NOT NULL, request_hash TEXT NOT NULL,
 request_json TEXT NOT NULL, receipt_json TEXT NOT NULL, PRIMARY KEY(project_id,business_key))"""


def record_wires(tx, operation, receipt, requests, observations):
    tx.execute(WIRE_DDL)
    for action in ("UPDATE", "DELETE"):
        tx.execute(
            f"CREATE TRIGGER IF NOT EXISTS core_authority_no_{action} BEFORE {action} ON core_authority_receipts BEGIN SELECT RAISE(ABORT,'immutable authority receipt'); END"
        )
    tx.execute(
        "CREATE TRIGGER IF NOT EXISTS core_authority_no_replace BEFORE INSERT ON core_authority_receipts WHEN EXISTS(SELECT 1 FROM core_authority_receipts WHERE project_id=NEW.project_id AND business_key=NEW.business_key) BEGIN SELECT RAISE(ABORT,'immutable authority receipt'); END"
    )
    for request in requests:
        p = request.typed_payload
        accepted = receipt.phase == "accepted"
        quantity, details = 0, []
        if p.kind == "reserve":
            allocations = [
                a
                for a in operation.payload.allocations
                if a.material_lot_id == p.lot_id
            ]
            require(
                not accepted
                or sum(a.amount.quantity for a in allocations) == p.quantity,
                "Prepared allocation quantity differs",
            )
            basis = []
            if accepted:
                grouped = {}
                for a in allocations:
                    qualification = observations.fact(a.qualification).payload
                    source = observations.fact(qualification.receipt)
                    key = source.source_key.model_dump_json()
                    if key in grouped:
                        previous = grouped[key]
                        grouped[key] = previous.model_copy(
                            update={"quantity": previous.quantity + a.amount.quantity}
                        )
                    else:
                        grouped[key] = StockBasis(
                            project_id=operation.project_id,
                            lot_id=p.lot_id,
                            owner_id=p.owner_id,
                            unit=p.unit,
                            system=source.source.system,
                            external_id=source.source.external_id,
                            source_version=source.source.version,
                            source_quantity=str(source.payload.amount.quantity),
                            quantity=str(a.amount.quantity),
                        )
                basis = list(grouped.values())
            source_id, quantity = p.reservation_id, p.quantity
            details = [
                ReceiptDetail(
                    key=str(p.requirement_id),
                    lot_id=p.lot_id,
                    owner_id=p.owner_id,
                    quantity=str(p.quantity if accepted else 0),
                    unit=p.unit,
                    stock_basis=basis,
                )
            ]
        elif p.kind == "eco_switch":
            from ..eco import switch_receipt_details
            from ..exchange_models import EcoReceiptDetail

            source_id, quantity = p.switch_id, p.remaining_quantity
            details = (
                [EcoReceiptDetail(**d) for d in switch_receipt_details(p)]
                if accepted
                else []
            )
        elif p.kind == "ship":
            from ..exchange_models import ShipmentReceiptDetail

            source_id, quantity = p.shipment_id, p.quantity
            boxes = {uid: box.box_id for box in p.boxes for uid in box.unit_ids}
            details = (
                [
                    ShipmentReceiptDetail(
                        key=str(uid),
                        unit_id=uid,
                        sn=sn,
                        work_order_id=wid,
                        order_line_id=p.order_line_id,
                        box_id=boxes.get(uid),
                    )
                    for uid, sn, wid in p.units
                ]
                if accepted
                else []
            )
        elif p.kind in {"stop", "resume"}:
            source_id, quantity = p.interruption_id, 1
            if p.kind == "resume" and accepted:
                from ..exchange_models import ControlReceiptDetail

                details = [
                    ControlReceiptDetail(
                        key=str(p.interruption_id),
                        work_order_id=p.work_order_id,
                        scope=p.scope,
                        state="partial" if p.scope == "trial" else "running",
                    )
                ]
        elif p.kind == "start":
            from ..exchange_models import UnitReceiptDetail

            source_id, quantity = p.start_id, len(p.units)
            details = (
                [
                    UnitReceiptDetail(key=str(uid), unit_id=uid, sn=sn, state="running")
                    for uid, sn in p.units
                ]
                if accepted
                else []
            )
        elif p.kind == "freeze":
            from ..freeze import receipt_details

            source_id, details = p.freeze_id, receipt_details(p)
        else:
            require(False, "Unsupported core wire")
        result = ExternalReceipt(
            receipt_id=uuid5(
                NAMESPACE_URL,
                f"{request.system}:{request.project_id}:{request.business_key}:receipt",
            ),
            business_key=request.business_key,
            request_hash=digest(request.model_dump(mode="json")),
            source_object_id=str(source_id),
            source_version=request.source_version,
            sequence=receipt.sequence,
            phase="accepted" if accepted else "rejected",
            accepted_quantity=str(quantity if accepted else 0),
            rejected_quantity=str(0 if accepted else quantity),
            details=details,
            occurred_at=receipt.occurred_at,
            error=receipt.error.message if receipt.error else None,
        )
        tx.execute(
            "INSERT INTO core_authority_receipts VALUES (?,?,?,?,?)",
            (
                str(operation.project_id),
                request.business_key,
                digest(request.model_dump(mode="json")),
                request.model_dump_json(),
                result.model_dump_json(),
            ),
        )


def next_sequence(tx):
    sequences = [
        tx.execute(
            "SELECT COALESCE(MAX(json_extract(receipt_json,'$.sequence')),0) FROM operations"
        ).fetchone()[0],
        tx.execute("SELECT COALESCE(MAX(sequence),0) FROM facts").fetchone()[0],
    ]
    if tx.execute(
        "SELECT 1 FROM sqlite_master WHERE name='core_authority_receipts'"
    ).fetchone():
        sequences.append(
            tx.execute(
                "SELECT COALESCE(MAX(json_extract(receipt_json,'$.sequence')),0) FROM core_authority_receipts"
            ).fetchone()[0]
        )
    return max(sequences) + 1


def observed_wires(registry, project_id, operation_id, system):
    with registry.workflow_store.transaction() as tx:
        from .core_preparation import bound_requests

        requests = bound_requests(tx, project_id, operation_id)
    if not requests:
        return []
    with registry.source_store(system).transaction() as tx:
        if not tx.execute(
            "SELECT 1 FROM sqlite_master WHERE name='core_authority_receipts'"
        ).fetchone():
            return []
        return [
            (
                str(request.id),
                tx.execute(
                    "SELECT receipt_json FROM core_authority_receipts WHERE project_id=? AND business_key=?",
                    (str(project_id), request.business_key),
                ).fetchone()[0],
            )
            for request in requests
        ]


class CoreAuthorityAdapter:
    """Legacy protocol facade; its query is deliberately separate from SystemAdapter."""

    mode = "mock"

    def __init__(self, system, registry):
        require(system in {"sap", "wms", "mes"}, "Unsupported core authority")
        self.system, self.registry = system, registry

    def query(self, system, business_key):
        require(system == self.system, "Authority system mismatch")
        with self.registry.source_store(system).transaction() as tx:
            if not tx.execute(
                "SELECT 1 FROM sqlite_master WHERE name='core_authority_receipts'"
            ).fetchone():
                return None
            row = tx.execute(
                "SELECT receipt_json FROM core_authority_receipts WHERE business_key=?",
                (business_key,),
            ).fetchone()
            return ExternalReceipt.model_validate_json(row[0]) if row else None

    def submit(self, request):
        from .contracts import SystemOperation
        from .core_guards import SourceSnapshot, project_guard
        from .store import canonical

        require(request.system == self.system, "Authority system mismatch")
        store = self.registry.source_store(self.system)
        with project_guard(self.registry, request.project_id):
            existing = self.query(request.system, request.business_key)
            if existing is not None:
                require(
                    existing.request_hash == digest(request.model_dump(mode="json")),
                    "Pinned authority request changed",
                )
                return existing
            with store.transaction() as tx:
                table = tx.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='core_authority_intents'"
                ).fetchone()
                prior = (
                    tx.execute(
                        "SELECT request_hash,operation_json FROM core_authority_intents WHERE business_key=?",
                        (request.business_key,),
                    ).fetchone()
                    if table
                    else None
                )
            if prior:
                require(
                    prior[0] == digest(request.model_dump(mode="json")),
                    "Pinned authority request changed",
                )
                operation = SystemOperation.model_validate_json(prior[1])
            else:
                observations = SourceSnapshot(self.registry, request.project_id)
                from ..contracts import DomainError

                try:
                    payload = self.translate(request, observations)
                except DomainError as exc:
                    if exc.status >= 500:
                        raise
                    from types import SimpleNamespace

                    with store.transaction(write=True) as tx:
                        rejection = SimpleNamespace(
                            phase="rejected",
                            sequence=next_sequence(tx),
                            occurred_at=store.clock(),
                            error=SimpleNamespace(message=exc.message),
                        )
                        native = SimpleNamespace(
                            project_id=request.project_id,
                            payload=SimpleNamespace(allocations=[]),
                        )
                        record_wires(tx, native, rejection, [request], observations)
                    return self.query(request.system, request.business_key)
                operation = SystemOperation(
                    operation_id=request.id,
                    system=self.system,
                    project_id=request.project_id,
                    payload=payload,
                )
                with store.transaction(write=True) as tx:
                    tx.execute(
                        "CREATE TABLE IF NOT EXISTS core_authority_intents(business_key TEXT PRIMARY KEY,project_id TEXT NOT NULL,request_hash TEXT NOT NULL,operation_json TEXT NOT NULL)"
                    )
                    for action in ("UPDATE", "DELETE"):
                        tx.execute(
                            f"CREATE TRIGGER IF NOT EXISTS core_intent_no_{action} BEFORE {action} ON core_authority_intents BEGIN SELECT RAISE(ABORT,'immutable authority intent'); END"
                        )
                    tx.execute(
                        "CREATE TRIGGER IF NOT EXISTS core_intent_no_replace BEFORE INSERT ON core_authority_intents WHEN EXISTS(SELECT 1 FROM core_authority_intents WHERE business_key=NEW.business_key) BEGIN SELECT RAISE(ABORT,'immutable authority intent'); END"
                    )
                    tx.execute(
                        "INSERT INTO core_authority_intents VALUES (?,?,?,?)",
                        (
                            request.business_key,
                            str(request.project_id),
                            digest(request.model_dump(mode="json")),
                            canonical(operation),
                        ),
                    )
        self.registry.adapter(self.system).execute(operation)
        receipt = self.query(request.system, request.business_key)
        require(receipt is not None, "Committed source receipt unavailable")
        return receipt

    def translate(self, request, observations):
        p = request.typed_payload
        if p.kind == "reserve":
            remaining, allocations = p.quantity, []
            for fact in observations.of_type("wms.qualification"):
                q = fact.payload
                if q.material_lot_id != p.lot_id:
                    continue
                from .core_custody import qualification_unreserved
                from .core_models import MaterialAllocation

                allocation = dict(
                    material_lot_id=p.lot_id,
                    material_id=p.material_id,
                    owner_id=p.owner_id,
                    amount=dict(quantity=str(p.quantity), unit=p.unit, scale=p.scale),
                    qualification=fact.source_key,
                )
                available = qualification_unreserved(
                    observations, MaterialAllocation(**allocation)
                )
                take = min(remaining, available)
                if take > 0:
                    allocation["amount"]["quantity"] = str(take)
                    allocations.append(allocation)
                    remaining -= take
            require(remaining == 0, "Reservation exceeds qualified available quantity")
            return dict(
                operation="wms.reserve",
                work_order_id=p.work_order_id,
                requirement_id=p.requirement_id,
                allocations=allocations,
            )
        if p.kind == "freeze":
            selected = {("unit", str(i)) for i in p.unit_ids} | {
                ("lot", str(i)) for i in p.lot_ids
            }
            current = {}
            for f in observations.of_type("mes.containment"):
                for kind, ids in (
                    ("unit", f.payload.unit_ids),
                    ("lot", f.payload.material_lot_ids),
                ):
                    for ident in ids:
                        if (kind, str(ident)) in selected:
                            current[kind, str(ident)] = f
            causes = []
            if p.state == "unfrozen":
                require(
                    set(current) == selected,
                    "Every released member requires a current hold",
                )
                causes = list(
                    {
                        f.source_key.model_dump_json(): f.source_key
                        for f in current.values()
                    }.values()
                )
            with self.registry.workflow_store.transaction() as tx:
                row = tx.execute(
                    "SELECT reason FROM freeze_requests WHERE project_id=? AND id=?",
                    (str(request.project_id), str(p.freeze_id)),
                ).fetchone()
            require(row is not None, "Actual prepared freeze request required")
            return dict(
                operation="mes.contain",
                work_order_id=None,
                unit_ids=p.unit_ids,
                material_lot_ids=p.lot_ids,
                decision=p.state,
                cause=causes[0] if causes else None,
                additional_causes=causes[1:],
                evidence=row[0],
            )
        if p.kind == "ship":
            ids = {uid for uid, _, _ in p.units}
            latest = {}
            for fact in observations.of_type("mes.release"):
                for unit in fact.payload.units:
                    if unit.unit_id in ids:
                        latest[unit.unit_id, fact.payload.kind] = fact
            require(
                all(
                    (uid, kind) in latest
                    and latest[uid, kind].payload.decision == "approved"
                    for uid in ids
                    for kind in ("quality", "manufacturing")
                ),
                "Actual approved releases covering shipment required",
            )
            releases = list(
                {f.source_key.model_dump_json(): f for f in latest.values()}.values()
            )
            return dict(
                operation="wms.ship",
                shipment_id=p.shipment_id,
                order_line_id=p.order_line_id,
                units=[dict(unit_id=uid, sn=sn) for uid, sn, _ in p.units],
                releases=[f.source_key for f in releases],
                amount=dict(quantity=str(p.quantity), unit=p.unit, scale=p.scale),
                destination="Customer shipment",
                evidence="Original prepared shipment request",
            )
        if p.kind == "eco_switch":
            if p.boundary == "cancel_remaining":
                return dict(
                    operation="mes.cancel_remaining",
                    work_order_id=p.work_order_id,
                    eco_id=p.eco_id,
                    retained_unit_ids=p.retained_unit_ids,
                    evidence="Prepared cancellation of remaining obligation",
                )
            changes = [
                f
                for f in observations.of_type("pdm.change")
                if f.payload.work_order_id == p.work_order_id
                and f.payload.from_revision_id == p.old_revision_id
                and f.payload.to_revision_id == p.new_revision_id
            ]
            require(bool(changes), "Actual approved PDM change required")
            approvals = [
                f
                for f in observations.of_type("oa.approval_decision")
                if f.payload.target.target_type == "engineering"
                and f.payload.target.revision_id == p.new_revision_id
                and f.payload.target.source_key == changes[-1].payload.released_revision
            ]
            require(bool(approvals), "Actual OA change approval required")
            with self.registry.workflow_store.transaction() as tx:
                units = [
                    dict(
                        unit_id=uid,
                        sn=tx.execute(
                            "SELECT sn FROM units WHERE project_id=? AND id=?",
                            (str(request.project_id), str(uid)),
                        ).fetchone()[0],
                    )
                    for uid in p.retained_unit_ids
                ]
            return dict(
                operation="mes.switch_revision",
                work_order_id=p.work_order_id,
                eco_id=p.eco_id,
                from_revision_id=p.old_revision_id,
                to_revision_id=p.new_revision_id,
                units=units,
                change=changes[-1].source_key,
                approval=approvals[-1].source_key,
                evidence="Prepared remaining scope split",
            )
        if p.kind == "start":
            employees = observations.of_type("hr_sap.employee")
            shifts = [
                f
                for f in observations.of_type("hr_dingtalk.shift")
                if f.payload.work_order_id == p.work_order_id
            ]
            equipment = [
                f
                for f in observations.of_type("plc.equipment")
                if observations.fact(f.payload.process_request).payload.work_order_id
                == p.work_order_id
            ]
            require(
                bool(employees and shifts and equipment),
                "Actual HR/PLC eligibility prerequisites required",
            )
            shift = shifts[-1]
            return dict(
                operation="mes.start",
                work_order_id=p.work_order_id,
                revision_id=p.revision_id,
                mode=p.mode,
                units=[dict(unit_id=uid, sn=sn) for uid, sn in p.units],
                operator=shift.payload.employee,
                shift=shift.source_key,
                equipment=equipment[-1].source_key,
                occurred_at=self.registry.workflow_store.business_clock().isoformat(),
            )
        if p.kind == "stop":
            with self.registry.workflow_store.transaction() as tx:
                interruption = tx.execute(
                    "SELECT x.kind FROM interruptions i JOIN execution_exceptions x ON x.id=i.exception_id AND x.project_id=i.project_id WHERE i.project_id=? AND i.id=? AND i.work_order_id=? AND i.reason=?",
                    (
                        str(request.project_id),
                        str(p.interruption_id),
                        str(p.work_order_id),
                        p.reason,
                    ),
                ).fetchone()
            require(interruption is not None, "Exact prepared interruption required")
            return dict(
                operation="mes.interrupt",
                work_order_id=p.work_order_id,
                interruption_id=p.interruption_id,
                reason=p.reason,
                kind=interruption["kind"],
                start_id=p.start_id,
            )
        if p.kind == "resume":
            return dict(
                operation="mes.resume",
                work_order_id=p.work_order_id,
                interruption_id=p.interruption_id,
                plan_id=p.plan_id,
                scope=p.scope,
                evidence="Prepared domain recovery",
            )
        require(False, "Core authority operation prerequisite unavailable")

    def source_fact(self, request):
        with self.registry.workflow_store.transaction() as tx:
            operation_id = request.id
            if tx.execute(
                "SELECT 1 FROM sqlite_master WHERE name='integration_core_bindings'"
            ).fetchone():
                row = tx.execute(
                    "SELECT operation_id FROM integration_core_bindings WHERE project_id=? AND exchange_id=?",
                    (str(request.project_id), str(request.id)),
                ).fetchone()
                if row:
                    from uuid import UUID

                    operation_id = UUID(row[0])
        receipt = self.registry.adapter(self.system).query(
            request.project_id, operation_id
        )
        wire = self.query(request.system, request.business_key)
        require(
            wire is not None
            and wire.request_hash == digest(request.model_dump(mode="json"))
            and receipt is not None
            and receipt.phase == "accepted"
            and bool(receipt.source_keys),
            "Actual original core source required",
        )
        return self.registry.observe_fact(request.project_id, receipt.source_keys[0])

    def snapshot(self, system, object_type):
        from ..exchange_models import AuthoritySnapshot, InboundReceipt, InboundIQC
        from .contracts import IntegrationFact

        require(
            system == self.system
            and (system, object_type) in {("wms", "receipt"), ("mes", "iqc")},
            "Unsupported core source feed",
        )
        store, records = self.registry.source_store(system), []
        with store.transaction() as tx:
            rows = tx.execute(
                "SELECT sequence,fact_json FROM facts WHERE object_type=? ORDER BY sequence DESC LIMIT 500",
                (object_type,),
            ).fetchall()
            sequence = tx.execute(
                "SELECT COALESCE(MAX(sequence),0) FROM facts"
            ).fetchone()[0]
        for row in reversed(rows):
            f = IntegrationFact.model_validate_json(row["fact_json"])
            p = f.payload
            common = dict(
                project_id=f.project_id,
                source=f.source,
                external_actor=f.external_actor,
                signature=f.evidence,
            )
            if object_type == "receipt":
                records.append(
                    InboundReceipt(
                        **common,
                        commitment_id=p.commitment_id,
                        material_lot_id=p.material_lot_id,
                        quantity=str(p.amount.quantity),
                        unit=p.amount.unit,
                    )
                )
            else:
                records.append(
                    InboundIQC(
                        **common,
                        receipt_system=p.receipt.system,
                        receipt_external_id=p.receipt.external_id,
                        accepted=str(p.accepted.quantity),
                        rejected=str(p.rejected.quantity),
                        evidence=p.evidence,
                        manual_iqc_id=p.manual_iqc_id,
                    )
                )
        return AuthoritySnapshot(
            system=system, object_type=object_type, sequence=sequence, records=records
        )

    def stock_basis(self, request):
        from ..exchange_models import ExternalRequest, StockBasisProof, StockSourceEvent
        from .contracts import IntegrationFact

        p = request.typed_payload
        require(
            p.kind == "stock_proof" and request.system == self.system,
            "Stock proof scope mismatch",
        )
        with self.registry.source_store(self.system).transaction() as tx:
            row = tx.execute(
                "SELECT request_json,receipt_json FROM core_authority_receipts WHERE project_id=? AND business_key=?",
                (str(request.project_id), p.original_business_key),
            ).fetchone()
            require(row is not None, "Original source coverage unavailable")
            original, receipt = (
                ExternalRequest.model_validate_json(row[0]),
                ExternalReceipt.model_validate_json(row[1]),
            )
            from hashlib import sha256

            require(
                original.id == p.original_exchange_id
                and original.project_id == request.project_id
                and original.system == request.system
                and receipt.phase == "accepted"
                and receipt.request_hash == digest(original.model_dump(mode="json"))
                and sha256(row[1].encode()).hexdigest() == p.original_receipt_hash,
                "Original stock proof scope/hash mismatch",
            )
            require(
                original.typed_payload.kind == "reserve"
                and original.typed_payload.reservation_id == p.reservation_id
                and bool(receipt.details)
                and receipt.details[0].stock_basis is not None,
                "Original reservation proof unavailable",
            )
            sources = []
            for basis in receipt.details[0].stock_basis:
                fact_row = tx.execute(
                    "SELECT sequence,fact_json FROM facts WHERE project_id=? AND object_type='receipt' AND external_id=? AND version=?",
                    (str(request.project_id), basis.external_id, basis.source_version),
                ).fetchone()
                require(fact_row is not None, "Original receipt source unavailable")
                fact = IntegrationFact.model_validate_json(fact_row["fact_json"])
                sources.append(
                    StockSourceEvent(
                        project_id=request.project_id,
                        lot_id=fact.payload.material_lot_id,
                        owner_id=fact.payload.owner_id,
                        material_id=fact.payload.material_id,
                        unit=fact.payload.amount.unit,
                        quantity=str(fact.payload.amount.quantity),
                        source=fact.source,
                        sequence=fact_row["sequence"],
                    )
                )
        return StockBasisProof(
            request_hash=digest(request.model_dump(mode="json")),
            mode="mock",
            receipt=receipt,
            sources=sources,
        )
