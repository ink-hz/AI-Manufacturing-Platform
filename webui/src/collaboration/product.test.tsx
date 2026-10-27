import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import { readFileSync } from "node:fs";
import { App } from "../App";
const catalog = JSON.parse(
  readFileSync("../src/manufacturing_platform/catalog.json", "utf8"),
);
let host: HTMLDivElement,
  root: Root,
  calls: { url: string; body: any; method: string }[],
  systems: any[],
  authorities: any[],
  packages: any[],
  handoffs: any[],
  readiness: any[],
  failure: string,
  dirty: ReturnType<typeof vi.fn<(value: boolean) => void>>;
const project = {
  id: "p1",
  name: "试产项目",
  code: "MF-1",
  line_id: "cameras",
  line_name: "相机",
  group_id: "internal",
  owner: "工程师",
  product: "P1",
  customer: "产品部",
  due_date: null,
  target_quantity: null,
  summary: "",
  archived: false,
  version: 1,
  status: "active",
  current_stage_id: "S1",
  current_stage_name: "需求",
  completed_stages: 0,
  total_stages: 9,
  open_tasks: 0,
};
const pkg = (status = "verified", id = "pk1", revision = 1) => ({
  id,
  version: 3,
  title: "生产依据",
  product_ref: "P1",
  scope: "首批",
  provider: "工程",
  owner: "工程师",
  customer_version: "",
  internal_version: "A",
  approval_party: "",
  approval_status: "unknown",
  approval_evidence: "",
  items: [
    {
      id: "bom",
      kind: "mbom",
      title: "制造清单",
      source_system_id: null,
      source_name: "人工台账",
      source_ref: "BOM-1",
      revision: "A",
      evidence: "DOC-1",
      owner: "工程师",
      status: "verified",
      reason: "",
    },
  ],
  project_id: "p1",
  family_id: "f1",
  revision,
  status,
  supersedes_id: null,
});
const check = () => ({
  id: "r1",
  version: 1,
  title: "首批开工",
  package_id: "pk1",
  package_revision: 1,
  work_order_ref: "WO1",
  scope: "首批",
  planned_use_date: "2026-11-01",
  required: true,
  owner: "工程师",
  status: "pending",
  superseded_by: null,
  items: [
    {
      id: "version",
      kind: "version",
      label: "版本核对",
      required: true,
      owner: "",
      due_date: null,
      status: "pending",
      evidence: "",
      source_ref: "",
      source_system_id: null,
      reason: "",
      valid_until: null,
      package_item_id: "bom",
      supply_mode: "unknown",
      first_article_result: "unknown",
    },
  ],
});
async function flush() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}
function btn(text: string) {
  const el = [...host.querySelectorAll("button")].find(
    (b) => b.textContent?.trim() === text && !b.closest("[hidden]"),
  );
  if (!el) throw Error("Missing button " + text);
  return el;
}
async function click(text: string) {
  for (let n = 0; n < 25; n++) {
    if (
      [...host.querySelectorAll("button")].some(
        (b) => b.textContent?.trim() === text && !b.closest("[hidden]"),
      )
    )
      break;
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
  }
  await act(async () => btn(text).click());
  await flush();
}
async function field(label: string, value: string) {
  const el = host.querySelector(`[aria-label="${label}"]`) as HTMLInputElement;
  expect(el, label).not.toBeNull();
  await act(async () => {
    const proto =
      el.tagName === "SELECT"
        ? HTMLSelectElement.prototype
        : el.tagName === "TEXTAREA"
          ? HTMLTextAreaElement.prototype
          : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
async function mount(readOnly = false) {
  await act(async () =>
    root.render(
      <App
        options={{
          apiBase: "/api",
          csrfToken: "csrf",
          readOnly,
          onDirtyChange: dirty,
        }}
      />,
    ),
  );
  await flush();
}
async function openTab(tab: string) {
  await click("试产项目");
  await click(tab);
  await flush();
}
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  calls = [];
  systems = [];
  authorities = [];
  packages = [];
  handoffs = [];
  readiness = [];
  failure = "";
  dirty = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: any = {}) => {
      const method = init.method || "GET",
        body = init.body ? JSON.parse(init.body) : null;
      calls.push({ url, body, method });
      if (failure === url) {
        failure = "";
        return new Response("{}", { status: 409 });
      }
      let result: any = {};
      if (url.endsWith("/catalog")) result = { ...catalog, can_edit: true };
      else if (url.endsWith("/dashboard"))
        result = {
          counts: {
            active_projects: 1,
            blocked_projects: 0,
            due_soon: 0,
            open_tasks: 0,
            pending_confirmations: 0,
          },
          projects: [project],
          attention: [],
          blockers: [],
          activity: [],
          control_attention: [],
        };
      else if (url.includes("/handbook?"))
        result = {
          title: "制造手册",
          markdown: "# 制造手册",
          updated_at: "2026-10-27T08:00:00Z",
          source_path: "handbook",
          release: "test",
          sha256: "test",
        };
      else if (url.endsWith("/project-tasks")) result = { items: [] };
      else if (url.endsWith("/projects")) result = { items: [project] };
      else if (url.endsWith("/projects/p1"))
        result = {
          project,
          stages: catalog.stages.map((s: any) => ({
            ...s,
            status: "todo",
            owner: "",
            due_date: null,
            blocker: "",
            practice: "",
            participants: [],
            handoffs: [],
            systems: [],
            version: 1,
          })),
          tasks: [],
          activity: [],
        };
      else if (url.endsWith("/collaboration"))
        result = { systems, authorities, handoffs, attention: [] };
      else if (url.endsWith("/controls"))
        result = { packages, handoffs, readiness, events: [] };
      else if (method !== "GET") {
        result = { ...body, id: "new-" + calls.length, version: 1 };
        if (url.endsWith("/systems")) systems.push(result);
        else if (url.includes("/systems/")) {
          const row = systems.find((s) => url.endsWith(s.id));
          Object.assign(row, body, { version: row.version + 1 });
          result = row;
        } else if (url.endsWith("/authorities")) authorities.push(result);
        else if (url.endsWith("/actions")) {
          const old = packages.find((p) => url.includes("/" + p.id + "/"));
          if (body.action === "revise") {
            result = {
              ...old,
              id: "revision-2",
              revision: old.revision + 1,
              version: 1,
              status: "draft",
            };
            packages.push(result);
          } else {
            old.status =
              body.action === "submit"
                ? "review"
                : body.action === "verify"
                  ? "verified"
                  : body.action === "return"
                    ? "returned"
                    : "invalid";
            old.version++;
            result = old;
          }
        } else if (url.includes("/handoffs/")) {
          const old = handoffs.find((h) => url.endsWith(h.id));
          old.status =
            body.action === "send"
              ? "sent"
              : body.action === "receive"
                ? "received"
                : body.action === "return"
                  ? "returned"
                  : "cancelled";
          old.version++;
          result = old;
        } else if (url.endsWith("/packages")) {
          result = {
            ...result,
            status: "draft",
            revision: 1,
            family_id: "new",
          };
          packages.push(result);
        } else if (url.endsWith("/handoffs")) {
          result = { ...result, status: "draft", package_revision: 1 };
          handoffs.push(result);
        } else if (url.endsWith("/readiness")) {
          result = { ...result, status: "pending", package_revision: 2 };
          readiness.push(result);
        }
      }
      return new Response(JSON.stringify(result), { status: 200 });
    }),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
it("opens system collaboration lazily and creates a real line-scoped system", async () => {
  await mount();
  expect(calls.some((c) => c.url.endsWith("/collaboration"))).toBe(false);
  await click("系统协同");
  await click("登记系统");
  await field("系统名称", "ERP");
  await field("系统类别", "业务系统");
  await click("保存系统");
  const write = calls.find((c) => c.url.endsWith("/systems") && c.body);
  expect(write?.body).toMatchObject({
    name: "ERP",
    kind: "业务系统",
    line_ids: ["cameras"],
    operation_id: expect.any(String),
  });
  expect(host.textContent).toContain("ERP");
});
it("preserves failed system payload and UUID, freezes editing, then refreshes without reposting", async () => {
  await mount();
  await click("系统协同");
  await click("登记系统");
  await field("系统名称", "ERP");
  await field("系统类别", "业务系统");
  failure = "/api/systems";
  await click("保存系统");
  expect(
    (host.querySelector('[aria-label="系统名称"]') as HTMLInputElement)
      .disabled ||
      host.querySelector('[aria-label="系统名称"]')?.closest("fieldset")
        ?.disabled,
  ).toBe(true);
  await click("保存系统");
  const writes = calls.filter((c) => c.url === "/api/systems");
  expect(writes).toHaveLength(2);
  expect(writes[0].body).toEqual(writes[1].body);
  expect(host.textContent).toContain("ERP");
});
it("edits and retires a system using CAS and editable fields only", async () => {
  systems = [
    {
      id: "s1",
      version: 2,
      name: "ERP",
      kind: "ERP",
      line_ids: ["cameras"],
      business_owner: "业务",
      it_owner: "IT",
      usage: "unverified",
      method: "api",
      notes: "",
      active: true,
      updated_by: "server",
    },
  ];
  await mount();
  await click("系统协同");
  await click("ERP");
  await field("业务负责人", "新负责人");
  await click("保存系统");
  expect(calls.find((c) => c.method === "PATCH")?.body).toMatchObject({
    expected_version: 2,
    business_owner: "新负责人",
  });
  expect(calls.find((c) => c.method === "PATCH")?.body).not.toHaveProperty(
    "updated_by",
  );
  await click("ERP");
  await click("停用系统");
  await click("保存系统");
  expect(calls.filter((c) => c.method === "PATCH").at(-1)?.body.active).toBe(
    false,
  );
});
it("creates a single active object authority and keeps conflict drafts", async () => {
  systems = [
    {
      id: "s1",
      version: 1,
      name: "ERP",
      kind: "ERP",
      line_ids: ["cameras"],
      active: true,
    },
  ];
  await mount();
  await click("系统协同");
  await click("主数据责任");
  await click("新增责任约定");
  await field("录入入口", "ERP物料");
  await field("责任人", "张工");
  failure = "/api/authorities";
  await click("保存责任约定");
  expect(host.textContent).toContain("草稿已保留");
  await click("保存责任约定");
  const writes = calls.filter((c) => c.url === "/api/authorities");
  expect(writes[0].body).toEqual(writes[1].body);
  expect(writes[0].body).toMatchObject({
    system_id: "s1",
    line_id: "cameras",
    object_type: "material",
  });
});
it("creates package content through a focused item editor without metadata", async () => {
  await mount();
  await openTab("工程资料");
  await click("新建资料包");
  await field("资料包名称", "首批依据");
  await field("产品型号", "P1");
  await field("适用范围", "首批");
  await click("资料项目");
  await field("资料名称", "制造清单");
  await click("保存资料包");
  const body = calls.find((c) => c.url.endsWith("/packages") && c.body)?.body;
  expect(body).toMatchObject({
    title: "首批依据",
    items: [expect.objectContaining({ title: "制造清单" })],
  });
  expect(body).not.toHaveProperty("status");
});
it("submits, verifies and revises a package with version-bound actions", async () => {
  packages = [pkg("draft")];
  await mount();
  await openTab("工程资料");
  await click("生产依据");
  await click("提交人工核对");
  await click("确认操作");
  expect(calls.find((c) => c.url.endsWith("/actions"))?.body).toMatchObject({
    action: "submit",
    expected_version: 3,
  });
});
it("creates independent handoffs only from verified revisions", async () => {
  packages = [pkg(), pkg("draft", "draft")];
  await mount();
  await openTab("交接记录");
  await click("新建交接");
  await field("交出方", "工程");
  await field("接收方", "生产");
  await field("交接负责人", "王工");
  await click("登记交接");
  const body = calls.find((c) => c.url.endsWith("/handoffs") && c.body)?.body;
  expect(body).toMatchObject({
    package_id: "pk1",
    from_party: "工程",
    to_party: "生产",
  });
  expect(body).not.toHaveProperty("status");
});
it("registers receipt with explicit revision, evidence and timezone-qualified instant", async () => {
  packages = [pkg()];
  handoffs = [
    {
      id: "h1",
      version: 2,
      package_id: "pk1",
      package_revision: 1,
      from_party: "工程",
      to_party: "生产",
      owner: "王工",
      status: "sent",
      code: "HO-1",
      method: "file",
      evidence: "",
      occurred_at: null,
    },
  ];
  await mount();
  await openTab("交接记录");
  await click("生产");
  await click("登记接收");
  await field("接收版本", "1");
  await field("操作凭据", "收据-1");
  await field("业务发生时间", "2026-10-27T12:30");
  await click("确认操作");
  const body = calls.find(
    (c) => c.method === "PATCH" && c.url.endsWith("/h1"),
  )?.body;
  expect(body).toMatchObject({
    action: "receive",
    received_revision: 1,
    evidence: "收据-1",
  });
  expect(body.occurred_at).toMatch(/Z$/);
});
it("creates fixed-scope readiness with selected applicability", async () => {
  packages = [pkg()];
  await mount();
  await openTab("生产准备");
  await click("新建准备核对");
  await field("核对名称", "首批核对");
  await field("工单编号", "WO1");
  await field("执行范围", "首批");
  await field("计划使用日期", "2026-11-01");
  await field("核对负责人", "王工");
  await click("建立核对");
  expect(
    calls.find((c) => c.url.endsWith("/readiness") && c.body)?.body,
  ).toMatchObject({
    package_id: "pk1",
    work_order_ref: "WO1",
    scope: "首批",
    items: [expect.objectContaining({ kind: "version", status: "pending" })],
  });
});
it("updates readiness evidence independently and creates a linked issue", async () => {
  packages = [pkg()];
  readiness = [check()];
  await mount();
  await openTab("生产准备");
  await click("首批开工");
  await click("版本核对");
  await field("核对状态", "blocked");
  await field("核对原因", "缺少版本证明");
  await click("保存核对");
  expect(calls.find((c) => c.method === "PUT")?.body.items[0]).toMatchObject({
    status: "blocked",
    reason: "缺少版本证明",
  });
  await click("首批开工");
  await click("版本核对");
  await click("登记关联问题");
  await field("问题标题", "补齐证明");
  await click("创建关联问题");
  expect(calls.find((c) => c.url.endsWith("/issues"))?.body).toMatchObject({
    item_id: "version",
    title: "补齐证明",
  });
});
it("replaces readiness using a newer verified family revision and pending assertions", async () => {
  packages = [pkg(), pkg("verified", "pk2", 2)];
  readiness = [check()];
  await mount();
  await openTab("生产准备");
  await click("首批开工");
  await click("替代此核对");
  await click("建立替代核对");
  const body = calls.find((c) => c.url.endsWith("/readiness") && c.body)?.body;
  expect(body).toMatchObject({
    package_id: "pk2",
    supersedes_id: "r1",
    supersedes_version: 1,
    scope: "首批",
    work_order_ref: "WO1",
    items: [expect.objectContaining({ id: "version", status: "pending" })],
  });
});
it("keeps superseded checks readable and forbids editing/issues", async () => {
  packages = [pkg()];
  readiness = [{ ...check(), superseded_by: "r2" }];
  await mount();
  await openTab("生产准备");
  await click("首批开工");
  expect(host.textContent).toContain("已被替代");
  await click("版本核对");
  expect(
    [...host.querySelectorAll("button")].some(
      (b) => b.textContent === "保存核对",
    ),
  ).toBe(false);
  expect(
    [...host.querySelectorAll("button")].some(
      (b) => b.textContent === "登记关联问题",
    ),
  ).toBe(false);
});
it("retains a dirty package draft while consulting the continuous handbook", async () => {
  await mount();
  await openTab("工程资料");
  await click("新建资料包");
  await field("资料包名称", "未完成草稿");
  expect(dirty).toHaveBeenLastCalledWith(true);
  await click("制造手册");
  await click("返回工作内容");
  expect(
    (host.querySelector('[aria-label="资料包名称"]') as HTMLInputElement).value,
  ).toBe("未完成草稿");
});
it("disables mutations for read-only users", async () => {
  await mount(true);
  await click("系统协同");
  expect(btn("登记系统").disabled).toBe(true);
  expect(calls.filter((c) => c.method !== "GET")).toHaveLength(0);
});
it("never repeats a successful create when the following collection read fails", async () => {
  await mount();
  await click("系统协同");
  await click("登记系统");
  await field("系统名称", "ERP");
  await field("系统类别", "ERP");
  failure = "/api/collaboration";
  await click("保存系统");
  expect(host.textContent).toContain("已保存");
  expect(host.textContent).toContain("刷新失败");
  expect(calls.filter((c) => c.url === "/api/systems")).toHaveLength(1);
  await click("重新读取已保存结果");
  expect(calls.filter((c) => c.url === "/api/systems")).toHaveLength(1);
  expect(host.textContent).toContain("ERP");
});
it("verifies and revises frozen package records without overwriting original content", async () => {
  packages = [pkg("review")];
  await mount();
  await openTab("工程资料");
  await click("生产依据");
  await click("确认人工核对");
  await click("确认操作");
  expect(calls.find((c) => c.url.endsWith("/actions"))?.body.action).toBe(
    "verify",
  );
  await click("生产依据");
  await click("创建新修订");
  await click("确认操作");
  expect(
    calls.filter((c) => c.url.endsWith("/actions")).at(-1)?.body,
  ).toMatchObject({ action: "revise", expected_version: 4 });
  expect(calls.some((c) => c.method === "PUT")).toBe(false);
});
it("registers independent send and return actions with a required reason", async () => {
  packages = [pkg()];
  handoffs = [
    {
      id: "h1",
      version: 1,
      package_id: "pk1",
      package_revision: 1,
      from_party: "工程",
      to_party: "生产",
      owner: "王工",
      status: "draft",
      code: "HO-1",
      method: "file",
      evidence: "",
      occurred_at: null,
    },
  ];
  await mount();
  await openTab("交接记录");
  await click("生产");
  await click("登记交出");
  await click("确认操作");
  expect(calls.find((c) => c.method === "PATCH")?.body.action).toBe("send");
  await click("生产");
  await click("登记退回");
  await field("操作原因", "版本不符");
  await click("确认操作");
  expect(calls.filter((c) => c.method === "PATCH").at(-1)?.body).toMatchObject({
    action: "return",
    reason: "版本不符",
    expected_version: 2,
  });
});
it("changes a responsibility agreement and explicitly deactivates the prior entry", async () => {
  systems = [
    {
      id: "s1",
      version: 1,
      name: "ERP",
      kind: "ERP",
      line_ids: ["cameras"],
      active: true,
    },
  ];
  authorities = [
    {
      id: "a1",
      version: 4,
      line_id: "cameras",
      object_type: "material",
      system_id: "s1",
      entry_point: "旧入口",
      owner: "张工",
      notes: "",
      active: true,
    },
  ];
  await mount();
  await click("系统协同");
  await click("主数据责任");
  await click("物料 · 旧入口");
  await field("录入入口", "新入口");
  await click("保存责任约定");
  expect(calls.find((c) => c.url.endsWith("/a1"))?.body).toMatchObject({
    entry_point: "新入口",
    expected_version: 4,
  });
});
it("discards a readiness draft before replacement and preserves the requested destination", async () => {
  packages = [pkg(), pkg("verified", "pk2", 2)];
  readiness = [check()];
  await mount();
  await openTab("生产准备");
  await click("首批开工");
  await field("核对原因", "尚未保存");
  await click("替代此核对");
  expect(host.querySelector('[role="dialog"]')).not.toBeNull();
  await click("放弃并离开");
  expect(btn("建立替代核对")).toBeDefined();
  await click("建立替代核对");
  expect(
    calls.find((c) => c.url.endsWith("/readiness") && c.body)?.body
      .supersedes_id,
  ).toBe("r1");
});
it("discards package content before a requested submit action rather than losing the action", async () => {
  packages = [pkg("draft")];
  await mount();
  await openTab("工程资料");
  await click("生产依据");
  await field("资料包名称", "未保存名称");
  await click("提交人工核对");
  await click("放弃并离开");
  await click("确认操作");
  expect(calls.find((c) => c.url.endsWith("/actions"))?.body.action).toBe(
    "submit",
  );
  expect(calls.some((c) => c.method === "PUT")).toBe(false);
});
it("opens the exact historical readiness source from an issue in the task center", async () => {
  packages = [pkg()];
  readiness = [{ ...check(), superseded_by: "r2" }];
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation(async (input, init) =>
    String(input).endsWith("/project-tasks")
      ? new Response(
          JSON.stringify({
            items: [
              {
                id: "t1",
                project_id: "p1",
                project_name: "试产项目",
                project_code: "MF-1",
                line_id: "cameras",
                line_name: "相机",
                stage_id: "S5",
                stage_name: "准备",
                kind: "issue",
                priority: "normal",
                status: "todo",
                title: "历史核对问题",
                owner: "王工",
                source: { type: "readiness", id: "r1", item_id: "version" },
              },
            ],
          }),
        )
      : original(input, init),
  );
  await mount();
  await click("事项");
  await click("查看来源准备项");
  await flush();
  expect(host.textContent).toContain("已被替代");
  expect(host.textContent).toContain("版本核对");
});
it("allows only HTTP(S) evidence links and renders opaque IDs as text", async () => {
  packages = [
    {
      ...pkg(),
      items: [
        {
          ...pkg().items[0],
          source_ref: "javascript:alert(1)",
          evidence: "https://example.com/proof",
        },
      ],
    },
  ];
  await mount();
  await openTab("工程资料");
  await click("生产依据");
  await click("资料项目");
  expect(host.querySelector('a[href^="javascript:"]')).toBeNull();
  const link = host.querySelector('a[href="https://example.com/proof"]');
  expect(link?.getAttribute("rel")).toContain("noopener");
  expect(link?.getAttribute("rel")).toContain("noreferrer");
});
it("retains newer collection results when an older read completes later", async () => {
  await mount();
  await click("系统协同");
  const original = vi.mocked(fetch).getMockImplementation()!;
  const pending: ((r: Response) => void)[] = [];
  vi.mocked(fetch).mockImplementation((input, init) =>
    String(input).endsWith("/collaboration")
      ? new Promise((resolve) => pending.push(resolve))
      : original(input, init),
  );
  await click("刷新协同记录");
  await click("刷新协同记录");
  expect(pending).toHaveLength(2);
  await act(async () =>
    pending[1](
      new Response(
        JSON.stringify({
          systems: [
            {
              id: "new",
              name: "新结果",
              kind: "ERP",
              line_ids: ["cameras"],
              usage: "unverified",
              method: "manual",
              active: true,
            },
          ],
          authorities: [],
          handoffs: [],
          attention: [],
        }),
      ),
    ),
  );
  await flush();
  await act(async () =>
    pending[0](
      new Response(
        JSON.stringify({
          systems: [
            {
              id: "old",
              name: "过期结果",
              kind: "ERP",
              line_ids: ["cameras"],
              usage: "unverified",
              method: "manual",
              active: true,
            },
          ],
          authorities: [],
          handoffs: [],
          attention: [],
        }),
      ),
    ),
  );
  await flush();
  expect(host.textContent).toContain("新结果");
  expect(host.textContent).not.toContain("过期结果");
});
it("reloads the current version after an explicit conflict-draft discard", async () => {
  systems = [
    {
      id: "s1",
      version: 2,
      name: "ERP",
      kind: "ERP",
      line_ids: ["cameras"],
      business_owner: "业务",
      it_owner: "",
      usage: "unverified",
      method: "manual",
      notes: "",
      active: true,
    },
  ];
  await mount();
  await click("系统协同");
  await click("ERP");
  await field("业务负责人", "我的草稿");
  failure = "/api/systems/s1";
  await click("保存系统");
  systems = [{ ...systems[0], version: 3, business_owner: "其他人的更新" }];
  await click("放弃草稿并重新读取");
  await click("放弃并离开");
  await click("ERP");
  expect(
    (host.querySelector('[aria-label="业务负责人"]') as HTMLInputElement).value,
  ).toBe("其他人的更新");
  await field("业务负责人", "协调后的负责人");
  await click("保存系统");
  expect(
    calls.filter((c) => c.method === "PATCH").at(-1)?.body.expected_version,
  ).toBe(3);
});
it("binds the version check to a verified package item at creation and keeps that binding fixed", async () => {
  packages = [pkg()];
  await mount();
  await openTab("生产准备");
  await click("新建准备核对");
  await field("核对名称", "首批核对");
  await field("工单编号", "WO1");
  await field("执行范围", "首批");
  await field("计划使用日期", "2026-11-01");
  await field("核对负责人", "王工");
  await click("建立核对");
  expect(
    calls.find((c) => c.url.endsWith("/readiness") && c.body)?.body.items[0]
      .package_item_id,
  ).toBe("bom");
  await click("首批核对");
  expect(host.querySelector('select[aria-label="对应冻结资料项"]')).toBeNull();
  expect(host.textContent).toContain("制造清单");
});
it("requires independent evidence and validity for an equipment check without changing fixed selection", async () => {
  packages = [pkg()];
  readiness = [
    {
      ...check(),
      items: [
        {
          ...check().items[0],
          id: "equipment",
          kind: "equipment",
          label: "设备准备",
          package_item_id: null,
        },
      ],
    },
  ];
  await mount();
  await openTab("生产准备");
  await click("首批开工");
  await field("核对状态", "verified");
  await field("检查负责人", "设备工程师");
  await field("核对来源", "EQ-1");
  await field("核对凭据", "CAL-1");
  await field("设备有效期至", "2026-11-10");
  await click("保存核对");
  expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({
    expected_version: 1,
    items: [
      expect.objectContaining({
        id: "equipment",
        kind: "equipment",
        required: true,
        status: "verified",
        owner: "设备工程师",
        source_ref: "EQ-1",
        evidence: "CAL-1",
        valid_until: "2026-11-10",
        package_item_id: null,
      }),
    ],
  });
});
it("records an actual first-article result instead of treating a plan as completion", async () => {
  packages = [pkg()];
  readiness = [
    {
      ...check(),
      items: [
        {
          ...check().items[0],
          id: "first",
          kind: "first_article",
          label: "首件确认",
          package_item_id: null,
        },
      ],
    },
  ];
  await mount();
  await openTab("生产准备");
  await click("首批开工");
  await field("首件实际结果", "passed");
  await field("核对状态", "verified");
  await field("检查负责人", "质检");
  await field("核对来源", "FA-1");
  await field("核对凭据", "REPORT-1");
  await click("保存核对");
  expect(
    calls.find((c) => c.method === "PUT")?.body.items[0].first_article_result,
  ).toBe("passed");
});
it("a deliberate reset permits editing and creates a new operation identity", async () => {
  await mount();
  await click("系统协同");
  await click("登记系统");
  await field("系统名称", "ERP");
  await field("系统类别", "ERP");
  failure = "/api/systems";
  await click("保存系统");
  await click("重置本次请求并继续编辑");
  await field("系统名称", "MES");
  await click("保存系统");
  const writes = calls.filter((c) => c.url === "/api/systems");
  expect(writes[0].body.operation_id).not.toBe(writes[1].body.operation_id);
  expect(writes[1].body.name).toBe("MES");
});
it("opens the exact handoff from the cross-project collaboration view", async () => {
  packages = [pkg()];
  handoffs = [
    {
      id: "h1",
      version: 1,
      project_id: "p1",
      project_name: "试产项目",
      package_id: "pk1",
      package_revision: 1,
      from_party: "工程",
      to_party: "生产",
      owner: "王工",
      status: "sent",
      code: "HO-1",
      method: "file",
      evidence: "收据",
      occurred_at: null,
    },
  ];
  await mount();
  await click("系统协同");
  await click("跨项目交接");
  await click("试产项目 · 生产");
  await flush();
  expect(host.textContent).toContain("HO-1");
  expect(host.textContent).toContain("已登记交出");
});
it("selects a real line-scoped source system by name instead of asking for an internal ID", async () => {
  systems = [
    {
      id: "s1",
      version: 1,
      name: "工程ERP",
      kind: "ERP",
      line_ids: ["cameras"],
      active: true,
    },
  ];
  await mount();
  await openTab("工程资料");
  await click("新建资料包");
  await field("资料包名称", "首批依据");
  await click("资料项目");
  await field("资料名称", "制造清单");
  await click("读取可选系统");
  await field("来源系统（可选）", "s1");
  await click("保存资料包");
  expect(
    calls.find((c) => c.url.endsWith("/packages") && c.body)?.body.items[0]
      .source_system_id,
  ).toBe("s1");
});
it("creates an explicitly unbound version check as documented NA immediately", async () => {
  packages = [pkg()];
  await mount();
  await openTab("生产准备");
  await click("新建准备核对");
  await field("核对名称", "无适用版本");
  await field("工单编号", "WO1");
  await field("执行范围", "首批");
  await field("计划使用日期", "2026-11-01");
  await field("核对负责人", "王工");
  await field("对应冻结资料项", "");
  await field("不适用原因", "此范围无该版本资料要求");
  await click("建立核对");
  expect(
    calls.find((c) => c.url.endsWith("/readiness") && c.body)?.body.items[0],
  ).toMatchObject({
    package_item_id: null,
    status: "na",
    reason: "此范围无该版本资料要求",
  });
});
it("blocks a pending replacement when its newer package has no applicable verified item", async () => {
  packages = [
    pkg(),
    {
      ...pkg("verified", "pk2", 2),
      items: [{ ...pkg().items[0], status: "na", reason: "不适用" }],
    },
  ];
  readiness = [check()];
  await mount();
  await openTab("生产准备");
  await click("首批开工");
  await click("替代此核对");
  await click("建立替代核对");
  expect(
    calls.filter((c) => c.url.endsWith("/readiness") && c.body),
  ).toHaveLength(0);
  expect(host.textContent).toContain("替代核对必须选择适用的冻结资料项");
});
