"""Strict engineering introduction and immutable reuse contracts."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictBool, StringConstraints, model_validator

from .commands import WorkflowCommand
from .contracts import DomainValue, StrictModel

Text = Annotated[
    str,
    StringConstraints(
        strict=True, strip_whitespace=True, min_length=1, max_length=2000
    ),
]
Name = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200),
]


class OpenNPI(WorkflowCommand):
    action: Literal["npi.open"]
    revision_id: UUID
    product_family: Name
    scenario: Literal["first_introduction", "change_validation"]
    required_checks: list[Name] = Field(min_length=1, max_length=100)
    work_order_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.required_checks)) != len(self.required_checks) or len(
            set(self.work_order_ids)
        ) != len(self.work_order_ids):
            raise ValueError("duplicate scope or check")
        return self


class ReviewCheck(StrictModel):
    code: Name
    required: StrictBool
    decision: Literal["pass", "blocked", "not_applicable"]
    evidence: Text
    reason: Text


class ReviewNPI(WorkflowCommand):
    action: Literal["npi.review"]
    npi_id: UUID
    checks: list[ReviewCheck] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique(self):
        if len({c.code for c in self.checks}) != len(self.checks):
            raise ValueError("duplicate review check")
        return self


class TrialNPI(WorkflowCommand):
    action: Literal["npi.trial"]
    npi_id: UUID
    work_order_id: UUID
    test_ids: list[UUID] = Field(min_length=1, max_length=100)
    evidence: Text


class IssueNPI(WorkflowCommand):
    action: Literal["npi.issue"]
    npi_id: UUID
    phenomenon: Text
    risk: Text
    containment: Text


class ResolveNPI(WorkflowCommand):
    action: Literal["npi.resolve"]
    issue_id: UUID
    verified_cause: Text
    countermeasure: Text
    verification_evidence: Text
    test_ids: list[UUID] = Field(default_factory=list, max_length=100)


class ApproveNPI(WorkflowCommand):
    action: Literal["npi.approve"]
    npi_id: UUID
    evidence: Text


class AssetContent(StrictModel):
    title: Name
    category: Literal["check", "process_module", "test_module"]
    product_families: list[Name] = Field(min_length=1, max_length=100)
    execution_content: Text
    verification_method: Text


class PublishAsset(WorkflowCommand):
    action: Literal["asset.publish"]
    issue_id: UUID
    content: AssetContent
    # Explicit separately authored public material; admin command acceptance is approval.
    public_content: AssetContent | None = None
    supersedes_id: UUID | None = None


class ApplyAsset(WorkflowCommand):
    action: Literal["asset.apply"]
    npi_id: UUID
    asset_revision_id: UUID
    required: StrictBool


class VerifyAsset(WorkflowCommand):
    action: Literal["asset.verify"]
    asset_use_id: UUID
    decision: Literal["pass", "blocked", "not_applicable"]
    evidence: Text


class ReviewRecord(StrictModel):
    id: UUID
    checks: list[ReviewCheck]
    actor_id: UUID
    recorded_at: datetime


class TrialRecord(StrictModel):
    outcome: Literal["pass", "fail"]
    qualified: StrictBool
    id: UUID
    work_order_id: UUID
    test_ids: list[UUID]
    evidence: Text
    actor_id: UUID
    recorded_at: datetime


class ApprovalRecord(StrictModel):
    id: UUID
    generation: int
    evidence: Text
    actor_id: UUID
    recorded_at: datetime


class NPI(DomainValue):
    kind: Literal["npi"] = "npi"
    revision_id: UUID
    product_family: Name
    scenario: Literal["first_introduction", "change_validation"]
    required_checks: list[Name]
    work_order_ids: list[UUID]
    state: Literal["open", "approved"]
    bulk_eligible: bool
    blocking_reasons: list[str]
    reviews: list[ReviewRecord]
    trials: list[TrialRecord]
    approvals: list[ApprovalRecord]


class IssueResolution(StrictModel):
    verified_cause: Text
    countermeasure: Text
    verification_evidence: Text
    test_ids: list[UUID]
    actor_id: UUID
    recorded_at: datetime


class NPIIssue(DomainValue):
    kind: Literal["npi_issue"] = "npi_issue"
    npi_id: UUID
    phenomenon: Text
    risk: Text
    containment: Text
    state: Literal["open", "resolved", "unverified"]
    verified: StrictBool
    resolution: IssueResolution | None
    resolutions: list[IssueResolution]


class ReusableAsset(DomainValue):
    kind: Literal["reusable_asset"] = "reusable_asset"
    issue_id: UUID
    content: AssetContent
    public_content: AssetContent | None
    supersedes_id: UUID | None
    revision: int
    published_by: UUID
    published_at: datetime


class AssetVerification(StrictModel):
    id: UUID
    decision: Literal["pass", "blocked", "not_applicable"]
    evidence: Text
    actor_id: UUID
    recorded_at: datetime


class AssetUse(DomainValue):
    kind: Literal["asset_use"] = "asset_use"
    npi_id: UUID
    asset_revision_id: UUID
    revision: int
    snapshot: AssetContent
    required: StrictBool
    verifications: list[AssetVerification]


class PublicAssetEntry(StrictModel):
    asset_revision_id: UUID
    revision: int
    content: AssetContent


class PublicAssetPage(StrictModel):
    items: list[PublicAssetEntry]
    total: int
    limit: int
    offset: int
