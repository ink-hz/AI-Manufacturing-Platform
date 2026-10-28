"""Immutable measurements, repair evidence and independent release decisions."""

import json
from datetime import datetime
from uuid import UUID, uuid4

from .commands import COMMAND_REGISTRY
from .contracts import (
    DomainError,
    MutationResult,
    ObjectDetail,
    ObjectRelation,
    ObjectSummary,
)
from .engineering import fixed_revision
from .execution_models import TestEvidenceScope
from .orders import _history_rows, amount, own, source_key
from .orders import project as project_row
from .quality_models import (
    CompleteRework,
    DecideRelease,
    Disposition,
    Eligibility,
    NonconformanceValue,
    OpenNonconformance,
    QualitySourceRecord,
    QualitySummary,
    RecordTest,
    ReleaseValue,
    ReworkValue,
    TestValue,
    TestView,
)
from .queries import OBJECT_REGISTRY


def fail(reason, status=409, *, field=None):
    raise DomainError(
        "PRECONDITION_FAILED" if status == 409 else "INVALID_COMMAND",
        status,
        reason,
        fields={field: reason} if field else {},
        blocking_reasons=[reason],
    )


def release_kinds(roles, qualifications):
    return [
        kind
        for kind, permitted in (
            ("manufacturing", "production" in roles),
            ("quality", "quality" in roles and "quality_release" in qualifications),
            ("customer", "project_owner" in roles),
        )
        if permitted
    ]


def authorize_release(tx, actor, pid, command):
    grant = tx.execute(
        "SELECT roles_json,qualifications_json FROM project_grants WHERE project_id=? AND user_id=? AND active=1",
        (str(pid), str(actor.user_id)),
    ).fetchone()
    if (
        not grant
        or actor.read_only
        or command.kind
        not in release_kinds(
            json.loads(grant["roles_json"]), json.loads(grant["qualifications_json"])
        )
    ):
        raise DomainError("FORBIDDEN", 403, "Release signatory permission denied")


def scrapped(tx, pid, uid):
    return bool(
        tx.execute(
            "SELECT 1 FROM quality_dispositions WHERE project_id=? AND unit_id=? AND decision='scrap'",
            (str(pid), str(uid)),
        ).fetchone()
    )


def latest_test(tx, pid, uid):
    return tx.execute(
        "SELECT * FROM quality_tests WHERE project_id=? AND unit_id=? ORDER BY attempt DESC LIMIT 1",
        (str(pid), str(uid)),
    ).fetchone()


def unresolved(tx, pid, uid):
    return tx.execute(
        """SELECT COUNT(*) FROM nonconformances n LEFT JOIN quality_dispositions d ON d.nonconformance_id=n.id LEFT JOIN rework_orders r ON r.nonconformance_id=n.id LEFT JOIN rework_completions c ON c.rework_order_id=r.id WHERE n.project_id=? AND n.unit_id=? AND NOT EXISTS(SELECT 1 FROM quality_dispositions scrap WHERE scrap.unit_id=n.unit_id AND scrap.decision='scrap') AND (d.id IS NULL OR (d.decision='rework' AND c.id IS NULL))""",
        (str(pid), str(uid)),
    ).fetchone()[0]


def final_good(tx, pid, uid):
    test = latest_test(tx, pid, uid)
    return bool(
        test
        and valid_test(tx, pid, test["id"])
        and test["outcome"] == "pass"
        and not scrapped(tx, pid, uid)
        and not unresolved(tx, pid, uid)
    )


def route_events(tx, pid, unit, steps, rework_id=None, before=None):
    events = []
    for step in steps:
        row = tx.execute(
            """SELECT e.* FROM execution_events e JOIN execution_admissions a ON a.event_id=e.id AND a.project_id=e.project_id WHERE e.project_id=? AND e.unit_id=? AND e.status='accepted' AND a.admitted=1 AND e.station=? AND e.route_version=? AND e.rework_order_id IS ? AND (? IS NULL OR julianday(e.occurred_at)<=julianday(?)) ORDER BY e.accepted_seq DESC LIMIT 1""",
            (
                str(pid),
                unit["id"],
                step.station,
                step.instruction_version,
                str(rework_id) if rework_id else None,
                before,
                before,
            ),
        ).fetchone()
        if not row or row["result"] != "pass":
            fail(
                "complete matching route execution is required before measurement",
                field="execution_event_ids",
            )
        events.append(row["id"])
    return events


def rework_route(tx, pid, unit, ident):
    row = own(tx, "rework_orders", pid, ident)
    if (
        row["unit_id"] != unit["id"]
        or row["revision_id"] != unit["revision_id"]
        or scrapped(tx, pid, unit["id"])
    ):
        fail("rework order does not match eligible serial and revision")
    if tx.execute(
        "SELECT 1 FROM rework_completions WHERE rework_order_id=?", (str(ident),)
    ).fetchone():
        fail("rework order is already complete")
    from .engineering_models import RouteStep

    return row, [RouteStep.model_validate(s) for s in json.loads(row["route_json"])]


