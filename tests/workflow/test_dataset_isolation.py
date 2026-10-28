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


def test_private_host_rejects_production_or_foreign_fixture_before_database_io(tmp_path):
    from .http_fixture import build_app
    context = ScenarioContext.isolated(tmp_path, case_id="E32", seed=88)
    fixture = context.directory / "fixture.json"
    fixture.write_text(json.dumps({"secret": "synthetic-only", "seed": 88, "dataset_mode": "production", "dataset_id": context.dataset_id}))
    fixture.chmod(0o600)
    with pytest.raises(ValueError, match="test dataset"):
        build_app(context.directory)
    fixture.write_text(json.dumps({"secret": "synthetic-only", "seed": 88, "dataset_mode": "test", "dataset_id": "foreign"}))
    with pytest.raises(ValueError, match="test dataset"):
        build_app(context.directory)
    assert not context.paths.domain.exists() and not context.paths.authority.exists()


def test_owned_dataset_reset_refuses_symlink_without_touching_sentinel(tmp_path):
    from .d3.proof_support import reset_dataset
    context = ScenarioContext.isolated(tmp_path, case_id="E32", seed=89)
    sentinel = tmp_path / "outside.txt"
    sentinel.write_text("untouched")
    context.paths.domain.symlink_to(sentinel)
    with pytest.raises(ValueError, match="symlink"):
        reset_dataset(context.directory)
    assert sentinel.read_text() == "untouched"


def test_manifest_symlink_cannot_authorize_a_process_or_reset(tmp_path):
    context = ScenarioContext.isolated(tmp_path, case_id="E32", seed=90)
    manifest = context.directory / "manifest.json"
    external = tmp_path / "borrowed-manifest.json"
    manifest.rename(external)
    manifest.symlink_to(external)
    with pytest.raises(ValueError):
        owned_run(context.directory)
