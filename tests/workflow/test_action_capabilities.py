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


def test_inspection_only_quality_member_has_no_release_variant_on_detail_or_list(workflow):
    from manufacturing_platform.workflow.commands import COMMAND_REGISTRY

    p, unit = workflow.executed_unit()
    workflow.grant(p["id"], "quality", ["quality"], ["inspection"])
    # Broad registration alone is insufficient; release variants have live policy.
    assert "release.decide" in COMMAND_REGISTRY.allowed_actions(["quality"], ["inspection"])

    def summaries():
        client = workflow.client("quality")
        detail = client.get(f"{BASE}/projects/{p['id']}/objects/unit/{unit['id']}")
        page = client.get(f"{BASE}/projects/{p['id']}/objects/unit")
        assert detail.status_code == page.status_code == 200
        return [detail.json()["summary"], *page.json()["items"]]

    for summary in summaries():
        assert "release.decide" not in summary["next_actions"]
        assert all(c["action"] != "release.decide" for c in summary["action_capabilities"])
    workflow.grant(p["id"], "quality", ["quality"], ["inspection", "quality_release"])
    for summary in summaries():
        assert "release.decide" in summary["next_actions"]
        release = next(c for c in summary["action_capabilities"] if c["action"] == "release.decide")
        assert set(release["variants"]) == {"quality"}
