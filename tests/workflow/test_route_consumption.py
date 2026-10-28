"""Real route completion uses exactly actual material consumption."""

from datetime import UTC, datetime
from uuid import uuid4

from .test_execution import running_execution
from .test_quality import measure


def test_consuming_assembly_nonconsuming_calibration_and_rework(workflow, monkeypatch):
    original = workflow.command

    def with_declared_route(pid, action, **kw):
        if action == "engineering.revision":
            kw["route_steps"] = [
                {"station": "assembly", "instruction_version": "S1"},
                {
                    "station": "calibration",
                    "instruction_version": "S2",
                    "material_consumption": "none",
                },
            ]
        return original(pid, action, **kw)

    monkeypatch.setattr(workflow, "command", with_declared_route)
    p, _wo, units, _, base = running_execution(workflow)
    pid, uid = p["id"], units[0]
    workflow.grant(
        pid, "quality", ["quality"], ["inspection", "disposition", "quality_release"]
    )

    def event(**changes):
        value = {**base, "occurred_at": datetime.now(UTC).isoformat(), **changes}
        result = workflow.command(
            pid,
            "execution.record",
            actor_name="production",
            source=workflow.source(str(uuid4()), object_type="execution"),
            **value,
        )
        return workflow.object(pid, "unit", uid)["execution_events"][-1], result

    missing, _ = event(material_uses=[])
    assert missing["status"] == "rejected" and "material usage" in missing["reason"]
    assembly, _ = event()
    assert assembly["status"] == "accepted"
    measure(workflow, p, uid, expected_status=409)
    calibration, _ = event(station="calibration", route_version="S2", material_uses=[])
    assert calibration["status"] == "accepted" and calibration["material_uses"] == []
    bad_use, _ = event(station="calibration", route_version="S2")
    assert bad_use["status"] == "rejected"
    failed = measure(workflow, p, uid, value="12")
    nc = workflow.command(
        pid,
        "nonconformance.open",
        actor_name="quality",
        test_id=failed["object_id"],
        defect="adjustment",
        evidence="measured",
    )
    rw = workflow.command(
        pid,
        "nonconformance.disposition",
        actor_name="quality",
        nonconformance_id=nc["object_id"],
        decision="rework",
        route_id="ADJ",
        route_steps=[
            {
                "station": "adjust",
                "instruction_version": "A1",
                "material_consumption": "none",
            }
        ],
        evidence="qualified no-parts adjustment",
    )
    adjustment, _ = event(
        station="adjust",
        route_version="A1",
        material_uses=[],
        rework_order_id=rw["object_id"],
    )
    assert adjustment["status"] == "accepted"
    passed = measure(workflow, p, uid, attempt=2, rework_order_id=rw["object_id"])
    workflow.command(
        pid,
        "rework.complete",
        actor_name="quality",
        rework_order_id=rw["object_id"],
        execution_event_ids=[adjustment["id"]],
        test_ids=[passed["object_id"]],
    )
    assert workflow.object(pid, "unit", uid)["final_good"] is True
    with workflow.db() as db:
        assert db.execute(
            "SELECT SUM(q_atoms),COUNT(*) FROM material_consumption WHERE unit_id=?",
            (uid,),
        ).fetchone()[:] == (100, 1)
