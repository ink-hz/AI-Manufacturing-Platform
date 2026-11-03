"""Manual/simulated laboratory management, using the real quality gate."""

import hashlib
import json
from datetime import datetime
from uuid import uuid4

from . import quality
from .commands import COMMAND_REGISTRY
from .contracts import MutationResult
from .engineering import fixed_revision
from .execution_models import TestEvidenceScope, sn_key
from .laboratory_models import (
    AliasUnit,
    ConfirmCalibration,
    FinishTestRun,
    InstallComponent,
    PublishTestPlan,
    RecordCalibration,
    RemoveComponent,
    StartTestRun,
)
from .orders import own
from .quality import fail
from .quality_models import RecordTest


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def stamp(context):
    return {
        "actor_id": str(context.actor.user_id),
        "recorded_at": context.now.isoformat(),
    }


def business(command):
    return command.model_dump(
        mode="json", exclude={"action", "operation_id", "expected_version"}
    )


def insert(tx, table, context, payload, **columns):
    ident = str(uuid4())
    payload = dict(id=ident, **payload, **stamp(context))
    names = ["id", "project_id", "payload_json", *columns]
    tx.execute(
        f"INSERT INTO {table}({','.join(names)}) VALUES ({','.join('?' for _ in names)})",
        (ident, str(context.project_id), canonical(payload), *columns.values()),
    )
    return ident


def publish(tx, context, command):
    revision = fixed_revision(tx, context.project_id, command.revision_id)
    ident = insert(
        tx,
        "test_plans",
        context,
        dict(
            **business(command),
            test_spec=revision.test_spec.model_dump(mode="json"),
            firmware_version=revision.firmware_version,
            revision_hash=revision.content_hash,
        ),
    )
    return MutationResult(object_type="test_plan", object_id=ident)


def current_basis(tx, context, unit, rework_id):
    from .execution import unit_interrupted

    if (
        not unit["accepted_start_id"]
        or unit["state"] != "running"
        or unit_interrupted(tx, context.project_id, unit["work_order_id"], unit)
    ):
        fail("run requires current accepted running execution")
    revision = fixed_revision(tx, context.project_id, unit["revision_id"])
    steps = (
        quality.rework_route(tx, context.project_id, unit, rework_id)[1]
        if rework_id
        else revision.route_steps
    )
    events = quality.route_events(
        tx, context.project_id, unit, steps, rework_id, context.now.isoformat()
    )
    if rework_id:
        quality.require_fresh_route(
            tx,
            context.project_id,
            quality.rework_parent_test(tx, context.project_id, rework_id),
            events,
        )
    equipment = tx.execute(
        "SELECT * FROM readiness_checks WHERE project_id=? AND work_order_id=? AND kind='equipment' ORDER BY accepted_seq DESC LIMIT 1",
        (str(context.project_id), unit["work_order_id"]),
    ).fetchone()
    if (
        not equipment
        or equipment["decision"] != "verified"
        or datetime.fromisoformat(equipment["valid_until"]) < context.now
    ):
        fail("run requires current valid equipment calibration")
    return TestEvidenceScope(
        route_fingerprint=revision.content_hash,
        test_version=revision.test_spec.version,
        program_version=revision.test_spec.program_version,
        firmware_version=revision.firmware_version,
        equipment_check_id=equipment["id"],
    ).model_dump(mode="json"), events


def start(tx, context, command):
    unit = own(tx, "units", context.project_id, command.unit_id)
    plan = json.loads(
        own(tx, "test_plans", context.project_id, command.plan_id)["payload_json"]
    )
    if plan["revision_id"] != unit["revision_id"]:
        fail("plan must match the unit engineering revision")
    if quality.scrapped(tx, context.project_id, unit["id"]):
        fail("scrapped units cannot start a run")
    if tx.execute(
        "SELECT 1 FROM test_runs WHERE project_id=? AND unit_id=? AND finish_json IS NULL",
        (str(context.project_id), unit["id"]),
    ).fetchone():
        fail("unit already has a running attempt")
    scope, events = current_basis(tx, context, unit, command.rework_order_id)
    attempt = tx.execute(
        "SELECT COUNT(*)+1 FROM test_runs WHERE project_id=? AND unit_id=?",
        (str(context.project_id), unit["id"]),
    ).fetchone()[0]
    ident = insert(
        tx,
        "test_runs",
        context,
        dict(
            **business(command),
            revision_id=unit["revision_id"],
            attempt=attempt,
            accepted_start_id=unit["accepted_start_id"],
            scope=scope,
            execution_event_ids=events,
        ),
        unit_id=unit["id"],
    )
    return MutationResult(object_type="test_run", object_id=ident)


def finish(tx, context, command):
    return _finish(tx, context, command)


