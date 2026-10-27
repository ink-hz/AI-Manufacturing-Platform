import { describe, it, expect, vi } from "vitest";
import { createApi, ApiError } from "./api";

describe("manufacturing API", () => {
  it("uses same-origin credentials, CSRF writes, whole records, and direct response bodies", async () => {
    const saved = {
      practice: "核对齐套",
      participants: [],
      handoffs: [],
      systems: [],
      version: 1,
    };
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(saved)));
    vi.stubGlobal("fetch", fetcher);
    const api = createApi({
      apiBase: "/api/v1/manufacturing/",
      csrfToken: "session-token",
      readOnly: false,
    });
    const result = await api.saveRecord("cameras", "S4", {
      ...saved,
      expected_version: 0,
    });
    expect(result).toEqual(saved);
    expect(fetcher.mock.calls[0][0]).toBe(
      "/api/v1/manufacturing/lines/cameras/stages/S4",
    );
    expect(fetcher.mock.calls[0][1]).toMatchObject({
      method: "PUT",
      credentials: "same-origin",
      headers: {
        "X-CSRF-Token": "session-token",
        "Content-Type": "application/json",
      },
    });
    expect(JSON.parse(fetcher.mock.calls[0][1].body).expected_version).toBe(0);
  });
  it("passes operation UUID unchanged on create and version on patch", async () => {
    const fetcher = vi
      .fn()
      .mockImplementation(() => Promise.resolve(new Response("{}")));
    vi.stubGlobal("fetch", fetcher);
    const api = createApi({
      apiBase: "/manufacturing",
      csrfToken: "token",
      readOnly: false,
    });
    const operation = "e0562756-8bb1-4ca1-95e1-997b40009cf0";
    await api.createTask("oem", "S2", {
      title: "确认客户 BOM",
      operation_id: operation,
    });
    await api.createTask("oem", "S2", {
      title: "确认客户 BOM",
      operation_id: operation,
    });
    await api.updateTask("oem", "S2", "task1", {
      title: "原始标题",
      completed: true,
      expected_version: 3,
    });
    expect(
      fetcher.mock.calls.slice(0, 2).map((c) => JSON.parse(c[1].body)),
    ).toEqual(
      Array(2).fill({ title: "确认客户 BOM", operation_id: operation }),
    );
    expect(JSON.parse(fetcher.mock.calls[2][1].body)).toEqual({
      title: "原始标题",
      completed: true,
      expected_version: 3,
    });
  });
  it("reports status without echoing server business data", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response('{"detail":"sensitive"}', { status: 409 }),
        ),
    );
    const api = createApi({ apiBase: "/api", csrfToken: "", readOnly: false });
    await expect(api.catalog()).rejects.toMatchObject({ status: 409 });
    expect(new ApiError(409).message).not.toContain("sensitive");
  });
});
