"""Bounded, deterministic rules over authorized stored facts, without mutations."""

import json
from typing import Literal
from uuid import UUID

from pydantic import Field

from .contracts import (
    MaterialBalance,
    NonnegativeQuantity,
    ObjectKind,
    SourceRef,
    StrictModel,
)
from .feedback_models import CapaStep
from .introduction_models import PublicAssetEntry
from .quality_models import Measurement
from .queries import OBJECT_REGISTRY

AssistanceKind = Literal[
    "introduction", "materials", "change", "knowledge", "testing", "quality"
]
LIMIT = 100
SOURCE_KINDS = {
    "introduction": ["npi", "npi_issue"],
    "materials": ["requirement", "receipt", "arrival"],
    "change": ["eco"],
    "knowledge": ["asset_use"],
    "testing": ["test", "test_run"],
    "quality": ["nonconformance", "rma", "capa"],
}
IMPACT_KINDS = {
    "purchase": "commitment",
    "stock": "material_lot",
    "wip": "unit",
    "work_order": "work_order",
    "unit": "unit",
}


class AssistanceTarget(StrictModel):
    scope: Literal["project", "public_catalog"]
    project_id: UUID | None = None
    kind: ObjectKind
    id: UUID


class ReceiptQuantities(StrictModel):
    accepted: NonnegativeQuantity
    rejected: NonnegativeQuantity
    pending: NonnegativeQuantity
    unit: str


class TestingEvidence(StrictModel):
    revision_id: UUID
    program_version: str
    run_state: Literal["running", "completed", "aborted", "invalid"] | None
    outcome: Literal["pass", "fail"] | None
    measurements: list[Measurement]
    failed_measurements: list[Measurement]
    current_qualified: bool | None
    origin: Literal["manual", "demo"] | None
    comparison_basis: Literal["same_revision_and_program"] = "same_revision_and_program"
    similar_targets: list[AssistanceTarget] = Field(default_factory=list, max_length=20)


class QualityOutline(StrictModel):
    format: Literal["8d_evidence_draft"] = "8d_evidence_draft"
    facts: list[str]
    containment: list[CapaStep] = Field(default_factory=list)
    registered_causes: list[CapaStep] = Field(default_factory=list)
    actions: list[CapaStep] = Field(default_factory=list)
    verification: list[CapaStep] = Field(default_factory=list)
    disposition: str | None = None
    disposition_evidence: str | None = None
    missing_fields: list[str]


class AssistanceItem(StrictModel):
    target: AssistanceTarget
    title: str
    state: str
    suggestion: str
    blockers: list[str]
    unknowns: list[str]
    evidence: list[str]
    related_targets: list[AssistanceTarget] = Field(default_factory=list)
    source: SourceRef | None = None
    quantities: ReceiptQuantities | None = None
    material_balance: MaterialBalance | None = None
    public_asset: PublicAssetEntry | None = None
    testing: TestingEvidence | None = None
    quality_outline: QualityOutline | None = None
    evidence_truncated: bool = False


class AssistanceResult(StrictModel):
    project_id: UUID
    kind: AssistanceKind
    mode: Literal["rules"] = "rules"
    state: Literal["evidence_available", "no_evidence"]
    source_scope: Literal["authorized_project_and_approved_public_catalog"] = (
        "authorized_project_and_approved_public_catalog"
    )
    items: list[AssistanceItem]
    unknowns: list[str]
    truncated: bool


def project_target(pid, kind, ident):
    return AssistanceTarget(scope="project", project_id=pid, kind=kind, id=ident)


