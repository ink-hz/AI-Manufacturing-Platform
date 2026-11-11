import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { ActivityBoard, AnomaliesBoard, Counts, OverviewBoard, ProjectBoard, type Api } from "./boards";
import type { Aggregate, Analysis, Overview, Scope } from "./types";
import type { Location } from "./context";
const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
const scope: Scope = { start: "2026-11-10T00:02:00Z", end: "2026-11-10T00:08:00Z" };
const location: Location = { view: "project", projectId: "1", labels: { project: "项目 A" }, inherited: true, scope };
const aggregate: Aggregate = { key: "a", records: "99999999999999999999", distinct_sn: "9007199254740993", pass_records: "0", fail_records: "12", unknown_records: "3", failed_sn: "12", first_time: scope.start, last_time: scope.end };
const block = { state: "ready" as const, captured_at: scope.end, complete: true, truncation_reason: null, error: null };
const analysis = (items: Aggregate[], complete = true): Analysis => ({ source_namespace: "native", source_project_id: "1", view: "trend", captured_at: scope.end, filters: scope, items, complete, truncation_reason: null, bucket_minutes: 5 });
async function render(node: ReactNode) { await act(async () => { root.render(node); }); }
afterEach(async () => { await render(null); });
function apiFor(data: Analysis, overview?: Overview): Api { return { productionAnalysis: vi.fn(async (_id, query) => query.view === "trend" || query.view === "activity" ? data : analysis(query.view === "devices" ? [{ ...aggregate, device: "PC01" }] : [aggregate])), productionOverview: vi.fn(async () => overview) } as unknown as Api; }
const props = (api: Api, loc = location) => ({ api, location: loc, refresh: 0, go: vi.fn(), inspect: vi.fn() });
it("shows exact page-only KPI totals and distinguishes unavailable project statistics", async () => {
  const overview: Overview = { source_namespace: "native", captured_at: scope.end, complete: false, has_more: true, next_before_id: "2", items: [{ id: "1", name: "项目 A", state: "ready", statistics: aggregate, trend: [], latest_at: null, blocks: { statistics: block, trend: block, latest: block } }, { id: "2", name: "项目 B", state: "unavailable", statistics: null, trend: [], latest_at: null, blocks: { statistics: { ...block, complete: false, state: "unavailable" }, trend: block, latest: block } }] };
  await render(<OverviewBoard {...props(apiFor(analysis([]), overview))} />);
  expect(host.querySelector('[role="group"][aria-label="测试记录"]')?.textContent).toContain("99999999999999999999");
  expect(host.querySelector('[role="group"][aria-label="测试 SN"]')?.textContent).toContain("9007199254740993");
  expect(host.textContent).toContain("仅汇总本页完整统计"); expect(host.textContent).toContain("遗漏分组和时间格未知"); expect(host.textContent).toContain("本次概览实际范围"); expect(host.textContent).toContain("统计未取得，不能计作零");
});
it("keeps zero failures neutral and missing statistics visibly unknown", async () => {
  await render(<><Counts item={{ ...aggregate, fail_records: "0", failed_sn: "0" }} /><Counts item={null} /></>);
  expect(host.querySelector('[aria-label="失败涉及 SN"]')?.getAttribute("data-tone")).toBe("neutral"); expect(host.textContent).toContain("失败涉及 SN 0"); expect(host.textContent).toContain("统计未取得，不能计作零");
});
it("draws test and failure series with exact labels and reachable clamped drills", async () => {
  const data = analysis([{ ...aggregate, timestamp: "2026-11-10T00:00:00Z" }, { ...aggregate, key: "b", records: "50000000000000000000", timestamp: "2026-11-10T00:05:00Z" }], false); const p = props(apiFor(data)); await render(<ProjectBoard {...p} />);
  expect(host.querySelector('svg[aria-label="测试与失败时间趋势"]')).not.toBeNull();
  const trend = host.querySelector('[aria-label="测试趋势"]')!; expect(trend.textContent).toContain("测试记录量（含所有结果）"); expect(trend.textContent).toContain("失败记录量"); expect(trend.textContent).toContain("99999999999999999999");
  const buttons = [...trend.querySelectorAll("button")]; expect(buttons.length).toBe(2); buttons[0].focus(); expect(document.activeElement).toBe(buttons[0]);
  await act(async () => { buttons[0].click(); buttons[1].click(); });
  expect(p.go.mock.calls.map(([l]) => l.scope)).toEqual([{ ...scope, end: "2026-11-10T00:05:00.000Z", start: "2026-11-10T00:02:00.000Z" }, { ...scope, start: "2026-11-10T00:05:00.000Z", end: "2026-11-10T00:08:00.000Z" }]);
  for (const rect of host.querySelectorAll("svg rect")) expect(Number(rect.getAttribute("height"))).toBeLessThanOrEqual(120);
});
it("labels activity failure, observed, complete-empty and partial-unknown separately", async () => {
  const rows = [{ ...aggregate, device: "PC01", timestamp: "2026-11-10T00:00:00Z" }, { ...aggregate, key: "b", device: null, fail_records: "0", timestamp: "2026-11-10T00:05:00Z" }]; const p = props(apiFor(analysis(rows)), { ...location, view: "activity" }); await render(<ActivityBoard {...p} />);
  expect(host.querySelector('[data-activity="failure"]')).not.toBeNull(); expect(host.querySelector('[data-activity="observed"]')).not.toBeNull(); expect(host.querySelector('[data-activity="empty"]')).not.toBeNull(); expect(host.textContent).toContain("完整范围无事件"); expect(host.textContent).toContain("部分范围未知");
  const missing = host.querySelector<HTMLButtonElement>('td[data-activity="observed"] button')!; await act(async () => missing.click()); expect(p.go.mock.calls[0][0].scope).toMatchObject({ missing_fields: ["device"], start: "2026-11-10T00:05:00.000Z", end: "2026-11-10T00:08:00.000Z" });
  await render(<ActivityBoard {...props(apiFor(analysis(rows, false)), { ...location, view: "activity" })} />); expect(host.querySelector('[data-activity="unknown"]')).not.toBeNull();
});
it("makes the 96-bucket display limit explicit without changing the requested scope", async () => {
  const long = { ...location, view: "activity" as const, scope: { start: "2026-11-10T00:00:00Z", end: "2026-11-11T00:00:00Z" } }; await render(<ActivityBoard {...props(apiFor(analysis([{ ...aggregate, device: "PC01", timestamp: "2026-11-10T00:00:00Z" }])), long)} />);
  expect(host.querySelectorAll("thead th").length).toBe(97); expect(host.textContent).toContain("仅展示前 96 个时间格"); expect(host.textContent).toContain("其余请求时段未在此图展示"); expect(host.querySelector("thead th:nth-child(2)")?.getAttribute("title")).toBeTruthy(); expect(host.querySelector("thead th:nth-child(2)")?.getAttribute("aria-label")).toBe(host.querySelector("thead th:nth-child(2)")?.getAttribute("title"));
});

