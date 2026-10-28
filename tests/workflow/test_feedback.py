"""C3 RMA/CAPA evidence through the public workflow API."""

from .conftest import BASE
from .test_delivery import source_now


def open_rma(workflow):
    p, order, units = workflow.released_order(quantity="1")
    shipment = workflow.ship(p["id"], order["id"], [units[0]["id"]])
    failed = workflow.test(p["id"], units[0]["id"], measured="7")
    result = workflow.command(
        p["id"],
        "rma.open",
        actor_name="quality",
        unit_id=units[0]["id"],
        shipment_id=shipment["id"],
        reason="Customer observed failure",
        source=source_now(workflow, "rma"),
    )
    return (
        p,
        order,
        shipment,
        failed,
        workflow.object(p["id"], "rma", result["object_id"]),
    )


def step(workflow, pid, rma, name, capa=None, **extra):
    return workflow.command(
        pid,
        "capa.update",
        actor_name="quality",
        rma_id=rma["id"],
        capa_id=capa,
        step=name,
        description="Human investigation " + name,
        evidence="Signed " + name + " evidence",
        **extra,
    )


def test_rma_retains_original_delivery_revision_failure_and_manual_source(workflow):
    p, order, shipment, failed, rma = open_rma(workflow)
    assert rma["shipment_id"] == shipment["id"] and rma["order_line_id"] == order["id"]
    assert rma["customer_id"] == "Customer 1" and failed["id"] in rma["test_ids"]
    assert rma["source"]["mode"] == "manual"
    assert workflow.object(p["id"], "shipment", shipment["id"])["shipped"] == "1"
    workflow.command(
        p["id"],
        "closure.record",
        kind="quality",
        source=source_now(workflow, "closure"),
        evidence="review",
        expected_status=409,
    )
    cost = workflow.command(
        p["id"],
        "closure.record",
        kind="cost",
        source=source_now(workflow, "closure"),
        evidence="independent cost review",
    )
    assert workflow.object(p["id"], "closure", cost["object_id"])["status"] == "closed"


def test_ordered_capa_failed_effectiveness_stays_open_supplier_uses_own_implementation(
    workflow,
):
    p, _, _, _, rma = open_rma(workflow)
    step(workflow, p["id"], rma, "root_cause", expected_status=409)
    capa = step(workflow, p["id"], rma, "containment")["object_id"]
    step(workflow, p["id"], rma, "root_cause", capa)
    step(
        workflow,
        p["id"],
        rma,
        "correction",
        capa,
        action_kind="supplier",
        implementation_evidence="Supplier revised inspection and signed implementation record",
    )
    step(workflow, p["id"], rma, "verification", capa, effective=False)
    workflow.command(
        p["id"], "capa.close", actor_name="quality", capa_id=capa, expected_status=409
    )
    assert workflow.object(p["id"], "capa", capa)["state"] == "open"
    step(workflow, p["id"], rma, "verification", capa, effective=True)
    workflow.command(p["id"], "capa.close", actor_name="quality", capa_id=capa)
    detail = workflow.object(p["id"], "capa", capa)
    assert detail["state"] == "closed" and len(detail["steps"]) == 5
    assert workflow.object(p["id"], "rma", rma["id"])["state"] == "closed"


