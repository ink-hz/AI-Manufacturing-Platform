"""New isolated OEM examples; never invokes the existing six-project portfolio."""

from .portfolio import Scenario

SIM = "【模拟】"


def record_run(f, plan, uid, runs, label, state="completed", value="5.02", rework=None):
    rid = f.c(
        label + "/start",
        "test_run.start",
        plan_id=plan,
        unit_id=uid,
        rework_order_id=rework,
    )["object_id"]
    runs.append(rid)
    fields = {
        "run_id": rid,
        "state": state,
        "source": f.source(label, "test"),
        "raw": {
            "origin": "demo",
            "curves": [
                {
                    "name": SIM + "电压曲线",
                    "x_unit": "s",
                    "y_unit": "V",
                    "points": [{"x": "0", "y": value}, {"x": "1", "y": value}],
                }
            ],
            "logs": [SIM + label + "；无真实设备连接"],
        },
    }
    if state == "completed":
        fields["measurements"] = [{**f.limit, "value": value}]
    else:
        fields["reason"] = SIM + "采集被中断，无测试结论"
    f.c(label + "/finish", "test_run.finish", **fields)
    return f.value("test_run", rid)


def populate(seed):
    results = {}
    asset = None
    for key, product in [("camera", "工业相机 C-200"), ("robot", "协作机器人 R-6")]:
        f = Scenario(
            seed,
            (
                key,
                SIM + "工程验证",
                product,
                SIM + key + "客户",
                2,
                SIM + "试产与知识复用",
            ),
        )
        if key == "robot":
            f.materials = [("机器人关节驱动控制板", SIM + "制造方自有")]
        f.foundation()
        f.stock()
        f.start(f.units[:1], "trial")
        uid = f.units[0]["id"]
        npi = f.c(
            "npi",
            "npi.open",
            revision_id=f.revision,
            product_family="electromechanical",
            scenario="first_introduction",
            required_checks=["fixture"],
            work_order_ids=[f.work],
        )["object_id"]
        f.c(
            "review",
            "npi.review",
            npi_id=npi,
            checks=[
                {
                    "code": "fixture",
                    "required": True,
                    "decision": "pass",
                    "evidence": SIM + "夹具与版本核对",
                    "reason": SIM + "适用本试产版本",
                }
            ],
        )
        source = f.source("assembly", "execution")
        f.c(
            "assembly",
            "execution.record",
            "production",
            work_order_id=f.work,
            sn=f.units[0]["sn"],
            station=f.route,
            route_version="DEMO-SOP-A.1",
            program_version="DEMO-TEST-A.1",
            firmware_version="DEMO-FW-1.4",
            material_uses=[
                {"lot_id": lot, "quantity": "1", "unit": "件"} for lot in f.lots
            ],
            result="pass",
            occurred_at=source["occurred_at"],
            source=source,
        )
        plan = f.c(
            "test-plan",
            "test_plan.publish",
            revision_id=f.revision,
            level="unit",
            station=SIM + "电源与接口台",
            equipment=SIM + "示例仪表",
            fixture=SIM + "固定夹具",
            algorithm_version="demo-gain-v1",
        )["object_id"]
        runs = []

        if key == "camera":
            record_run(f, plan, uid, runs, "interrupted", state="aborted")
            failed = record_run(f, plan, uid, runs, "failed", value="5.42")
            nc = f.c(
                "nc",
                "nonconformance.open",
                test_id=failed["test_id"],
                defect=SIM + "电源反馈偏差",
                evidence=SIM + "保留5.42V失败测量",
            )["object_id"]
            rw = f.c(
                "rework",
                "nonconformance.disposition",
                nonconformance_id=nc,
                decision="rework",
                route_id="DEMO-RW",
                route_steps=[
                    {
                        "station": "repair",
                        "instruction_version": "DEMO-RW-1",
                        "material_consumption": "none",
                    }
                ],
                evidence=SIM + "调整夹具反馈接触并复测",
            )["object_id"]
            source = f.source("repair", "execution")
            f.c(
                "repair",
                "execution.record",
                work_order_id=f.work,
                sn=f.units[0]["sn"],
                station="repair",
                route_version="DEMO-RW-1",
                program_version="DEMO-TEST-A.1",
                firmware_version="DEMO-FW-1.4",
                material_uses=[],
                result="pass",
                occurred_at=source["occurred_at"],
                source=source,
                rework_order_id=rw,
            )
            passed = record_run(f, plan, uid, runs, "retested", rework=rw)
            unit = f.value("unit", uid)
            f.c(
                "rework-complete",
                "rework.complete",
                rework_order_id=rw,
                execution_event_ids=[unit["execution_events"][-1]["id"]],
                test_ids=[passed["test_id"]],
            )
        else:
            passed = record_run(f, plan, uid, runs, "passed")
        f.c(
            "trial",
            "npi.trial",
            npi_id=npi,
            work_order_id=f.work,
            test_ids=[passed["test_id"]],
            evidence=SIM + "当前试产实测记录",
        )
        f.c(
            "first-article",
            "first_article.record",
            work_order_id=f.work,
            unit_ids=[uid],
            test_ids=[passed["test_id"]],
            inspection_id=SIM + key + "-FAI",
        )
        calibration = f.c(
            "calibration",
            "calibration.record",
            run_id=passed["id"],
            algorithm_version="demo-gain-v1",
            parameters=[{"name": "gain", "value": "1.25", "unit": "ratio"}],
            source_identity=key + "-calculation",
            source_version="1",
            origin="demo",
            evidence=SIM + "预先计算的示例参数；等待独立回读登记，不代表设备写入",
        )["object_id"]
        old = f.c(
            "component-old",
            "component.install",
            unit_id=uid,
            material_id=SIM + "反馈模块",
            component_serial="DEMO-" + key + "-OLD",
            origin="demo",
            evidence=SIM + "安装记录",
        )["object_id"]
        f.c(
            "component-remove",
            "component.remove",
            component_link_id=old,
            evidence=SIM + "更换记录",
        )
        f.c(
            "component-new",
            "component.install",
            unit_id=uid,
            material_id=SIM + "反馈模块",
            component_serial="DEMO-" + key + "-NEW",
            origin="demo",
            evidence=SIM + "替换件安装记录",
        )
        f.c(
            "alias",
            "unit.alias",
            unit_id=uid,
            customer_serial="DEMO-CUSTOMER-" + key + "-001",
            evidence=SIM + "客户SN映射，不改变工厂SN",
        )
        result = {
            "project_id": f.pid,
            "npi_id": npi,
            "unit_id": uid,
            "sn": f.units[0]["sn"],
            "runs": runs,
            "calibration_id": calibration,
            "work_order_id": f.work,
        }
        if key == "camera":
            issue = f.c(
                "issue",
                "npi.issue",
                npi_id=npi,
                phenomenon=SIM + "PRIVATE-CAMERA电源漂移",
                risk=SIM + "客户专属工况",
                containment=SIM + "隔离试产件",
            )["object_id"]
            f.c(
                "resolve",
                "npi.resolve",
                issue_id=issue,
                verified_cause=SIM + "PRIVATE-CAMERA夹具反馈接触不稳",
                countermeasure=SIM + "调整夹具接触并测量",
                verification_evidence=SIM + "复测通过",
                test_ids=[passed["test_id"]],
            )
            content = {
                "title": SIM + "电源反馈与夹具接触检查",
                "category": "check",
                "product_families": ["electromechanical"],
                "execution_content": SIM
                + "检查夹具接触与电源反馈元件；每个目标产品使用自己的限值",
                "verification_method": SIM
                + "目标项目独立测量和签署，不复制源产品合格结论",
            }
            asset = f.c(
                "publish",
                "asset.publish",
                issue_id=issue,
                content={
                    **content,
                    "execution_content": SIM + "PRIVATE-CAMERA专属细节",
                },
                public_content=content,
            )["object_id"]
            f.c("approve", "npi.approve", npi_id=npi, evidence=SIM + "源项目工程审批")
            result["issue_id"] = issue
        else:
            result["asset_use_id"] = f.c(
                "apply",
                "asset.apply",
                npi_id=npi,
                asset_revision_id=asset,
                required=True,
            )["object_id"]
        seed.manifest["projects"].append(
            {
                "key": key,
                "id": f.pid,
                "intended_stage": SIM + "待独立回读"
                if key == "camera"
                else SIM + "待目标验证与导入批准",
            }
        )
        seed.checkpoint()
        results[key] = result
    results["future_project"] = {
        "name": SIM + "新项目",
        "line_id": SIM + "试产线",
        "product": SIM + "产品",
        "customer_id": SIM + "客户",
        "mode": "internal",
        "unit": {"code": "台", "scale": 0},
        "quantity": "1",
        "contract": {
            "customer_approval_required": False,
            "customer_release_required": False,
            "acceptance_required": False,
            "customer_revision": "C1",
            "internal_revision": "M1",
            "material_ownership_rules": SIM + "自有",
        },
    }
    return results
