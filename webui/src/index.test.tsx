import { act } from "react";
import { expect, it, vi } from "vitest";
import { mount } from "./index";
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
          JSON.stringify(
            String(url).endsWith("/dashboard")
              ? {
                  counts: {
                    active_projects: 0,
                    blocked_projects: 0,
                    due_soon: 0,
                    open_tasks: 0,
                    pending_confirmations: 0,
                  },
                  projects: [],
                  attention: [],
                  blockers: [],
                  activity: [],
                }
              : String(url).endsWith("/catalog")
                ? { groups: [], lines: [], stages: [], can_edit: false }
                : { items: [] },
          ),
        ),
    );
    let current!: ReturnType<typeof mount>;
    await act(async () => {
      current = mount(element, {
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
