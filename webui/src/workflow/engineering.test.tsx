import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import { EngineeringForms } from "./forms/EngineeringForms";
import { WorkflowDetail } from "./WorkflowDetail";
import { createWorkflowApi } from "./api";
import type {
  ProjectDetail,
  CommandFields,
  ObjectDetail,
  ObjectSummary,
} from "./types";
const id = "00000000-0000-4000-8000-000000000001",
  order = "00000000-0000-4000-8000-000000000002",
  revision = "00000000-0000-4000-8000-000000000003",
  workOrder = "00000000-0000-4000-8000-000000000004";
const project: ProjectDetail = {
  id,
  version: 7,
  name: "相机项目",
  line_id: "相机线",
  product: "D1",
  customer_id: "客户甲",
  mode: "internal",
  unit: { code: "件", scale: 0 },
  quantity: "100",
  contract: {
    customer_approval_required: true,
    customer_release_required: false,
    acceptance_required: true,
    customer_revision: "C1",
    internal_revision: "I1",
    material_ownership_rules: "客户所有",
  },
  allowed_actions: [
    "engineering.revision",
    "engineering.handoff",
    "engineering.customer_approval",
    "work_order.register",
    "readiness.record",
  ],
  stages: [],
  summary: {
    original_order_quantity: "100",
    current_order_quantity: "100",
    allocated: "0",
    produced_good: "0",
    shipped: "0",
    signed: "0",
    accepted: "0",
    remaining_to_ship: "100",
    remaining_to_accept: "100",
  },
};
function summary(
  id: string,
  kind: ObjectSummary["kind"],
  title: string,
): ObjectSummary {
  return {
    id,
    kind,
    title,
    project_id: project.id,
    state: kind === "revision" ? "fixed" : "active",
    quantity: null,
    unit: null,
    version: 1,
    source: null,
    blocking_reasons: [],
    next_actions: [],
  };
}
let box: HTMLDivElement,
  root: Root,
  commands: any[],
  detail: ObjectDetail,
  api: ReturnType<typeof createWorkflowApi>;
const changed = vi.fn(),
  dirty = vi.fn();
