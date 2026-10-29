"""Actual-host E29 must prove denied writes leave every business table intact."""

import json
from pathlib import Path

import pytest

from .d3.case_authorization import run
from .scenarios.base import ScenarioContext
from .scenarios.fixtures import BusinessHTTP


@pytest.mark.parametrize("preexisting_count", [0, 2], ids=["standalone", "preexisting-projects"])
def test_actual_host_e29_records_scope_write_matrix(tmp_path, preexisting_count):
    context = ScenarioContext.isolated(tmp_path, case_id="E29", seed=75)
    preexisting_ids = set()
    if preexisting_count:
        # The complete E29 wrapper creates local HTTP facts before the real-PF
        # proof starts against this same owned dataset.
        fixture = BusinessHTTP(context)
        try:
            preexisting_ids = {
                fixture.project(product=f"Preexisting {number}")
                for number in range(preexisting_count)
            }
        finally:
            fixture.close()
    try:
        run(context)
    finally:
        if context.client:
            context.client.close()
    artifacts = list(context.directory.glob("*-scope-write-matrix.json"))
    assert len(artifacts) == 1, "E29 lacks the required actual-host negative write matrix"
    matrix = json.loads(artifacts[0].read_text())["value"]
    own, same, other = (matrix["projects"][key] for key in ("own", "same_customer", "other_customer"))
    assert len({own["id"], same["id"], other["id"]}) == 3
    assert own["customer_id"] == same["customer_id"] != other["customer_id"]
    positive = json.loads(Path(matrix["positive_response"]).read_text())["value"]
    assert positive["status"] == 200 and positive["body"]["object_type"] == "demand"
    positive_request = json.loads(Path(positive["request_artifact"]).read_text())["value"]
    expected = {"anonymous": 401, "outsider": 404, "other_same_customer": 404, "other_customer": 404}
    assert {row["case"]: row["status"] for row in matrix["denied"]} == expected
    operations = {positive_request["body"]["operation_id"]}
    sources = {positive_request["body"]["source"]["external_id"]}
    for row in matrix["denied"]:
        request = json.loads(Path(row["request"]).read_text())["value"]
        response = json.loads(Path(row["response"]).read_text())["value"]
        assert request["method"] == "POST" and request["body"]["action"] == "demand.record"
        assert response["status"] == expected[row["case"]]
        assert response["request_artifact"] == row["request"]
        assert request["body"]["expected_version"] == row["project_versions"][row["project_id"]]
        operations.add(request["body"]["operation_id"])
        sources.add(request["body"]["source"]["external_id"])
        for field in ("action", "kind", "product", "quantity", "unit", "due_date"):
            assert request["body"][field] == positive_request["body"][field]
        if row["case"] in {"other_same_customer", "other_customer"}:
            assert request["actor"] == positive_request["actor"]
        if row["case"] == "anonymous":
            assert request["actor"] is None
        assert row["before"] == row["after"]
        assert {"operations", "audit_events", "projects", "demands"} <= set(row["before"]["workflow.db"])
    assert len(operations) == len(sources) == 5

    admin_artifacts = list(context.directory.glob("*-admin-full-access.json"))
    assert len(admin_artifacts) == 1
    admin = json.loads(admin_artifacts[0].read_text())["value"]
    assert admin["initial_grants"] == {"active": 0, "total": 0}
    assert admin["final_grant_count"] == 0
    expected_initial_ids = preexisting_ids | {admin["existing_project_id"]}
    assert len(admin["initial_project_ids"]) == len(expected_initial_ids)
    assert set(admin["initial_project_ids"]) == expected_initial_ids
    assert len(admin["initial_access"]["project_ids"]) == len(expected_initial_ids)
    assert set(admin["initial_access"]["project_ids"]) == expected_initial_ids
    assert set(admin["initial_reads"]) == expected_initial_ids
    for project_id, read in admin["initial_reads"].items():
        assert read["id"] == project_id
        assert {"demand.record", "readiness.record", "release.decide"} <= set(read["allowed_actions"])
        assert read["release_kinds"] == ["manufacturing", "quality", "customer"]
    assert len(admin["later_project_ids"]) == 2
    assert len(set(admin["later_project_ids"])) == 2
    assert set(admin["later_project_ids"]).isdisjoint(expected_initial_ids)
    expected_later_ids = expected_initial_ids | set(admin["later_project_ids"])
    assert len(admin["later_access"]["project_ids"]) == len(expected_later_ids)
    assert set(admin["later_access"]["project_ids"]) == expected_later_ids
    assert admin["audit"]["actor_id"] == admin["actor_id"]
    assert admin["audit"]["object_id"] == admin["result"]["object_id"]
    assert admin["audit"]["action"] == "demand.record"
    response = json.loads(Path(admin["valid_command_response"]).read_text())["value"]
    assert response["status"] == 200
    assert response["body"]["object_id"] == admin["audit"]["object_id"]
    assert set(admin["reads"]) == {"own", "same_customer", "other_customer"}
