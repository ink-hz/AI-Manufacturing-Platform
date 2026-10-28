"""Append-only customer conditions applicable to one immutable revision."""

import json
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field

from .commands import COMMAND_REGISTRY, WorkflowCommand
from .contracts import ContractPolicy, DomainError, MutationResult, StrictModel


class AgreeContract(WorkflowCommand):
    action: Literal["contract.agree"]
    revision_id: UUID
    supersedes_agreement_id: UUID | None = None
    contract: ContractPolicy
    customer_id: str = Field(min_length=1, max_length=200, pattern=r"\S")
    external_signatory: str = Field(min_length=1, max_length=200, pattern=r"\S")
    evidence: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class AgreementView(StrictModel):
    id: UUID
    supersedes_agreement_id: UUID | None
    revision_id: UUID
    contract: ContractPolicy
    customer_id: str
    external_signatory: str
    evidence: str
    project_version: int
    recorded_at: str


def latest(tx, pid, revision_id, *, at=None):
    # Server acceptance order is authoritative; at only restricts prospective
    # use of evidence and is never a caller-controlled agreement effective date.
    return tx.execute(
        "SELECT * FROM contract_agreements WHERE project_id=? AND revision_id=? AND (? IS NULL OR julianday(created_at)<=julianday(?)) ORDER BY project_version DESC LIMIT 1",
        (
            str(pid),
            str(revision_id),
            at.isoformat() if at else None,
            at.isoformat() if at else None,
        ),
    ).fetchone()


def applicable(tx, pid, revision_id, *, at=None):
    if at is None:
        row = tx.execute(
            "SELECT contract_json FROM current_revision_contracts WHERE project_id=? AND revision_id=?",
            (str(pid), str(revision_id)),
        ).fetchone()
        if row:
            return json.loads(row[0])
    row = latest(tx, pid, revision_id, at=at)
    if row:
        return json.loads(row["contract_json"])
    return json.loads(
        tx.execute(
            "SELECT contract_json FROM projects WHERE id=?", (str(pid),)
        ).fetchone()[0]
    )


def view(tx, pid, revision_id):
    row = latest(tx, pid, revision_id)
    if row is None:
        return None
    return AgreementView(
        id=row["id"],
        revision_id=row["revision_id"],
        supersedes_agreement_id=row["supersedes_id"],
        contract=json.loads(row["contract_json"]),
        customer_id=row["customer_id"],
        external_signatory=row["external_signatory"],
        evidence=row["evidence"],
        project_version=row["project_version"],
        recorded_at=row["created_at"],
    )


def agree(tx, context, command):
    from .orders import own, project

    pid = context.project_id
    revision = own(tx, "engineering_revisions", pid, command.revision_id)
    p = project(tx, pid)

    def fail(reason):
        raise DomainError("PRECONDITION_FAILED", 409, reason, blocking_reasons=[reason])

    if (
        command.customer_id != p["customer_id"]
        or command.contract.customer_revision != revision["customer_revision"]
        or command.contract.internal_revision != revision["internal_revision"]
    ):
        fail(
            "Agreement must match this customer and exact fixed customer/internal revision"
        )
    prior = latest(tx, pid, command.revision_id)
    if (prior["id"] if prior else None) != (
        str(command.supersedes_agreement_id)
        if command.supersedes_agreement_id
        else None
    ):
        fail("Agreement predecessor changed; review the current scoped conditions")
    old = json.loads(prior["contract_json"] if prior else p["contract_json"])
    same_scope = prior or (
        old["customer_revision"] in {"unknown", revision["customer_revision"]}
        and old["internal_revision"] in {"unknown", revision["internal_revision"]}
    )
    new = command.contract.model_dump(mode="json")
    if same_scope and any(
        value != "unknown" and value != new[key] for key, value in old.items()
    ):
        fail(
            "Known conditions of an existing revision remain fixed; only unknown conditions may be confirmed"
        )
    ident = str(uuid4())
    tx.execute(
        "INSERT INTO contract_agreements(id,project_id,revision_id,supersedes_id,contract_json,customer_id,external_signatory,evidence,project_version,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            ident,
            str(pid),
            revision["id"],
            prior["id"] if prior else None,
            command.contract.model_dump_json(),
            command.customer_id,
            command.external_signatory,
            command.evidence,
            context.project_version + 1,
            context.now.isoformat(),
        ),
    )
    return MutationResult(object_type="revision", object_id=command.revision_id)


COMMAND_REGISTRY.register(
    AgreeContract, roles={"project_owner"}, qualifications=set(), handler=agree
)
