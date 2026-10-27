import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { createApi } from "../api";
import { reasonLabel, eventLabel } from "./labels";
const operation = {
  operation_id: "a755bbad-ae32-459a-b3a6-52f9bfeebd79",
  expected_version: 2,
};
beforeEach(() =>
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}")),
  ),
);
afterEach(() => vi.unstubAllGlobals());
it("routes controls through the same CSRF, no-store and abort-aware request helper with encoded IDs", async () => {
  const api = createApi({
    apiBase: "/api",
    csrfToken: "secret",
    readOnly: false,
  });
  await api.packageAction("project/one", "package?two", {
    ...operation,
    action: "verify",
    reason: "",
  });
  expect(fetch).toHaveBeenCalledWith(
    "/api/projects/project%2Fone/packages/package%3Ftwo/actions",
    expect.objectContaining({
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      signal: expect.any(AbortSignal),
      headers: { "Content-Type": "application/json", "X-CSRF-Token": "secret" },
    }),
  );
  api.dispose();
  await expect(api.controls("p")).rejects.toMatchObject({ name: "AbortError" });
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("revokes the shared client after control authorization fails", async () => {
  const denied = vi.fn();
  vi.mocked(fetch).mockResolvedValueOnce(new Response("{}", { status: 403 }));
  const api = createApi({
    apiBase: "/api",
    csrfToken: "secret",
    readOnly: false,
    onAuthError: denied,
  });
  await expect(api.collaboration()).rejects.toMatchObject({ status: 403 });
  await expect(api.dashboard()).rejects.toMatchObject({ status: 403 });
  expect(denied).toHaveBeenCalledTimes(1);
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("translates fixed server attention and audit strings while retaining user-authored reasons", () => {
  expect(reasonLabel("Engineering material requires review")).toBe(
    "工程资料项等待人工核对",
  );
  expect(reasonLabel("Execution basis is not verified")).toBe(
    "执行依据尚未完成人工核对",
  );
  expect(reasonLabel("Package invalidated: 用户自己的理由")).toBe(
    "资料包已失效：用户自己的理由",
  );
  expect(reasonLabel("Source system retired or business scope removed")).toBe(
    "来源系统已停用或移出该业务线",
  );
  expect(reasonLabel("需要客户补齐 P1")).toBe("需要客户补齐 P1");
  expect(reasonLabel("Replaced by next-id for package revision 2")).toContain(
    "资料修订 2",
  );
  expect(eventLabel("basis_invalidated")).toBe("准备依据已失效");
});
