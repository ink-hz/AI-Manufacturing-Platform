"""Test-only scenarios using the real fixed producer composition and business APIs."""

from dataclasses import dataclass, replace
from uuid import uuid4
from .support import NOW


@dataclass
class ScenarioRefs:
    name: str
    core: object
    facts: list


def synchronize(rig):
    from manufacturing_platform.workflow.integrations.catalog import SYSTEM_IDS

    for _ in range(12):
        batch = rig.drain(limit=200)
        if not batch.pending:
            break
    assert not batch.failed and not batch.pending, batch
    # Follow actual source commitment order; producers precede consumer children.
    pending = []
    for system in SYSTEM_IDS:
        from manufacturing_platform.workflow.integrations.contracts import (
            IntegrationFact,
        )

        pending.extend(
            IntegrationFact.model_validate_json(row["fact_json"])
            for row in rig.rows(system, "facts")
            if row["project_id"] == str(rig.project_id)
        )
    while pending:
        progress = False
        remaining = []
        for fact in pending:
            if rig.projection_count(fact.source_key):
                progress = True
                continue
            if all(rig.projection_count(k) for k in fact.caused_by):
                rig.pull(fact.source_key)
                progress = True
            else:
                remaining.append(fact)
        assert progress, [(f.payload.fact_type, f.caused_by) for f in remaining]
        pending = remaining


def approval_request(rig, refs):
    revision = next(
        f
        for f in rig.registry.adapter("pdm")
        .facts(rig.project_id, "revision", 0, 200)
        .records
        if rig.target(f, "revision") == refs.revision
    )
    npi = rig.command(
        "npi.open",
        revision_id=str(refs.revision),
        product_family="P",
        scenario="first_introduction",
        required_checks=["design"],
        work_order_ids=[str(refs.work_order)],
    ).object_id
    target = dict(
        target_type="engineering",
        source_key=revision.source_key.model_dump(),
        npi_id=str(npi),
        revision_id=str(refs.revision),
        checks=[
            dict(
                code="design",
                required=True,
                decision="pass",
                evidence="Design reviewed",
                reason="Verified",
            )
        ],
    )
    rig.execute(
        "mes",
        dict(
            operation="mes.prepare",
            work_order_id=str(refs.work_order),
            unit_ids=[u["unit_id"] for u in refs.units],
            test_plan_id=str(refs.test_plan),
            equipment_id="EQ1",
            approval_target=target,
        ),
    )
    request = (
        rig.registry.adapter("mes")
        .facts(rig.project_id, "approval_request", 0, 200)
        .records[-1]
    )
    rig.execute(
        "oa",
        dict(
            operation="oa.decide_approval",
            target=target,
            request=request.source_key.model_dump(),
            decision="approved",
            external_signer="Engineering reviewer",
            signed_at=NOW.isoformat(),
            evidence="Signed OA engineering review",
        ),
    )
    rig.execute(
        "customer",
        dict(
            operation="customer.approve_revision",
            revision_id=str(refs.revision),
            revision=revision.source_key.model_dump(),
            customer_id="C",
            decision="approved",
            external_signer="Customer design authority",
            signed_at=NOW.isoformat(),
            evidence="Independent design approval",
        ),
    )


def finish_measured(rig, refs):
    rig.execute("mes", refs.start_payload)
    refs.execution = rig.pass_unit(refs)
    refs.run = rig.command(
        "test_run.start", plan_id=str(refs.test_plan), unit_id=refs.units[0]["unit_id"]
    ).object_id
    prepared = rig.result_fact(
        rig.execute(
            "product_test",
            dict(
                operation="product_test.prepare_artifact",
                run_id=str(refs.run),
                template="pass-v1",
            ),
        )
    )
    refs.test = rig.result_fact(
        rig.execute(
            "product_test",
            dict(
                operation="product_test.run",
                **prepared.payload.prepared.model_dump(mode="json", exclude={"kind"}),
            ),
        )
    )
    return refs


