"""Quantity fulfilment needs actual scoped receipts, not a coordination note."""
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from .conftest import BASE, USERS
from .test_exchanges import authority
from .test_expedites import accounting


def prepared(w, *, reserved=True, quantity="20", stock_quantity=None):
    stock_quantity = stock_quantity or quantity
    p, req, facts = w.material_requirement(required=quantity, qualified=stock_quantity, mode="oem")
    pid, rid = p["id"], req["id"]
    w.grant(pid, "warehouse", ["warehouse"])
    w.grant(pid, "production", ["production"])
    if reserved:
        with w.db() as tx:
            expiry = tx.execute("SELECT expiry FROM material_lots WHERE id=?", (facts["lot_id"],)).fetchone()[0]
        adapter = authority(w)
        adapter.receive(project_id=pid, external_id="delivery-1", commitment_id=facts["id"],
                        lot_id=facts["lot_id"], material_id="steel-1", owner_id="Customer 1", quantity=stock_quantity,
                        unit="kg", scale=3, expiry=expiry, external_actor="Warehouse", signature="Source receiving")
        adapter.inspect(project_id=pid, external_id="iqc-1", receipt_external_id="delivery-1",
                        accepted=stock_quantity, rejected="0", external_actor="Quality", signature="Source inspection")
        intent = w.command(pid, "reservation.request", actor_name="planner",
                           work_order_id=facts["work_order_id"], requirement_id=rid,
                           lot_id=facts["lot_id"], quantity=quantity, unit="kg")
        w.command(pid, "exchange.dispatch", actor_name="planner", exchange_id=intent["exchange_id"])
        assert w.balance(pid, rid)["reserved"] == quantity
    case = w.command(pid, "expedite.open", actor_name="supply", requirement_id=rid,
                     reason="线边急需", impact="影响当前装配")["object_id"]
    return pid, rid, facts, case


def handoff(w, pid, rid, facts, sent="20", actual="20", *, scoped=True):
    ident = w.command(pid, "material_handoff.record", actor_name="warehouse",
                      material_lot_id=facts["lot_id"], work_order_id=facts["work_order_id"],
                      quantity=sent, unit="kg", from_location="仓库", to_location="线边仓",
                      receiver_id=str(USERS["production"]))["object_id"]
    fields = dict(receipt_use="line_side", requirement_id=rid) if scoped else {}
    w.command(pid, "material_handoff.receive", actor_name="production", handoff_id=ident,
              received_quantity=actual, received_location="线边仓", note="实际签收核对", **fields)
    return ident


def check(w, pid, case):
    result = w.client().get(f"{BASE}/projects/{pid}/objects/material_expedite/{case}")
    assert result.status_code == 200, result.text
    return result.json()["value"]["fulfillment_check"]


def close(w, pid, case, **kwargs):
    return w.command(pid, "expedite.close", actor_name="supply", expedite_id=case,
                     outcome="fulfilled", reason="按当前凭据核对", **kwargs)


def test_fulfilled_cannot_be_written_from_text_or_inspection_alone(workflow):
    w = workflow
    pid, rid, facts, case = prepared(w)
    before = accounting(w)
    close(w, pid, case, expected_status=409)
    assert accounting(w) == before
    assert w.object(pid, "material_expedite", case)["state"] == "open"
    view = check(w, pid, case)
    assert view["can_fulfill"] is False
    assert view["line_received"] is None
    assert view["blocking_reasons"]


def test_receiver_can_confirm_existing_signed_receipt_use_once(workflow):
    w = workflow
    pid, rid, facts, case = prepared(w)
    ident = handoff(w, pid, rid, facts, scoped=False)
    original = w.object(pid, "material_handoff", ident)["receipt"]
    close(w, pid, case, expected_status=409)
    payload = dict(handoff_id=ident, receipt_use="line_side", requirement_id=rid, evidence="该笔已入本工单线边仓")
    w.command(pid, "material_handoff.confirm_use", actor_name="owner", expected_status=403, **payload)
    w.command(pid, "material_handoff.confirm_use", actor_name="production", **payload)
    changed = w.object(pid, "material_handoff", ident)["receipt"]
    for key in ("actor_id", "received_quantity", "received_location", "occurred_at", "recorded_at"):
        assert changed[key] == original[key]
    assert changed["receipt_use"] == "line_side"
    assert changed["requirement_id"] == rid
    w.command(pid, "material_handoff.confirm_use", actor_name="production", expected_status=409, **payload)
    assert check(w, pid, case)["can_fulfill"] is True


