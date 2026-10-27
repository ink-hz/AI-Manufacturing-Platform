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
