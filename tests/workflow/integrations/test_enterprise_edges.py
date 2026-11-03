"""Actual enterprise operations, typed evidence and domain consequences."""

from datetime import timedelta
from uuid import uuid4

import pytest

from manufacturing_platform.workflow.service import WorkflowService
from .support import MockRig, NOW


class EnterpriseRig(MockRig):
    def __init__(self, root):
        super().__init__(root, core=True, network=True)

    def reopen(self):
        super().reopen()
        self.workflow = WorkflowService(self.workflow.store, lambda uid: True)
        self.registry = self.workflow.system_registry
        return self


@pytest.fixture
def rig(tmp_path):
    value = EnterpriseRig(tmp_path)
    value.grant(
        [
            "project_owner",
            "engineering",
            "planner",
            "quality",
            "production",
            "supply",
            "warehouse",
        ],
        ["inspection", "disposition", "quality_release", "readiness_verification"],
    )
    return value


def revision_payload(revision="A"):
    return dict(
        operation="pdm.publish_revision",
        bom_materials=[
            dict(material_id="M", per_unit=dict(quantity="1", unit="piece", scale=0))
        ],
        package_id="PKG",
        revision=revision,
        customer_revision=revision,
        internal_revision=revision,
        firmware_version="F1",
        items=[
            dict(
                id="drawing",
                kind="drawing",
                title="Drawing",
                revision=revision,
                status="verified",
                evidence="Released drawing",
            )
        ],
        route_steps=[dict(station="assembly", instruction_version="S1")],
        test_spec=dict(
            version="T1",
            program_version="P1",
            measurements=[dict(name="voltage", unit="V", lower="4", upper="6")],
        ),
        released_at=NOW.isoformat(),
    )


def test_real_pdm_revision_has_structured_bom_and_domain_link(rig):
    assert rig.registry.available("pdm"), "PDM producer is not configured"
    fact = rig.result_fact(rig.execute("pdm", revision_payload()))
    rid = rig.target(fact, "revision")
    with rig.workflow.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT revision FROM engineering_revisions WHERE id=?", (str(rid),)
            ).fetchone()[0]
            == "A"
        )
    assert fact.payload.bom_materials[0].material_id == "M"
    assert len(rig.rows("pdm", "operations")) == 1
    detail = rig.workflow.integration_fact(rig.actor, rig.project_id, fact.source_key)
    assert detail.workflow_projected


def test_real_hr_records_do_not_grant_application_permissions(rig):
    assert rig.registry.available("hr_sap"), "HR producer is not configured"
    with rig.workflow.store.transaction() as tx:
        before = [tuple(r) for r in tx.execute("SELECT * FROM project_grants")]
    employee = rig.result_fact(
        rig.execute(
            "hr_sap",
            dict(
                operation="hr_sap.publish_employee",
                employee_id="E1",
                display_name="Fictional operator",
                organization="Factory",
                position="assembly",
                active=True,
            ),
        )
    )
    qualification = rig.result_fact(
        rig.execute(
            "hr_beisen",
            dict(
                operation="hr_beisen.publish_qualification",
                employee=employee.source_key.model_dump(),
                qualification="assembly",
                training_reference="TR1",
                valid_from=(NOW - timedelta(days=1)).isoformat(),
                valid_until=(NOW + timedelta(days=1)).isoformat(),
                evidence="Training completed",
            ),
        )
    )
    with rig.workflow.store.transaction() as tx:
        assert before == [tuple(r) for r in tx.execute("SELECT * FROM project_grants")]
    for fact, kind in [(employee, "employee"), (qualification, "qualification")]:
        detail = rig.workflow.integration_fact(
            rig.actor, rig.project_id, fact.source_key
        )
        assert detail.projection.auxiliary[0].kind == kind
        assert detail.auxiliary_records[0].source_key == fact.source_key
        assert (
            detail.auxiliary_records[0].payload_hash == detail.projection.payload_hash
        )


