#!/usr/bin/env python3
"""Exercise the actual loopback preview API; unconnected external systems are mock.

Uses a fresh owned preview directory. The only direct maintenance write assigns
the immutable demo integration profile immediately after HTTP project creation.
All business commands, reads, source operations and recovery use socket HTTP.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import select
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx

import preview_manufacturing as preview

BASE = "/api/v1/manufacturing/workflow"
TABLES = ("material_lots", "supply_receipts", "iqc_results", "reservations", "requirements")
FLAG = "Expedited: open expedite on linked requirement"


class Walkthrough:
    def __init__(self, root, output):
        self.root, self.output = root, output
        self.manifest = preview.load_owned(root)
        self.steps, self.process, self.client = [], None, None
        self.pid = None

    def record(self, name, **fields):
        self.steps.append(dict(step=name, **fields))
        print(name, flush=True)

    def stop(self):
        if self.client:
            self.client.close()
            self.client = None
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
            self.process.stdout.close()
            self.process.stderr.close()
            self.process = None

    def start(self, actor_id=None):
        self.stop()
        command = [sys.executable, str(Path(preview.__file__)), "serve", "--root", str(self.root)]
        if actor_id:
            command += ["--actor-id", actor_id]
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if not select.select([self.process.stdout], [], [], 20)[0]:
            raise RuntimeError("preview startup timed out")
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("preview startup failed: " + self.process.stderr.read())
        url = json.loads(line)["url"]
        self.client = httpx.Client(base_url=url, timeout=30)
        deadline = time.monotonic() + 10
        while True:
            try:
                bootstrap = self.client.get("/preview-bootstrap")
                bootstrap.raise_for_status()
                break
            except httpx.ConnectError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.025)
        body = bootstrap.json()
        self.client.headers.update({"Origin": url, "X-CSRF-Token": body["csrfToken"]})
        self.record("preview process", url=url, actor=body["bootstrap"]["user"],
                    configuration_admin=body["bootstrap"]["configuration_admin"], external_systems="mock")

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        if response.status_code != 200:
            raise AssertionError(f"{method} {path}: {response.status_code} {response.text}")
        return response.json()

    def command(self, action, **fields):
        version = self.request("GET", f"{BASE}/projects/{self.pid}")["version"]
        body = dict(action=action, operation_id=str(uuid4()), expected_version=version, **fields)
        result = self.request("POST", f"{BASE}/projects/{self.pid}/commands", json=body)
        network = result.get("network")
        self.record(action, http_status=200, object_type=result["object_type"], object_id=result["object_id"],
                    project_version=result["project_version"], integration=result.get("integration"),
                    network={k: network[k] for k in ("pending", "delivered", "duplicate", "failed")} if network else None)
        return result

    def value(self, kind, ident):
        return self.request("GET", f"{BASE}/projects/{self.pid}/objects/{kind}/{ident}")

    def source(self, kind):
        now = datetime.now(UTC).isoformat()
        return dict(system="manual", object_type=kind, external_id=str(uuid4()), version=1,
                    mode="manual", occurred_at=now, collected_at=now, evidence="Isolated manual walkthrough observation")

    def facts(self, system, kind):
        return self.request("GET", f"{BASE}/projects/{self.pid}/systems/{system}/facts",
                            params=dict(object_type=kind, limit=200))["records"]

    def fact(self, key):
        return self.request("GET", f"{BASE}/projects/{self.pid}/systems/{key['system']}/facts/{key['object_type']}/{key['external_id']}",
                            params=dict(version=key["version"]))

    @staticmethod
    def key(fact):
        return {name: fact["source"][name] for name in ("system", "object_type", "external_id", "version")}

    def execute(self, system, operation, fact_type, **fields):
        result = self.command("mock_system.execute", system=system, payload=dict(operation=operation, **fields))
        assert result["integration"]["phase"] == "applied", result
        for _ in range(10):
            queried = self.command("mock_system.query", intent_id=result["integration"]["intent_id"])
            assert queried["network"]["failed"] == 0, queried
            if queried["network"]["pending"] == 0:
                break
        else:
            raise AssertionError("Mock causal deliveries did not settle within ten bounded batches")
        key = dict(system=system, object_type=fact_type,
                   external_id=result["integration"]["intent_id"], version=1)
        detail = self.fact(key)
        assert detail["source_accepted"] is True and detail["workflow_projected"] is True, detail
        assert detail["fact"]["source"]["mode"] == "mock"
        self.record(operation + " source evidence", source=detail["fact"]["source"],
                    source_accepted=detail["source_accepted"], consumer_delivered=detail["consumer_delivered"],
                    workflow_projected=detail["workflow_projected"], sap_posted=detail["sap_posted"],
                    targets=detail["projection"]["targets"])
        return detail

    @staticmethod
    def target(detail, kind):
        return next(t["id"] for t in detail["projection"]["targets"] if t["kind"] == kind)

    def accounting(self):
        with sqlite3.connect(f"file:{self.root / 'workflow.db'}?mode=ro", uri=True) as tx:
            result = {name: tx.execute(f"SELECT * FROM {name} ORDER BY rowid").fetchall() for name in TABLES}
        with sqlite3.connect(f"file:{self.root / 'authority.db'}?mode=ro", uri=True) as tx:
            names = [r[0] for r in tx.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            result["legacy_authority"] = {name: tx.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall() for name in names}
        for system in ("wms", "sap"):
            path = self.root / "mock-systems" / self.manifest["dataset"]["id"] / (system + ".sqlite3")
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as tx:
                result[system + "_facts"] = tx.execute("SELECT * FROM facts ORDER BY sequence").fetchall()
        return result

    def tasks(self, ident):
        items = self.request("GET", BASE + "/tasks", params=dict(project_id=self.pid))["items"]
        return [item for item in items if item["target"]["id"] == ident]

    def run(self):
        self.start()
        now = datetime.now(UTC)
        due, expiry = (now + timedelta(days=7)).date().isoformat(), (now + timedelta(days=90)).date().isoformat()
        amount = dict(quantity="5", unit="piece", scale=0)
        project = self.request("POST", BASE + "/projects", json=dict(
            operation_id=str(uuid4()), name="【模拟】急料批次②③ HTTP 走查", line_id="MOCK-LINE", product="MOCK-OEM",
            customer_id="MOCK-CUSTOMER", mode="oem", unit=dict(code="piece", scale=0), quantity="5",
            contract=dict(customer_approval_required=False, customer_release_required=False, acceptance_required=False,
                          customer_revision="A", internal_revision="A", material_ownership_rules="customer")))
        self.pid = project["id"]
        self.record("HTTP create OEM project", http_status=200, project_id=self.pid, mode=project["mode"])
        # Server-owned maintenance, before grants or any domain operation. No API
        # accepts a client-selected adapter/profile; preserve that boundary.
        from manufacturing_platform.workflow.store import WorkflowStore
        from manufacturing_platform.workflow.integrations.routing import assign_profile
        store = WorkflowStore(str(self.root / "workflow.db"), str(self.root / "authority.db"), self.manifest["dataset"])
        with store.transaction(write=True) as tx:
            assign_profile(tx, UUID(self.pid), "oem-network-v1")
        self.record("demo maintenance profile assignment", profile="oem-network-v1", business_rows_written=False)
        production = next(s for s in self.manifest["synthetic_subjects"] if s["display_name"].endswith("production"))
        self.request("PUT", f"{BASE}/projects/{self.pid}/members/{production['user_id']}", json=dict(
            operation_id=str(uuid4()), expected_version=project["version"], scope=dict(kind="project", project_id=self.pid),
            roles=["production"], qualifications=[], active=True, evidence="Synthetic production actor for two-person receipt"))
        demand = self.command("demand.record", kind="firm", product="MOCK-OEM", quantity="5", unit="piece", due_date=due,
                              source=self.source("demand"))["object_id"]
        for dimension in ("technical", "material", "capacity", "commercial", "quality"):
            self.command("demand.review", demand_id=demand, dimension=dimension, decision="approved", evidence="Synthetic reviewed scope")
        order = self.execute("sap", "sap.release_order", "order", demand_id=demand, customer_id="MOCK-CUSTOMER",
                             product="MOCK-OEM", amount=amount, due_date=due)
        oid = self.target(order, "order_line")
        revision = self.execute("pdm", "pdm.publish_revision", "revision", package_id="MOCK-PACKAGE", revision="A",
            customer_revision="A", internal_revision="A", firmware_version="F1", released_at=now.isoformat(),
            bom_materials=[dict(material_id="MOCK-MAT", per_unit=dict(quantity="1", unit="piece", scale=0))],
            items=[dict(id="drawing", kind="drawing", title="Synthetic drawing", revision="A", status="verified", evidence="Mock released drawing")],
            route_steps=[dict(station="assembly", instruction_version="S1")],
            test_spec=dict(version="T1", program_version="P1", measurements=[dict(name="voltage", unit="V", lower="4", upper="6")]))
        rid = self.target(revision, "revision")
        work = self.execute("sap", "sap.release_work_order", "work_order", order_line_id=oid, revision_id=rid,
                            released_revision=self.key(revision["fact"]), amount=amount,
                            trial_amount=dict(quantity="1", unit="piece", scale=0), purpose="production",
                            planned_start=now.isoformat(), planned_end=(now + timedelta(days=1)).isoformat())
        wid = self.target(work, "work_order")
        self.command("order.allocate", order_line_id=oid, work_order_id=wid, quantity="5", unit="piece")
        lot = self.command("material.define", material_id="MOCK-MAT", lot_id="MOCK-LOT", owner_id="MOCK-CUSTOMER",
                           unit="piece", scale=0, expiry=expiry, source=self.source("material_lot"))["object_id"]
        reqid = str(uuid4())
        self.execute("sap", "sap.publish_plan", "plan", input_revision_ids=[rid],
            input_order_versions=[dict(order_line_id=oid, version=1)],
            requirements=[dict(requirement_id=reqid, work_order_id=wid, execution_scope="common", material_id="MOCK-MAT",
                               owner_id="MOCK-CUSTOMER", amount=amount)], cutoff=datetime.now(UTC).isoformat())
        purchase = next(f for f in self.facts("sap", "purchase_requirement") if f["payload"]["requirement_id"] == reqid)
        commitment = str(uuid4())
        promise = self.execute("srm", "srm.promise", "promise", requirement_id=reqid,
            purchase_requirement=self.key(purchase), commitment_id=commitment, supplier_id="MOCK-SUPPLIER",
            owner_id="MOCK-CUSTOMER", supply_type="customer", amount=amount,
            original_due=due, current_due=due, evidence="Mock supplier/customer promise; no production SRM connection")
        announcement = self.execute("srm", "srm.announce_arrival", "arrival", commitment_id=commitment,
            promise=self.key(promise["fact"]), material_id="MOCK-MAT", supplier_batch="MOCK-B1", supplier_id="MOCK-SUPPLIER",
            amount=amount, expected_at=now.isoformat(), coa_reference="MOCK-COA", coa_evidence="Synthetic certificate reference")
        before = self.accounting()
        case = self.command("expedite.open", requirement_id=reqid, reason="Mock supplier delay", impact="Mock work order at risk")["object_id"]
        assert self.accounting() == before
        assert len(self.tasks(case)) == 1
        self.record("general expedite responsibility", title=self.tasks(case)[0]["title"], accounting_unchanged=True)
        arrival = self.command("arrival.record", arrival_number="MOCK-AR", location="receiving", package_count=1,
                               description="Synthetic package", source=self.source("arrival"))["object_id"]
        receipt = self.execute("wms", "wms.receive", "receipt", custodian="warehouse", commitment_id=commitment,
            material_lot_id=lot, lot_id="MOCK-LOT", material_id="MOCK-MAT", owner_id="MOCK-CUSTOMER", amount=amount,
            location="receiving", supplier_batch="MOCK-B1", expiry=expiry, arrival=self.key(announcement["fact"]))
        receipt_id = self.target(receipt, "receipt")
        self.command("arrival.match", arrival_id=arrival, receipt_id=receipt_id, evidence="Package and received source reconciled")
        self.execute("mes", "mes.inspect", "iqc", receipt=self.key(receipt["fact"]), accepted=amount,
                     rejected=dict(quantity="0", unit="piece", scale=0), evidence="Mock IQC qualified")
        summary = self.value("receipt", receipt_id)["summary"]
        assert summary["blocking_reasons"] and summary["blocking_reasons"][0] == FLAG, summary
        tasks = self.tasks(case)
        assert len(tasks) == 1 and tasks[0]["title"] == "急料已检验，待安排上线/关案"
        before = self.accounting()
        assert self.tasks(case) == tasks and self.accounting() == before
        self.record("receipt urgent flag and qualified responsibility", receipt_id=receipt_id,
                    blocking_reasons=summary["blocking_reasons"], task_title=tasks[0]["title"], read_accounting_unchanged=True)
        qualification = next(f for f in self.facts("wms", "qualification") if f["payload"]["material_lot_id"] == lot)
        allocation = dict(material_lot_id=lot, material_id="MOCK-MAT", owner_id="MOCK-CUSTOMER", amount=amount,
                          qualification=self.key(qualification))
        self.execute("wms", "wms.putaway", "putaway", work_order_id=wid, allocations=[allocation],
            source_custody=dict(location="receiving", custodian="warehouse"),
            destination_custody=dict(location="rack-A", custodian="warehouse"), cause=self.key(receipt["fact"]), evidence="Mock physical putaway")
        reservation = self.execute("wms", "wms.reserve", "reservation", requirement_id=reqid, work_order_id=wid, allocations=[allocation])
        pick = self.execute("wms", "wms.pick", "pick", work_order_id=wid,
            allocations=[dict(**allocation, reservation=self.key(reservation["fact"]))],
            source_custody=dict(location="rack-A", custodian="warehouse"),
            destination_custody=dict(location="line-A", custodian="production"), cause=self.key(reservation["fact"]), evidence="Mock physical pick")
        pick_detail = self.fact(self.key(pick["fact"]))
        assert pick_detail["consumer_delivered"] is True, pick_detail
        posting = [f for f in self.facts("sap", "accounting_entry") if f["payload"]["cause"] == self.key(pick["fact"])]
        assert len(posting) == 1, posting
        self.command("integration.pull", source_key=self.key(posting[0]))
        posting_detail = self.fact(self.key(posting[0]))
        assert posting_detail["source_accepted"] is True and posting_detail["sap_posted"] is True, posting_detail
        self.record("WMS pick causal SAP posting", source_key=self.key(pick["fact"]),
                    consumer_delivered=pick_detail["consumer_delivered"], sap_posting_key=self.key(posting[0]),
                    sap_posted=posting_detail["sap_posted"], workflow_projected=posting_detail["workflow_projected"])
        # Separate sender and receiver through actual preview processes. Actor
        # selection admits only manifest subjects and never grants admin access.
        self.start(production["user_id"])
        handoff = self.command("material_handoff.record", material_lot_id=lot, work_order_id=wid, quantity="5", unit="piece",
            from_location="rack-A", to_location="line-A", receiver_id=self.manifest["admin_id"])["object_id"]
        self.start()
        self.command("material_handoff.receive", handoff_id=handoff, received_quantity="5", received_location="line-A")
        before = self.accounting()
        for stage in ("printed", "picked", "receipted", "posted"):
            self.command("issue.mark", requirement_id=reqid, stage=stage, note="Manual status observation, no accounting effect")
            assert self.accounting() == before
        marks = self.request("GET", f"{BASE}/projects/{self.pid}/objects/issue_mark", params=dict(requirement_id=reqid, limit=2))
        rest = self.request("GET", f"{BASE}/projects/{self.pid}/objects/issue_mark", params=dict(requirement_id=reqid, limit=2, offset=2))
        assert marks["total"] == rest["total"] == 4 and len(marks["items"] + rest["items"]) == 4
        milestones = self.value("material_expedite", case)["value"]["milestones"]
        assert all(milestones.values()), milestones
        self.record("four issue marks and all five milestones", marks_total=marks["total"], milestones=milestones, accounting_unchanged=True)
        self.command("expedite.close", expedite_id=case, outcome="fulfilled", reason="Mock physical chain completed")
        assert self.accounting() == before
        assert not self.tasks(case)
        assert FLAG not in self.value("receipt", receipt_id)["summary"]["blocking_reasons"]
        self.record("closed case clears flag and responsibility", case_id=case, accounting_unchanged=True)
        shortage = self.execute("mes", "mes.shortage", "shortage", requirement_id=reqid, reason="Mock new shortage report", impact="Mock delivery risk")
        new_case = self.target(shortage, "material_expedite")
        assert self.accounting() == before
        case_value = self.value("material_expedite", new_case)["value"]
        assert case_value["state"] == "open"
        assert (case_value["source"]["system"], case_value["source"]["mode"]) == ("mes", "mock")
        for _ in range(2):
            self.command("integration.pull", source_key=self.key(shortage["fact"]))
        cases = self.request("GET", f"{BASE}/projects/{self.pid}/objects/material_expedite")
        assert cases["total"] == 2 and self.accounting() == before
        self.start()
        assert self.value("material_expedite", new_case)["value"]["source"] == case_value["source"]
        self.record("MES shortage replay and restart", case_id=new_case, case_count=cases["total"],
                    source=case_value["source"], accounting_unchanged=True, restart_readable=True)

    def save(self, success, error=None):
        self.output.mkdir(parents=True, exist_ok=True)
        report = dict(success=success, recorded_at=datetime.now(UTC).isoformat(), preview_directory=str(self.root),
                      project_id=self.pid, platform="actual loopback HTTP service", external_systems="typed mock", error=error, steps=self.steps)
        (self.output / "http-evidence.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        lines = ["# 急料批次②③真实 HTTP 数据流走查", "", f"时间：{report['recorded_at']}",
                 f"结果：{'通过' if success else '失败'}；项目：{self.pid}", "",
                 "平台运行 preview_manufacturing.py 的实际回环 socket 服务；未打通的外部 SAP/WMS/MES/PDM 使用类型化 mock。",
                 "业务操作全部通过 HTTP；唯一直接维护步骤是在新项目任何业务意图之前绑定 demo 集成档案。",
                 "交接发起与签收使用不同的清单内合成身份，切换通过重启 preview --actor-id 完成，不放松授权。",
                 "原始响应关键字段见同目录 http-evidence.json；不记录 CSRF token。", ""]
        if error:
            lines += ["失败：" + error, ""]
        for item in self.steps:
            lines += ["## " + item["step"], "", "```json", json.dumps(item, ensure_ascii=False, indent=2), "```", ""]
        (self.output / "e2e-walkthrough.md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--platform-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if root.exists():
        parser.error("A new preview root is required; existing data is never reseeded")
    if output.is_relative_to(root):
        parser.error("Evidence output must be outside the owned preview directory")
    preview.prepare(root, args.platform_root)
    walkthrough = Walkthrough(root, output)
    try:
        walkthrough.run()
    except Exception as exc:
        walkthrough.save(False, f"{type(exc).__name__}: {exc}")
        raise
    else:
        walkthrough.save(True)
    finally:
        walkthrough.stop()


if __name__ == "__main__":
    main()
