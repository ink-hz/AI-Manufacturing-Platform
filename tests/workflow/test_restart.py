from .scenarios.base import ScenarioContext, run_case
from .scenarios.fixtures import connect


def test_private_http_host_relogs_and_reads_after_process_restart(tmp_path):
    context = ScenarioContext.isolated(tmp_path, case_id="E31", seed=8)

    def scenario(ctx):
        api = connect(ctx)
        project = api.project("1")
        before = api.get("/projects/" + project)
        old_pid = api.process.pid
        api.restart()
        assert api.process.pid != old_pid
        assert api.get("/projects/" + project) == before
        assert api.get("/access")["dataset"]["mode"] == "test"

    result = run_case(context, steps=[scenario])
    assert result.status == "passed", result.error
