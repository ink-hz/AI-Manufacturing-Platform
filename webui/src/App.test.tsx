import { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { App } from "./App";
const catalog = JSON.parse(
  readFileSync("../src/manufacturing_platform/catalog.json", "utf8"),
);
let host: HTMLDivElement,
  root: Root,
  detail: any,
  projects: any[],
  requests: any[],
  fail: number,
  dirty: any,
  renderMarkdown: any,
  retires: any[];
const summary = () => ({
  id: "p1",
  code: "MF-001",
  name: "深度相机试产",
  line_id: "cameras",
  line_name: "自研相机",
  group_id: "internal",
  owner: "王工",
  product: "D1",
  customer: "产品部",
  due_date: "2026-11-01",
  target_quantity: 100,
  summary: "交付首批样机",
  archived: false,
  version: 1,
  status: "planned",
  current_stage_id: "S1",
  current_stage_name: "需求确认",
  completed_stages: 0,
  total_stages: 9,
  open_tasks: 0,
  updated_at: "2026-10-27T08:00:00Z",
});
const response = (v: any, status = 200) =>
  new Response(JSON.stringify(v), { status });
async function flush() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}
function button(text: string) {
  const b = [...host.querySelectorAll("button")].find(
    (b) => b.textContent?.trim() === text && !b.closest("[hidden]"),
  );
  if (!b) throw new Error(`Missing ${text}: ${host.textContent}`);
  return b;
}
async function click(text: string) {
  await act(async () => button(text).click());
  await flush();
}
async function field(label: string, value: string) {
  const e = host.querySelector(`[aria-label="${label}"]`) as HTMLInputElement;
  expect(e, label).not.toBeNull();
  await act(async () => {
    const proto =
      e.tagName === "SELECT"
        ? HTMLSelectElement.prototype
        : e.tagName === "TEXTAREA"
          ? HTMLTextAreaElement.prototype
          : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(e, value);
    e.dispatchEvent(new Event("input", { bubbles: true }));
    e.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
async function mount(extra = {}) {
  await act(async () =>
    root.render(
      <App
        options={{
          apiBase: "/api",
          csrfToken: "csrf",
          readOnly: false,
          onDirtyChange: dirty,
          renderMarkdown,
          ...extra,
        }}
      />,
    ),
  );
  await flush();
}
async function open() {
  await click("深度相机试产");
}
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  projects = [summary()];
  detail = {
    project: projects[0],
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
    activity: [
      {
        id: "a",
        actor: "王工",
        summary: "创建制造项目",
        created_at: "2026-10-27T08:00:00Z",
        stage_id: null,
      },
    ],
  };
  requests = [];
  fail = 0;
  dirty = vi.fn();
  retires = [];
  renderMarkdown = vi.fn((el: HTMLElement, { markdown }: any) => {
    el.textContent = `已渲染 ${markdown}`;
    const a = document.createElement("a");
    a.href = "workflows/manufacturing-process-overview.md";
    a.textContent = "流程总览";
    el.append(a);
    const unmount = vi.fn(() => el.replaceChildren());
    retires.push(unmount);
    return { unmount };
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const path = url.replace("/api", "");
      const method = init.method || "GET";
      const body = init.body ? JSON.parse(init.body as string) : undefined;
      requests.push({ path, method, body });
      if (method !== "GET" && fail) {
        const status = fail;
        fail = 0;
        return response({}, status);
      }
      if (path === "/catalog")
        return response({ ...catalog, can_edit: true, release: "v2" });
      if (path === "/dashboard")
        return response({
          counts: {
            active_projects: 7,
            blocked_projects: 2,
            due_soon: 3,
            open_tasks: 11,
            pending_confirmations: 1,
          },
          projects,
          attention: detail.tasks.map((t: any) => ({
            ...t,
            project_name: detail.project.name,
            stage_name: "需求确认",
          })),
          blockers: [],
          activity: detail.activity.map((a: any) => ({
            ...a,
            project_name: detail.project.name,
            project_id: "p1",
          })),
        });
      if (path === "/projects" && method === "GET")
        return response({ items: projects });
      if (path === "/project-tasks")
        return response({
          items: detail.tasks.map((t: any) => ({
            ...t,
            project_name: detail.project.name,
            line_id: "cameras",
            line_name: "自研相机",
            stage_name: "需求确认",
          })),
        });
      if (path.startsWith("/handbook"))
        return response({
          title: path.includes("workflow") ? "流程总览" : "制造手册",
          markdown:
            "# 手册\n介绍\n## 5. S1 需求\n阶段内容\n## 6. S2 工程\n工程内容",
          updated_at: "2026-10-26T00:00:00Z",
          source_path: "docs/manufacturing-system-handbook.md",
          release: "v2",
        });
      if (path === "/projects" && method === "POST") {
        detail = { ...detail, project: { ...summary(), ...body } };
        projects = [detail.project];
        return response(detail);
      }
      if (method === "PUT") {
        const id = path.split("/").at(-1);
        const i = detail.stages.findIndex((s: any) => s.id === id);
        detail.stages[i] = {
          ...detail.stages[i],
          ...body,
          version: detail.stages[i].version + 1,
        };
        return response(detail.stages[i]);
      }
      if (path === "/projects/p1" && method === "PATCH") {
        detail.project = {
          ...detail.project,
          ...body,
          version: detail.project.version + 1,
        };
        return response(detail);
      }
      if (path === "/projects/p1/tasks" && method === "POST") {
        const t = {
          ...body,
          id: "t1",
          project_id: "p1",
          status: "todo",
          version: 1,
        };
        detail.tasks.push(t);
        return response(t);
      }
      if (method === "PATCH") {
        detail.tasks[0] = {
          ...detail.tasks[0],
          ...body,
          version: detail.tasks[0].version + 1,
        };
        return response(detail.tasks[0]);
      }
      return response(detail);
    }),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
it("opens on real projects with server counts, compact progress, and factual activity", async () => {
  await mount();
  expect(host.textContent).toContain("在管项目");
  expect(host.textContent).toContain("7");
  expect(host.textContent).toContain("王工");
  expect(host.textContent).toContain("创建制造项目");
  expect(host.querySelector(".mf-home-grid")).not.toBeNull();
  expect(host.querySelector(".mf-progress")?.children).toHaveLength(9);
  expect(host.querySelector(".mf-stages")).toBeNull();
});
it("creates a project with immutable retry identity then enters detail", async () => {
  projects = [];
  await mount();
  await click("新建项目");
  await field("项目名称", "OEM 首批交付");
  await field("项目负责人", "李工");
  fail = 503;
  await click("创建项目");
  expect(host.textContent).toContain("尚未保存");
  await click("创建项目");
  const writes = requests.filter((r) => r.method === "POST");
  expect(writes[0].body).toEqual(writes[1].body);
  expect(writes[0].body.operation_id).toMatch(/^[\da-f-]{36}$/);
  expect(host.querySelector(".mf-phase-rail")).not.toBeNull();
  expect(host.textContent).toContain("OEM 首批交付");
});
it("keeps filters and shows actual project cards in board", async () => {
  await mount();
  await click("制造项目");
  await field("搜索项目", "不存在");
  expect(host.textContent).toContain("没有符合筛选的项目");
  await click("看板");
  expect(host.querySelector(".mf-board")).not.toBeNull();
  await field("搜索项目", "深度");
  expect(host.querySelectorAll(".mf-project-card")).toHaveLength(1);
  await click("制造手册");
  await click("制造项目");
  expect(
    (host.querySelector('[aria-label="搜索项目"]') as HTMLInputElement).value,
  ).toBe("深度");
  expect(button("看板").getAttribute("aria-pressed")).toBe("true");
});
it("saves stage facts and relations together, retains conflict draft and reopens completion", async () => {
  await mount();
  await open();
  await click("编辑阶段");
  await field("阶段说明", "等待客户确认");
  await field("阶段状态", "blocked");
  await field("受阻原因", "BOM 版本待确认");
  await click("添加参与方");
  await field("参与方 1 名称", "工程");
  fail = 409;
  await click("保存阶段");
  expect(host.textContent).toContain("内容已更新");
  expect(
    (host.querySelector('[aria-label="阶段说明"]') as HTMLTextAreaElement)
      .value,
  ).toBe("等待客户确认");
  expect(dirty).toHaveBeenLastCalledWith(true);
  await click("保留草稿");
  await click("保存阶段");
  expect(detail.stages[0]).toMatchObject({
    status: "blocked",
    blocker: "BOM 版本待确认",
    participants: [{ name: "工程" }],
  });
  await click("完成阶段");
  expect(detail.stages[0].status).toBe("done");
  await click("重新打开阶段");
  expect(detail.stages[0].status).toBe("doing");
});
it("creates assigned dated priority confirmations and completes/reopens", async () => {
  await mount();
  await open();
  await click("新建事项");
  await field("事项标题", "确认客户样机");
  await field("事项类型", "confirmation");
  await field("事项负责人", "陈工");
  await field("事项日期", "2026-11-03");
  await field("事项优先级", "urgent");
  await field("事项说明", "核对验收依据");
  fail = 503;
  await click("创建事项");
  await click("创建事项");
  const posts = requests.filter(
    (r) => r.path.endsWith("/tasks") && r.method === "POST",
  );
  expect(posts[0].body).toEqual(posts[1].body);
  expect(detail.tasks[0]).toMatchObject({
    kind: "confirmation",
    owner: "陈工",
    due_date: "2026-11-03",
    priority: "urgent",
  });
  await click("完成事项");
  expect(detail.tasks[0].status).toBe("done");
  await click("重新打开事项");
  expect(detail.tasks[0].status).toBe("todo");
});
it("retains the dirty stage while reading and guards leaving", async () => {
  await mount();
  await open();
  await click("编辑阶段");
  await field("阶段说明", "还未保存");
  await click("了解这个阶段");
  expect(renderMarkdown.mock.calls.at(-1)[1].markdown).toContain("## 5. S1");
  expect(host.textContent).toContain("2026-10-26");
  await click("返回工作内容");
  expect(
    (host.querySelector('[aria-label="阶段说明"]') as HTMLTextAreaElement)
      .value,
  ).toBe("还未保存");
  expect(dirty).toHaveBeenLastCalledWith(true);
  await click("返回项目列表");
  expect(host.querySelector('[role="dialog"]')).not.toBeNull();
  await click("继续编辑");
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(true);
});
it("uses renderer handles and fixed workflow links, with no raw markdown fallback", async () => {
  await mount();
  await click("制造手册");
  expect(renderMarkdown).toHaveBeenCalled();
  await act(async () =>
    (host.querySelector(".mf-article a") as HTMLAnchorElement).click(),
  );
  await flush();
  expect(requests.some((r) => r.path.includes("document=workflow"))).toBe(true);
  expect(retires.some((fn) => fn.mock.calls.length)).toBe(true);
  await click("工作台");
  expect(retires.at(-1)).toHaveBeenCalledTimes(1);
  await mount({ renderMarkdown: undefined });
  await click("制造手册");
  expect(host.textContent).toContain("阅读组件暂不可用");
  expect(host.querySelector(".mf-article")?.textContent || "").not.toContain(
    "##",
  );
});
it("archives via core CAS and disables all mutations when read-only", async () => {
  await mount();
  await open();
  await click("归档项目");
  expect(requests.find((r) => r.method === "PATCH").body).toEqual({
    expected_version: 1,
    archived: true,
  });
  await mount({ readOnly: true });
  expect(button("恢复项目").disabled).toBe(true);
  expect(button("编辑阶段").disabled).toBe(true);
  expect(button("新建事项").disabled).toBe(true);
  expect(button("新建项目").disabled).toBe(true);
});
it("uses the actual handbook workflow link and retires late unauthorized document responses on leaving", async () => {
  const auth = vi.fn();
  await mount({ onAuthError: auth });
  const original = vi.mocked(fetch).getMockImplementation()!;
  let resolve!: (r: Response) => void;
  let signal: AbortSignal | undefined;
  vi.mocked(fetch).mockImplementation((...args) => {
    if (String(args[0]).includes("/handbook")) {
      signal = args[1]?.signal as AbortSignal;
      return new Promise((r) => {
        resolve = r;
      });
    }
    return original(...args);
  });
  await click("制造手册");
  await click("工作台");
  expect(signal?.aborted).toBe(true);
  await act(async () => resolve(response({}, 403)));
  await flush();
  expect(auth).not.toHaveBeenCalled();
  expect(host.textContent).not.toContain("无权访问");
});
it("preserves S2 selection, filters and a project form draft when consulting the handbook", async () => {
  await mount();
  await open();
  await click("S2工程准备未开始");
  await click("编辑阶段");
  await field("阶段说明", "工程阶段草稿");
  await click("了解这个阶段");
  expect(renderMarkdown.mock.calls.at(-1)[1].markdown).toContain("S2 工程");
  await click("返回工作内容");
  expect(
    (host.querySelector('[aria-label="阶段说明"]') as HTMLTextAreaElement)
      .value,
  ).toBe("工程阶段草稿");
  expect(host.querySelector('[aria-current="step"]')?.textContent).toContain(
    "S2",
  );
  await click("返回项目列表");
  await click("放弃并离开");
  await click("新建项目");
  await field("项目名称", "保存中的相机");
  await click("制造手册");
  await click("返回工作内容");
  expect(
    (host.querySelector('[aria-label="项目名称"]') as HTMLInputElement).value,
  ).toBe("保存中的相机");
  expect(dirty).toHaveBeenLastCalledWith(true);
});
it("filters real items by type/status/business and locates their project stage", async () => {
  detail.tasks = [
    {
      id: "t1",
      project_id: "p1",
      stage_id: "S2",
      title: "核对测试版本",
      kind: "issue",
      owner: "陈工",
      priority: "high",
      status: "blocked",
      due_date: "2026-11-01",
      notes: "版本缺失",
      version: 1,
    },
  ];
  await mount();
  await click("事项");
  expect(host.textContent).toContain("核对测试版本");
  await field("筛选事项类型", "confirmation");
  expect(host.textContent).toContain("没有符合筛选的事项");
  await field("筛选事项类型", "issue");
  await click("核对测试版本");
  expect(host.querySelector('[aria-current="step"]')?.textContent).toContain(
    "S2",
  );
  expect(host.querySelector(".mf-task-highlight")?.textContent).toContain(
    "核对测试版本",
  );
  await click("编辑事项");
  await field("事项类型", "task");
  await field("事项状态", "doing");
  await field("事项日期", "");
  await field("事项优先级", "normal");
  await click("保存事项");
  expect(detail.tasks[0]).toMatchObject({
    kind: "task",
    status: "doing",
    due_date: null,
    priority: "normal",
  });
});
it("keeps creation content locked after ambiguous failure until explicit cancellation", async () => {
  await mount();
  await click("新建项目");
  await field("项目名称", "第一项");
  await field("项目负责人", "王工");
  fail = 503;
  await click("创建项目");
  expect(
    (host.querySelector('[aria-label="项目名称"]') as HTMLInputElement).closest(
      "fieldset",
    )?.disabled,
  ).toBe(true);
  await click("取消本次创建");
  await click("新建项目");
  await field("项目名称", "第二项");
  await field("项目负责人", "李工");
  await click("创建项目");
  const posts = requests.filter((r) => r.method === "POST");
  expect(posts[0].body.operation_id).not.toBe(posts[1].body.operation_id);
  expect(detail.project.name).toBe("第二项");
});
it("preserves independent stage drafts when adding an item without forcing loss", async () => {
  await mount();
  await open();
  await click("编辑阶段");
  await field("阶段说明", "阶段草稿");
  await click("新建事项");
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  await field("事项标题", "独立保存事项");
  await click("创建事项");
  expect(dirty).toHaveBeenLastCalledWith(true);
  expect(
    (host.querySelector('[aria-label="阶段说明"]') as HTMLTextAreaElement)
      .value,
  ).toBe("阶段草稿");
  expect(detail.stages[0].practice).toBe("");
});
it("does not navigate on a project save response after its form was explicitly discarded", async () => {
  await mount();
  await click("新建项目");
  await field("项目名称", "晚到的响应");
  await field("项目负责人", "王工");
  const original = vi.mocked(fetch).getMockImplementation()!;
  let finish!: () => void;
  const wait = new Promise<void>((r) => {
    finish = r;
  });
  vi.mocked(fetch).mockImplementation(async (...args) => {
    const result = await original(...args);
    if (args[1]?.method === "POST") await wait;
    return result;
  });
  await click("创建项目");
  await click("工作台");
  await click("放弃并离开");
  await act(async () => finish());
  await flush();
  expect(host.querySelector(".mf-phase-rail")).toBeNull();
  expect(host.querySelector(".mf-home-grid")).not.toBeNull();
  await click("制造项目");
  expect(host.querySelector(".mf-project-table")).not.toBeNull();
  expect(host.querySelector(".mf-phase-rail")).toBeNull();
});
it("preserves the renderer heading slugs and follows named hashes inside only the current article", async () => {
  await mount();
  const scrollToHeading = vi.fn();
  renderMarkdown.mockImplementationOnce(
    (element: HTMLElement, options: any) => {
      const heading = document.createElement("h2");
      heading.id = "named-heading";
      heading.textContent = "命名标题";
      heading.scrollIntoView = scrollToHeading;
      const link = document.createElement("a");
      link.href = "#named-heading";
      link.textContent = "章节内定位";
      element.replaceChildren(heading, link);
      return { unmount: vi.fn() };
    },
  );
  await click("制造手册");
  expect(renderMarkdown.mock.calls.at(-1)[1].headingIds).toBeUndefined();
  const link = host.querySelector(".mf-article a")!;
  const event = new MouseEvent("click", { bubbles: true, cancelable: true });
  await act(async () => link.dispatchEvent(event));
  expect(event.defaultPrevented).toBe(true);
  expect(scrollToHeading).toHaveBeenCalledWith({ block: "start" });
});
it("retires each chapter renderer and rejects an older document after switching documents", async () => {
  await mount();
  await click("制造手册");
  const first = retires.at(-1);
  await click("5. S1 需求");
  expect(first).toHaveBeenCalledTimes(1);
  const old = renderMarkdown.mock.calls.length;
  const original = vi.mocked(fetch).getMockImplementation()!;
  let finish!: (r: Response) => void;
  vi.mocked(fetch).mockImplementation((...args) =>
    String(args[0]).includes("document=workflow")
      ? new Promise((r) => {
          finish = r;
        })
      : original(...args),
  );
  await click("工作流总览");
  await click("系统手册");
  await act(async () =>
    finish(
      response({
        title: "迟到的旧资料",
        markdown: "# 过期正文",
        updated_at: "old",
        source_path: "old",
        release: "v2",
      }),
    ),
  );
  await flush();
  expect(host.textContent).not.toContain("迟到的旧资料");
  expect(renderMarkdown.mock.calls.length).toBeGreaterThan(old);
  expect(renderMarkdown.mock.calls.at(-1)[1].markdown).not.toContain(
    "过期正文",
  );
});
it("retains a failed task edit and core CAS draft until explicitly reloaded", async () => {
  detail.tasks = [
    {
      id: "t1",
      project_id: "p1",
      stage_id: "S1",
      title: "原事项",
      kind: "issue",
      owner: "王工",
      due_date: null,
      priority: "high",
      notes: "原说明",
      status: "todo",
      version: 4,
    },
  ];
  await mount();
  await open();
  await click("编辑事项");
  await field("事项标题", "本地事项草稿");
  fail = 409;
  await click("保存事项");
  expect(
    (host.querySelector('[aria-label="事项标题"]') as HTMLInputElement).value,
  ).toBe("本地事项草稿");
  expect(
    requests.find((r) => r.path.endsWith("/tasks/t1") && r.method === "PATCH")
      .body.expected_version,
  ).toBe(4);
  await click("保留草稿");
  await click("取消事项编辑");
  await click("编辑项目资料");
  await field("项目负责人", "新负责人");
  fail = 409;
  await click("保存项目");
  expect(
    (host.querySelector('[aria-label="项目负责人"]') as HTMLInputElement).value,
  ).toBe("新负责人");
  expect(dirty).toHaveBeenLastCalledWith(true);
  await click("放弃草稿并重新读取");
  await click("放弃并离开");
  expect(host.querySelector('[aria-label="项目负责人"]')).toBeNull();
  expect(host.textContent).toContain("负责人 王工");
});
it("keeps write controls disabled when read-only changes during stage and item editing", async () => {
  await mount();
  await open();
  await click("编辑阶段");
  await click("新建事项");
  await mount({ readOnly: true });
  for (const label of [
    "保存阶段",
    "创建事项",
    "添加参与方",
    "采用参考关系并核对",
    "归档项目",
  ])
    expect(button(label).disabled, label).toBe(true);
  expect(
    (
      host.querySelector('[aria-label="阶段状态"]') as HTMLSelectElement
    ).closest("fieldset")?.disabled,
  ).toBe(true);
  expect(
    (host.querySelector('[aria-label="事项标题"]') as HTMLInputElement).closest(
      "fieldset",
    )?.disabled,
  ).toBe(true);
});
it("preserves a core draft and its original CAS when another child save refreshes a newer server core", async () => {
  await mount();
  await open();
  await click("编辑项目资料");
  await field("项目负责人", "本地责任人");
  await click("新建事项");
  await field("事项标题", "并行登记事项");
  detail.project = { ...detail.project, owner: "另一位操作者", version: 2 };
  await click("创建事项");
  expect(
    (host.querySelector('[aria-label="项目负责人"]') as HTMLInputElement).value,
  ).toBe("本地责任人");
  fail = 409;
  await click("保存项目");
  const patch = requests.find(
    (r) => r.method === "PATCH" && r.path === "/projects/p1",
  );
  expect(patch.body.expected_version).toBe(1);
  expect(dirty).toHaveBeenLastCalledWith(true);
});
it("adopts reference relationships only by explicit action and saves all relation types in one stage CAS", async () => {
  await mount();
  await open();
  expect(detail.stages[0].participants).toEqual([]);
  await click("编辑阶段");
  await click("采用参考关系并核对");
  await click("保存阶段");
  const write = requests.find((r) => r.method === "PUT");
  expect(write.body).toMatchObject({
    expected_version: 1,
    status: "todo",
    owner: "",
    due_date: null,
    blocker: "",
    practice: "",
  });
  expect(write.body.participants).toEqual(
    catalog.stages[0].reference_participants,
  );
  expect(write.body.handoffs).toEqual(catalog.stages[0].reference_handoffs);
  expect(write.body.systems).toEqual(catalog.stages[0].reference_systems);
  expect(host.textContent).toContain("关系登记，尚未验证连接");
  expect(requests.filter((r) => r.method === "PUT")).toHaveLength(1);
});
it("filters project groups, lines, states and archived records identically across list and board", async () => {
  projects.push({
    ...summary(),
    id: "p2",
    name: "客户 OEM 交付",
    line_id: "oem",
    line_name: "OEM 代工代料",
    group_id: "external",
    owner: "李工",
    status: "blocked",
  });
  projects.push({
    ...summary(),
    id: "p3",
    name: "旧项目",
    status: "archived",
    archived: true,
  });
  await mount();
  expect(
    [...host.querySelectorAll(".mf-summary-strip strong")].map(
      (e) => e.textContent,
    ),
  ).toEqual(["7", "2", "3", "11"]);
  await click("制造项目");
  await field("业务归属", "external");
  await field("项目业务线", "oem");
  await field("项目状态", "blocked");
  expect(host.querySelectorAll(".mf-project-row")).toHaveLength(1);
  expect(host.querySelector(".mf-project-row")?.textContent).toContain(
    "客户 OEM 交付",
  );
  await click("看板");
  expect(host.querySelectorAll(".mf-project-card")).toHaveLength(1);
  await field("业务归属", "");
  await field("项目状态", "archived");
  expect(host.querySelectorAll(".mf-project-card")).toHaveLength(1);
  expect(host.querySelector(".mf-project-card")?.textContent).toContain(
    "旧项目",
  );
});
it("requires a real blocker before a stage can be saved as blocked", async () => {
  await mount();
  await open();
  await click("标记受阻");
  expect(button("保存阶段").disabled).toBe(true);
  await click("保存阶段");
  expect(requests.filter((r) => r.method === "PUT")).toHaveLength(0);
  await field("受阻原因", "供应商版本不一致");
  await click("保存阶段");
  expect(detail.stages[0].status).toBe("blocked");
  expect(detail.stages[0].blocker).toBe("供应商版本不一致");
});
it("keeps the same pending item operation across handbook visits and locks duplicate submissions", async () => {
  await mount();
  await open();
  await click("新建事项");
  await field("事项标题", "确认原始依据");
  const original = vi.mocked(fetch).getMockImplementation()!;
  let finish!: () => void;
  const wait = new Promise<void>((r) => {
    finish = r;
  });
  vi.mocked(fetch).mockImplementation(async (...args) => {
    if (args[1]?.method === "POST") {
      await wait;
      return response({}, 503);
    }
    return original(...args);
  });
  const create = button("创建事项");
  await act(async () => {
    create.click();
    create.click();
  });
  expect(create.disabled).toBe(true);
  await act(async () => finish());
  await flush();
  vi.mocked(fetch).mockImplementation(original);
  await click("制造手册");
  await click("返回工作内容");
  await click("创建事项");
  expect(detail.tasks[0].title).toBe("确认原始依据");
  const calls = vi
    .mocked(fetch)
    .mock.calls.filter((c) => c[1]?.method === "POST");
  expect(calls).toHaveLength(2);
  expect(JSON.parse(calls[0][1]!.body as string)).toEqual(
    JSON.parse(calls[1][1]!.body as string),
  );
});
it("scrolls an attention item into view inside its selected project phase", async () => {
  const old = HTMLElement.prototype.scrollIntoView;
  const scroll = vi.fn();
  HTMLElement.prototype.scrollIntoView = scroll;
  try {
    detail.tasks = [
      {
        id: "attention-task",
        project_id: "p1",
        stage_id: "S2",
        title: "待确认的工程版本",
        kind: "confirmation",
        status: "todo",
        priority: "high",
        owner: "王工",
        due_date: null,
        notes: "",
        version: 1,
      },
    ];
    await mount();
    await click("待确认的工程版本");
    expect(host.querySelector('[aria-current="step"]')?.textContent).toContain(
      "S2",
    );
    expect(scroll).toHaveBeenCalledWith({ block: "center" });
  } finally {
    HTMLElement.prototype.scrollIntoView = old;
  }
});