def test_direct_signed_line_receipt_can_close_and_saves_exact_proof(workflow):
    w = workflow
    pid, rid, facts, case = prepared(w)
    ident = handoff(w, pid, rid, facts)
    view = check(w, pid, case)
    assert view["can_fulfill"] is True
    assert view["line_received"] == "20"
    assert view["remaining_to_receive"] == "0"
    before = accounting(w)
    version = w.client().get(f"{BASE}/projects/{pid}").json()["version"]
    body = dict(action="expedite.close", operation_id=str(uuid4()), expected_version=version,
                expedite_id=case, outcome="fulfilled", reason="实收满足当前需求")
    response = w.client("supply").post(f"{BASE}/projects/{pid}/commands", json=body)
    assert response.status_code == 200, response.text
    proof = w.object(pid, "material_expedite", case)["closure"]["fulfillment_proof"]
    assert proof["can_fulfill"] is True
    assert ident in proof["evidence_refs"]["handoff_ids"]
    replay = w.client("supply").post(f"{BASE}/projects/{pid}/commands", json=body)
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert accounting(w) == before


def test_short_receipt_found_or_text_resolved_stays_open_until_scoped_supplement(workflow):
    w = workflow
    pid, rid, facts, case = prepared(w)
    original = handoff(w, pid, rid, facts, actual="18")
    view = check(w, pid, case)
    assert view["line_received"] == "18" and view["remaining_to_receive"] == "2"
    close(w, pid, case, expected_status=409)
    w.command(pid, "material_handoff.resolve", actor_name="warehouse", handoff_id=original, resolution="已经找到缺少的2件")
    close(w, pid, case, expected_status=409)
    task = w.command(pid, "material_task.open", actor_name="supply", requirement_id=rid,
                     task_kind="trace", handoff_id=original, assignee_id=str(USERS["warehouse"]), note="追查并补收")["object_id"]
    w.command(pid, "material_task.accept", actor_name="warehouse", task_id=task)
    w.command(pid, "material_task.progress", actor_name="warehouse", task_id=task,
              note="找到2件", found_quantity="2", found_location="仓库")
    close(w, pid, case, expected_status=409)
    supplement = handoff(w, pid, rid, facts, sent="2", actual="2")
    close(w, pid, case, expected_status=409)  # independent events need the explicit supplement relationship
    w.command(pid, "material_task.close", actor_name="warehouse", task_id=task,
              outcome="fulfilled", evidence="同次短收补足并签收", handoff_ids=[supplement])
    assert check(w, pid, case)["can_fulfill"] is True
    close(w, pid, case)


def test_independent_or_multileg_handoffs_are_not_summed(workflow):
    w = workflow
    pid, rid, facts, case = prepared(w)
    handoff(w, pid, rid, facts, sent="8", actual="8")
    handoff(w, pid, rid, facts, sent="12", actual="12")
    view = check(w, pid, case)
    assert view["can_fulfill"] is False and view["line_received"] is None
    close(w, pid, case, expected_status=409)


def test_current_allocation_is_required_even_for_actual_line_receipt(workflow):
    w = workflow
    pid, rid, facts, case = prepared(w, reserved=False)
    handoff(w, pid, rid, facts)
    assert check(w, pid, case)["can_fulfill"] is False
    close(w, pid, case, expected_status=409)


def test_expiry_after_preview_is_rechecked_and_saved_proof_is_historical(workflow):
    w = workflow
    pid, rid, facts, case = prepared(w)
    handoff(w, pid, rid, facts)
    assert check(w, pid, case)["can_fulfill"] is True
    w.business_clock = lambda: datetime(2028, 1, 1, tzinfo=UTC)
    w.reopen()
    assert check(w, pid, case)["can_fulfill"] is False
    close(w, pid, case, expected_status=409)


def test_older_closed_proof_is_not_replaced_by_new_current_checks(workflow):
    w = workflow
    pid, rid, facts, case = prepared(w)
    handoff(w, pid, rid, facts)
    close(w, pid, case)
    original = w.object(pid, "material_expedite", case)["closure"]["fulfillment_proof"]
    w.business_clock = lambda: datetime(2028, 1, 1, tzinfo=UTC)
    w.reopen()
    current = w.object(pid, "material_expedite", case)
    assert current["fulfillment_check"]["can_fulfill"] is False
    assert current["closure"]["fulfillment_proof"] == original


