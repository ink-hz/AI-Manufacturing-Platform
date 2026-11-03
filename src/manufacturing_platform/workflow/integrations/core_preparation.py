"""One-time existing-domain preparation; no source I/O inside workflow transactions."""

from ..exchange_models import ExternalRequest, RequestReservation
from .contracts import ObjectRef
from .core_guards import require
from .core_projections import command_data


BINDINGS_DDL = """CREATE TABLE IF NOT EXISTS integration_core_bindings(
 project_id TEXT NOT NULL, operation_id TEXT NOT NULL, exchange_id TEXT NOT NULL,
 target_kind TEXT NOT NULL, target_id TEXT NOT NULL, request_json TEXT NOT NULL,
 PRIMARY KEY(project_id,operation_id,exchange_id))"""
OBSERVATIONS_DDL = """CREATE TABLE IF NOT EXISTS integration_core_receipts(
 project_id TEXT NOT NULL, exchange_id TEXT NOT NULL, receipt_json TEXT NOT NULL,
 PRIMARY KEY(project_id,exchange_id))"""


def ensure_core_tables(tx):
    tx.execute(BINDINGS_DDL)
    tx.execute(OBSERVATIONS_DDL)
    for table, keys in (
        ("integration_core_bindings", ("project_id", "operation_id", "exchange_id")),
        ("integration_core_receipts", ("project_id", "exchange_id")),
    ):
        for action in ("UPDATE", "DELETE"):
            tx.execute(
                f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable core binding'); END"
            )
        predicate = " AND ".join(f"{key}=NEW.{key}" for key in keys)
        tx.execute(
            f"CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM {table} WHERE {predicate}) BEGIN SELECT RAISE(ABORT,'immutable core binding'); END"
        )


def prepare_core_effect(tx, context, operation):
    p = operation.payload
    if p.operation not in {
        "wms.reserve",
        "mes.contain",
        "mes.start",
        "mes.interrupt",
        "mes.resume",
        "wms.ship",
        "mes.switch_revision",
        "mes.cancel_remaining",
    }:
        return
    ensure_core_tables(tx)
    results = []
    if p.operation == "wms.reserve":
        groups = {}
        for allocation in p.allocations:
            groups.setdefault(allocation.material_lot_id, []).append(allocation)
        from ..exchanges import request_reservation

        for allocations in groups.values():
            allocation = allocations[0]
            results.append(
                request_reservation(
                    tx,
                    context,
                    RequestReservation(
                        **command_data(context),
                        action="reservation.request",
                        work_order_id=p.work_order_id,
                        requirement_id=p.requirement_id,
                        lot_id=allocation.material_lot_id,
                        quantity=str(sum(a.amount.quantity for a in allocations)),
                        unit=allocation.amount.unit,
                    ),
                )
            )
    elif p.operation in {"mes.switch_revision", "mes.cancel_remaining"}:
        from ..eco import switch
        from ..eco_models import SwitchEco

        results.append(
            switch(
                tx,
                context,
                SwitchEco(
                    **command_data(context),
                    action="eco.switch",
                    eco_id=p.eco_id,
                    target_work_order_id=p.work_order_id,
                    boundary="split_remaining"
                    if p.operation == "mes.switch_revision"
                    else "cancel_remaining",
                    new_revision_id=p.to_revision_id
                    if p.operation == "mes.switch_revision"
                    else None,
                    evidence=p.evidence,
                ),
            )
        )
    elif p.operation == "wms.ship":
        from ..delivery import _request_shipment
        from ..delivery_models import RequestShipment

        results.append(
            _request_shipment(
                tx,
                context,
                RequestShipment(
                    **command_data(context),
                    action="shipment.request",
                    order_line_id=p.order_line_id,
                    unit_ids=[u.unit_id for u in p.units],
                    quantity=str(p.amount.quantity),
                    unit=p.amount.unit,
                    boxes=[],
                ),
                shipment_id=p.shipment_id,
            )
        )
    elif p.operation == "mes.interrupt":
        from ..execution import _interrupt_production
        from ..execution_models import InterruptProduction

        results.append(
            _interrupt_production(
                tx,
                context,
                InterruptProduction(
                    **command_data(context),
                    action="production.interrupt",
                    work_order_id=p.work_order_id,
                    reason=p.reason,
                    kind=p.kind,
                    start_id=p.start_id,
                ),
                object_id=p.interruption_id,
            )
        )
    elif p.operation == "mes.resume":
        from ..execution import resume_production
        from ..execution_models import ResumeProduction

        results.append(
            resume_production(
                tx,
                context,
                ResumeProduction(
                    **command_data(context),
                    action="production.resume",
                    interruption_id=p.interruption_id,
                    plan_id=p.plan_id,
                    scope=p.scope,
                    evidence=p.evidence,
                ),
            )
        )
    elif p.operation == "mes.start":
        from ..execution import start_production
        from ..execution_models import StartProduction

        results.append(
            start_production(
                tx,
                context,
                StartProduction(
                    **command_data(context),
                    action="production.start",
                    work_order_id=p.work_order_id,
                    mode=p.mode,
                    unit_ids=[u.unit_id for u in p.units],
                    quantity=str(len(p.units)),
                ),
            )
        )
    elif p.operation == "mes.contain":
        from ..freeze import request
        from ..feedback_models import FreezeRequest

        results.append(
            request(
                tx,
                context,
                FreezeRequest(
                    **command_data(context),
                    action="freeze.request",
                    unit_ids=p.unit_ids,
                    lot_ids=p.material_lot_ids,
                    state=p.decision,
                    reason=p.evidence,
                ),
            )
        )
    for result in results:
        request = tx.execute(
            "SELECT request_json FROM exchanges WHERE project_id=? AND id=?",
            (str(context.project_id), str(result.exchange_id)),
        ).fetchone()[0]
        tx.execute(
            "INSERT INTO integration_core_bindings VALUES (?,?,?,?,?,?)",
            (
                str(context.project_id),
                str(operation.operation_id),
                str(result.exchange_id),
                result.object_type.value,
                str(result.object_id),
                request,
            ),
        )