it("does not present an all-unavailable overview as zero tests", async () => {
  const unavailable = { ...block, state: "unavailable" as const, complete: false };
  const overview: Overview = { source_namespace: "native", captured_at: scope.end, complete: false, has_more: false, next_before_id: null, items: [{ id: "1", name: "项目 A", state: "unavailable", statistics: null, trend: [], latest_at: null, blocks: { statistics: unavailable, trend: unavailable, latest: unavailable } }] };
  await render(<OverviewBoard {...props(apiFor(analysis([]), overview))} />);
  expect(host.querySelector('[role="group"][aria-label="测试记录"]')?.textContent).toContain("—");
  expect(host.textContent).not.toContain("测试 SN 0");
  expect(host.textContent).not.toContain("当前无观测失败");
});

it("leaves returned trend buckets at their actual time positions", async () => {
  const loc = { ...location, scope: { ...scope, end: "2026-11-10T00:15:00Z" } };
  await render(<ProjectBoard {...props(apiFor(analysis([{ ...aggregate, timestamp: "2026-11-10T00:00:00Z" }, { ...aggregate, key: "b", timestamp: "2026-11-10T00:10:00Z" }])), loc)} />);
  const bars = [...host.querySelectorAll('svg[aria-label="测试与失败时间趋势"] .pt-chart-tests')];
  expect(Number(bars[1].getAttribute("x")) - Number(bars[0].getAttribute("x"))).toBe(256);
  expect(host.textContent).toContain("空白位置仅表示未返回时间格");
});


it("groups exception rankings with comparable bars and preserves the symptom drill", async () => {
  const rows = [{ ...aggregate, key: "a", error_code: "E1", stage_id: "7", software_id: "8", failed_sn: "99999999999999999999" }, { ...aggregate, key: "b", error_code: "E2", failed_sn: "50000000000000000000" }];
  const api = { productionAnalysis: vi.fn(async () => analysis(rows)) } as unknown as Api;
  const p = props(api, { ...location, view: "anomalies" });
  await render(<AnomaliesBoard {...p} />);
  expect([...host.querySelectorAll("h3")].map((h) => h.textContent)).toContain("异常排行");
  const bars = [...host.querySelectorAll<HTMLElement>(".pt-ranking-track > span")];
  expect(bars.map((b) => b.style.width)).toEqual(["100%", "50%"]);
  const button = [...host.querySelectorAll("button")].find((b) => b.textContent === "选择异常 E1")!;
  await act(async () => button.click());
  expect(p.go.mock.calls[0][0]).toMatchObject({ selectedError: true, scope: { ...scope, stage_id: "7", software_id: "8", error_code: "E1", status: "2" } });
});
