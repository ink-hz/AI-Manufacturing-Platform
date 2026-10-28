import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import { App } from "../App";
import type { ProjectDetail, ObjectDetail, ObjectKind } from "./types";
const project: ProjectDetail = {
  id: "00000000-0000-4000-8000-000000000001",
  version: 3,
  name: "相机项目",
  line_id: "相机线",
  product: "D1",
  customer_id: "客户甲",
  mode: "internal",
  unit: { code: "件", scale: 0 },
  quantity: "100",
  contract: {
    customer_approval_required: "unknown",
    customer_release_required: "unknown",
    acceptance_required: "unknown",
    customer_revision: "A",
    internal_revision: "1",
    material_ownership_rules: "自有",
  },
  stages: [],
  summary: {
    original_order_quantity: "100",
    current_order_quantity: "80",
    allocated: "0",
    produced_good: "0",
    shipped: "0",
    signed: "0",
    accepted: "0",
    remaining_to_ship: "80",
    remaining_to_accept: "80",
  },
  allowed_actions: ["demand.record", "engineering.revision"],
};
const bootstrap = {
  protocol: 1 as const,
  allowed: true,
  available: true,
  workflow_available: true,
  workflow_access: true,
  can_edit: true,
  release: "test",
  legacy_access: false,
  configuration_admin: false,
  dataset: { id: "demo", mode: "demo" as const, label: "隔离演示" },
  user: { id: "00000000-0000-4000-8000-000000000003", display_name: "李工" },
  project_ids: ["00000000-0000-4000-8000-000000000001"],
};
let host: HTMLDivElement,
  root: Root,
  requests: { url: string; body: any }[],
  fail: number;
const response = (v: unknown, status = 200) =>
  new Response(JSON.stringify(v), { status });
async function flush() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}
async function click(text: string) {
  const b = [...host.querySelectorAll("button")].find(
    (b) =>
      (b.getAttribute("aria-label") || b.textContent?.trim()) === text &&
      !b.closest("[hidden]"),
  );
  expect(b, text).toBeTruthy();
  await act(async () => b!.click());
  await flush();
}
async function field(label: string, value: string) {
  const e = host.querySelector(`[aria-label="${label}"]`) as HTMLInputElement;
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
async function mount(extra = {}) {
  await act(async () =>
    root.render(
      <App
        options={{
          apiBase: "/preview/api/v1/manufacturing",
          csrfToken: "csrf",
          readOnly: false,
          bootstrap,
          ...extra,
        }}
      />,
    ),
  );
  await flush();
}
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  requests = [];
  fail = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const body = init.body ? JSON.parse(String(init.body)) : undefined;
      requests.push({ url, body });
      if (url.endsWith("/commands"))
        return response(
          fail
            ? { code: "VERSION_CONFLICT", message: "Project version changed" }
            : {
                operation_id: body.operation_id,
                project_id: "00000000-0000-4000-8000-000000000001",
                project_version: 4,
                object_type: "demand",
                object_id: "00000000-0000-4000-8000-000000000002",
                replayed: false,
              },
          fail || 200,
        );
      if (url.endsWith("/dashboard"))
        return response({
          counts: { demand: 0 },
          cards: [],
          project_ids: ["00000000-0000-4000-8000-000000000001"],
          project_count: 1,
        });
      if (url.endsWith("/projects")) return response({ items: [project] });
      if (url.endsWith("/projects/00000000-0000-4000-8000-000000000001"))
        return response(project);
      if (url.endsWith("/handbook"))
        return response({
          title: "手册",
          markdown: "# 全文\n\n制造证据",
          release: "test",
          updated_at: "2026-10-28T00:00:00Z",
          source_path: "docs/handbook",
          document: "handbook",
        });
      if (url.includes("/objects/"))
        return response({ items: [], total: 0, limit: 50, offset: 0 });
      throw new Error("Unexpected " + url);
    }),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