const response = (v: unknown) => new Response(JSON.stringify(v));
async function flush() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}
async function field(label: string, value: string) {
  const e = box.querySelector(`[aria-label="${label}"]`) as HTMLInputElement;
  expect(e, label).toBeTruthy();
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
async function click(label: string) {
  const b = [...box.querySelectorAll("button")].find(
    (b) => b.textContent === label,
  );
  expect(b, label).toBeTruthy();
  await act(async () => b!.click());
  await flush();
}
async function mount(action: CommandFields["action"]) {
  await act(async () =>
    root.render(
      <EngineeringForms
        action={action}
        api={api}
        project={project}
        onChanged={changed}
        onOpen={() => {}}
        onDirty={dirty}
        readOnly={false}
        ecos={[{...summary(order,"eco","ECO M1 → M2"),state:"open"}]}
        orders={[summary(order, "order_line", "ERP-100")]}
        revisions={[summary(revision, "revision", "资料系列 R1")]}
        workOrders={[summary(workOrder, "work_order", "MES-200")]}
      />,
    ),
  );
  await flush();
}
beforeEach(() => {
  box = document.createElement("div");
  document.body.append(box);
  root = createRoot(box);
  commands = [];
  changed.mockClear();
  dirty.mockClear();
  detail = {
    summary: summary(revision, "revision", "资料系列 R1"),
    value: {
      kind: "revision",
      id: revision,
      project_id: id,
      package_id: "camera-family",
      revision: "R1",
      customer_revision: "C1",
      internal_revision: "I1",
      items: [],
      route_steps: [],
      test_spec: {
        version: "T1",
        program_version: "P1",
        measurements: [{ name: "电压", unit: "V", lower: "0", upper: "5" }],
      },
      firmware_version: "F1",
      content_hash: "hash",
      handoffs: [],
      customer_approvals: [],
    },
    relations: [],
    evidence: [],
    history: [],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      if (init.method === "POST") {
        const body = JSON.parse(String(init.body));
        commands.push(body);
        if (body.action === "engineering.revision") {
          const { action, operation_id, expected_version, ...fields } = body;
          detail = {
            ...detail,
            value: {
              ...fields,
              kind: "revision",
              id: revision,
              project_id: id,
              content_hash: "hash",
              handoffs: [],
              customer_approvals: [],
            },
          };
        }
        return response({
          operation_id: body.operation_id,
          project_id: id,
          project_version: 8,
          object_type: "revision",
          object_id: revision,
          exchange_id: null,
          replayed: false,
        });
      }
      return response(detail);
    }),
  );
  api = createWorkflowApi({
    apiBase: "/api/v1/manufacturing",
    csrfToken: "csrf",
    readOnly: false,
  });
});
afterEach(async () => {
  await act(async () => root.unmount());
  api.dispose();
  box.remove();
  vi.unstubAllGlobals();
});
it("fixes a named engineering revision with decimal limits and reads back fixed contents", async () => {
  await mount("engineering.revision");
  for (const [k, v] of Object.entries({
    修订号: "R2",
    固件版本: "F2",
    "资料名称 1": "装配图",
    "来源名称 1": "PLM",
    "资料业务编号或链接 1": "DRW-99",
    "资料版本 1": "B",
    "资料负责人 1": "王工",
    "资料凭据 1": "PLM审核单",
    "核对理由 1": "已检查",
    "工位 1": "装配",
    "作业指导版本 1": "SOP-2",
    测试规范版本: "T2",
    测试程序版本: "P2",
    "测量名称 1": "电压",
    "测量单位 1": "V",
    "测量下限 1": "-0.50",
    "测量上限 1": "0",
  }))
    await field(k, v);
  await field("资料核对 1", "verified");
  await click("固定修订");
  expect(commands).toHaveLength(1);
  expect(commands[0]).toMatchObject({
    action: "engineering.revision",
    expected_version: 7,
    revision: "R2",
    route_steps: [{ station: "装配", instruction_version: "SOP-2" }],
    test_spec: {
      version: "T2",
      program_version: "P2",
      measurements: [{ name: "电压", unit: "V", lower: "-0.50", upper: "0" }],
    },
  });
  expect(commands[0].package_id).toMatch(/[0-9a-f-]{36}/);
  await act(async () =>
    root.render(
      <WorkflowDetail
        api={api}
        target={{ projectId: id, kind: "revision", id: revision }}
        onOpen={() => {}}
      />,
    ),
  );
  await flush();
  expect(box.textContent).toContain("装配图");
  expect(box.textContent).toContain("-0.50 — 0 V");
});
it("selects an existing revision family through its actual package identity", async () => {
  await mount("engineering.revision");
  await field("资料系列", "camera-family");
  expect(
    (box.querySelector('[aria-label="资料系列"]') as HTMLSelectElement).value,
  ).toBe("camera-family");
});
it("registers a fixed order/revision work order with local times converted only at submission", async () => {
  await mount("work_order.register");
  await field("工单依据订单", order);
  await field("工单固定修订", revision);
  await field("工单数量", "20");
  await field("试产数量", "2");
  await field("计划开始", "2026-11-01T09:00");
  await field("计划结束", "2026-11-02T09:00");
  expect(
    (box.querySelector('[aria-label="计划开始"]') as HTMLInputElement).value,
  ).toBe("2026-11-01T09:00");
  await field("来源业务编号", "MES-200");
  await field("来源凭据", "MES工单截图");
  await click("保存工单");
  expect(commands[0]).toMatchObject({
    action: "work_order.register",
    order_line_id: order,
    revision_id: revision,
    quantity: "20",
    trial_quantity: "2",
    unit: "件",
    planned_start: new Date("2026-11-01T09:00").toISOString(),
    planned_end: new Date("2026-11-02T09:00").toISOString(),
  });
});
it("renders rejected handoff and blocked trial/bulk readiness without a generic success", async () => {
  if (detail.value.kind === "revision")
    detail.value.handoffs = [
      {
        id: "receipt",
        to_system: "MES",
        received_revision: "WRONG",
        status: "rejected",
        evidence: "接收记录",
      },
    ];
  await act(async () =>
    root.render(
      <WorkflowDetail
        api={api}
        target={{ projectId: id, kind: "revision", id: revision }}
        onOpen={() => {}}
      />,
    ),
  );
  await flush();
  expect(box.textContent).toContain("拒绝");
  expect(box.textContent).toContain("WRONG");
  const common = {
    ready: false,
    checks: [
      {
        kind: "material",
        required: true,
        status: "blocked" as const,
        reason: "no accepted scoped material reservation",
        evidence_ids: [],
      },
    ],
    input_versions: { project: 7, revision, work_order: 1 },
  };
  detail = {
    summary: summary(workOrder, "work_order", "MES-200"),
    value: {
      kind: "work_order",
      order_line_id: order,
      revision_id: revision,
      quantity: "20",
      unit: "件",
      purpose: "trial",
      trial_quantity: "2",
      source: {
        system: "MES",
        object_type: "work_order",
        external_id: "MES-200",
        version: 1,
        mode: "manual",
        occurred_at: "2026-10-28T00:00:00Z",
        collected_at: "2026-10-28T00:01:00Z",
        cutoff: null,
        evidence: "工单截图",
      },
      planned_start: "2026-11-01T00:00:00Z",
      planned_end: "2026-11-02T00:00:00Z",
      state: "planned",
      trial_readiness: common,
      execution_event_total: 0,
      execution_events: [],
      bulk_readiness: {
        ...common,
        checks: [
          ...common.checks,
          {
            kind: "first_article",
            required: true,
            status: "blocked",
            reason: "matching tested first article absent",
            evidence_ids: [],
          },
        ],
      },
    },
    relations: [],
    evidence: [],
    history: [],
  };
  await act(async () =>
    root.render(
      <WorkflowDetail
        api={api}
        target={{ projectId: id, kind: "work_order", id: workOrder }}
        onOpen={() => {}}
      />,
    ),
  );
  await flush();
  expect(box.textContent).toContain("试产准备 · 阻断");
  expect(box.textContent).toContain("量产准备 · 阻断");
  expect(box.textContent).toContain("缺少已确认的范围内物料预留");
  expect(box.textContent).toContain("缺少匹配版本的首件检验证据");
});
it("submits explicit manual customer signatory and readiness evidence DTOs", async () => {
  await mount("engineering.customer_approval");
  await field("批准修订", revision);
  await field("外部签署人", "客户张工");
  await field("客户批准结论", "approved");
  await field("批准凭据", "客户签字单");
  await click("保存人工批准记录");
  expect(commands[0]).toMatchObject({
    action: "engineering.customer_approval",
    method: "manual",
    external_signatory: "客户张工",
    customer_id: "客户甲",
    decision: "approved",
  });
  await mount("readiness.record");
  await field("准备核验工单", workOrder);
  await field("核验业务编号", "CAL-20");
  await field("核验凭据", "校准有效证明");
  await field("有效期至", "2026-12-01T09:00");
  await click("保存准备证据");
  expect(commands[1]).toMatchObject({
    action: "readiness.record",
    work_order_id: workOrder,
    kind: "equipment",
    reference: "CAL-20",
    evidence: "校准有效证明",
    decision: "verified",
    valid_until: new Date("2026-12-01T09:00").toISOString(),
  });
});
it("retains original draft version when parent project refreshes", async () => {
  await mount("engineering.handoff");
  await field("交接修订", revision);
  await field("实际收到修订号", "I1");
  await field("交接凭据", "MES凭据");
  await act(async () =>
    root.render(
      <EngineeringForms
        action="engineering.handoff"
        api={api}
        project={{ ...project, version: 99 }}
        onChanged={changed}
        onOpen={() => {}}
        onDirty={dirty}
        readOnly={false}
        orders={[]}
        revisions={[summary(revision, "revision", "R1")]}
        workOrders={[]}
      />,
    ),
  );
  await click("保存交接事实");
  expect(commands[0]).toMatchObject({
    action: "engineering.handoff",
    expected_version: 7,
    revision_id: revision,
    to_system: "MES",
    received_revision: "I1",
    decision: "accepted",
    evidence: "MES凭据",
  });
});
it("shows immutable history evidence using the actual ObjectEvidence wire shape", async () => {
  detail.history = [
    {
      event_id: 1,
      actor_id: id,
      action: "engineering.handoff",
      occurred_at: "2026-10-28T00:00:00Z",
      recorded_at: "2026-10-28T00:01:00Z",
      evidence: [{ reference: "历史接收凭据", source: null }],
    },
  ];
  await act(async () =>
    root.render(
      <WorkflowDetail
        api={api}
        target={{ projectId: id, kind: "revision", id: revision }}
        onOpen={() => {}}
      />,
    ),
  );
  await flush();
  expect(box.textContent).toContain("历史接收凭据");
});

