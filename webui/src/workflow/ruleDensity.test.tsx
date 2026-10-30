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
