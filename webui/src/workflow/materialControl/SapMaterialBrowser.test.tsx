import { act } from "react";
import { createRoot } from "react-dom/client";
import { it, expect, vi } from "vitest";
import { SapMaterialBrowser } from "./SapMaterialBrowser";
import type { WorkflowApi } from "../api";
const source = {
  system: "SAP",
  environment: "test",
  system_id: "TEST",
  client: "100",
  namespace: "a",
  origin: "native",
  fact_role: "observation",
};
const order = {
  snapshot: {
    id: "1",
    kind: "production-order",
    scope: { number: "000000000001", plant: "P" },
    source,
    collected_at: "old-time",
    data: {
      number: "000000000001",
      plant: "P",
      material: "M",
      description: "组件测试",
      quantity: "1.000",
      unit: "EA",
      total: 1,
      components: [
        {
          component_key: "1",
          material: "M",
          plant: "P",
          required_quantity: "123456789.0001",
          withdrawn_quantity: "0.000",
          unit: "EA",
          required_at: "00000000",
          storage_location: "S",
        },
      ],
    },
  },
  refresh_error: null,
};
async function tick() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}
it("shows source and exact quantities; component opens scoped MRP and failure keeps original timestamp", async () => {
  const api = {
    sapMaterialStatus: vi.fn(async () => ({
      configured: true,
      can_refresh: true,
      source,
    })),
    sapProductionOrder: vi.fn(async () => order),
    sapStockRequirements: vi.fn(async () => ({
      snapshot: {
        id: "2",
        kind: "stock-requirements",
        source,
        scope: { material: "M", plant: "P" },
        collected_at: "mrp-time",
        data: { mrp_list: { BASE_UOM: "EA" }, items: [] },
      },
      refresh_error: { code: "READ_FAILED", message: "failed" },
    })),
  } as unknown as WorkflowApi;
  const host = document.createElement("div");
  const root = createRoot(host);
  await act(async () =>
    root.render(<SapMaterialBrowser api={api} readOnly={false} />),
  );
  await tick();
  expect(host.textContent).toContain("SAP测试环境");
  await act(async () => {
    const inputs = host.querySelectorAll("input");
    for (const [i, v] of ["001", "P"].entries()) {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(inputs[i], v);
      inputs[i].dispatchEvent(new Event("input", { bubbles: true }));
    }
  });
  await act(async () =>
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
  await tick();
  expect(host.textContent).toContain("123456789.0001");
  expect(host.textContent).toContain("未提供");
  await act(async () =>
    Array.from(host.querySelectorAll("button"))
      .find((b) => b.textContent === "查MRP供需")!
      .click(),
  );
  await tick();
  expect(api.sapStockRequirements).toHaveBeenCalledWith(
    "M",
    "P",
    true,
    expect.any(AbortSignal),
  );
  expect(host.textContent).toContain("无供需明细");
  expect(host.textContent).toContain("mrp-time");
  expect(host.textContent).toContain("刷新失败");
  await act(async () => root.unmount());
});
async function mount(api: WorkflowApi, readOnly = false) {
  const host = document.createElement("div");
  const root = createRoot(host);
  await act(async () =>
    root.render(<SapMaterialBrowser api={api} readOnly={readOnly} />),
  );
  await tick();
  return { host, root };
}
async function fill(host: HTMLDivElement, number = "001", plant = "P") {
  await act(async () => {
    host.querySelectorAll("input").forEach((input, i) => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(input, [number, plant][i]);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  });
}
async function submit(host: HTMLDivElement) {
  await act(async () =>
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
  await tick();
}
function fake(overrides: Record<string, unknown> = {}) {
  return {
    sapMaterialStatus: vi.fn(async () => ({
      configured: true,
      source,
      can_refresh: true,
    })),
    sapProductionOrder: vi.fn(async () => order),
    sapStockRequirements: vi.fn(),
    ...overrides,
  } as unknown as WorkflowApi;
}
it("read only fetches saved results; refresh error retains exact original observation", async () => {
  const value = {
    ...order,
    refresh_error: { code: "SAP_RESULT_LIMIT_EXCEEDED", message: "limit" },
  };
  const api = fake({ sapProductionOrder: vi.fn(async () => value) });
  const v = await mount(api, true);
  await fill(v.host);
  await submit(v.host);
  expect(api.sapProductionOrder).toHaveBeenCalledWith(
    "001",
    "P",
    false,
    expect.any(AbortSignal),
  );
  expect(v.host.textContent).toContain("查看已保存结果");
  expect(v.host.textContent).toContain("500");
  expect(v.host.textContent).toContain("old-time");
  await act(async () => v.root.unmount());
});
it("displays genuine empty results and unavailable configuration without querying", async () => {
  const api = fake({
    sapProductionOrder: vi.fn(async () => ({
      ...order,
      snapshot: {
        ...order.snapshot,
        data: { ...order.snapshot.data, total: 0, components: [] },
      },
    })),
  });
  const v = await mount(api);
  await fill(v.host);
  await submit(v.host);
  expect(v.host.textContent).toContain("无组件明细");
  await act(async () =>
    v.root.render(
      <SapMaterialBrowser
        api={fake({
          sapMaterialStatus: async () => ({
            configured: false,
            source: null,
            can_refresh: false,
          }),
        })}
        readOnly={false}
      />,
    ),
  );
  await tick();
  expect(v.host.textContent).toContain("SAP连接未配置");
  expect(v.host.textContent).not.toContain("old-time");
  await act(async () => v.root.unmount());
});
it("ignores noncooperating late order responses after scope and API changes", async () => {
  let finish!: (value: unknown) => void;
  const api = fake({
    sapProductionOrder: vi.fn(() => new Promise((r) => (finish = r))),
  });
  const v = await mount(api);
  await fill(v.host);
  await submit(v.host);
  await fill(v.host, "002");
  await act(async () => finish(order));
  await tick();
  expect(v.host.textContent).not.toContain("old-time");
  await submit(v.host);
  const next = fake();
  await act(async () =>
    v.root.render(<SapMaterialBrowser api={next} readOnly={false} />),
  );
  await act(async () => finish(order));
  await tick();
  expect(v.host.textContent).not.toContain("old-time");
  await act(async () => v.root.unmount());
});
it("rejects a source namespace mismatch and clears prior data on snapshot-null failure", async () => {
  let value: unknown = order;
  const api = fake({ sapProductionOrder: async () => value });
  const v = await mount(api);
  await fill(v.host);
  await submit(v.host);
  expect(v.host.textContent).toContain("old-time");
  value = {
    snapshot: null,
    refresh_error: { code: "SAP_RESULT_LIMIT_EXCEEDED", message: "limit" },
  };
  await submit(v.host);
  expect(v.host.textContent).not.toContain("old-time");
  expect(v.host.textContent).toContain("500");
  value = {
    ...order,
    snapshot: { ...order.snapshot, source: { ...source, namespace: "other" } },
  };
  await submit(v.host);
  expect(v.host.textContent).not.toContain("old-time");
  expect(v.host.textContent).toContain("范围不匹配");
  await act(async () => v.root.unmount());
});
it("invalidates pending nested MRP when parent scope changes", async () => {
  let finish!: (value: unknown) => void;
  const api = fake({
    sapStockRequirements: () => new Promise((r) => (finish = r)),
  });
  const v = await mount(api);
  await fill(v.host);
  await submit(v.host);
  await act(async () =>
    Array.from(v.host.querySelectorAll("button"))
      .find((b) => b.textContent === "查MRP供需")!
      .click(),
  );
  await fill(v.host, "002");
  await act(async () =>
    finish({
      snapshot: {
        source,
        scope: { material: "M", plant: "P" },
        kind: "stock-requirements",
        collected_at: "stale-mrp",
        data: { mrp_list: {}, items: [] },
      },
      refresh_error: null,
    }),
  );
  await tick();
  expect(v.host.textContent).not.toContain("stale-mrp");
  await act(async () => v.root.unmount());
});

it("never labels an unknown source environment as production", async () => {
  const v = await mount(
    fake({
      sapMaterialStatus: async () => ({
        configured: true,
        source: { ...source, environment: "unknown" },
        can_refresh: false,
      }),
    }),
  );
  expect(v.host.textContent).toContain("环境待核对");
  expect(v.host.textContent).not.toContain("SAP生产环境");
  await act(async () => v.root.unmount());
});
it("status errors stop loading and offer a retry, including explicit source errors", async () => {
  let fails = true;
  const api = fake({
    sapMaterialStatus: vi.fn(async () => {
      if (fails) throw Error("offline");
      return {
        configured: false,
        source: null,
        can_refresh: false,
        refresh_error: { code: "CONFIG_ERROR", message: "failure" },
      };
    }),
  });
  const v = await mount(api);
  expect(v.host.textContent).not.toContain("正在读取SAP连接状态");
  expect(v.host.textContent).toContain("重试连接状态");
  fails = false;
  await act(async () =>
    Array.from(v.host.querySelectorAll("button"))
      .find((b) => b.textContent === "重试连接状态")!
      .click(),
  );
  await tick();
  expect(v.host.textContent).toContain("连接状态读取失败");
  expect(v.host.textContent).not.toContain("SAP连接未配置");
  await act(async () => v.root.unmount());
});
it("shows raw MRP business columns without inventing available quantity and explains overlong material", async () => {
  const api = fake({
    sapStockRequirements: async () => ({
      snapshot: {
        id: "2",
        kind: "stock-requirements",
        scope: { material: "M", plant: "P" },
        source,
        collected_at: "mrp-time",
        data: {
          mrp_list: { BASE_UOM: "EA" },
          items: [
            {
              AVAIL_DATE: "20261113",
              MRP_ELEMENT_IND: "WB",
              PLUS_MINUS: "+",
              REC_REQD_QTY: "99.00001",
              MRP_NO12: "REFERENCE",
              MRP_NO: "WRONG",
              MRP_POS: "001",
              STORAGE_LOC: "S",
              ENTRY_QNT: "3.000",
              ENTRY_UOM: "BOX",
              AVAILABLE: "DO_NOT_USE",
            },
          ],
        },
      },
      refresh_error: null,
    }),
  });
  const v = await mount(api);
  await fill(v.host);
  await submit(v.host);
  await act(async () =>
    Array.from(v.host.querySelectorAll("button"))
      .find((b) => b.textContent === "查MRP供需")!
      .click(),
  );
  await tick();
  expect(v.host.textContent).toContain("99.00001");
  expect(v.host.textContent).toContain("REFERENCE");
  expect(v.host.textContent).toContain("录入数量");
  expect(v.host.textContent).not.toContain("DO_NOT_USE");
  expect(v.host.textContent).not.toContain("WRONG");
  await act(async () => v.root.unmount());
  const long = fake({
    sapProductionOrder: async () => ({
      ...order,
      snapshot: {
        ...order.snapshot,
        data: {
          ...order.snapshot.data,
          components: [
            {
              ...order.snapshot.data.components[0],
              material: "1234567890123456789",
            },
          ],
        },
      },
    }),
  });
  const w = await mount(long);
  await fill(w.host);
  await submit(w.host);
  const button = Array.from(w.host.querySelectorAll("button")).find(
    (b) => b.textContent === "查MRP供需",
  )!;
  expect(button.disabled).toBe(true);
  expect(w.host.textContent).toContain("不能截断查询");
  await act(async () => w.root.unmount());
});
it("MRP null snapshot limit failure is explicit rather than a false empty result", async () => {
  const api = fake({
    sapStockRequirements: async () => ({
      snapshot: null,
      refresh_error: { code: "SAP_RESULT_LIMIT_EXCEEDED", message: "limit" },
    }),
  });
  const v = await mount(api);
  await fill(v.host);
  await submit(v.host);
  await act(async () =>
    Array.from(v.host.querySelectorAll("button"))
      .find((b) => b.textContent === "查MRP供需")!
      .click(),
  );
  await tick();
  expect(v.host.textContent).toContain("上限 50 条");
  expect(v.host.textContent).not.toContain("无供需明细");
  await act(async () => v.root.unmount());
});
