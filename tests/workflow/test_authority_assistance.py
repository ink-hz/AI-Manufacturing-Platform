"""Authority evidence and bounded rule assistance through actual HTTP."""
from uuid import uuid4

from .conftest import BASE
from .test_arrivals import fields, stock


def mapping(**overrides):
    return dict(object_category="receipt", business_scope="customer-supplied materials", system="WMS candidate", responsible_identity="Warehouse lead", evidence="proposed contract v1", origin="manual", **overrides)


def test_authority_revisions_verification_never_connect_or_rewrite_sources(workflow):
    w = workflow
    p, _, c = w.material_requirement(qualified="0")
    before = stock(w)
    first = w.command(p["id"], "authority.register", actor_name="engineering", **mapping())["object_id"]
    w.command(p["id"], "authority.verify", rule_id=first, expected_status=422)
    w.command(p["id"], "authority.verify", rule_id=first, contract_evidence="reviewed object contract and scope")
    second = w.command(p["id"], "authority.register", **{**mapping(), "system":"alternate WMS"})["object_id"]
    old = w.object(p["id"], "authority_rule", first)
    new = w.object(p["id"], "authority_rule", second)
    assert old["revision"] == 1 and not old["active"] and old["state"] == "verified"
    assert new["revision"] == 2 and new["active"] and new["supersedes_id"] == first
    assert new["connection_state"] == old["connection_state"] == "unconnected"
    assert old["verification"]["contract_evidence"] == "reviewed object contract and scope"
    w.command(p["id"], "authority.verify", rule_id=first, contract_evidence="replace", expected_status=409)
    for override in ({"connected":True}, {"connection_state":"production_connected"}, {"business_scope":" "}):
        w.command(p["id"], "authority.register", expected_status=422, **{**mapping(), **override})
    demo = w.command(p["id"], "authority.register", **{**mapping(),"business_scope":"demo scope","origin":"demo","system":"mock-wms"})["object_id"]
    assert w.object(p["id"], "authority_rule", demo)["connection_state"] == "demo"
    assert stock(w) == before


def test_authority_live_policy_scope_cas_replay_and_csrf(workflow):
    w = workflow
    p = w.create_project()
    w.grant(p["id"], "engineering", ["engineering"])
    w.grant(p["id"], "production", ["production"])
    url = f"{BASE}/projects/{p['id']}/commands"
    for action, data in [("authority.register", mapping()), ("authority.verify", None)]:
        if data is None:
            data = dict(rule_id=ident,contract_evidence="reviewed scope contract")
        version = w.client().get(f"{BASE}/projects/{p['id']}").json()["version"]
        body=dict(action=action,operation_id=str(uuid4()),expected_version=version,**data)
        assert w.client("production").post(url,json=body).status_code == 403
        assert w.client("engineering").post(url,json={**body,"expected_version":version-1}).status_code == 409
        assert w.client("engineering").post(url,json=body,headers={"x-csrf-token":"bad"}).status_code == 403
        response=w.client("engineering").post(url,json=body)
        assert response.status_code == 200, response.text
        ident=response.json()["object_id"]
        assert w.client("engineering").post(url,json=body).json()["replayed"]
        w.read_only.add("engineering")
        assert w.client("engineering").post(url,json=body).status_code == 403
        w.read_only.clear()
        w.grant(p["id"],"engineering",["production"])
        assert w.client("engineering").post(url,json=body).status_code == 403
        w.grant(p["id"],"engineering",["engineering"])
    p2=w.create_project()
    w.command(p2["id"],"authority.verify",rule_id=ident,contract_evidence="foreign",expected_status=404)
    assert w.client("outsider").get(f"{BASE}/projects/{p['id']}/objects/authority_rule/{ident}").status_code == 404


def assist(w,p,kind):
    r=w.client().get(f"{BASE}/projects/{p['id']}/assistance?kind={kind}")
    assert r.status_code == 200,r.text
    assert "no-store" in r.headers["cache-control"]
    return r.json()


