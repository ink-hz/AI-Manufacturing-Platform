"""Manual, append-only issue evidence; stages do not imply accounting changes."""
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime

from .commands import WorkflowCommand
from .contracts import DomainValue, SourceRef
from .introduction_models import Name, Text

IssueStage = Literal["printed", "picked", "receipted", "posted"]


class MarkIssue(WorkflowCommand):
    action: Literal["issue.mark"]
    requirement_id: UUID
    stage: IssueStage
    note: Text | None = None
    occurred_at: AwareDatetime | None = None


class IssueMark(DomainValue):
    kind: Literal["issue_mark"] = "issue_mark"
    id: UUID
    requirement_id: UUID
    work_order_id: UUID
    material_id: str
    stage: IssueStage
    note: Text | None = None
    actor_id: UUID
    actor_name: Name
    occurred_at: AwareDatetime
    recorded_at: AwareDatetime
    source: SourceRef
