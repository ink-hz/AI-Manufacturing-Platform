import { afterEach, expect, it, vi } from "vitest";
import { createWorkflowApi } from "../api";
afterEach(() => vi.unstubAllGlobals());
it("encodes exact analytics scope and every investigation operation with expected revisions and CSRF", async () => {
  const calls: { url: URL; init: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input, init) => {
      calls.push({ url: new URL(String(input), location.origin), init });
      return new Response("{}");
    }),
  );
  const api = createWorkflowApi({
    apiBase: "/api/v1/manufacturing",
    csrfToken: "csrf",
    readOnly: false,
  });
  const project = "99999999999999999999",
    id = "11111111-1111-4111-8111-111111111111",
    range = { start: "2026-11-10T00:00:00Z", end: "2026-11-10T01:00:00Z" };
  await api.productionOverview({ ...range, before_id: "9007199254740993" });
  await api.productionAnalysis(project, {
    ...range,
    view: "errors",
    stage_id: "9007199254740993",
    missing_fields: ["device", "error_code"],
  });
  expect(calls[1].url.searchParams.get("stage_id")).toBe("9007199254740993");
  expect(calls[1].url.searchParams.getAll("missing_fields")).toEqual([
    "device,error_code",
  ]);
  await api.investigations(project);
  await api.createInvestigation(project, {
    context: {
      ...range,
      view: "history",
      history_sn: "HISTORY-SN",
      missing_fields: ["device"],
    },
  });
  await api.updateInvestigation(project, id, {
    expected_version: 7,
    primary: { snapshot_id: id, offset: 50 },
  });
  await api.investigation(project, id);
  await api.resolveInvestigation(project, id);
  await api.createProductionHandoff(project, id, 8);
  await api.productionHandoff(id);
  await api.resolveProductionHandoff(id);
  await api.forkProductionHandoff(id);
  expect(
    calls.map((c) => [
      c.init.method,
      c.url.pathname.split("/production-tools")[1],
    ]),
  ).toEqual([
    ["GET", "/overview"],
    ["GET", `/projects/${project}/analysis`],
    ["GET", `/projects/${project}/investigations`],
    ["POST", `/projects/${project}/investigations`],
    ["PUT", `/projects/${project}/investigations/${id}`],
    ["GET", `/projects/${project}/investigations/${id}`],
    ["GET", `/projects/${project}/investigations/${id}/resolve`],
    ["POST", `/projects/${project}/investigations/${id}/handoffs`],
    ["GET", `/handoffs/${id}`],
    ["GET", `/handoffs/${id}/resolve`],
    ["POST", `/handoffs/${id}/fork`],
  ]);
  expect(JSON.parse(String(calls[4].init.body))).toEqual({
    expected_version: 7,
    primary: { snapshot_id: id, offset: 50 },
  });
  for (const c of calls.filter((c) => c.init.method !== "GET"))
    expect(new Headers(c.init.headers).get("X-CSRF-Token")).toBe("csrf");
  api.dispose();
});
it("retires investigation requests and aborts sibling reads after authorization loss", async () => {
  let signal: AbortSignal | null | undefined;
  const auth = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input, init) => {
      if (String(input).endsWith("/resolve")) {
        signal = init.signal;
        return new Promise(() => {});
      }
      return new Response("{}", { status: 403 });
    }),
  );
  const api = createWorkflowApi(
    { apiBase: "/api/v1/manufacturing", csrfToken: "csrf", readOnly: false },
    auth,
  );
  void api.resolveProductionHandoff("id").catch(() => {});
  await expect(api.productionHandoff("id")).rejects.toMatchObject({
    status: 403,
  });
  expect(signal?.aborted).toBe(true);
  expect(auth).toHaveBeenCalledOnce();
  await expect(api.forkProductionHandoff("id")).rejects.toMatchObject({
    name: "AbortError",
  });
});
