import { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { App } from "./App";

const catalog = JSON.parse(
  readFileSync("../src/manufacturing_platform/catalog.json", "utf8"),
);
const empty = () => ({
  practice: "",
  participants: [],
  handoffs: [],
  systems: [],
  version: 0,
  updated_at: null,
  updated_by: null,
});
let host: HTMLDivElement,
  root: Root,
  requests: { path: string; method: string; body: any }[],
  saved: any,
  tasks: any[],
  failSave: number,
  failRead: number,
  failTask: number;
let dirty = vi.fn();
const options = () => ({
  apiBase: "/api/v1/manufacturing",
  csrfToken: "token",
  readOnly: false,
  onDirtyChange: dirty,
});
async function flush() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}
function button(text: string) {
  const found = [...host.querySelectorAll("button")].find(
    (b) => b.textContent?.trim() === text,
  );
  if (!found) throw new Error(`Missing button ${text}: ${host.textContent}`);
  return found;
}
async function click(text: string) {
  await act(async () => button(text).click());
  await flush();
}
async function input(label: string, value: string) {
  const el = [...host.querySelectorAll("input,textarea")].find(
    (e) => e.getAttribute("aria-label") === label,
  ) as HTMLInputElement;
  if (!el) throw new Error(`Missing field ${label}`);
  await act(async () => {
    const proto =
      el.tagName === "TEXTAREA"
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
async function mount(extra = {}) {
  await act(async () =>
    root.render(<App options={{ ...options(), ...extra }} />),
  );
  await flush();
}
async function open() {
  await click("01 需求确认 未记录 →");
}
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  requests = [];
  saved = empty();
  tasks = [];
  failSave = 0;
  failRead = 0;
  failTask = 0;
  dirty = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const path = url.replace("/api/v1/manufacturing", "");
      const method = init.method || "GET";
      const body = init.body ? JSON.parse(init.body as string) : undefined;
      requests.push({ path, method, body });
      const response = (data: unknown, status = 200) =>
        new Response(JSON.stringify(data), { status });
      if (path === "/catalog") return response({ ...catalog, can_edit: true });
      const parts = path.split("/");
      const line = catalog.lines.find((l: any) => l.id === parts[2]);
      const stage = catalog.stages.find((s: any) => s.id === parts[4]);
      if (method === "PUT") {
        if (failSave) return response({}, failSave);
        saved = {
          ...body,
          version: saved.version + 1,
          updated_at: "2026-10-27T08:00:00Z",
          updated_by: "王工",
        };
        delete saved.expected_version;
        return response(saved);
      }
      if (method === "POST") {
        if (failTask) {
          failTask--;
          return response({}, 503);
        }
        const t = {
          id: "task1",
          title: body.title,
          completed: false,
          version: 1,
          created_at: "now",
          updated_at: "now",
          updated_by: "王工",
        };
        if (!tasks.length) tasks.push(t);
        return response(t);
      }
      if (method === "PATCH") {
        if (failSave) return response({}, failSave);
        const t = { ...tasks[0], ...body, version: tasks[0].version + 1 };
        tasks = [t];
        return response(t);
      }
      if (stage) {
        if (failRead) return response({}, failRead);
        return response({
          line,
          stage,
          record: parts[2] === "cameras" ? saved : empty(),
          tasks: parts[2] === "cameras" ? tasks : [],
          can_edit: true,
        });
      }
      return response({
        line,
        stages: catalog.stages.map((s: any) => ({
          ...s,
          recorded:
            parts[2] === "cameras" && s.id === "S1" && !!saved.practice.trim(),
          open_tasks:
            s.id === "S1" ? tasks.filter((t) => !t.completed).length : 0,
        })),
        can_edit: true,
      });
    }),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("two-view workbench", () => {
  it("defaults to cameras and switches group/line by stable scope", async () => {
    await mount();
    expect(requests.some((r) => r.path === "/lines/cameras")).toBe(true);
    await click("3D 打印机");
    expect(requests.at(-1)?.path).toBe("/lines/3d-printers");
    await click("外部业务");
    expect(requests.at(-1)?.path).toBe("/lines/oem");
    expect(host.querySelector('[aria-label="业务线"] button')).toBeNull();
    await open();
    expect(host.textContent).toContain("OEM 代工代料");
    expect(host.textContent).toContain("尚未记录");
  });
  it("saves actual practice and relations together, refreshes overview, and clears recorded state", async () => {
    await mount();
    await open();
    await click("编辑");
    await input("现状说明", "部分事实仍待核实");
    const details = host.querySelector(
      'details[data-section="relationships"]',
    ) as HTMLDetailsElement;
    details.open = true;
    await click("添加参与方");
    await input("参与方 1 名称", "奥比工程");
    await input("参与方 1 责任", "核对设计 BOM");
    await click("添加系统");
    await input("系统 1 名称", "现有 ERP");
    expect(host.textContent).toContain("关系登记，尚未验证连接");
    await click("保存");
    expect(saved).toMatchObject({
      practice: "部分事实仍待核实",
      participants: [{ name: "奥比工程", responsibility: "核对设计 BOM" }],
      systems: [{ name: "现有 ERP", method: "unknown" }],
    });
    expect(host.textContent).toContain("王工");
    expect(dirty).toHaveBeenLastCalledWith(false);
    await click("← 返回流程");
    expect(host.textContent).toContain("已记录");
    await click("01 需求确认 已记录 →");
    await click("编辑");
    await input("现状说明", "");
    await click("保存");
    await click("← 返回流程");
    expect(host.textContent).not.toContain("已记录");
  });
  it("retains unsaved practice on save failure and CAS conflict with explicit reload choice", async () => {
    await mount();
    await open();
    await click("编辑");
    await input("现状说明", "本地草稿");
    failSave = 503;
    await click("保存");
    expect(
      (
        host.querySelector(
          'textarea[aria-label="现状说明"]',
        ) as HTMLTextAreaElement
      ).value,
    ).toBe("本地草稿");
    expect(host.textContent).toContain("尚未保存");
    failSave = 409;
    await click("保存");
    expect(host.textContent).toContain("内容已更新");
    expect(host.textContent).toContain("保留草稿");
    await click("保留草稿");
    expect((host.querySelector("textarea") as HTMLTextAreaElement).value).toBe(
      "本地草稿",
    );
    await click("保存");
    await click("放弃草稿并重新读取");
    expect(host.querySelector('textarea[aria-label="现状说明"]')).toBeNull();
  });
  it("protects dirty back navigation, notifies host, and prevents unload", async () => {
    await mount();
    await open();
    await click("编辑");
    await input("现状说明", "草稿");
    expect(dirty).toHaveBeenLastCalledWith(true);
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    await click("← 返回流程");
    expect(host.querySelector('[role="dialog"]')).not.toBeNull();
    await click("继续编辑");
    expect(host.querySelector("textarea")).not.toBeNull();
    await click("← 返回流程");
    await click("放弃并离开");
    expect(host.textContent).toContain("大制造");
    expect(dirty).toHaveBeenLastCalledWith(false);
  });
  it("retries task creation with same UUID and allows edit, completion, reopen", async () => {
    await mount();
    await open();
    await input("新待办", "确认供应商交期");
    failTask = 1;
    await click("添加待办");
    expect(host.textContent).toContain("尚未保存");
    await click("添加待办");
    const bodies = requests
      .filter((r) => r.method === "POST")
      .map((r) => r.body);
    expect(bodies[0].operation_id).toBe(bodies[1].operation_id);
    expect(bodies[0].operation_id).toMatch(/^[0-9a-f-]{36}$/);
    await click("修改待办");
    await input("待办标题", "确认原始交期依据");
    await click("保存待办");
    expect(tasks[0].title).toBe("确认原始交期依据");
    await click("标记完成");
    expect(tasks[0].completed).toBe(true);
    expect(host.textContent).toContain("已完成（1）");
    await click("重新打开");
    expect(tasks[0].completed).toBe(false);
    expect(
      requests.find((r) => r.method === "PATCH")?.body.expected_version,
    ).toBe(1);
  });
  it("keeps old content on read failures and disables writes for read-only", async () => {
    saved = { ...empty(), practice: "已了解的事实", version: 1 };
    await mount({ readOnly: true });
    await click("01 需求确认 已记录 →");
    expect(host.textContent).toContain("已了解的事实");
    expect(button("编辑").disabled).toBe(true);
    expect(button("添加待办").disabled).toBe(true);
    failRead = 503;
    await click("重新读取");
    expect(host.textContent).toContain("已了解的事实");
    expect(host.textContent).toContain("读取失败");
    failRead = 0;
    await click("重试读取");
    expect(host.textContent).toContain("已了解的事实");
  });
  it("clears loaded sensitive content and informs host on auth failure", async () => {
    const onAuthError = vi.fn();
    saved = { ...empty(), practice: "敏感记录", version: 1 };
    await mount({ onAuthError });
    await click("01 需求确认 已记录 →");
    failRead = 403;
    await click("重新读取");
    expect(host.textContent).not.toContain("敏感记录");
    expect(host.textContent).toContain("无权访问");
    expect(onAuthError).toHaveBeenCalledTimes(1);
  });
  it("does not leak persisted scope into another business line", async () => {
    saved = { ...empty(), practice: "相机业务专属", version: 1 };
    await mount();
    await click("01 需求确认 已记录 →");
    await click("← 返回流程");
    await click("3D 打印机");
    await open();
    expect(host.textContent).not.toContain("相机业务专属");
    expect(host.textContent).toContain("尚未记录");
  });
  it("edits and removes all relation types in one draft and cancels without persistence", async () => {
    await mount();
    await open();
    await click("编辑关系");
    await click("添加参与方");
    await input("参与方 1 名称", "研发");
    await click("添加交接资料");
    await input("交接资料 1 资料或数据名", "工程 BOM");
    await input("交接资料 1 版本/依据", "A版，待批准");
    await click("添加系统");
    await input("系统 1 名称", "MES");
    await click("保存现状与关系");
    expect(saved.handoffs[0]).toMatchObject({
      name: "工程 BOM",
      version_reference: "A版，待批准",
    });
    expect(saved.practice).toBe("");
    await click("编辑关系");
    await input("参与方 1 责任", "修改草稿");
    await click("移除系统 1");
    await click("取消");
    expect(saved.systems).toHaveLength(1);
    expect(saved.participants[0].responsibility).toBe("");
    await click("编辑关系");
    await click("移除参与方 1");
    await click("移除交接资料 1");
    await click("移除系统 1");
    await click("保存现状与关系");
    expect(saved.participants).toEqual([]);
    expect(saved.handoffs).toEqual([]);
    expect(saved.systems).toEqual([]);
  });
  it("retains failed task updates and expected_version on conflict", async () => {
    tasks = [{ id: "t1", title: "原始待办", completed: false, version: 4 }];
    await mount();
    await click("01 需求确认 未记录 · 1 项待办 →");
    await click("修改待办");
    await input("待办标题", "需要核对的标题");
    failSave = 409;
    await click("保存待办");
    await click("保留草稿");
    expect(
      (host.querySelector('input[aria-label="待办标题"]') as HTMLInputElement)
        .value,
    ).toBe("需要核对的标题");
    expect(tasks[0].title).toBe("原始待办");
    expect(
      requests.find((r) => r.method === "PATCH")?.body.expected_version,
    ).toBe(4);
  });
  it("saves a draft before leaving and keeps selection and shell scroll position", async () => {
    await mount();
    host.scrollTop = 265;
    await open();
    await click("编辑");
    await input("现状说明", "保存后返回");
    await click("← 返回流程");
    await click("保存并返回");
    expect(saved.practice).toBe("保存后返回");
    expect(host.scrollTop).toBe(265);
    expect(host.querySelector('button[aria-pressed="true"]')?.textContent).toBe(
      "自研相机",
    );
  });
  it("puts conflict choices in keyboard focus and Escape preserves the draft", async () => {
    await mount();
    await open();
    await click("编辑");
    await input("现状说明", "键盘草稿");
    failSave = 409;
    await click("保存");
    const dialog = host.querySelector('[role="dialog"]')!;
    expect(dialog.contains(document.activeElement)).toBe(true);
    await act(async () =>
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      ),
    );
    expect(host.querySelector('[role="dialog"]')).toBeNull();
    expect((host.querySelector("textarea") as HTMLTextAreaElement).value).toBe(
      "键盘草稿",
    );
  });
  it("creates a fresh task operation if a failed title is deliberately changed", async () => {
    await mount();
    await open();
    await input("新待办", "原始标题");
    failTask = 1;
    await click("添加待办");
    await input("新待办", "新标题");
    await click("添加待办");
    const bodies = requests
      .filter((r) => r.method === "POST")
      .map((r) => r.body);
    expect(bodies[0].operation_id).not.toBe(bodies[1].operation_id);
    expect(tasks[0].title).toBe("新标题");
  });

  it("identifies a task save separately while a record draft remains unsaved", async () => {
    await mount();
    await open();
    await click("编辑");
    await input("现状说明", "未保存现状");
    await input("新待办", "单独保存待办");
    await click("添加待办");
    expect(host.textContent).toContain("待办已保存");
    expect(dirty).toHaveBeenLastCalledWith(true);
    expect(saved.practice).toBe("");
    expect((host.querySelector("textarea") as HTMLTextAreaElement).value).toBe(
      "未保存现状",
    );
  });
  it("prevents draft edits while an explicit reload is in flight", async () => {
    await mount();
    await open();
    await click("编辑");
    await input("现状说明", "先核对本地草稿");
    await click("重新读取");
    const original = vi.mocked(fetch).getMockImplementation()!;
    let finish!: () => void;
    const pending = new Promise<void>((resolve) => {
      finish = resolve;
    });
    vi.mocked(fetch).mockImplementation(async (...args) => {
      await pending;
      return original(...args);
    });
    await click("放弃草稿并重新读取");
    expect(
      (
        host.querySelector(
          'textarea[aria-label="现状说明"]',
        ) as HTMLTextAreaElement
      ).disabled,
    ).toBe(true);
    await act(async () => {
      finish();
    });
    await flush();
  });
  it.each(["practice", "relationships", "new task", "task edit"])(
    "confirms retry reads before discarding a %s draft",
    async (kind) => {
      if (kind === "task edit")
        tasks = [{ id: "t1", title: "待核对", completed: false, version: 1 }];
      await mount();
      await click(
        kind === "task edit"
          ? "01 需求确认 未记录 · 1 项待办 →"
          : "01 需求确认 未记录 →",
      );
      failRead = 503;
      await click("重新读取");
      failRead = 0;
      if (kind === "practice") {
        await click("编辑");
        await input("现状说明", "本地现状");
      }
      if (kind === "relationships") {
        await click("编辑关系");
        await click("添加参与方");
        await input("参与方 1 名称", "本地参与方");
      }
      if (kind === "new task") {
        await input("新待办", "待确认标题");
        failTask = 1;
        await click("添加待办");
      }
      if (kind === "task edit") {
        await click("修改待办");
        await input("待办标题", "本地标题");
      }
      const readCount = requests.filter((r) => r.method === "GET").length;
      await click("重试读取");
      expect(requests.filter((r) => r.method === "GET")).toHaveLength(
        readCount,
      );
      expect(host.querySelector('[role="dialog"]')).not.toBeNull();
      await click("保留草稿");
      expect(dirty).toHaveBeenLastCalledWith(true);
      if (kind === "new task") {
        await click("添加待办");
        const posts = requests.filter((r) => r.method === "POST");
        expect(posts).toHaveLength(2);
        expect(posts[0].body.operation_id).toBe(posts[1].body.operation_id);
      }
    },
  );
  it("blocks retry reads during a pending write and locks repeated retry requests", async () => {
    await mount();
    await open();
    failRead = 503;
    await click("重新读取");
    failRead = 0;
    await click("编辑");
    await input("现状说明", "正在保存的现状");
    const original = vi.mocked(fetch).getMockImplementation()!;
    let finish!: () => void;
    let hold = new Promise<void>((resolve) => {
      finish = resolve;
    });
    vi.mocked(fetch).mockImplementation(async (...args) => {
      const response = await original(...args);
      await hold;
      return response;
    });
    await click("保存");
    const readCount = requests.filter((r) => r.method === "GET").length;
    expect(button("重试读取").disabled).toBe(true);
    await click("重试读取");
    expect(requests.filter((r) => r.method === "GET")).toHaveLength(readCount);
    await act(async () => {
      finish();
    });
    await flush();
    hold = new Promise<void>((resolve) => {
      finish = resolve;
    });
    const retry = button("重试读取");
    await act(async () => {
      retry.click();
      retry.click();
    });
    expect(requests.filter((r) => r.method === "GET")).toHaveLength(
      readCount + 1,
    );
    await act(async () => {
      finish();
    });
    await flush();
  });
});
