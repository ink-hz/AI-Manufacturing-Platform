"""Current business progress. Collaboration hints never waive domain predicates."""

from .clock import business_time

import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from .commands import COMMAND_REGISTRY, WorkflowCommand
from .contracts import (
    ClosureProgress,
    MutationResult,
    ObjectSummary,
    ProgressSummary,
    ProjectStageView,
)


class StageHint(WorkflowCommand):
    action: Literal["project.stage"]
    stage: Literal["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"]
    status: Literal["pending", "active", "blocked", "complete"]
    reason: str = Field(min_length=1, max_length=2000)


def record_hint(tx, context, command):
    # The central immutable audit is the hint history; no second business state.
    return MutationResult(object_type="project", object_id=context.project_id)


COMMAND_REGISTRY.register(
    StageHint, roles={"project_owner"}, qualifications=set(), handler=record_hint
)


def hints(tx, project_id):
    return [
        ProjectStageView.model_validate(
            {k: json.loads(r[0])[k] for k in ("stage", "status", "reason")}
        )
        for r in tx.execute(
            """SELECT typed_payload FROM audit_events WHERE id IN
            (SELECT MAX(id) FROM audit_events WHERE project_id=? AND action='project.stage'
            GROUP BY json_extract(typed_payload,'$.stage')) ORDER BY json_extract(typed_payload,'$.stage') LIMIT 9""",
            (str(project_id),),
        )
    ]


