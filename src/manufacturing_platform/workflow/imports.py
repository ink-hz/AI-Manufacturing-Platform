"""Bounded parsing and shared domain ingestion. Parsing performs no I/O or writes."""

import csv
import io
import json
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError

from .contracts import DomainError, MutationResult
from .exchange_models import (
    InboundApproval,
    InboundIQC,
    InboundReceipt,
    TypedInboundRecord,
)
from .orders import own, source_key
from .supply import atoms, inspect_supply, receive_supply
from .supply_models import InspectSupply, ReceiveSupply

MAX_BYTES = 1024 * 1024
record_adapter = TypeAdapter(TypedInboundRecord)


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def parse_import(content: bytes, format, object_type) -> list[TypedInboundRecord]:
    if len(content) > MAX_BYTES:
        raise DomainError("IMPORT_INVALID", 422, "Import exceeds 1 MB", {"line": 1})
    try:
        text = content.decode("utf-8-sig")
        if format == "json":
            rows = json.loads(text, object_pairs_hook=_unique_fields)
        elif format == "csv":
            rows = []
            for raw in csv.DictReader(io.StringIO(text)):
                # Source is flattened for spreadsheet-friendly CSV, never arbitrary executable data.
                source = {
                    k[7:]: v for k, v in raw.items() if k and k.startswith("source_")
                }
                if "version" in source:
                    source["version"] = int(source["version"])
                raw = {
                    k: v for k, v in raw.items() if k and not k.startswith("source_")
                }
                raw["source"] = source
                rows.append(raw)
        else:
            raise ValueError("unsupported format")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
            raise ValueError("batch must contain 1..500 rows")
    except (ValueError, UnicodeError, csv.Error) as exc:
        raise DomainError(
            "IMPORT_INVALID", 422, "Invalid import format", {"line": 1}
        ) from exc
    result = []
    for number, row in enumerate(rows, 1):
        try:
            value = record_adapter.validate_python(row)
            if value.object_type != object_type or value.source.mode not in {
                "manual",
                "file",
            }:
                raise ValueError("import type or provenance invalid")
            result.append(value)
        except (ValidationError, ValueError) as exc:
            raise DomainError(
                "IMPORT_INVALID", 422, "Invalid import row", {"line": number}
            ) from exc
    return result


def validate_record(record, context, *, trusted):
    from .supply import MAX_CLOCK_SKEW

    if record.project_id != context.project_id:
        raise DomainError("NOT_FOUND", 404, "Workflow resource not found")
    source = record.source
    if source_key(source)[1] != record.object_type or source.mode not in (
        {"mock", "api"} if trusted else {"manual", "file"}
    ):
        raise DomainError("IMPORT_INVALID", 422, "Invalid source type or provenance")
    if (
        source.collected_at < source.occurred_at
        or source.occurred_at > context.now + MAX_CLOCK_SKEW
        or source.collected_at > context.now + MAX_CLOCK_SKEW
    ):
        raise DomainError("IMPORT_INVALID", 422, "Invalid source clock")