def rework_parent_test(tx, pid, rework_id, *, before_seq=None):
    previous = tx.execute(
        "SELECT id FROM quality_tests WHERE project_id=? AND rework_order_id=? AND (? IS NULL OR seq<?) ORDER BY seq DESC LIMIT 1",
        (str(pid), str(rework_id), before_seq, before_seq),
    ).fetchone()
    if previous:
        return previous["id"]
    row = tx.execute(
        "SELECT n.test_id FROM rework_orders r JOIN nonconformances n ON n.id=r.nonconformance_id AND n.project_id=r.project_id WHERE r.id=? AND r.project_id=?",
        (str(rework_id), str(pid)),
    ).fetchone()
    if not row:
        fail("rework has no owned original failed-test basis", field="rework_order_id")
    return row["test_id"]


def require_fresh_route(tx, pid, prior_test_id, events):
    basis = tx.execute(
        "SELECT execution_cutoff FROM quality_test_bases WHERE test_id=? AND project_id=?",
        (str(prior_test_id), str(pid)),
    ).fetchone()
    if not basis or basis["execution_cutoff"] is None:
        fail(
            "repair failure has no unambiguous recorded-order basis",
            field="rework_order_id",
        )
    for ident in events:
        row = own(tx, "execution_events", pid, ident)
        if row["accepted_seq"] <= basis["execution_cutoff"]:
            fail(
                "every repair step requires fresh accepted execution after its own prior test",
                field="execution_event_ids",
            )


def valid_test(tx, pid, test_id):
    return (
        tx.execute(
            "SELECT 1 FROM valid_quality_tests WHERE project_id=? AND id=?",
            (str(pid), str(test_id)),
        ).fetchone()
        is not None
    )


def rebuild_test_bases(tx):
    """Derive v11 cutoffs from exact accepted-fact/audit bindings; never rewrite facts."""
    seen_events, seen_tests, ambiguous_tests, unsafe_projects = (
        set(),
        set(),
        set(),
        set(),
    )
    maxima, inserted = {}, {}
    for audit in tx.execute(
        "SELECT * FROM audit_events WHERE action IN ('execution.record','test.record') ORDER BY id"
    ):
        pid = audit["project_id"]
        try:
            payload = json.loads(audit["typed_payload"])
            key = source_key(payload["source"])
            if payload.get("project_id") != pid:
                unsafe_projects.add(pid)
                continue
            if audit["action"] == "execution.record":
                events = tx.execute(
                    "SELECT * FROM execution_events WHERE project_id=? AND source_system=? AND source_type=? AND source_external_id=? AND source_version=? AND status='accepted' LIMIT 2",
                    (pid, *key, payload["source"]["version"]),
                ).fetchall()
                if len(events) > 1:
                    unsafe_projects.add(pid)
                if len(events) != 1:
                    continue
                event = events[0]
                if event["id"] in seen_events:
                    continue  # rejected duplicate submissions do not move the original accepted fact
                if (
                    audit["object_id"] != event["unit_id"]
                    or payload.get("work_order_id") != event["work_order_id"]
                    or payload["source"] != json.loads(event["source_json"])
                    or payload.get("rework_order_id") != event["rework_order_id"]
                    or any(
                        payload.get(field) != event[field]
                        for field in (
                            "station",
                            "route_version",
                            "program_version",
                            "firmware_version",
                            "result",
                        )
                    )
                    or payload.get("sn") != event["claimed_sn"]
                    or datetime.fromisoformat(payload["occurred_at"])
                    != datetime.fromisoformat(event["occurred_at"])
                ):
                    unsafe_projects.add(pid)
                    continue
                seen_events.add(event["id"])
                maxima[pid] = max(maxima.get(pid, 0), event["accepted_seq"])
            else:
                test = tx.execute(
                    "SELECT * FROM quality_tests WHERE id=? AND project_id=?",
                    (audit["object_id"], pid),
                ).fetchone()
                if not test:
                    continue
                if test["id"] in seen_tests:
                    ambiguous_tests.add(test["id"])
                    continue
                seen_tests.add(test["id"])
                valid = (
                    key
                    == (
                        test["source_system"],
                        test["source_type"],
                        test["source_external_id"],
                    )
                    and payload.get("unit_id") == test["unit_id"]
                    and payload.get("rework_order_id") == test["rework_order_id"]
                    and payload["source"] == json.loads(test["source_json"])
                    and payload.get("attempt") == test["attempt"]
                    and payload.get("measurements")
                    == json.loads(test["measurements_json"])
                )
                prior = (
                    rework_parent_test(
                        tx, pid, test["rework_order_id"], before_seq=test["seq"]
                    )
                    if test["rework_order_id"]
                    else None
                )
                cursor = tx.execute(
                    "INSERT OR IGNORE INTO quality_test_bases VALUES (?,?,?,?)",
                    (test["id"], pid, maxima.get(pid, 0) if valid else None, prior),
                )
                if cursor.rowcount:
                    inserted[test["id"]] = pid
        except (ValueError, KeyError, TypeError, DomainError):
            unsafe_projects.add(pid)
    for event in tx.execute(
        "SELECT id,project_id FROM execution_events WHERE status='accepted'"
    ):
        if event["id"] not in seen_events:
            unsafe_projects.add(event["project_id"])
    for test in tx.execute("SELECT * FROM quality_tests ORDER BY seq"):
        prior = (
            rework_parent_test(
                tx, test["project_id"], test["rework_order_id"], before_seq=test["seq"]
            )
            if test["rework_order_id"]
            else None
        )
        tx.execute(
            "INSERT OR IGNORE INTO quality_test_bases VALUES (?,?,NULL,?)",
            (test["id"], test["project_id"], prior),
        )
    for ident, pid in inserted.items():
        if pid in unsafe_projects or ident in ambiguous_tests:
            tx.execute(
                "UPDATE quality_test_bases SET execution_cutoff=NULL WHERE test_id=?",
                (ident,),
            )