def test_engineering_capa_needs_applicable_actual_new_revision_and_closed_eco(workflow):
    from uuid import uuid4

    p, order, shipment, failed, rma = open_rma(workflow)
    original = workflow.object(p["id"], "order_line", order["id"])
    change = workflow.command(
        p["id"],
        "order.change",
        order_line_id=order["id"],
        new_quantity="2",
        cancel=False,
        new_due_date=original["current_due"],
        reason="Customer orders one future replacement batch",
        source={**original["source"], "version": 2},
    )
    impacts = workflow.object(p["id"], "commitment_change", change["object_id"])[
        "impacts"
    ]
    workflow.command(
        p["id"],
        "order.resolve_change",
        change_id=change["object_id"],
        dispositions=[
            {
                "object_type": i["object_type"],
                "object_id": i["object_id"],
                "decision": "retain",
                "evidence": "Retain actual original delivered obligation",
            }
            for i in impacts
        ],
    )
    future = workflow.command(
        p["id"],
        "work_order.register",
        actor_name="planner",
        order_line_id=order["id"],
        revision_id=rma["revision_id"],
        source=workflow.source(str(uuid4()), object_type="work_order"),
        quantity="1",
        unit="piece",
        purpose="trial",
        trial_quantity="1",
        planned_start="2026-12-01T00:00:00+00:00",
        planned_end="2026-12-02T00:00:00+00:00",
    )
    new = workflow.revision(p["id"], internal_revision="M2")
    workflow.command(
        p["id"],
        "engineering.handoff",
        actor_name="engineering",
        revision_id=new["id"],
        to_system="MES",
        received_revision="M2",
        decision="accepted",
        evidence="Accepted new inspection engineering package",
    )
    workflow.command(
        p["id"],
        "engineering.customer_approval",
        revision_id=new["id"],
        customer_id="Customer 1",
        external_signatory="Customer QE",
        decision="approved",
        evidence="Approved M2",
    )
    eco = workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=rma["revision_id"],
        new_revision_id=new["id"],
        effective_work_order_ids=[future["object_id"]],
        reason="Actual future batch engineering correction",
    )
    cid = step(workflow, p["id"], rma, "containment")["object_id"]
    step(workflow, p["id"], rma, "root_cause", cid)
    step(
        workflow,
        p["id"],
        rma,
        "correction",
        cid,
        action_kind="engineering",
        eco_id=eco["object_id"],
    )
    step(workflow, p["id"], rma, "verification", cid, effective=True)
    workflow.command(
        p["id"], "capa.close", actor_name="quality", capa_id=cid, expected_status=409
    )
    switch = workflow.command(
        p["id"],
        "eco.switch",
        actor_name="engineering",
        eco_id=eco["object_id"],
        target_work_order_id=future["object_id"],
        new_revision_id=new["id"],
        boundary="split_remaining",
        evidence="Replace actual unstarted one-unit batch",
    )
    workflow.command(
        p["id"],
        "exchange.dispatch",
        actor_name="engineering",
        exchange_id=switch["exchange_id"],
    )
    workflow.command(
        p["id"], "capa.close", actor_name="quality", capa_id=cid, expected_status=409
    )
    for impact in workflow.object(p["id"], "eco", eco["object_id"])["impacts"]:
        workflow.command(
            p["id"],
            "eco.disposition",
            actor_name="engineering",
            eco_id=eco["object_id"],
            impact_id=impact["id"],
            quantity=impact["quantity"],
            decision="use_old",
            evidence="Prior actual shipment and material retained; next batch uses new package",
        )
    workflow.command(
        p["id"], "eco.close", actor_name="engineering", eco_id=eco["object_id"]
    )
    workflow.command(p["id"], "capa.close", actor_name="quality", capa_id=cid)
    assert workflow.object(p["id"], "capa", cid)["state"] == "closed"
    assert (
        workflow.object(p["id"], "unit", rma["unit_id"])["revision_id"]
        == rma["revision_id"]
    )
    assert (
        workflow.object(p["id"], "work_order", switch["object_id"])["revision_id"]
        == new["id"]
    )
    assert workflow.object(p["id"], "shipment", shipment["id"])["shipped"] == "1"
    assert workflow.object(p["id"], "test", failed["id"])["outcome"] == "fail"


def test_rma_rejects_unshipped_foreign_scope_source_and_replay_requires_current_actor(
    workflow,
):
    from uuid import uuid4

    p, order, units = workflow.released_order(quantity="2")
    shipped = workflow.ship(p["id"], order["id"], [units[0]["id"]])
    workflow.command(
        p["id"],
        "rma.open",
        actor_name="quality",
        unit_id=units[1]["id"],
        shipment_id=shipped["id"],
        reason="Not shipped",
        source=source_now(workflow, "rma"),
        expected_status=409,
    )
    body = {
        "operation_id": str(uuid4()),
        "expected_version": workflow.client()
        .get(f"{BASE}/projects/{p['id']}")
        .json()["version"],
        "action": "rma.open",
        "unit_id": units[0]["id"],
        "shipment_id": shipped["id"],
        "reason": "Customer report",
        "source": source_now(workflow, "rma"),
    }
    url = f"{BASE}/projects/{p['id']}/commands"
    first = workflow.client("quality").post(url, json=body)
    assert first.status_code == 200
    assert workflow.client("quality").post(url, json=body).json()["replayed"] is True
    workflow.grant(p["id"], "quality", ["quality"], ["inspection"])
    assert workflow.client("quality").post(url, json=body).status_code == 403


