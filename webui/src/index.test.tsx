import { act } from "react";
import { expect, it, vi } from "vitest";
import { mount } from "./index";
import { bootstrap } from "./workflow/testHelpers";
it("exposes an independent mount handle and cleans up twice safely", async () => {
  const element = document.createElement("div");
  document.body.append(element);
  const auth = vi.fn(),
    dirty = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 401 })),
  );
  let handle: ReturnType<typeof mount>;
  await act(async () => {
    handle = mount(element, {
      bootstrap: {...bootstrap,configuration_admin:true},
      apiBase: "/api/v1/manufacturing",
      csrfToken: "",
      readOnly: true,
      onAuthError: auth,
      onDirtyChange: dirty,
    });
  });
  expect(handle!.isDirty()).toBe(false);
  expect(element.textContent).toContain("无权访问");
  expect(auth).toHaveBeenCalledTimes(1);
  await act(async () => {
    handle!.unmount();
    handle!.unmount();
  });
  expect(element.childElementCount).toBe(0);
  expect(dirty).toHaveBeenLastCalledWith(false);
  element.remove();
});

it.each([401, 403])(
  "retires pending %s responses even when fetch ignores abort",
  async (status) => {
    const element = document.createElement("div");
    document.body.append(element);
    const retiredAuth = vi.fn(),
      retiredDirty = vi.fn(),
      currentAuth = vi.fn();
    let resolveOld!: (response: Response) => void;
    let oldSignal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        oldSignal = init?.signal as AbortSignal | undefined;
        return new Promise<Response>((resolve) => {
          resolveOld = resolve;
        });
      }),
    );
    let old!: ReturnType<typeof mount>;
    await act(async () => {
      old = mount(element, {
        bootstrap: {...bootstrap,configuration_admin:true},
        apiBase: "/api/v1/manufacturing",
        csrfToken: "",
        readOnly: true,
        onAuthError: retiredAuth,
        onDirtyChange: retiredDirty,
      });
    });
    await act(async () => old.unmount());
    const callbackCount = retiredDirty.mock.calls.length;
    vi.mocked(fetch).mockImplementation(
      async (url) =>
        new Response(
          JSON.stringify(String(url).endsWith('/dashboard') ? {counts:{},cards:[],project_ids:[],project_count:0} : {items:[]}),
        ),
    );
    let current!: ReturnType<typeof mount>;
    await act(async () => {
      current = mount(element, {
        bootstrap: {...bootstrap,configuration_admin:true},
        apiBase: "/api/v1/manufacturing",
        csrfToken: "",
        readOnly: true,
        onAuthError: currentAuth,
      });
    });
    await act(async () => {
      resolveOld(new Response("{}", { status }));
    });
    expect(retiredAuth).not.toHaveBeenCalled();
    expect(oldSignal?.aborted).toBe(true);
    expect(currentAuth).not.toHaveBeenCalled();
    expect(retiredDirty).toHaveBeenCalledTimes(callbackCount);
    expect(element.textContent).not.toContain("无权访问");
    expect(old.isDirty()).toBe(false);
    await act(async () => current.unmount());
    element.remove();
  },
);

it("updates account metadata in place while retaining a dirty project draft and retires updates", async () => {
  const element = document.createElement("div");
  document.body.append(element);
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (url) =>
        new Response(
          JSON.stringify(String(url).endsWith('/dashboard') ? {counts:{},cards:[],project_ids:[],project_count:0} : {items:[]}),
        ),
    ),
  );
  let handle!: ReturnType<typeof mount>;
  await act(async () => {
    handle = mount(element, {
      bootstrap: {...bootstrap,configuration_admin:true},
      apiBase: "/api",
      csrfToken: "csrf",
      readOnly: false,
      user: { displayName: "旧姓名", roleLabel: "平台管理员" },
    });
  });
  await act(async () =>
    [...element.querySelectorAll("button")]
      .find((b) => b.textContent === "新建项目")!
      .click(),
  );
  const input = element.querySelector(
    '[aria-label="项目名称"]',
  ) as HTMLInputElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "未保存项目");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(handle.isDirty()).toBe(true);
  const calls = vi.mocked(fetch).mock.calls.length;
  await act(async () =>
    handle.updateUser!({ displayName: "新姓名", roleLabel: "平台管理员" }),
  );
  expect(element.textContent).toContain("新姓名");
  expect(element.textContent).not.toContain("旧姓名");
  expect(element.querySelector('[aria-label="项目名称"]')).toBe(input);
  expect(input.value).toBe("未保存项目");
  expect(handle.isDirty()).toBe(true);
  expect(fetch).toHaveBeenCalledTimes(calls);
  await act(async () => handle.unmount());
  await act(async () =>
    handle.updateUser!({ displayName: "已退休", roleLabel: "" }),
  );
  expect(element.childElementCount).toBe(0);
  element.remove();
});