def _finish(tx, context, command, *, trusted_fact=None):
    row = own(tx, "test_runs", context.project_id, command.run_id)
    if row["finish_json"]:
        fail("finished run is immutable; start a new attempt")
    run = json.loads(row["payload_json"])
    if (
        command.source.occurred_at < datetime.fromisoformat(run["recorded_at"])
        or command.source.occurred_at > context.now
        or command.source.collected_at > context.now
    ):
        fail("run evidence must occur after start and before admission")
    if command.source.object_type != "test":
        fail("run source must identify test evidence")
    test_id = None
    outcome = None
    if command.state == "completed":
        unit = own(tx, "units", context.project_id, run["unit_id"])
        scope, events = current_basis(tx, context, unit, run["rework_order_id"])
        if (
            scope != run["scope"]
            or events != run["execution_event_ids"]
            or unit["accepted_start_id"] != run["accepted_start_id"]
        ):
            fail("run execution or equipment scope changed; start a new attempt")
        previous = quality.latest_test(tx, context.project_id, unit["id"])
        test_command = RecordTest(
            action="test.record",
            operation_id=command.operation_id,
            expected_version=command.expected_version,
            source=command.source,
            unit_id=unit["id"],
            attempt=previous["attempt"] + 1 if previous else 1,
            program_version=scope["program_version"],
            limit_version=scope["test_version"],
            firmware_version=scope["firmware_version"],
            measurements=command.measurements,
            rework_order_id=run["rework_order_id"],
        )
        result = quality._record_test(
            tx, context, test_command, trusted_fact=trusted_fact
        )
        test = own(tx, "quality_tests", context.project_id, result.object_id)
        if (
            json.loads(test["scope_json"]) != scope
            or json.loads(test["execution_ids_json"]) != events
        ):
            fail("measurement occurrence does not match captured run scope")
        test_id = str(result.object_id)
        outcome = test["outcome"]
        tx.execute(
            "INSERT INTO audit_events(project_id,actor_id,action,object_id,occurred_at,recorded_at,typed_payload) VALUES (?,?,?,?,?,?,?)",
            (
                str(context.project_id),
                str(context.actor.user_id),
                "test.record",
                test_id,
                command.source.occurred_at.isoformat(),
                context.now.isoformat(),
                canonical(
                    dict(
                        project_id=str(context.project_id),
                        **test_command.model_dump(mode="json"),
                    )
                ),
            ),
        )
    raw = command.raw.model_dump(mode="json")
    payload = dict(
        **stamp(context),
        evidence=command.reason or command.source.evidence,
        source=command.source.model_dump(mode="json"),
        state=command.state,
        measurements=[m.model_dump(mode="json") for m in command.measurements],
        raw=raw,
        raw_digest=digest(
            {
                "run_id": row["id"],
                "source": command.source.model_dump(mode="json"),
                "raw": raw,
            }
        ),
        test_id=test_id,
        outcome=outcome,
    )
    tx.execute(
        "UPDATE test_runs SET finish_json=? WHERE id=? AND project_id=?",
        (canonical(payload), row["id"], str(context.project_id)),
    )
    return MutationResult(object_type="test_run", object_id=row["id"])


def qualified_run(tx, pid, run_id):
    row = own(tx, "test_runs", pid, run_id)
    run = json.loads(row["payload_json"])
    result = json.loads(row["finish_json"]) if row["finish_json"] else {}
    if (
        result.get("state") != "completed"
        or result.get("outcome") != "pass"
        or not quality.complete_pass(
            tx,
            pid,
            result["test_id"],
            run["unit_id"],
            run["revision_id"],
            scope=TestEvidenceScope.model_validate(run["scope"]),
        )
    ):
        fail("calibration requires a current matching successful test run")
    return run


def parameter_content(parameters):
    if len({p.name for p in parameters}) != len(parameters):
        fail("parameter names must be unique", 422)
    # Canonical numerical equality, independent of presentation scale/order.
    return sorted(
        [
            {
                "name": p.name,
                "value": (
                    format(p.value, "f").rstrip("0").rstrip(".")
                    if "." in format(p.value, "f")
                    else format(p.value, "f")
                ),
                "unit": p.unit,
            }
            for p in parameters
        ],
        key=lambda p: p["name"],
    )


def validate_calibration(tx, context, command):
    run = qualified_run(tx, context.project_id, command.run_id)
    plan = json.loads(
        own(tx, "test_plans", context.project_id, run["plan_id"])["payload_json"]
    )
    finish = json.loads(
        own(tx, "test_runs", context.project_id, command.run_id)["finish_json"]
    )
    if finish["raw"]["origin"] == "demo" and command.origin != "demo":
        fail("simulated run evidence must remain visibly simulated")
    if command.algorithm_version != plan["algorithm_version"]:
        fail("calibration algorithm version must match published plan")
    parameter_content(command.parameters)
    return run


