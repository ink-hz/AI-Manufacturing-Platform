import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
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

it("keeps the laboratory device evidence limitation visible", async () => {
  const view = await workflowView({ initial: "测试与标定", projectContext: true });
  try {
    const notice = view.host.querySelector(".wf-oem-workspace > p");
    expect(notice?.textContent).toContain("设备证据为人工登记或隔离模拟");
  } finally {
    await view.dispose();
  }
});

it("loads rule advice only after the reader opens it", async () => {
  const { AssistancePanel } = await import("./AssistancePanel");
  const api = { assistance: vi.fn(async () => ({ items: [], unknowns: ["来源尚未核清"], state: "no_evidence", truncated: true })) };
  await act(async () => root.render(<AssistancePanel api={api as any} projectId="p1" version={1} onOpen={() => {}} />));
  expect(api.assistance).not.toHaveBeenCalled();
  const opener = [...host.querySelectorAll("button")].find(b => b.textContent === "查看核对建议");
  expect(opener?.getAttribute("aria-expanded")).toBe("false");
  await act(async () => opener!.click());
  expect(api.assistance).toHaveBeenCalledTimes(1);
  expect(host.querySelector('[aria-expanded="true"]')?.textContent).toBe("收起核对建议");
  expect(host.textContent).toContain("来源尚未核清");
  expect(host.textContent).toContain("分析范围有界");
});

it("does not display advice from the previous project after switching projects", async () => {
  const { AssistancePanel } = await import("./AssistancePanel");
  const pending = new Map<string, (value: any) => void>();
  const api = { assistance: vi.fn((id: string) => new Promise(resolve => pending.set(id, resolve))) };
  await act(async () => root.render(<AssistancePanel api={api as any} projectId="p1" version={1} onOpen={() => {}} />));
  const opener = [...host.querySelectorAll("button")].find(b => b.textContent === "查看核对建议");
  await act(async () => opener!.click());
  await act(async () => root.render(<AssistancePanel api={api as any} projectId="p2" version={1} onOpen={() => {}} />));
  await act(async () => pending.get("p1")!({ items: [], unknowns: ["旧项目证据"], state: "evidence_available", truncated: false }));
  expect(host.textContent).not.toContain("旧项目证据");
  await act(async () => pending.get("p2")!({ items: [], unknowns: ["新项目证据"], state: "evidence_available", truncated: false }));
  expect(host.textContent).toContain("新项目证据");
});

it("keeps each suggestion and blocker visible while detailed evidence is closed", async () => {
  const { AssistancePanel } = await import("./AssistancePanel");
  const item = (id: string) => ({
    target: { scope: "project", project_id: "p1", kind: "order_line", id },
    title: id,
    state: "blocked",
    suggestion: `建议 ${id}`,
    blockers: [`阻断 ${id}`],
    unknowns: [`未知 ${id}`],
    evidence: [`凭据 ${id}`],
    related_targets: [],
    evidence_truncated: false,
    source: id === "A" ? source : null,
  });
  const api = { assistance: vi.fn(async () => ({ items: [item("A"), item("B")], unknowns: [], state: "evidence_available", truncated: false })) };
  await act(async () => root.render(<AssistancePanel api={api as any} projectId="p1" version={1} onOpen={() => {}} />));
  await act(async () => (host.querySelector('button[aria-expanded="false"]') as HTMLButtonElement).click());
  const cards = host.querySelectorAll(".wf-assistance-item");
  expect(cards).toHaveLength(2);
  expect(cards[0].querySelector("details")?.open).toBe(false);
  expect(cards[0].querySelector("details")?.textContent).toContain("凭据 A");
  expect(cards[0].querySelector("details")?.textContent).not.toContain("建议 A");
  expect(cards[0].querySelector("h4")?.textContent).toContain("模拟系统");
  expect(cards[0].textContent).toContain("阻断 A");
  expect(cards[1].textContent).toContain("未知 B");
});

it("aborts pending advice when closed and shows errors only while open", async () => {
  const { AssistancePanel } = await import("./AssistancePanel");
  let signal: AbortSignal | undefined;
  const api = { assistance: vi.fn(async (_id: string, _kind: string, current: AbortSignal) => {
    signal = current;
    throw new Error("规则读取失败");
  }) };
  await act(async () => root.render(<AssistancePanel api={api as any} projectId="p1" version={1} onOpen={() => {}} />));
  await act(async () => (host.querySelector('button[aria-expanded="false"]') as HTMLButtonElement).click());
  expect(host.querySelector('[role="alert"]')?.textContent).toContain("规则读取失败");
  await act(async () => (host.querySelector('button[aria-expanded="true"]') as HTMLButtonElement).click());
  expect(signal?.aborted).toBe(true);
  expect(host.textContent).not.toContain("规则读取失败");
});
