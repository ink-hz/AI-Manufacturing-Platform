import { act, useState } from "react";
import { createRoot, Root } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { HandbookReader } from "./HandbookReader";
import type { MountOptions } from "./types";
import { TaskEditor } from "./projects/TaskEditor";
import { ProjectDetail } from "./projects/ProjectDetail";
import { createApi } from "./api";
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
    (b) =>
      (b.getAttribute("aria-label") || b.textContent?.trim()) === text &&
      !b.closest("[hidden]"),
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
// Test the shared reader directly; retired product navigation is deliberately absent.
function ReaderHarness({options}: {options:MountOptions}) {
  const [visible,setVisible]=useState(false), [target,setTarget]=useState<{stage?:string;serial:number}>({serial:0});
  return <><button onClick={()=>{setTarget(t=>({serial:t.serial+1}));setVisible(true);}}>制造手册</button>
    <button onClick={()=>setVisible(false)}>工作台</button>
    <button onClick={()=>{setTarget(t=>({stage:'S2',serial:t.serial+1}));setVisible(true);}}>打开 S2 手册</button>
    <HandbookReader options={options} visible={visible} target={target} onBack={()=>setVisible(false)} onLegacy={()=>{}}/>
  </>;
}
async function mount(extra = {}) {
  await act(async()=>root.render(<ReaderHarness options={{apiBase:'/api',csrfToken:'csrf',readOnly:false,renderMarkdown,...extra}}/>));
  await flush();
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

it("follows named hashes even when outline IDs override the renderer heading slugs", async () => {
  await mount();
  const scrollToHeading = vi.fn();
  renderMarkdown.mockImplementationOnce(
    (element: HTMLElement, options: any) => {
      const heading = document.createElement("h2");
      heading.id = options.headingIds[3];
      heading.textContent = "命名标题";
      heading.scrollIntoView = scrollToHeading;
      const link = document.createElement("a");
      link.href = "#命名标题";
      link.textContent = "章节内定位";
      element.replaceChildren(heading, link);
      return { unmount: vi.fn() };
    },
  );
  await click("制造手册");
  expect(renderMarkdown.mock.calls.at(-1)[1].headingIds).toEqual({
    1: "mf-chapter-0",
    3: "mf-chapter-1",
    5: "mf-chapter-2",
  });
  const link = host.querySelector(".mf-article a")!;
  const event = new MouseEvent("click", { bubbles: true, cancelable: true });
  await act(async () => link.dispatchEvent(event));
  expect(event.defaultPrevented).toBe(true);
  expect(scrollToHeading).toHaveBeenCalledWith({ block: "start" });
});

it("retains the renderer on outline navigation and rejects an older document after switching documents", async () => {
  await mount();
  await click("制造手册");
  const first = retires.at(-1);
  await click("5. S1 需求");
  expect(first).not.toHaveBeenCalled();
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
  expect(first).toHaveBeenCalledTimes(1);
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

it("maps the workflow handbook backlink and prevents broken unpublished relative reference navigation", async () => {
  await mount();
  renderMarkdown.mockImplementation((element: HTMLElement) => {
    const backlink = document.createElement("a");
    backlink.href = "../manufacturing-system-handbook.md";
    backlink.textContent = "系统学习手册";
    const reference = document.createElement("a");
    reference.href =
      "../../knowledge/01-foundations/01-manufacturing-process.md";
    reference.textContent = "制造过程知识";
    const external = document.createElement("a");
    external.href = "https://example.com/source";
    external.textContent = "外部来源";
    element.replaceChildren(backlink, reference, external);
    return { unmount: () => element.replaceChildren() };
  });
  await click("制造手册");
  await click("工作流总览");
  const reference = [...host.querySelectorAll(".mf-article a")].find(
    (a) => a.textContent === "制造过程知识",
  )!;
  const broken = new MouseEvent("click", { bubbles: true, cancelable: true });
  await act(async () => reference.dispatchEvent(broken));
  expect(broken.defaultPrevented).toBe(true);
  expect(host.textContent).toContain("尚未纳入本次发布");
  const before = requests.filter((r) =>
    r.path.includes("document=handbook"),
  ).length;
  const backlink = [...host.querySelectorAll(".mf-article a")].find(
    (a) => a.textContent === "系统学习手册",
  )!;
  const back = new MouseEvent("click", { bubbles: true, cancelable: true });
  await act(async () => backlink.dispatchEvent(back));
  await flush();
  expect(back.defaultPrevented).toBe(true);
  expect(
    requests.filter((r) => r.path.includes("document=handbook")),
  ).toHaveLength(before + 1);
  const external = host.querySelector('.mf-article a[href^="https:"]')!;
  let policyPreserved = false;
  const prevent = (e: Event) => {
    policyPreserved = !e.defaultPrevented;
    e.preventDefault();
  };
  host.addEventListener("click", prevent);
  await act(async () =>
    external.dispatchEvent(
      new MouseEvent("click", { bubbles: true, cancelable: true }),
    ),
  );
  host.removeEventListener("click", prevent);
  expect(policyPreserved).toBe(true);
});

it.each([
  ["initial", 200],
  ["initial", 503],
  ["stage save", 200],
  ["stage save", 503],
  ["retry", 200],
  ["retry", 503],
] as const)(
  "retires a late %s detail response (%s) after an independent task save",
  async (source, status) => {
    const api = createApi({
      apiBase: "/api",
      csrfToken: "csrf",
      readOnly: false,
    });
    const original = vi.mocked(fetch).getMockImplementation()!;
    let holdNext = source === "initial",
      failNext = false,
      release!: () => void;
    const pending = new Promise<void>((resolve) => (release = resolve));
    const held = vi.fn();
    vi.mocked(fetch).mockImplementation(async (...args) => {
      if (String(args[0]) === "/api/projects/p1" && args[1]?.method === "GET") {
        if (failNext) {
          failNext = false;
          return response({}, 503);
        }
        if (holdNext) {
          holdNext = false;
          const snapshot = await original(...args);
          held();
          await pending;
          return status === 200 ? snapshot : response({}, status);
        }
      }
      return original(...args);
    });
    try {
      await act(async () =>
        root.render(
          <ProjectDetail
            api={api}
            draftEpoch={0}
            id="p1"
            initial={structuredClone(detail)}
            catalog={catalog}
            readOnly={false}
            onDirty={vi.fn()}
            onChanged={vi.fn()}
            onBack={vi.fn()}
            onHandbook={vi.fn()}
            onLegacy={vi.fn()}
            requestLeave={(action) => action()}
          />,
        ),
      );
      await flush();
      if (source === "stage save") {
        holdNext = true;
        await click("开始阶段");
      } else if (source === "retry") {
        failNext = true;
        await click("开始阶段");
        expect(host.querySelector('[role="alert"]')).not.toBeNull();
        holdNext = true;
        await click("重试读取项目");
      }
      expect(held).toHaveBeenCalledTimes(1);
      await click("新建事项");
      await field("事项标题", "并行保存后必须保留");
      await click("创建事项");
      expect(host.querySelector(".mf-task strong")?.textContent).toBe(
        "并行保存后必须保留",
      );
      expect(host.querySelector('[aria-label="事项标题"]')).toBeNull();
      release();
      await flush();
      expect(detail.tasks).toHaveLength(1);
      expect(requests.filter((r) => r.method === "POST")).toHaveLength(1);
      expect(host.querySelector(".mf-task strong")?.textContent).toBe(
        "并行保存后必须保留",
      );
      expect(host.querySelector('[role="alert"]')).toBeNull();
      expect(host.textContent).not.toContain("正在读取项目");
      expect(button("新建事项").disabled).toBe(false);
    } finally {
      release();
      api.dispose();
    }
  },
);

it("never replays a committed task creation when its refresh callback rejects", async () => {
  const api = createApi({
    apiBase: "/api",
    csrfToken: "csrf",
    readOnly: false,
  });
  const saved = vi.fn().mockRejectedValue(new Error("读取失败"));
  const closed = vi.fn();
  try {
    await act(async () =>
      root.render(
        <TaskEditor
          api={api}
          projectId="p1"
          stageId="S1"
          stages={detail.stages}
          readOnly={false}
          onDirty={vi.fn()}
          onSaved={saved}
          onCancel={closed}
          onReload={vi.fn()}
        />,
      ),
    );
    await field("事项标题", "已经提交的事项");
    await click("创建事项");
    expect(host.querySelector('[aria-label="事项标题"]')).toBeNull();
    expect(host.textContent).toContain("事项已保存");
    expect(host.textContent).not.toContain("尚未保存");
    await click("重试读取项目");
    expect(requests.filter((r) => r.method === "POST")).toHaveLength(1);
    expect(saved).toHaveBeenCalledTimes(2);
    saved.mockResolvedValue(undefined);
    await click("重试读取项目");
    expect(closed).toHaveBeenCalledTimes(1);
    expect(requests.filter((r) => r.method === "POST")).toHaveLength(1);
  } finally {
    api.dispose();
  }
});


it("renders the complete handbook through its end and keeps the same renderer when navigating the outline", async () => {
  await mount();
  const scrolls = new Map<string, ReturnType<typeof vi.fn>>();
  renderMarkdown.mockImplementation((element: HTMLElement, options: any) => {
    element.textContent = options.markdown;
    options.markdown.split("\n").forEach((line: string, index: number) => {
      const match = /^(#{1,2})\s+(.+)$/.exec(line);
      if (!match) return;
      const heading = document.createElement(`h${match[1].length}`);
      heading.id = options.headingIds?.[index + 1] || `unmapped-${index + 1}`;
      heading.textContent = match[2];
      const scroll = vi.fn();
      heading.scrollIntoView = scroll;
      scrolls.set(match[2], scroll);
      element.append(heading);
    });
    const unmount = vi.fn();
    retires.push(unmount);
    return { unmount };
  });
  await click("制造手册");
  const complete =
    "# 手册\n介绍\n## 5. S1 需求\n阶段内容\n## 6. S2 工程\n工程内容";
  expect(renderMarkdown.mock.calls.at(-1)[1].markdown).toBe(complete);
  const count = renderMarkdown.mock.calls.length;
  const handle = retires.at(-1);
  await click("6. S2 工程");
  expect(renderMarkdown).toHaveBeenCalledTimes(count);
  expect(handle).not.toHaveBeenCalled();
  expect(scrolls.get("6. S2 工程")).toHaveBeenCalledWith({ block: "start" });
  expect(host.querySelector(".mf-article")?.textContent).toContain("介绍");
  expect(host.querySelector(".mf-article")?.textContent).toContain("阶段内容");
  expect(host.querySelector(".mf-article")?.textContent).toContain("工程内容");
  await click("6. S2 工程");
  expect(scrolls.get("6. S2 工程")).toHaveBeenCalledTimes(2);
  const body = host.querySelector<HTMLElement>(".mf-book-body")!;
  body.scrollTop = 480;
  await click("返回工作内容");
  await click("制造手册");
  expect(host.querySelector<HTMLElement>(".mf-book-body")?.scrollTop).toBe(480);
  expect(scrolls.get("6. S2 工程")).not.toHaveBeenCalled();
});


it("waits for the shared renderer to insert the target heading while retaining the entire stage-linked document", async () => {
  await mount();
  const scroll = vi.fn();
  let insert!: () => void;
  renderMarkdown.mockImplementation((element: HTMLElement, options: any) => {
    insert = () => {
      element.textContent = options.markdown;
      const heading = document.createElement("h2");
      heading.id = options.headingIds?.[5] || "unmapped";
      heading.textContent = "6. S2 工程";
      heading.scrollIntoView = (options) => {
        scroll(options);
        element.parentElement!.scrollTop = 50;
      };
      element.append(heading);
    };
    return { unmount: vi.fn() };
  });
  await click("打开 S2 手册");
  expect(renderMarkdown.mock.calls.at(-1)[1].markdown).toContain(
    "# 手册\n介绍",
  );
  expect(renderMarkdown.mock.calls.at(-1)[1].markdown).toContain("阶段内容");
  expect(scroll).not.toHaveBeenCalled();
  await act(async () => insert());
  await flush();
  expect(scroll).toHaveBeenCalledWith({ block: "start" });
  host.querySelector<HTMLElement>(".mf-book-body")!.scrollTop = 111;
  await click("工作流总览");
  await act(async () => insert());
  await click("系统手册");
  await act(async () => insert());
  expect(host.querySelector<HTMLElement>(".mf-book-body")!.scrollTop).toBe(111);
  expect(scroll).toHaveBeenCalledTimes(1);
  await click("返回工作内容");
  await click("打开 S2 手册");
  await act(async () => insert());
  expect(scroll).toHaveBeenCalledTimes(2);
});


it("preserves independent document positions with asynchronous renderer commits", async () => {
  await mount();
  let insert!: () => void;
  renderMarkdown.mockImplementation((element: HTMLElement, options: any) => {
    let active = true;
    insert = () => {
      if (!active) return;
      const heading = document.createElement("h1");
      heading.id = options.headingIds[1];
      heading.textContent = options.markdown;
      element.append(heading);
    };
    return {
      unmount() {
        active = false;
        element.replaceChildren();
      },
    };
  });
  await click("制造手册");
  await act(async () => insert());
  host.querySelector<HTMLElement>(".mf-book-body")!.scrollTop = 111;
  await click("工作流总览");
  await act(async () => insert());
  const workflowStart =
    host.querySelector<HTMLElement>(".mf-book-body")!.scrollTop;
  host.querySelector<HTMLElement>(".mf-book-body")!.scrollTop = 222;
  await click("系统手册");
  await act(async () => insert());
  expect(workflowStart).toBe(0);
  expect(host.querySelector<HTMLElement>(".mf-book-body")!.scrollTop).toBe(111);
  expect(renderMarkdown).toHaveBeenCalledTimes(3);
});


it("retires an unfinished stage jump when opening the general handbook", async () => {
  await mount();
  const scroll = vi.fn();
  let insert!: () => void;
  renderMarkdown.mockImplementation((element: HTMLElement, options: any) => {
    insert = () => {
      const heading = document.createElement("h2");
      heading.id = options.headingIds[5];
      heading.textContent = "6. S2 工程";
      heading.scrollIntoView = scroll;
      element.append(heading);
    };
    return { unmount: vi.fn() };
  });
  await click("打开 S2 手册");
  await click("返回工作内容");
  await click("制造手册");
  await act(async () => insert());
  expect(scroll).not.toHaveBeenCalled();
});