def aggregate(tx, project_id) -> ProgressSummary:
    from . import delivery

    pid = str(project_id)
    counts = {}
    for table in (
        "demands",
        "order_lines",
        "engineering_revisions",
        "work_orders",
        "plans",
        "units",
        "quality_tests",
        "shipments",
        "rmas",
        "material_lots",
        "execution_events",
    ):
        counts[table] = tx.execute(
            f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (pid,)
        ).fetchone()[0]
    closures = {}
    for kind in ("fulfillment", "quality", "cost"):
        reasons = delivery.close_predicates(tx, project_id, kind)
        recorded = tx.execute(
            "SELECT COUNT(*) FROM closures WHERE project_id=? AND kind=?", (pid, kind)
        ).fetchone()[0]
        closures[kind] = ClosureProgress(
            status="blocked" if reasons else "closed" if recorded else "ready",
            recorded_count=recorded,
            blocking_reasons=reasons,
        )
    # Bounded witnesses, selected before materialization. Counts/predicates above
    # remain authoritative even when there are more than 50 blocking objects.
    rows = tx.execute(
        """SELECT * FROM (
      SELECT id, 'order_line' kind, source_external_id title, 'Delivery/signature/acceptance incomplete' reason FROM order_lines o
      WHERE project_id=? AND (current_q_atoms > COALESCE((SELECT COUNT(*) FROM shipment_items si WHERE si.order_line_id=o.id),0) * CAST(pow(10,(SELECT unit_scale FROM projects WHERE id=o.project_id)) AS INTEGER) OR current_q_atoms > COALESCE((SELECT SUM(f.q_atoms) FROM delivery_facts f JOIN shipments s ON s.id=f.shipment_id WHERE s.order_line_id=o.id AND f.action='sign'),0) OR EXISTS(SELECT 1 FROM shipments s JOIN shipment_items i ON i.shipment_id=s.id AND i.project_id=s.project_id JOIN units u ON u.id=i.unit_id AND u.project_id=i.project_id JOIN current_revision_contracts policy ON policy.project_id=u.project_id AND policy.revision_id=u.revision_id WHERE s.project_id=o.project_id AND s.order_line_id=o.id AND (json_extract(policy.contract_json,'$.acceptance_required')='unknown' OR (json_extract(policy.contract_json,'$.acceptance_required')=1 AND s.q_atoms>COALESCE((SELECT SUM(f.q_atoms) FROM delivery_facts f WHERE f.project_id=s.project_id AND f.shipment_id=s.id AND f.action='accept'),0)))))
      UNION ALL SELECT id,'commitment_change',reason,'change disposition pending' FROM commitment_changes WHERE project_id=? AND state='pending'
      UNION ALL SELECT id,'nonconformance',defect,'Mandatory nonconformance remains unresolved' FROM nonconformances n WHERE project_id=? AND NOT EXISTS(SELECT 1 FROM quality_dispositions d WHERE d.unit_id=n.unit_id AND d.decision='scrap') AND NOT EXISTS(SELECT 1 FROM rework_orders r JOIN rework_completions c ON c.rework_order_id=r.id WHERE r.nonconformance_id=n.id)
      UNION ALL SELECT id,'rma',reason,'Customer quality feedback remains open' FROM rmas r WHERE project_id=? AND NOT EXISTS(SELECT 1 FROM capas c WHERE c.rma_id=r.id AND c.state='closed')
      UNION ALL SELECT s.id,'shipment',i.title,'Required acceptance issue: '||i.owner_name FROM acceptance_issues i JOIN shipments s ON s.id=i.shipment_id WHERE i.project_id=? AND i.required=1 AND NOT EXISTS(SELECT 1 FROM acceptance_resolutions r WHERE r.issue_id=i.id)
      UNION ALL SELECT c.id,'capa','CAPA investigation','Mandatory CAPA remains open' FROM capas c WHERE c.project_id=? AND c.state='open'
      UNION ALL SELECT e.id,'exchange',e.system||' source reconciliation','Responsible source discrepancy requires reconciliation' FROM exchanges e WHERE e.project_id=? AND e.phase NOT IN ('accepted','posted') AND EXISTS(SELECT 1 FROM exchange_discrepancies d WHERE d.exchange_id=e.id AND d.resolves_seq IS NULL AND d.reason<>'Authority rejected request' AND NOT EXISTS(SELECT 1 FROM exchange_discrepancies r WHERE r.resolves_seq=d.seq))
      UNION ALL SELECT COALESCE(m.unit_id,m.lot_id),CASE WHEN m.unit_id IS NULL THEN 'material_lot' ELSE 'unit' END,COALESCE(u.sn,l.lot_id),'Containment pending or frozen' FROM freeze_requests r JOIN freeze_members m ON m.request_id=r.id LEFT JOIN units u ON u.id=m.unit_id LEFT JOIN material_lots l ON l.id=m.lot_id LEFT JOIN freeze_confirmations f ON f.project_id=m.project_id AND f.object_kind=CASE WHEN m.unit_id IS NULL THEN 'material_lot' ELSE 'unit' END AND f.object_id=COALESCE(m.unit_id,m.lot_id) WHERE r.project_id=? AND r.seq=(SELECT MAX(x.seq) FROM freeze_requests x JOIN freeze_members y ON y.request_id=x.id WHERE y.project_id=m.project_id AND COALESCE(y.unit_id,y.lot_id)=COALESCE(m.unit_id,m.lot_id)) AND (f.request_id IS NULL OR f.source_version<r.source_version OR f.state='frozen')
      UNION ALL SELECT u.id,'unit',u.sn,'Latest measured evidence is failed or currently invalid' FROM units u JOIN quality_tests t ON t.unit_id=u.id WHERE u.project_id=? AND t.attempt=(SELECT MAX(q.attempt) FROM quality_tests q WHERE q.unit_id=u.id) AND (t.outcome='fail' OR NOT EXISTS(SELECT 1 FROM valid_quality_tests v WHERE v.id=t.id AND v.project_id=t.project_id)) AND NOT EXISTS(SELECT 1 FROM quality_dispositions d WHERE d.unit_id=u.id AND d.decision='scrap')
    ) ORDER BY kind,id LIMIT 51""",
        (pid,) * 9,
    ).fetchall()
    blockers = [
        ObjectSummary(
            id=r["id"],
            project_id=pid,
            kind=r["kind"],
            title=r["title"],
            state="blocked",
            version=1,
            blocking_reasons=[r["reason"]],
        )
        for r in rows[:50]
    ]
    from .readiness import evaluate

    work_orders = tx.execute(
        "SELECT id,source_external_id FROM effective_work_orders WHERE project_id=? AND obligation_atoms>0 ORDER BY planned_start,id LIMIT 21",
        (pid,),
    ).fetchall()
    readiness_checks = []
    now = business_time(tx)
    for work_order in work_orders[:20]:
        checks = [
            evaluate(tx, pid, work_order["id"], mode, now) for mode in ("trial", "bulk")
        ]
        blocked = [
            c
            for result in checks
            for c in result.checks
            if c.required and c.status == "blocked"
        ]
        readiness_checks.extend(blocked)
        if blocked:
            blockers.append(
                ObjectSummary(
                    id=work_order["id"],
                    kind="work_order",
                    project_id=pid,
                    title=work_order["source_external_id"],
                    state="blocked",
                    version=1,
                    blocking_reasons=list(dict.fromkeys(c.reason for c in blocked)),
                )
            )
    stage_tables = (
        "demands",
        "engineering_revisions",
        "plans",
        "material_lots",
        "work_orders",
        "execution_events",
        "quality_tests",
        "shipments",
        "rmas",
    )
    stages = [
        ProjectStageView(
            stage=f"S{i + 1}",
            status="active" if counts[t] else "pending",
            reason=f"{counts[t]} actual records; completion requires current domain evidence",
        )
        for i, t in enumerate(stage_tables)
    ]
    for index, kinds in (
        (1, {"version", "customer"}),
        (2, {"plan"}),
        (3, {"material", "equipment", "people"}),
        (
            4,
            {
                "version",
                "customer",
                "plan",
                "material",
                "equipment",
                "people",
                "first_article",
            },
        ),
    ):
        reasons = list(
            dict.fromkeys(c.reason for c in readiness_checks if c.kind in kinds)
        )
        if reasons:
            stages[index] = ProjectStageView(
                stage=f"S{index + 1}",
                status="blocked",
                reason="; ".join(reasons)[:2000],
            )
    if closures["quality"].status == "blocked":
        stages[6] = ProjectStageView(
            stage="S7",
            status="blocked",
            reason="; ".join(closures["quality"].blocking_reasons)[:2000],
        )
    stages[7] = ProjectStageView(
        stage="S8",
        status="complete"
        if closures["fulfillment"].status == "closed"
        else "blocked"
        if closures["fulfillment"].status == "blocked"
        else "active",
        reason="; ".join(closures["fulfillment"].blocking_reasons)[:2000]
        or "Delivery predicates currently satisfied",
    )
    stages[8] = ProjectStageView(
        stage="S9",
        status="complete"
        if all(c.status == "closed" for c in closures.values())
        else "blocked"
        if any(c.status == "blocked" for c in closures.values())
        else "active",
        reason="Fulfillment, quality and cost close independently",
    )
    return ProgressSummary(
        stages=stages,
        blocking_objects=blockers[:50],
        blockers_truncated=len(rows) > 50
        or len(blockers) > 50
        or len(work_orders) > 20,
        **closures,
    )