def admitted_quality_source(tx, pid, row, kind, payload=None):
    """Repeat historical admission binding, without requiring current write permission."""
    from types import SimpleNamespace

    from pydantic import ValidationError

    from .imports import record_scope, validate_record

    try:
        record = QualitySourceRecord(
            object_type=kind,
            project_id=row["project_id"],
            source=json.loads(row["source_json"])
            if kind == "test"
            else payload["source"],
            unit_ids=[row["unit_id"]] if kind == "test" else payload["unit_ids"],
            revision_id=row["revision_id"]
            if kind == "test"
            else payload["revision_id"],
            customer_id=None if kind == "test" else payload["customer_id"],
        )
        record_scope(
            tx,
            pid,
            record,
            object_type=kind,
            system=row["source_system"],
            external_id=row["source_external_id"],
            mode="manual",
        )
        if row["source_type"] != kind:
            return None
        validate_record(
            record,
            SimpleNamespace(
                project_id=UUID(str(pid)),
                now=datetime.fromisoformat(
                    row["recorded_at"] if kind == "test" else row["created_at"]
                ),
            ),
            trusted=False,
        )
        return record.source
    except (DomainError, ValidationError, ValueError, KeyError, TypeError):
        return None


def record_test(tx, context, command):
    from .imports import admit_records

    pid = context.project_id
    unit = own(tx, "units", pid, command.unit_id)
    record = QualitySourceRecord(
        object_type="test",
        project_id=pid,
        source=command.source,
        unit_ids=[command.unit_id],
    )
    admit_records(tx, context, [record], object_type="test", mode="manual")
    key = source_key(command.source)
    if tx.execute(
        "SELECT 1 FROM quality_tests WHERE source_system=? AND source_type=? AND source_external_id=?",
        key,
    ).fetchone():
        fail("test source identity already recorded; replay the original operation")
    if scrapped(tx, pid, unit["id"]):
        fail("scrap is an irreversible quality exclusion")
    if not unit["accepted_start_id"]:
        fail("measurement requires an accepted execution scope")
    revision = fixed_revision(tx, pid, unit["revision_id"])
    spec = revision.test_spec
    expected = {m.name: m for m in spec.measurements}
    actual = {m.name: m for m in command.measurements}
    if (
        len(expected) != len(spec.measurements)
        or len(actual) != len(command.measurements)
        or set(actual) != set(expected)
        or (command.limit_version, command.program_version, command.firmware_version)
        != (spec.version, spec.program_version, revision.firmware_version)
    ):
        fail(
            "measurements and versions must match the complete frozen specification",
            422,
            field="measurements",
        )
    for name, limit in expected.items():
        m = actual[name]
        if (m.unit, m.lower, m.upper) != (limit.unit, limit.lower, limit.upper):
            fail(
                "measurement units and limits differ from the frozen specification",
                422,
                field="measurements",
            )
    previous = latest_test(tx, pid, unit["id"])
    if previous and command.source.occurred_at < datetime.fromisoformat(
        previous["occurred_at"]
    ):
        fail("later attempts cannot predate the recorded first-test history")
    if command.attempt != (previous["attempt"] + 1 if previous else 1):
        fail("test attempt must be the next immutable attempt")
    if (
        previous
        and (previous["outcome"] == "fail" or not valid_test(tx, pid, previous["id"]))
        and not command.rework_order_id
    ):
        fail(
            "failed or invalid test proof requires qualified independent rework before retest",
            field="rework_order_id",
        )
    if command.rework_order_id:
        _, steps = rework_route(tx, pid, unit, command.rework_order_id)
    else:
        steps = revision.route_steps
    events = route_events(
        tx,
        pid,
        unit,
        steps,
        command.rework_order_id,
        command.source.occurred_at.isoformat(),
    )
    prior_test_id = None
    if command.rework_order_id:
        prior_test_id = rework_parent_test(tx, pid, command.rework_order_id)
        require_fresh_route(tx, pid, prior_test_id, events)
    equipment = tx.execute(
        "SELECT * FROM readiness_checks WHERE project_id=? AND work_order_id=? AND kind='equipment' AND julianday(created_at)<=julianday(?) ORDER BY rowid DESC LIMIT 1",
        (str(pid), unit["work_order_id"], command.source.occurred_at.isoformat()),
    ).fetchone()
    if (
        not equipment
        or equipment["decision"] != "verified"
        or datetime.fromisoformat(equipment["valid_until"]) < command.source.occurred_at
    ):
        fail("measurement occurrence has no valid equipment calibration")
    scope = TestEvidenceScope(
        route_fingerprint=revision.content_hash,
        test_version=spec.version,
        program_version=spec.program_version,
        firmware_version=revision.firmware_version,
        equipment_check_id=UUID(equipment["id"]),
    )
    ident = str(uuid4())
    outcome = (
        "pass"
        if all(m.lower <= m.value <= m.upper for m in command.measurements)
        else "fail"
    )
    tx.execute(
        "INSERT INTO quality_tests(id,project_id,unit_id,revision_id,attempt,scope_json,measurements_json,outcome,rework_order_id,execution_ids_json,source_system,source_type,source_external_id,source_json,actor_id,occurred_at,recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ident,
            str(pid),
            unit["id"],
            unit["revision_id"],
            command.attempt,
            scope.model_dump_json(),
            json.dumps([m.model_dump(mode="json") for m in command.measurements]),
            outcome,
            str(command.rework_order_id) if command.rework_order_id else None,
            json.dumps(events),
            *key,
            command.source.model_dump_json(),
            str(context.actor.user_id),
            command.source.occurred_at.isoformat(),
            context.now.isoformat(),
        ),
    )
    cutoff = tx.execute(
        "SELECT COALESCE(MAX(accepted_seq),0) FROM execution_events WHERE project_id=? AND status='accepted'",
        (str(pid),),
    ).fetchone()[0]
    tx.execute(
        "INSERT INTO quality_test_bases VALUES (?,?,?,?)",
        (ident, str(pid), cutoff, prior_test_id),
    )
    return MutationResult(object_type="test", object_id=ident)


