import { it, expect, vi, afterEach } from "vitest";
import { createWorkflowApi } from "../api";
afterEach(() => vi.unstubAllGlobals());
it("encodes exact SAP scopes and sends trusted CSRF on bodyless refresh only", async () => {
  const fetcher = vi.fn(
    async (_url: string, _init?: RequestInit) => new Response("{}"),
  );
  vi.stubGlobal("fetch", fetcher);
  const api = createWorkflowApi({
    apiBase: "/api/v1/manufacturing",
    csrfToken: "trusted",
    readOnly: false,
  });
  await api.sapProductionOrder("00 +/", "A&1", true);
  expect(fetcher.mock.calls[0]).toEqual([
    "/api/v1/manufacturing/workflow/material-control/sap/production-order?number=00+%2B%2F&plant=A%261",
    expect.objectContaining({
      method: "POST",
      headers: { "X-CSRF-Token": "trusted" },
    }),
  ]);
  expect(fetcher.mock.calls[0][1]?.body).toBeUndefined();
  await api.sapStockRequirements("0001", "A1", false);
  expect(fetcher.mock.calls[1]).toEqual([
    expect.stringContaining("stock-requirements?material=0001&plant=A1"),
    expect.objectContaining({ method: "GET", headers: {} }),
  ]);
});
