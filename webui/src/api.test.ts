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
it("extends the same protected request lifecycle for project APIs and fixed documents", async () => {
  const fetcher = vi
    .fn()
    .mockImplementation(() => Promise.resolve(new Response("{}")));
  vi.stubGlobal("fetch", fetcher);
  const api = createApi({
    apiBase: "/api",
    csrfToken: "csrf",
    readOnly: false,
  });
  await api.dashboard();
  await api.projects();
  await api.project("p /1");
  const body = {
    operation_id: "id",
    name: "相机",
    line_id: "cameras",
    owner: "王工",
    due_date: null,
  };
  await api.createProject(body);
  await api.createProject(body);
  await api.updateProject("p", { expected_version: 2, archived: true });
  await api.saveProjectStage("p", "S1", {
    expected_version: 4,
    status: "done",
    owner: "王工",
    due_date: null,
    blocker: "",
    practice: "事实",
    participants: [],
    handoffs: [],
    systems: [],
  });
  await api.projectTasks();
  await api.createProjectTask("p", {
    operation_id: "task-id",
    stage_id: "S1",
    title: "确认",
    kind: "confirmation",
    priority: "urgent",
    due_date: null,
  });
  await api.updateProjectTask("p", "t", {
    expected_version: 3,
    status: "todo",
  });
  await api.handbook("workflow", "release 1");
  expect(fetcher.mock.calls.map((c) => c[0])).toEqual([
    "/api/dashboard",
    "/api/projects",
    "/api/projects/p%20%2F1",
    "/api/projects",
    "/api/projects",
    "/api/projects/p",
    "/api/projects/p/stages/S1",
    "/api/project-tasks",
    "/api/projects/p/tasks",
    "/api/projects/p/tasks/t",
    "/api/handbook?document=workflow&release=release%201",
  ]);
  expect(JSON.parse(fetcher.mock.calls[3][1].body)).toEqual(
    JSON.parse(fetcher.mock.calls[4][1].body),
  );
  expect(fetcher.mock.calls[6][1]).toMatchObject({
    method: "PUT",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": "csrf" },
  });
  api.dispose();
  await expect(api.handbook()).rejects.toMatchObject({ name: "AbortError" });
});