def test_rule_assistance_zero_evidence_readonly_and_project_scope(workflow):
    w=workflow
    p=w.create_project()
    for kind in ("introduction","materials","change","knowledge","testing","quality"):
        value=assist(w,p,kind)
        assert value["mode"] == "rules" and value["state"] == "no_evidence"
        assert value["items"] == [] and value["unknowns"]
    assert w.client("outsider").get(f"{BASE}/projects/{p['id']}/assistance?kind=materials").status_code == 404
    assert w.client().get(f"{BASE}/projects/{p['id']}/assistance?kind=other").status_code == 422
    before=stock(w)
    assert w.client().post(f"{BASE}/projects/{p['id']}/assistance?kind=materials",json={}).status_code == 405
    assert stock(w) == before


def test_material_assistance_actual_partial_iqc_and_pending_identity(workflow):
    w=workflow
    p,req,c=w.material_requirement(qualified="0")
    receipt=w.receive(p["id"],c["id"],quantity="10",lot_id=c["lot_id"])["object_id"]
    w.command(p["id"],"supply.inspect",receipt_id=receipt,accepted="3",rejected="2",evidence="partial sample")
    arrival=w.command(p["id"],"arrival.record",**fields(w))["object_id"]
    before=stock(w)
    with w.db() as tx:
        counts=tuple(tx.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("operations","audit_events"))
    value=assist(w,p,"materials")
    by_id={i["target"]["id"]:i for i in value["items"]}
    assert "Inspect" in by_id[receipt]["suggestion"]
    assert "receipt" in by_id[arrival]["suggestion"]
    assert req["id"] in by_id and by_id[receipt]["quantities"] == {"accepted":"3","rejected":"2","pending":"5","unit":"kg"}
    assert by_id[arrival]["blockers"] and by_id[arrival]["target"]["scope"] == "project"
    assert stock(w)==before
    with w.db() as tx:
        assert counts==tuple(tx.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("operations","audit_events"))
    detail=w.client().get(f"{BASE}/projects/{p['id']}/objects/receipt/{receipt}").json()
    assert detail["value"]["quantity_state"] == "partially_inspected"
    assert detail["value"]["next_step"] == "inspect_remaining"
    assert detail["summary"]["state"] == "partially_inspected"
    assert "supply.inspect" in detail["summary"]["next_actions"]
    p2=w.create_project()
    assert assist(w,p2,"materials")["items"]==[]


def test_introduction_and_change_assistance_reference_actual_current_objects(workflow):
    from .test_introduction import open_npi
    from .test_eco import open_eco_with_stock
    w=workflow
    p,eco,_=open_eco_with_stock(w)
    npi=open_npi(w,p,eco["old_revision_id"])
    issue=w.command(p["id"],"npi.issue",npi_id=npi,phenomenon="missing drawing",risk="assembly blocked",containment="hold release")["object_id"]
    value=assist(w,p,"introduction")
    by_id={i["target"]["id"]:i for i in value["items"]}
    assert by_id[npi]["blockers"] and by_id[issue]["blockers"]
    change=assist(w,p,"change")["items"][0]
    assert change["target"]["id"]==eco["id"] and change["blockers"]
    targets={r["id"] for r in change["related_targets"]}
    assert {i["object_id"] for i in eco["impacts"]}.issubset(targets)
    for target in change["related_targets"]:
        assert w.client().get(f"{BASE}/projects/{p['id']}/objects/{target['kind']}/{target['id']}").status_code==200


