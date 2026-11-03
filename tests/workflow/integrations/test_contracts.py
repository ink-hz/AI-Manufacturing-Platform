from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from manufacturing_platform.workflow.integrations.catalog import (
    EDGES,
    OPERATIONS,
    SYSTEM_IDS,
)
from manufacturing_platform.workflow.integrations.contracts import (
    SourceKey,
    SystemOperation,
    SystemReceipt,
)
from manufacturing_platform.workflow.integrations.core_models import (
    Amount,
    MesInspect,
    UnitScope,
)
from manufacturing_platform.workflow.integrations.routing import route

EXPECTED = {
    "sap": "release_order release_work_order publish_plan post_movement post_completion",
    "wms": "receive putaway reserve pick return stocktake ship",
    "mes": "inspect start interrupt resume switch_revision pass assemble contain release complete",
    "pdm": "publish_revision issue_change",
    "crm": "publish_demand open_return",
    "oa": "request_approval decide_approval",
    "hr_sap": "publish_employee",
    "hr_beisen": "publish_qualification",
    "hr_dingtalk": "assign_shift",
    "product_test": "run calibrate",
    "plc": "set_state sample readback",
    "customer": "approve_revision receive_shipment confirm_delivery map_serial",
    "overseas": "receive_shipment report_return",
    "srm": "promise announce_arrival",
    "bi": "refresh",
}


def test_profiles_do_not_reinterpret_legacy_execution():
    assert len(SYSTEM_IDS) == len(set(SYSTEM_IDS)) == 15
    assert "erp" not in SYSTEM_IDS
    assert route("legacy-erp-v1", "production.start") == "erp"
    assert route("oem-network-v1", "production.start") == "mes"
    assert route("oem-network-v1", "reservation.request") == "wms"
    assert route("oem-network-v1", "shipment.request") == "wms"
    with pytest.raises(ValueError):
        route("oem-network-v1", "invented.action")


@pytest.mark.parametrize(
    "system,name", [(s, n) for s, names in EXPECTED.items() for n in names.split()]
)
def test_all_operations_have_closed_typed_contract_and_policy(system, name):
    tag = f"{system}.{name}"
    spec = OPERATIONS[tag]
    assert spec.system == system
    assert spec.input_model.model_fields["operation"].default == tag
    assert spec.input_model.model_config["extra"] == "forbid"
    assert spec.underlying_action
    assert spec.output_fact_types


from .payloads import order_payload


def operation(**overrides):
    return dict(
        operation_id=str(uuid4()),
        project_id=str(uuid4()),
        system="sap",
        payload=order_payload(),
        **overrides,
    )


def test_wrong_system_unknown_discriminator_and_extra_are_rejected():
    valid = operation()
    SystemOperation.model_validate(valid)
    for change in (
        {"system": "erp"},
        {"system": "wms"},
        {"payload": {**order_payload(), "operation": "sap.unknown"}},
        {"payload": {**order_payload(), "untrusted": "yes"}},
    ):
        with pytest.raises(ValidationError):
            SystemOperation.model_validate(valid | change)


@pytest.mark.parametrize(
    "quantity,scale",
    [("1.01", 1), ("NaN", 0), ("1e2", 0), ("-0", 0), ("9223372036854775808", 0)],
)
def test_precision_and_canonical_decimal(quantity, scale):
    with pytest.raises(ValidationError):
        Amount(quantity=quantity, unit="piece", scale=scale)


def test_source_identity_and_naive_datetime():
    for key in (
        {"system": "erp"},
        {"object_type": " "},
        {"external_id": "../bad"},
        {"version": True},
    ):
        with pytest.raises(ValidationError):
            SourceKey.model_validate(
                dict(
                    system="wms",
                    object_type="receipt",
                    external_id="receipt-1",
                    version=1,
                )
                | key
            )
    with pytest.raises(ValidationError):
        SystemReceipt(
            operation_id=uuid4(),
            system="sap",
            request_hash="a" * 64,
            phase="accepted",
            source_keys=[],
            sequence=1,
            occurred_at=datetime.now(),
            received_at=datetime.now(UTC),
        )


