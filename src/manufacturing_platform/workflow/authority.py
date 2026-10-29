"""Scoped contract evidence; deliberately unused by production source selection."""

import json

from .authority_models import AuthorityRule, RegisterAuthority, VerifyAuthority
from .commands import COMMAND_REGISTRY
from .contracts import MutationResult, ObjectDetail, ObjectEvidence, ObjectSummary
from .laboratory import business, canonical, insert, stamp
from .orders import _history_rows, own
from .quality import fail
from .queries import OBJECT_REGISTRY


def register_authority(tx, context, command):
    key = command.business_scope.casefold()
    previous = tx.execute(
        "SELECT * FROM authority_rules WHERE project_id=? AND object_category=? "
        "AND scope_key=? ORDER BY revision DESC LIMIT 1",
        (str(context.project_id), command.object_category.value, key),
    ).fetchone()
    revision = previous["revision"] + 1 if previous else 1
    ident = insert(
        tx,
        "authority_rules",
        context,
        dict(
            **business(command),
            revision=revision,
            supersedes_id=previous["id"] if previous else None,
        ),
        object_category=command.object_category.value,
        scope_key=key,
        revision=revision,
    )
    return MutationResult(object_type="authority_rule", object_id=ident)


def verify(tx, context, command):
    own(tx, "authority_rules", context.project_id, command.rule_id)
    if tx.execute(
        "SELECT 1 FROM authority_verifications WHERE rule_id=?",
        (str(command.rule_id),),
    ).fetchone():
        fail("Contract verification is immutable; register a new scope revision")
    tx.execute(
        "INSERT INTO authority_verifications VALUES (?,?,?)",
        (
            str(command.rule_id),
            str(context.project_id),
            canonical(dict(contract_evidence=command.contract_evidence, **stamp(context))),
        ),
    )
    return MutationResult(object_type="authority_rule", object_id=command.rule_id)


def value(tx, pid, row):
    latest = tx.execute(
        "SELECT MAX(revision) FROM authority_rules WHERE project_id=? "
        "AND object_category=? AND scope_key=?",
        (str(pid), row["object_category"], row["scope_key"]),
    ).fetchone()[0]
    verification = tx.execute(
        "SELECT payload_json FROM authority_verifications WHERE project_id=? AND rule_id=?",
        (str(pid), row["id"]),
    ).fetchone()
    payload = json.loads(row["payload_json"])
    return AuthorityRule(
        **payload,
        active=row["revision"] == latest,
        state="verified" if verification else "registered",
        connection_state="demo" if payload["origin"] == "demo" else "unconnected",
        verification=json.loads(verification[0]) if verification else None,
    )


def summary(tx, pid, row):
    item = value(tx, pid, row)
    return ObjectSummary(
        id=item.id,
        project_id=pid,
        kind="authority_rule",
        title=(
            f"{item.object_category.value} · {item.business_scope} · "
            f"{item.system} · {item.connection_state}"
        ),
        state=item.state if item.active else "superseded",
        version=item.revision,
        blocking_reasons=[
            "Registration and contract verification do not establish a production connection"
        ],
        next_actions=["authority.verify"] if not item.verification else [],
    )


def register_reader(
    kind, table, model, read_value, read_summary, relations=lambda value, pid: []
):
    """Trusted fixed-table readers, bounded in SQL and scoped before serialization."""
    def count(tx, pid):
        return tx.execute(
            f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (str(pid),)
        ).fetchone()[0]

    def page(tx, pid, limit, offset):
        return [
            read_summary(tx, pid, row)
            for row in tx.execute(
                f"SELECT * FROM {table} WHERE project_id=? ORDER BY seq LIMIT ? OFFSET ?",
                (str(pid), limit, offset),
            )
        ]

    def detail(tx, pid, ident):
        row = tx.execute(
            f"SELECT * FROM {table} WHERE project_id=? AND id=?",
            (str(pid), str(ident)),
        ).fetchone()
        if row is None:
            return None
        item = read_value(tx, pid, row)
        reference = getattr(item, "evidence", None)
        source = getattr(item, "source", None)
        return ObjectDetail[model](
            summary=read_summary(tx, pid, row),
            value=item,
            relations=relations(item, pid),
            evidence=[ObjectEvidence(reference=reference or source.evidence, source=source)],
            history=_history_rows(
                tx.execute(
                    "SELECT * FROM audit_events WHERE project_id=? AND object_id=? "
                    "ORDER BY id LIMIT 500",
                    (str(pid), str(ident)),
                ).fetchall()
            ),
        )

    OBJECT_REGISTRY.register(kind, model, count=count, summaries=page, detail=detail)


COMMAND_REGISTRY.register(
    RegisterAuthority,
    roles={"engineering", "project_owner"},
    qualifications=set(),
    handler=register_authority,
)
COMMAND_REGISTRY.register(
    VerifyAuthority,
    roles={"engineering", "project_owner"},
    qualifications=set(),
    handler=verify,
)
register_reader("authority_rule", "authority_rules", AuthorityRule, value, summary)