it("submits an explicit cancellation ECO boundary without inventing a new revision", async () => {
  await mount("eco.open" as CommandFields["action"]);
  await field("旧固定版本", revision);
  const checkbox = box.querySelector('input[type="checkbox"]') as HTMLInputElement;
  expect(checkbox).toBeTruthy();
  await act(async () => checkbox.click());
  await field("变更原因", "订单取消剩余范围");
  await click("建立 ECO");
  expect(commands[0]).toMatchObject({action:"eco.open", old_revision_id:revision, new_revision_id:null, effective_work_order_ids:[workOrder], effective_sn_ids:[]});
});

it("shows ECO old/new versions, owned stock and waiting authority acceptance", async () => {
  detail = {
    summary:summary(order,"eco","ECO M1 → M2"),
    value:{kind:"eco",id:order,old_revision_id:revision,new_revision_id:id,old_revision:"M1",new_revision:"M2",effective_work_order_ids:[workOrder],effective_sn_ids:[],reason:"替代版本",state:"open",impacts:[{id:revision,type:"stock",object_id:id,title:"LOT-OLD",owner_id:"客户甲",quantity:"15.000",unit:"kg",scale:3,state:"active",resolved_quantity:"0",dispositions:[]}],switches:[{id:revision,work_order_id:workOrder,new_work_order_id:id,boundary:"split_remaining",quantity:"15",retained_quantity:"5",exchange_id:revision,phase:"unknown"}]},
    relations:[], evidence:[],history:[],
  } as ObjectDetail;
  await act(async () => root.render(<WorkflowDetail api={api} target={{projectId:id,kind:"eco",id:order}} onOpen={()=>{}}/>));
  await flush();
  expect(box.textContent).toContain("M1");
  expect(box.textContent).toContain("M2");
  expect(box.textContent).toContain("LOT-OLD");
  expect(box.textContent).toContain("客户甲");
  expect(box.textContent).toContain("等待权威接受");
});