def test_duplicate_units_and_serials():
    unit_id = uuid4()
    for rows in (
        [{"unit_id": unit_id, "sn": "A"}, {"unit_id": unit_id, "sn": "B"}],
        [{"unit_id": uuid4(), "sn": "Ａ"}, {"unit_id": uuid4(), "sn": "a"}],
    ):
        with pytest.raises(ValidationError):
            UnitScope(units=rows)


def test_iqc_mixed_units_and_non_wms_receipt():
    payload = dict(
        receipt={
            "system": "wms",
            "object_type": "receipt",
            "external_id": "r1",
            "version": 1,
        },
        accepted={"quantity": "2", "unit": "piece", "scale": 0},
        rejected={"quantity": "1", "unit": "kg", "scale": 0},
        evidence="inspection",
    )
    with pytest.raises(ValidationError):
        MesInspect.model_validate(payload)
    payload["rejected"]["unit"] = "piece"
    MesInspect.model_validate(payload)
    payload["receipt"]["system"] = "sap"
    with pytest.raises(ValidationError):
        MesInspect.model_validate(payload)


def sample_from_schema(schema, definitions, name=""):
    """Build a minimal wire example, then add operation-specific relationships."""
    if "$ref" in schema:
        return sample_from_schema(
            definitions[schema["$ref"].rsplit("/", 1)[1]], definitions, name
        )
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    if "anyOf" in schema or "oneOf" in schema:
        options = schema.get("anyOf", schema.get("oneOf"))
        chosen = next((s for s in options if s.get("type") == "string"), options[0])
        return sample_from_schema(chosen, definitions, name)
    kind = schema.get("type")
    if kind == "object":
        return {
            k: sample_from_schema(v, definitions, k)
            for k, v in schema.get("properties", {}).items()
            if k in schema.get("required", []) or "const" in v
        }
    if kind == "array":
        return [
            sample_from_schema(schema["items"], definitions, name)
            for _ in range(schema.get("minItems", 0))
        ]
    if kind == "integer":
        return max(schema.get("minimum", 0), 1)
    if kind == "number":
        return 1
    if kind == "boolean":
        return True
    if schema.get("format") == "uuid":
        return str(uuid4())
    if schema.get("format") == "date-time":
        return (
            "2027-01-02T00:00:00Z"
            if name in {"planned_end", "valid_until", "ends_at"}
            else "2027-01-01T00:00:00Z"
        )
    if schema.get("format") == "date":
        return "2027-01-01"
    if name in {"quantity", "value", "lower", "upper"}:
        return "1"
    if "checksum" in name:
        return "a" * 64
    return "value"


def valid_payload(tag):
    model = OPERATIONS[tag].input_model
    schema = model.model_json_schema()
    data = sample_from_schema(schema, schema.get("$defs", {}))
    data["operation"] = tag
    for field, system, kind in [
        ("released_revision", "pdm", "revision"),
        ("receipt", "wms", "receipt"),
        ("shipment", "wms", "shipment"),
        ("employee", "hr_sap", "employee"),
        ("calibration", "product_test", "calibration"),
        ("completion", "mes", "completion"),
    ]:
        if field in data:
            data[field].update(system=system, object_type=kind)
    if tag == "wms.release_reservation":
        data["reservation"].update(system="wms", object_type="reservation")
        for allocation in data["allocations"]:
            allocation["reservation"] = data["reservation"]
            allocation["qualification"].update(
                system="wms", object_type="qualification"
            )
    if tag == "wms.ship":
        for release in data["releases"]:
            release.update(system="mes", object_type="release")
    if tag == "sap.post_movement":
        data["cause"].update(system="wms", object_type="pick")
    if tag == "mes.contain":
        data["unit_ids"] = [str(uuid4())]
    return data