def complete_pass(
    tx, project_id, test_id, unit_id, revision_id, *, scope: TestEvidenceScope
):
    row = tx.execute(
        "SELECT * FROM quality_tests WHERE project_id=? AND id=? AND unit_id=? AND revision_id=?",
        tuple(map(str, (project_id, test_id, unit_id, revision_id))),
    ).fetchone()
    return bool(
        row
        and valid_test(tx, project_id, row["id"])
        and row["outcome"] == "pass"
        and TestEvidenceScope.model_validate_json(row["scope_json"]) == scope
        and latest_test(tx, project_id, unit_id)["id"] == row["id"]
        and not scrapped(tx, project_id, unit_id)
        and not unresolved(tx, project_id, unit_id)
    )


def open_nonconformance(tx, context, command):
    test = own(tx, "quality_tests", context.project_id, command.test_id)
    if (
        test["outcome"] != "fail"
        or tx.execute(
            "SELECT 1 FROM nonconformances WHERE test_id=?", (test["id"],)
        ).fetchone()
    ):
        fail("nonconformance requires an unlinked failed measured test")
    ident = str(uuid4())
    tx.execute(
        "INSERT INTO nonconformances(id,project_id,unit_id,test_id,defect,evidence,actor_id,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            ident,
            str(context.project_id),
            test["unit_id"],
            test["id"],
            command.defect,
            command.evidence,
            str(context.actor.user_id),
            context.now.isoformat(),
        ),
    )
    return MutationResult(object_type="nonconformance", object_id=ident)


