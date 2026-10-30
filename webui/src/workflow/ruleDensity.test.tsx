import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";
import { ObjectTable } from "./OrdersWorkspace";
import type { ObjectSummary, SourceRef } from "./types";
import { workflowView, project } from "./testHelpers";

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
const source: SourceRef = {
  system: "ERP",
  object_type: "order_line",
  external_id: "INTERNAL-ERP-987",
  version: 12,
  mode: "mock",
  occurred_at: "2026-10-30T00:00:00Z",
  collected_at: "2026-10-30T00:01:00Z",
  cutoff: null,
  evidence: "核对文件",
};
const row: ObjectSummary = {
  id: "item-1",
  project_id: project.id,
  kind: "order_line",
  title: "相机订单",
  state: "blocked",
  quantity: "8",
  unit: "件",
  source,
  version: 2,
  blocking_reasons: ["待发运"],
  next_actions: [],
};

it("keeps provenance mode and blocking visible without verbose source identity in project rows", async () => {
  await act(async () => root.render(<ObjectTable items={[row]} onOpen={() => {}} />));
  const text = host.querySelector("tr.wf-attention-row")?.textContent || "";
  expect(text).toContain("模拟系统");
  expect(text).toContain("待发运");
  expect(text).not.toContain("INTERNAL-ERP-987");
  expect(text).not.toContain("12");
});

it("keeps provenance mode and blocking visible without verbose source identity in global rows", async () => {
  const view = await workflowView({ readLedger: async (_kind, limit, offset) => ({ items: [row], total: 1, limit, offset }) });
  try {
    await view.click("订单与交付");
    const text = view.host.querySelector("tr.wf-attention-row")?.textContent || "";
    expect(text).toContain("模拟系统");
    expect(text).toContain("待发运");
    expect(text).not.toContain("INTERNAL-ERP-987");
    expect(text).not.toContain("版本 12");
  } finally {
    await view.dispose();
  }
});

it("keeps source mode visible while collapsing full provenance", async () => {
  const { Source } = await import("./WorkflowDetail");
  await act(async () => root.render(<Source value={source} />));
  const disclosure = host.querySelector("details");
  expect(disclosure).not.toBeNull();
  expect(disclosure!.open).toBe(false);
  expect(disclosure!.querySelector("summary")?.textContent).toContain("模拟系统");
  expect(disclosure!.textContent).toContain("INTERNAL-ERP-987");
});

it("keeps readiness blockers visible and collapses explanatory versions", async () => {
  const { DetailContent } = await import("./WorkflowDetail");
  const readiness = {
    ready: false,
    checks: [{kind: "material", required: true, status: "blocked", reason: "缺少物料", evidence_ids: []}],
    input_versions: {project: "7", revision: "M2"},
  };
  const detail = {
    summary: {...row, kind: "work_order", source: null},
    value: {
      kind: "work_order", quantity: "8", unit: "件", remaining_obligation: "8",
      purpose: "production", trial_quantity: "1", planned_start: "2026-11-01", planned_end: "2026-11-02",
      trial_readiness: readiness, bulk_readiness: readiness, held_start_scopes: [], execution_events: [],
    },
    relations: [], evidence: [], history: [],
  };
  await act(async () => root.render(<DetailContent data={detail as any} onOpen={() => {}} />));
  expect(host.textContent).toContain("缺少物料");
  const disclosure = [...host.querySelectorAll("details")].find(d => d.querySelector("summary")?.textContent?.includes("依据版本"));
  expect(disclosure).toBeTruthy();
  expect(disclosure!.open).toBe(false);
  expect(disclosure!.textContent).toContain("M2");
});

it("puts static supply rules behind operation help", async () => {
  const view = await workflowView({ initial: "计划与物料", projectContext: true });
  try {
    const help = [...view.host.querySelectorAll("details")].find(d => d.querySelector("summary")?.textContent === "操作说明");
    expect(help).toBeTruthy();
    expect(help!.open).toBe(false);
    expect(help!.textContent).toContain("库存预留由权威系统原子接受");
  } finally {
    await view.dispose();
  }
});