@pytest.mark.parametrize("tag", sorted(OPERATIONS))
def test_every_operation_and_primary_fact_roundtrip_and_rejects_wrong_pair(tag):
    from manufacturing_platform.workflow.integrations.contracts import IntegrationFact

    payload = valid_payload(tag)
    spec = OPERATIONS[tag]
    data = dict(
        operation_id=uuid4(), project_id=uuid4(), system=spec.system, payload=payload
    )
    if "artifact_ref" in payload:
        payload["artifact_ref"]["project_id"] = str(data["project_id"])
    value = SystemOperation.model_validate(data)
    assert SystemOperation.model_validate_json(value.model_dump_json()) == value
    with pytest.raises(ValidationError):
        SystemOperation.model_validate(
            data | {"system": "bi" if spec.system != "bi" else "sap"}
        )
    with pytest.raises(ValidationError):
        SystemOperation.model_validate(
            data | {"payload": payload | {"extra": "forbidden"}}
        )
    fact_payload = value.payload.model_dump(mode="json")
    fact_payload.pop("operation")
    fact_type = spec.output_fact_types[0]
    if tag == "wms.release_reservation":
        for allocation in fact_payload["allocations"]:
            allocation["reservation_id"] = str(uuid4())
            allocation["receipt"] = dict(
                system="wms",
                object_type="receipt",
                external_id="actual-receipt",
                version=1,
            )
    if tag in {"mes.cancel_remaining", "mes.switch_revision"}:
        fact_payload["remaining_amount"] = dict(quantity="1", unit="piece", scale=0)
    if tag == "mes.switch_revision":
        fact_payload["replacement_work_order_id"] = str(uuid4())
    if tag == "plc.readback":
        fact_payload.update(parameter_digest="a" * 64, confirmation_matches=True)
    if tag in {"bi.refresh", "product_test.prepare_artifact", "sap.request_bom"}:
        from manufacturing_platform.workflow.integrations.evidence_models import (
            BiRefreshFact,
            ProductTestArtifactFact,
        )
        from manufacturing_platform.workflow.integrations.core_models import (
            SapBomRequest,
        )

        model = {
            "bi.refresh": BiRefreshFact,
            "product_test.prepare_artifact": ProductTestArtifactFact,
            "sap.request_bom": SapBomRequest,
        }[tag]
        schema = model.model_json_schema()
        fact_payload = sample_from_schema(schema, schema.get("$defs", {}))
        if tag == "product_test.prepare_artifact":
            fact_payload["prepared"]["artifact_ref"]["project_id"] = str(
                data["project_id"]
            )
        if tag == "bi.refresh":
            fact_payload["metrics"][0]["sources"][0].update(
                system="sap", object_type="order"
            )
    fact = IntegrationFact(
        project_id=data["project_id"],
        source=dict(
            system=spec.system,
            object_type=fact_type.split(".")[1],
            external_id="fact-1",
            version=1,
            mode="mock",
            occurred_at="2027-01-01T00:00:00Z",
            collected_at="2027-01-01T00:00:00Z",
            evidence="source",
        ),
        payload=fact_payload | {"fact_type": fact_type},
        external_actor="external-operator",
        evidence="source",
    )
    assert IntegrationFact.model_validate_json(fact.model_dump_json()) == fact


def test_oa_policy_depends_on_closed_target_and_does_not_grant_qualifications():
    for tag in ("oa.request_approval", "oa.decide_approval"):
        spec = OPERATIONS[tag]
        payload = valid_payload(tag)
        assert spec.policy_for(spec.input_model.model_validate(payload)) == "npi.review"
        payload["target"] = dict(
            target_type="quality",
            source_key=payload["target"]["source_key"],
            nonconformance_id=uuid4(),
            work_order_id=uuid4(),
            disposition="scrap",
        )
        assert (
            spec.policy_for(spec.input_model.model_validate(payload))
            == "nonconformance.disposition"
        )
        payload["target"]["target_type"] = "arbitrary"
        with pytest.raises(ValidationError):
            spec.input_model.model_validate(payload)


def test_omitted_posted_time_is_explicitly_unknown():
    receipt = SystemReceipt(
        operation_id=uuid4(),
        system="sap",
        request_hash="a" * 64,
        phase="accepted",
        source_keys=[],
        sequence=1,
        occurred_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
    )
    assert receipt.posted_at is None
    assert receipt.model_dump(mode="json")["posted_at"] is None