def test_closed_retained_eco_is_not_engineering_corrective_implementation(workflow):
    p, _, _, _, rma = open_rma(workflow)
    unit = workflow.object(p["id"], "unit", rma["unit_id"])
    new = workflow.revision(p["id"], internal_revision="M2")
    eco = workflow.command(
        p["id"],
        "eco.open",
        actor_name="engineering",
        old_revision_id=rma["revision_id"],
        new_revision_id=new["id"],
        effective_work_order_ids=[unit["work_order_id"]],
        reason="Retain actual delivered scope",
    )
    for impact in workflow.object(p["id"], "eco", eco["object_id"])["impacts"]:
        workflow.command(
            p["id"],
            "eco.disposition",
            actor_name="engineering",
            eco_id=eco["object_id"],
            impact_id=impact["id"],
            quantity=impact["quantity"],
            decision="use_old",
            evidence="Retain actual prior scope and material",
        )
    workflow.command(
        p["id"],
        "eco.switch",
        actor_name="engineering",
        eco_id=eco["object_id"],
        target_work_order_id=unit["work_order_id"],
        boundary="retain_existing",
        retained_quantity="1",
        evidence="Already produced and shipped original serial",
    )
    workflow.command(
        p["id"], "eco.close", actor_name="engineering", eco_id=eco["object_id"]
    )
    assert (
        workflow.object(p["id"], "eco", eco["object_id"])["implementation_outcome"]
        == "retained"
    )
    cid = step(workflow, p["id"], rma, "containment")["object_id"]
    step(workflow, p["id"], rma, "root_cause", cid)
    step(
        workflow,
        p["id"],
        rma,
        "correction",
        cid,
        action_kind="engineering",
        eco_id=eco["object_id"],
    )
    step(workflow, p["id"], rma, "verification", cid, effective=True)
    workflow.command(
        p["id"], "capa.close", actor_name="quality", capa_id=cid, expected_status=409
    )


def test_historical_rma_audit_does_not_depend_on_current_writer_qualification(workflow):
    p, _, _, _, rma = open_rma(workflow)
    workflow.grant(p["id"], "quality", ["quality"], [])
    detail = (
        workflow.client()
        .get(f"{BASE}/projects/{p['id']}/objects/rma/{rma['id']}")
        .json()
    )
    assert detail["value"]["source"] == rma["source"]
    assert detail["history"][0]["evidence"][0]["source"] == rma["source"]


def test_invalid_rma_source_is_suppressed_in_value_and_restricted_audit_projection(
    workflow,
):
    import json
    import sqlite3

    p, _, _, _, rma = open_rma(workflow)
    url = f"{BASE}/projects/{p['id']}/objects/rma/{rma['id']}"
    original = workflow.client().get(url).json()
    # Corrupt source fixture only: never seed a successful business fact.
    bad = {
        **rma["source"],
        "external_id": "foreign-source-secret",
        "evidence": "unsafe-source-evidence",
    }
    with sqlite3.connect(workflow.paths.domain) as db:
        db.execute(
            "UPDATE rmas SET source_json=? WHERE id=?", (json.dumps(bad), rma["id"])
        )
    read = workflow.client().get(url)
    assert read.status_code == 200
    detail = read.json()
    assert detail["value"]["source"] is None
    assert detail["history"][0]["evidence"] == []
    assert detail["history"][0]["event_id"] == original["history"][0]["event_id"]
    assert (
        "foreign-source-secret" not in read.text
        and "unsafe-source-evidence" not in read.text
    )


def test_failed_capa_revised_correction_binds_new_effectiveness_and_retains_history(workflow):
    p, _, _, _, rma = open_rma(workflow)
    pid = p["id"]
    cid = step(workflow, pid, rma, "containment")["object_id"]
    step(workflow, pid, rma, "root_cause", cid)
    step(workflow, pid, rma, "correction", cid, action_kind="supplier", implementation_evidence="Initial supplier action")
    old_basis = workflow.object(pid, "capa", cid)["steps"][-1]["sequence"]
    step(workflow, pid, rma, "verification", cid, effective=False)
    step(workflow, pid, rma, "correction", cid, action_kind="supplier", implementation_evidence="Improved supplier action")
    workflow.command(pid, "capa.close", actor_name="quality", capa_id=cid, expected_status=409)
    step(workflow, pid, rma, "verification", cid, effective=True, basis_sequence=old_basis, expected_status=409)
    detail = workflow.object(pid, "capa", cid)
    assert len(detail["steps"]) == 5 and detail["steps"][3]["effective"] is False
    basis = detail["current_basis_sequence"]
    step(workflow, pid, rma, "verification", cid, effective=True, basis_sequence=basis)
    workflow.command(pid, "capa.close", actor_name="quality", capa_id=cid)
    assert workflow.object(pid, "capa", cid)["state"] == "closed"


def test_new_capa_investigation_invalidates_successful_prior_verification(workflow):
    p, _, _, _, rma = open_rma(workflow)
    pid = p["id"]
    cid = step(workflow, pid, rma, "containment")["object_id"]
    step(workflow, pid, rma, "root_cause", cid)
    step(workflow, pid, rma, "correction", cid, action_kind="process", implementation_evidence="Implemented")
    step(workflow, pid, rma, "verification", cid, effective=True)
    step(workflow, pid, rma, "root_cause", cid)
    workflow.command(pid, "capa.close", actor_name="quality", capa_id=cid, expected_status=409)
    step(workflow, pid, rma, "verification", cid, effective=True, expected_status=409)
    step(workflow, pid, rma, "correction", cid, action_kind="process", implementation_evidence="New basis implemented")
    step(workflow, pid, rma, "verification", cid, effective=True)
    workflow.command(pid, "capa.close", actor_name="quality", capa_id=cid)