def completion(rig):
    refs = rig.start_ready()
    approval_request(rig, refs)
    # Preparation created a fresh process request; select its actual observation.
    request = (
        rig.registry.adapter("mes")
        .facts(rig.project_id, "process_request", 0, 200)
        .records[-1]
    )
    equipment = rig.result_fact(
        rig.execute(
            "plc",
            dict(
                operation="plc.set_state",
                equipment="EQ1",
                state="available",
                program_version="P1",
                process_request=request.source_key.model_dump(),
                observed_at=NOW.isoformat(),
                evidence="Current prepared equipment",
            ),
        )
    )
    refs.start_payload["equipment"] = equipment.source_key.model_dump()
    finish_measured(rig, refs)
    start = (
        rig.registry.adapter("mes").facts(rig.project_id, "start", 0, 200).records[-1]
    )
    rig.execute(
        "plc",
        dict(
            operation="plc.sample",
            equipment="EQ1",
            work_order_id=str(refs.work_order),
            unit_id=refs.units[0]["unit_id"],
            mes_session=start.source_key.model_dump(),
            program_version="P1",
            parameters=[dict(name="cycle", value="1", unit="s")],
            observed_at=NOW.isoformat(),
            evidence="Independent process sample",
        ),
    )
    prepared = rig.result_fact(
        rig.execute(
            "product_test",
            dict(
                operation="product_test.prepare_artifact",
                run_id=str(refs.run),
                template="calibration-v1",
            ),
        )
    )
    calibration = rig.result_fact(
        rig.execute(
            "product_test",
            dict(
                operation="product_test.calibrate",
                **prepared.payload.prepared.model_dump(mode="json", exclude={"kind"}),
            ),
        )
    )
    p = calibration.payload
    rig.execute(
        "plc",
        dict(
            operation="plc.readback",
            calibration=calibration.source_key.model_dump(),
            run_id=str(refs.run),
            unit_id=refs.units[0]["unit_id"],
            equipment="EQ1",
            source_identity="PLC-original-readback",
            source_version="1",
            parameters=[v.model_dump(mode="json") for v in p.parameters],
            observed_at=NOW.isoformat(),
            evidence="Independent observed parameter values",
        ),
    )
    rig.execute(
        "mes",
        dict(
            operation="mes.assemble",
            work_order_id=str(refs.work_order),
            unit_id=refs.units[0]["unit_id"],
            material_id="M",
            material_lot_id=str(refs.lot),
            component_serial="COMPONENT1",
            execution=refs.execution.source_key.model_dump(),
            evidence="Actual installed component",
        ),
    )
    rig.execute(
        "mes",
        dict(
            operation="mes.complete",
            work_order_id=str(refs.work_order),
            revision_id=str(refs.revision),
            units=refs.units,
            execution_sources=[refs.execution.source_key.model_dump()],
            consumption=[
                a.model_dump(mode="json") for a in refs.execution.payload.material_uses
            ],
            occurred_at=NOW.isoformat(),
        ),
    )
    needed = (
        rig.registry.adapter("mes")
        .facts(rig.project_id, "return_requirement", 0, 200)
        .records[-1]
    )
    returned = rig.result_fact(
        rig.execute(
            "wms",
            dict(
                operation="wms.return",
                direction="to_warehouse",
                **(
                    needed.payload.model_dump(mode="json", exclude={"fact_type"})
                    | {"cause": needed.source_key.model_dump()}
                ),
            ),
        )
    )
    reservation = (
        rig.registry.adapter("wms")
        .facts(rig.project_id, "reservation", 0, 200)
        .records[-1]
    )
    rig.execute(
        "wms",
        dict(
            operation="wms.release_reservation",
            work_order_id=str(refs.work_order),
            reservation=reservation.source_key.model_dump(),
            allocations=[
                a.model_dump(mode="json") for a in returned.payload.allocations
            ],
            cause=returned.source_key.model_dump(),
            evidence="Release returned unused allocation",
        ),
    )
    for kind in ("manufacturing", "quality"):
        rig.execute(
            "mes",
            dict(
                operation="mes.release",
                work_order_id=str(refs.work_order),
                units=refs.units,
                kind=kind,
                decision="approved",
                test_sources=[refs.test.source_key.model_dump()],
                evidence="Current test release",
            ),
        )
    shipment = rig.command(
        "shipment.request",
        order_line_id=str(refs.order_line),
        unit_ids=[u["unit_id"] for u in refs.units],
        quantity="1",
        unit="piece",
    )
    rig.command("exchange.dispatch", exchange_id=str(shipment.exchange_id))
    synchronize(rig)
    refs.shipment = (
        rig.registry.adapter("wms")
        .facts(rig.project_id, "shipment", 0, 200)
        .records[-1]
    )
    base = dict(
        shipment_id=str(refs.shipment.payload.shipment_id),
        shipment=refs.shipment.source_key.model_dump(),
        units=refs.units,
        amount=dict(quantity="1", unit="piece", scale=0),
        customer_id="C",
        external_signer="External receiving authority",
        reason="Delivery observation",
        signed_evidence="Original signed shipment",
        occurred_at=NOW.isoformat(),
    )
    rig.execute(
        "overseas",
        dict(operation="overseas.receive_shipment", decision="accepted", **base),
    )
    rig.execute(
        "customer",
        dict(operation="customer.confirm_delivery", decision="accepted", **base),
    )
    rig.execute(
        "customer",
        dict(
            operation="customer.map_serial",
            unit_id=refs.units[0]["unit_id"],
            shipment=refs.shipment.source_key.model_dump(),
            customer_id="C",
            customer_serial="CUSTOMER-SN1",
            external_signer="Customer receiver",
            evidence="Observed serial",
        ),
    )
    rig.execute("bi", dict(operation="bi.refresh"))
    synchronize(rig)
    return refs