def disposition(tx, context, command):
    pid = context.project_id
    nc = own(tx, "nonconformances", pid, command.nonconformance_id)
    if scrapped(tx, pid, nc["unit_id"]) or (
        command.decision != "scrap"
        and tx.execute(
            "SELECT 1 FROM quality_dispositions WHERE nonconformance_id=?", (nc["id"],)
        ).fetchone()
    ):
        fail("disposition is immutable and scrap cannot be reversed")
    if command.decision == "concession":
        fail("no explicit validated concession policy is configured")
    ident = str(uuid4())
    tx.execute(
        "INSERT INTO quality_dispositions(id,project_id,nonconformance_id,unit_id,decision,evidence,actor_id,created_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            ident,
            str(pid),
            nc["id"],
            nc["unit_id"],
            command.decision,
            command.evidence,
            str(context.actor.user_id),
            context.now.isoformat(),
        ),
    )
    if command.decision == "rework":
        unit = own(tx, "units", pid, nc["unit_id"])
        rwid = str(uuid4())
        tx.execute(
            "INSERT INTO rework_orders(id,project_id,nonconformance_id,unit_id,revision_id,route_id,route_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                rwid,
                str(pid),
                nc["id"],
                unit["id"],
                unit["revision_id"],
                command.route_id,
                json.dumps([s.model_dump() for s in command.route_steps]),
                context.now.isoformat(),
            ),
        )
        return MutationResult(object_type="rework", object_id=rwid)
    return MutationResult(object_type="nonconformance", object_id=nc["id"])


def complete_rework(tx, context, command):
    pid = context.project_id
    row = own(tx, "rework_orders", pid, command.rework_order_id)
    unit = own(tx, "units", pid, row["unit_id"])
    _, steps = rework_route(tx, pid, unit, row["id"])
    expected = route_events(tx, pid, unit, steps, row["id"])
    if len(set(command.execution_event_ids)) != len(command.execution_event_ids) or set(
        map(str, command.execution_event_ids)
    ) != set(expected):
        fail("completion requires the exact accepted independent rework route events")
    latest = latest_test(tx, pid, unit["id"])
    if (
        len(command.test_ids) != 1
        or not latest
        or str(command.test_ids[0]) != latest["id"]
        or latest["outcome"] != "pass"
        or not valid_test(tx, pid, latest["id"])
        or latest["rework_order_id"] != row["id"]
        or set(json.loads(latest["execution_ids_json"])) != set(expected)
    ):
        fail("completion requires the matching latest passed retest after repair")
    tx.execute(
        "INSERT INTO rework_completions VALUES (?,?,?,?,?,?,?)",
        (
            str(uuid4()),
            str(pid),
            row["id"],
            json.dumps(expected),
            json.dumps([latest["id"]]),
            str(context.actor.user_id),
            context.now.isoformat(),
        ),
    )
    return MutationResult(object_type="rework", object_id=row["id"])


def decide_release(tx, context, command):
    pid = context.project_id
    authorize_release(tx, context.actor, pid, command)
    if len(set(command.unit_ids)) != len(command.unit_ids):
        fail("release requires unique explicit serials", 422)
    units = [own(tx, "units", pid, uid) for uid in command.unit_ids]
    if command.decision == "conditional":
        fail("no explicit validated conditional release policy is configured")
    if command.kind == "customer":
        project = project_row(tx, pid)
        contract = json.loads(project["contract_json"])
        if (
            not all(
                (
                    command.customer_id,
                    command.revision_id,
                    command.customer_revision,
                    command.external_signatory,
                    command.source,
                )
            )
            or command.method != "manual"
        ):
            fail(
                "customer receipt requires explicit named external signatory and manual source",
                422,
            )
        revision = fixed_revision(tx, pid, command.revision_id)
        if (
            command.customer_id != project["customer_id"]
            or command.customer_revision != contract["customer_revision"]
            or command.customer_revision != revision.customer_revision
            or any(u["revision_id"] != str(command.revision_id) for u in units)
        ):
            fail(
                "customer receipt must match the current contract, customer and fixed revision"
            )
        from .imports import admit_records

        record = QualitySourceRecord(
            object_type="customer_release",
            project_id=pid,
            source=command.source,
            unit_ids=command.unit_ids,
            revision_id=command.revision_id,
            customer_id=command.customer_id,
        )
        admit_records(
            tx, context, [record], object_type="customer_release", mode="manual"
        )
        if tx.execute(
            "SELECT 1 FROM quality_releases WHERE source_system=? AND source_type=? AND source_external_id=?",
            source_key(command.source),
        ).fetchone():
            fail(
                "customer source decision already recorded; replay the original operation"
            )
    elif any(
        v is not None
        for v in (
            command.customer_id,
            command.revision_id,
            command.customer_revision,
            command.external_signatory,
            command.method,
            command.source,
        )
    ):
        fail("external customer evidence only belongs to customer release", 422)
    if command.decision == "approved" and any(
        not final_good(tx, pid, u["id"]) for u in units
    ):
        fail(
            "approval requires measured final-good serials without open defects or scrap"
        )
    ident = str(uuid4())
    tx.execute(
        "INSERT INTO quality_releases(id,project_id,kind,decision,payload_json,actor_id,created_at,source_system,source_type,source_external_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            ident,
            str(pid),
            command.kind,
            command.decision,
            command.model_dump_json(),
            str(context.actor.user_id),
            context.now.isoformat(),
            *(source_key(command.source) if command.source else (None, None, None)),
        ),
    )
    for unit in units:
        test = latest_test(tx, pid, unit["id"])
        tx.execute(
            "INSERT INTO quality_release_units VALUES (?,?,?,?)",
            (ident, str(pid), unit["id"], test["id"] if test else None),
        )
    return MutationResult(object_type="release", object_id=ident)


