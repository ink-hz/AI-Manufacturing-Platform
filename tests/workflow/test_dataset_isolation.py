import json
import pytest
from .scenarios.base import ScenarioContext, run_case, owned_run


def test_seed_changes_identifiers_without_changing_clock(tmp_path):
    a = ScenarioContext.isolated(tmp_path, case_id="F01", seed=41)
    b = ScenarioContext.isolated(tmp_path, case_id="F01", seed=42)
    assert a.identifier("SN") != b.identifier("SN")
    assert a.clock == b.clock
    assert a.paths.domain != b.paths.domain


def test_resume_creates_linked_new_run_preserving_previous_failure(tmp_path):
    previous = ScenarioContext.isolated(tmp_path, case_id="E21", seed=41)

    def fail(ctx):
        raise AssertionError("original failure")

    run_case(previous, steps=[fail])
    original = (previous.directory / "result.json").read_bytes()
    resumed = ScenarioContext.isolated(
        tmp_path, case_id="E21", seed=41, resume=previous.directory
    )
    assert resumed.run_id != previous.run_id
    assert json.loads((resumed.directory / "manifest.json").read_text())[
        "resumes"
    ] == str(previous.directory)
    assert original == (previous.directory / "result.json").read_bytes()


def test_owned_run_rejects_unowned_production_and_symlink(tmp_path):
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    with pytest.raises(ValueError):
        owned_run(unrelated)
    c = ScenarioContext.isolated(tmp_path, case_id="E32", seed=1)
    link = tmp_path / "alias"
    link.symlink_to(c.directory, target_is_directory=True)
    with pytest.raises(ValueError):
        owned_run(link)
    assert owned_run(c.directory)["dataset_mode"] == "test"
