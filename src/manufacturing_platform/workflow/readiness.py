"""Readiness is derived from fixed revision and authoritative evidence."""

import json
from datetime import datetime
from uuid import UUID

from .contracts import DomainError
from .engineering import fixed_revision
from .engineering_models import ReadinessCheck, ReadinessResult
from .supply import MAX_CUTOFF_AGE, available


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
    scopes = ("trial", "common") if mode == "trial" else ("bulk", "common")
    plan_rows = tx.execute(
        """SELECT DISTINCT p.* FROM plans p JOIN requirements r ON r.plan_id=p.id
           WHERE p.project_id=? AND p.state='confirmed' AND r.work_order_id=?
           ORDER BY p.created_at DESC,p.source_version DESC,p.id DESC LIMIT 1""",
        (str(project_id), str(work_order_id)),
    ).fetchall()
    plan = plan_rows[0] if plan_rows else None
    plan_ok = False
    applicable = []
    if plan and plan["cutoff"]:
        cutoff = datetime.fromisoformat(plan["cutoff"])
        inputs = json.loads(plan["inputs_json"])
        order_versions = {
            i["order_line_id"]: i["version"] for i in inputs["input_order_versions"]
        }
        order = tx.execute(
            "SELECT source_version,state FROM order_lines WHERE id=? AND project_id=?",
            (row["order_line_id"], str(project_id)),
        ).fetchone()
        plan_ok = (
            cutoff <= now
            and now - cutoff <= MAX_CUTOFF_AGE
            and row["revision_id"] in inputs["input_revision_ids"]
            and order is not None
            and order["state"] == "active"
            and order_versions.get(row["order_line_id"]) == order["source_version"]
        )
        if plan_ok:
            applicable = tx.execute(
                """SELECT * FROM requirements WHERE project_id=? AND plan_id=?
                   AND work_order_id=? AND execution_scope IN (?,?) ORDER BY created_at,id LIMIT 500""",
                (str(project_id), plan["id"], str(work_order_id), *scopes),
            ).fetchall()
    add(
        "plan",
        True,
        plan_ok and bool(applicable),
        "current scoped plan and source cutoff"
        if plan_ok and applicable
        else "no valid applicable plan, fixed input version or fresh cutoff",
        [UUID(plan["id"])] if plan else [],
    )
    material_ok = bool(applicable) and all(
        available(tx, project_id, req["id"], now).shortage == 0
        and tx.execute(
            """SELECT COALESCE(SUM(v.confirmed_atoms),0) FROM reservations v
               JOIN requirements prior ON prior.id=v.requirement_id AND prior.project_id=v.project_id
               JOIN material_lots l ON l.id=v.material_lot_id AND l.project_id=v.project_id
               WHERE v.project_id=? AND prior.lineage_id=? AND v.work_order_id=?
                 AND v.authority_receipt_id IS NOT NULL AND v.confirmed_atoms>0
                 AND l.owner_id=? AND l.material_id=? AND l.unit=?
                 AND l.state='active' AND l.expiry>=?""",
            (
                str(project_id),
                req["lineage_id"],
                str(work_order_id),
                req["owner_id"],
                req["material_id"],
                req["unit"],
                now.date().isoformat(),
            ),
        ).fetchone()[0]
        >= req["q_atoms"]
        for req in applicable
    )
    add(
        "material",
        True,
        plan_ok and material_ok,
        "accepted scoped authority reservations"
        if plan_ok and material_ok
        else "accepted scoped material reservation missing or ineligible",
        [UUID(req["id"]) for req in applicable],
    )
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
            "plan": plan["source_version"] if plan else 0,
            "plan_id": plan["id"] if plan else "",
            "plan_source": plan["source_external_id"] if plan else "",
            "plan_cutoff": plan["cutoff"] if plan and plan["cutoff"] else "",
        },
    )