def test_knowledge_assistance_uses_only_sanitized_applicable_public_assets(workflow):
    from .test_introduction import resolved_issue, publish, CONTENT, open_npi
    w=workflow
    private,npi,issue=resolved_issue(w)
    secret=publish(w,private,issue)
    public=publish(w,private,issue,public_content=CONTENT)
    w.grant(private["id"],"production",[],active=False)
    target,_,_,revision=w.order_workorder()
    open_npi(w,target,revision["id"])
    w.grant(target["id"],"production",["production"])
    url=f"{BASE}/projects/{target['id']}/assistance?kind=knowledge"
    r=w.client("production").get(url)
    assert r.status_code==200
    value=r.json()
    assert [i["target"]["id"] for i in value["items"]]==[public]
    assert value["items"][0]["target"]["scope"]=="public_catalog"
    assert value["items"][0]["target"]["project_id"] is None
    for text in ("PRIVATE",private["id"],issue,npi,secret):
        assert text not in r.text
    assert w.client("production").get(f"{BASE}/projects/{private['id']}/objects/reusable_asset/{public}").status_code==404
    w.read_only.add("production")
    assert w.client("production").get(url).status_code==200
    w.grant(target["id"],"production",[],active=False)
    assert w.client("production").get(url).status_code==404


def test_authority_summary_live_actions_admin_future_scope_and_replay_conflict(workflow):
    w=workflow
    p=w.create_project()
    for actor in ("owner","admin"):
        result=w.command(p["id"],"authority.register",actor_name=actor,**{**mapping(),"business_scope":actor})
        ident=result["object_id"]
        detail=w.client(actor).get(f"{BASE}/projects/{p['id']}/objects/authority_rule/{ident}").json()
        assert detail["summary"]["next_actions"]==["authority.verify"]
        assert detail["summary"]["blocking_reasons"]
        body=dict(action="authority.register",operation_id=result["operation_id"],expected_version=result["project_version"]-1,**{**mapping(),"business_scope":actor,"evidence":"changed intent"})
        assert w.client(actor).post(f"{BASE}/projects/{p['id']}/commands",json=body).status_code==409
        w.command(p["id"],"authority.verify",actor_name=actor,rule_id=ident,contract_evidence="scoped review")
    w.grant(p["id"],"production",["production"])
    detail=w.client("production").get(f"{BASE}/projects/{p['id']}/objects/authority_rule/{ident}").json()
    assert detail["summary"]["next_actions"]==[]


def test_schema20_additive_migration_preserves_existing_facts(workflow):
    import sqlite3
    from manufacturing_platform.workflow.schema import SCHEMA_VERSION
    w=workflow
    p,_,_=w.material_requirement(qualified="0")
    before=stock(w)
    with w.db() as tx:
        facts={t:[tuple(r) for r in tx.execute(f"SELECT * FROM {t} ORDER BY rowid")] for t in ("projects","operations","audit_events")}
    w._client.close()
    with sqlite3.connect(w.paths.domain) as tx:
        for table in ("arrival_matches","arrivals","authority_verifications","authority_rules"):
            tx.execute(f"DROP TABLE {table}")
        tx.execute("UPDATE schema_version SET version=20")
    w.reopen()
    assert w.client().get(f"{BASE}/projects/{p['id']}").status_code==200
    assert stock(w)==before
    with w.db() as tx:
        assert tx.execute("SELECT version FROM schema_version").fetchone()[0]==SCHEMA_VERSION
        assert facts=={t:[tuple(r) for r in tx.execute(f"SELECT * FROM {t} ORDER BY rowid")] for t in facts}
    w.command(p["id"],"arrival.record",**fields(w))


def test_assistance_material_limit_is_visible_and_returns_real_scoped_targets(workflow):
    w=workflow
    p=w.create_project()
    for index in range(101):
        w.command(p["id"],"arrival.record",**{**fields(w),"arrival_number":f"PKG-{index}"})
    value=assist(w,p,"materials")
    assert len(value["items"])==100 and value["truncated"]
    assert any("first 100" in text for text in value["unknowns"])
    page=w.client().get(f"{BASE}/projects/{p['id']}/objects/arrival?limit=200").json()
    assert [i["target"]["id"] for i in value["items"]]==[i["id"] for i in page["items"][:100]]


