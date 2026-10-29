"""Laboratory HTTP evidence uses real execution and quality fixtures."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from .conftest import BASE
from .test_quality import executed, measure


def setup_run(w):
    p, wo, uid, event = executed(w)
    revision = w.object(p["id"], "unit", uid)["revision_id"]
    plan = w.command(
        p["id"],
        "test_plan.publish",
        revision_id=revision,
        level="unit",
        station="bench",
        equipment="meter-1",
        fixture="fixture-1",
        algorithm_version="manual-1",
    )["object_id"]
    run = w.command(
        p["id"], "test_run.start", actor_name="production", plan_id=plan, unit_id=uid
    )["object_id"]
    return p, wo, uid, event, plan, run


def finish_fields(w, run, **overrides):
    source = w.source(str(uuid4()), object_type="test")
    source.update(
        occurred_at=datetime.now(UTC).isoformat(),
        collected_at=datetime.now(UTC).isoformat(),
    )
    fields = {
        "run_id": run,
        "state": "completed",
        "source": source,
        "measurements": [
            {"name": "voltage", "value": "5", "unit": "V", "lower": "4", "upper": "6"}
        ],
        "raw": {
            "origin": "manual",
            "curves": [
                {
                    "name": "voltage",
                    "x_unit": "s",
                    "y_unit": "V",
                    "points": [{"x": "0", "y": "5"}, {"x": "1", "y": "5"}],
                }
            ],
            "logs": ["manual bench observation"],
        },
    }
    fields.update(overrides)
    return fields


def finish(w, p, run, **overrides):
    return w.command(
        p["id"],
        "test_run.finish",
        actor_name="quality",
        **finish_fields(w, run, **overrides),
    )


def test_run_pins_scope_and_enters_existing_quality_without_release(workflow):
    w = workflow
    p, _, uid, _, plan, run = setup_run(w)
    started = w.object(p["id"], "test_run", run)
    assert started["state"] == "running" and started["outcome"] is None
    assert (
        started["execution_event_ids"] and started["scope"]["program_version"] == "P1"
    )
    assert w.object(p["id"], "test_plan", plan)["test_spec"]["version"] == "T1"
    finish(w, p, run)
    value = w.object(p["id"], "test_run", run)
    assert value["state"] == "completed" and value["outcome"] == "pass"
    assert (
        len(value["raw_digest"]) == 64
        and value["raw"]["curves"][0]["points"][1]["y"] == "5"
    )
    assert w.object(p["id"], "test", value["test_id"])["outcome"] == "pass"
    test_response = w.client().get(
        f"{BASE}/projects/{p['id']}/objects/test/{value['test_id']}"
    )
    assert test_response.json()["history"][0]["action"] == "test.record"
    run_response = w.client().get(f"{BASE}/projects/{p['id']}/objects/test_run/{run}")
    assert "calibration.record" in run_response.json()["summary"]["next_actions"]
    assert "no-store" in run_response.headers["cache-control"]
    assert w.object(p["id"], "unit", uid)["tests"][0]["id"] == value["test_id"]
    with w.db() as tx:
        assert tx.execute("SELECT COUNT(*) FROM quality_releases").fetchone()[0] == 0
    finish(w, p, run, expected_status=409)


def test_run_rejects_overrides_cross_revision_and_stale_execution(workflow):
    w = workflow
    p, _, uid, event, plan, run = setup_run(w)
    finish(w, p, run, program_version="P2", expected_status=422)
    finish(
        w,
        p,
        run,
        measurements=[
            {"name": "voltage", "value": "5", "unit": "V", "lower": "0", "upper": "9"}
        ],
        expected_status=422,
    )
    p2, _, uid2, _ = executed(w)
    w.command(
        p["id"], "test_run.start", plan_id=plan, unit_id=uid2, expected_status=404
    )
    w.command(
        p2["id"], "test_run.start", plan_id=plan, unit_id=uid2, expected_status=404
    )
    event["occurred_at"] = datetime.now(UTC).isoformat()
    w.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=w.source(str(uuid4()), object_type="execution"),
        **event,
    )
    finish(w, p, run, expected_status=409)
    assert w.object(p["id"], "unit", uid)["tests"] == []


@pytest.mark.parametrize("state", ["aborted", "invalid"])
def test_noncompleted_attempts_preserve_history_and_never_pass(workflow, state):
    w = workflow
    p, _, uid, _, plan, run = setup_run(w)
    finish(w, p, run, state=state, measurements=[], reason="interrupted acquisition")
    value = w.object(p["id"], "test_run", run)
    assert value["outcome"] is None and value["test_id"] is None
    assert w.object(p["id"], "unit", uid)["tests"] == []
    run2 = w.command(p["id"], "test_run.start", plan_id=plan, unit_id=uid)["object_id"]
    finish(w, p, run2)
    assert w.object(p["id"], "test_run", run2)["attempt"] == 2
    assert w.object(p["id"], "test_run", run)["state"] == state


def test_finish_live_quality_policy_cas_replay_and_readonly(workflow):
    w = workflow
    p, _, _, _, _, run = setup_run(w)
    fields = finish_fields(w, run)
    w.command(
        p["id"],
        "test_run.finish",
        actor_name="production",
        expected_status=403,
        **fields,
    )
    version = w.client().get(f"{BASE}/projects/{p['id']}").json()["version"]
    body = dict(
        action="test_run.finish",
        operation_id=str(uuid4()),
        expected_version=version,
        **fields,
    )
    url = f"{BASE}/projects/{p['id']}/commands"
    assert (
        w.client("quality")
        .post(url, json={**body, "expected_version": version - 1})
        .status_code
        == 409
    )
    assert w.client("quality").post(url, json=body).status_code == 200
    w.reopen()
    assert w.client("quality").post(url, json=body).json()["replayed"]
    w.read_only.add("quality")
    assert w.client("quality").post(url, json=body).status_code == 403
    w.read_only.clear()
    w.grant(p["id"], "quality", ["quality"], [])
    assert w.client("quality").post(url, json=body).status_code == 403


@pytest.mark.parametrize("actor_name", ["quality", "owner"])
def test_calibration_requires_successful_run_and_independent_matching_readback(
    workflow,
    actor_name,
):
    w = workflow
    p, _, _, _, _, run = setup_run(w)
    params = [{"name": "gain", "value": "1.25", "unit": "ratio"}]
    fields = {
        "run_id": run,
        "algorithm_version": "manual-1",
        "parameters": params,
        "origin": "manual",
        "source_identity": "bench-record-1",
        "source_version": "1",
        "evidence": "bench calculation",
    }
    w.command(p["id"], "calibration.record", expected_status=409, **fields)
    finish(w, p, run)
    w.command(
        p["id"],
        "calibration.record",
        expected_status=409,
        **{**fields, "algorithm_version": "wrong"},
    )
    calibration = w.command(
        p["id"], "calibration.record", actor_name=actor_name, **fields
    )["object_id"]
    assert w.object(p["id"], "calibration", calibration)["state"] == "pending"
    confirmation = {
        "calibration_id": calibration,
        "readback": params,
        "origin": "manual",
        "source_identity": "meter-1 readback-1",
        "source_version": "1",
        "evidence": "separate signed readback",
    }
    w.command(
        p["id"],
        "calibration.confirm",
        actor_name="production",
        expected_status=403,
        **confirmation,
    )
    w.command(
        p["id"],
        "calibration.confirm",
        expected_status=409,
        **{
            **confirmation,
            "readback": [{"name": "gain", "value": "2", "unit": "ratio"}],
        },
    )
    w.command(
        p["id"],
        "calibration.confirm",
        actor_name=actor_name,
        expected_status=409,
        **{**confirmation, "source_identity": fields["source_identity"]},
    )
    receipt = w.command(
        p["id"], "calibration.confirm", actor_name=actor_name, **confirmation
    )
    replay_body = dict(
        action="calibration.confirm",
        operation_id=receipt["operation_id"],
        expected_version=receipt["project_version"] - 1,
        **confirmation,
    )
    replay = w.client(actor_name).post(
        f"{BASE}/projects/{p['id']}/commands", json=replay_body
    )
    assert replay.status_code == 200 and replay.json()["replayed"]
    with w.db() as tx:
        audits = tx.execute(
            "SELECT action FROM audit_events WHERE object_id=? ORDER BY id",
            (calibration,),
        ).fetchall()
        assert [r[0] for r in audits] == ["calibration.record", "calibration.confirm"]
    value = w.object(p["id"], "calibration", calibration)
    assert (
        value["state"] == "confirmed"
        and value["confirmation"]["actor_id"] == value["actor_id"]
    )
    assert value["confirmation"]["origin"] == "manual"


def test_components_aliases_and_scoped_history(workflow, monkeypatch):
    w = workflow
    p, _, uid, _, _, _ = setup_run(w)
    fields = {
        "unit_id": uid,
        "material_id": "connector",
        "component_serial": "C001",
        "origin": "manual",
        "evidence": "signed installation",
    }
    link = w.command(p["id"], "component.install", **fields)["object_id"]
    w.command(p["id"], "component.install", expected_status=409, **fields)
    w.command(
        p["id"], "component.remove", component_link_id=link, evidence="signed removal"
    )
    again = w.command(p["id"], "component.install", **fields)["object_id"]
    unit = w.object(p["id"], "unit", uid)
    assert [x["state"] for x in unit["components"]] == ["removed", "installed"]
    assert unit["components"][0]["id"] == link and unit["components"][1]["id"] == again
    original_sn = unit["sn"]
    w.command(
        p["id"],
        "unit.alias",
        unit_id=uid,
        customer_serial="001",
        evidence="customer label",
    )
    w.command(
        p["id"],
        "unit.alias",
        unit_id=uid,
        customer_serial="002",
        evidence="second label",
    )
    assert w.object(p["id"], "unit", uid)["sn"] == original_sn
    assert [
        x["customer_serial"] for x in w.object(p["id"], "unit", uid)["aliases"]
    ] == ["001", "002"]
    p2, _, uid2, _ = executed(w)
    w.command(
        p2["id"],
        "unit.alias",
        unit_id=uid2,
        customer_serial="001",
        evidence="collision",
        expected_status=409,
    )
    original_command = w.command

    def other_customer_command(pid, action, **fields):
        if action == "engineering.customer_approval":
            fields["customer_id"] = "Other customer"
        return original_command(pid, action, **fields)

    monkeypatch.setattr(w, "command", other_customer_command)
    original = w.create_project
    monkeypatch.setattr(
        w,
        "create_project",
        lambda **kw: original(**{**kw, "customer_id": "Other customer"}),
    )
    p3, _, uid3, _ = executed(w)
    w.command(
        p3["id"],
        "unit.alias",
        unit_id=uid3,
        customer_serial="001",
        evidence="separate namespace",
    )
    assert (
        w.client("outsider")
        .get(f"{BASE}/projects/{p['id']}/objects/unit/{uid}")
        .status_code
        == 404
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"origin": "manual", "curves": [], "logs": [], "path": "/etc/passwd"},
        {
            "origin": "manual",
            "curves": [
                {
                    "name": "v",
                    "x_unit": "s",
                    "y_unit": "V",
                    "points": [{"x": "NaN", "y": "1"}],
                }
            ],
            "logs": [],
        },
        {"origin": "manual", "curves": [], "logs": ["x" * 4001]},
    ],
)
def test_raw_evidence_is_bounded_structured_data(workflow, raw):
    p, _, _, _, _, run = setup_run(workflow)
    finish(workflow, p, run, raw=raw, expected_status=422)


def test_failed_attempt_rework_retains_quality_history(workflow):
    from .test_quality import rework

    w = workflow
    p, _, uid, event, plan, run = setup_run(w)
    finish(
        w,
        p,
        run,
        measurements=[
            {"name": "voltage", "value": "12", "unit": "V", "lower": "4", "upper": "6"}
        ],
    )
    failed = w.object(p["id"], "test_run", run)
    assert failed["outcome"] == "fail"
    _, rw = rework(w, p, {"object_id": failed["test_id"]})
    event.update(
        station="repair",
        route_version="RW-S1",
        rework_order_id=rw["object_id"],
        occurred_at=datetime.now(UTC).isoformat(),
    )
    w.command(
        p["id"],
        "execution.record",
        actor_name="production",
        source=w.source(str(uuid4()), object_type="execution"),
        **event,
    )
    second = w.command(
        p["id"],
        "test_run.start",
        plan_id=plan,
        unit_id=uid,
        rework_order_id=rw["object_id"],
    )["object_id"]
    finish(w, p, second)
    current = w.object(p["id"], "test_run", second)
    assert current["attempt"] == 2 and current["outcome"] == "pass"
    assert [t["outcome"] for t in w.object(p["id"], "unit", uid)["tests"]] == [
        "fail",
        "pass",
    ]
    assert w.object(p["id"], "unit", uid)["final_good"] is False
    w.command(
        p["id"],
        "rework.complete",
        actor_name="quality",
        rework_order_id=rw["object_id"],
        execution_event_ids=current["execution_event_ids"],
        test_ids=[current["test_id"]],
    )
    assert w.object(p["id"], "unit", uid)["final_good"]


def test_schema19_additive_migration_preserves_old_facts(workflow):
    import sqlite3

    from manufacturing_platform.workflow.schema import SCHEMA_VERSION

    w = workflow
    p, _, uid, _ = executed(w)
    measure(w, p, uid)
    tables = [
        "projects",
        "units",
        "quality_tests",
        "quality_test_bases",
        "operations",
        "audit_events",
    ]
    with w.db() as tx:
        before = {
            table: [
                tuple(r) for r in tx.execute(f"SELECT * FROM {table} ORDER BY rowid")
            ]
            for table in tables
        }
    w._client.close()
    with sqlite3.connect(w.paths.domain) as tx:
        for table in [
            "unit_aliases",
            "component_links",
            "calibrations",
            "test_runs",
            "test_plans",
        ]:
            tx.execute(f"DROP TABLE {table}")
        tx.execute("UPDATE schema_version SET version=19")
    w.reopen()
    assert w.object(p["id"], "unit", uid)["sn"]
    with w.db() as tx:
        assert (
            tx.execute("SELECT version FROM schema_version").fetchone()[0]
            == SCHEMA_VERSION
        )
        assert before == {
            table: [
                tuple(r) for r in tx.execute(f"SELECT * FROM {table} ORDER BY rowid")
            ]
            for table in tables
        }
    w.command(
        p["id"],
        "unit.alias",
        unit_id=uid,
        customer_serial="migration",
        evidence="post-migration label",
    )


def test_alias_replay_and_cross_project_collision_do_not_disclose_source(workflow):
    w = workflow
    p, _, uid, _ = executed(w)
    version = w.client().get(f"{BASE}/projects/{p['id']}").json()["version"]
    body = {
        "action": "unit.alias",
        "operation_id": str(uuid4()),
        "expected_version": version,
        "unit_id": uid,
        "customer_serial": "PRIVATE-001",
        "evidence": "private label",
    }
    url = f"{BASE}/projects/{p['id']}/commands"
    assert w.client("production").post(url, json=body).status_code == 200
    assert w.client("production").post(url, json=body).json()["replayed"]
    assert len(w.object(p["id"], "unit", uid)["aliases"]) == 1
    w.grant(p["id"], "production", [], active=False)
    assert w.client("production").post(url, json=body).status_code == 404
    p2, _, uid2, _ = executed(w)
    denied = w.command(
        p2["id"],
        "unit.alias",
        actor_name="production",
        unit_id=uid2,
        customer_serial="PRIVATE-001",
        evidence="collision",
        expected_status=409,
    )
    assert uid not in str(denied) and p["id"] not in str(denied)
    foreign = w.client("production").get(
        f"{BASE}/projects/{p2['id']}/objects/unit/{uid}"
    )
    assert foreign.status_code == 404


def test_same_project_plan_revision_mismatch_and_component_second_parent(workflow):
    w = workflow
    p, _, uid, _, _plan, _ = setup_run(w)
    revision = w.revision(p["id"], internal_revision="M2")
    plan2 = w.command(
        p["id"],
        "test_plan.publish",
        revision_id=revision["id"],
        level="unit",
        station="bench",
        equipment="meter",
        fixture="fixture",
        algorithm_version="manual-1",
    )["object_id"]
    w.command(
        p["id"], "test_run.start", plan_id=plan2, unit_id=uid, expected_status=409
    )


@pytest.mark.parametrize(
    "level", ["board", "component", "subassembly", "unit", "printer_motion_system"]
)
def test_plan_levels_remain_distinct_and_extensible(workflow, level):
    w = workflow
    p, _, _, revision = w.order_workorder(quantity="1")
    result = w.command(
        p["id"],
        "test_plan.publish",
        revision_id=revision["id"],
        level=level,
        station="named bench",
        equipment="manual meter",
        fixture="named fixture",
        algorithm_version="manual-1",
    )
    assert w.object(p["id"], "test_plan", result["object_id"])["level"] == level


def test_component_active_identity_lot_scope_and_parent_relations(workflow):
    w = workflow
    p, _wo, uid, _, _, _ = setup_run(w)
    units = w.client().get(f"{BASE}/projects/{p['id']}/objects/unit").json()["items"]
    second = next(u["id"] for u in units if u["id"] != uid)
    with w.db() as tx:
        lot = tx.execute(
            "SELECT id FROM material_lots WHERE project_id=?", (p["id"],)
        ).fetchone()[0]
    fields = {
        "material_id": "steel-1",
        "component_serial": "Ｃ００１",
        "lot_id": lot,
        "origin": "manual",
        "evidence": "signed component identity",
    }
    link = w.command(p["id"], "component.install", unit_id=uid, **fields)["object_id"]
    w.command(
        p["id"],
        "component.install",
        unit_id=second,
        expected_status=409,
        **{**fields, "component_serial": "C001"},
    )
    w.command(
        p["id"],
        "component.install",
        unit_id=second,
        expected_status=409,
        **{**fields, "material_id": "other"},
    )
    p2, _, _, _ = executed(w)
    with w.db() as tx:
        foreign_lot = tx.execute(
            "SELECT id FROM material_lots WHERE project_id=?", (p2["id"],)
        ).fetchone()[0]
    w.command(
        p["id"],
        "component.install",
        unit_id=second,
        expected_status=404,
        **{**fields, "lot_id": foreign_lot},
    )
    response = w.client().get(
        f"{BASE}/projects/{p['id']}/objects/component_link/{link}"
    )
    assert any(
        r["kind"] == "unit" and r["id"] == uid for r in response.json()["relations"]
    )
    w.command(
        p["id"], "component.remove", component_link_id=link, evidence="verified removal"
    )
    w.command(p["id"], "component.install", unit_id=second, **fields)
    assert w.object(p["id"], "unit", uid)["components"][0]["state"] == "removed"


def test_equipment_refresh_invalidates_open_run_and_raw_digest_binds_content(workflow):
    import hashlib
    import json
    from datetime import timedelta

    w = workflow
    p, wo, uid, _, plan, run = setup_run(w)
    w.command(
        p["id"],
        "readiness.record",
        work_order_id=wo["id"],
        kind="equipment",
        reference="new calibration",
        evidence="renewed calibration",
        decision="verified",
        valid_until=(datetime.now(UTC) + timedelta(days=60)).isoformat(),
    )
    finish(w, p, run, expected_status=409)
    finish(
        w, p, run, state="invalid", measurements=[], reason="equipment scope replaced"
    )
    new = w.command(p["id"], "test_run.start", plan_id=plan, unit_id=uid)["object_id"]
    finish(w, p, new)
    value = w.object(p["id"], "test_run", new)
    bound = {"run_id": new, "source": value["finish"]["source"], "raw": value["raw"]}
    calculated = hashlib.sha256(
        json.dumps(
            bound, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    assert value["raw_digest"] == calculated


def test_demo_calibration_cannot_lose_origin_or_reuse_record_as_readback(workflow):
    w = workflow
    p, _, _, _, _, run = setup_run(w)
    raw = finish_fields(w, run)["raw"]
    raw["origin"] = "demo"
    finish(w, p, run, raw=raw)
    fields = {
        "run_id": run,
        "algorithm_version": "manual-1",
        "parameters": [{"name": "gain", "value": "1", "unit": "ratio"}],
        "origin": "manual",
        "source_identity": "record-1",
        "source_version": "1",
        "evidence": "simulated calculation",
    }
    w.command(p["id"], "calibration.record", expected_status=409, **fields)
    fields["origin"] = "demo"
    calibration = w.command(
        p["id"], "calibration.record", actor_name="quality", **fields
    )["object_id"]
    confirm = {
        "calibration_id": calibration,
        "readback": fields["parameters"],
        "origin": "demo",
        "source_identity": "record-1",
        "source_version": "1",
        "evidence": "simulated readback",
    }
    w.command(p["id"], "calibration.confirm", expected_status=409, **confirm)
    confirm["source_identity"] = "readback-1"
    w.command(
        p["id"],
        "calibration.confirm",
        expected_status=409,
        **{**confirm, "origin": "manual"},
    )
    w.command(p["id"], "calibration.confirm", **confirm)
    assert (
        w.object(p["id"], "calibration", calibration)["confirmation"]["origin"]
        == "demo"
    )


def test_small_curve_values_and_exact_parameter_digest_do_not_round(workflow):
    w = workflow
    p, _, _, _, _, run = setup_run(w)
    raw = finish_fields(w, run)["raw"]
    raw["curves"][0]["points"] = [{"x": "0.00000000000001", "y": "0.00000000000002"}]
    finish(w, p, run, raw=raw)
    assert (
        w.object(p["id"], "test_run", run)["raw"]["curves"][0]["points"]
        == raw["curves"][0]["points"]
    )
    params = [
        {"name": "gain", "value": "12345678901234567890123456789.1", "unit": "ratio"}
    ]
    calibration = w.command(
        p["id"],
        "calibration.record",
        actor_name="quality",
        run_id=run,
        algorithm_version="manual-1",
        parameters=params,
        origin="manual",
        source_identity="precision-record",
        source_version="1",
        evidence="precise measured parameter",
    )["object_id"]
    confirmation = {
        "calibration_id": calibration,
        "readback": [{**params[0], "value": "12345678901234567890123456789.2"}],
        "origin": "manual",
        "source_identity": "precision-readback",
        "source_version": "1",
        "evidence": "precise readback",
    }
    w.command(p["id"], "calibration.confirm", expected_status=409, **confirmation)
    confirmation["readback"] = params
    w.command(p["id"], "calibration.confirm", **confirmation)


def test_laboratory_summaries_show_verdict_titles_blockers_and_live_actions(workflow):
    w = workflow
    p, _, uid, _, plan, run = setup_run(w)
    sn = w.object(p["id"], "unit", uid)["sn"]

    def summary(kind, ident, actor="owner"):
        response = w.client(actor).get(
            f"{BASE}/projects/{p['id']}/objects/{kind}/{ident}"
        )
        assert response.status_code == 200
        return response.json()["summary"]

    plan_summary = summary("test_plan", plan)
    assert "bench" in plan_summary["title"] and "unit" in plan_summary["title"]
    assert plan_summary["next_actions"] == ["test_run.start"]
    running = summary("test_run", run)
    assert sn in running["title"] and "bench" in running["title"]
    assert running["next_actions"] == ["test_run.finish"]
    assert summary("test_run", run, "production")["next_actions"] == []
    finish(
        w,
        p,
        run,
        measurements=[
            {"name": "voltage", "value": "12", "unit": "V", "lower": "4", "upper": "6"}
        ],
    )
    failed = summary("test_run", run)
    assert failed["state"] == "fail" and failed["blocking_reasons"]
    assert failed["next_actions"] == []
    assert w.object(p["id"], "test_run", run)["state"] == "completed"
    link = w.command(
        p["id"],
        "component.install",
        unit_id=uid,
        material_id="connector",
        component_serial="COMP-1",
        origin="manual",
        evidence="manual installation",
    )["object_id"]
    installed = summary("component_link", link)
    assert sn in installed["title"] and "COMP-1" in installed["title"]
    assert installed["next_actions"] == ["component.remove"]
    w.command(
        p["id"], "component.remove", component_link_id=link, evidence="manual removal"
    )
    assert summary("component_link", link)["next_actions"] == []
    p, _, uid, _, _, run = setup_run(w)
    finish(w, p, run)
    assert summary("test_run", run)["next_actions"] == ["calibration.record"]
    parameters = [{"name": "gain", "value": "1", "unit": "ratio"}]
    calibration = w.command(
        p["id"],
        "calibration.record",
        run_id=run,
        algorithm_version="manual-1",
        parameters=parameters,
        source_identity="calculation-1",
        source_version="1",
        origin="manual",
        evidence="manual calculation",
    )["object_id"]
    pending = summary("calibration", calibration)
    assert "manual-1" in pending["title"] and pending["blocking_reasons"]
    assert pending["next_actions"] == ["calibration.confirm"]
    w.command(
        p["id"],
        "calibration.confirm",
        calibration_id=calibration,
        readback=parameters,
        source_identity="readback-1",
        source_version="1",
        origin="manual",
        evidence="separate readback evidence",
    )
    confirmed = summary("calibration", calibration)
    assert confirmed["next_actions"] == [] and confirmed["blocking_reasons"] == []