def record_calibration(tx, context, command):
    run = validate_calibration(tx, context, command)
    ident = insert(
        tx,
        "calibrations",
        context,
        dict(
            **business(command),
            unit_id=run["unit_id"],
            parameter_digest=digest(parameter_content(command.parameters)),
        ),
    )
    return MutationResult(object_type="calibration", object_id=ident)


def confirmation_basis(tx, context, command):
    row = own(tx, "calibrations", context.project_id, command.calibration_id)
    value = json.loads(row["payload_json"])
    if row["confirmation_json"]:
        fail("calibration confirmation is immutable")
    qualified_run(tx, context.project_id, value["run_id"])
    if command.source_identity == value["source_identity"]:
        fail("readback must name a separate source evidence identity")
    if command.origin != value["origin"]:
        fail("readback origin must match calibration evidence origin")
    readback_digest = digest(parameter_content(command.readback))
    return row, readback_digest, value["parameter_digest"]


def validate_confirmation(tx, context, command):
    row, readback_digest, parameter_digest = confirmation_basis(tx, context, command)
    if readback_digest != parameter_digest:
        fail("readback must match recorded parameters and units")
    return row, readback_digest


def confirm_calibration(tx, context, command):
    row, readback_digest = validate_confirmation(tx, context, command)
    payload = business(command)
    payload.pop("calibration_id")
    tx.execute(
        "UPDATE calibrations SET confirmation_json=? WHERE id=? AND project_id=?",
        (
            canonical(
                dict(**payload, **stamp(context), parameter_digest=readback_digest)
            ),
            row["id"],
            str(context.project_id),
        ),
    )
    return MutationResult(object_type="calibration", object_id=row["id"])


def validate_install(tx, context, command):
    own(tx, "units", context.project_id, command.unit_id)
    if command.lot_id:
        lot = own(tx, "material_lots", context.project_id, command.lot_id)
        if lot["material_id"] != command.material_id:
            fail("component lot must match material identity")
    key = sn_key(command.component_serial)
    if tx.execute(
        "SELECT 1 FROM component_links WHERE project_id=? AND material_id=? AND serial_key=? AND removal_json IS NULL",
        (str(context.project_id), command.material_id, key),
    ).fetchone():
        fail("component already has an active installation")


def install(tx, context, command):
    return _install(tx, context, command)


def _install(tx, context, command, *, trusted_fact=None):
    validate_install(tx, context, command)
    key = sn_key(command.component_serial)
    payload = business(command)
    if trusted_fact is not None:
        payload["source"] = trusted_fact.source.model_dump(mode="json")
    ident = insert(
        tx,
        "component_links",
        context,
        payload,
        unit_id=str(command.unit_id),
        material_id=command.material_id,
        serial_key=key,
    )
    return MutationResult(object_type="component_link", object_id=ident)


def remove(tx, context, command):
    row = own(tx, "component_links", context.project_id, command.component_link_id)
    if row["removal_json"]:
        fail("component installation is already closed")
    tx.execute(
        "UPDATE component_links SET removal_json=? WHERE id=? AND project_id=?",
        (
            canonical(dict(**stamp(context), evidence=command.evidence)),
            row["id"],
            str(context.project_id),
        ),
    )
    return MutationResult(object_type="component_link", object_id=row["id"])


def validate_alias(tx, context, command):
    own(tx, "units", context.project_id, command.unit_id)
    customer = tx.execute(
        "SELECT customer_id FROM projects WHERE id=?", (str(context.project_id),)
    ).fetchone()[0]
    key = sn_key(command.customer_serial)
    if tx.execute(
        "SELECT 1 FROM unit_aliases WHERE customer_id=? AND serial_key=?",
        (customer, key),
    ).fetchone():
        fail("customer serial is already assigned")
    return customer, key


def alias(tx, context, command):
    customer, key = validate_alias(tx, context, command)
    insert(
        tx,
        "unit_aliases",
        context,
        {
            "customer_id": customer,
            "customer_serial": command.customer_serial,
            "evidence": command.evidence,
        },
        unit_id=str(command.unit_id),
        customer_id=customer,
        serial_key=key,
    )
    return MutationResult(object_type="unit", object_id=command.unit_id)


for model, handler, roles, qualifications in (
    (PublishTestPlan, publish, {"engineering"}, set()),
    (StartTestRun, start, {"production", "quality"}, set()),
    # Same live policy as test.record, enforced centrally before idempotent replay.
    (FinishTestRun, finish, {"quality"}, {"inspection"}),
    (RecordCalibration, record_calibration, {"quality"}, {"inspection"}),
    (ConfirmCalibration, confirm_calibration, {"quality"}, {"inspection"}),
    (InstallComponent, install, {"production"}, set()),
    (RemoveComponent, remove, {"production"}, set()),
    (AliasUnit, alias, {"production"}, set()),
):
    COMMAND_REGISTRY.register(
        model, roles=roles, qualifications=qualifications, handler=handler
    )

from . import laboratory_readers  # noqa: F401 - trusted reader registration
