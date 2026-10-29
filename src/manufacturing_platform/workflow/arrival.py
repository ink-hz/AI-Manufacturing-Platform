"""Receipt linkage adds no inventory, inspection, reservation or external event."""

import json
from uuid import uuid4

from .arrival_models import Arrival, MatchArrival, RecordArrival
from .authority import register_reader
from .commands import COMMAND_REGISTRY
from .contracts import MutationResult, ObjectRelation, ObjectSummary
from .laboratory import business, canonical, insert, stamp
from .orders import own
from .quality import fail


def record(tx, context, command):
    if (
        command.source.occurred_at > context.now
        or command.source.collected_at > context.now
        or command.source.collected_at < command.source.occurred_at
    ):
        fail("Observation must already have occurred and been collected", 422)
    ident = insert(tx, "arrivals", context, business(command))
    return MutationResult(object_type="arrival", object_id=ident)


def matches(tx, pid, ident):
    return [
        json.loads(row[0])
        for row in tx.execute(
            "SELECT payload_json FROM arrival_matches WHERE project_id=? "
            "AND arrival_id=? ORDER BY seq",
            (str(pid), str(ident)),
        )
    ]


def match(tx, context, command):
    own(tx, "arrivals", context.project_id, command.arrival_id)
    own(tx, "supply_receipts", context.project_id, command.receipt_id)
    history = matches(tx, context.project_id, command.arrival_id)
    previous = history[-1]["receipt_id"] if history else None
    if previous == str(command.receipt_id):
        fail("Arrival is already matched to this receipt")
    if previous and not command.correction_reason:
        fail("Correcting a match requires an explicit reason")
    if not previous and command.correction_reason:
        fail("An initial match is not a correction", 422)
    ident = str(uuid4())
    tx.execute(
        "INSERT INTO arrival_matches(id,project_id,arrival_id,receipt_id,payload_json) "
        "VALUES (?,?,?,?,?)",
        (
            ident,
            str(context.project_id),
            str(command.arrival_id),
            str(command.receipt_id),
            canonical(
                dict(
                    id=ident,
                    receipt_id=str(command.receipt_id),
                    previous_receipt_id=previous,
                    evidence=command.evidence,
                    correction_reason=command.correction_reason,
                    **stamp(context),
                )
            ),
        ),
    )
    return MutationResult(object_type="arrival", object_id=command.arrival_id)


def value(tx, pid, row):
    history = matches(tx, pid, row["id"])
    return Arrival(
        **json.loads(row["payload_json"]),
        state="matched" if history else "unlinked",
        receipt_id=history[-1]["receipt_id"] if history else None,
        matches=history,
    )


def summary(tx, pid, row):
    item = value(tx, pid, row)
    return ObjectSummary(
        id=item.id,
        project_id=pid,
        kind="arrival",
        title=(f"{item.arrival_number} · {item.location} · "
               f"{item.package_count} packages · manual"),
        state=item.state,
        version=1 + len(item.matches),
        source=item.source,
        blocking_reasons=[
            "Package identity requires receipt matching; observation carries no stock or IQC quantity"
        ] if not item.receipt_id else [],
        next_actions=["arrival.match"],
    )


def relations(item, pid):
    return [
        ObjectRelation(
            relation="matched_receipt", project_id=pid, kind="receipt", id=match.receipt_id
        )
        for match in item.matches
    ]


for model, handler in [(RecordArrival, record), (MatchArrival, match)]:
    COMMAND_REGISTRY.register(
        model, roles={"warehouse", "supply"}, qualifications=set(), handler=handler
    )
register_reader("arrival", "arrivals", Arrival, value, summary, relations)