def shipment_eligibility(tx, project_id, unit_ids) -> Eligibility:
    project = project_row(tx, project_id)
    contract = json.loads(project["contract_json"])
    reasons, releases, good = [], set(), 0
    if not unit_ids or len(set(map(str, unit_ids))) != len(unit_ids):
        reasons.append("unique explicit serials required")
    for uid in dict.fromkeys(map(str, unit_ids)):
        own(tx, "units", project_id, uid)
        unit_reasons = []
        if not final_good(tx, project_id, uid):
            unit_reasons.append("no final-good measured output")
        if contract["customer_release_required"] == "unknown":
            unit_reasons.append("customer release contract is unknown")
        kinds = ["manufacturing", "quality"] + (
            ["customer"] if contract["customer_release_required"] is True else []
        )
        latest = latest_test(tx, project_id, uid)
        for kind in kinds:
            row = tx.execute(
                "SELECT r.*,u.test_id FROM quality_releases r JOIN quality_release_units u ON u.release_id=r.id WHERE r.project_id=? AND u.unit_id=? AND r.kind=? ORDER BY r.seq DESC LIMIT 1",
                (str(project_id), uid, kind),
            ).fetchone()
            if (
                not row
                or row["decision"] != "approved"
                or not latest
                or row["test_id"] != latest["id"]
            ):
                unit_reasons.append(kind + " approval missing for latest test")
            else:
                releases.add(UUID(row["id"]))
        reasons.extend(uid + ": " + r for r in unit_reasons)
        if not unit_reasons:
            good += 1
    return Eligibility(
        allowed=not reasons,
        reasons=reasons,
        qualified_quantity=amount(good * (10 ** project["unit_scale"]), project),
        release_ids=sorted(releases, key=str),
    )


def final_good_count(tx, pid, order_id=None):
    return tx.execute(
        """SELECT COUNT(*) FROM valid_quality_tests t JOIN units unit ON unit.id=t.unit_id AND unit.project_id=t.project_id JOIN effective_work_orders wo ON wo.id=unit.work_order_id AND wo.project_id=unit.project_id WHERE t.project_id=? AND (? IS NULL OR wo.order_line_id=?) AND t.outcome='pass' AND NOT EXISTS(SELECT 1 FROM quality_tests newer WHERE newer.unit_id=t.unit_id AND newer.attempt>t.attempt) AND NOT EXISTS(SELECT 1 FROM quality_dispositions d WHERE d.unit_id=t.unit_id AND d.decision='scrap') AND NOT EXISTS(SELECT 1 FROM nonconformances n LEFT JOIN quality_dispositions d ON d.nonconformance_id=n.id LEFT JOIN rework_orders r ON r.nonconformance_id=n.id LEFT JOIN rework_completions c ON c.rework_order_id=r.id WHERE n.unit_id=t.unit_id AND (d.id IS NULL OR (d.decision='rework' AND c.id IS NULL)))""",
        (
            str(pid),
            str(order_id) if order_id else None,
            str(order_id) if order_id else None,
        ),
    ).fetchone()[0]


def quality_summary(tx, pid):
    first = tx.execute(
        "SELECT COUNT(*),COALESCE(SUM(outcome='pass'),0) FROM quality_tests WHERE project_id=? AND attempt=1",
        (str(pid),),
    ).fetchone()
    final = final_good_count(tx, pid)
    scrap = tx.execute(
        "SELECT COUNT(DISTINCT unit_id) FROM quality_dispositions WHERE project_id=? AND decision='scrap'",
        (str(pid),),
    ).fetchone()[0]
    open_nc = tx.execute(
        """SELECT COUNT(*) FROM nonconformances n LEFT JOIN quality_dispositions d ON d.nonconformance_id=n.id LEFT JOIN rework_orders r ON r.nonconformance_id=n.id LEFT JOIN rework_completions c ON c.rework_order_id=r.id WHERE n.project_id=? AND NOT EXISTS(SELECT 1 FROM quality_dispositions scrap WHERE scrap.unit_id=n.unit_id AND scrap.decision='scrap') AND (d.id IS NULL OR (d.decision='rework' AND c.id IS NULL))""",
        (str(pid),),
    ).fetchone()[0]
    return QualitySummary(
        first_tested=first[0],
        first_passed=first[1],
        final_good=final,
        scrapped=scrap,
        open_nonconformances=open_nc,
    )


