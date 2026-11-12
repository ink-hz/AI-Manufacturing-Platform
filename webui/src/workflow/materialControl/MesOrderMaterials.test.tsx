// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { MaterialControlWorkspace } from "./MaterialControlWorkspace";
import { project } from "../testHelpers";

it("offers work order choices before a supply plan exists", async () => {
  const api = {
    materialProject: vi
      .fn()
      .mockResolvedValue({ requirements: [], work_orders: [], total: 0 }),
    objects: vi.fn().mockResolvedValue({
      items: [{ id: "w1", title: "装配工单" }],
      total: 1,
    }),
  };
  const host = document.createElement("div"),
    root = createRoot(host);
  await act(async () =>
    root.render(
      <MaterialControlWorkspace
        {...({
          api,
          project,
          readOnly: false,
          onDirty: vi.fn(),
          onChanged: vi.fn(),
          onOpen: vi.fn(),
          requestLeave: (f: () => void) => f(),
        } as any)}
      />,
    ),
  );
  await act(async () => {});
  expect(host.textContent).toContain("MES工单物料");
  expect(host.textContent).toContain("装配工单");
  await act(async () => root.unmount());
});

it("binds, displays exact saved quantities, refreshes, and retains the snapshot on failure", async () => {
  const binding = {
    id: "b1",
    shop_order: "OEM-1",
    environment: "test",
    site_code: "1000",
    verified_at: "2026-01-01",
  };
  const snapshot = {
    id: "s1",
    collected_at: "2026-01-02",
    total: 1,
    components: [
      {
        quantities: { required_quantity: { value: "1.00000000001", unit: "EA", meaning: "required", origins: ["mock"], environments: ["test"], fact_role: "observation", observed_at: null, collected_at: "2026-01-02", coverage: "partial", source_refs: [], input_refs: [] }, withdrawn_quantity: { value: null, unit: "EA", meaning: "withdrawn", origins: ["unknown"], environments: ["unknown"], fact_role: "unknown", observed_at: null, collected_at: null, coverage: "unknown", source_refs: [], input_refs: [] } },
        component_key: "1:2",
        material_id: "MAT",
        required_quantity: "1.00000000001",
        withdrawn_quantity: null,
        unit: "EA",
        storage_location: null,
      },
    ],
  };
  const api = {
    objects: vi
      .fn()
      .mockResolvedValueOnce({
        items: [{ id: "w1", title: "装配工单" }],
        total: 2,
      })
      .mockResolvedValueOnce({
        items: [{ id: "w2", title: "第二工单" }],
        total: 2,
      }),
    mesOrderMaterials: vi
      .fn()
      .mockResolvedValueOnce({
        work_order_id: "w1",
        can_manage: true,
        binding: null,
        snapshot: null,
      })
      .mockResolvedValue({
        work_order_id: "w1",
        can_manage: true,
        binding,
        snapshot,
      }),
    command: vi
      .fn()
      .mockResolvedValueOnce({ project_id: project.id, project_version: 4 })
      .mockRejectedValueOnce(new Error("private source")),
  };
  const host = document.createElement("div"),
    root = createRoot(host),
    changed = vi.fn(),
    dirty = vi.fn();
  const { MesOrderMaterials } = await import("./MesOrderMaterials");
  await act(async () =>
    root.render(
      <MesOrderMaterials
        p={
          {
            api,
            project,
            readOnly: false,
            onChanged: changed,
            onDirty: dirty,
          } as any
        }
        leave={(f) => f()}
      />,
    ),
  );
  const button = (name: string) =>
    [...host.querySelectorAll("button")].find((x) => x.textContent === name)!;
  await act(async () => button("加载更多工单").click());
  expect(host.textContent).toContain("第二工单");
  const select = host.querySelector("select")!;
  await act(async () => {
    select.value = "w1";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const input = host.querySelector("input")!;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(input, "OEM-1");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => button("关联MES工单").click());
  expect(api.command).toHaveBeenCalledWith(
    project.id,
    expect.objectContaining({
      action: "mes_order.bind",
      work_order_id: "w1",
      shop_order: "OEM-1",
      replace_binding_id: null,
      reason: null,
      expected_version: project.version,
    }),
  );
  expect(changed).toHaveBeenCalled();
  expect(host.textContent).toContain("1.00000000001 EA · 模拟");
  expect(host.textContent).toContain("来源待核对");
  expect(host.textContent).toContain("未提供");
  expect(host.textContent).toContain("EA");
  expect(button("更换关联").disabled).toBe(true);
  await act(async () => button("刷新组件").click());
  expect(api.command).toHaveBeenLastCalledWith(
    project.id,
    expect.objectContaining({ action: "mes_order.refresh", binding_id: "b1" }),
  );
  expect(host.textContent).toContain("MAT");
  expect(host.textContent).not.toContain("private source");
  await act(async () => root.unmount());
});

it("hides mutations when management is unavailable", async () => {
  const { MesOrderMaterials } = await import("./MesOrderMaterials");
  const api = {
    objects: vi
      .fn()
      .mockResolvedValue({ items: [{ id: "w1", title: "工单一" }], total: 1 }),
    mesOrderMaterials: vi.fn().mockResolvedValue({
      work_order_id: "w1",
      can_manage: false,
      binding: null,
      snapshot: null,
    }),
  };
  const host = document.createElement("div"),
    root = createRoot(host);
  await act(async () =>
    root.render(
      <MesOrderMaterials
        p={{ api, project, readOnly: false, onDirty: vi.fn() } as any}
        leave={(f) => f()}
      />,
    ),
  );
  const select = host.querySelector("select")!;
  await act(async () => {
    select.value = "w1";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(host.textContent).toContain("尚未关联");
  expect(host.querySelector("input")).toBeNull();
  await act(async () => root.unmount());
});

it("requires a replacement reason and submits the current binding", async () => {
  const { MesOrderMaterials } = await import("./MesOrderMaterials");
  const api = {
    objects: vi
      .fn()
      .mockResolvedValue({ items: [{ id: "w", title: "工单" }], total: 1 }),
    mesOrderMaterials: vi.fn().mockResolvedValue({
      work_order_id: "w",
      can_manage: true,
      binding: {
        id: "old",
        shop_order: "OLD",
        environment: "production",
        site_code: "1",
        verified_at: "time",
      },
      snapshot: null,
    }),
    command: vi
      .fn()
      .mockResolvedValue({ project_id: project.id, project_version: 4 }),
  };
  const host = document.createElement("div"),
    root = createRoot(host);
  await act(async () =>
    root.render(
      <MesOrderMaterials
        p={
          {
            api,
            project,
            readOnly: false,
            onDirty: vi.fn(),
            onChanged: vi.fn(),
          } as any
        }
        leave={(f) => f()}
      />,
    ),
  );
  const select = host.querySelector("select")!;
  await act(async () => {
    select.value = "w";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const inputs = host.querySelectorAll("input"),
    setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
  await act(async () => {
    setter.call(inputs[0], "NEW");
    inputs[0].dispatchEvent(new Event("input", { bubbles: true }));
  });
  const replace = [...host.querySelectorAll("button")].find(
    (x) => x.textContent === "更换关联",
  )!;
  expect(replace.disabled).toBe(true);
  await act(async () => {
    setter.call(inputs[1], "业务调整");
    inputs[1].dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => replace.click());
  expect(api.command).toHaveBeenCalledWith(
    project.id,
    expect.objectContaining({
      action: "mes_order.bind",
      replace_binding_id: "old",
      reason: "业务调整",
    }),
  );
  await act(async () => root.unmount());
});

it("ignores a late result after the selected work order changes", async () => {
  const { MesOrderMaterials } = await import("./MesOrderMaterials");
  let resolve!: (v: any) => void;
  const pending = new Promise((r) => {
    resolve = r;
  });
  const api = {
    objects: vi.fn().mockResolvedValue({
      items: [
        { id: "a", title: "甲" },
        { id: "b", title: "乙" },
      ],
      total: 2,
    }),
    mesOrderMaterials: vi.fn().mockReturnValueOnce(pending).mockResolvedValue({
      work_order_id: "b",
      can_manage: false,
      binding: null,
      snapshot: null,
    }),
  };
  const host = document.createElement("div"),
    root = createRoot(host);
  await act(async () =>
    root.render(
      <MesOrderMaterials
        p={{ api, project, readOnly: false, onDirty: vi.fn() } as any}
        leave={(f) => f()}
      />,
    ),
  );
  const select = host.querySelector("select")!;
  await act(async () => {
    select.value = "a";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await act(async () => {
    select.value = "b";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await act(async () =>
    resolve({
      work_order_id: "a",
      can_manage: true,
      binding: { shop_order: "STALE" },
      snapshot: null,
    }),
  );
  expect(host.textContent).not.toContain("STALE");
  expect(host.querySelector("input")).toBeNull();
  await act(async () => root.unmount());
});

it("retains a conflicted draft until guarded discard reloads the project", async () => {
  const { MesOrderMaterials } = await import("./MesOrderMaterials");
  const { WorkflowError } = await import("../api");
  const api = {
    objects: vi
      .fn()
      .mockResolvedValue({ items: [{ id: "w", title: "工单" }], total: 1 }),
    mesOrderMaterials: vi.fn().mockResolvedValue({
      work_order_id: "w",
      can_manage: true,
      binding: null,
      snapshot: null,
    }),
    project: vi.fn().mockResolvedValue({ ...project, version: 9 }),
    command: vi
      .fn()
      .mockRejectedValue(new WorkflowError(409, "VERSION_CONFLICT")),
  };
  const host = document.createElement("div"),
    root = createRoot(host),
    changed = vi.fn();
  let deferred: (() => void) | undefined;
  await act(async () =>
    root.render(
      <MesOrderMaterials
        p={
          {
            api,
            project,
            readOnly: false,
            onDirty: vi.fn(),
            onChanged: changed,
          } as any
        }
        leave={(f) => {
          if (!host.querySelector("input")) f();
          else deferred = f;
        }}
      />,
    ),
  );
  const select = host.querySelector("select")!;
  await act(async () => {
    select.value = "w";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const input = host.querySelector("input")!,
    setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
  await act(async () => {
    setter.call(input, "DRAFT");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((x) => x.textContent === "关联MES工单")!
      .click(),
  );
  expect(input.value).toBe("DRAFT");
  const discard = [...host.querySelectorAll("button")].find(
    (x) => x.textContent === "放弃草稿并重新读取",
  );
  expect(discard).toBeTruthy();
  await act(async () => discard!.click());
  expect(input.value).toBe("DRAFT");
  await act(async () => deferred!());
  expect(api.project).toHaveBeenCalled();
  expect(changed).toHaveBeenCalledWith(
    expect.objectContaining({ project_version: 9 }),
  );
  await act(async () => root.unmount());
});

it("blocks a draft created against an older project version", async () => {
  const { MesOrderMaterials } = await import("./MesOrderMaterials");
  const api = {
    objects: vi
      .fn()
      .mockResolvedValue({ items: [{ id: "w", title: "工单" }], total: 1 }),
    mesOrderMaterials: vi.fn().mockResolvedValue({
      work_order_id: "w",
      can_manage: true,
      binding: null,
      snapshot: null,
    }),
  };
  const host = document.createElement("div"),
    root = createRoot(host),
    p = {
      api,
      project,
      readOnly: false,
      onDirty: vi.fn(),
      onChanged: vi.fn(),
    } as any;
  await act(async () =>
    root.render(<MesOrderMaterials p={p} leave={(f) => f()} />),
  );
  const select = host.querySelector("select")!;
  await act(async () => {
    select.value = "w";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const input = host.querySelector("input")!,
    setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
  await act(async () => {
    setter.call(input, "DRAFT");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    root.render(
      <MesOrderMaterials
        p={{ ...p, project: { ...project, version: project.version + 1 } }}
        leave={(f) => f()}
      />,
    ),
  );
  expect(input.value).toBe("DRAFT");
  expect(
    [...host.querySelectorAll("button")].find(
      (x) => x.textContent === "关联MES工单",
    )!.disabled,
  ).toBe(true);
  await act(async () => root.unmount());
});

it("clears the loading indicator when selection is cleared during a read", async () => {
  const { MesOrderMaterials } = await import("./MesOrderMaterials");
  const api = {
    objects: vi
      .fn()
      .mockResolvedValue({ items: [{ id: "w", title: "工单" }], total: 1 }),
    mesOrderMaterials: vi.fn().mockReturnValue(new Promise(() => {})),
  };
  const host = document.createElement("div"),
    root = createRoot(host);
  await act(async () =>
    root.render(
      <MesOrderMaterials
        p={{ api, project, readOnly: false, onDirty: vi.fn() } as any}
        leave={(f) => f()}
      />,
    ),
  );
  const select = host.querySelector("select")!;
  await act(async () => {
    select.value = "w";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(host.textContent).toContain("正在读取MES工单物料");
  await act(async () => {
    select.value = "";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(host.textContent).not.toContain("正在读取MES工单物料");
  await act(async () => root.unmount());
});
