"""Readiness is derived from fixed revision and authoritative evidence."""

import json
from datetime import datetime
from uuid import UUID

from .contracts import DomainError
from .engineering import fixed_revision
from .engineering_models import ReadinessCheck, ReadinessResult


def evaluate(tx, project_id, work_order_id, mode, now) -> ReadinessResult:
    if mode not in {"trial", "bulk"}:
        raise ValueError("mode must be trial or bulk")
    row = tx.execute(
        "SELECT * FROM work_orders WHERE id=? AND project_id=?",
        (str(work_order_id), str(project_id)),
    ).fetchone()
    if row is None:
        raise DomainError("NOT_FOUND", 404, "Workflow resource not found")
    project = tx.execute(
        "SELECT * FROM projects WHERE id=?", (str(project_id),)
    ).fetchone()
    revision = fixed_revision(tx, project_id, row["revision_id"])
    contract = json.loads(project["contract_json"])
    checks = []

    def add(kind, required, passed, reason, ids=()):
        checks.append(
            ReadinessCheck(
                kind=kind,
                required=required,
                status=("ready" if passed else "blocked")
                if required
                else "not_required",
                reason=reason,
                evidence_ids=list(ids),
            )
        )

    handoff = tx.execute(
        "SELECT * FROM handoffs WHERE project_id=? AND revision_id=? AND to_system='MES' ORDER BY created_at DESC,id DESC LIMIT 1",
        (str(project_id), row["revision_id"]),
    ).fetchone()
    version_ok = (
        handoff is not None
        and handoff["status"] == "verified"
        and handoff["received_revision"] == revision.internal_revision
    )
    add(
        "version",
        True,
        version_ok,
        "MES receipt matches fixed revision"
        if version_ok
        else "fixed revision lacks matching accepted MES receipt",
        [UUID(handoff["id"])] if handoff else [],
    )
    start = datetime.fromisoformat(row["planned_start"])
    for kind in ("equipment", "people"):
        evidence = tx.execute(
            "SELECT * FROM readiness_checks WHERE project_id=? AND work_order_id=? AND kind=? ORDER BY created_at DESC,id DESC LIMIT 1",
            (str(project_id), str(work_order_id), kind),
        ).fetchone()
        valid = (
            evidence is not None
            and evidence["decision"] == "verified"
            and datetime.fromisoformat(evidence["valid_until"]) >= start
            and datetime.fromisoformat(evidence["valid_until"]) >= now
        )
        add(
            kind,
            True,
            valid,
            f"{kind} evidence valid at planned use"
            if valid
            else f"{kind} evidence missing, rejected, or expired at planned use",
            [UUID(evidence["id"])] if evidence else [],
        )
    required = contract["customer_approval_required"] is not False
    approval = tx.execute(
        "SELECT * FROM customer_approvals WHERE project_id=? AND revision_id=? ORDER BY created_at DESC,id DESC LIMIT 1",
        (str(project_id), row["revision_id"]),
    ).fetchone()
    customer_ok = (
        contract["customer_approval_required"] is True
        and contract["customer_revision"] == revision.customer_revision
        and approval is not None
        and approval["decision"] == "approved"
        and approval["customer_id"] == project["customer_id"]
    )
    add(
        "customer",
        required,
        customer_ok,
        "matching customer approval recorded"
        if customer_ok
        else "customer approval or contractual revision is unknown or missing",
        [UUID(approval["id"])] if approval else [],
    )
    # B1/B2 replace these with accepted plan and reservation sources; absence is blocking.
    add("plan", True, False, "no authoritative material plan cutoff")
    add("material", True, False, "no accepted scoped material reservation")
    # B3/C1 will supply actual complete first article evidence on this fixed scope.
    add(
        "first_article",
        mode == "bulk",
        False,
        "matching tested first article absent"
        if mode == "bulk"
        else "trial does not require first article",
    )
    return ReadinessResult(
        ready=all(c.status != "blocked" for c in checks),
        checks=checks,
        input_versions={
            "project": project["version"],
            "revision": row["revision_id"],
            "work_order": row["source_version"],
        },
    )
