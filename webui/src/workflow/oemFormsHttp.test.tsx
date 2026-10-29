import { IntroductionForms } from "./forms/IntroductionForms";
import { AssetForms } from "./forms/AssetForms";
import { LaboratoryForms } from "./forms/LaboratoryForms";
import { CalibrationForms } from "./forms/CalibrationForms";
import { GenealogyForms } from "./forms/GenealogyForms";
import { ArrivalForms } from "./forms/ArrivalForms";
import { AuthorityForms } from "./forms/AuthorityForms";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterAll, afterEach, beforeAll, expect, it, vi } from "vitest";
import { startHttpHost, projectInput } from "./httpTestHost";
import { EngineeringForms } from "./forms/EngineeringForms";
import { SupplyForms } from "./forms/SupplyForms";
import { ExecutionForms } from "./forms/ExecutionForms";
import { QualityForms } from "./forms/QualityForms";
import { QualityWorkspace } from "./QualityWorkspace";
import { DeliveryForms } from "./forms/DeliveryForms";
import { FeedbackForms } from "./forms/FeedbackForms";
import { OrdersForms } from "./forms/OrdersForms";
import type {
  CommandFields,
  CommandResult,
  ProjectDetail,
  WorkspaceProps,
  ObjectKind,
  ObjectSummary,
  DomainValue,
} from "./types";
let http: Awaited<ReturnType<typeof startHttpHost>>,
  session: Awaited<
    ReturnType<Awaited<ReturnType<typeof startHttpHost>>["login"]>
  >,
  host: HTMLDivElement,
  root: Root;
beforeAll(async () => {
  http = await startHttpHost();
  session = await http.login("owner");
  vi.stubGlobal("fetch", session.transport);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
}, 15000);
let preserveFailure = false;
afterEach((context) => {
  if (context.task.result?.state === "fail") preserveFailure = true;
});
afterAll(async () => {
  if (root) await act(async () => root.unmount());
  host?.remove();
  vi.unstubAllGlobals();
  const retain =
    preserveFailure || process.env.WORKFLOW_TEST_KEEP_FIXTURE === "1";
  if (retain)
    console.error(
      `HTTP ${preserveFailure ? "failure" : "success"} fixture retained at ${http?.root}`,
    );
  await http?.close(retain);
});
async function field(name: string, value: string) {
  const e = host.querySelector(
    `input[aria-label="${name}"],select[aria-label="${name}"]`,
  ) as HTMLInputElement;
  expect(e, name).toBeTruthy();
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      e.tagName === "SELECT"
        ? HTMLSelectElement.prototype
        : HTMLInputElement.prototype,
      "value",
    )!.set!.call(e, value);
    e.dispatchEvent(new Event("input", { bubbles: true }));
    e.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
