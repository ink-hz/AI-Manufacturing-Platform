import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { WorkflowApp } from "../WorkflowApp";
import { bootstrap, flush } from "../testHelpers";
const id = "33333333-3333-4333-8333-333333333333";
afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
  history.replaceState(null, "", "/");
});
async function shell(admin = true, readonly = false) {
  const requests: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input) => {
      const path = String(input);
      requests.push(path);
      if (path.endsWith("/status"))
        return new Response(
          JSON.stringify({ configured: false, capabilities: {} }),
        );
      if (path.includes("/handoffs/"))
        return new Response("{}", { status: 410 });
      return new Response(
        JSON.stringify(
          path.endsWith("/dashboard")
            ? { cards: [], counts: {}, project_count: 0, project_ids: [] }
            : { items: [], has_more: false },
        ),
      );
    }),
  );
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const onLogout = vi.fn();
  await act(async () =>
    root.render(
      <WorkflowApp
        options={{
          apiBase: "/api/v1/manufacturing",
          csrfToken: "csrf",
          readOnly: readonly,
          bootstrap: {
            ...bootstrap,
            configuration_admin: admin,
            can_edit: !readonly,
          },
          onLogout,
        }}
      />,
    ),
  );
  await flush();
  return {
    host,
    requests,
    onLogout,
    dispose: async () => {
      await act(async () => root.unmount());
      host.remove();
    },
    click: async (label: string) => {
      const b = [...host.querySelectorAll("button")].find(
        (b) =>
          b.textContent === label || b.getAttribute("aria-label") === label,
      );
      expect(b, label).toBeTruthy();
      await act(async () => b!.click());
      await flush();
    },
  };
}
it("selects production at shell bootstrap only for authorized valid handoff links", async () => {
  history.replaceState(null, "", "/?production_handoff=" + id);
  const v = await shell(true, true);
  try {
    expect(
      v.host.querySelector('[aria-label="产测管理工作区"]'),
    ).not.toBeNull();
    expect(v.requests.some((p) => p.endsWith("/handoffs/" + id))).toBe(true);
    expect(v.host.textContent).toContain("已过期");
    expect(
      [...v.host.querySelectorAll("button")].find(
        (b) => b.textContent === "开始调查",
      )?.disabled,
    ).toBe(true);
  } finally {
    await v.dispose();
  }
  const ordinary = await shell(false);
  try {
    expect(ordinary.requests.some((p) => p.includes("/production-tools"))).toBe(
      false,
    );
    expect(
      ordinary.host.querySelector('[aria-label="产测管理工作区"]'),
    ).toBeNull();
  } finally {
    await ordinary.dispose();
  }
});
it("clears account-scoped production resume data on successful logout", async () => {
  sessionStorage.setItem(
    `production-investigation:${bootstrap.user.id}:7`,
    JSON.stringify({ id, pending: { note: "private" } }),
  );
  const v = await shell();
  try {
    await v.click("账户菜单");
    await v.click("退出登录");
    expect(v.onLogout).toHaveBeenCalledOnce();
    expect(
      sessionStorage.getItem(`production-investigation:${bootstrap.user.id}:7`),
    ).toBeNull();
  } finally {
    await v.dispose();
  }
});