def object_item(tx, pid, summary):
    if summary.kind == ObjectKind.arrival:
        return arrival_item(tx, pid, summary)
    detail = OBJECT_REGISTRY.detail(tx, pid, summary.kind, summary.id)
    value = detail.value
    item = AssistanceItem(
        target=project_target(pid, summary.kind, summary.id),
        title=summary.title,
        state=summary.state,
        suggestion="Review the referenced record and its current evidence",
        blockers=summary.blocking_reasons,
        unknowns=[],
        evidence=[e.reference for e in detail.evidence],
        source=summary.source,
        related_targets=[project_target(pid, r.kind, r.id) for r in detail.relations],
    )
    if summary.kind == ObjectKind.npi:
        item.suggestion = "Review missing checks and unresolved introduction evidence"
        item.blockers = value.blocking_reasons
        item.unknowns = ["Customer approval and unrecorded checks are not inferred"]
    elif summary.kind == ObjectKind.npi_issue and not value.verified:
        item.suggestion = "Record and verify resolution evidence through the issue workflow"
        item.blockers = ["Issue resolution lacks current qualified verification"]
    elif summary.kind == ObjectKind.requirement:
        item.suggestion = "Review actual material shortage and authority-confirmed reservations"
        item.material_balance = value.balance
        item.blockers = value.balance.blocking_reasons
        item.unknowns = [
            "Unobserved packages cannot be treated as received or available stock"
        ]
    elif summary.kind == ObjectKind.receipt:
        item.suggestion = (
            "Inspect remaining receipt quantity through the quality workflow" if value.uninspected
            else "Review rejected quantity through the quality workflow" if value.rejected
            else "Review authority-confirmed reservation eligibility"
        )
        item.quantities = ReceiptQuantities(
            accepted=str(value.accepted),
            rejected=str(value.rejected),
            pending=str(value.uninspected),
            unit=value.unit,
        )
        item.blockers = (
            (["Inspection remains pending"] if value.uninspected else [])
            + (["Rejected quantity is not qualified stock"] if value.rejected else [])
        )
    elif summary.kind == ObjectKind.eco:
        item.suggestion = "Review explicit affected objects and unresolved change dispositions"
        item.related_targets.extend(
            project_target(pid, IMPACT_KINDS[impact.type], impact.object_id)
            for impact in value.impacts
        )
        item.blockers = [
            f"Unresolved {impact.type}: {impact.id}"
            for impact in value.impacts
            if impact.resolved_quantity < impact.quantity
        ]
        item.unknowns = ["Unrecorded external change effects are unknown"]
    elif summary.kind in {ObjectKind.test, ObjectKind.test_run}:
        is_run = summary.kind == ObjectKind.test_run
        measurements = value.finish.measurements if is_run and value.finish else (
            [] if is_run else value.measurements
        )
        item.testing = TestingEvidence(
            revision_id=value.revision_id,
            program_version=value.scope.program_version,
            run_state=value.state if is_run else None,
            outcome=value.outcome,
            measurements=measurements,
            failed_measurements=[
                m for m in measurements if m.value < m.lower or m.value > m.upper
            ],
            current_qualified=None if is_run else value.current_qualified,
            origin=value.raw.origin if is_run and value.raw else None,
        )
        item.source = value.finish.source if is_run and value.finish else (
            None if is_run else value.source
        )
        if item.source:
            item.evidence.append(item.source.evidence)
        item.suggestion = "Review recorded measurements, run state and comparable scoped evidence"
        item.unknowns = [
            "Measurements and similar records establish no cause, causal proof or prediction",
            "Unrecorded equipment conditions and root cause remain unknown",
        ]
    elif summary.kind in {ObjectKind.nonconformance, ObjectKind.rma, ObjectKind.capa}:
        item.quality_outline = quality_outline(value, summary.kind)
        item.suggestion = "Review the 8D evidence draft and explicitly missing investigation fields"
        item.unknowns = [
            "The draft does not establish team responsibility, root cause or effectiveness",
            "Registered causes and verification decisions are attributed records, not independently proven conclusions",
        ]
        if summary.kind == ObjectKind.capa:
            item.blockers = value.blocking_reasons
            item.evidence_truncated = value.steps_truncated
            item.evidence.extend(step.evidence for step in value.steps)
        elif summary.kind == ObjectKind.nonconformance:
            item.evidence.append(value.evidence)
            item.related_targets.append(project_target(pid, "test", value.test_id))
        else:
            item.source = value.source
            item.evidence_truncated = value.tests_truncated
            item.related_targets.extend(
                project_target(pid, "test", ident) for ident in value.test_ids
            )
            if value.source:
                item.evidence.append(value.source.evidence)
    return item


def arrival_item(tx, pid, summary):
    from .arrival import assistance_projection, relations

    value, truncated = assistance_projection(tx, pid, summary.id, limit=LIMIT)
    item = AssistanceItem(
        target=project_target(pid, summary.kind, summary.id),
        title=summary.title,
        state=value.state,
        suggestion="Review the referenced record and its current evidence",
        blockers=summary.blocking_reasons,
        unknowns=[],
        evidence=[value.source.evidence],
        source=value.source,
        related_targets=[project_target(pid, r.kind, r.id) for r in relations(value, pid)],
        evidence_truncated=truncated,
    )
    if not value.receipt_id:
        item.suggestion = "Check package identity against an actual same-project receipt"
        item.unknowns.append(
            "Material, sender and purchase identity remain unverified until checked against receipt evidence"
        )
    if truncated:
        item.unknowns.append(
            f"Only the most recent {LIMIT} arrival match references are shown; older correction evidence is unknown in this analysis"
        )
    return item