def test_catalog_edges_only_reference_closed_facts_and_all_systems_participate():
    from manufacturing_platform.workflow.integrations.contracts import FACT_ADAPTER

    schema = FACT_ADAPTER.json_schema()
    tags = set(schema["discriminator"]["mapping"])
    assert {s for e in EDGES for s in (e.producer, e.consumer)} == set(SYSTEM_IDS)
    assert {t for e in EDGES for t in e.fact_types} <= tags
    assert {t for spec in OPERATIONS.values() for t in spec.output_fact_types} <= tags


def test_mock_test_raw_evidence_cannot_be_relabelled_manual():
    payload = valid_payload("product_test.run")
    payload["raw"]["origin"] = "manual"
    with pytest.raises(ValidationError):
        OPERATIONS["product_test.run"].input_model.model_validate(payload)


def test_oa_targets_require_concrete_review_or_disposition_details():
    from manufacturing_platform.workflow.integrations.enterprise_models import (
        EngineeringTarget,
        QualityTarget,
    )

    source = dict(
        system="mes", object_type="approval_request", external_id="a1", version=1
    )
    with pytest.raises(ValidationError):
        EngineeringTarget(source_key=source, npi_id=uuid4(), revision_id=uuid4())
    with pytest.raises(ValidationError):
        QualityTarget(
            source_key=source, nonconformance_id=uuid4(), work_order_id=uuid4()
        )
    with pytest.raises(ValidationError):
        QualityTarget(
            source_key=source,
            nonconformance_id=uuid4(),
            work_order_id=uuid4(),
            disposition="rework",
        )


def test_mes_cannot_claim_customer_release_authority():
    data = valid_payload("mes.release") | {"kind": "customer"}
    with pytest.raises(ValidationError):
        OPERATIONS["mes.release"].input_model.model_validate(data)


@pytest.mark.parametrize("tag", ["product_test.run", "product_test.calibrate"])
def test_raw_artifact_reference_is_required_and_closed(tag):
    payload = valid_payload(tag)
    payload.pop("artifact_ref", None)
    with pytest.raises(ValidationError):
        OPERATIONS[tag].input_model.model_validate(payload)


@pytest.mark.parametrize(
    "change",
    [
        {"system": "plc"},
        {"project_id": "not-a-project"},
        {"artifact_id": "bad-id"},
        {"version": 0},
        {"version": True},
        {"reference": "../outside"},
        {"reference": "https://example.com/raw"},
        {"reference": " "},
        {"reference": "a" * 201},
        {"unexpected": "data"},
    ],
)
def test_raw_artifact_reference_rejects_malformed_identity(change):
    payload = valid_payload("product_test.run")
    payload["artifact_ref"] = (
        dict(
            system="product_test",
            project_id=str(uuid4()),
            artifact_id=str(uuid4()),
            version=1,
            reference="raw-result-1.json",
        )
        | change
    )
    with pytest.raises(ValidationError):
        OPERATIONS["product_test.run"].input_model.model_validate(payload)


@pytest.mark.parametrize("tag", ["product_test.run", "product_test.calibrate"])
@pytest.mark.parametrize("envelope", ["operation", "fact"])
def test_raw_artifact_project_matches_its_envelope(tag, envelope):
    from manufacturing_platform.workflow.integrations.contracts import IntegrationFact

    payload = valid_payload(tag)
    project_id = uuid4()
    payload["artifact_ref"]["project_id"] = str(project_id)
    if envelope == "operation":
        data = dict(
            operation_id=uuid4(),
            project_id=project_id,
            system="product_test",
            payload=payload,
        )
        model = SystemOperation
    else:
        payload.pop("operation")
        payload["fact_type"] = OPERATIONS[tag].output_fact_types[0]
        data = dict(
            project_id=project_id,
            source=dict(
                system="product_test",
                object_type=payload["fact_type"].split(".")[1],
                external_id="fact-1",
                version=1,
                mode="mock",
                occurred_at="2027-01-01T00:00:00Z",
                collected_at="2027-01-01T00:00:00Z",
                evidence="source",
            ),
            payload=payload,
            external_actor="instrument",
            evidence="source",
        )
        model = IntegrationFact
    model.model_validate(data)
    payload["artifact_ref"]["project_id"] = str(uuid4())
    with pytest.raises(ValidationError, match="cross-project artifact"):
        model.model_validate(data)