async function button(text: string) {
  const b = [...host.querySelectorAll("button")].find(
    (b) => b.textContent === text,
  );
  expect(b, text).toBeTruthy();
  await act(async () => b!.click());
}
async function check(text: string) {
  const l = [...host.querySelectorAll("label")].find(
    (l) =>
      l.textContent?.includes(text) &&
      l.querySelector('input[type="checkbox"]'),
  );
  expect(l, text).toBeTruthy();
  await act(async () =>
    (l!.querySelector("input") as HTMLInputElement).click(),
  );
}
async function settle() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 40));
  });
}
async function submit() {
  await act(async () => {
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  // Await actual request completion, not a 40ms assumption about loopback I/O.
  await vi.waitFor(
    async () => {
      await act(async () => {
        await new Promise((r) => setTimeout(r, 10));
      });
      expect(host.querySelector("form fieldset:disabled")).toBeNull();
    },
    { timeout: 2000, interval: 10 },
  );
}
it("persists all 21 manufacturing capability actions through named forms and real HTTP", async () => {
  const input = projectInput();
  const p = await session.api.createProject({
    ...input,
    mode: "internal",
    contract: { ...input.contract, customer_release_required: false },
  });
  let result: CommandResult | undefined;
  const props = async (): Promise<WorkspaceProps> => ({
    api: session.api,
    project: await session.api.project(p.id),
    onChanged: (r) => {
      if (!("operation_id" in r))
        throw Error("Expected command acknowledgement");
      result = r;
    },
    onDirty: () => {},
    onOpen: () => {},
    readOnly: false,
  });
  await act(async () =>
    root.render(
      <OrdersForms
        {...await props()}
        action="demand.record"
        demands={[]}
        orders={[]}
        workOrders={[]}
      />,
    ),
  );
  await field("需求数量", "2");
  await field("需求交期", "2026-12-01");
  await field("来源业务编号", "D-HTTP");
  await field("来源凭据", "Signed demand");
  await submit();
  expect(result, host.textContent || "").toBeDefined();
  const demand = (await session.api.objects(p.id, "demand")).items[0];
  expect(demand.source?.object_type).toBe("demand");
  expect(demand.quantity).toBe("2");
  for (const dimension of [
    "technical",
    "material",
    "capacity",
    "commercial",
    "quality",
  ]) {
    result = undefined;
    await act(async () =>
      root.render(
        <OrdersForms
          key={dimension}
          {...await props()}
          action="demand.review"
          demands={[demand]}
          orders={[]}
          workOrders={[]}
        />,
      ),
    );
    await field("评审需求", demand.id);
    await field("评审维度", dimension);
    await field("评审结论", "approved");
    await field("评审凭据", "Signed " + dimension);
    await submit();
    expect(result, host.textContent || "").toBeDefined();
  }
  result = undefined;
  await act(async () =>
    root.render(
      <OrdersForms
        key="order"
        {...await props()}
        action="order.register"
        demands={[demand]}
        orders={[]}
        workOrders={[]}
      />,
    ),
  );
  await field("订单依据需求", demand.id);
  await field("订单数量", "2");
  await field("订单交期", "2026-12-01");
  await field("来源业务编号", "O-HTTP");
  await field("来源凭据", "Signed order");
  await submit();
  expect(result, host.textContent || "").toBeDefined();
  expect(
    (await session.api.objects(p.id, "order_line")).items[0].source
      ?.object_type,
  ).toBe("order_line");
  const allRoles = [
    "project_owner",
    "engineering",
    "planner",
    "supply",
    "production",
    "quality",
    "warehouse",
  ];
  await session.api.grant(p.id, session.identity.user_id, {
    operation_id: crypto.randomUUID(),
    expected_version: (await session.api.project(p.id)).version,
    scope: { kind: "project", project_id: p.id },
    roles: allRoles,
    qualifications: [
      "inspection",
      "disposition",
      "quality_release",
      "readiness_verification",
    ],
    active: true,
    evidence: "Explicit synthetic test grant",
  });
  const items = async (kind: ObjectKind) =>
    (await session.api.objects(p.id, kind)).items;
  const value = async <K extends DomainValue["kind"]>(kind: K, id: string) =>
    (await session.api.object(p.id, kind, id)).value as Extract<
      DomainValue,
      {
        kind: K;
      }
    >;
  const cmd = async (fields: CommandFields) =>
    session.api.command(p.id, {
      ...fields,
      expected_version: (await session.api.project(p.id)).version,
      operation_id: crypto.randomUUID(),
    });
  const manual = (object_type: string, external_id = crypto.randomUUID()) => ({
    system: "fixture source",
    object_type,
    external_id,
    version: 1,
    mode: "manual" as const,
    occurred_at: new Date().toISOString(),
    collected_at: new Date().toISOString(),
    cutoff: null,
    evidence: "Signed fixture evidence",
  });
  let serial = 0;
  const form = async (
    component:
      | typeof OrdersForms
      | typeof EngineeringForms
      | typeof SupplyForms
      | typeof ExecutionForms
      | typeof QualityForms
      | typeof DeliveryForms
      | typeof FeedbackForms,
    extra: Record<string, unknown>,
  ) => {
    result = undefined;
    const Component = component as React.ComponentType<any>;
    await act(async () =>
      root.render(
        <Component
          key={++serial}
          {...await props()}
          demands={await items("demand")}
          orders={await items("order_line")}
          workOrders={await items("work_order")}
          revisions={await items("revision")}
          lots={await items("material_lot")}
          requirements={await items("requirement")}
          commitments={await items("commitment")}
          receipts={await items("receipt")}
          units={await items("unit")}
          tests={await items("test")}
          nonconformances={await items("nonconformance")}
          reworks={await items("rework")}
          interruptions={[]}
          plans={await items("plan")}
          shipments={await items("shipment")}
          members={(await session.api.members(p.id)).items}
          ecos={await items("eco")}
          reservations={await items("reservation")}
          {...extra}
        />,
      ),
    );
    await settle();
  };
  const fill = async (fields: Record<string, string>) => {
    for (const [k, v] of Object.entries(fields)) await field(k, v);
    await settle();
  };
  const sourceFields = async (id: string = crypto.randomUUID()) =>
    fill({ 来源业务编号: id, 来源凭据: "Signed actual form evidence" });
  const saved = async () => {
    await submit();
    expect(result, host.textContent || "").toBeDefined();
    const fact = await session.api.object(
      p.id,
      result!.object_type as ObjectKind,
      result!.object_id,
    );
    expect(fact.summary).toMatchObject({
      project_id: p.id,
      kind: result!.object_type,
      id: result!.object_id,
    });
    return result!;
  };
  await form(OrdersForms, { action: "order.change" });
  const order = (await items("order_line"))[0];
  await fill({
    变更订单: order.id,
    变更后数量: "2",
    变更后交期: "2026-12-02",
    变更原因: "Customer due date change",
  });
  await sourceFields("O-HTTP");
  await field("来源版本", "2");
  const change = (await saved()).object_id;
  await form(OrdersForms, {
    action: "order.resolve_change",
    change: await value("commitment_change", change),
    changeId: change,
  });
  await saved();
  expect((await value("order_line", order.id)).current_due).toBe("2026-12-02");
  await form(EngineeringForms, { action: "engineering.revision" });
  await fill({
    修订号: "M1",
    客户版本: "C1",
    内部版本: "M1",
    固件版本: "F1",
    "资料名称 1": "Camera drawing",
    "资料版本 1": "M1",
    "资料凭据 1": "signed drawing",
    "资料核对 1": "verified",
    "工位 1": "assembly",
    "作业指导版本 1": "S1",
    测试规范版本: "T1",
    测试程序版本: "P1",
    "测量名称 1": "voltage",
    "测量单位 1": "V",
    "测量下限 1": "4",
    "测量上限 1": "6",
  });
  const rev = (await saved()).object_id;
  expect((await value("revision", rev)).test_spec.measurements[0].upper).toBe(
    "6",
  );
  await form(EngineeringForms, { action: "engineering.handoff" });
  await fill({
    交接修订: rev,
    接收系统: "MES",
    实际收到修订号: "M1",
    接收结论: "accepted",
    交接凭据: "MES signed handoff",
  });
  await saved();
  await form(EngineeringForms, { action: "work_order.register" });
  await fill({
    工单依据订单: order.id,
    工单固定修订: rev,
    工单数量: "2",
    试产数量: "1",
    计划开始: "2026-12-01T08:00",
    计划结束: "2026-12-02T08:00",
  });
  await sourceFields("WO-HTTP");
  const wo = (await saved()).object_id;
  expect((await value("work_order", wo)).source.object_type).toBe("work_order");
  await cmd({
    action: "order.allocate",
    order_line_id: order.id,
    work_order_id: wo,
    quantity: "2",
    unit: "piece",
  });
  for (const kind of ["equipment", "people"] as const)
    await cmd({
      action: "readiness.record",
      work_order_id: wo,
      kind,
      reference: kind + "-HTTP",
      evidence: "Current qualified readiness",
      decision: "verified",
      valid_until: "2027-12-01T00:00:00Z",
    });
  await form(SupplyForms, { action: "material.define" });
  await fill({
    物料业务编号: "steel",
    批次业务编号: "LOT-HTTP",
    批次有效期: "2027-12-01",
  });
  await sourceFields("LOT-HTTP");
  const lot = (await saved()).object_id;
  const plan = await cmd({
    action: "plan.receive",
    source: { ...manual("plan"), cutoff: new Date().toISOString() },
    input_revision_ids: [rev],
    input_order_versions: [{ order_line_id: order.id, version: 2 }],
    requirements: ["trial", "bulk"].map((execution_scope) => ({
      work_order_id: wo,
      execution_scope: execution_scope as "trial" | "bulk",
      material_id: "steel",
      owner_id: "Customer 1",
      quantity: "1",
      unit: "kg",
    })),
  });
  const reqs = (await value("plan", plan.object_id)).requirement_ids;
  await form(SupplyForms, { action: "supply.commit" });
  await fill({
    承诺对应需求: reqs[0],
    供应承诺数量: "2",
    原始承诺交期: "2026-12-01",
    当前承诺交期: "2026-12-01",
  });
  await sourceFields("PROMISE-HTTP");
  const commitment = (await saved()).object_id;
  await form(SupplyForms, { action: "supply.receive" });
  await fill({
    到货对应承诺: commitment,
    到货物料批次: lot,
    本次到货数量: "2",
  });
  await sourceFields("RECEIPT-HTTP");
  const receipt = (await saved()).object_id;
  await form(SupplyForms, { action: "supply.inspect" });
  await fill({
    检验到货记录: receipt,
    本次合格数量: "2",
    本次拒收数量: "0",
    检验凭据: "Qualified IQC",
  });
  await saved();
  expect((await value("receipt", receipt)).accepted).toBe("2");
  const external = async (action: string, fields: Record<string, unknown>) => {
    const r = await session.transport("/fixture/authority", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-csrf-token": session.options.csrfToken,
      },
      body: JSON.stringify({ action, fields }),
    });
    expect(r.status, await r.text()).toBe(200);
  };
  await external("receive", {
    project_id: p.id,
    external_id: "WMS-HTTP",
    commitment_id: commitment,
    lot_id: lot,
    material_id: "steel",
    owner_id: "Customer 1",
    quantity: "2",
    unit: "kg",
    scale: 3,
    expiry: "2027-12-01",
    external_actor: "WMS operator",
    signature: "External signed receipt",
  });
  await external("inspect", {
    project_id: p.id,
    external_id: "QMS-HTTP",
    receipt_external_id: "WMS-HTTP",
    accepted: "2",
    rejected: "0",
    external_actor: "QMS inspector",
    signature: "External signed inspection",
  });
  for (const req of reqs) {
    await form(SupplyForms, { action: "reservation.request" });
    await fill({ 预留对应需求: req, 预留物料批次: lot, 请求预留数量: "1" });
    const reservation = await saved();
    await cmd({
      action: "exchange.dispatch",
      exchange_id: reservation.exchange_id!,
    });
    expect((await value("exchange", reservation.exchange_id!)).phase).toBe(
      "accepted",
    );
  }
  await cmd({
    action: "unit.register",
    work_order_id: wo,
    sns: ["CAM-001", "CAM-002"],
  });
  const units = await items("unit");
  expect(units.every((u) => u.revision_id === rev)).toBe(true);
  await form(ExecutionForms, {
    action: "production.start",
    mode: "trial",
    workOrderId: wo,
  });
  await field("开工工单", wo);
  await check("CAM-001");
  const start = await saved();
  await cmd({ action: "exchange.dispatch", exchange_id: start.exchange_id! });
  expect((await value("unit", units[0].id)).state).toBe("running");
  const revision = await value("revision", rev);
  const execute = async (unit: ObjectSummary, rework?: string) => {
    await form(ExecutionForms, {
      action: "execution.record",
      workOrderId: wo,
      revision,
    });
    await fill({ 执行工单: wo, 序列号: unit.title, "实际物料用量 1": "0.001" });
    if (rework)
      await fill({ 独立返工单: rework, 工位: "repair", 作业指导版本: "RW1" });
    await sourceFields();
    return saved();
  };
  const measure = async (
    unit: ObjectSummary,
    measured: string,
    rework?: string,
  ) => {
    await form(QualityForms, {
      action: "test.record",
      unit: await value("unit", unit.id),
      revision,
    });
    await field("voltage 实测值", measured);
    if (rework) await field("独立返工单（复测）", rework);
    await sourceFields();
    return saved();
  };
  await execute(units[0]);
  const oem = async (Component: React.ComponentType<any>, action: string) => {
    result = undefined;
    const kinds: ObjectKind[] = [
      "revision",
      "work_order",
      "unit",
      "test",
      "npi",
      "npi_issue",
      "reusable_asset",
      "asset_use",
      "test_plan",
      "test_run",
      "calibration",
      "component_link",
      "arrival",
      "authority_rule",
      "receipt",
      "material_lot",
      "rework",
    ];
    const pages = await Promise.all(
      kinds.map(async (k) => [k, await items(k)] as const),
    );
    await act(async () =>
      root.render(
        <Component
          key={++serial}
          {...await props()}
          action={action}
          items={Object.fromEntries(pages)}
          configurationAdmin
          publicAssets={(await session.api.publicAssets()).items}
        />,
      ),
    );
    await settle();
  };
  await oem(LaboratoryForms, "test_plan.publish");
  await fill({
    测试计划固定修订: rev,
    测试层级: "unit",
    测试工位: "assembly",
    测试设备: "meter-1",
    测试治具: "fixture-1",
    算法版本: "A1",
  });
  const testPlan = (await saved()).object_id;
  await oem(LaboratoryForms, "test_run.start");
  await fill({ 运行测试计划: testPlan, "运行产品 SN": units[0].id });
  const abortedRun = (await saved()).object_id;
  await oem(LaboratoryForms, "test_run.finish");
  await field("待结束运行", abortedRun);
  await settle();
  await field("运行结束状态", "aborted");
  await field(
    "中断或无效原因",
    "Observed interruption in isolated HTTP fixture",
  );
  await sourceFields();
  await saved();
  expect(await value("test_run", abortedRun)).toMatchObject({
    state: "aborted",
    outcome: null,
    test_id: null,
  });
  await oem(LaboratoryForms, "test_run.start");
  await fill({ 运行测试计划: testPlan, "运行产品 SN": units[0].id });
  const run = (await saved()).object_id;
  await oem(LaboratoryForms, "test_run.finish");
  await field("待结束运行", run);
  await settle();
  await vi.waitFor(() =>
    expect(host.querySelector('[aria-label="实际测量值 1"]')).toBeTruthy(),
  );
  expect(
    (host.querySelector('[aria-label="实际测量值 1"]') as HTMLInputElement)
      .value,
  ).toBe("");
  await field("实际测量值 1", "5");
  await button("添加观察曲线");
  await fill({
    "曲线名称 1": "voltage",
    "横轴单位 1": "ms",
    "纵轴单位 1": "V",
    "曲线 1 点 1 x": "0.00000000000000000001",
    "曲线 1 点 1 y": "5",
  });
  await button("添加原始日志");
  await field("原始日志 1", "Simulated test fixture observation");
  await sourceFields();
  await saved();
  const runFact = await value("test_run", run);
  expect(runFact).toMatchObject({ state: "completed", outcome: "pass" });
  expect(runFact.raw?.curves[0].points[0].x).toBe("0.00000000000000000001");
  const actualTest = runFact.test_id!;
  expect((await value("test", actualTest)).current_qualified).toBe(true);
  await oem(CalibrationForms, "calibration.record");
  await fill({
    标定依据运行: run,
    标定算法版本: "A1",
    "标定参数名称 1": "gain",
    "标定参数单位 1": "ratio",
    "标定参数数值 1": "1.25",
    参数来源标识: "fixture-parameter-record",
    参数来源版本: "1",
    参数登记凭据: "Simulated manual parameter observation",
  });
  const calibration = (await saved()).object_id;
  expect((await value("calibration", calibration)).state).toBe("pending");
  await oem(CalibrationForms, "calibration.confirm");
  await field("待确认标定", calibration);
  await settle();
  expect(
    (host.querySelector('[aria-label="实际读回数值 1"]') as HTMLInputElement)
      .value,
  ).toBe("");
  await fill({
    "实际读回数值 1": "1.25",
    读回来源标识: "fixture-independent-readback",
    读回来源版本: "2",
    读回确认凭据: "Simulated independently observed readback",
  });
  await saved();
  expect((await value("calibration", calibration)).state).toBe("confirmed");
  await oem(GenealogyForms, "unit.alias");
  await fill({
    "对应出厂 SN": units[0].id,
    客户序列号: "CUSTOMER-HTTP-001",
    序列号对应凭据: "Simulated customer label observation",
  });
  await saved();
  await oem(GenealogyForms, "component.install");
  await fill({
    "安装产品 SN": units[0].id,
    部件物料业务编号: "steel",
    部件序列号: "COMP-HTTP-001",
    "部件批次（可选）": lot,
    部件安装凭据: "Simulated installation observation",
  });
  const component = (await saved()).object_id;
  await oem(GenealogyForms, "component.remove");
  await fill({
    待拆除安装记录: component,
    部件拆除凭据: "Simulated removal observation",
  });
  await saved();
  expect(
    (await value("unit", units[0].id)).components?.[0].removal?.evidence,
  ).toBe("Simulated removal observation");
  await oem(IntroductionForms, "npi.open");
  await fill({
    导入固定修订: rev,
    产品族: "camera",
    "必需检查项 1": "drawing",
  });
  const npi = (await saved()).object_id;
  await oem(IntroductionForms, "npi.review");
  await field("评审导入", npi);
  await settle();
  await fill({
    "检查结论 1": "pass",
    "检查凭据 1": "Simulated signed drawing review",
    "检查理由 1": "Fixed specification checked",
  });
  await saved();
  await oem(IntroductionForms, "npi.trial");
  await fill({
    试做导入: npi,
    试做工单: wo,
    试做凭据: "Simulated actual trial test reference",
  });
  await check((await items("test")).find((t) => t.id === actualTest)!.title);
  await saved();
  await oem(IntroductionForms, "npi.issue");
  await fill({
    问题所属导入: npi,
    问题现象: "Private fixture offset",
    风险: "Assembly variation",
    遏制措施: "Hold fixture",
  });
  const issue = (await saved()).object_id;
  await oem(IntroductionForms, "npi.resolve");
  await fill({
    待验证问题: issue,
    已验证原因: "Signed fixture alignment inspection",
    对策: "Alignment control",
    解决验证凭据: "Simulated signed process inspection",
  });
  await saved();
  await oem(AssetForms, "asset.publish");
  await fill({
    资产来源问题: issue,
    项目资产标题: "Private fixture process",
    "项目资产适用产品族 1": "camera",
    项目资产执行内容: "Private project fixture instruction",
    项目资产验证方法: "Private inspection",
  });
  await check("单独编写并批准公共内容");
  expect(
    (host.querySelector('[aria-label="公共资产执行内容"]') as HTMLInputElement)
      .value,
  ).toBe("");
  await fill({
    公共资产标题: "Generic fixture check",
    "公共资产适用产品族 1": "camera",
    公共资产执行内容: "Check generic alignment",
    公共资产验证方法: "Inspect alignment",
  });
  const asset = (await saved()).object_id;
  const catalog = await session.api.publicAssets();
  expect(JSON.stringify(catalog)).not.toContain("Private");
  expect(catalog.items.some((a) => a.asset_revision_id === asset)).toBe(true);
  await oem(AssetForms, "asset.apply");
  await fill({ 采用目标导入: npi, 采用资产修订: asset });
  const use = (await saved()).object_id;
  await oem(AssetForms, "asset.verify");
  await fill({
    待验证采用: use,
    资产验证结论: "pass",
    资产验证凭据: "Simulated independent target inspection",
  });
  await saved();
  await oem(IntroductionForms, "npi.approve");
  await fill({
    待批准导入: npi,
    导入批准凭据: "Simulated current complete evidence review",
  });
  await saved();
  expect((await value("npi", npi)).bulk_eligible).toBe(true);
  await oem(ArrivalForms, "arrival.record");
  await fill({
    "到件编号（扫码或输入）": "SCAN-HTTP-001",
    观察收货或暂存位置: "Receiving shelf",
    观察包裹数: "2",
    实物观察描述: "Labels observed; purchase identity initially unknown",
  });
  await sourceFields();
  const arrival = (await saved()).object_id;
  await oem(ArrivalForms, "arrival.match");
  await field("待匹配收货观察", arrival);
  await settle();
  await fill({
    核对后的到货凭据: receipt,
    收货匹配凭据: "Simulated observed label matched",
  });
  await saved();
  const receipt2 = (
    await cmd({
      action: "supply.receive",
      commitment_id: commitment,
      material_lot_id: lot,
      quantity: "0.1",
      unit: "kg",
      source: manual("receipt"),
    })
  ).object_id;
  await oem(ArrivalForms, "arrival.match");
  await field("待匹配收货观察", arrival);
  await settle();
  await fill({
    核对后的到货凭据: receipt2,
    收货匹配凭据: "Simulated corrected label match",
    匹配纠正原因: "Initial receipt selection corrected",
  });
  await saved();
  expect((await value("arrival", arrival)).matches).toHaveLength(2);
  await oem(AuthorityForms, "authority.register");
  await fill({
    责任对象类别: "receipt",
    责任业务范围: "receiving",
    候选责任系统: "Unconnected candidate WMS",
    责任人或组织: "Warehouse lead",
    责任登记凭据: "Simulated proposed contract",
  });
  const rule = (await saved()).object_id;
  await oem(AuthorityForms, "authority.verify");
  await fill({
    待核验责任映射: rule,
    责任契约核验凭据: "Simulated signed contract review",
  });
  await saved();
  expect(await value("authority_rule", rule)).toMatchObject({
    state: "verified",
    connection_state: "unconnected",
  });
  for (const kind of [
    "introduction",
    "materials",
    "change",
    "knowledge",
    "testing",
    "quality",
  ] as const) {
    const assistance = await session.api.assistance(p.id, kind);
    expect(assistance).toMatchObject({ kind, mode: "rules", project_id: p.id });
  }

  // Stale CAS stays in the named form and retains the observed draft.
  await oem(IntroductionForms, "npi.issue");
  await fill({
    问题所属导入: npi,
    问题现象: "Stale draft survives conflict",
    风险: "fixture risk",
    遏制措施: "fixture hold",
  });
  await cmd({
    action: "authority.register",
    object_category: "receipt",
    business_scope: "second scope",
    system: "manual fixture",
    responsible_identity: "fixture owner",
    origin: "demo",
    evidence: "Concurrent isolated fixture update",
  });
  result = undefined;
  await submit();
  expect(result).toBeUndefined();
  expect(host.textContent).toContain("草稿已保留");
  expect(
    (host.querySelector('[aria-label="问题现象"]') as HTMLInputElement).value,
  ).toBe("Stale draft survives conflict");
  // A forged foreign selector value is still rejected by the real scoped backend.
  const foreign = await session.api.createProject(projectInput());
  result = undefined;
  await act(async () =>
    root.render(
      <IntroductionForms
        key={++serial}
        {...await props()}
        project={foreign}
        action="npi.open"
        items={{ revision: await items("revision") }}
      />,
    ),
  );
  await fill({
    导入固定修订: rev,
    产品族: "camera",
    "必需检查项 1": "drawing",
  });
  await submit();
  expect(result).toBeUndefined();
  expect((await session.api.objects(foreign.id, "npi")).total).toBe(0);
  expect(host.querySelector('[role="alert"]')).toBeTruthy();
  // A read-only form does not send a command even on direct submit dispatch.
  const before = (await items("npi_issue")).length;
  await act(async () =>
    root.render(
      <IntroductionForms
        key={++serial}
        {...await props()}
        readOnly
        action="npi.issue"
        items={{ npi: await items("npi") }}
      />,
    ),
  );
  expect(
    (host.querySelector('button[type="submit"]') as HTMLButtonElement).disabled,
  ).toBe(true);
  await act(async () =>
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
  expect((await items("npi_issue")).length).toBe(before);
}, 60000);