def ingest(
    tx,
    context,
    records,
    *,
    trusted=False,
    correction_exchange=None,
    correction_evidence="",
):
    from .adapters.mock import digest

    results = []
    # Entire command is transactional; any failure rolls back every prior row.
    for index, record in enumerate(records, 1):
        try:
            validate_record(record, context, trusted=trusted)
            key = source_key(record.source)
            existing = tx.execute(
                "SELECT * FROM source_confirmations WHERE system=? AND object_type=? AND external_id=? AND version=? AND mode=?",
                (*key, record.source.version, record.source.mode),
            ).fetchone()
            body_hash = digest(record.model_dump(mode="json"))
            if existing:
                if existing["project_id"] != str(context.project_id):
                    raise DomainError("NOT_FOUND", 404, "Workflow resource not found")
                if existing["payload_hash"] != body_hash:
                    raise DomainError(
                        "SOURCE_CONFLICT", 409, "Source identity has changed detail"
                    )
                kind = {
                    "receipt": "receipt",
                    "iqc": "receipt",
                    "customer_approval": "revision",
                }[record.object_type]
                results.append(
                    MutationResult(
                        object_type=kind, object_id=UUID(existing["object_id"])
                    )
                )
                continue
            command_base = {
                "operation_id": uuid4(),
                "expected_version": context.project_version,
            }
            if isinstance(record, InboundReceipt):
                prior = tx.execute(
                    "SELECT * FROM effective_supply_receipts WHERE source_system=? AND source_type=? AND source_external_id=?",
                    key,
                ).fetchone()
                if prior:
                    if prior["project_id"] != str(context.project_id):
                        raise DomainError(
                            "NOT_FOUND", 404, "Workflow resource not found"
                        )
                    lot = own(
                        tx, "material_lots", context.project_id, record.material_lot_id
                    )
                    expected = (
                        str(context.project_id),
                        str(record.commitment_id),
                        str(record.material_lot_id),
                        atoms(record.quantity, record.unit, lot["unit"], lot["scale"]),
                        record.unit,
                    )
                    actual = tuple(
                        prior[k]
                        for k in (
                            "project_id",
                            "commitment_id",
                            "material_lot_id",
                            "q_atoms",
                            "unit",
                        )
                    )
                    if (
                        correction_exchange
                        and actual[:3] == expected[:3]
                        and actual[4] == expected[4]
                        and prior["source_version"] == record.source.version
                    ):
                        checked = tx.execute(
                            "SELECT COALESCE(SUM(accepted_atoms+rejected_atoms),0) FROM effective_iqc_results WHERE receipt_id=?",
                            (prior["id"],),
                        ).fetchone()[0]
                        if expected[3] < checked:
                            raise DomainError(
                                "SOURCE_DISCREPANCY",
                                409,
                                "Corrected receipt cannot be below inspected quantity; reconcile inspection first",
                            )
                        tx.execute(
                            "INSERT INTO source_corrections(project_id,receipt_id,received_delta,exchange_id,evidence) VALUES (?,?,?,?,?)",
                            (
                                str(context.project_id),
                                prior["id"],
                                expected[3] - actual[3],
                                correction_exchange,
                                correction_evidence,
                            ),
                        )
                    elif (
                        actual != expected
                        or prior["source_version"] != record.source.version
                    ):
                        raise DomainError(
                            "SOURCE_DISCREPANCY",
                            409,
                            "Manual receipt differs from authoritative detail; retain evidence and resolve discrepancy",
                        )
                    result = MutationResult(
                        object_type="receipt", object_id=UUID(prior["id"])
                    )
                else:
                    result = receive_supply(
                        tx,
                        context,
                        ReceiveSupply(
                            **command_base,
                            action="supply.receive",
                            commitment_id=record.commitment_id,
                            material_lot_id=record.material_lot_id,
                            quantity=str(record.quantity),
                            unit=record.unit,
                            source=record.source,
                        ),
                        source_modes={"mock", "api"} if trusted else {"file", "manual"},
                    )
            elif isinstance(record, InboundIQC):
                receipt = tx.execute(
                    "SELECT * FROM effective_supply_receipts WHERE project_id=? AND source_system=? AND source_type='receipt' AND source_external_id=?",
                    (
                        str(context.project_id),
                        record.receipt_system.strip().casefold(),
                        record.receipt_external_id.strip(),
                    ),
                ).fetchone()
                if not receipt:
                    raise DomainError(
                        "NOT_FOUND", 404, "Referenced receipt must be pulled first"
                    )
                lot = own(
                    tx, "material_lots", context.project_id, receipt["material_lot_id"]
                )
                accepted = atoms(
                    record.accepted, lot["unit"], lot["unit"], lot["scale"]
                )
                rejected = atoms(
                    record.rejected, lot["unit"], lot["unit"], lot["scale"]
                )
                matches = tx.execute(
                    """SELECT i.* FROM effective_iqc_results i WHERE i.project_id=? AND i.receipt_id=? AND NOT EXISTS(SELECT 1 FROM source_confirmations c WHERE c.object_type='iqc' AND c.fact_id=i.id AND c.mode IN ('mock','api')) ORDER BY i.accepted_seq""",
                    (str(context.project_id), receipt["id"]),
                ).fetchall()
                matched = None
                if record.manual_iqc_id:
                    matched = next(
                        (i for i in matches if i["id"] == str(record.manual_iqc_id)),
                        None,
                    )
                    if not matched or (
                        matched["accepted_atoms"],
                        matched["rejected_atoms"],
                    ) != (accepted, rejected):
                        raise DomainError(
                            "SOURCE_DISCREPANCY",
                            409,
                            "Manual inspection differs from authoritative detail",
                        )
                elif len(matches) == 1 and (
                    matches[0]["accepted_atoms"],
                    matches[0]["rejected_atoms"],
                ) == (accepted, rejected):
                    matched = matches[0]
                if correction_exchange and not matched and len(matches) == 1:
                    matched = matches[0]
                    if accepted + rejected > receipt["q_atoms"]:
                        raise DomainError(
                            "SOURCE_DISCREPANCY",
                            409,
                            "Corrected inspection exceeds receipt",
                        )
                    tx.execute(
                        "INSERT INTO source_corrections(project_id,receipt_id,iqc_id,accepted_delta,rejected_delta,exchange_id,evidence) VALUES (?,?,?,?,?,?,?)",
                        (
                            str(context.project_id),
                            receipt["id"],
                            matched["id"],
                            accepted - matched["accepted_atoms"],
                            rejected - matched["rejected_atoms"],
                            correction_exchange,
                            correction_evidence,
                        ),
                    )
                if matched:
                    result = MutationResult(
                        object_type="receipt", object_id=UUID(receipt["id"])
                    )
                else:
                    result = inspect_supply(
                        tx,
                        context,
                        InspectSupply(
                            **command_base,
                            action="supply.inspect",
                            receipt_id=receipt["id"],
                            accepted=str(record.accepted),
                            rejected=str(record.rejected),
                            evidence=record.evidence,
                        ),
                    )
                iqc_id = (
                    matched["id"]
                    if matched
                    else tx.execute(
                        "SELECT id FROM iqc_results WHERE receipt_id=? ORDER BY rowid DESC LIMIT 1",
                        (receipt["id"],),
                    ).fetchone()[0]
                )
            elif isinstance(record, InboundApproval):
                own(tx, "engineering_revisions", context.project_id, record.revision_id)
                project = tx.execute(
                    "SELECT * FROM projects WHERE id=?", (str(context.project_id),)
                ).fetchone()
                if project["customer_id"] != record.customer_id:
                    raise DomainError(
                        "PRECONDITION_FAILED", 409, "Customer scope mismatch"
                    )
                manual = tx.execute(
                    "SELECT id FROM customer_approvals WHERE project_id=? AND revision_id=? AND customer_id=? AND external_signatory=? AND decision=? AND evidence=? AND method IN ('manual','file') ORDER BY accepted_seq LIMIT 1",
                    (
                        str(context.project_id),
                        str(record.revision_id),
                        record.customer_id,
                        record.external_actor,
                        record.decision,
                        record.evidence,
                    ),
                ).fetchone()
                if trusted and manual:
                    ident = manual["id"]
                else:
                    ident = str(uuid4())
                    tx.execute(
                        "INSERT INTO customer_approvals VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            ident,
                            str(context.project_id),
                            str(record.revision_id),
                            record.customer_id,
                            record.external_actor,
                            record.source.mode,
                            record.decision,
                            record.evidence,
                            str(context.actor.user_id),
                            context.now.isoformat(),
                            tx.execute(
                                "SELECT COALESCE(MAX(accepted_seq),0)+1 FROM customer_approvals WHERE project_id=?",
                                (str(context.project_id),),
                            ).fetchone()[0],
                        ),
                    )
                result = MutationResult(
                    object_type="revision", object_id=record.revision_id
                )
            source_body = record.source.model_dump(mode="json")
            fact_id = (
                iqc_id
                if isinstance(record, InboundIQC)
                else ident
                if isinstance(record, InboundApproval)
                else str(result.object_id)
            )
            tx.execute(
                "INSERT INTO source_confirmations(project_id,system,object_type,external_id,version,object_id,payload_hash,source_json,mode,fact_id,external_actor,signature,recorded_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(context.project_id),
                    *key,
                    record.source.version,
                    str(result.object_id),
                    body_hash,
                    json.dumps(source_body),
                    record.source.mode,
                    fact_id,
                    record.external_actor,
                    record.signature,
                    str(context.actor.user_id),
                ),
            )
            results.append(result)
        except DomainError as exc:
            exc.fields = {**exc.fields, "line": index}
            raise
    return results