def connected_scenario(rig, name):
    assert rig.network, "Connected scenarios require real producer composition"
    if not hasattr(rig, "_scenarios"):
        rig._scenarios = {}
    if name in rig._scenarios:
        return rig._scenarios[name]
    if name == "completion":
        refs = completion(rig)
    elif name == "shortage":
        refs = rig.core_ready()
        rig.pick_qualified(refs, quantity=8)
        synchronize(rig)
    elif name == "ecn_return":
        refs = connected_scenario(rig, "completion").core
        change = rig.change_ready(refs)
        rig.execute(
            "mes",
            dict(
                operation="mes.switch_revision",
                work_order_id=str(refs.work_order),
                eco_id=str(change.eco),
                from_revision_id=str(refs.revision),
                to_revision_id=str(change.revision),
                units=refs.units,
                change=change.change.model_dump(),
                approval=change.approval.model_dump(),
                evidence="Retain completed original and replace remaining obligation",
            ),
        )
        switch = (
            rig.registry.adapter("mes")
            .facts(rig.project_id, "revision_switch", 0, 200)
            .records[-1]
        )
        wid = switch.payload.replacement_work_order_id
        reqid = uuid4()
        plan = dict(
            operation="sap.publish_plan",
            input_revision_ids=[str(change.revision)],
            input_order_versions=[dict(order_line_id=str(refs.order_line), version=1)],
            requirements=[
                dict(
                    requirement_id=str(reqid),
                    work_order_id=str(wid),
                    execution_scope="common",
                    material_id="M",
                    owner_id="C",
                    amount=dict(quantity="11", unit="piece", scale=0),
                )
            ],
            cutoff=NOW.isoformat(),
        )
        from manufacturing_platform.workflow.contracts import DomainError

        try:
            rig.execute("sap", plan)
            raise AssertionError("Replacement plan bypassed required BOM request")
        except DomainError as exc:
            assert "BOM confirmation" in exc.message
        rig.execute("sap", dict(operation="sap.request_bom", work_order_id=str(wid)))
        rig.drain()
        rig.drain()
        rig.execute("sap", plan)
        replacement = replace(
            refs,
            work_order=wid,
            revision=change.revision,
            requirement=reqid,
            units=[],
            quantity=11,
        )
        replacement = rig.start_ready(replacement, sn="REPLACEMENT-SN")
        rig.execute("mes", replacement.start_payload)
        refs.replacement = replacement
        rig.execute(
            "crm",
            dict(
                operation="crm.open_return",
                shipment_id=str(refs.shipment.payload.shipment_id),
                shipment=refs.shipment.source_key.model_dump(),
                units=refs.units,
                amount=dict(quantity="1", unit="piece", scale=0),
                customer_id="C",
                external_signer="Customer quality",
                reason="Customer returned original unit",
                signed_evidence="Signed return claim",
                occurred_at=NOW.isoformat(),
            ),
        )
        synchronize(rig)
    else:
        raise ValueError("Unknown scenario")
    from manufacturing_platform.workflow.integrations.catalog import SYSTEM_IDS
    from manufacturing_platform.workflow.integrations.contracts import IntegrationFact

    keys = [
        IntegrationFact.model_validate_json(row["fact_json"]).source_key
        for system in SYSTEM_IDS
        for row in rig.rows(system, "facts")
        if row["project_id"] == str(rig.project_id)
    ]
    result = ScenarioRefs(name, refs, keys)
    rig._scenarios[name] = result
    return result