it("member mounts only workflow endpoints and implemented navigation", async () => {
  await mount();
  expect(host.textContent).toContain("隔离演示");
  expect(requests.every((r) => r.url.includes("/workflow/"))).toBe(true);
  expect(host.textContent).not.toContain("系统协同");
  await click("制造项目");
  await click("相机项目");
  expect(host.textContent).toContain("原始承诺");
  expect(host.textContent).toContain("100");
  expect(host.textContent).toContain("80");
});
it("named demand form preserves draft CAS, operation and source timestamps on 409 retry", async () => {
  await mount();
  await click("制造项目");
  await click("相机项目");
  await click("订单与需求");
  await click("登记需求");
  await field("需求数量", "20");
  await field("需求交期", "2026-12-01");
  await field("来源业务编号", "ERP-101");
  await field("来源凭据", "客户邮件");
  fail = 409;
  await click("保存需求");
  expect(host.textContent).toContain("草稿已保留");
  expect(
    (host.querySelector('[aria-label="需求数量"]') as HTMLInputElement).value,
  ).toBe("20");
  await click("保存需求");
  const writes = requests.filter((r) => r.body?.action === "demand.record");
  expect(writes).toHaveLength(2);
  expect(writes[0].body).toEqual(writes[1].body);
  expect(writes[0].body).toMatchObject({
    expected_version: 3,
    kind: "firm",
    product: "D1",
    quantity: "20",
    unit: "件",
    due_date: "2026-12-01",
    source: { external_id: "ERP-101", mode: "manual", evidence: "客户邮件" },
  });
});
it("whole handbook uses workflow endpoint and shared renderer while preserving draft", async () => {
  const renderMarkdown = vi.fn(() => ({ unmount: vi.fn() }));
  await mount({ renderMarkdown });
  await click("制造项目");
  await click("相机项目");
  await click("订单与需求");
  await click("登记需求");
  await field("需求数量", "25");
  await click("制造手册");
  expect(renderMarkdown).toHaveBeenCalled();
  expect(requests.some((r) => r.url.endsWith("/workflow/handbook"))).toBe(true);
  await click("返回工作区");
  expect(
    (host.querySelector('[aria-label="需求数量"]') as HTMLInputElement).value,
  ).toBe("25");
});
it("only server allowed actions expose edit forms including qualified readiness", async () => {
  await mount();
  await click("制造项目");
  await click("相机项目");
  await click("工程与工单");
  expect(host.textContent).toContain("固定工程修订");
  expect(host.textContent).not.toContain("登记准备核验");
});
it("guards account return once and clears dirty before invoking host", async () => {
  const dirty = vi.fn();
  const onNavigatePlatform = vi.fn(() =>
    expect(dirty).toHaveBeenLastCalledWith(false),
  );
  await mount({ onDirtyChange: dirty, onNavigatePlatform });
  await click("制造项目");
  await click("相机项目");
  await click("订单与需求");
  await click("登记需求");
  await field("需求数量", "12");
  await click("返回 Agent 平台");
  expect(onNavigatePlatform).not.toHaveBeenCalled();
  expect(host.querySelectorAll('[role="dialog"]')).toHaveLength(1);
  await click("放弃并离开");
  expect(onNavigatePlatform).toHaveBeenCalledTimes(1);
});
it("admin switches to legacy only deliberately and guards a dirty workflow draft", async () => {
  await mount({
    bootstrap: { ...bootstrap, legacy_access: true, configuration_admin: true },
  });
  expect(requests.every((r) => r.url.includes("/workflow/"))).toBe(true);
  await click("制造项目");
  await click("相机项目");
  await click("订单与需求");
  await click("登记需求");
  await field("需求数量", "12");
  await click("打开旧项目协同");
  expect(requests.every((r) => r.url.includes("/workflow/"))).toBe(true);
  await click("放弃并离开");
  expect(requests.some((r) => r.url.endsWith("/catalog"))).toBe(true);
  expect(host.querySelectorAll(".mf-console")).toHaveLength(1);
});
it("creates a project with explicit contract fields and exact decimal string DTO", async () => {
  const prior = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (u, i) =>
    String(u).endsWith("/projects") && i?.method === "POST"
      ? (requests.push({ url: String(u), body: JSON.parse(String(i.body)) }),
        response(project))
      : prior(u, i),
  );
  await mount({ bootstrap: { ...bootstrap, configuration_admin: true } });
  await click("新建项目");
  for (const [k, v] of Object.entries({
    项目名称: "新相机",
    产线名称: "镜头线",
    项目产品: "D2",
    项目客户: "客户乙",
    项目目标数量: "0.50",
    项目单位: "千件",
    合同客户版本: "C1",
    合同内部版本: "I1",
    物料权属规则: "客户所有",
  }))
    await field(k, v);
  await field("数量小数位", "2");
  await click("创建制造项目");
  const body = requests.find((r) => r.body?.name === "新相机")?.body;
  expect(body).toMatchObject({
    quantity: "0.50",
    unit: { code: "千件", scale: 2 },
    contract: {
      customer_approval_required: "unknown",
      customer_release_required: "unknown",
      acceptance_required: "unknown",
      customer_revision: "C1",
      internal_revision: "I1",
      material_ownership_rules: "客户所有",
    },
  });
  expect(body.operation_id).toMatch(/[0-9a-f-]{36}/);
});
it("uses real named member choices and leaves readiness qualifications explicit", async () => {
  const prior = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (u, i) =>
    (String(u).endsWith("/members") || String(u) === `/preview/api/v1/manufacturing/workflow/projects/${project.id}/members?user_id=00000000-0000-4000-8000-000000000004`)
      ? response({ items: [] })
      : String(u).includes("/members/")
        ? (requests.push({ url: String(u), body: JSON.parse(String(i?.body)) }),
          response({
            operation_id: "op",
            project_id: "00000000-0000-4000-8000-000000000001",
            project_version: 4,
            object_type: "project",
            object_id: "00000000-0000-4000-8000-000000000001",
            replayed: false,
          }))
        : prior(u, i),
  );
  const findSubjects = vi.fn(async (_q: string, _signal: AbortSignal) => [
    { id: "00000000-0000-4000-8000-000000000004", displayName: "王工程师" },
  ]);
  await mount({
    bootstrap: { ...bootstrap, configuration_admin: true },
    findSubjects,
  });
  await click("制造项目");
  await click("相机项目");
  await click("成员授权");
  await field("授权成员", "00000000-0000-4000-8000-000000000004");
  expect(
    (host.querySelector('[aria-label="准备依据核验资格"]') as HTMLInputElement)
      .checked,
  ).toBe(false);
  await act(async () =>
    (host.querySelector('[aria-label="工程"]') as HTMLInputElement).click(),
  );
  await field("授权凭据", "主管授权单");
  await click("保存成员授权");
  expect(requests.find((r) => r.url.includes("/members/"))?.body).toMatchObject(
    {
      scope: {
        kind: "project",
        project_id: "00000000-0000-4000-8000-000000000001",
      },
      expected_version: 3,
      roles: ["engineering"],
      qualifications: [],
      active: true,
      evidence: "主管授权单",
    },
  );
});
it("retires directory results after leaving the member workspace", async () => {
  const prior = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (u, i) =>
    String(u).endsWith("/members") ? response({ items: [] }) : prior(u, i),
  );
  let finish!: (v: { id: string; displayName: string }[]) => void;
  const findSubjects = vi.fn(
    (_q: string, _s: AbortSignal) =>
      new Promise<{ id: string; displayName: string }[]>((r) => (finish = r)),
  );
  await mount({
    bootstrap: { ...bootstrap, configuration_admin: true },
    findSubjects,
  });
  await click("制造项目");
  await click("相机项目");
  await click("成员授权");
  await click("工程与工单");
  expect(findSubjects.mock.calls[0][1].aborted).toBe(true);
  await act(async () => finish([{ id: "late", displayName: "迟到用户" }]));
  expect(host.textContent).not.toContain("迟到用户");
});
it("reloads conflicted draft from current project version only after explicit discard", async () => {
  await mount();
  await click("制造项目");
  await click("相机项目");
  await click("订单与需求");
  await click("登记需求");
  await field("需求数量", "20");
  await field("需求交期", "2026-12-01");
  await field("来源业务编号", "ERP-102");
  await field("来源凭据", "邮件");
  fail = 409;
  await click("保存需求");
  const prior = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (u, i) =>
    String(u).endsWith("/projects")
      ? response({ items: [{ ...project, version: 9 }] })
      : prior(u, i),
  );
  await click("重新读取项目");
  await click("放弃并离开");
  await click("登记需求");
  expect(host.textContent).toContain("草稿依据：项目版本 9");
});
it("retires pending workflow responses and dirty edits on authentication loss", async () => {
  const prior = vi.mocked(fetch).getMockImplementation()!;
  const onAuthError = vi.fn(),
    onDirtyChange = vi.fn();
  await mount({ onAuthError, onDirtyChange });
  await click("制造项目");
  await click("相机项目");
  await click("订单与需求");
  await click("登记需求");
  await field("需求数量", "20");
  await field("需求交期", "2026-12-01");
  await field("来源业务编号", "ERP-103");
  await field("来源凭据", "邮件");
  vi.mocked(fetch).mockImplementation(async (u, i) =>
    String(u).endsWith("/commands")
      ? response({ detail: "Forbidden" }, 403)
      : prior(u, i),
  );
  await click("保存需求");
  expect(onAuthError).toHaveBeenCalledTimes(1);
  expect(onDirtyChange).toHaveBeenLastCalledWith(false);
  expect(host.textContent).toContain("无权访问制造工作区");
  expect(host.querySelector("form")).toBeNull();
});
it("reselecting handbook keeps the prior workspace and draft return target", async () => {
  await mount({ renderMarkdown: vi.fn(() => ({ unmount() {} })) });
  await click("制造项目");
  await click("相机项目");
  await click("订单与需求");
  await click("登记需求");
  await field("需求数量", "33");
  await click("制造手册");
  await click("制造手册");
  await click("返回工作区");
  const input = host.querySelector(
    '[aria-label="需求数量"]',
  ) as HTMLInputElement;
  expect(input).not.toBeNull();
  expect(input.closest("[hidden]")).toBeNull();
  expect(input.value).toBe("33");
});
it("keeps initial object reads bounded even when more choices exist", async () => {
  const prior = vi.mocked(fetch).getMockImplementation()!;
  const reads: string[] = [];
  vi.mocked(fetch).mockImplementation(async (u, i) => {
    if (String(u).includes("/objects/demand?")) {
      reads.push(String(u));
      const items = Array.from({ length: 50 }, (_, n) => ({
        id: `00000000-0000-4000-8000-${String(n + Number(new URL(String(u), location.origin).searchParams.get("offset"))).padStart(12, "0")}`,
        project_id: project.id,
        kind: "demand",
        title: `需求 ${n}`,
        state: "firm",
        quantity: "1",
        unit: "件",
        source: null,
        version: 1,
        blocking_reasons: [],
        next_actions: [],
      }));
      return response({ items, total: 100, limit: 50, offset: 0 });
    }
    return prior(u, i);
  });
  await mount();
  await click("制造项目");
  await click("相机项目");
  expect(reads).toHaveLength(1);
  expect(reads[0]).toContain("limit=50");
  expect(host.textContent).toContain("读取更多需求");
});
it("disables an open project form immediately when the host becomes read-only", async () => {
  const admin = { ...bootstrap, configuration_admin: true };
  await mount({ bootstrap: admin });
  await click("新建项目");
  await field("项目名称", "未提交");
  await mount({ bootstrap: admin, readOnly: true });
  const save = [...host.querySelectorAll("button")].find(
    (b) => b.textContent === "创建制造项目",
  );
  expect(save?.disabled).toBe(true);
  expect(
    host.querySelector('[aria-label="项目名称"]')?.matches(":disabled"),
  ).toBe(true);
});
it("advances the next grant draft immediately and rejects delayed older project snapshots", async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  const writes: any[] = [];
  const reads: ((r: Response) => void)[] = [];
  vi.mocked(fetch).mockImplementation(async (u, i) => {
    const url = String(u);
    if (url.endsWith("/members") || ["00000000-0000-4000-8000-000000000010", "00000000-0000-4000-8000-000000000011"].some(user => url === `/preview/api/v1/manufacturing/workflow/projects/${project.id}/members?user_id=${user}`)) return response({ items: [] });
    if (url.includes("/members/")) {
      const body = JSON.parse(String(i?.body));
      writes.push(body);
      return response({
        operation_id: body.operation_id,
        project_id: project.id,
        project_version: 3 + writes.length,
        object_type: "project",
        object_id: project.id,
        exchange_id: null,
        replayed: false,
      });
    }
    if (url.endsWith("/projects") && writes.length)
      return new Promise<Response>((r) => reads.push(r));
    return original(u, i);
  });
  await mount({
    bootstrap: { ...bootstrap, configuration_admin: true },
    findSubjects: async () => [
      { id: "00000000-0000-4000-8000-000000000010", displayName: "成员甲" },
      { id: "00000000-0000-4000-8000-000000000011", displayName: "成员乙" },
    ],
  });
  await click("制造项目");
  await click("相机项目");
  await click("成员授权");
  for (const n of [10, 11]) {
    await field(
      "授权成员",
      `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
    );
    await act(async () =>
      (host.querySelector('[aria-label="工程"]') as HTMLInputElement).click(),
    );
    await field("授权凭据", `授权单${n}`);
    await click("保存成员授权");
  }
  expect(writes.map((w) => w.expected_version)).toEqual([3, 4]);
  await act(async () =>
    reads.forEach((r) => r(response({ items: [project] }))),
  );
  await flush();
  await click("订单与需求");
  await click("登记需求");
  expect(host.textContent).toContain("草稿依据：项目版本 5");
});
it("compares current server facts after a conflict without changing draft CAS or retry identity", async () => {
  const prior = vi.mocked(fetch).getMockImplementation()!;
  let newer = false;
  vi.mocked(fetch).mockImplementation(async (u, i) => {
    if (String(u).endsWith("/commands")) {
      requests.push({ url: String(u), body: JSON.parse(String(i?.body)) });
      newer = true;
      return response(
        {
          code: "VERSION_CONFLICT",
          fields: { current_version: 9 },
          blocking_reasons: [],
        },
        409,
      );
    }
    if (String(u).endsWith("/projects/" + project.id) && newer)
      return response({
        ...project,
        version: 9,
        summary: { ...project.summary, current_order_quantity: "75.250" },
      });
    return prior(u, i);
  });
  await mount();
  await click("制造项目");
  await click("相机项目");
  await click("登记需求");
  await field("需求数量", "20");
  await field("需求交期", "2026-12-01");
  await field("来源业务编号", "ERP-CONFLICT");
  await field("来源凭据", "客户邮件");
  await click("保存需求");
  expect(host.textContent).toContain("服务端冲突版本：9");
  await click("保留草稿并对照当前资料");
  expect(host.textContent).toContain("服务端当前项目版本：9");
  expect(host.textContent).toContain("75.250");
  expect(
    (host.querySelector('[aria-label="需求数量"]') as HTMLInputElement).value,
  ).toBe("20");
  expect(host.textContent).toContain("草稿依据：项目版本 3");
  await click("保存需求");
  const writes = requests.filter((r) => r.body?.action === "demand.record");
  expect(writes).toHaveLength(2);
  expect(writes[0].body).toEqual(writes[1].body);
});
const demandId = "00000000-0000-4000-8000-000000000020",
  orderId = "00000000-0000-4000-8000-000000000021",
  workOrderId = "00000000-0000-4000-8000-000000000022",
  unallocatedId = "00000000-0000-4000-8000-000000000023",
  changeId = "00000000-0000-4000-8000-000000000024";
function businessFixtures(): Record<string, ObjectDetail> {
  const source = {
    system: "ERP",
    object_type: "order_line",
    external_id: "ERP-ORDER-21",
    version: 1,
    mode: "manual" as const,
    occurred_at: "2026-10-28T00:00:00Z",
    collected_at: "2026-10-28T00:01:00Z",
    cutoff: null,
    evidence: "客户订单确认",
  };
  const summary = (id: string, kind: ObjectKind, title: string) => ({
    id,
    kind,
    title,
    project_id: project.id,
    state: "active",
    quantity: "9007199254.123456",
    unit: "件",
    source,
    version: 1,
    blocking_reasons: [],
    next_actions: [],
  });
  const readiness = {
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
    input_versions: { project: 3 },
  };
  const order: ObjectDetail = {
    summary: summary(orderId, "order_line", "ERP-ORDER-21"),
    value: {
      kind: "order_line",
      demand_id: demandId,
      original_quantity: "9007199254.123456",
      current_quantity: "9007199254.123456",
      original_due: "2026-12-01",
      current_due: "2026-12-01",
      unit: "件",
      source,
      state: "active",
      allocated: "0.100001",
      work_order_impact: {
        registered_quantity: "0.100003",
        total: 2,
        shown: 2,
        has_more: false,
        items: [
          {
            id: workOrderId,
            source_system: "MES",
            external_id: "MES-WO-22",
            quantity: "0.100001",
            unit: "件",
          },
          {
            id: unallocatedId,
            source_system: "MES",
            external_id: "MES-WO-23",
            quantity: "0.000002",
            unit: "件",
          },
        ],
      },
      produced_good: "0",
      shipped: "0",
      signed: "0",
      accepted: "0",
      remaining_to_ship: "9007199254.123456",
      remaining_to_accept: "9007199254.123456",
    },
    relations: [
      {
        relation: "allocated_work_order",
        project_id: project.id,
        kind: "work_order",
        id: workOrderId,
      },
    ],
    evidence: [],
    history: [],
  };
  const work = (id: string, ref: string, qty: string): ObjectDetail => ({
    summary: {
      ...summary(id, "work_order", ref),
      state: "planned",
      quantity: qty,
    },
    value: {
      kind: "work_order",
      order_line_id: orderId,
      revision_id: "00000000-0000-4000-8000-000000000025",
      quantity: qty,
      unit: "件",
      purpose: "trial",
      trial_quantity: "0.000001",
      source: { ...source, object_type: "work_order", external_id: ref },
      planned_start: "2026-11-01T00:00:00Z",
      planned_end: "2026-11-02T00:00:00Z",
      state: "planned",
      trial_readiness: readiness,
      bulk_readiness: readiness,
      execution_event_total: 0,
      execution_events: [],
    },
    relations: [],
    evidence: [],
    history: [],
  });
  const demand: ObjectDetail = {
    summary: { ...summary(demandId, "demand", "正式需求 D1"), state: "firm" },
    value: {
      kind: "demand",
      demand_kind: "firm",
      product: "D1",
      quantity: "9007199254.123456",
      unit: "件",
      due_date: "2026-12-01",
      source: { ...source, object_type: "demand", external_id: "DEMAND-20" },
      supersedes_demand_id: null,
      reviews: {
        technical: "approved",
        material: "approved",
        capacity: "approved",
        commercial: "approved",
        quality: "approved",
      },
    },
    relations: [],
    evidence: [],
    history: [],
  };
  const change: ObjectDetail = {
    summary: {
      ...summary(changeId, "commitment_change", "客户缩量变更"),
      state: "pending",
      next_actions: ["order.resolve_change"],
      blocking_reasons: ["change disposition pending"],
    },
    value: {
      kind: "commitment_change",
      order_line_id: orderId,
      old_quantity: "9007199254.123456",
      new_quantity: "9007199254.123455",
      unit: "件",
      old_due: "2026-12-01",
      new_due: "2026-12-02",
      cancel: false,
      reason: "客户缩量变更",
      source,
      state: "pending",
      impacts: [
        {
          object_type: "work_order",
          object_id: workOrderId,
          quantity: "0.100001",
          unit: "件",
          decision: null,
          evidence: null,
        },
      ],
    },
    relations: [],
    evidence: [],
    history: [],
  };
  return {
    [orderId]: order,
    [workOrderId]: work(workOrderId, "MES-WO-22", "0.100001"),
    [unallocatedId]: work(unallocatedId, "MES-WO-23", "0.000002"),
    [demandId]: demand,
    [changeId]: change,
  };
}
function installBusinessFacts(
  actions: ProjectDetail["allowed_actions"],
  facts = businessFixtures(),
) {
  const prior = vi.mocked(fetch).getMockImplementation()!;
  const p = {
    ...project,
    unit: { code: "件", scale: 6 },
    quantity: "9007199254.123456",
    allowed_actions: actions,
  };
  vi.mocked(fetch).mockImplementation(async (u, i) => {
    const url = new URL(String(u), location.origin);
    if (url.pathname.endsWith("/projects")) return response({ items: [p] });
    if (url.pathname.endsWith("/projects/" + project.id)) return response(p);
    if (url.pathname.includes("/objects/")) {
      const [kind, id] = url.pathname.split("/objects/")[1].split("/");
      if (id) return response(facts[id]);
      const items = Object.values(facts)
        .filter((d) => d.summary.kind === kind)
        .map((d) => d.summary);
      return response({ items, total: items.length, limit: 50, offset: 0 });
    }
    if (url.pathname.endsWith("/commands")) {
      const body = JSON.parse(String(i?.body));
      requests.push({ url: String(u), body });
      return response({
        operation_id: body.operation_id,
        project_id: project.id,
        project_version: 4,
        object_type:
          body.action === "order.change" ? "commitment_change" : "order_line",
        object_id: body.action === "order.change" ? changeId : orderId,
        exchange_id: null,
        replayed: false,
      });
    }
    return prior(u, i);
  });
  return facts;
}
it("submits the actual named formal order form with API-selected demand and exact decimal DTO", async () => {
  installBusinessFacts(["order.register"]);
  await mount();
  await click("制造项目");
  await click("相机项目");
  await click("登记正式订单");
  await field("订单依据需求", demandId);
  await field("订单数量", "9007199254.123456");
  await field("订单交期", "2026-12-01");
  await field("来源业务编号", "ERP-NEW-ORDER");
  await field("来源凭据", "签署订单");
  await click("保存订单");
  expect(
    requests.find((r) => r.body?.action === "order.register")?.body,
  ).toMatchObject({
    action: "order.register",
    expected_version: 3,
    demand_id: demandId,
    quantity: "9007199254.123456",
    unit: "件",
    due_date: "2026-12-01",
    source: {
      object_type: "order_line",
      external_id: "ERP-NEW-ORDER",
      mode: "manual",
      evidence: "签署订单",
    },
  });
  expect(host.textContent).toContain("原始承诺数量");
});
it("previews exact current to proposed commitments and allocated/registered work orders before submitting", async () => {
  installBusinessFacts(["order.change"]);
  await mount();
  await click("制造项目");
  await click("相机项目");
  await click("变更订单承诺");
  await field("变更订单", orderId);
  await field("变更后数量", "9007199254.123455");
  await field("变更后交期", "2026-12-02");
  await flush();
  expect(host.textContent).toContain(
    "9007199254.123456 → 9007199254.123455 件",
  );
  const preview = host.querySelector('[aria-label="承诺变更影响预览"]');
  expect(preview?.textContent).toContain("已分配合计：0.100001 件");
  expect(preview?.textContent).toContain("变更来源须沿用 ERP · ERP-ORDER-21，来源版本须大于 1");
  expect(preview?.textContent).toContain("MES-WO-22");
  expect(preview?.textContent).toContain("0.100001");
  expect(preview?.textContent).toContain("MES-WO-23");
  expect(preview?.textContent).toContain("0.000002");
  await field("取消订单", "true");
  expect(preview?.textContent).toContain("9007199254.123456 → 0 件");
  expect(preview?.textContent).toContain("取消时变更后数量仍须填写当前数量 9007199254.123456，作为撤销依据；实际承诺为 0");
  await field("取消订单", "false");
  await field("变更原因", "客户缩量");
  await field("来源系统", "ERP");
  await field("来源业务编号", "ERP-ORDER-21");
  await field("来源版本", "2");
  await field("来源凭据", "客户变更邮件");
  await click("保存承诺变更");
  expect(
    requests.find((r) => r.body?.action === "order.change")?.body,
  ).toMatchObject({
    order_line_id: orderId,
    new_quantity: "9007199254.123455",
    new_due_date: "2026-12-02",
    cancel: false,
    reason: "客户缩量",
    source: { object_type: "order_line", system: "ERP", external_id: "ERP-ORDER-21", version: 2 },
  });
});
it("submits cancellation with the original quantity as evidence and the next order source revision", async () => {
  installBusinessFacts(["order.change"]);
  await mount();
  await click("制造项目");
  await click("相机项目");
  await click("变更订单承诺");
  await field("变更订单", orderId);
  await field("变更后数量", "9007199254.123456");
  await field("变更后交期", "2026-12-01");
  await field("取消订单", "true");
  await field("变更原因", "客户取消");
  await field("来源系统", "ERP");
  await field("来源业务编号", "ERP-ORDER-21");
  await field("来源版本", "2");
  await field("来源凭据", "客户取消通知");
  await flush();
  await click("保存承诺变更");
  expect(requests.find((r) => r.body?.action === "order.change")?.body).toMatchObject({
    order_line_id: orderId,
    new_quantity: "9007199254.123456",
    cancel: true,
    source: { object_type: "order_line", system: "ERP", external_id: "ERP-ORDER-21", version: 2 },
  });
});
it.each([
  { hint: true, allowed: true, show: true },
  { hint: false, allowed: true, show: false },
  { hint: true, allowed: false, show: false },
])(
  "uses server contextual action metadata and live permission %j",
  async ({ hint, allowed, show }) => {
    const facts = businessFixtures();
    facts[changeId].summary.next_actions = hint ? ["order.resolve_change"] : [];
    const state = hint && allowed ? "applied" : "pending";
    facts[changeId].summary.state = state;
    if (facts[changeId].value.kind === "commitment_change")
      facts[changeId].value.state = state;
    installBusinessFacts(allowed ? ["order.resolve_change"] : [], facts);
    await mount();
    await click("制造项目");
    await click("相机项目");
    await click("客户缩量变更");
    expect(
      [...host.querySelectorAll("button")].some(
        (b) => b.textContent === "处理承诺影响",
      ),
    ).toBe(show);
    if (show) {
      await click("处理承诺影响");
      await flush();
      expect(host.querySelector("form")?.textContent).toContain("MES-WO-22");
      await field("影响处理凭据 1", "保留工单核对单");
      await click("保存影响处理");
      expect(
        requests.find((r) => r.body?.action === "order.resolve_change")?.body,
      ).toMatchObject({
        change_id: changeId,
        dispositions: [
          {
            object_type: "work_order",
            object_id: workOrderId,
            decision: "retain",
            evidence: "保留工单核对单",
          },
        ],
      });
    }
  },
);
it("submits order allocation using actual labeled order and work order selectors", async () => {
  installBusinessFacts(["order.allocate"]);
  await mount();
  await click("制造项目");
  await click("相机项目");
  await click("分配订单工单");
  await field("分配订单", orderId);
  await field("分配工单", workOrderId);
  await field("分配数量", "0.100001");
  await click("保存分配");
  expect(
    requests.find((r) => r.body?.action === "order.allocate")?.body,
  ).toMatchObject({
    order_line_id: orderId,
    work_order_id: workOrderId,
    quantity: "0.100001",
    unit: "件",
    expected_version: 3,
  });
});
it("compares a conflicted member grant without rebasing selected roles or operation", async () => {
  const prior = vi.mocked(fetch).getMockImplementation()!;
  const member = "00000000-0000-4000-8000-000000000010";
  let conflict = false;
  const writes: any[] = [];
  vi.mocked(fetch).mockImplementation(async (u, i) => {
    const url = String(u);
    if (url.endsWith("/members") || url === `/preview/api/v1/manufacturing/workflow/projects/${project.id}/members?user_id=${member}`)
      return response({
        items: conflict
          ? [
              {
                scope: { kind: "project", project_id: project.id },
                user_id: member,
                roles: ["planner"],
                qualifications: [],
                active: true,
              },
            ]
          : [],
      });
    if (url.includes("/members/")) {
      const v = JSON.parse(String(i?.body));
      writes.push(v);
      conflict = true;
      return response(
        {
          code: "VERSION_CONFLICT",
          fields: { current_version: 9 },
          blocking_reasons: [],
        },
        409,
      );
    }
    if (url.endsWith("/projects/" + project.id) && conflict)
      return response({ ...project, version: 9 });
    return prior(u, i);
  });
  await mount({
    bootstrap: { ...bootstrap, configuration_admin: true },
    findSubjects: async () => [{ id: member, displayName: "成员甲" }],
  });
  await click("制造项目");
  await click("相机项目");
  await click("成员授权");
  await field("授权成员", member);
  await act(async () =>
    (host.querySelector('[aria-label="工程"]') as HTMLInputElement).click(),
  );
  await field("授权凭据", "授权依据");
  await click("保存成员授权");
  await click("保留草稿并对照当前资料");
  expect(host.textContent).toContain("职责：计划");
  expect(
    (host.querySelector('[aria-label="工程"]') as HTMLInputElement).checked,
  ).toBe(true);
  await click("保存成员授权");
  expect(writes).toHaveLength(2);
  expect(writes[1]).toEqual(writes[0]);
  expect(writes[1].expected_version).toBe(3);
});
it("compares newer order facts beside an unchanged proposed commitment and retries the original payload", async () => {
  const facts = installBusinessFacts(["order.change"]);
  const prior = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (u, i) => {
    const url = String(u);
    if (url.endsWith("/commands")) {
      requests.push({ url, body: JSON.parse(String(i?.body)) });
      if (facts[orderId].value.kind === "order_line")
        facts[orderId].value.current_quantity = "9007199254.123454";
      return response(
        {
          code: "VERSION_CONFLICT",
          fields: { current_version: 9 },
          blocking_reasons: [],
        },
        409,
      );
    }
    if (url.endsWith("/projects/" + project.id))
      return response({ ...project, version: 9 });
    return prior(u, i);
  });
  await mount();
  await click("制造项目");
  await click("相机项目");
  await click("变更订单承诺");
  await field("变更订单", orderId);
  await field("变更后数量", "9007199254.123455");
  await field("变更后交期", "2026-12-02");
  await field("变更原因", "调整承诺");
  await field("来源系统", "ERP");
  await field("来源业务编号", "ERP-ORDER-21");
  await field("来源版本", "2");
  await field("来源凭据", "客户变更记录");
  await flush();
  await click("保存承诺变更");
  await click("保留草稿并对照当前资料");
  expect(
    host.querySelector('[aria-label="当前服务端资料对照"]')?.textContent,
  ).toContain("9007199254.123454 件");
  expect(
    (host.querySelector('[aria-label="变更后数量"]') as HTMLInputElement).value,
  ).toBe("9007199254.123455");
  await click("保存承诺变更");
  const writes = requests.filter((r) => r.body?.action === "order.change");
  expect(writes).toHaveLength(2);
  expect(writes[1].body).toEqual(writes[0].body);
  expect(writes[1].body.expected_version).toBe(3);
});
it("reads exact scoped impact totals once and labels bounded references without scanning project work orders", async () => {
  const facts = businessFixtures();
  if (facts[orderId].value.kind === "order_line")
    facts[orderId].value.work_order_impact = {
      registered_quantity: "5.300053",
      total: 53,
      shown: 50,
      has_more: true,
      items: Array.from({ length: 50 }, (_, n) => ({
        id: `00000000-0000-4000-8000-${String(100 + n).padStart(12, "0")}`,
        source_system: "MES",
        external_id: `TARGET-${n}`,
        quantity: "0.100001",
        unit: "件",
      })),
    };
  installBusinessFacts(["order.change"], facts);
  await mount();
  await click("制造项目");
  await click("相机项目");
  const prior = vi.mocked(fetch).getMockImplementation()!;
  const previewReads: string[] = [];
  let finish!: (r: Response) => void;
  vi.mocked(fetch).mockImplementation(async (u, i) => {
    const url = String(u);
    previewReads.push(url);
    if (url.endsWith("/objects/order_line/" + orderId))
      return new Promise<Response>((r) => (finish = r));
    if (url.includes("/objects/work_order"))
      throw new Error("Preview must not scan work order pages or details");
    return prior(u, i);
  });
  await click("变更订单承诺");
  await field("变更订单", orderId);
  await flush();
  const save = [...host.querySelectorAll("button")].find(
    (b) => b.textContent === "保存承诺变更",
  )!;
  expect(save.disabled).toBe(true);
  await act(async () => finish(response(facts[orderId])));
  await flush();
  const preview = host.querySelector('[aria-label="承诺变更影响预览"]');
  expect(preview?.textContent).toContain("已登记工单总量：5.300053 件");
  expect(preview?.textContent).toContain("显示 50 / 53 个工单");
  expect(preview?.textContent).toContain(
    "仅展示部分业务编号；上述总量包含全部工单",
  );
  expect(preview?.querySelectorAll("tbody tr")).toHaveLength(50);
  expect(save.disabled).toBe(false);
  expect(previewReads).toEqual([
    expect.stringContaining("/objects/order_line/" + orderId),
  ]);
});
