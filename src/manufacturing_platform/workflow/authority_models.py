"""Mapping registration is evidence, never a production routing command."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from .commands import WorkflowCommand
from .contracts import DomainValue, ObjectKind, StrictModel
from .introduction_models import Name, Text


class RegisterAuthority(WorkflowCommand):
    action: Literal["authority.register"]
    object_category: ObjectKind
    business_scope: Name
    system: Name
    responsible_identity: Name
    evidence: Text
    origin: Literal["manual", "demo"]


class VerifyAuthority(WorkflowCommand):
    action: Literal["authority.verify"]
    rule_id: UUID
    contract_evidence: Text


class AuthorityVerification(StrictModel):
    contract_evidence: Text
    actor_id: UUID
    recorded_at: datetime


class AuthorityRule(DomainValue):
    kind: Literal["authority_rule"] = "authority_rule"
    id: UUID
    object_category: ObjectKind
    business_scope: Name
    system: Name
    responsible_identity: Name
    evidence: Text
    origin: Literal["manual", "demo"]
    revision: int
    supersedes_id: UUID | None
    actor_id: UUID
    recorded_at: datetime
    active: bool
    state: Literal["registered", "verified"]
    connection_state: Literal["unconnected", "demo"]
    verification: AuthorityVerification | None
