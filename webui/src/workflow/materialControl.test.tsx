// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { SupplyWorkspace } from "./SupplyWorkspace";
import { project, flush } from "./testHelpers";

let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
afterEach(async () => {
  if (root) await act(async () => root.unmount());
  host?.remove();
});
it("opens OEM material status and preserves exact quantities and units", async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const api = {
    materialProject: vi.fn().mockResolvedValue({
      requirements: [
        {
          id: "r",
          material_id: "齿轮",
          work_order_id: "w",
          unit: "件",
          required: "10.50",
          reserved: "2.00",
          qualified: "3.00",
          shortage: "8.50",
          received: "3.00",
          rejected: "0",
          in_transit: "1",
          need_at: "2026-12-01",
          need_at_basis: "work_order_planned_start_proxy",
          expedite_ids: [],
          receipt_ids: [],
          handoff_ids: [],
        },
      ],
      work_orders: [{ id: "w", title: "工单 A" }],
      expedites: [],
      receipts: [],
      handoffs: [],
      coverage_issues: [],
      source_modes: [],
      total: 1,
      limit: 50,
      offset: 0,
    }),
    objects: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    members: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  };
  await act(async () =>
    root.render(
      <SupplyWorkspace
        api={api as never}
        project={{ ...project, mode: "oem" }}
        readOnly={false}
        onChanged={() => {}}
        onOpen={() => {}}
        onDirty={() => {}}
        requestLeave={(f) => f()}
      />,
    ),
  );
  await flush();
  expect(host.textContent).toContain("料况");
  expect(host.textContent).toContain("齿轮");
  expect(host.textContent).toContain("10.50 件");
  expect(host.textContent).toContain("8.50 件");
});
it("opens an expedite from a requirement using the project version", async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const api = {
    materialProject: vi.fn().mockResolvedValue({
      requirements: [
        {
          id: "r",
          material_id: "齿轮",
          work_order_id: "w",
          unit: "件",
          required: "10",
          reserved: "0",
          qualified: "0",
          shortage: "10",
          received: "0",
          rejected: "0",
          in_transit: "0",
          need_at: null,
          expedite_ids: [],
          receipt_ids: [],
          handoff_ids: [],
        },
      ],
      work_orders: [],
      expedites: [],
      receipts: [],
      handoffs: [],
      coverage_issues: [],
      source_modes: [],
      total: 1,
    }),
    command: vi.fn().mockResolvedValue({
      project_id: project.id,
      project_version: 4,
      operation_id: "x",
    }),
  };
  await act(async () =>
    root.render(
      <SupplyWorkspace
        api={api as never}
        project={{
          ...project,
          mode: "oem",
          allowed_actions: ["expedite.open"] as never,
        }}
        readOnly={false}
        onChanged={() => {}}
        onOpen={() => {}}
        onDirty={() => {}}
        requestLeave={(f) => f()}
      />,
    ),
  );
  await flush();
  const click = async (t: string) => {
    const b = [...host.querySelectorAll("button")].find(
      (x) => x.textContent === t,
    );
    expect(b).toBeTruthy();
    await act(async () => b!.click());
  };
  await click("齿轮");
  await click("发起催料");
  for (const [name, value] of [
    ["催料原因", "交期临近"],
    ["影响", "装配受阻"],
  ]) {
    const e = host.querySelector(`[aria-label="${name}"]`) as HTMLInputElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(e, value);
      e.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }
  await click("提交催料");
  await flush();
  expect(api.command).toHaveBeenCalledWith(
    project.id,
    expect.objectContaining({
      action: "expedite.open",
      requirement_id: "r",
      reason: "交期临近",
      impact: "装配受阻",
      expected_version: 3,
    }),
  );
});
it("offers accept only when the task exposes that action", async () => {
  const { MaterialTaskPanel } =
    await import("./materialControl/MaterialTaskPanel");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const api = {
    object: vi.fn().mockResolvedValue({
      summary: {
        id: "t",
        title: "检验齿轮",
        next_actions: ["material_task.accept"],
      },
      value: {
        kind: "material_task",
        task_kind: "iqc",
        state: "pending",
        note: "检验齿轮",
        history: [],
      },
    }),
    command: vi.fn().mockResolvedValue({
      project_id: project.id,
      project_version: 4,
      operation_id: "x",
    }),
  };
  await act(async () =>
    root.render(
      <MaterialTaskPanel
        api={api as never}
        project={{
          ...project,
          allowed_actions: ["material_task.accept"] as never,
        }}
        taskId="t"
        readOnly={false}
        onChanged={() => {}}
        onDirty={() => {}}
      />,
    ),
  );
  await flush();
  const b = [...host.querySelectorAll("button")].find(
    (x) => x.textContent === "接单",
  );
  expect(b).toBeTruthy();
  await act(async () => b!.click());
  await flush();
  expect(api.command).toHaveBeenCalledWith(
    project.id,
    expect.objectContaining({
      action: "material_task.accept",
      task_id: "t",
      expected_version: 3,
    }),
  );
});
it("opens IQC for a selected receipt and named assignee", async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const page = {
    requirements: [
      {
        id: "r",
        material_id: "齿轮",
        work_order_id: "w",
        unit: "件",
        required: "10",
        reserved: "0",
        qualified: "0",
        shortage: "10",
        received: "10",
        rejected: "0",
        in_transit: "0",
        need_at: null,
        expedite_ids: [],
        receipt_ids: ["receipt"],
        handoff_ids: [],
      },
    ],
    work_orders: [],
    expedites: [],
    receipts: [
      {
        id: "receipt",
        quantity: "10",
        unit: "件",
        qualified: "0",
        rejected: "0",
        uninspected: "10",
      },
    ],
    handoffs: [],
    coverage_issues: [],
    source_modes: [],
    total: 1,
  };
  const api = {
    materialProject: vi.fn().mockResolvedValue(page),
    materialAssignees: vi
      .fn()
      .mockResolvedValue({ items: [{ id: "u", display_name: "王检" }] }),
    command: vi.fn().mockResolvedValue({
      project_id: project.id,
      project_version: 4,
      operation_id: "x",
    }),
  };
  await act(async () =>
    root.render(
      <SupplyWorkspace
        api={api as never}
        project={{
          ...project,
          mode: "oem",
          allowed_actions: ["material_task.open"] as never,
        }}
        readOnly={false}
        onChanged={() => {}}
        onOpen={() => {}}
        onDirty={() => {}}
        requestLeave={(f) => f()}
      />,
    ),
  );
  await flush();
  const click = async (t: string) => {
    const b = [...host.querySelectorAll("button")].find(
      (x) => x.textContent === t,
    );
    expect(b).toBeTruthy();
    await act(async () => b!.click());
    await flush();
  };
  await click("齿轮");
  await click("安排检验");
  for (const [name, value] of [
    ["到货记录", "receipt"],
    ["检验人", "u"],
    ["任务说明", "检验齿轮"],
  ]) {
    const e = host.querySelector(`[aria-label="${name}"]`) as HTMLInputElement;
    expect(e).toBeTruthy();
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        e.tagName === "SELECT"
          ? HTMLSelectElement.prototype
          : HTMLInputElement.prototype,
        "value",
      )!.set!.call(e, value);
      e.dispatchEvent(new Event("input", { bubbles: true }));
      e.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }
  await click("创建任务");
  expect(api.command).toHaveBeenCalledWith(
    project.id,
    expect.objectContaining({
      action: "material_task.open",
      receipt_id: "receipt",
      assignee_id: "u",
      task_kind: "iqc",
    }),
  );
});
it("does not show task actions in read-only mode", async () => {
  const { MaterialTaskPanel } =
    await import("./materialControl/MaterialTaskPanel");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const api = {
    object: vi.fn().mockResolvedValue({
      summary: { title: "检验", next_actions: ["material_task.accept"] },
      value: {
        task_kind: "iqc",
        state: "pending",
        note: "检验",
        history: [],
      },
    }),
  };
  await act(async () =>
    root.render(
      <MaterialTaskPanel
        api={api as never}
        project={{
          ...project,
          allowed_actions: ["material_task.accept"] as never,
        }}
        taskId="t"
        readOnly
        onChanged={() => {}}
        onDirty={() => {}}
      />,
    ),
  );
  await flush();
  expect(
    [...host.querySelectorAll("button")].some((b) => b.textContent === "接单"),
  ).toBe(false);
});
it("ignores a late material page after project changes", async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  let finish!: (x: unknown) => void;
  const empty = {
    requirements: [],
    work_orders: [],
    expedites: [],
    receipts: [],
    handoffs: [],
    coverage_issues: [],
    source_modes: [],
    total: 0,
  };
  const api = {
    materialProject: vi.fn().mockImplementation((id: string) =>
      id === project.id
        ? new Promise((r) => {
            finish = r;
          })
        : Promise.resolve(empty),
    ),
  };
  const props = {
    api: api as never,
    project: { ...project, mode: "oem" as const },
    readOnly: false,
    onChanged: () => {},
    onOpen: () => {},
    onDirty: () => {},
    requestLeave: (f: () => void) => f(),
  };
  await act(async () => root.render(<SupplyWorkspace {...props} />));
  await act(async () =>
    root.render(
      <SupplyWorkspace
        {...props}
        project={{ ...props.project, id: "other" }}
      />,
    ),
  );
  await flush();
  await act(async () =>
    finish({
      ...empty,
      requirements: [{ id: "old", material_id: "旧项目秘密" }],
    }),
  );
  expect(host.textContent).not.toContain("旧项目秘密");
  expect(host.textContent).toContain("暂无物料需求");
});
it("lists project tasks with links to their product task panels", async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const open = vi.fn();
  const api = {
    materialProject: vi.fn().mockResolvedValue({
      requirements: [],
      work_orders: [],
      expedites: [],
      receipts: [],
      handoffs: [],
      coverage_issues: [],
      source_modes: [],
      total: 0,
    }),
    materialTasks: vi.fn().mockResolvedValue({
      items: [
        {
          id: "task",
          project_id: project.id,
          kind: "material_task",
          title: "查找齿轮",
          state: "pending",
          next_actions: [],
        },
      ],
      total: 1,
    }),
  };
  await act(async () =>
    root.render(
      <SupplyWorkspace
        api={api as never}
        project={{ ...project, mode: "oem" }}
        readOnly={false}
        onChanged={() => {}}
        onOpen={open}
        onDirty={() => {}}
        requestLeave={(f) => f()}
      />,
    ),
  );
  await flush();
  const b = [...host.querySelectorAll("button")].find(
    (x) => x.textContent === "查找齿轮",
  );
  expect(b).toBeTruthy();
  await act(async () => b!.click());
  expect(open).toHaveBeenCalledWith({
    projectId: project.id,
    kind: "material_task",
    id: "task",
  });
});
it("selects signed supplemental handoffs for trace closure", async () => {
  const { MaterialTaskPanel } =
    await import("./materialControl/MaterialTaskPanel");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const base = {
    material_lot_id: "lot",
    work_order_id: "w",
    receiver_id: "u",
    unit: "件",
    to_location: "线边",
    quantity: "2",
    receipt: { received_quantity: "2", received_location: "线边" },
  };
  const api = {
    object: vi.fn().mockResolvedValue({
      summary: { title: "查料", next_actions: ["material_task.close"] },
      value: {
        task_kind: "trace",
        state: "processing",
        note: "查料",
        requirement_id: "r",
        handoff_id: "h1",
        history: [],
      },
    }),
    materialRequirement: vi.fn().mockResolvedValue({
      handoffs: [
        { ...base, id: "h1", handoff_number: "原交料" },
        { ...base, id: "h2", handoff_number: "补充交料" },
        { ...base, id: "h3", handoff_number: "未签收", receipt: null },
      ],
    }),
    command: vi.fn().mockResolvedValue({
      project_id: project.id,
      project_version: 4,
      operation_id: "x",
    }),
  };
  await act(async () =>
    root.render(
      <MaterialTaskPanel
        api={api as never}
        project={{
          ...project,
          allowed_actions: ["material_task.close"] as never,
        }}
        taskId="t"
        readOnly={false}
        onChanged={() => {}}
        onDirty={() => {}}
      />,
    ),
  );
  await flush();
  const click = async (t: string) => {
    const b = [...host.querySelectorAll("button")].find(
      (x) => x.textContent === t,
    );
    expect(b).toBeTruthy();
    await act(async () => b!.click());
    await flush();
  };
  await click("完成任务");
  expect(host.textContent).toContain("补充交料");
  expect(host.textContent).not.toContain("未签收");
  const check = host.querySelector("input[type=checkbox]") as HTMLInputElement;
  await act(async () => check.click());
  const e = host.querySelector('[aria-label="完成说明"]') as HTMLInputElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(e, "已签收");
    e.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await click("提交");
  expect(api.command).toHaveBeenCalledWith(
    project.id,
    expect.objectContaining({
      action: "material_task.close",
      handoff_ids: ["h2"],
    }),
  );
});
it("records an IQC result for the task receipt directly", async () => {
  const { MaterialTaskPanel } =
    await import("./materialControl/MaterialTaskPanel");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const api = {
    object: vi.fn().mockImplementation(async (_p: string, k: string) =>
      k === "receipt"
        ? { summary: { next_actions: ["supply.inspect"] } }
        : {
            summary: {
              title: "检验",
              next_actions: ["material_task.progress"],
            },
            value: {
              task_kind: "iqc",
              state: "processing",
              note: "检验",
              receipt_id: "receipt",
              history: [],
            },
          },
    ),
    command: vi.fn().mockResolvedValue({
      project_id: project.id,
      project_version: 4,
      operation_id: "x",
    }),
  };
  await act(async () =>
    root.render(
      <MaterialTaskPanel
        api={api as never}
        project={{ ...project, allowed_actions: ["supply.inspect"] as never }}
        taskId="t"
        readOnly={false}
        onChanged={() => {}}
        onDirty={() => {}}
      />,
    ),
  );
  await flush();
  const click = async (t: string) => {
    const b = [...host.querySelectorAll("button")].find(
      (x) => x.textContent === t,
    );
    expect(b).toBeTruthy();
    await act(async () => b!.click());
  };
  await click("登记检验结果");
  for (const [name, value] of [
    ["合格数量", "8"],
    ["拒收数量", "2"],
    ["检验说明", "检验单"],
  ]) {
    const e = host.querySelector(`[aria-label="${name}"]`) as HTMLInputElement;
    expect(e).toBeTruthy();
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(e, value);
      e.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }
  await click("提交");
  await flush();
  expect(api.command).toHaveBeenCalledWith(
    project.id,
    expect.objectContaining({
      action: "supply.inspect",
      receipt_id: "receipt",
      accepted: "8",
      rejected: "2",
      evidence: "检验单",
    }),
  );
});
it("shows linked arrival and signed handoff facts for a requirement", async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const open = vi.fn();
  const api = {
    materialProject: vi.fn().mockResolvedValue({
      requirements: [
        {
          id: "r",
          material_id: "齿轮",
          work_order_id: "w",
          unit: "件",
          required: "3",
          reserved: "0",
          qualified: "2",
          shortage: "3",
          received: "3",
          rejected: "1",
          in_transit: "0",
          need_at: null,
          expedite_ids: [],
          receipt_ids: ["r1"],
          handoff_ids: ["h1"],
        },
      ],
      work_orders: [],
      expedites: [],
      receipts: [
        {
          id: "r1",
          quantity: "3",
          unit: "件",
          qualified: "2",
          rejected: "1",
          uninspected: "0",
        },
      ],
      handoffs: [
        {
          id: "h1",
          handoff_number: "交料 1",
          quantity: "3",
          unit: "件",
          from_location: "仓库",
          to_location: "线边",
          receipt: { received_quantity: "2", received_location: "线边" },
        },
      ],
      coverage_issues: [],
      source_modes: [],
      total: 1,
    }),
  };
  await act(async () =>
    root.render(
      <SupplyWorkspace
        api={api as never}
        project={{ ...project, mode: "oem" }}
        readOnly
        onChanged={() => {}}
        onOpen={open}
        onDirty={() => {}}
        requestLeave={(f) => f()}
      />,
    ),
  );
  await flush();
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((b) => b.textContent === "齿轮")!
      .click(),
  );
  expect(host.textContent).toContain("已签收 2 件");
  expect(host.textContent).toContain("检验合格 2 件");
});
it("filters requirements by work order and material without inventing totals", async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const req = (id: string, material_id: string, work_order_id: string) => ({
    id,
    material_id,
    work_order_id,
    unit: "件",
    required: "1",
    reserved: "0",
    qualified: "0",
    shortage: "1",
    received: "0",
    rejected: "0",
    in_transit: "0",
    need_at: null,
    expedite_ids: [],
    receipt_ids: [],
    handoff_ids: [],
  });
  const api = {
    materialProject: vi.fn().mockResolvedValue({
      requirements: [req("r1", "齿轮", "w1"), req("r2", "轴承", "w2")],
      work_orders: [
        { id: "w1", title: "工单甲" },
        { id: "w2", title: "工单乙" },
      ],
      expedites: [],
      receipts: [],
      handoffs: [],
      coverage_issues: ["fixed disclaimer"],
      source_modes: [],
      total: 2,
    }),
  };
  await act(async () =>
    root.render(
      <SupplyWorkspace
        api={api as never}
        project={{ ...project, mode: "oem" }}
        readOnly
        onChanged={() => {}}
        onOpen={() => {}}
        onDirty={() => {}}
        requestLeave={(f) => f()}
      />,
    ),
  );
  await flush();
  expect(host.textContent).not.toContain("部分料况尚未取得");
  const e = host.querySelector(
    '[aria-label="筛选本页工单"]',
  ) as HTMLSelectElement;
  expect(e).toBeTruthy();
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLSelectElement.prototype,
      "value",
    )!.set!.call(e, "w1");
    e.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(host.textContent).toContain("齿轮");
  expect(host.textContent).not.toContain("轴承");
});
it("retries an unchanged expedite with the same operation identity", async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const api = {
    materialProject: vi.fn().mockResolvedValue({
      requirements: [
        {
          id: "r",
          material_id: "齿轮",
          work_order_id: "w",
          unit: "件",
          required: "1",
          reserved: "0",
          qualified: "0",
          shortage: "1",
          received: "0",
          rejected: "0",
          in_transit: "0",
          need_at: null,
          expedite_ids: [],
          receipt_ids: [],
          handoff_ids: [],
        },
      ],
      work_orders: [],
      expedites: [],
      receipts: [],
      handoffs: [],
      coverage_issues: [],
      source_modes: [],
      total: 1,
    }),
    command: vi.fn().mockRejectedValue(new Error("网络中断")),
  };
  await act(async () =>
    root.render(
      <SupplyWorkspace
        api={api as never}
        project={{
          ...project,
          mode: "oem",
          allowed_actions: ["expedite.open"] as never,
        }}
        readOnly={false}
        onChanged={() => {}}
        onOpen={() => {}}
        onDirty={() => {}}
        requestLeave={(f) => f()}
      />,
    ),
  );
  await flush();
  const click = async (t: string) => {
    await act(async () =>
      [...host.querySelectorAll("button")]
        .find((x) => x.textContent === t)!
        .click(),
    );
    await flush();
  };
  await click("齿轮");
  await click("发起催料");
  for (const [name, value] of [
    ["催料原因", "缺料"],
    ["影响", "等待"],
  ]) {
    const e = host.querySelector(`[aria-label="${name}"]`) as HTMLInputElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(e, value);
      e.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }
  await click("提交催料");
  await click("提交催料");
  expect(api.command.mock.calls[1][1].operation_id).toBe(
    api.command.mock.calls[0][1].operation_id,
  );
});
it("disables an open task draft if authorization is revoked", async () => {
  const { MaterialTaskPanel } =
    await import("./materialControl/MaterialTaskPanel");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const api = {
    object: vi.fn().mockResolvedValue({
      summary: { title: "任务", next_actions: ["material_task.progress"] },
      value: {
        task_kind: "trace",
        state: "processing",
        note: "查料",
        history: [],
      },
    }),
    command: vi.fn(),
  };
  const props = {
    api: api as never,
    project: {
      ...project,
      allowed_actions: ["material_task.progress"] as never,
    },
    taskId: "t",
    readOnly: false,
    onChanged: () => {},
    onDirty: () => {},
  };
  await act(async () => root.render(<MaterialTaskPanel {...props} />));
  await flush();
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((x) => x.textContent === "更新进展")!
      .click(),
  );
  const e = host.querySelector('[aria-label="进展"]') as HTMLInputElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(e, "草稿");
    e.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => root.render(<MaterialTaskPanel {...props} readOnly />));
  expect(
    (host.querySelector('[aria-label="进展"]') as HTMLInputElement).value,
  ).toBe("草稿");
  expect(
    (
      [...host.querySelectorAll("button")].find(
        (x) => x.textContent === "提交",
      ) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});