def all_facts(w):
    with w.db() as tx:
        tables = [r[0] for r in tx.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {table: [tuple(r) for r in tx.execute(f'SELECT * FROM "{table}" ORDER BY rowid')] for table in tables}


def test_material_assistance_bounds_arrival_history_without_losing_current_match(workflow, monkeypatch):
    import sqlite3

    w = workflow
    p, _, commitment = w.material_requirement(qualified="0")
    receipts = [
        w.receive(p["id"], commitment["id"], quantity="1", lot_id=commitment["lot_id"])["object_id"]
        for _ in range(3)
    ]
    inventory = stock(w)
    observation = fields(w)
    arrival = w.command(p["id"], "arrival.record", **observation)["object_id"]
    original = w.object(p["id"], "arrival", arrival)
    for index in range(103):
        w.command(
            p["id"], "arrival.match", arrival_id=arrival,
            receipt_id=receipts[2] if index == 102 else receipts[index % 2],
            evidence=f"Checked package label {index}",
            **({"correction_reason": f"Correcting selection {index - 1}"} if index else {}),
        )
        if index == 99:
            result = assist(w, p, "materials")
            item = next(i for i in result["items"] if i["target"]["id"] == arrival)
            assert len(item["related_targets"]) == 100
            assert not item["evidence_truncated"] and not result["truncated"]
    assert stock(w) == inventory
    before = all_facts(w)

    # Trace real HTTP queries so loading the full history then slicing cannot pass.
    statements = []
    connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", traced_connect)
        response = w.client().get(f"{BASE}/projects/{p['id']}/objects/arrival")
        assert response.status_code == 200, response.text
        summary = response.json()["items"][0]
        result = assist(w, p, "materials")
    item = next(i for i in result["items"] if i["target"]["id"] == arrival)
    assert len(item["related_targets"]) == 100
    assert item["related_targets"][-1] == dict(
        scope="project", project_id=p["id"], kind="receipt", id=receipts[2],
    )
    assert item["state"] == summary["state"] == "matched"
    assert summary["version"] == 104
    assert item["source"] == original["source"]
    assert observation["source"]["evidence"] in item["evidence"]
    assert item["evidence_truncated"] and result["truncated"]
    assert any("100" in text and "unknown" in text for text in item["unknowns"])
    assert any("truncated" in text.lower() for text in result["unknowns"])
    history_queries = [sql.upper() for sql in statements if "FROM ARRIVAL_MATCHES" in sql.upper()]
    assert history_queries
    assert all("COUNT(" in sql or "LIMIT" in sql for sql in history_queries)

    detail = w.client().get(f"{BASE}/projects/{p['id']}/objects/arrival/{arrival}").json()
    assert detail["value"]["receipt_id"] == receipts[2]
    assert detail["value"]["source"] == original["source"]
    assert detail["value"]["description"] == observation["description"]
    assert len(detail["value"]["matches"]) == len(detail["relations"]) == 103
    assert detail["value"]["matches"][0]["previous_receipt_id"] is None
    assert detail["value"]["matches"][-1]["previous_receipt_id"] == receipts[1]
    assert len(detail["history"]) == 104
    assert all_facts(w) == before
    assert stock(w) == inventory


def test_testing_assistance_reports_actual_failures_and_scoped_similar_records(workflow):
    from .test_laboratory import setup_run, finish
    from .test_quality import measure
    w = workflow
    p,_,uid,_,_,run = setup_run(w)
    measure(w,p,uid,value="5")
    finish(w,p,run,measurements=[dict(name="voltage",value="13",unit="V",lower="4",upper="6")])
    second = w.object(p["id"],"test_run",run)["test_id"]
    w.grant(p["id"],"production",["production"])
    before = all_facts(w)
    response = assist(w,p,"testing")
    assert response["mode"] == "rules"
    by_id = {item["target"]["id"]: item for item in response["items"]}
    assert by_id[run]["testing"]["run_state"] == "completed"
    assert by_id[run]["testing"]["outcome"] == "fail"
    failed = by_id[second]["testing"]["failed_measurements"]
    assert failed == [dict(name="voltage",value="13",unit="V",lower="4",upper="6")]
    assert by_id[second]["testing"]["similar_targets"]
    assert any("cause" in text for text in by_id[second]["unknowns"])
    assert all_facts(w) == before
    w.read_only.add("production")
    assert w.client("production").get(f"{BASE}/projects/{p['id']}/assistance?kind=testing").status_code == 200
    other = w.create_project()
    assert assist(w,other,"testing")["state"] == "no_evidence"
    assert w.client("outsider").get(f"{BASE}/projects/{p['id']}/assistance?kind=testing").status_code == 404
    w.grant(p["id"],"production",[],active=False)
    assert w.client("production").get(f"{BASE}/projects/{p['id']}/assistance?kind=testing").status_code == 404


def test_quality_assistance_is_8d_evidence_outline_without_invented_effectiveness(workflow):
    from .test_feedback import open_rma, step
    w = workflow
    p,_,_,failed,rma = open_rma(w)
    nc = w.command(p["id"],"nonconformance.open",test_id=failed["id"],defect="registered voltage failure",evidence="actual measurement")["object_id"]
    capa = step(w,p["id"],rma,"containment")["object_id"]
    step(w,p["id"],rma,"root_cause",capa)
    step(w,p["id"],rma,"correction",capa,action_kind="supplier",implementation_evidence="signed supplier action")
    step(w,p["id"],rma,"verification",capa,effective=False)
    before = all_facts(w)
    response = assist(w,p,"quality")
    by_id = {item["target"]["id"]: item for item in response["items"]}
    outline = by_id[capa]["quality_outline"]
    assert outline["registered_causes"][0]["description"] == "Human investigation root_cause"
    assert outline["actions"][0]["implementation_evidence"] == "signed supplier action"
    assert outline["verification"][0]["effective"] is False
    assert "team" in outline["missing_fields"]
    assert by_id[nc]["quality_outline"]["facts"] == ["registered voltage failure"]
    assert by_id[rma["id"]]["quality_outline"]["facts"] == ["Customer observed failure"]
    assert by_id[capa]["blockers"]
    assert all_facts(w) == before
    other = w.create_project()
    empty = assist(w,other,"quality")
    assert empty["state"] == "no_evidence" and empty["items"] == []
    assert w.client("outsider").get(f"{BASE}/projects/{p['id']}/assistance?kind=quality").status_code == 404
    w.read_only.add("quality")
    assert w.client("quality").get(f"{BASE}/projects/{p['id']}/assistance?kind=quality").status_code == 200


def test_receipt_complete_iqc_presentation_does_not_offer_inspecting_remaining_quantity(workflow):
    w = workflow
    p,_,c = w.material_requirement(qualified="0")
    receipt = w.receive(p["id"],c["id"],quantity="4",lot_id=c["lot_id"])["object_id"]
    url = f"{BASE}/projects/{p['id']}/objects/receipt/{receipt}"
    initial = w.client().get(url).json()
    assert initial["value"]["quantity_state"] == "pending_inspection"
    assert "supply.inspect" in initial["summary"]["next_actions"]
    w.command(p["id"],"supply.inspect",receipt_id=receipt,accepted="3",rejected="1",evidence="complete actual IQC")
    detail = w.client().get(url).json()
    assert detail["value"]["quantity_state"] == "mixed"
    assert detail["value"]["next_step"] == "review_rejected"
    assert "supply.inspect" not in detail["summary"]["next_actions"]
    page = w.client().get(f"{BASE}/projects/{p['id']}/objects/receipt").json()
    summary = next(item for item in page["items"] if item["id"] == receipt)
    assert summary["state"] == "mixed" and "supply.inspect" not in summary["next_actions"]