def test_crm_demand_is_real_reviewable_demand(rig):
    assert rig.registry.available("crm"), "CRM producer is not configured"
    fact = rig.result_fact(
        rig.execute(
            "crm",
            dict(
                operation="crm.publish_demand",
                customer_id="C",
                demand_kind="firm",
                product="P",
                amount=dict(quantity="2", unit="piece", scale=0),
                due_date=(NOW + timedelta(days=7)).date().isoformat(),
            ),
        )
    )
    ident = rig.target(fact, "demand")
    with rig.workflow.store.transaction() as tx:
        row = tx.execute("SELECT * FROM demands WHERE id=?", (str(ident),)).fetchone()
        assert (row["source_system"], row["source_type"], row["q_atoms"]) == (
            "crm",
            "demand",
            2,
        )
    rig.command(
        "demand.review",
        demand_id=str(ident),
        dimension="technical",
        decision="approved",
        evidence="Reviewed source demand",
    )


def test_oa_decision_is_bound_to_actual_revision_request_and_review(rig):
    revision = rig.result_fact(rig.execute("pdm", revision_payload()))
    rid = rig.target(revision, "revision")
    npi = rig.command(
        "npi.open",
        revision_id=str(rid),
        product_family="P",
        scenario="first_introduction",
        required_checks=["drawing"],
        work_order_ids=[],
    ).object_id
    target = dict(
        target_type="engineering",
        source_key=revision.source_key.model_dump(),
        npi_id=str(npi),
        revision_id=str(rid),
        checks=[
            dict(
                code="drawing",
                required=True,
                decision="pass",
                evidence="Checked",
                reason="Verified",
            )
        ],
    )
    request = rig.result_fact(
        rig.execute(
            "oa",
            dict(
                operation="oa.request_approval",
                target=target,
                requested_by="Engineering",
                evidence="Request",
            ),
        )
    )
    decision = rig.result_fact(
        rig.execute(
            "oa",
            dict(
                operation="oa.decide_approval",
                target=target,
                request=request.source_key.model_dump(),
                decision="approved",
                external_signer="OA reviewer",
                signed_at=NOW.isoformat(),
                evidence="Signed review",
            ),
        )
    )
    assert rig.target(decision, "npi") == npi
    with rig.workflow.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT count(*) FROM npi_records WHERE npi_id=? AND record_type='review'",
                (str(npi),),
            ).fetchone()[0]
            == 1
        )
        assert (
            tx.execute(
                "SELECT count(*) FROM npi_records WHERE npi_id=? AND record_type='approval'",
                (str(npi),),
            ).fetchone()[0]
            == 0
        )
    assert (
        rig.workflow.integration_fact(rig.actor, rig.project_id, request.source_key)
        .auxiliary_records[0]
        .kind
        == "approval_request"
    )


def test_srm_promise_and_asn_are_expected_supply_not_physical_receipt(rig):
    refs = rig.core_ready()
    purchase = (
        rig.registry.adapter("sap")
        .facts(rig.project_id, "purchase_requirement", 0, 200)
        .records[0]
    )
    commitment = uuid4()
    promise = rig.result_fact(
        rig.execute(
            "srm",
            dict(
                operation="srm.promise",
                requirement_id=str(refs.requirement),
                purchase_requirement=purchase.source_key.model_dump(),
                commitment_id=str(commitment),
                supplier_id="Supplier",
                owner_id="C",
                supply_type="customer",
                amount=dict(quantity="2", unit="piece", scale=0),
                original_due=(NOW + timedelta(days=7)).date().isoformat(),
                current_due=(NOW + timedelta(days=7)).date().isoformat(),
                evidence="Promised",
            ),
        )
    )
    assert rig.target(promise, "commitment") == commitment
    before = rig.physical_balance(refs.lot)
    arrival = rig.result_fact(
        rig.execute(
            "srm",
            dict(
                operation="srm.announce_arrival",
                commitment_id=str(commitment),
                promise=promise.source_key.model_dump(),
                material_id="M",
                supplier_batch="B2",
                supplier_id="Supplier",
                amount=dict(quantity="2", unit="piece", scale=0),
                expected_at=(NOW + timedelta(days=1)).isoformat(),
                coa_reference="COA-2",
                coa_evidence="Certificate",
            ),
        )
    )
    assert rig.physical_balance(refs.lot) == before
    detail = rig.workflow.integration_fact(
        rig.actor, rig.project_id, arrival.source_key
    )
    assert detail.auxiliary_records[0].kind == "supplier_notice"
    assert detail.auxiliary_records[0].expected_at > NOW


