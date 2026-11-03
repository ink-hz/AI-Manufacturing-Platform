"""Bounded handoff projections preserve each split's intended and actual location."""
import json

from .authority import register_reader
from .contracts import ObjectRelation, ObjectSummary
from .material_handoff_models import MaterialHandoff


def value(tx, pid, row):
    return MaterialHandoff(
        **json.loads(row["payload_json"]),
        state=row["state"],
        receipt=json.loads(row["receipt_json"]) if row["receipt_json"] else None,
        resolution=json.loads(row["resolution_json"]) if row["resolution_json"] else None,
        cancellation=json.loads(row["cancellation_json"]) if row["cancellation_json"] else None,
    )


def summary(tx, pid, row):
    item = value(tx, pid, row)
    location = (
        f"actual receipt: {item.receipt.received_location}" if item.receipt
        else f"intended destination: {item.to_location}; receipt unconfirmed"
    )
    return ObjectSummary(
        id=item.id,
        project_id=pid,
        kind="material_handoff",
        title=f"{item.handoff_number} · {item.quantity} {item.unit} · {location} · manual",
        state=item.state,
        version=1 + bool(item.receipt) + bool(item.resolution) + bool(item.cancellation),
        source=item.source,
        blocking_reasons=(
            ["Awaiting designated receiver"] if item.state == "pending" else
            ["Receipt discrepancy requires sender resolution"] if item.state == "disputed" else []
        ),
        next_actions={
            "pending": ["material_handoff.receive", "material_handoff.cancel"],
            "disputed": ["material_handoff.resolve"],
        }.get(item.state, []),
    )


def relations(item, pid):
    result = [ObjectRelation(
        relation="material_lot", project_id=pid, kind="material_lot", id=item.material_lot_id,
    )]
    if item.work_order_id:
        result.append(ObjectRelation(
            relation="work_order", project_id=pid, kind="work_order", id=item.work_order_id,
        ))
    return result


register_reader("material_handoff", "material_handoffs", MaterialHandoff, value, summary, relations)