function ecoDetail(): ObjectDetail {
  return {summary:{...summary(order,"eco","ECO M1 → M2"),state:"open"},value:{kind:"eco",id:order,old_revision_id:revision,new_revision_id:id,old_revision:"M1",new_revision:"M2",effective_work_order_ids:[workOrder],effective_sn_ids:[],reason:"M2",state:"open",impacts:[{id:revision,type:"stock",object_id:id,title:"LOT-OLD",owner_id:"客户甲",quantity:"15.000",unit:"kg",scale:3,state:"active",resolved_quantity:"0",dispositions:[]}],switches:[]},relations:[],evidence:[],history:[]};
}
it("records a quantity and evidence against a named ECO impact", async()=>{
  detail=ecoDetail(); await mount("eco.disposition");
  await field("待处理 ECO",order); await flush();
  await field("受影响对象",revision); await field("处置决定","return");
  await field("处置数量","15.000"); await field("处置凭据","退料批准");
  await click("追加 ECO 处置");
  expect(commands[0]).toMatchObject({action:"eco.disposition",eco_id:order,impact_id:revision,quantity:"15.000",decision:"return",evidence:"退料批准"});
});
it("submits a typed split using the selected ECO target revision", async()=>{
  detail=ecoDetail(); await mount("eco.switch");
  await field("待处理 ECO",order); await flush();
  await field("切换原工单",workOrder); await field("切换凭据","未执行十五件拆分");
  await click("请求权威切换");
  expect(commands[0]).toMatchObject({action:"eco.switch",eco_id:order,target_work_order_id:workOrder,new_revision_id:id,boundary:"split_remaining"});
});
it("submits close from a named ECO after showing the unresolved impacts", async()=>{
  detail=ecoDetail(); await mount("eco.close");
  await field("待关闭 ECO",order); await flush();
  expect(box.textContent).toContain("LOT-OLD");
  await click("关闭 ECO");
  expect(commands[0]).toMatchObject({action:"eco.close",eco_id:order});
});

it("pages ECO and serial boundary selectors explicitly without object-detail scans", async()=>{
  const {OrdersWorkspace}=await import("./OrdersWorkspace");
  const calls:string[]=[];
  vi.stubGlobal("fetch",vi.fn(async(url:string)=>{
    calls.push(url);
    const kind=url.split("/objects/")[1]?.split("?")[0];
    if(kind==="eco"||kind==="unit") {
      const offset=Number(new URL(url,"http://test").searchParams.get("offset"));
      return response({items:[{...summary(kind+offset,kind,kind==="eco"?`ECO-${offset}`:`SN-${offset}`),state:kind==="eco"?"open":"registered"}],total:2,limit:50,offset});
    }
    return response({items:[],total:0,limit:50,offset:0});
  }));
  await act(async()=>root.render(<OrdersWorkspace api={api} project={{...project,allowed_actions:[...project.allowed_actions,"eco.open"]}} engineering readOnly={false} requestLeave={f=>f()} onChanged={changed} onOpen={()=>{}} onDirty={dirty}/>));
  await flush();
  const next=[...box.querySelectorAll("button")].filter(b=>b.textContent?.startsWith("读取更多"));
  expect(next).toHaveLength(2);
  for(const b of next) { await act(async()=>b.click()); await flush(); }
  await click("建立 ECO");
  expect(box.textContent).toContain("SN-1");
  expect(calls.filter(c=>c.includes("/objects/unit?"))).toHaveLength(2);
  expect(calls.filter(c=>c.includes("/objects/eco?"))).toHaveLength(2);
  expect(calls.every(c=>c.includes("limit=50"))).toBe(true);
});