def quality_outline(value, kind):
    if kind != ObjectKind.capa:
        return QualityOutline(
            facts=[value.defect if kind == ObjectKind.nonconformance else value.reason],
            disposition=value.disposition if kind == ObjectKind.nonconformance else None,
            disposition_evidence=(
                value.disposition_evidence if kind == ObjectKind.nonconformance else None
            ),
            missing_fields=[
                "team", "containment", "root_cause", "correction",
                "verification", "prevention", "recognition",
            ],
        )
    by_step = {
        name: [step for step in value.steps if step.step == name]
        for name in ("containment", "root_cause", "correction", "verification")
    }
    return QualityOutline(
        facts=[f"Registered CAPA state: {value.state}"],
        containment=by_step["containment"],
        registered_causes=by_step["root_cause"],
        actions=by_step["correction"],
        verification=by_step["verification"],
        missing_fields=["team", "prevention", "recognition"] + [
            name for name, steps in by_step.items() if not steps
        ],
    )


def compare_testing(items):
    for item in items:
        peers = [
            other.target for other in items
            if other.target.id != item.target.id
            and other.target.kind == item.target.kind
            and other.testing.revision_id == item.testing.revision_id
            and other.testing.program_version == item.testing.program_version
        ]
        item.testing.similar_targets = peers[:20]
        if len(peers) > 20:
            item.evidence_truncated = True
            item.unknowns.append("Only the first 20 scoped comparison references are shown")


def applicable_assets(tx, pid):
    # Applicability is grounded in the project's actual introduction families.
    family_rows = tx.execute(
        "SELECT DISTINCT product_family FROM npis WHERE project_id=? "
        "ORDER BY product_family LIMIT ?", (str(pid), LIMIT + 1),
    ).fetchall()
    families = {row[0] for row in family_rows[:LIMIT]}
    rows = tx.execute(
        "SELECT * FROM reusable_assets WHERE project_id=? OR public_content_json IS NOT NULL "
        "ORDER BY seq LIMIT ?", (str(pid), LIMIT + 1),
    ).fetchall()
    items = []
    for row in rows[:LIMIT]:
        local = row["project_id"] == str(pid)
        content = json.loads(row["content_json"] if local else row["public_content_json"])
        if not families.intersection(content["product_families"]):
            continue
        # Foreign references expose only the approved catalog entry, never source project/issue.
        entry = PublicAssetEntry(
            asset_revision_id=row["id"], revision=row["revision"], content=content
        )
        items.append(
            AssistanceItem(
                target=AssistanceTarget(
                    scope="project" if local else "public_catalog",
                    project_id=pid if local else None,
                    kind="reusable_asset",
                    id=row["id"],
                ),
                title=content["title"],
                state="published",
                suggestion="Review applicability before explicit asset application and verification",
                blockers=[],
                unknowns=["Applicability still requires explicit application and verification"],
                evidence=["Approved published asset revision"],
                public_asset=entry,
            )
        )
    return items, len(rows) > LIMIT or len(family_rows) > LIMIT


def analyze(tx, pid, kind):
    items = []
    truncated = False
    for object_kind in SOURCE_KINDS[kind]:
        object_kind = ObjectKind(object_kind)
        truncated |= OBJECT_REGISTRY.count(tx, pid, object_kind) > LIMIT
        items.extend(
            object_item(tx, pid, summary)
            for summary in OBJECT_REGISTRY.summaries(
                tx, pid, object_kind, limit=LIMIT, offset=0
            )
        )
    if kind == "testing":
        compare_testing(items)
    truncated |= any(item.evidence_truncated for item in items)
    if kind == "knowledge":
        assets, asset_truncated = applicable_assets(tx, pid)
        items.extend(assets)
        truncated |= asset_truncated
    unknowns = [
        "External production connection status and facts outside this scoped evidence are unknown",
        "Rules produce review suggestions; no model invocation, root-cause validation or customer approval is implied",
    ]
    if not items:
        unknowns.append("No applicable authorized evidence is recorded for this analysis")
    if truncated:
        unknowns.append(
            "Evidence was truncated: at most the first 100 records per source category and each item's disclosed evidence limit were examined; further evidence is unknown"
        )
    return AssistanceResult(
        project_id=pid,
        kind=kind,
        state="evidence_available" if items else "no_evidence",
        items=items,
        unknowns=unknowns,
        truncated=truncated,
    )
