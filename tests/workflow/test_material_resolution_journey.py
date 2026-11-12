"""Controlled platform journey; the external stock authority is an explicit test adapter.

This proves authorized product commands and projections, not native SAP/MES/WMS
identity matching or physical delivery. No successful business facts are patched in SQL.
"""
from datetime import UTC, datetime, timedelta

from .conftest import BASE, USERS
from .test_exchanges import authority
from .test_expedites import accounting
from .test_expedite_fulfillment import check, close, handoff


def test_urgent_iqc_short_receipt_and_signed_supplement_journey(workflow):
    w = workflow
    project, requirement, facts = w.material_requirement(required="20", qualified="0", mode="oem")
    pid, rid = project["id"], requirement["id"]
    w.grant(pid, "warehouse", ["warehouse"])
    w.grant(pid, "production", ["production"])
    path = f"{BASE}/projects/{pid}/material-control"

    def material(problem="all"):
        response = w.client("supply").get(path, params={"search": "steel-1", "problem": problem})
        assert response.status_code == 200, response.text
        return response.json()

    assert material()["requirements"][0]["shortage"] == "20"
    need_at = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    w.command(pid, "material.need_time", actor_name="planner", requirement_id=rid,
              need_at=need_at, evidence="本工单装配排程确认")
    case = w.command(pid, "expedite.open", actor_name="supply", requirement_id=rid,
                     reason="机器人装配急料", impact="本工单装配缺料")["object_id"]
    assert material("urgent")["total"] == 1
    receipt = w.receive(pid, facts["id"], quantity="20", lot_id=facts["lot_id"])["object_id"]
    issue = next(i for i in material("pending_iqc")["requirements"][0]["issues"] if i["code"] == "pending_iqc")
    assert issue["object_id"] == receipt
    task = w.command(pid, "material_task.open", actor_name="supply", requirement_id=rid,
                     task_kind="iqc", receipt_id=receipt, assignee_id=str(USERS["quality"]),
                     note="急料到货，请检验该收货批次")["object_id"]
    w.command(pid, "material_task.accept", actor_name="quality", task_id=task)
    assigned = next(i for i in material("pending_iqc")["requirements"][0]["issues"] if i["code"] == "pending_iqc")
    assert assigned["task_id"] == task and assigned["assignee_id"] == str(USERS["quality"])
    w.inspect(pid, receipt, accepted="20", rejected="0")
    w.command(pid, "material_task.close", actor_name="quality", task_id=task,
              outcome="fulfilled", evidence="本批次IQC结果已正式登记")
    assert material("pending_iqc")["total"] == 0
    close(w, pid, case, expected_status=409)  # Quality alone is not allocation or delivery.

    # Explicit controlled boundary: authority-side receipt/IQC are test-adapter events.
    lot = w.object(pid, "material_lot", facts["lot_id"])
    adapter = authority(w)
    adapter.receive(project_id=pid, external_id="journey-delivery", commitment_id=facts["id"],
                    lot_id=facts["lot_id"], material_id="steel-1", owner_id="Customer 1", quantity="20",
                    unit="kg", scale=3, expiry=lot["expiry"], external_actor="Test warehouse",
                    signature="Controlled authority receiving")
    adapter.inspect(project_id=pid, external_id="journey-iqc", receipt_external_id="journey-delivery",
                    accepted="20", rejected="0", external_actor="Test quality", signature="Controlled authority IQC")
    intent = w.command(pid, "reservation.request", actor_name="planner", work_order_id=facts["work_order_id"],
                       requirement_id=rid, lot_id=facts["lot_id"], quantity="20", unit="kg")
    w.command(pid, "exchange.dispatch", actor_name="planner", exchange_id=intent["exchange_id"])
    assert material()["requirements"][0]["confirmed_satisfied"] == "20"
    inventory = accounting(w)

    original = handoff(w, pid, rid, facts, actual="18")
    assert check(w, pid, case)["remaining_to_receive"] == "2"
    assert material("unreceived")["total"] == 1
    close(w, pid, case, expected_status=409)
    trace = w.command(pid, "material_task.open", actor_name="supply", requirement_id=rid,
                      task_kind="trace", handoff_id=original, assignee_id=str(USERS["warehouse"]),
                      note="追查本笔短收2公斤")["object_id"]
    w.command(pid, "material_task.accept", actor_name="warehouse", task_id=trace)
    w.command(pid, "material_task.progress", actor_name="warehouse", task_id=trace,
              note="已找到2公斤，等待产线实际接收", found_quantity="2", found_location="暂存区")
    close(w, pid, case, expected_status=409)
    supplement = handoff(w, pid, rid, facts, sent="2", actual="2")
    close(w, pid, case, expected_status=409)  # Independent signatures cannot be blindly summed.
    w.command(pid, "material_task.close", actor_name="warehouse", task_id=trace, outcome="fulfilled",
              evidence="本次短收的补交已由指定人实收", handoff_ids=[supplement])
    current = check(w, pid, case)
    assert current["can_fulfill"] and current["line_received"] == "20" and current["remaining_to_receive"] == "0"
    close(w, pid, case)
    proof = w.object(pid, "material_expedite", case)["closure"]["fulfillment_proof"]
    assert set(proof["evidence_refs"]["handoff_ids"]) == {original, supplement}
    assert proof["line_received"] == "20"
    for problem in ("urgent", "pending_iqc", "unreceived"):
        assert material(problem)["total"] == 0
    assert accounting(w) == inventory  # Coordination/signatures do not manufacture stock or IQC.
    assert material()["requirements"][0]["need_at"] == need_at