it("opens a material task from my tasks and returns to the same list", async () => {
  const { workflowView, bootstrap } = await import("./testHelpers");
  const task = {
    id: "t",
    project_id: project.id,
    kind: "material_task",
    title: "我的检验",
    state: "pending",
    quantity: null,
    unit: null,
    version: 1,
    blocking_reasons: [],
    next_actions: ["material_task.accept"],
  };
  const p = {
    ...project,
    mode: "oem" as const,
    allowed_actions: ["material_task.accept"] as never,
  };
  const view = await workflowView({
    readProjects: async () => [p],
    readProject: async () => p,
    readTasks: async () => ({
      items: [
        {
          category: "business",
          title: "待接单",
          target: task as never,
          owner_id: "u",
          owner_name: "王检",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
      truncated: false,
    }),
    readObject: async () =>
      ({
        summary: task,
        value: {
          kind: "material_task",
          task_kind: "iqc",
          state: "pending",
          note: "我的检验",
          history: [],
        },
        relations: [],
        history: [],
        evidence: [],
      }) as never,
    options: { bootstrap },
  });
  try {
    await view.click("事项");
    await view.click("我的检验");
    expect(view.host.querySelector('[aria-label="物料任务"]')).toBeTruthy();
    await view.click("返回业务列表");
    expect(
      view.host.querySelector('[aria-label="我的待处理事项"]'),
    ).toBeTruthy();
  } finally {
    await view.dispose();
  }
});
it("preserves a material draft if the project refresh fails", async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const page = {
    requirements: [
      {
        id: "r",
        material_id: "齿轮",
        work_order_id: "w",
        unit: "件",
        required: "1",
        reserved: "0",
        qualified: "0",
        shortage: "1",
        received: "0",
        rejected: "0",
        in_transit: "0",
        need_at: null,
        expedite_ids: [],
        receipt_ids: [],
        handoff_ids: [],
      },
    ],
    work_orders: [],
    expedites: [],
    receipts: [],
    handoffs: [],
    coverage_issues: [],
    source_modes: [],
    total: 1,
  };
  const api = {
    materialProject: vi
      .fn()
      .mockResolvedValueOnce(page)
      .mockRejectedValue(new Error("刷新失败")),
  };
  const props = {
    api: api as never,
    project: {
      ...project,
      mode: "oem" as const,
      allowed_actions: ["expedite.open"] as never,
    },
    readOnly: false,
    onChanged: () => {},
    onOpen: () => {},
    onDirty: () => {},
    requestLeave: (f: () => void) => f(),
  };
  await act(async () => root.render(<SupplyWorkspace {...props} />));
  await flush();
  for (const t of ["齿轮", "发起催料"])
    await act(async () =>
      [...host.querySelectorAll("button")]
        .find((b) => b.textContent === t)!
        .click(),
    );
  const e = host.querySelector('[aria-label="催料原因"]') as HTMLInputElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(e, "保留草稿");
    e.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    root.render(
      <SupplyWorkspace {...props} project={{ ...props.project, version: 4 }} />,
    ),
  );
  await flush();
  expect(
    (host.querySelector('[aria-label="催料原因"]') as HTMLInputElement)?.value,
  ).toBe("保留草稿");
  expect(host.textContent).toContain("刷新失败");
  expect(
    host.querySelector("button:disabled") as HTMLButtonElement,
  ).toBeTruthy();
});
it("keeps only one material action open before drafts are entered", async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const page = {
    requirements: [
      {
        id: "r",
        material_id: "齿轮",
        work_order_id: "w",
        unit: "件",
        required: "1",
        reserved: "0",
        qualified: "0",
        shortage: "1",
        received: "0",
        rejected: "0",
        in_transit: "0",
        need_at: null,
        expedite_ids: [],
        receipt_ids: [],
        handoff_ids: [],
      },
    ],
    work_orders: [],
    expedites: [],
    receipts: [],
    handoffs: [],
    coverage_issues: [],
    source_modes: [],
    total: 1,
  };
  const api = {
    materialProject: vi.fn().mockResolvedValue(page),
    materialAssignees: vi.fn().mockResolvedValue({ items: [] }),
  };
  await act(async () =>
    root.render(
      <SupplyWorkspace
        api={api as never}
        project={{
          ...project,
          mode: "oem",
          allowed_actions: ["expedite.open", "material_task.open"] as never,
        }}
        readOnly={false}
        onChanged={() => {}}
        onOpen={() => {}}
        onDirty={() => {}}
        requestLeave={(f) => f()}
      />,
    ),
  );
  await flush();
  for (const t of ["齿轮", "发起催料", "安排检验"]) {
    await act(async () =>
      [...host.querySelectorAll("button")]
        .find((b) => b.textContent === t)!
        .click(),
    );
    await flush();
  }
  expect(host.querySelector('[aria-label="催料原因"]')).toBeNull();
  expect(host.querySelector('[aria-label="任务说明"]')).toBeTruthy();
});
it("shows original receipt quantities and complete named task history", async () => {
  const { MaterialTaskPanel } =
    await import("./materialControl/MaterialTaskPanel");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const api = {
    object: vi.fn().mockImplementation(async (_p: string, k: string) =>
      k === "receipt"
        ? {
            summary: { title: "到货单 A", next_actions: ["supply.inspect"] },
            value: {
              kind: "receipt",
              material_lot_id: "lot",
              quantity: "10",
              unit: "kg",
              accepted: "7",
              rejected: "2",
              uninspected: "1",
              quantity_state: "partially_inspected",
            },
          }
        : k === "material_lot"
          ? { summary: { title: "批次 A" }, value: { kind: "material_lot" } }
          : {
              summary: { title: "检验", next_actions: [] },
              value: {
                task_kind: "iqc",
                state: "processing",
                note: "检验",
                receipt_id: "rec",
                history: [
                  {
                    action: "progress",
                    actor_name: "王检",
                    recorded_at: "2026-01-01",
                    note: "继续",
                    blocked_reason: "等样品",
                  },
                ],
              },
            },
    ),
  };
  await act(async () =>
    root.render(
      <MaterialTaskPanel
        api={api as never}
        project={project}
        taskId="t"
        readOnly
        onChanged={() => {}}
        onDirty={() => {}}
      />,
    ),
  );
  await flush();
  expect(host.textContent).toContain("到货单 A");
  expect(host.textContent).toContain("批次 A");
  expect(host.textContent).toContain("待检 1 kg");
  expect(host.textContent).toContain("等样品");
  expect(host.textContent).toContain("王检");
});
it("loads complete expedite history beyond the preview", async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const req = {
    id: "r",
    material_id: "齿轮",
    work_order_id: "w",
    unit: "件",
    required: "1",
    reserved: "0",
    qualified: "0",
    shortage: "1",
    received: "0",
    rejected: "0",
    in_transit: "0",
    need_at: null,
    expedite_ids: ["e"],
    receipt_ids: [],
    handoff_ids: [],
  };
  const api = {
    materialProject: vi.fn().mockResolvedValue({
      requirements: [req],
      work_orders: [],
      expedites: [
        {
          id: "e",
          requirement_id: "r",
          expedite_number: "催料一",
          state: "open",
          reason: "缺料",
          progress: [{ note: "早期" }],
          progress_total: 21,
          progress_truncated: true,
        },
      ],
      receipts: [],
      handoffs: [],
      coverage_issues: [],
      source_modes: [],
      total: 1,
    }),
    object: vi.fn().mockResolvedValue({
      value: {
        kind: "material_expedite",
        progress: [{ note: "早期" }, { note: "第21条" }],
      },
    }),
  };
  await act(async () =>
    root.render(
      <SupplyWorkspace
        api={api as never}
        project={{ ...project, mode: "oem" }}
        readOnly
        onChanged={() => {}}
        onOpen={() => {}}
        onDirty={() => {}}
        requestLeave={(f) => f()}
      />,
    ),
  );
  await flush();
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((b) => b.textContent === "齿轮")!
      .click(),
  );
  const b = [...host.querySelectorAll("button")].find(
    (b) => b.textContent === "查看全部催料进展",
  );
  expect(b).toBeTruthy();
  await act(async () => b!.click());
  await flush();
  expect(host.textContent).toContain("第21条");
});
it("can read later signed handoffs for trace completion", async () => {
  const { MaterialTaskPanel } =
    await import("./materialControl/MaterialTaskPanel");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const base = {
    kind: "material_handoff",
    material_lot_id: "lot",
    work_order_id: "w",
    receiver_id: "u",
    unit: "件",
    to_location: "线边",
    quantity: "2",
    receipt: { received_quantity: "2", received_location: "线边" },
  };
  const original = { ...base, id: "h1", handoff_number: "原记录" },
    later = { ...base, id: "h2", handoff_number: "后续签收" };
  const api = {
    object: vi
      .fn()
      .mockImplementation(async (_p: string, k: string, id: string) =>
        k === "material_task"
          ? {
              summary: { next_actions: ["material_task.close"] },
              value: {
                task_kind: "trace",
                state: "processing",
                note: "查料",
                requirement_id: "r",
                handoff_id: "h1",
                history: [],
              },
            }
          : { summary: { title: id }, value: id === "h1" ? original : later },
      ),
    materialRequirement: vi
      .fn()
      .mockResolvedValue({ handoffs: [original], requirements: [] }),
    objects: vi.fn().mockResolvedValue({
      items: [{ id: "h2" }],
      total: 1,
      offset: 0,
      limit: 50,
    }),
  };
  await act(async () =>
    root.render(
      <MaterialTaskPanel
        api={api as never}
        project={{
          ...project,
          allowed_actions: ["material_task.close"] as never,
        }}
        taskId="t"
        readOnly={false}
        onChanged={() => {}}
        onDirty={() => {}}
      />,
    ),
  );
  await flush();
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((b) => b.textContent === "完成任务")!
      .click(),
  );
  await flush();
  const b = [...host.querySelectorAll("button")].find(
    (b) => b.textContent === "查找更多签收记录",
  );
  expect(b).toBeTruthy();
  await act(async () => b!.click());
  await flush();
  expect(host.textContent).toContain("后续签收");
});
it("does not replace trace assignees with a late IQC response", async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  let finish!: (v: unknown) => void;
  const api = {
    materialProject: vi.fn().mockResolvedValue({
      requirements: [
        {
          id: "r",
          material_id: "齿轮",
          work_order_id: "w",
          unit: "件",
          required: "1",
          reserved: "0",
          qualified: "0",
          shortage: "1",
          received: "0",
          rejected: "0",
          in_transit: "0",
          need_at: null,
          expedite_ids: [],
          receipt_ids: [],
          handoff_ids: [],
        },
      ],
      work_orders: [],
      expedites: [],
      receipts: [],
      handoffs: [],
      coverage_issues: [],
      source_modes: [],
      total: 1,
    }),
    materialAssignees: vi.fn().mockImplementation((_p: string, kind: string) =>
      kind === "iqc"
        ? new Promise((r) => {
            finish = r;
          })
        : Promise.resolve({ items: [{ id: "t", display_name: "查料员" }] }),
    ),
  };
  await act(async () =>
    root.render(
      <SupplyWorkspace
        api={api as never}
        project={{
          ...project,
          mode: "oem",
          allowed_actions: ["material_task.open"] as never,
        }}
        readOnly={false}
        onChanged={() => {}}
        onOpen={() => {}}
        onDirty={() => {}}
        requestLeave={(f) => f()}
      />,
    ),
  );
  await flush();
  for (const t of ["齿轮", "安排检验", "安排查料"]) {
    await act(async () =>
      [...host.querySelectorAll("button")]
        .find((b) => b.textContent === t)!
        .click(),
    );
    await flush();
  }
  await act(async () =>
    finish({ items: [{ id: "i", display_name: "过期检验员" }] }),
  );
  expect(host.querySelector('[aria-label="查料人"]')?.textContent).toContain(
    "查料员",
  );
  expect(
    host.querySelector('[aria-label="查料人"]')?.textContent,
  ).not.toContain("过期检验员");
});
it("guards a dirty expedite before switching to task creation", async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const page = {
    requirements: [
      {
        id: "r",
        material_id: "齿轮",
        work_order_id: "w",
        unit: "件",
        required: "1",
        reserved: "0",
        qualified: "0",
        shortage: "1",
        received: "0",
        rejected: "0",
        in_transit: "0",
        need_at: null,
        expedite_ids: [],
        receipt_ids: [],
        handoff_ids: [],
      },
    ],
    work_orders: [],
    expedites: [],
    receipts: [],
    handoffs: [],
    coverage_issues: [],
    source_modes: [],
    total: 1,
  };
  let dirty = false,
    pending: (() => void) | null = null;
  const api = {
    materialProject: vi.fn().mockResolvedValue(page),
    materialAssignees: vi.fn().mockResolvedValue({ items: [] }),
  };
  await act(async () =>
    root.render(
      <SupplyWorkspace
        api={api as never}
        project={{
          ...project,
          mode: "oem",
          allowed_actions: ["expedite.open", "material_task.open"] as never,
        }}
        readOnly={false}
        onChanged={() => {}}
        onOpen={() => {}}
        onDirty={(_k, v) => {
          dirty = v;
        }}
        requestLeave={(f) => {
          if (dirty) pending = f;
          else f();
        }}
      />,
    ),
  );
  await flush();
  for (const t of ["齿轮", "发起催料"])
    await act(async () =>
      [...host.querySelectorAll("button")]
        .find((b) => b.textContent === t)!
        .click(),
    );
  const e = host.querySelector('[aria-label="催料原因"]') as HTMLInputElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(e, "草稿");
    e.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((b) => b.textContent === "安排检验")!
      .click(),
  );
  expect(
    (host.querySelector('[aria-label="催料原因"]') as HTMLInputElement).value,
  ).toBe("草稿");
  expect(host.querySelector('[aria-label="任务说明"]')).toBeNull();
  expect(pending).toBeTruthy();
  await act(async () => pending!());
  expect(host.querySelector('[aria-label="催料原因"]')).toBeNull();
  expect(host.querySelector('[aria-label="任务说明"]')).toBeTruthy();
});
it("shows the actual task owner and proposed recipient in the project queue", async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const api = {
    materialProject: vi
      .fn()
      .mockResolvedValue({
        requirements: [],
        work_orders: [],
        expedites: [],
        receipts: [],
        handoffs: [],
        coverage_issues: [],
        source_modes: [],
        total: 0,
      }),
    materialTasks: vi
      .fn()
      .mockResolvedValue({
        items: [{ id: "t", title: "查找齿轮", state: "processing" }],
        total: 2,
      }),
    object: vi
      .fn()
      .mockResolvedValue({
        value: {
          kind: "material_task",
          task_kind: "trace",
          assignee_id: "a",
          proposed_assignee_id: "b",
        },
      }),
    materialAssignees: vi.fn().mockResolvedValue({
      items: [
        { id: "a", display_name: "张工" },
        { id: "b", display_name: "李工" },
      ],
    }),
  };
  await act(async () =>
    root.render(
      <SupplyWorkspace
        api={api as never}
        project={{ ...project, mode: "oem" }}
        readOnly
        onChanged={() => {}}
        onOpen={() => {}}
        onDirty={() => {}}
        requestLeave={(f) => f()}
      />,
    ),
  );
  await flush();
  expect(host.textContent).toContain("负责人：张工");
  expect(host.textContent).toContain("待接收：李工");
  expect(host.textContent).toContain("本页 1 条，共 2 条");
});