def multi_work_order_shipment(rig):
    from datetime import timedelta

    first = rig.measured_ready(
        rig.core_ready(quantity=12, received=12, accepted=12, work_order_quantity=6)
    )

    def release(refs):
        for kind in ("manufacturing", "quality"):
            rig.execute(
                "mes",
                dict(
                    operation="mes.release",
                    work_order_id=str(refs.work_order),
                    units=refs.units,
                    kind=kind,
                    decision="approved",
                    test_sources=[refs.test.source_key.model_dump()],
                    evidence="Current test release",
                ),
            )

    release(first)
    original = (
        rig.registry.adapter("sap")
        .facts(rig.project_id, "work_order", 0, 200)
        .records[0]
    )
    work = rig.result_fact(
        rig.execute(
            "sap",
            dict(
                operation="sap.release_work_order",
                order_line_id=str(first.order_line),
                revision_id=str(first.revision),
                released_revision=original.payload.released_revision.model_dump(),
                amount=dict(quantity="6", unit="piece", scale=0),
                trial_amount=dict(quantity="1", unit="piece", scale=0),
                purpose="production",
                planned_start=NOW.isoformat(),
                planned_end=(NOW + timedelta(days=1)).isoformat(),
            ),
        )
    )
    wid = rig.target(work, "work_order")
    rig.command(
        "order.allocate",
        order_line_id=str(first.order_line),
        work_order_id=str(wid),
        quantity="6",
        unit="piece",
    )
    rig.drain()
    rig.drain()
    req = uuid4()
    rig.execute(
        "sap",
        dict(
            operation="sap.publish_plan",
            input_revision_ids=[str(first.revision)],
            input_order_versions=[dict(order_line_id=str(first.order_line), version=1)],
            requirements=[
                dict(
                    requirement_id=str(req),
                    work_order_id=str(wid),
                    execution_scope="common",
                    material_id="M",
                    owner_id="C",
                    amount=dict(quantity="6", unit="piece", scale=0),
                )
            ],
            cutoff=NOW.isoformat(),
        ),
    )
    second = rig.measured_ready(
        replace(first, work_order=wid, requirement=req, units=[]), sn="SN2"
    )
    release(second)
    members = first.units + second.units
    request = rig.command(
        "shipment.request",
        order_line_id=str(first.order_line),
        unit_ids=[u["unit_id"] for u in members],
        quantity="2",
        unit="piece",
    )
    rig.command("exchange.dispatch", exchange_id=str(request.exchange_id))
    synchronize(rig)
    first.shipment = (
        rig.registry.adapter("wms")
        .facts(rig.project_id, "shipment", 0, 200)
        .records[-1]
    )
    first.units = members
    return first
