import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import { App } from "../App";
import type { ProjectDetail } from "./types";
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
    String(u).endsWith("/members")
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
it('disables an open project form immediately when the host becomes read-only',async()=>{const admin={...bootstrap,configuration_admin:true};await mount({bootstrap:admin});await click('新建项目');await field('项目名称','未提交');await mount({bootstrap:admin,readOnly:true});const save=[...host.querySelectorAll('button')].find(b=>b.textContent==='创建制造项目');expect(save?.disabled).toBe(true);expect(host.querySelector('[aria-label="项目名称"]')?.matches(':disabled')).toBe(true);});
