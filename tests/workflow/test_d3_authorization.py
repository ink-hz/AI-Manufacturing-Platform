"""Actual-host E29 must prove denied writes leave every business table intact."""

import json
from pathlib import Path

from .d3.case_authorization import run
from .scenarios.base import ScenarioContext


def test_actual_host_e29_records_scope_write_matrix(tmp_path):
    context = ScenarioContext.isolated(tmp_path, case_id="E29", seed=75)
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
