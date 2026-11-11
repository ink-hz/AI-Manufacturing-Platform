// @vitest-environment jsdom
import { expect, it } from "vitest";
import { workflowView, project, order } from "./testHelpers";
import type {
  MaterialProject,
  MaterialRequirement,
} from "./materialControl/types";
import type { ObjectSummary } from "./types";
it("returns to the filtered second requirement and task pages after opening a project task", async () => {
  const p = { ...project, mode: "oem" as const };
  const requirement = (n: number): MaterialRequirement => ({
    id: "r" + n,
    work_order_id: "w",
    material_id: n === 50 ? "齿轮目标" : "物料" + n,
    owner_id: "客户",
    unit: "件",
    required: "1",
    received: "0",
    qualified: "0",
    rejected: "0",
    reserved: "0",
    shortage: "1",
    in_transit: "0",
    need_at: null,
    need_at_basis: "work_order_planned_start_proxy",
    coverage_issues: [],
    expedite_ids: [],
    receipt_ids: [],
    handoff_ids: [],
  });
  const summary = (n: number): ObjectSummary => ({
    ...order,
    id: "t" + n,
    kind: "material_task",
    title: n === 50 ? "目标任务" : "任务" + n,
    state: "pending",
    next_actions: [],
  });
  const view = await workflowView({
    readTasks: async () => ({
      items: [
        {
          category: "business",
          title: "待处理",
          target: summary(50),
          owner_id: "owner",
          owner_name: "责任人",
        },
      ],
      total: 1,
      limit: 50,
      offset: 0,
      truncated: false,
    }),
    readProjects: async () => [p],
    readProject: async () => p,
    readMaterialProject: async (offset) =>
      ({
        project_id: p.id,
        project_version: p.version,
        read_at: "",
        coverage_issues: [],
        source_modes: [],
        work_orders: [{ id: "w", title: "工单甲" }],
        requirements:
          offset === 0
            ? Array.from({ length: 50 }, (_, n) => requirement(n))
            : [requirement(50)],
        expedites: [],
        receipts: [],
        handoffs: [],
        issue_marks: [],
        material_task_counts: { pending: 51 },
        total: 51,
        limit: 50,
        offset,
      }) as MaterialProject,
    readMaterialTasks: async (offset) => ({
      items:
        offset === 0
          ? Array.from({ length: 50 }, (_, n) => summary(n))
          : [summary(50)],
      total: 51,
      limit: 50,
      offset,
    }),
    readObject: async (_id, kind, id) =>
      kind === "material_task"
        ? ({
            summary: summary(50),
            value: {
              kind: "material_task",
              task_kind: "trace",
              state: "pending",
              note: "目标任务",
              history: [],
              receipt_id: null,
              handoff_id: null,
            },
            relations: [],
            history: [],
            evidence: [],
          } as never)
        : ({
            summary: { ...order, id },
            value: { kind: "material_lot" },
          } as never),
  });
  try {
    await view.click("制造项目");
    await view.click(p.name);
    await view.click("供应与物料");
    await view.click("下一页");
    await view.field("筛选本页工单", "w");
    await view.field("筛选本页物料", "齿轮");
    await view.click("齿轮目标");
    await view.click("下一页任务");
    await view.click("目标任务");
    expect(view.host.querySelector('[aria-label="物料任务"]')).toBeTruthy();
    await view.click("返回业务列表");
    expect(
      (
        view.host.querySelector(
          '[aria-label="筛选本页工单"]',
        ) as HTMLSelectElement
      ).value,
    ).toBe("w");
    expect(
      (
        view.host.querySelector(
          '[aria-label="筛选本页物料"]',
        ) as HTMLInputElement
      ).value,
    ).toBe("齿轮");
    expect(
      view.host.querySelector('[aria-label="物料需求详情"]')?.textContent,
    ).toContain("齿轮目标");
    expect(view.host.textContent).toContain("目标任务");
    expect(view.host.textContent).toContain("本页 1 条，共 51 条");
    expect(view.host.textContent).toContain("上一页任务");
    await view.click("事项");
    await view.click("目标任务");
    await view.click("返回业务列表");
    expect(
      view.host.querySelector('[aria-label="我的待处理事项"]'),
    ).toBeTruthy();
    expect(view.host.querySelector('[aria-label="料况"]')).toBeNull();
  } finally {
    await view.dispose();
  }
});
it("keeps material view state isolated by project", async () => {
  const first = { ...project, mode: "oem" as const };
  const other = { ...first, id: "another-project", name: "另一项目" };
  const view = await workflowView({
    readProjects: async () => [first, other],
    readProject: async () => first,
    readMaterialProject: async (offset, id) =>
      ({
        project_id: id,
        project_version: 3,
        read_at: "",
        coverage_issues: [],
        source_modes: [],
        work_orders: [],
        requirements: [],
        expedites: [],
        receipts: [],
        handoffs: [],
        issue_marks: [],
        material_task_counts: {},
        total: 0,
        limit: 50,
        offset,
      }) as MaterialProject,
    readMaterialTasks: async (offset) => ({
      items: [],
      total: 0,
      limit: 50,
      offset,
    }),
  });
  try {
    await view.click("制造项目");
    await view.click(first.name);
    await view.click("供应与物料");
    await view.field("筛选本页物料", "仅甲项目");
    await view.click("返回项目列表");
    await view.click(other.name);
    await view.click("供应与物料");
    expect(
      (
        view.host.querySelector(
          '[aria-label="筛选本页物料"]',
        ) as HTMLInputElement
      ).value,
    ).toBe("");
  } finally {
    await view.dispose();
  }
});
