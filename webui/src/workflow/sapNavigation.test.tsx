import { it, expect, vi } from "vitest";
import { workflowView, bootstrap } from "./testHelpers";
it.each([true, false])(
  "SAP browser needs no project and is gated for administrator=%s",
  async (admin) => {
    const v = await workflowView({
      readProjects: async () => [],
      options: {
        bootstrap: {
          ...bootstrap,
          configuration_admin: admin,
          project_ids: [],
        },
      },
    });
    const original = fetch;
    const status = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input, init) => {
        if (String(input).endsWith("/material-control/sap/status")) {
          status();
          return new Response(
            JSON.stringify({
              configured: false,
              source: null,
              can_refresh: false,
            }),
          );
        }
        return original(input, init);
      }),
    );
    try {
      await v.click("计划与物料");
      expect(!!v.host.querySelector('[aria-label="SAP工单与物料供需"]')).toBe(
        admin,
      );
      expect(status).toHaveBeenCalledTimes(admin ? 1 : 0);
      if (admin) expect(v.host.textContent).toContain("SAP连接未配置");
    } finally {
      await v.dispose();
    }
  },
);
