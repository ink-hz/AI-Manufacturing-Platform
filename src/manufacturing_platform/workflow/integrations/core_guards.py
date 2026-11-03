"""Serialize cooperating physical/eligibility writers before opening source writers."""

import fcntl
import os
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID

from ..contracts import DomainError
from .contracts import IntegrationFact
from .store import identity


def require(condition, message):
    if not condition:
        raise DomainError("PRECONDITION_FAILED", 409, message)


@contextmanager
def project_guard(registry, project_id):
    """Task4 eligibility updates must take this same dataset/project flock.

    Never enter with a workflow/source write transaction open. Snapshot every
    other store before opening the owning source writer. No nested guard entry.
    """
    project_id = UUID(str(project_id))
    require(
        registry.workflow_store.dataset["mode"] in {"demo", "test"}, "Mock unavailable"
    )
    directory = registry.root / registry.workflow_store.dataset["id"] / "guards"
    directory.mkdir(parents=True, exist_ok=True)
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError("Aliased project guard path")
    fd = os.open(
        directory / f"{project_id}.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600
    )
    try:
        if os.fstat(fd).st_nlink != 1:
            raise ValueError("Aliased project guard file")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class SourceSnapshot:
    """Immutable observations collected under the guard, before any source writer."""

    def __init__(self, registry, project_id):
        self.project_id = project_id
        self.facts = {}
        self.acks = {}
        for store in registry.existing_stores():
            with store.transaction() as tx:
                for row in tx.execute(
                    "SELECT fact_json FROM facts WHERE project_id=? ORDER BY sequence",
                    (str(project_id),),
                ):
                    fact = IntegrationFact.model_validate_json(row[0])
                    self.facts[identity(project_id, fact.source_key)] = fact
                for row in tx.execute(
                    "SELECT o.system,o.object_type,o.external_id,o.version,o.consumer,a.receipt_json FROM outbox o LEFT JOIN acknowledgments a ON a.delivery_id=o.id WHERE o.project_id=?",
                    (str(project_id),),
                ):
                    self.acks[
                        (
                            *identity(project_id, SimpleNamespace(**dict(row)))[:5],
                            row["consumer"],
                        )
                    ] = row["receipt_json"]

    def fact(self, key):
        fact = self.facts.get(identity(self.project_id, key))
        require(fact is not None, "Exact causal source is unavailable")
        return fact

    def of_type(self, tag):
        return [f for f in self.facts.values() if f.payload.fact_type == tag]

    def containment(self, *, lot_ids=(), unit_ids=()):
        lots, units = set(map(str, lot_ids)), set(map(str, unit_ids))
        latest = {}
        for fact in self.of_type("mes.containment"):
            for kind, values in (
                ("lot", fact.payload.material_lot_ids),
                ("unit", fact.payload.unit_ids),
            ):
                for value in values:
                    latest[kind, str(value)] = fact
        for key, fact in latest.items():
            if (key[0] == "lot" and key[1] in lots) or (
                key[0] == "unit" and key[1] in units
            ):
                self.acknowledged(fact)
                require(fact.payload.decision == "unfrozen", "Scope is frozen")

    def acknowledged(self, fact):
        from .contracts import DeliveryReceipt

        for target in ("wms", "sap"):
            raw = self.acks.get((*identity(self.project_id, fact.source_key), target))
            require(
                raw is not None
                and DeliveryReceipt.model_validate_json(raw).phase == "accepted",
                "Containment acknowledgment pending or unknown",
            )
