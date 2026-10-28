"""Sensitivity checks against genuine HTTP-created facts, never synthetic success."""

from copy import deepcopy
import json
import pytest

from .scenarios.base import ScenarioContext, run_case
from .scenarios import business as b


def test_empty_assertion_keeps_first_error_and_structured_location(tmp_path):
    context = ScenarioContext.isolated(tmp_path, case_id="E21", seed=91)

    class BrokenClose:
        def close(self):
            raise RuntimeError("teardown error")

    context.client = BrokenClose()

    def failing_assertion(ctx):
        secret = "never-export-this-local"
        assert secret
        raise AssertionError()

    result = run_case(context, [failing_assertion])
    assert result.status == "failed" and result.error == ""
    artifact = next(
        p
        for p in context.directory.glob("*-failure.json")
        if json.loads(p.read_text())["kind"] == "failure"
    )
    value = json.loads(artifact.read_text())["value"]
    assert value["frames"][-1]["file"].endswith("test_acceptance_proofs.py")
    assert value["frames"][-1]["function"] == "failing_assertion"
    assert value["frames"][-1]["line"] > 0
    assert "never-export-this-local" not in artifact.read_text()
    assert "locals" not in artifact.read_text()


def test_trace_proof_rejects_missing_disconnected_and_wrong_linked_facts(
    tmp_path, monkeypatch
):
    context = ScenarioContext.isolated(tmp_path, case_id="F02", seed=92)
    flow = b.order(context, 1)
    try:
        rid = b.revision(flow)
        wid = b.work_order(flow, 1, rid)
        b.prepare(flow)
        uid = flow.units[0]
        b.start(flow, wid, [uid])
        b.execution(flow, uid, flow.lots[0])
        b.measure(flow, uid, value="7")
        b.repair(flow, uid, flow.lots[0])
        b.release(flow)
        shipment = b.ship(flow, [uid])["object_id"]
        b.assert_trace(
            flow, uid
        )  # E20 also proves core genealogy before delivery acceptance.
        b.accept(flow, shipment, 1)
        rma, capa = b.feedback(flow)
        real_get = flow.api.get
        real_object = flow.api.object
        b.assert_trace(flow, uid)
        # Each corruption changes only a read result from the real graph.
        for mutation in (
            "empty_edges",
            "missing_material",
            "disconnected_shipment",
            "missing_prior_test",
            "missing_feedback",
            "truncated",
        ):

            def altered_get(path, mutation=mutation):
                result = deepcopy(real_get(path))
                if "/trace?" in path:
                    if mutation == "empty_edges":
                        result["edges"] = []
                    elif mutation == "truncated":
                        result["truncated"] = True
                    elif mutation == "missing_material":
                        result["nodes"] = [
                            n for n in result["nodes"] if n["kind"] != "material_lot"
                        ]
                    else:
                        relation = {
                            "disconnected_shipment": "shipment",
                            "missing_prior_test": "prior_test",
                            "missing_feedback": "capa",
                        }[mutation]
                        result["edges"] = [
                            e for e in result["edges"] if e["relation"] != relation
                        ]
                return result

            monkeypatch.setattr(flow.api, "get", altered_get)
            with pytest.raises(AssertionError, match=".+"):
                b.assert_trace(flow, uid)
        monkeypatch.setattr(flow.api, "get", real_get)
        for kind, field in (
            ("shipment", "order_line_id"),
            ("rma", "unit_id"),
            ("test", "revision_id"),
        ):

            def altered_object(project, object_kind, ident, kind=kind, field=field):
                value = deepcopy(real_object(project, object_kind, ident))
                if object_kind == kind:
                    value[field] = context.identifier("wrong-link")
                return value

            monkeypatch.setattr(flow.api, "object", altered_object)
            with pytest.raises(AssertionError, match=".+"):
                b.assert_trace(flow, uid)
        monkeypatch.setattr(flow.api, "object", real_object)
    finally:
        flow.api.close()


def test_e12_future_equipment_is_the_only_blocker(tmp_path):
    context = ScenarioContext.isolated(tmp_path, case_id="E12", seed=93)
    result = run_case(context)
    assert result.status == "passed", result.error
    assert result.actual["planned_use_after_equipment_expiry"] is True
    assert result.actual["only_equipment_changed"] is True
    assert result.actual["blocked_kinds"] == ["equipment"]


@pytest.mark.parametrize(
    "mutation", ["planned_now", "equipment_ready", "people_blocked"]
)
def test_e12_proof_rejects_lost_planned_use_or_equipment_isolation(
    tmp_path, monkeypatch, mutation
):
    from .scenarios import execution_quality_cases as cases
    from .scenarios.fixtures import BusinessHTTP

    context = ScenarioContext.isolated(tmp_path, case_id="E12", seed=94)
    if mutation == "planned_now":
        real_work_order = cases.work_order

        def wrong_plan(*args, **kwargs):
            kwargs["planned_start"] = context.clock
            return real_work_order(*args, **kwargs)

        monkeypatch.setattr(cases, "work_order", wrong_plan)
    else:
        real_object = BusinessHTTP.object

        def altered_read(self, project, kind, ident):
            value = deepcopy(real_object(self, project, kind, ident))
            if kind == "work_order":
                checks = value["trial_readiness"]["checks"]
                if any(
                    c["kind"] == "equipment" and c["status"] == "blocked"
                    for c in checks
                ):
                    for check in checks:
                        if (
                            mutation == "equipment_ready"
                            and check["kind"] == "equipment"
                        ):
                            check["status"] = "ready"
                        if mutation == "people_blocked" and check["kind"] == "people":
                            check["status"] = "blocked"
            return value

        monkeypatch.setattr(BusinessHTTP, "object", altered_read)
    result = run_case(context)
    assert result.status == "failed"
    assert (
        "strictly between" if mutation == "planned_now" else "Only future-use equipment"
    ) in result.error
