import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import { ConsoleShell } from "./ConsoleShell";
it("keeps the approved application name and asset URLs while toggling navigation", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  await act(async () => root.render(<ConsoleShell view="home" creating={false} readOnly busy={false}
    onNavigate={() => {}} onCreate={() => {}}
    branding={{logo: "/api/assets/master-logo-v2.png?release=test", icon: "/api/assets/app-icon-v2.png?release=test"}}>
    <p>工作台</p>
  </ConsoleShell>));
  expect(host.querySelector('[role="img"]')?.getAttribute("aria-label")).toBe("奥比制造管理");
  expect([...host.querySelectorAll("img")].map(img => img.getAttribute("src"))).toEqual([
    "/api/assets/master-logo-v2.png?release=test", "/api/assets/app-icon-v2.png?release=test",
  ]);
  expect(host.textContent).not.toContain("奥比大制造");
  const toggle = host.querySelector<HTMLButtonElement>('[aria-label="收起侧栏"]')!;
  await act(async () => toggle.click());
  expect(host.querySelector('[aria-label="展开侧栏"]')).not.toBeNull();
  expect(host.querySelector('[role="img"]')?.getAttribute("aria-label")).toBe("奥比制造管理");
  await act(async () => root.unmount());
  host.remove();
});