def unit_tests(tx, pid, uid):
    rows = tx.execute(
        "SELECT id,attempt,outcome,rework_order_id,occurred_at FROM quality_tests WHERE project_id=? AND unit_id=? ORDER BY attempt DESC LIMIT 100",
        (str(pid), str(uid)),
    ).fetchall()
    first = tx.execute(
        "SELECT outcome FROM quality_tests WHERE project_id=? AND unit_id=? AND attempt=1",
        (str(pid), str(uid)),
    ).fetchone()
    total = tx.execute(
        "SELECT COUNT(*) FROM quality_tests WHERE project_id=? AND unit_id=?",
        (str(pid), str(uid)),
    ).fetchone()[0]
    return {
        "tests": [TestView(**dict(r)).model_dump(mode="json") for r in reversed(rows)],
        "test_total": total,
        "first_pass": first["outcome"] == "pass" if first else None,
        "scrapped": scrapped(tx, pid, uid),
        "final_good": final_good(tx, pid, uid),
    }


def value_for(tx, pid, kind, row, *, candidates=True):
    if kind == "test":
        return TestValue(
            id=row["id"],
            unit_id=row["unit_id"],
            revision_id=row["revision_id"],
            attempt=row["attempt"],
            scope=TestEvidenceScope.model_validate_json(row["scope_json"]),
            measurements=json.loads(row["measurements_json"]),
            outcome=row["outcome"],
            rework_order_id=row["rework_order_id"],
            execution_event_ids=json.loads(row["execution_ids_json"]),
            source=admitted_quality_source(tx, pid, row, "test"),
            actor_id=row["actor_id"],
            occurred_at=row["occurred_at"],
            recorded_at=row["recorded_at"],
        )
    if kind == "nonconformance":
        d = tx.execute(
            "SELECT * FROM quality_dispositions WHERE nonconformance_id=? ORDER BY seq DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        rw = tx.execute(
            "SELECT r.id,c.id completed FROM rework_orders r LEFT JOIN rework_completions c ON c.rework_order_id=r.id WHERE r.nonconformance_id=?",
            (row["id"],),
        ).fetchone()
        state = (
            "scrapped"
            if d and d["decision"] == "scrap"
            else "resolved"
            if rw and rw["completed"]
            else "rework"
            if rw
            else "open"
        )
        return NonconformanceValue(
            id=row["id"],
            unit_id=row["unit_id"],
            test_id=row["test_id"],
            defect=row["defect"],
            evidence=row["evidence"],
            state=state,
            rework_order_id=rw["id"] if rw else None,
            disposition=d["decision"] if d else None,
            disposition_evidence=d["evidence"] if d else None,
        )
    if kind == "rework":
        from .execution import event_view

        events = []
        if candidates:
            for step in json.loads(row["route_json"]):
                event = tx.execute(
                    "SELECT e.* FROM execution_events e JOIN execution_admissions a ON a.event_id=e.id AND a.project_id=e.project_id WHERE e.project_id=? AND e.unit_id=? AND e.rework_order_id=? AND e.station=? AND e.route_version=? AND e.status='accepted' AND a.admitted=1 ORDER BY e.accepted_seq DESC LIMIT 1",
                    (
                        str(pid),
                        row["unit_id"],
                        row["id"],
                        step["station"],
                        step["instruction_version"],
                    ),
                ).fetchone()
                if event:
                    events.append(event_view(tx, pid, event))
        c = tx.execute(
            "SELECT * FROM rework_completions WHERE rework_order_id=?", (row["id"],)
        ).fetchone()
        return ReworkValue(
            candidate_execution_events=events,
            id=row["id"],
            unit_id=row["unit_id"],
            nonconformance_id=row["nonconformance_id"],
            revision_id=row["revision_id"],
            route_id=row["route_id"],
            route_steps=json.loads(row["route_json"]),
            state="complete" if c else "open",
            execution_event_ids=json.loads(c["execution_ids_json"]) if c else [],
            test_ids=json.loads(c["test_ids_json"]) if c else [],
        )
    payload = json.loads(row["payload_json"])
    tests = tx.execute(
        "SELECT test_id FROM quality_release_units WHERE release_id=? AND test_id IS NOT NULL ORDER BY unit_id",
        (row["id"],),
    ).fetchall()
    return ReleaseValue(
        id=row["id"],
        release_kind=row["kind"],
        unit_ids=payload["unit_ids"],
        decision=row["decision"],
        evidence=payload["evidence"],
        test_ids=[t[0] for t in tests],
        actor_id=row["actor_id"],
        customer_id=payload["customer_id"],
        revision_id=payload["revision_id"],
        customer_revision=payload["customer_revision"],
        external_signatory=payload["external_signatory"],
        method=payload["method"],
        source=admitted_quality_source(tx, pid, row, "customer_release", payload)
        if payload["source"] is not None
        else None,
        recorded_at=row["created_at"],
    )


