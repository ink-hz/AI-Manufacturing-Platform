"""Fifteen real sources, all directed durable deliveries, actual projections."""

import pytest

from manufacturing_platform.workflow.integrations.catalog import EDGES, SYSTEM_IDS


@pytest.fixture
def rig(network_rig):
    return network_rig


def test_every_system_has_an_operation_and_every_edge_has_evidence(rig):
    assert hasattr(rig, "connected_scenario"), "Real connected scenario builder missing"
    rig.connected_scenario("completion")
    rig.connected_scenario("ecn_return")
    assert len(EDGES) == 32
    for system in SYSTEM_IDS:
        assert rig.completed_operations(system) > 0, system
        assert rig.visible_fact_count(system) > 0, system
    for edge in EDGES:
        evidence = rig.edge_evidence(edge.id)
        assert evidence.producer_key, edge.id
        assert evidence.consumer_receipt.phase == "accepted", edge.id
        assert evidence.projection_refs, edge.id
    assert set(SYSTEM_IDS) <= {s.system for s in rig.all_visible_systems()}


@pytest.fixture(scope="module")
def completed_network(tmp_path_factory):
    from .test_enterprise_edges import EnterpriseRig

    value = EnterpriseRig(tmp_path_factory.mktemp("all-real-systems"))
    value.connected_scenario("completion")
    value.connected_scenario("ecn_return")
    return value


@pytest.mark.parametrize("system", SYSTEM_IDS)
def test_each_real_system_has_receipt_source_and_linked_read_model(
    completed_network, system
):
    rig = completed_network
    from manufacturing_platform.workflow.integrations.contracts import SystemReceipt

    receipt = next(
        SystemReceipt.model_validate_json(row["receipt_json"])
        for row in rig.rows(system, "operations")
        if SystemReceipt.model_validate_json(row["receipt_json"]).phase == "accepted"
    )
    assert receipt.source_keys
    details = [
        rig.workflow.integration_fact(rig.actor, rig.project_id, key)
        for key in receipt.source_keys
    ]
    assert all(
        d.source_accepted
        and d.workflow_projected
        and d.projection.targets + d.projection.auxiliary
        for d in details
    )