def bound_requests(tx, project_id, operation_id):
    rows = []
    if tx.execute(
        "SELECT 1 FROM sqlite_master WHERE name='integration_core_bindings'"
    ).fetchone():
        rows = tx.execute(
            "SELECT request_json FROM integration_core_bindings WHERE project_id=? AND operation_id=? ORDER BY exchange_id",
            (str(project_id), str(operation_id)),
        ).fetchall()
    if not rows:
        rows = tx.execute(
            "SELECT request_json FROM exchanges WHERE project_id=? AND id=? AND system IN ('wms','mes','sap')",
            (str(project_id), str(operation_id)),
        ).fetchall()
    return [ExternalRequest.model_validate_json(r[0]) for r in rows]


def project_bound_effect(tx, context, fact):
    from ..exchange_models import ExternalReceipt

    ensure_core_tables(tx)
    rows = tx.execute(
        "SELECT b.*,r.receipt_json FROM integration_core_bindings b LEFT JOIN integration_core_receipts r ON r.project_id=b.project_id AND r.exchange_id=b.exchange_id WHERE b.project_id=? AND b.operation_id=? ORDER BY b.exchange_id",
        (str(context.project_id), fact.source.external_id),
    ).fetchall()
    if not rows:
        originals = tx.execute(
            "SELECT e.*,r.receipt_json observed_receipt FROM exchanges e JOIN integration_core_receipts r ON r.project_id=e.project_id AND r.exchange_id=e.id WHERE e.project_id=? AND e.id=? AND e.system=?",
            (str(context.project_id), fact.source.external_id, fact.source.system),
        ).fetchall()
        rows = []
        for original in originals:
            request = ExternalRequest.model_validate_json(original["request_json"])
            p = request.typed_payload
            kind, ident = (
                ("reservation", p.reservation_id)
                if p.kind == "reserve"
                else ("exchange", request.id)
            )
            rows.append(
                dict(
                    receipt_json=original["observed_receipt"],
                    target_kind=kind,
                    target_id=ident,
                )
            )
    require(bool(rows), "Physical effect has no prepared domain binding")
    targets = []
    for row in rows:
        require(
            row["receipt_json"] is not None, "Original source receipt is not observed"
        )
        context.exchange_service.apply(
            tx,
            context,
            ExternalReceipt.model_validate_json(row["receipt_json"]),
            source_fact=fact,
        )
        targets.append(
            ObjectRef(
                project_id=context.project_id,
                kind=row["target_kind"],
                id=row["target_id"],
            )
        )
    return targets
