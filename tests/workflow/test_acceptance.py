"""Unit contracts for immutable runs; complete scenarios are selected explicitly by CLI."""

import json
import pytest
from .scenarios.base import ScenarioContext, run_case


def test_runner_stops_at_first_error_and_preserves_evidence(tmp_path):
    context = ScenarioContext.isolated(tmp_path, case_id="E21", seed=41)
    visited = []

    def first(ctx):
        visited.append("first")
        raise AssertionError("intentional quantity mismatch")

    def second(ctx):
        visited.append("second")

    result = run_case(context, steps=[first, second])
    assert result.status == "failed"
    assert result.error == "intentional quantity mismatch"
    assert visited == ["first"]
    original = (context.directory / "result.json").read_bytes()
    with pytest.raises(FileExistsError):
        run_case(context, steps=[second])
    assert (context.directory / "result.json").read_bytes() == original


def test_runner_records_success_in_a_different_owned_run(tmp_path):
    a = ScenarioContext.isolated(tmp_path, case_id="E21", seed=41)
    b = ScenarioContext.isolated(tmp_path, case_id="E21", seed=42)
    assert a.directory != b.directory
    result = run_case(b, steps=[lambda ctx: ctx.actual.update(visited=True)])
    assert result.status == "passed"
    manifest = json.loads((b.directory / "manifest.json").read_text())
    assert manifest["dataset_mode"] == "test"
    assert manifest["source"]["manufacturing_commit"]
    assert manifest["source"]["platform_commit"]
    assert manifest["source"]["release_hash"]
    assert (
        manifest["auth_fixture_boundary"]["transport"]
        == "server-session-cookie-and-CSRF"
    )
    assert manifest["business_clock"] == "2026-10-28T00:00:00+00:00"


def test_unknown_case_fails_before_creating_state(tmp_path):
    with pytest.raises(ValueError, match="Unknown case"):
        ScenarioContext.isolated(tmp_path / "not-created", case_id="E99", seed=41)
    assert not (tmp_path / "not-created").exists()


def test_credentials_redacted_and_snapshots_read_only(tmp_path):
    context = ScenarioContext.isolated(tmp_path, case_id="E25", seed=41)
    context.evidence.record_request(
        {
            "headers": {"Cookie": "secret-cookie", "Authorization": "secret-bearer"},
            "body": {"secret": "secret-password"},
        }
    )
    context.evidence.record_response(
        {"headers": {"set-cookie": "secret-cookie"}, "body": {"csrf": "secret-csrf"}}
    )
    content = "".join(p.read_text() for p in context.directory.glob("*.json"))
    assert (
        "secret-cookie" not in content
        and "secret-bearer" not in content
        and "secret-password" not in content
        and "secret-csrf" not in content
    )
    assert not context.paths.domain.exists()
    context.evidence.record_db_snapshot(context.paths.domain)
    assert not context.paths.domain.exists()


def test_f01(tmp_path):
    context = ScenarioContext.isolated(tmp_path, case_id="F01", seed=41)
    result = run_case(context)
    assert result.status == "passed", result.error
    assert result.actual["quantity"] == 100
    assert result.actual["work_order_quantities"] == [60, 40]
    assert result.actual["remaining_after_first"] == "40"
    assert result.actual["accepted"] == "100"
    assert result.actual["feedback_closed"] is True
    assert list(context.directory.glob("*-external-erp-cost-receipt.json"))


def test_exact36_registry_has_real_callable_scenarios():
    from .scenarios import CASE_IDS, ScenarioRegistry

    assert len(CASE_IDS) == 36
    for case in CASE_IDS:
        assert callable(ScenarioRegistry.get(case))


def test_teardown_error_preserves_first_business_failure(tmp_path):
    context = ScenarioContext.isolated(tmp_path, case_id="E21", seed=41)

    class BrokenClose:
        def close(self):
            raise RuntimeError("teardown failed")

    context.client = BrokenClose()

    def failure(ctx):
        raise AssertionError("original business failure")

    result = run_case(context, steps=[failure])
    assert result.error == "original business failure"
    assert (context.directory / "result.json").exists()


# Full business execution is opt-in for pytest; CLI always invokes selected real cases.
import os


def selected_case(case):
    selected = os.environ.get("WORKFLOW_ACCEPTANCE_CASES", "").split(",")
    return pytest.mark.skipif(
        "all" not in selected and case not in selected,
        reason="Business case not selected; use CLI or WORKFLOW_ACCEPTANCE_CASES",
    )


