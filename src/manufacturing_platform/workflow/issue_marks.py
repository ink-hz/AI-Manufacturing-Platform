"""Issue stage observations preserve event time and never mutate stock or IQC."""
import json
from uuid import uuid4

from .authority import register_reader
from .commands import COMMAND_REGISTRY
from .contracts import MutationResult, ObjectRelation, ObjectSummary
from .issue_mark_models import IssueMark, MarkIssue
from .laboratory import business, canonical
from .material_handoffs import actor_fact, applicable
from .orders import own
from .quality import fail

ROLES = {"warehouse", "supply", "production", "project_owner"}


def authorize(tx, actor, pid, command):
    if command.action == "issue.mark" and not applicable(tx, pid):
        fail("Issue marks require an OEM project", 422)


def mark(tx, context, command):
    requirement = own(tx, "requirements", context.project_id, command.requirement_id)
    happened = command.occurred_at or context.now
    if happened > context.now:
        fail("Issue mark time must be no later than now", 422)
    ident = str(uuid4())
    payload = dict(
        **business(command), **actor_fact(context), id=ident,
        work_order_id=requirement["work_order_id"], material_id=requirement["material_id"],
    )
    payload.update(
        occurred_at=happened.isoformat(),
        source=dict(
            system="manual", object_type="issue_mark", external_id=ident,
            version=1, mode="manual", occurred_at=happened.isoformat(),
            collected_at=context.now.isoformat(),
            evidence="Manual issue mark recorded by " + str(context.actor.user_id),
        ),
    )
    tx.execute(
        "INSERT INTO issue_marks(id,project_id,requirement_id,work_order_id,stage,payload_json) "
        "VALUES (?,?,?,?,?,?)",
        (ident, str(context.project_id), str(command.requirement_id),
         requirement["work_order_id"], command.stage, canonical(payload)),
    )
    return MutationResult(object_type="issue_mark", object_id=ident)


def value(tx, pid, row):
    return IssueMark(**json.loads(row["payload_json"]))


def summary(tx, pid, row):
    payload = json.loads(row["payload_json"])
    return ObjectSummary(
        id=row["id"], project_id=pid, kind="issue_mark",
        title=f"{payload['stage']} · {payload['material_id']} · manual",
        state=payload["stage"], version=1, source=payload["source"],
    )


def relations(item, pid):
    return [
        ObjectRelation(relation="requirement", project_id=pid, kind="requirement", id=item.requirement_id),
        ObjectRelation(relation="work_order", project_id=pid, kind="work_order", id=item.work_order_id),
    ]


def requirement_page(tx, pid, requirement_id, *, limit, offset):
    """Scope and count in SQL before taking a stable, bounded page."""
    own(tx, "requirements", pid, requirement_id)
    scope = (str(pid), str(requirement_id))
    total = tx.execute(
        "SELECT COUNT(*) FROM issue_marks WHERE project_id=? AND requirement_id=?", scope,
    ).fetchone()[0]
    items = [summary(tx, pid, row) for row in tx.execute(
        "SELECT * FROM issue_marks WHERE project_id=? AND requirement_id=? "
        "ORDER BY seq LIMIT ? OFFSET ?", (*scope, limit, offset),
    )]
    return total, items


COMMAND_REGISTRY.register(MarkIssue, roles=ROLES, qualifications=set(), handler=mark)
register_reader("issue_mark", "issue_marks", IssueMark, value, summary, relations)
