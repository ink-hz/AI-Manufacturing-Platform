"""Read-only binding of A2/A3/B1/B3 audit sources to their original facts.

Authorization to read is enforced by the service. Historical source validity
uses persisted operation/admission bindings, never the writer's current role.
"""

import hashlib
import json
from datetime import datetime
from pydantic import ValidationError

from .commands import COMMAND_REGISTRY
from .contracts import DomainError, ObjectEvidence, SourceRef
from .orders import _audit_evidence, source_key

TABLES = {
    "demand.record": ("demands", "demand"),
    "order.register": ("order_lines", "order_line"),
    "order.change": ("commitment_changes", "commitment_change"),
    "work_order.register": ("work_orders", "work_order"),
    "plan.receive": ("plans", "plan"),
    "material.define": ("material_lots", "material_lot"),
    "supply.commit": ("supply_commitments", "commitment"),
    "supply.receive": ("supply_receipts", "receipt"),
}


def evidence(tx, pid, audit, payload):
    denied = [ObjectEvidence(reference="Unverified historical source; private audit retained")]
    if payload.get("source") is None:
        if audit["action"] in TABLES or audit["action"] == "execution.record":
            return denied
        return _audit_evidence(payload)
    try:
        action = audit["action"]
        if action not in TABLES and action != "execution.record":
            return denied
        if audit["project_id"] != str(pid) or payload.get("project_id") != str(pid) or payload.get("action") != action:
            return denied
        command = COMMAND_REGISTRY.registration(action).model.model_validate({k: v for k, v in payload.items() if k != "project_id"})
        source = command.source
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        operation = tx.execute("SELECT result_json FROM operations WHERE dataset=(SELECT id FROM dataset_metadata) AND actor_id=? AND operation_id=? AND payload_hash=?", (audit["actor_id"], str(command.operation_id), digest)).fetchone()
        if operation is None:
            return denied
        result = json.loads(operation[0])
        if result.get("project_id") != str(pid) or result.get("object_id") != audit["object_id"]:
            return denied
        if action == "execution.record":
            from .execution import admitted_execution_source
            candidates = tx.execute("SELECT * FROM execution_events WHERE project_id=? AND work_order_id=? AND claimed_sn=? AND source_system=? AND source_type=? AND source_external_id=? ORDER BY accepted_seq", (str(pid), str(command.work_order_id), command.sn, *source_key(source)))
            for event in candidates:
                if (event["unit_id"] or event["work_order_id"]) != audit["object_id"]:
                    continue
                if result.get("object_type") != ("unit" if event["unit_id"] else "work_order"):
                    continue
                if any(event[k] != getattr(command, k) for k in ("station", "route_version", "program_version", "firmware_version", "result")):
                    continue
                if datetime.fromisoformat(event["occurred_at"]) != command.occurred_at or datetime.fromisoformat(event["recorded_at"]) > datetime.fromisoformat(audit["recorded_at"]):
                    continue
                if SourceRef.model_validate_json(event["source_json"]) == source and admitted_execution_source(tx, pid, event) == source:
                    return [ObjectEvidence(reference=source.evidence, source=source)]
            return denied
        table, kind = TABLES[action]
        if result.get("object_type") != kind:
            return denied
        row = tx.execute(f"SELECT * FROM {table} WHERE project_id=? AND id=?", (str(pid), audit["object_id"])).fetchone()
        if row is None:
            return denied
        # Amendable orders retain original source in the immutable operation;
        # amendments retain their exact separate source snapshot.
        original = SourceRef.model_validate_json(row["source_json"])
        if action == "order.register":
            if source_key(source) != source_key(original) or source.version > row["source_version"]:
                return denied
        elif action == "supply.commit":
            revisions = tx.execute("SELECT source_json FROM supply_promise_revisions WHERE project_id=? AND commitment_id=?", (str(pid), row["id"]))
            if not any(SourceRef.model_validate_json(r[0]) == source for r in revisions):
                return denied
        elif original != source:
            return denied
        for field in ("demand_id", "order_line_id", "revision_id", "requirement_id", "commitment_id", "material_lot_id"):
            if field in row.keys() and hasattr(command, field) and getattr(command, field) is not None and str(getattr(command, field)) != row[field]:
                return denied
        if source.mode not in {"manual", "file"} or source.collected_at < source.occurred_at:
            return denied
        return [ObjectEvidence(reference=source.evidence, source=source)]
    except (DomainError, ValidationError, ValueError, KeyError, TypeError):
        return denied
