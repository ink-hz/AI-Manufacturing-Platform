import { it, expect, vi, afterEach } from "vitest";
import { createWorkflowApi } from "./api";
afterEach(() => vi.unstubAllGlobals());
it("uses one workflow prefix with CSRF and retires late responses", async () => {
  let resolve!: (r: Response) => void;
  const fetcher = vi.fn(
    (_url: string, _init?: RequestInit) =>
      new Promise<Response>((r) => (resolve = r)),
  );
  vi.stubGlobal("fetch", fetcher);
  const auth = vi.fn();
  const api = createWorkflowApi(
    {
      apiBase: "/preview/api/v1/manufacturing",
      csrfToken: "csrf",
      readOnly: false,
    },
    auth,
  );
  const pending = api.projects();
  api.dispose();
  resolve(new Response("{}", { status: 403 }));
  await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  expect(auth).not.toHaveBeenCalled();
  expect(fetcher.mock.calls[0][0]).toBe(
    "/preview/api/v1/manufacturing/workflow/projects",
  );
});
it("sends exact command data and CSRF without actor fields", async () => {
  const body = {
    action: "demand.review" as const,
    operation_id: "00000000-0000-4000-8000-000000000001",
    expected_version: 2,
    demand_id: "00000000-0000-4000-8000-000000000002",
    dimension: "technical" as const,
    decision: "approved" as const,
    evidence: "技术评审单",
  };
  const fetcher = vi.fn(
    async () =>
      new Response(
        JSON.stringify({
          operation_id: body.operation_id,
          project_id: "p",
          project_version: 3,
          object_type: "demand",
          object_id: body.demand_id,
          exchange_id: null,
          replayed: false,
        }),
      ),
  );
  vi.stubGlobal("fetch", fetcher);
  const api = createWorkflowApi({
    apiBase: "/api/v1/manufacturing",
    csrfToken: "csrf",
    readOnly: false,
  });
  await api.command("p", body);
  expect(fetcher).toHaveBeenCalledWith(
    "/api/v1/manufacturing/workflow/projects/p/commands",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json", "X-CSRF-Token": "csrf" },
      cache: "no-store",
      credentials: "same-origin",
    }),
  );
  api.dispose();
});
