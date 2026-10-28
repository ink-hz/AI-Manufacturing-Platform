from .scenarios.base import ScenarioContext, run_case
from .scenarios.fixtures import connect


def test_actual_platform_host_uses_fresh_provider_session_and_business_clock(tmp_path):
    from .d3.pf_client import PlatformHTTP

    context = ScenarioContext.isolated(tmp_path, case_id="E31", seed=81)
    api = PlatformHTTP(context)
    try:
        pid = api.project("2")
        source = api.source("demand")
        command = api.command(pid, "demand.record", kind="firm", product="Camera", quantity="2", unit="piece", due_date="2026-12-01", source=source)
        with api.db() as db:
            assert db.execute("SELECT created_at FROM demands WHERE id=?", (command["object_id"],)).fetchone()[0] == context.clock.isoformat()
        old = api.process.pid
        api.restart()
        assert api.process.pid != old
        assert api.get("/projects/" + pid)["id"] == pid
        api.request("GET", "/api/v1/manufacturing/projects", actor="planner", expected=403)
    finally:
        api.close()


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
