"""Independent source transactions. Callbacks are trusted typed family code, never HTTP data."""

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from stat import S_ISLNK, S_ISREG
from time import monotonic, sleep
from uuid import NAMESPACE_URL, UUID, uuid5

from ..contracts import DomainError
from .catalog import EDGES, SYSTEM_IDS
from .contracts import (
    DeliveryReceipt,
    FactPage,
    IntegrationFact,
    NetworkDelivery,
    SourceKey,
    SystemError,
    SystemOperation,
    SystemReceipt,
)


def canonical(value):
    return json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def canonical_hash(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def identity(project_id, key):
    return (str(project_id), key.system, key.object_type, key.external_id, key.version)


def conflict(message):
    raise DomainError("SOURCE_CONFLICT", 409, message)


SCHEMA = """
CREATE TABLE metadata(dataset_id TEXT NOT NULL,system_id TEXT NOT NULL,schema_version INTEGER NOT NULL);
CREATE TABLE operations(project_id TEXT NOT NULL,id TEXT NOT NULL,payload_hash TEXT NOT NULL,payload_json TEXT NOT NULL,receipt_json TEXT NOT NULL,PRIMARY KEY(project_id,id));
CREATE TABLE facts(sequence INTEGER PRIMARY KEY AUTOINCREMENT,project_id TEXT NOT NULL,system TEXT NOT NULL,object_type TEXT NOT NULL,external_id TEXT NOT NULL,version INTEGER NOT NULL,payload_hash TEXT NOT NULL,fact_json TEXT NOT NULL,UNIQUE(project_id,system,object_type,external_id,version));
CREATE INDEX facts_page ON facts(project_id,object_type,sequence);
CREATE TABLE fact_origins(project_id TEXT NOT NULL,system TEXT NOT NULL,object_type TEXT NOT NULL,external_id TEXT NOT NULL,version INTEGER NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('operation','inbox')),origin_id TEXT NOT NULL,PRIMARY KEY(project_id,system,object_type,external_id,version),FOREIGN KEY(project_id,system,object_type,external_id,version) REFERENCES facts(project_id,system,object_type,external_id,version));

CREATE TABLE outbox(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,consumer TEXT NOT NULL,system TEXT NOT NULL,object_type TEXT NOT NULL,external_id TEXT NOT NULL,version INTEGER NOT NULL,payload_hash TEXT NOT NULL,delivery_json TEXT NOT NULL,UNIQUE(project_id,consumer,system,object_type,external_id,version));
CREATE INDEX outbox_project ON outbox(project_id,id);
CREATE TABLE acknowledgments(delivery_id TEXT PRIMARY KEY REFERENCES outbox(id),receipt_json TEXT NOT NULL);
CREATE TABLE inbox(project_id TEXT NOT NULL,producer TEXT NOT NULL,object_type TEXT NOT NULL,external_id TEXT NOT NULL,version INTEGER NOT NULL,delivery_id TEXT NOT NULL,payload_hash TEXT NOT NULL,fact_hash TEXT NOT NULL,receipt_json TEXT NOT NULL,PRIMARY KEY(project_id,producer,object_type,external_id,version),UNIQUE(project_id,delivery_id));
CREATE TABLE faults(project_id TEXT NOT NULL,operation_id TEXT NOT NULL,name TEXT NOT NULL,remaining INTEGER NOT NULL CHECK(remaining>=0),PRIMARY KEY(project_id,operation_id));
"""


@dataclass(frozen=True)
class ScheduledDelivery:
    position: int
    delivery: NetworkDelivery


class SystemStore:
    def __init__(
        self, root: Path, dataset_id: str, system, *, clock: Callable[[], datetime]
    ):
        if (
            system not in SYSTEM_IDS
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", dataset_id)
            or dataset_id in {".", ".."}
        ):
            raise ValueError("invalid fixed source identity")
        self.root = Path(root).absolute()
        self.dataset_id, self.system, self.clock = dataset_id, system, clock
        self.path = self.root / dataset_id / f"{system}.sqlite3"

    @staticmethod
    def _entry_aliased(p: Path) -> bool:
        # One atomic lstat per entry: the previous exists()/is_file()/stat() triple
        # raced SQLite sidecar lifecycle and intermittently surfaced OSError or a
        # stale anomalous link count as a 503. Absent entries are fine; a symlink or
        # a regular file with an extra hard link is an alias.
        try:
            st = os.lstat(p)
        except OSError:
            return False
        return S_ISLNK(st.st_mode) or (S_ISREG(st.st_mode) and st.st_nlink != 1)

    def _validate_path(self):
        # Every existing path component must be a real local entry (no churn here:
        # directories and the main database are never recycled by SQLite).
        for p in (*self.path.parents, self.path):
            if self._entry_aliased(p):
                raise ValueError("aliased source database")
        # SQLite creates and deletes -wal/-shm concurrently with readers. Only a
        # STABLE alias observation rejects; a transient anomaly that disappears on
        # immediate re-observation is normal sidecar churn, never a retry of any
        # business operation.
        for sidecar in (Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm")):
            for attempt in range(3):
                if not self._entry_aliased(sidecar):
                    break
                if attempt == 2:
                    raise ValueError("aliased source database")
                sleep(0.005)
        if self.path.exists() and not self.path.is_file():
            raise ValueError("invalid source database")

    def _metadata(self, tx):
        tables = tx.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        if tables:
            if "metadata" not in {r[0] for r in tables}:
                raise ValueError("unrecognized source database")
            rows = tx.execute(
                "SELECT dataset_id,system_id,schema_version FROM metadata"
            ).fetchall()
            if len(rows) != 1 or tuple(rows[0]) != (self.dataset_id, self.system, 1):
                raise ValueError("source metadata mismatch")
        return bool(tables)

    @staticmethod
    def _enable_wal(tx):
        # SQLite's journal-mode upgrade can report BUSY immediately during first
        # concurrent opens despite busy_timeout. Retry only this pre-transaction
        # configuration; never replay an operation or consumer callback.
        deadline = monotonic() + 5
        while True:
            try:
                if tx.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                    tx.execute("PRAGMA journal_mode=WAL")
                return
            except sqlite3.OperationalError as exc:
                if (
                    getattr(exc, "sqlite_errorcode", None)
                    not in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
                    or monotonic() >= deadline
                ):
                    raise
                sleep(0.01)

    @contextmanager
    def transaction(self, write=False):
        self._validate_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tx = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        tx.row_factory = sqlite3.Row
        try:
            tx.execute("PRAGMA foreign_keys=ON")
            # Reject foreign identity before WAL, then recheck under the writer lock:
            # another process may have initialized the same empty file meanwhile.
            tables = self._metadata(tx)
            self._enable_wal(tx)
            tx.execute("BEGIN IMMEDIATE" if write or not tables else "BEGIN")
            tables = self._metadata(tx)
            if not tables:
                for statement in SCHEMA.split(";"):
                    if statement.strip():
                        tx.execute(statement)
                tx.execute(
                    "INSERT INTO metadata VALUES (?,?,1)",
                    (self.dataset_id, self.system),
                )
                for table in (
                    "operations",
                    "facts",
                    "outbox",
                    "inbox",
                    "acknowledgments",
                    "fact_origins",
                ):
                    for action in ("UPDATE", "DELETE"):
                        tx.execute(
                            f"CREATE TRIGGER {table}_no_{action} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'immutable source history'); END"
                        )
                    # REPLACE would otherwise silently erase history without delete triggers.
                    cols = {
                        "operations": ("project_id", "id"),
                        "facts": (
                            "project_id",
                            "system",
                            "object_type",
                            "external_id",
                            "version",
                        ),
                        "outbox": ("id",),
                        "inbox": (
                            "project_id",
                            "producer",
                            "object_type",
                            "external_id",
                            "version",
                        ),
                        "acknowledgments": ("delivery_id",),
                        "fact_origins": (
                            "project_id",
                            "system",
                            "object_type",
                            "external_id",
                            "version",
                        ),
                    }[table]
                    predicate = " AND ".join(f"{c}=NEW.{c}" for c in cols)
                    tx.execute(
                        f"CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM {table} WHERE {predicate}) BEGIN SELECT RAISE(ABORT,'immutable source history'); END"
                    )
                for table, predicate in (
                    ("facts", "sequence=NEW.sequence"),
                    (
                        "outbox",
                        "project_id=NEW.project_id AND consumer=NEW.consumer AND system=NEW.system AND object_type=NEW.object_type AND external_id=NEW.external_id AND version=NEW.version",
                    ),
                    (
                        "inbox",
                        "project_id=NEW.project_id AND delivery_id=NEW.delivery_id",
                    ),
                ):
                    tx.execute(
                        f"CREATE TRIGGER {table}_alternate_no_replace BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM {table} WHERE {predicate}) BEGIN SELECT RAISE(ABORT,'immutable source history'); END"
                    )
            yield tx
            tx.commit()
        except BaseException:
            tx.rollback()
            raise
        finally:
            tx.close()

    def append_fact(self, tx, fact: IntegrationFact):
        fact = IntegrationFact.model_validate_json(canonical(fact))
        if fact.source.system != self.system:
            conflict("wrong source producer")
        key = identity(fact.project_id, fact.source_key)
        old = tx.execute(
            "SELECT sequence,payload_hash FROM facts WHERE project_id=? AND system=? AND object_type=? AND external_id=? AND version=?",
            key,
        ).fetchone()
        if old:
            if old["payload_hash"] != canonical_hash(fact):
                conflict("immutable fact changed")
            return old["sequence"]
        return tx.execute(
            "INSERT INTO facts(project_id,system,object_type,external_id,version,payload_hash,fact_json) VALUES (?,?,?,?,?,?,?)",
            (*key, canonical_hash(fact), canonical(fact)),
        ).lastrowid

    def get_fact(self, project_id, key: SourceKey):
        if key.system != self.system:
            conflict("wrong source producer")
        with self.transaction() as tx:
            row = tx.execute(
                "SELECT fact_json FROM facts WHERE project_id=? AND system=? AND object_type=? AND external_id=? AND version=?",
                identity(project_id, key),
            ).fetchone()
            if not row:
                raise DomainError("NOT_FOUND", 404, "Source fact not found")
            return IntegrationFact.model_validate_json(row[0])

    def list_facts(self, project_id, object_type, cursor=0, limit=50):
        if (
            type(cursor) is not int
            or cursor < 0
            or type(limit) is not int
            or not 1 <= limit <= 200
        ):
            raise DomainError("INVALID_PAGINATION", 422, "Invalid source pagination")
        with self.transaction() as tx:
            cutoff = tx.execute(
                "SELECT COALESCE(MAX(sequence),0) FROM facts WHERE project_id=?",
                (str(project_id),),
            ).fetchone()[0]
            rows = tx.execute(
                "SELECT sequence,fact_json FROM facts WHERE project_id=? AND object_type=? AND sequence>? AND sequence<=? ORDER BY sequence LIMIT ?",
                (str(project_id), object_type, cursor, cutoff, limit + 1),
            ).fetchall()
            return FactPage(
                project_id=project_id,
                records=[
                    IntegrationFact.model_validate_json(r["fact_json"])
                    for r in rows[:limit]
                ],
                continuation=rows[limit - 1]["sequence"] if len(rows) > limit else None,
                source_cutoff=cutoff,
            )

    def execute(self, operation: SystemOperation, apply: Callable):
        operation = SystemOperation.model_validate_json(canonical(operation))
        if operation.system != self.system:
            conflict("wrong operation system")
        with self.transaction(write=True) as tx:
            old = tx.execute(
                "SELECT payload_hash,receipt_json FROM operations WHERE project_id=? AND id=?",
                (str(operation.project_id), str(operation.operation_id)),
            ).fetchone()
            if old:
                if old["payload_hash"] != canonical_hash(operation):
                    raise DomainError(
                        "IDEMPOTENCY_CONFLICT", 409, "Operation ID already used"
                    )
                return SystemReceipt.model_validate_json(old["receipt_json"])
            before = tx.execute(
                "SELECT COALESCE(MAX(sequence),0) FROM facts"
            ).fetchone()[0]
            receipt = SystemReceipt.model_validate(apply(tx, operation))
            self._record_origins(
                tx, before, operation.project_id, "operation", operation.operation_id
            )
            if (
                receipt.operation_id != operation.operation_id
                or receipt.system != self.system
                or receipt.request_hash != canonical_hash(operation)
            ):
                conflict("operation receipt mismatch")
            for key in receipt.source_keys:
                if not tx.execute(
                    "SELECT 1 FROM facts WHERE project_id=? AND system=? AND object_type=? AND external_id=? AND version=?",
                    identity(operation.project_id, key),
                ).fetchone():
                    conflict("receipt source missing")
            tx.execute(
                "INSERT INTO operations VALUES (?,?,?,?,?)",
                (
                    str(operation.project_id),
                    str(operation.operation_id),
                    canonical_hash(operation),
                    canonical(operation),
                    canonical(receipt),
                ),
            )
        return receipt

    def query(self, project_id, operation_id):
        with self.transaction() as tx:
            row = tx.execute(
                "SELECT receipt_json FROM operations WHERE project_id=? AND id=?",
                (str(project_id), str(operation_id)),
            ).fetchone()
            return SystemReceipt.model_validate_json(row[0]) if row else None

    def enqueue(self, tx, fact: IntegrationFact, target):
        if target not in SYSTEM_IDS or fact.source.system != self.system:
            conflict("invalid network endpoint")
        if not any(
            e.producer == self.system
            and e.consumer == target
            and fact.payload.fact_type in e.fact_types
            for e in EDGES
        ):
            conflict("Unmodeled causal edge")
        row = tx.execute(
            "SELECT payload_hash FROM facts WHERE project_id=? AND system=? AND object_type=? AND external_id=? AND version=?",
            identity(fact.project_id, fact.source_key),
        ).fetchone()
        if not row or row[0] != canonical_hash(fact):
            conflict("outbox requires committed source identity")
        did = uuid5(
            NAMESPACE_URL,
            json.dumps((*identity(fact.project_id, fact.source_key), target)),
        )
        delivery = NetworkDelivery(
            delivery_id=did,
            project_id=fact.project_id,
            consumer=target,
            fact=fact,
            payload_hash=canonical_hash(fact),
        )
        old = tx.execute(
            "SELECT delivery_json FROM outbox WHERE id=?", (str(did),)
        ).fetchone()
        if old:
            return NetworkDelivery.model_validate_json(old[0])
        tx.execute(
            "INSERT INTO outbox VALUES (?,?,?,?,?,?,?,?,?)",
            (
                str(did),
                str(fact.project_id),
                target,
                *identity(fact.project_id, fact.source_key)[1:],
                canonical_hash(fact),
                canonical(delivery),
            ),
        )
        return delivery

    def consume(self, delivery: NetworkDelivery, apply: Callable):
        if (
            delivery.consumer != self.system
            or delivery.project_id != delivery.fact.project_id
        ):
            conflict("delivery scope mismatch")
        key = identity(delivery.project_id, delivery.fact.source_key)
        with self.transaction(write=True) as tx:
            old = tx.execute(
                "SELECT * FROM inbox WHERE project_id=? AND producer=? AND object_type=? AND external_id=? AND version=?",
                key,
            ).fetchone()
            if old:
                if (
                    old["payload_hash"] != delivery.payload_hash
                    or old["fact_hash"] != canonical_hash(delivery.fact)
                    or old["delivery_id"] != str(delivery.delivery_id)
                ):
                    conflict("causal identity changed")
                return DeliveryReceipt.model_validate_json(old["receipt_json"])
            error = None
            tx.execute("SAVEPOINT consumer_effect")
            try:
                if delivery.payload_hash != canonical_hash(delivery.fact):
                    conflict("delivery hash mismatch")
                if not any(
                    e.producer == delivery.fact.source.system
                    and e.consumer == self.system
                    and delivery.fact.payload.fact_type in e.fact_types
                    for e in EDGES
                ):
                    conflict("Unmodeled causal edge")
                newer = tx.execute(
                    "SELECT 1 FROM inbox WHERE project_id=? AND producer=? AND object_type=? AND external_id=? AND version>? LIMIT 1",
                    key,
                ).fetchone()
                if newer:
                    conflict("stale source version")
                before = tx.execute(
                    "SELECT COALESCE(MAX(sequence),0) FROM facts"
                ).fetchone()[0]
                apply(tx, delivery)
                self._record_origins(
                    tx, before, delivery.project_id, "inbox", delivery.delivery_id
                )
            except DomainError as exc:
                tx.execute("ROLLBACK TO consumer_effect")
                if exc.status >= 500:
                    raise
                error = SystemError(code=exc.code, message=exc.message, retryable=False)
            tx.execute("RELEASE consumer_effect")
            receipt = DeliveryReceipt(
                delivery_id=delivery.delivery_id,
                project_id=delivery.project_id,
                consumer=self.system,
                source_key=delivery.fact.source_key,
                payload_hash=delivery.payload_hash,
                phase="rejected" if error else "accepted",
                received_at=self.clock(),
                error=error,
            )
            tx.execute(
                "INSERT INTO inbox VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    *key,
                    str(delivery.delivery_id),
                    delivery.payload_hash,
                    canonical_hash(delivery.fact),
                    canonical(receipt),
                ),
            )
            return receipt

    def _record_origins(self, tx, after_sequence, project_id, kind, origin_id):
        rows = tx.execute(
            "SELECT project_id,system,object_type,external_id,version FROM facts WHERE sequence>? ORDER BY sequence",
            (after_sequence,),
        ).fetchall()
        for row in rows:
            if row["project_id"] != str(project_id):
                conflict("Source effect crossed project boundary")
            tx.execute(
                "INSERT INTO fact_origins VALUES (?,?,?,?,?,?,?)",
                (*tuple(row), kind, str(origin_id)),
            )

    def origin(self, project_id, key):
        from .browse import InboxOrigin, OperationOrigin, UntrackedOrigin

        with self.transaction() as tx:
            row = tx.execute(
                "SELECT kind,origin_id FROM fact_origins WHERE project_id=? AND system=? AND object_type=? AND external_id=? AND version=?",
                identity(project_id, key),
            ).fetchone()
            if not row:
                return UntrackedOrigin()
            if row["kind"] == "operation":
                receipt = tx.execute(
                    "SELECT receipt_json FROM operations WHERE project_id=? AND id=?",
                    (str(project_id), row["origin_id"]),
                ).fetchone()
                if not receipt:
                    conflict("Missing producer operation receipt")
                return OperationOrigin(
                    operation_receipt=SystemReceipt.model_validate_json(receipt[0])
                )
            receipt = tx.execute(
                "SELECT receipt_json FROM inbox WHERE project_id=? AND delivery_id=?",
                (str(project_id), row["origin_id"]),
            ).fetchone()
            if not receipt:
                conflict("Missing causal inbox receipt")
            return InboxOrigin(
                inbox_receipt=DeliveryReceipt.model_validate_json(receipt[0])
            )

    def delivery_states(self, project_id, key):
        from .browse import CausalDeliveryStatus

        with self.transaction() as tx:
            rows = tx.execute(
                "SELECT o.id,o.consumer,a.receipt_json FROM outbox o LEFT JOIN acknowledgments a ON a.delivery_id=o.id WHERE o.project_id=? AND o.system=? AND o.object_type=? AND o.external_id=? AND o.version=? ORDER BY o.rowid LIMIT 16",
                identity(project_id, key),
            ).fetchall()
            return [
                CausalDeliveryStatus(
                    delivery_id=r["id"],
                    consumer=r["consumer"],
                    receipt=DeliveryReceipt.model_validate_json(r["receipt_json"])
                    if r["receipt_json"]
                    else None,
                )
                for r in rows
            ]

    def query_delivery(self, project_id, delivery_id):
        with self.transaction() as tx:
            row = tx.execute(
                "SELECT receipt_json FROM inbox WHERE project_id=? AND delivery_id=?",
                (str(project_id), str(delivery_id)),
            ).fetchone()
            return DeliveryReceipt.model_validate_json(row[0]) if row else None

    def consumer_activity(self, project_id):
        from .browse import ConsumerActivity

        with self.transaction() as tx:
            row = tx.execute(
                "SELECT receipt_json FROM inbox WHERE project_id=? ORDER BY rowid DESC LIMIT 1",
                (str(project_id),),
            ).fetchone()
            if row is None:
                return None
            receipt = DeliveryReceipt.model_validate_json(row[0])
            if receipt.project_id != project_id or receipt.consumer != self.system:
                conflict("Consumer activity scope mismatch")
            counts = tx.execute(
                "SELECT COALESCE(SUM(json_extract(receipt_json,'$.phase')='accepted'),0),COALESCE(SUM(json_extract(receipt_json,'$.phase')='rejected'),0) FROM inbox WHERE project_id=?",
                (str(project_id),),
            ).fetchone()
            return ConsumerActivity(
                accepted_count=counts[0],
                rejected_count=counts[1],
                last_receipt=receipt,
                healthy=False,
            )

    def inbox_receipt(self, project_id, key):
        with self.transaction() as tx:
            row = tx.execute(
                "SELECT receipt_json FROM inbox WHERE project_id=? AND producer=? AND object_type=? AND external_id=? AND version=?",
                identity(project_id, key),
            ).fetchone()
            return DeliveryReceipt.model_validate_json(row[0]) if row else None

    def pending_window(self, project_id, limit=100, *, after=0, through=None):
        if not 1 <= limit <= 200 or after < 0 or (through is not None and through < 0):
            raise DomainError("INVALID_PAGINATION", 422, "Invalid delivery window")
        with self.transaction() as tx:
            rows = tx.execute(
                "SELECT o.rowid position,o.delivery_json FROM outbox o WHERE project_id=? AND o.rowid>? "
                + ("AND o.rowid<=? " if through is not None else "")
                + "AND NOT EXISTS(SELECT 1 FROM acknowledgments a WHERE a.delivery_id=o.id) ORDER BY o.rowid LIMIT ?",
                (
                    str(project_id),
                    after,
                    *((through,) if through is not None else ()),
                    limit,
                ),
            ).fetchall()
            return [
                ScheduledDelivery(
                    r["position"],
                    NetworkDelivery.model_validate_json(r["delivery_json"]),
                )
                for r in rows
            ]

    def pending(self, project_id, limit=100):
        if not 1 <= limit <= 200:
            raise DomainError("INVALID_PAGINATION", 422, "Invalid delivery limit")
        with self.transaction() as tx:
            return [
                NetworkDelivery.model_validate_json(r[0])
                for r in tx.execute(
                    "SELECT delivery_json FROM outbox o WHERE project_id=? AND NOT EXISTS(SELECT 1 FROM acknowledgments a WHERE a.delivery_id=o.id) ORDER BY rowid LIMIT ?",
                    (str(project_id), limit),
                )
            ]

    def pending_count(self, project_id):
        with self.transaction() as tx:
            return tx.execute(
                "SELECT COUNT(*) FROM outbox o WHERE project_id=? AND NOT EXISTS(SELECT 1 FROM acknowledgments a WHERE a.delivery_id=o.id)",
                (str(project_id),),
            ).fetchone()[0]

    def acknowledge(self, delivery_id, receipt: DeliveryReceipt):
        with self.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT delivery_json FROM outbox WHERE id=?", (str(delivery_id),)
            ).fetchone()
            if not row:
                conflict("unknown delivery")
            d = NetworkDelivery.model_validate_json(row[0])
            if (
                receipt.delivery_id,
                receipt.project_id,
                receipt.consumer,
                receipt.source_key,
                receipt.payload_hash,
            ) != (
                d.delivery_id,
                d.project_id,
                d.consumer,
                d.fact.source_key,
                d.payload_hash,
            ) or receipt.phase not in {"accepted", "rejected"}:
                conflict("invalid delivery acknowledgment")
            old = tx.execute(
                "SELECT receipt_json FROM acknowledgments WHERE delivery_id=?",
                (str(delivery_id),),
            ).fetchone()
            if old:
                if old[0] != canonical(receipt):
                    conflict("acknowledgment changed")
                return
            tx.execute(
                "INSERT INTO acknowledgments VALUES (?,?)",
                (str(delivery_id), canonical(receipt)),
            )

    def configure_fault(
        self, project_id: UUID, operation_id: UUID, name: str, *, count=1
    ):
        if (
            name
            not in {
                "none",
                "reject",
                "partial_quantity",
                "timeout_after_commit",
                "stale_sequence",
                "wrong_unit",
                "changed_detail_same_total",
            }
            or not 0 <= count <= 100
        ):
            raise ValueError("invalid scoped fault")
        with self.transaction(write=True) as tx:
            tx.execute(
                "INSERT INTO faults VALUES (?,?,?,?) ON CONFLICT(project_id,operation_id) DO UPDATE SET name=excluded.name,remaining=excluded.remaining",
                (str(project_id), str(operation_id), name, count),
            )

    def take_fault(self, project_id, operation_id):
        with self.transaction(write=True) as tx:
            row = tx.execute(
                "SELECT name FROM faults WHERE project_id=? AND operation_id=? AND remaining>0",
                (str(project_id), str(operation_id)),
            ).fetchone()
            if not row:
                return "none"
            tx.execute(
                "UPDATE faults SET remaining=remaining-1 WHERE project_id=? AND operation_id=?",
                (str(project_id), str(operation_id)),
            )
            return row[0]
