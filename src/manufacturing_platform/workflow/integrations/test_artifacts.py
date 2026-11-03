"""Closed, authorized artifact preparation and immutable original byte storage."""

import hashlib
import json
from decimal import Decimal
from uuid import UUID
from ..orders import own
from ..laboratory import qualified_run
from .core_guards import require
from ..laboratory import canonical


def prepare(system, operation, observations):
    p = operation.payload
    with system.registry.workflow_store.transaction() as tx:
        row = own(tx, "test_runs", operation.project_id, p.run_id)
        run = json.loads(row["payload_json"])
        plan = json.loads(
            own(tx, "test_plans", operation.project_id, run["plan_id"])["payload_json"]
        )
        unit = own(tx, "units", operation.project_id, run["unit_id"])
        if p.template == "calibration-v1":
            qualified_run(tx, operation.project_id, p.run_id)
            data = dict(
                kind="calibration",
                run_id=str(p.run_id),
                unit_id=unit["id"],
                algorithm_version=plan["algorithm_version"],
                equipment=plan["equipment"],
                source_identity=f"calibration-{operation.operation_id}",
                source_version="1",
                parameters=[
                    dict(name="gain", value="1", unit="ratio"),
                    dict(name="offset", value="0", unit="V"),
                ],
                evidence="Controlled calibration template v1",
            )
            causes = [
                f.source_key
                for f in observations.of_type("product_test.test")
                if f.payload.run_id == p.run_id
            ]
            require(
                len(causes) == 1, "Calibration needs the exact product-test run source"
            )
        else:
            require(row["finish_json"] is None, "Cannot prepare finished test run")
            requests = [
                f
                for f in observations.of_type("mes.test_request")
                if f.payload.unit_id == UUID(unit["id"])
                and f.payload.plan_id == UUID(run["plan_id"])
            ]
            require(bool(requests), "Actual matching MES test request required")
            request = requests[-1]
            measurements = []
            for index, bound in enumerate(plan["test_spec"]["measurements"]):
                low, high = Decimal(bound["lower"]), Decimal(bound["upper"])
                value = (
                    high + 1
                    if p.template == "fail-v1" and index == 0
                    else (low + high) / 2
                )
                measurements.append(dict(**bound, value=str(value)))
            data = dict(
                kind="test",
                work_order_id=unit["work_order_id"],
                unit_id=unit["id"],
                revision_id=unit["revision_id"],
                plan_id=run["plan_id"],
                run_id=str(p.run_id),
                request=request.source_key.model_dump(mode="json"),
                station=plan["station"],
                test_version=plan["test_spec"]["version"],
                program_version=plan["test_spec"]["program_version"],
                firmware_version=plan["firmware_version"],
                algorithm_version=plan["algorithm_version"],
                equipment=plan["equipment"],
                fixture=plan["fixture"],
                attempt=run["attempt"],
                result="fail" if p.template == "fail-v1" else "pass",
                measurements=measurements,
                raw=dict(
                    origin="demo",
                    curves=[],
                    logs=[f"{p.template}: original controlled measured values"],
                ),
                occurred_at=system.store.clock().isoformat(),
                rework_order_id=run["rework_order_id"],
            )
            causes = [request.source_key]
    content = canonical(dict(template=p.template, prepared=data)).encode()
    data.update(
        artifact_ref=dict(
            system="product_test",
            project_id=str(operation.project_id),
            artifact_id=str(operation.operation_id),
            version=1,
            reference=f"artifact-{operation.operation_id}",
        ),
        artifact_checksum=hashlib.sha256(content).hexdigest(),
    )
    fact = system.make_fact(
        operation.project_id,
        dict(fact_type="product_test.artifact", template=p.template, prepared=data),
        operation.operation_id,
        causes=causes,
    )
    checksum = hashlib.sha256(original_bytes(fact)).hexdigest()
    return fact.model_copy(
        update={
            "payload": fact.payload.model_copy(
                update={
                    "prepared": fact.payload.prepared.model_copy(
                        update={"artifact_checksum": checksum}
                    )
                }
            )
        }
    )


def original_bytes(fact):
    return canonical(
        dict(
            template=fact.payload.template,
            prepared=fact.payload.prepared.model_dump(
                mode="json", exclude={"artifact_ref", "artifact_checksum"}
            ),
        )
    ).encode()


def persist(tx, fact):
    p = fact.payload.prepared
    tx.execute(
        "CREATE TABLE IF NOT EXISTS original_artifacts(project_id TEXT NOT NULL, artifact_id TEXT NOT NULL, version INTEGER NOT NULL, reference TEXT NOT NULL, checksum TEXT NOT NULL, content BLOB NOT NULL, PRIMARY KEY(project_id,artifact_id,version))"
    )
    tx.execute(
        "CREATE TRIGGER IF NOT EXISTS original_artifacts_no_replace BEFORE INSERT ON original_artifacts WHEN EXISTS(SELECT 1 FROM original_artifacts WHERE project_id=NEW.project_id AND artifact_id=NEW.artifact_id AND version=NEW.version) BEGIN SELECT RAISE(ABORT,'original artifacts are immutable'); END"
    )
    for event in ("UPDATE", "DELETE"):
        tx.execute(
            f"CREATE TRIGGER IF NOT EXISTS original_artifacts_no_{event.lower()} BEFORE {event} ON original_artifacts BEGIN SELECT RAISE(ABORT,'original artifacts are immutable'); END"
        )
    content = original_bytes(fact)
    require(
        hashlib.sha256(content).hexdigest() == p.artifact_checksum,
        "Prepared artifact content/hash mismatch",
    )
    tx.execute(
        "INSERT INTO original_artifacts VALUES (?,?,?,?,?,?)",
        (
            str(fact.project_id),
            str(p.artifact_ref.artifact_id),
            p.artifact_ref.version,
            p.artifact_ref.reference,
            p.artifact_checksum,
            content,
        ),
    )


def resolve(store, project_id, ref, checksum):
    require(
        ref.project_id == project_id and ref.system == store.system == "product_test",
        "Artifact project/source mismatch",
    )
    with store.transaction() as tx:
        require(
            tx.execute(
                "SELECT 1 FROM sqlite_master WHERE name='original_artifacts'"
            ).fetchone()
            is not None,
            "Owned original artifact unavailable",
        )
        row = tx.execute(
            "SELECT * FROM original_artifacts WHERE project_id=? AND artifact_id=? AND version=?",
            (str(project_id), str(ref.artifact_id), ref.version),
        ).fetchone()
    require(
        row is not None
        and row["reference"] == ref.reference
        and row["checksum"] == checksum,
        "Exact owned artifact identity/checksum unavailable",
    )
    content = bytes(row["content"])
    require(
        hashlib.sha256(content).hexdigest() == checksum,
        "Original artifact bytes checksum mismatch",
    )
    return content


def validate_inline(store, project_id, payload):
    decoded = json.loads(
        resolve(store, project_id, payload.artifact_ref, payload.artifact_checksum)
    )
    expected = payload.model_dump(
        mode="json",
        exclude={"operation", "fact_type", "artifact_ref", "artifact_checksum"},
    )
    expected["kind"] = "test" if hasattr(payload, "measurements") else "calibration"
    require(
        decoded["prepared"] == expected,
        "Inline evidence differs from original artifact scope/values",
    )