def test_exact_small_remainder_beyond_binary_float_precision(workflow):
    w = workflow
    pid, rid, facts, case = prepared(w, quantity="9007199254740.993")
    handoff(w, pid, rid, facts, sent="9007199254740.993", actual="9007199254740.992")
    view = check(w, pid, case)
    assert view["remaining_to_receive"] == "0.001"
    assert view["can_fulfill"] is False
    close(w, pid, case, expected_status=409)


def test_wrong_destination_cannot_be_fixed_by_a_resolution_note(workflow):
    w = workflow
    pid, rid, facts, case = prepared(w)
    ident = w.command(pid, "material_handoff.record", actor_name="warehouse",
                      material_lot_id=facts["lot_id"], work_order_id=facts["work_order_id"],
                      quantity="20", unit="kg", from_location="仓库", to_location="线边仓",
                      receiver_id=str(USERS["production"]))["object_id"]
    w.command(pid, "material_handoff.receive", actor_name="production", handoff_id=ident,
              received_quantity="20", received_location="暂存区", note="位置不符",
              receipt_use="line_side", requirement_id=rid)
    w.command(pid, "material_handoff.resolve", actor_name="warehouse", handoff_id=ident,
              resolution="已说明位置差异")
    assert check(w, pid, case)["line_received"] is None
    close(w, pid, case, expected_status=409)


def test_actual_receiver_must_still_be_active_for_use_confirmation(workflow):
    w = workflow
    pid, rid, facts, case = prepared(w)
    ident = handoff(w, pid, rid, facts, scoped=False)
    payload = dict(handoff_id=ident, receipt_use="line_side", requirement_id=rid, evidence="核对用途")
    w.inactive.add("production")
    w.command(pid, "material_handoff.confirm_use", actor_name="production", expected_status=403, **payload)
    w.inactive.clear()
    w.read_only.add("production")
    w.command(pid, "material_handoff.confirm_use", actor_name="production", expected_status=403, **payload)
    assert w.object(pid, "material_handoff", ident)["receipt"]["receipt_use"] == "unspecified"


def test_shared_lot_final_receipt_is_not_donated_to_a_second_requirement(workflow):
    w = workflow
    pid, old_rid, facts, case_a = prepared(w, stock_quantity="40")
    now = datetime.now(UTC)
    source = w.source(str(uuid4()), object_type="plan")
    source.update(occurred_at=(now-timedelta(seconds=30)).isoformat(),
                  collected_at=now.isoformat(), cutoff=(now-timedelta(seconds=30)).isoformat())
    plan = w.command(pid, "plan.receive", actor_name="planner",
                     source=source,
                     input_revision_ids=[facts["revision_id"]],
                     input_order_versions=[{"order_line_id": facts["order_id"], "version": 1}],
                     requirements=[dict(work_order_id=facts["work_order_id"], execution_scope=scope,
                                        material_id="steel-1", owner_id="Customer 1", quantity="20", unit="kg")
                                   for scope in ("trial", "bulk")])
    plan_value = w.object(pid, "plan", plan["object_id"])
    assert plan_value["state"] == "confirmed", plan_value["reason"]
    requirements = [dict(w.object(pid, "requirement", rid), id=rid) for rid in plan_value["requirement_ids"]]
    projection = w.client("supply").get(f"{BASE}/projects/{pid}/material-control").json()
    assert {r["id"]: r["execution_scope"] for r in projection["requirements"]} == {r["id"]: r["execution_scope"] for r in requirements}
    first = next(r["id"] for r in requirements if r["execution_scope"] == "trial")
    second = next(r["id"] for r in requirements if r["execution_scope"] == "bulk")
    intent = w.command(pid, "reservation.request", actor_name="planner",
                       work_order_id=facts["work_order_id"], requirement_id=second,
                       lot_id=facts["lot_id"], quantity="20", unit="kg")
    w.command(pid, "exchange.dispatch", actor_name="planner", exchange_id=intent["exchange_id"])
    case_b = w.command(pid, "expedite.open", actor_name="supply", requirement_id=second,
                       reason="另一范围的需求", impact="另一批装配")["object_id"]
    ident = handoff(w, pid, first, facts)
    assert check(w, pid, case_a)["can_fulfill"] is True
    assert check(w, pid, case_b)["can_fulfill"] is False
    assert check(w, pid, case_b)["line_received"] is None
    w.command(pid, "material_handoff.confirm_use", actor_name="production", handoff_id=ident,
              receipt_use="line_side", requirement_id=second, evidence="尝试重复归属", expected_status=409)
    close(w, pid, case_b, expected_status=409)