TABLES = {
    "test": ("quality_tests", TestValue),
    "nonconformance": ("nonconformances", NonconformanceValue),
    "rework": ("rework_orders", ReworkValue),
    "release": ("quality_releases", ReleaseValue),
}


def summary(tx, pid, kind, row):
    value = value_for(tx, pid, kind, row, candidates=False)
    state = getattr(
        value,
        "state",
        getattr(value, "outcome", getattr(value, "decision", "recorded")),
    )
    unit = tx.execute(
        "SELECT sn FROM units WHERE id=? AND project_id=?",
        (str(getattr(value, "unit_id", "")), str(pid)),
    ).fetchone()
    title = f"{kind} · {unit['sn'] if unit else getattr(value, 'release_kind', '')}"
    if kind == "test":
        title += f" · attempt {value.attempt}"
    return ObjectSummary(
        id=row["id"], project_id=pid, kind=kind, title=title, state=state, version=1
    )


def quality_history(tx, pid, kind, row):
    history = []
    for audit in tx.execute(
        "SELECT * FROM audit_events WHERE project_id=? AND object_id=? ORDER BY id LIMIT 500",
        (str(pid), row["id"]),
    ):
        item = dict(audit)
        try:
            payload = json.loads(audit["typed_payload"])
        except (ValueError, TypeError):
            payload = {}
        if (
            payload.get("source") is not None
            or kind == "test"
            or (kind == "release" and row["kind"] == "customer")
        ):
            source = None
            if payload.get("project_id") == str(pid):
                if kind == "test":
                    source = admitted_quality_source(
                        tx,
                        pid,
                        {
                            **dict(row),
                            "source_json": json.dumps(payload.get("source")),
                            "recorded_at": audit["recorded_at"],
                        },
                        "test",
                    )
                elif kind == "release" and row["kind"] == "customer":
                    source = admitted_quality_source(
                        tx,
                        pid,
                        {**dict(row), "created_at": audit["recorded_at"]},
                        "customer_release",
                        payload,
                    )
            if source is None:
                payload.pop("source", None)
                payload.pop("evidence", None)
            else:
                payload["source"] = source.model_dump(mode="json")
        item["typed_payload"] = json.dumps(payload)
        history.append(item)
    return _history_rows(history)


def register_objects(kind, table, model):
    def count(tx, pid):
        return tx.execute(
            f"SELECT COUNT(*) FROM {table} WHERE project_id=?", (str(pid),)
        ).fetchone()[0]

    def page(tx, pid, limit, offset):
        return [
            summary(tx, pid, kind, row)
            for row in tx.execute(
                f"SELECT * FROM {table} WHERE project_id=? ORDER BY seq LIMIT ? OFFSET ?",
                (str(pid), limit, offset),
            )
        ]

    def detail(tx, pid, ident):
        row = tx.execute(
            f"SELECT * FROM {table} WHERE project_id=? AND id=?", (str(pid), str(ident))
        ).fetchone()
        if not row:
            return None
        value = value_for(tx, pid, kind, row)
        relations = (
            [
                ObjectRelation(
                    relation="unit", project_id=pid, kind="unit", id=value.unit_id
                )
            ]
            if hasattr(value, "unit_id")
            else []
        )
        return ObjectDetail[model](
            summary=summary(tx, pid, kind, row),
            value=value,
            relations=relations,
            evidence=[],
            history=quality_history(tx, pid, kind, row),
        )

    OBJECT_REGISTRY.register(kind, model, count=count, summaries=page, detail=detail)


for kind, (table, model) in TABLES.items():
    register_objects(kind, table, model)
for model, handler, roles, qualifications in (
    (RecordTest, record_test, {"quality"}, {"inspection"}),
    (OpenNonconformance, open_nonconformance, {"quality"}, {"inspection"}),
    (Disposition, disposition, {"quality"}, {"disposition"}),
    (CompleteRework, complete_rework, {"quality"}, {"disposition"}),
    (DecideRelease, decide_release, {"production", "quality", "project_owner"}, set()),
):
    COMMAND_REGISTRY.register(
        model, roles=roles, qualifications=qualifications, handler=handler
    )