@selected_case("F02")
def test_f02(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="F02", seed=41))
    assert result.status == "passed", result.error


@selected_case("F03")
def test_f03(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="F03", seed=41))
    assert result.status == "passed", result.error


@selected_case("F04")
def test_f04(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="F04", seed=41))
    assert result.status == "passed", result.error


@selected_case("E01")
def test_e01(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E01", seed=41))
    assert result.status == "passed", result.error


@selected_case("E02")
def test_e02(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E02", seed=41))
    assert result.status == "passed", result.error


@selected_case("E03")
def test_e03(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E03", seed=41))
    assert result.status == "passed", result.error


@selected_case("E04")
def test_e04(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E04", seed=41))
    assert result.status == "passed", result.error


@selected_case("E05")
def test_e05(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E05", seed=41))
    assert result.status == "passed", result.error


@selected_case("E06")
def test_e06(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E06", seed=41))
    assert result.status == "passed", result.error


@selected_case("E07")
def test_e07(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E07", seed=41))
    assert result.status == "passed", result.error


@selected_case("E08")
def test_e08(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E08", seed=41))
    assert result.status == "passed", result.error


@selected_case("E09")
def test_e09(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E09", seed=41))
    assert result.status == "passed", result.error


@selected_case("E10")
def test_e10(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E10", seed=41))
    assert result.status == "passed", result.error


@selected_case("E11")
def test_e11(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E11", seed=41))
    assert result.status == "passed", result.error


@selected_case("E12")
def test_e12(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E12", seed=41))
    assert result.status == "passed", result.error


@selected_case("E13")
def test_e13(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E13", seed=41))
    assert result.status == "passed", result.error


@selected_case("E14")
def test_e14(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E14", seed=41))
    assert result.status == "passed", result.error


@selected_case("E15")
def test_e15(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E15", seed=41))
    assert result.status == "passed", result.error


@selected_case("E16")
def test_e16(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E16", seed=41))
    assert result.status == "passed", result.error


@selected_case("E17")
def test_e17(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E17", seed=41))
    assert result.status == "passed", result.error


@selected_case("E18")
def test_e18(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E18", seed=41))
    assert result.status == "passed", result.error


@selected_case("E19")
def test_e19(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E19", seed=41))
    assert result.status == "passed", result.error


@selected_case("E20")
def test_e20(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E20", seed=41))
    assert result.status == "passed", result.error


@selected_case("E21")
def test_e21(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E21", seed=41))
    assert result.status == "passed", result.error


@selected_case("E22")
def test_e22(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E22", seed=41))
    assert result.status == "passed", result.error


@selected_case("E23")
def test_e23(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E23", seed=41))
    assert result.status == "passed", result.error


@selected_case("E24")
def test_e24(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E24", seed=41))
    assert result.status == "passed", result.error


@selected_case("E25")
def test_e25(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E25", seed=41))
    assert result.status == "passed", result.error


@selected_case("E26")
def test_e26(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E26", seed=41))
    assert result.status == "passed", result.error


@selected_case("E27")
def test_e27(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E27", seed=41))
    assert result.status == "passed", result.error


@selected_case("E28")
def test_e28(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E28", seed=41))
    assert result.status == "passed", result.error


@selected_case("E29")
def test_e29(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E29", seed=41))
    assert result.status == "passed", result.error


@selected_case("E30")
def test_e30(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E30", seed=41))
    assert result.status == "passed", result.error


@selected_case("E31")
def test_e31(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E31", seed=41))
    assert result.status == "passed", result.error


@selected_case("E32")
def test_e32(tmp_path):
    result = run_case(ScenarioContext.isolated(tmp_path, case_id="E32", seed=41))
    assert result.status == "passed", result.error


def test_cli_unknown_case_exits_two_without_state(tmp_path):
    import subprocess
    import sys
    from .scenarios.base import ROOT

    output = tmp_path / "must-not-exist"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/run_workflow_acceptance.py"),
            "--cases",
            "E99",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2 and "Unknown case" in result.stderr
    assert not output.exists()


def test_registry_imports_without_pytest_dependency():
    import subprocess
    import sys
    from .scenarios.base import ROOT

    code = "import sys; from workflow.scenarios import CASE_IDS, ScenarioRegistry; [ScenarioRegistry.get(c) for c in CASE_IDS]; assert 'pytest' not in sys.modules"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "tests")},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
