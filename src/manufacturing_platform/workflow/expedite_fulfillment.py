"""Conservative fulfilment proof over current, explicitly scoped platform facts.

Multiple independent transfers have no physical lineage in the legacy model.
Only one direct receipt or one exclusive trace/supplement group is countable.
"""
import json
from decimal import Decimal

from .clock import business_time
from .expedite_fulfillment_models import ExpediteFulfillmentCheck
from .orders import own
from .supply import amount, available, current_plan_id


def evaluate(tx, project_id, case, *, now=None):
    pid = str(project_id)
    now = now or business_time(tx)
    opened = own(tx, "requirements", pid, case["requirement_id"])
    plan_id = current_plan_id(tx, pid, opened["work_order_id"])
    req = tx.execute(
        "SELECT * FROM requirements WHERE project_id=? AND plan_id=? AND lineage_id=?",
        (pid, plan_id, opened["lineage_id"]),
    ).fetchone()
    project = tx.execute("SELECT version FROM projects WHERE id=?", (pid,)).fetchone()
    blockers = []
    refs = {key: [] for key in ("plan_ids", "reservation_ids", "receipt_ids", "iqc_ids", "handoff_ids", "trace_task_ids")}
    snapshots = {key: [] for key in ("reservations", "inspections", "handoffs")}
    if req is None:
        return ExpediteFulfillmentCheck(
            can_fulfill=False, evaluated_at=now, project_version=project["version"],
            requirement_id=opened["id"], current_requirement_id=None,
            required=amount(opened["q_atoms"], opened["scale"]), qualified=None,
            usable_reserved="0", line_received=None, remaining_to_receive=None,
            unit=opened["unit"], blocking_reasons=["原需求已不在当前确认计划中，请核对变更后的需求。"],
        )
    required = Decimal(amount(req["q_atoms"], req["scale"]))
    balance = available(tx, pid, req["id"], now)
    refs["plan_ids"] = [req["plan_id"]]
    allocations = list(tx.execute(
        "SELECT v.*,l.material_id,l.owner_id,l.unit lot_unit,l.scale,l.expiry,l.state lot_state "
        "FROM effective_reservations v JOIN requirements r ON r.id=v.requirement_id AND r.project_id=v.project_id "
        "JOIN material_lots l ON l.id=v.material_lot_id AND l.project_id=v.project_id "
        "WHERE v.project_id=? AND r.lineage_id=? AND v.work_order_id=? "
        "AND v.authority_receipt_id IS NOT NULL AND v.confirmed_atoms>0",
        (pid, req["lineage_id"], req["work_order_id"]),
    ))
    from .material_eligibility import lot_unavailable_reason

    related_lots = {r[0] for r in tx.execute(
        "SELECT DISTINCT s.material_lot_id FROM effective_supply_receipts s "
        "JOIN supply_commitments c ON c.id=s.commitment_id AND c.project_id=s.project_id "
        "JOIN requirements r ON r.id=c.requirement_id AND r.project_id=c.project_id "
        "WHERE r.project_id=? AND r.lineage_id=?", (pid, req["lineage_id"]),
    )}
    related_lots.update(a["material_lot_id"] for a in allocations)
    quality, eligible, qualified_total, has_quality = {}, {}, Decimal(0), False
    for lot_id in sorted(related_lots):
        lot = own(tx, "material_lots", pid, lot_id)
        if (lot["material_id"], lot["owner_id"], lot["unit"]) != (req["material_id"], req["owner_id"], req["unit"]):
            continue
        inspections = list(tx.execute(
            "SELECT i.*,s.material_lot_id FROM effective_iqc_results i "
            "JOIN effective_supply_receipts s ON s.id=i.receipt_id AND s.project_id=i.project_id "
            "WHERE s.project_id=? AND s.material_lot_id=?", (pid, lot_id),
        ))
        qualified = sum((Decimal(amount(i["accepted_atoms"], lot["scale"])) for i in inspections), Decimal(0))
        quality[lot_id] = qualified if inspections else None
        if inspections:
            has_quality = True
            qualified_total += qualified
        for inspection in inspections:
            refs["iqc_ids"].append(inspection["id"])
            refs["receipt_ids"].append(inspection["receipt_id"])
            snapshots["inspections"].append(dict(
                id=inspection["id"], receipt_id=inspection["receipt_id"], lot_id=lot_id,
                accepted=amount(inspection["accepted_atoms"], lot["scale"]),
                rejected=amount(inspection["rejected_atoms"], lot["scale"]), unit=lot["unit"],
            ))
        global_claims = tx.execute(
            "SELECT COALESCE(SUM(confirmed_atoms),0) FROM effective_reservations "
            "WHERE project_id=? AND material_lot_id=? AND authority_receipt_id IS NOT NULL",
            (pid, lot_id),
        ).fetchone()[0]
        if (inspections and Decimal(amount(global_claims, lot["scale"])) <= qualified
                and not lot_unavailable_reason(tx, pid, lot, now)):
            eligible[lot_id] = Decimal(0)
    for allocation in allocations:
        refs["reservation_ids"].append(allocation["id"])
        quantity = amount(allocation["confirmed_atoms"], allocation["scale"])
        snapshots["reservations"].append(dict(
            id=allocation["id"], lot_id=allocation["material_lot_id"], quantity=quantity,
            requirement_id=allocation["requirement_id"], work_order_id=allocation["work_order_id"],
            authority_receipt_id=allocation["authority_receipt_id"], unit=allocation["unit"],
        ))
        if allocation["material_lot_id"] in eligible and allocation["unit"] == req["unit"]:
            eligible[allocation["material_lot_id"]] += Decimal(quantity)
    usable = min(sum(eligible.values(), Decimal(0)), required - balance.shortage)
    if usable < required:
        blockers.append("本需求的合格可用预留尚未满足；请核对分配、检验及批次状态。")
    if not has_quality:
        blockers.append("尚无可核对的正式检验合格记录。")

    candidates = list(tx.execute(
        "SELECT h.* FROM material_handoffs h JOIN material_lots l "
        "ON l.id=h.material_lot_id AND l.project_id=h.project_id "
        "WHERE h.project_id=? AND h.work_order_id=? AND h.state!='cancelled' "
        "AND l.material_id=? AND l.owner_id=? AND l.unit=? ORDER BY h.seq",
        (pid, req["work_order_id"], req["material_id"], req["owner_id"], req["unit"]),
    ))
    # Explicit scopes for other requirements are never donated to this one.
    relevant = []
    for handoff in candidates:
        receipt = json.loads(handoff["receipt_json"]) if handoff["receipt_json"] else None
        assigned = receipt.get("requirement_id") if receipt else None
        if assigned:
            scope = tx.execute("SELECT lineage_id FROM requirements WHERE project_id=? AND id=?", (pid, assigned)).fetchone()
            if scope and scope["lineage_id"] != req["lineage_id"]:
                continue
        relevant.append(handoff)
    line_received = _line_quantity(tx, pid, req, relevant, refs, snapshots, blockers)
    if line_received is not None and line_received < required:
        blockers.append("线边实收仍有差额，找到物料或文字处理不等于已签收。")
    if line_received is not None:
        credited = {}
        for h in relevant:
            receipt = json.loads(h["receipt_json"])
            credited[h["material_lot_id"]] = credited.get(h["material_lot_id"], Decimal(0)) + Decimal(receipt["received_quantity"])
        for lot_id, quantity in credited.items():
            if min(quantity, required) > eligible.get(lot_id, Decimal(0)):
                blockers.append("已签收批次与本需求的合格预留范围不一致，请核对批次分配。")
                break
    for key in refs:
        refs[key] = sorted(set(refs[key]))
    return ExpediteFulfillmentCheck(
        can_fulfill=not blockers, evaluated_at=now, project_version=project["version"],
        requirement_id=opened["id"], current_requirement_id=req["id"], required=format(required, "f"),
        qualified=format(qualified_total, "f") if has_quality else None,
        usable_reserved=format(max(Decimal(0), usable), "f"),
        line_received=format(line_received, "f") if line_received is not None else None,
        remaining_to_receive=format(max(Decimal(0), required-line_received), "f") if line_received is not None else None,
        unit=req["unit"], blocking_reasons=list(dict.fromkeys(blockers)),
        evidence_refs=refs, evidence_snapshots=snapshots,
    )