def test_quality_correction_after_preview_invalidates_fulfilled_close(workflow):
    from .test_exchanges import authority
    from .test_imports import review_correct

    w = workflow
    pid, rid, facts, case = prepared(w)
    handoff(w, pid, rid, facts)
    assert check(w, pid, case)["can_fulfill"] is True
    with w.db() as tx:
        receipt = tx.execute("SELECT * FROM supply_receipts WHERE project_id=?", (pid,)).fetchone()
        receipt_source = json.loads(receipt["source_json"])
        inspection_id = tx.execute("SELECT id FROM iqc_results WHERE receipt_id=?", (receipt["id"],)).fetchone()[0]
        expiry = tx.execute("SELECT expiry FROM material_lots WHERE id=?", (facts["lot_id"],)).fetchone()[0]
    adapter = authority(w)
    adapter.receive(project_id=pid, external_id=receipt_source["external_id"], commitment_id=facts["id"],
                    lot_id=facts["lot_id"], material_id="steel-1", owner_id="Customer 1", quantity="20",
                    unit="kg", scale=3, expiry=expiry, external_actor="Warehouse", signature="Actual source receipt")
    w.command(pid, "source.pull", actor_name="supply", system="erp", object_type="receipt",
              external_id=receipt_source["external_id"])
    adapter.inspect(project_id=pid, external_id="corrected-iqc", receipt_external_id=receipt_source["external_id"],
                    accepted="18", rejected="2", external_actor="Quality", signature="Corrected source result",
                    manual_iqc_id=inspection_id)
    pulled = w.command(pid, "source.pull", actor_name="quality", system="erp", object_type="iqc", external_id="corrected-iqc")
    assert w.object(pid, "exchange", pulled["exchange_id"])["phase"] == "rejected"
    review_correct(w, {"id": pid}, pulled, "iqc", "corrected-iqc")
    current = check(w, pid, case)
    assert current["qualified"] == "18" and current["can_fulfill"] is False
    close(w, pid, case, expected_status=409)


def test_use_confirmation_replay_scope_and_project_version(workflow):
    w = workflow
    pid, rid, facts, case = prepared(w)
    ident = handoff(w, pid, rid, facts, scoped=False)
    version = w.client().get(f"{BASE}/projects/{pid}").json()["version"]
    body = dict(action="material_handoff.confirm_use", operation_id=str(uuid4()), expected_version=version,
                handoff_id=ident, receipt_use="line_side", requirement_id=rid, evidence="核对旧签收用途")
    w.command(pid, "expedite.progress", actor_name="supply", expedite_id=case, note="并行协调")
    rejected = w.client("production").post(f"{BASE}/projects/{pid}/commands", json=body)
    assert rejected.status_code == 409 and rejected.json()["code"] == "VERSION_CONFLICT"
    assert w.object(pid, "material_handoff", ident)["receipt"]["receipt_use"] == "unspecified"
    body["expected_version"] = w.client().get(f"{BASE}/projects/{pid}").json()["version"]
    first = w.client("production").post(f"{BASE}/projects/{pid}/commands", json=body)
    assert first.status_code == 200, first.text
    assert w.client("production").post(f"{BASE}/projects/{pid}/commands", json=body).json()["replayed"] is True
    changed = w.client("production").post(f"{BASE}/projects/{pid}/commands", json={**body, "evidence": "changed"})
    assert changed.status_code == 409 and changed.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_retired_coordinator_cannot_write_a_new_fulfillment_proof(workflow):
    w = workflow
    pid, rid, facts, case = prepared(w)
    handoff(w, pid, rid, facts)
    assert check(w, pid, case)["can_fulfill"] is True
    w.inactive.add("supply")
    close(w, pid, case, expected_status=403)
    assert w.object(pid, "material_expedite", case)["state"] == "open"