def test_bom_confirmation_has_real_plan_gate_without_duplicate_revision(rig):
    refs = rig.core_ready()
    rig.drain()
    confirmations = (
        rig.registry.adapter("pdm")
        .facts(rig.project_id, "bom_confirmation", 0, 200)
        .records
    )
    assert confirmations, "Actual BOM confirmation producer is missing"
    confirmation = confirmations[-1]
    assert confirmation.payload.work_order_id == refs.work_order
    assert confirmation.payload.bom_materials[0].material_id == "M"
    with rig.workflow.store.transaction() as tx:
        assert (
            tx.execute(
                "SELECT count(*) FROM engineering_revisions WHERE project_id=?",
                (str(rig.project_id),),
            ).fetchone()[0]
            == 1
        )
    plan = rig.registry.adapter("sap").facts(rig.project_id, "plan", 0, 200).records[-1]
    assert confirmation.source_key in plan.caused_by
    bad = plan.payload.model_dump(mode="json", exclude={"fact_type"})
    bad["requirements"][0]["requirement_id"] = str(uuid4())
    bad["requirements"][0]["material_id"] = "DOCUMENT-NOT-MATERIAL"
    before = len(rig.rows("sap", "facts"))
    from manufacturing_platform.workflow.contracts import DomainError

    with pytest.raises(DomainError):
        rig.execute("sap", dict(operation="sap.publish_plan", **bad))
    assert len(rig.rows("sap", "facts")) == before


def test_replacement_work_order_gets_own_bom_sync_plan_and_start(rig):
    original = rig.connected_scenario("completion").core
    with rig.workflow.store.transaction() as tx:
        retained = dict(
            tx.execute(
                "SELECT * FROM units WHERE id=?", (original.units[0]["unit_id"],)
            ).fetchone()
        )
    rig.connected_scenario("ecn_return")
    switch = (
        rig.registry.adapter("mes")
        .facts(rig.project_id, "revision_switch", 0, 200)
        .records[-1]
    )
    wid = switch.payload.replacement_work_order_id
    requests = (
        rig.registry.adapter("sap").facts(rig.project_id, "bom_request", 0, 200).records
    )
    assert any(f.payload.work_order_id == wid for f in requests), (
        "Replacement BOM synchronization request missing"
    )
    plans = rig.registry.adapter("sap").facts(rig.project_id, "plan", 0, 200).records
    assert any(
        any(r.work_order_id == wid for r in f.payload.requirements) for f in plans
    )
    assert any(
        f.payload.work_order_id == wid
        for f in rig.registry.adapter("mes")
        .facts(rig.project_id, "start", 0, 200)
        .records
    )
    with rig.workflow.store.transaction() as tx:
        assert (
            dict(
                tx.execute(
                    "SELECT * FROM units WHERE id=?", (original.units[0]["unit_id"],)
                ).fetchone()
            )
            == retained
        )


def test_real_hr_updates_cannot_bypass_application_grant_or_current_training(rig):
    from manufacturing_platform.workflow.contracts import DomainError

    refs = rig.start_ready()
    rig.grant(["warehouse"])
    before = len(rig.rows("mes", "operations"))
    with pytest.raises(DomainError):
        rig.execute("mes", refs.start_payload)
    assert len(rig.rows("mes", "operations")) == before
    rig.grant(["project_owner", "production"])
    rig.execute(
        "hr_beisen",
        dict(
            operation="hr_beisen.publish_qualification",
            employee=refs.start_payload["operator"],
            qualification="assembly",
            training_reference="expired-current",
            valid_from=(NOW - timedelta(days=2)).isoformat(),
            valid_until=(NOW - timedelta(days=1)).isoformat(),
            evidence="Expired current training",
        ),
    )
    with pytest.raises(DomainError, match="training"):
        rig.execute("mes", refs.start_payload)
    assert (
        not rig.registry.adapter("mes").facts(rig.project_id, "start", 0, 200).records
    )


def test_wms_receipt_retains_actual_supplier_notice_lineage(rig):
    refs = rig.core_ready()
    receipt = rig.registry.observe_fact(rig.project_id, refs.receipt)
    assert any(
        k.system == "srm" and k.object_type == "arrival" for k in receipt.caused_by
    ), "Actual receipt lost supplier ASN provenance"