def _line_quantity(tx, pid, req, handoffs, refs, snapshots, blockers):
    if not handoffs:
        blockers.append("尚无本需求的线边实收用途确认。")
        return None
    candidate_ids = {h["id"] for h in handoffs}
    if len(handoffs) > 1:
        groups = []
        for task in tx.execute(
            "SELECT t.* FROM material_tasks t JOIN requirements r ON r.id=t.requirement_id AND r.project_id=t.project_id "
            "WHERE t.project_id=? AND r.lineage_id=? AND t.task_kind='trace' AND t.state!='cancelled'",
            (pid, req["lineage_id"]),
        ):
            supplements = {r[0] for r in tx.execute(
                "SELECT handoff_id FROM material_task_evidence WHERE project_id=? AND task_id=?", (pid, task["id"]))}
            if {task["handoff_id"], *supplements} == candidate_ids:
                groups.append(task)
        if len(groups) != 1:
            blockers.append("存在多笔交接，尚未核实为同次独占补收；不能将独立发料或多段流转相加。")
            return None
        refs["trace_task_ids"].append(groups[0]["id"])
        root = next(h for h in handoffs if h["id"] == groups[0]["handoff_id"])
        original_quantity = Decimal(json.loads(root["payload_json"])["quantity"])
    else:
        original_quantity = None
    total = Decimal(0)
    for handoff in handoffs:
        payload = json.loads(handoff["payload_json"])
        receipt = json.loads(handoff["receipt_json"]) if handoff["receipt_json"] else None
        if not receipt or receipt.get("receipt_use", "unspecified") != "line_side" or not receipt.get("requirement_id"):
            blockers.append("交接尚未由指定接收人确认本需求线边实收用途。")
            return None
        scope = tx.execute("SELECT * FROM requirements WHERE project_id=? AND id=?", (pid, receipt["requirement_id"])).fetchone()
        if (not scope or scope["lineage_id"] != req["lineage_id"]
                or scope["work_order_id"] != req["work_order_id"]
                or receipt["actor_id"] != handoff["receiver_id"]
                or receipt.get("scope_actor_id") != handoff["receiver_id"]
                or receipt["received_location"] != payload["to_location"]
                or payload["unit"] != req["unit"]
                or Decimal(receipt["received_quantity"]) > Decimal(payload["quantity"])):
            blockers.append("实收的需求归属、数量、位置或接收人仍需核对。")
            return None
        total += Decimal(receipt["received_quantity"])
        refs["handoff_ids"].append(handoff["id"])
        snapshots["handoffs"].append(dict(
            id=handoff["id"], material_lot_id=handoff["material_lot_id"],
            sent=payload["quantity"], received=receipt["received_quantity"],
            unit=payload["unit"], location=receipt["received_location"],
            requirement_id=receipt["requirement_id"], actor_id=receipt["actor_id"],
            occurred_at=receipt["occurred_at"], scope_recorded_at=receipt.get("scope_recorded_at"),
        ))
    if original_quantity is not None and total > original_quantity:
        blockers.append("补收数量超出原交接范围，请核对分笔数量。")
        return None
    return total
