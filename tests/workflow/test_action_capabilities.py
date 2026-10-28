from .conftest import BASE


def test_actions_follow_live_roles_qualification_and_read_only(workflow):
    p = workflow.create_project()["id"]

    def actions(actor):
        return (
            workflow.client(actor).get(f"{BASE}/projects/{p}").json()["allowed_actions"]
        )

    assert "demand.record" in actions("owner")
    assert "readiness.record" not in actions("owner")
    workflow.grant(p, "engineering", ["engineering"])
    assert "engineering.revision" in actions("engineering")
    assert "readiness.record" not in actions("engineering")
    workflow.grant(p, "engineering", ["engineering"], ["readiness_verification"])
    assert "readiness.record" in actions("engineering")
    workflow.read_only.add("engineering")
    assert actions("engineering") == []
    workflow.read_only.clear()
    workflow.grant(p, "engineering", ["engineering"])
    assert "readiness.record" not in actions("engineering")
