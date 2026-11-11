import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { Compare, EventSidebar, Parameters, RecordTable } from "./details";
import { InvestigationPanel, type InvestigationController } from "./investigations";
import type { Api } from "./boards";
import type { Location } from "./context";
import type { Investigation, ProductionPage, ViewedEvent } from "./types";
const host = document.createElement("div");
document.body.append(host);
const root = createRoot(host);
async function render(children: ReactNode) { await act(async () => root.render(children)); }
afterEach(async () => { await act(async () => root.render(null)); });
const scope = { start: "2026-11-10T00:00:00Z", end: "2026-11-10T08:00:00Z", status: "2" as const };
const location: Location = { projectId: "7", labels: {}, inherited: false, view: "history", scope, historySN: "SN-A" };
const event: ViewedEvent = { snapshot_id: "capture-a", offset: 12, kind: "production", projectId: "7", captured_at: scope.end, row: { timestamp: scope.start, sn: "SN-A", status: "2", softwareid: "8", devicename: "PC07", measurement: 12 } };
const page: ProductionPage = { snapshot_id: event.snapshot_id, source_namespace: "native", source_project_id: "7", source_kind: "production", captured_at: scope.end, expires_at: scope.end, items: [event.row, { ...event.row, status: "1" }, { ...event.row, status: "PASS" }], filters: scope, complete: false, truncation_reason: "limit", next_before_id: null, redacted_fields: [], offset: 12, limit: 3, captured_count: 15, has_more: true };
const selection = { snapshot_id: event.snapshot_id, offset: 12, source_kind: "production" as const, descriptor: event.row, fingerprint: "saved" };
const draft: Investigation = { id: "draft-a", source_namespace: "native", source_project_id: "7", owner_id: "me", version: 3, created_at: scope.start, updated_at: scope.start, expires_at: scope.end, context: { ...scope, view: "history" }, primary: selection, comparison: { ...selection, descriptor: { ...event.row, status: "1" } }, logs: [], note: "待确认", impact: null };
function controller(overrides = {}): InvestigationController {
  return { draft, handoff: null, state: "已保存", note: "待确认", dirty: false, error: "", canStart: true, list: [], resolved: null, conflict: null, browsingOtherScope: false, logBusy: false, start: vi.fn(), generate: vi.fn(), restore: vi.fn(), setNote: vi.fn(), resolve: vi.fn(), removeComparison: vi.fn(), ...overrides } as unknown as InvestigationController;
}
const button = (label: string) => [...host.querySelectorAll("button")].find((n) => n.textContent === label)!;
it("uses explicit source result pills and symptom attention while preserving captured actions", async () => {
  const go = vi.fn(), inspect = vi.fn();
  await render(<RecordTable page={page} location={location} go={go} inspect={inspect} />);
  const rows = [...host.querySelectorAll("tbody tr")];
  expect(rows.map((row) => row.querySelector("[data-tone]")?.getAttribute("data-tone"))).toEqual(["danger", "success", "neutral"]);
  expect(rows[2].textContent).toContain("结果未知（PASS）");
  expect(rows[0].textContent).toContain("原症状命中");
  expect(host.textContent).toContain("部分结果未显示，请缩小范围");
  await act(async () => button("查看测试 1").click());
  expect(inspect).toHaveBeenCalledWith(event);
  await act(async () => button("下一页").click());
  expect(go.mock.calls[0][0].cursor).toEqual({ id: "capture-a", offset: 15, limit: 3, kind: "production" });
});
it("groups drawer facts, metadata, selection and parameters with stable actions", async () => {
  const onPrimary = vi.fn(), close = vi.fn();
  await render(<EventSidebar api={{} as Api} event={event} location={location} go={vi.fn()} close={close} investigation={draft} readOnly={false} onPrimary={onPrimary} onComparison={vi.fn()} onLog={vi.fn()} logBusy={false} onEvidenceScope={vi.fn()} />);
  expect(host.querySelector("header")?.textContent).toContain("生产测试详情");
  for (const label of ["事件核心事实", "相关记录", "调查选择", "测试项与参数"]) expect(host.querySelector(`section[aria-label="${label}"]`)).not.toBeNull();
  expect(host.querySelector('[aria-label="调查选择"]')?.textContent).toContain("当前主要事件");
  expect(host.querySelector('[aria-label="调查选择"]')?.textContent).toContain("当前对照事件");
  await act(async () => button("设为调查对象").click());
  expect(onPrimary).toHaveBeenCalledWith(event);
  await act(async () => button("关闭测试详情").click());
  expect(close).toHaveBeenCalledTimes(1);
});
it("makes comparison roles and source differences readable", async () => {
  await render(<Compare primary={event} comparison={{ ...event, row: { ...event.row, status: "1", measurement: 10 } }} />);
  expect(host.querySelector('section[aria-label="主要事件"]')?.textContent).toContain("失败 FAIL");
  expect(host.querySelector('section[aria-label="对照事件"]')?.textContent).toContain("通过 PASS");
  const measurement = [...host.querySelectorAll("tbody tr")].find((row) => row.textContent?.includes("measurement"))!;
  expect(measurement.querySelector('[data-tone="warning"]')?.textContent).toBe("不同");
  expect(measurement.textContent).toContain("12");
  expect(measurement.textContent).toContain("10");
});
it("keeps parameters searchable and distinguishes a search miss from missing source values", async () => {
  await render(<Parameters row={event.row} />);
  const input = host.querySelector("input")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "absent");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(host.textContent).toContain("没有匹配的参数");
  expect(host.textContent).not.toContain("源未提供有值测试参数");
});
it("separates investigation evidence, notes and always-visible handoff recovery", async () => {
  const c = controller();
  await render(<InvestigationPanel controller={c} readOnly={false} onCompare={vi.fn()} onCandidate={vi.fn()} />);
  for (const label of ["主要事件", "对照事件", "调查备注", "交接与恢复"]) expect(host.querySelector(`section[aria-label="${label}"]`)).not.toBeNull();
  expect(host.querySelector("header [role=status]")?.textContent).toContain("已保存");
  expect(button("读取交接").closest("details")).toBeNull();
  expect(host.querySelector('[aria-label="日志引用"]')).toBeNull();
  await act(async () => button("生成交接摘要").click());
  expect(c.generate).toHaveBeenCalledTimes(1);
});
it("preserves visible conflict recovery and readonly restrictions", async () => {
  const acceptServer = vi.fn(), retainLocal = vi.fn();
  const c = controller({ state: "修订冲突", conflict: { ...draft, version: 4, note: "服务端备注" }, acceptServer, retainLocal });
  await render(<InvestigationPanel controller={c} readOnly onCompare={vi.fn()} onCandidate={vi.fn()} />);
  expect(host.querySelector('[role="alert"]')?.textContent).toContain("服务端内容");
  expect(button("生成交接摘要").disabled).toBe(true);
  expect(host.querySelector("textarea")!.disabled).toBe(true);
  expect(host.textContent).toContain("只读管理员");
  await act(async () => button("采用服务端版本").click());
  expect(acceptServer).toHaveBeenCalledTimes(1);
});
it("keeps investigation roles visible while browsing candidate logs", async () => {
  const api = { productionStatus: vi.fn(async () => ({ configured: true, capabilities: {} })) } as unknown as Api;
  await render(<EventSidebar api={api} event={event} location={location} go={vi.fn()} close={vi.fn()} investigation={draft} readOnly={false} onPrimary={vi.fn()} onComparison={vi.fn()} onLog={vi.fn()} logBusy={false} onEvidenceScope={vi.fn()} />);
  await act(async () => button("查找候选日志").click());
  expect(host.querySelector('section[aria-label="候选日志"]')).not.toBeNull();
  expect(host.querySelector('section[aria-label="调查选择"]')?.textContent).toContain("当前主要事件");
  expect(host.querySelector('section[aria-label="调查选择"]')?.textContent).toContain("当前对照事件");
});
it("keeps fixed handoff fork and restore operations available without changing saved content", async () => {
  const fork = vi.fn(), restore = vi.fn();
  const c = controller({ handoff: draft, fork, restore });
  await render(<InvestigationPanel controller={c} readOnly={false} onCompare={vi.fn()} onCandidate={vi.fn()} />);
  expect(host.querySelector('[aria-label="固定交接内容"]')?.textContent).toContain("交接时内容 · 不随源更新");
  expect(host.querySelector("textarea")!.disabled).toBe(true);
  await act(async () => button("另存为我的调查").click());
  expect(fork).toHaveBeenCalledTimes(1);
  const input = host.querySelector<HTMLInputElement>('[aria-label="交接号或内部恢复链接"]')!;
  const id = "33333333-3333-4333-8333-333333333333";
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, id);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => button("读取交接").click());
  expect(restore).toHaveBeenCalledWith(id, true);
});
