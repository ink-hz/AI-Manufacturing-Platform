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
  const p = props(apiFor(analysis([]), overview));
  await render(<OverviewBoard {...p} />);
  expect(host.querySelector('[role="group"][aria-label="测试次数"]')?.textContent).toContain("99999999999999999999");
  expect(host.querySelector('[role="group"][aria-label="测试 SN"]')?.textContent).toContain("9007199254740993");
  expect(host.textContent).toContain("本页可用统计"); expect(host.textContent).toContain("部分结果未显示，请缩小范围"); expect(host.textContent).toContain("统计未取得"); expect(host.textContent).toContain("还有更多项目");
  const projectEntry = [...host.querySelectorAll("button")].find((button) => button.textContent === "项目 A")!;
  expect(projectEntry.classList.contains("pt-project-name")).toBe(true);
  await act(async () => projectEntry.click());
  expect(p.go.mock.calls[0][0]).toMatchObject({ view: "project", projectId: "1", labels: { project: "项目 A" }, scope, inherited: true });
});
it("keeps zero failures neutral and missing statistics visibly unknown", async () => {
  await render(<><Counts item={{ ...aggregate, fail_records: "0", failed_sn: "0" }} /><Counts item={null} /></>);
  expect(host.querySelector('[aria-label="失败 SN"]')?.getAttribute("data-tone")).toBe("neutral"); expect(host.textContent).toContain("失败 SN 0"); expect(host.textContent).toContain("统计未取得");
});
it("draws test and failure series with exact labels and reachable clamped drills", async () => {
  const data = analysis([{ ...aggregate, timestamp: "2026-11-10T00:00:00Z" }, { ...aggregate, key: "b", records: "50000000000000000000", timestamp: "2026-11-10T00:05:00Z" }], false); const p = props(apiFor(data)); await render(<ProjectBoard {...p} />);
  expect(host.querySelector('svg[aria-label="测试与失败时间趋势"]')).not.toBeNull();
  const trend = host.querySelector('[aria-label="测试趋势"]')!; expect(trend.textContent).toContain("测试次数"); expect(trend.textContent).toContain("其中失败"); expect(trend.textContent).toContain("99999999999999999999");
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
  expect(host.querySelectorAll(".pt-activity-map thead th").length).toBe(97); expect(host.textContent).toContain("已显示时段"); expect(host.textContent).toContain("更多时段请缩小范围"); expect(host.querySelector(".pt-activity-map thead th:nth-child(2)")?.getAttribute("title")).toBeTruthy(); expect(host.querySelector(".pt-activity-map thead th:nth-child(2)")?.getAttribute("aria-label")).toBe(host.querySelector(".pt-activity-map thead th:nth-child(2)")?.getAttribute("title"));
});

it("does not present an all-unavailable overview as zero tests", async () => {
  const unavailable = { ...block, state: "unavailable" as const, complete: false };
  const overview: Overview = { source_namespace: "native", captured_at: scope.end, complete: false, has_more: false, next_before_id: null, items: [{ id: "1", name: "项目 A", state: "unavailable", statistics: null, trend: [], latest_at: null, blocks: { statistics: unavailable, trend: unavailable, latest: unavailable } }] };
  await render(<OverviewBoard {...props(apiFor(analysis([]), overview))} />);
  expect(host.querySelector('[role="group"][aria-label="测试次数"]')?.textContent).toContain("—");
  expect(host.textContent).not.toContain("测试 SN 0");
  expect(host.textContent).not.toContain("当前无观测失败");
});

it("leaves returned trend buckets at their actual time positions", async () => {
  const loc = { ...location, scope: { ...scope, end: "2026-11-10T00:15:00Z" } };
  await render(<ProjectBoard {...props(apiFor(analysis([{ ...aggregate, timestamp: "2026-11-10T00:00:00Z" }, { ...aggregate, key: "b", timestamp: "2026-11-10T00:10:00Z" }])), loc)} />);
  const bars = [...host.querySelectorAll('svg[aria-label="测试与失败时间趋势"] .pt-chart-tests')];
  expect(Number(bars[1].getAttribute("x")) - Number(bars[0].getAttribute("x"))).toBe(256);
  expect(host.textContent).toContain("空白：未知");
});


it("groups exception rankings in compact semantic rows and preserves the symptom drill", async () => {
  const rows = [{ ...aggregate, key: "a", error_code: "E1", stage_id: "7", software_id: "8", failed_sn: "99999999999999999999" }, { ...aggregate, key: "b", error_code: "E2", failed_sn: "50000000000000000000" }];
  const api = { productionAnalysis: vi.fn(async () => analysis(rows)) } as unknown as Api;
  const p = props(api, { ...location, view: "anomalies" });
  await render(<AnomaliesBoard {...p} />);
  expect([...host.querySelectorAll("h3")].map((h) => h.textContent)).toContain("异常排行");
  const table = host.querySelector('[aria-label="症状排行"]')!;
  expect(table).not.toBeNull();
  expect([...table.querySelectorAll("thead th")].map(h => h.textContent)).toEqual(["错误", "工具 / 环节", "失败 SN", "失败次数", "适用样本"]);
  expect(table.querySelectorAll("tbody tr")).toHaveLength(2);
  expect(table.querySelectorAll('[role="group"]')).toHaveLength(0);
  expect(table.querySelector("tbody tr")?.textContent).toContain("99999999999999999999");
  const button = [...host.querySelectorAll("button")].find((b) => b.textContent === "选择异常 E1")!;
  await act(async () => button.click());
  expect(p.go.mock.calls[0][0]).toMatchObject({ selectedError: true, scope: { ...scope, stage_id: "7", software_id: "8", error_code: "E1", status: "2" } });
});

it("shows actual reread count changes concisely without repeating read provenance", async () => {
  const loc = { ...location, parentRead: { captured_at: scope.start, records: "100", distinct_sn: "10", scope } };
  await render(<ProjectBoard {...props(apiFor(analysis([{ ...aggregate, timestamp: scope.start }])), loc)} />);
  expect(host.textContent).toContain("测试次数 100 → 99999999999999999999");
  expect(host.textContent).not.toContain("父视图读取"); expect(host.textContent).not.toContain("各次读取不是跨源原子快照");
  const trend = host.querySelector('[aria-label="测试趋势"]')!;
  expect(trend.querySelectorAll(".pt-updated time")).toHaveLength(0);
});


it("keeps same-code tool identities and missing-error groups separate with only supplied denominators", async () => {
  const rows = [
    { ...aggregate, key: "tool-a", error_code: "E1", stage_id: "7", software_id: "8", software_name: "工具甲", denominator_records: "99999999999999999999", failed_sn: "9007199254740994" },
    { ...aggregate, key: "tool-b", error_code: "E1", stage_id: "17", software_id: "18", software_name: "工具乙", failed_sn: "9007199254740993" },
    { ...aggregate, key: "missing", error_code: null, stage_id: null, software_id: null, failed_sn: "1" },
  ];
  const api = { productionAnalysis: vi.fn(async () => analysis(rows)) } as unknown as Api;
  const p = props(api, { ...location, view: "anomalies" }); await render(<AnomaliesBoard {...p} />);
  const table = host.querySelector('[aria-label="症状排行"]')!;
  expect(table).not.toBeNull();
  const ranked = [...table.querySelectorAll("tbody tr")];
  expect(ranked).toHaveLength(3);
  expect(ranked.map(row => row.querySelector("td:last-child")?.textContent)).toEqual(["99999999999999999999", "—", "—"]);
  await act(async () => ranked[1].querySelector<HTMLButtonElement>("button")!.click());
  expect(p.go.mock.calls[0][0].scope).toMatchObject({ stage_id: "17", software_id: "18", error_code: "E1", status: "2" });
  await act(async () => ranked[2].querySelector<HTMLButtonElement>("button")!.click());
  expect(p.go.mock.calls[1][0].scope).toMatchObject({ missing_fields: ["stage_id", "software_id", "error_code"], status: "2" });
});

it("mounts selected symptom trend only after its action and preserves selected and all-test scopes", async () => {
  const selected: Location = { ...location, view: "anomalies", selectedError: true, scope: { ...scope, stage_id: "7", software_id: "8", error_code: "E1", status: "2" } };
  const api = { productionAnalysis: vi.fn(async () => analysis([{ ...aggregate, device: null, timestamp: "2026-11-10T00:00:00Z" }])), productionStatus: vi.fn(async () => ({ configured: true, capabilities: { production: { available: true } } })), productionObservations: vi.fn(async () => ({ items: [], redacted_fields: [], complete: true, captured_at: scope.end })) } as unknown as Api;
  const p = props(api, selected); await render(<AnomaliesBoard {...p} />);
  const requests = () => vi.mocked(api.productionAnalysis).mock.calls.map(([, q]) => q);
  expect(requests().find(q => q.view === "errors")).toEqual({ ...scope, stage_id: "7", software_id: "8", missing_fields: undefined, view: "errors" });
  expect(requests().find(q => q.view === "devices")).toEqual({ ...selected.scope, view: "devices" });
  expect(host.querySelector('[aria-label="症状影响分布"] table')).not.toBeNull();
  expect(host.querySelector('svg')).toBeNull(); expect(requests().some(q => q.view === "trend")).toBe(false);
  const click = async (label: string) => act(async () => [...host.querySelectorAll("button")].find(b => b.textContent === label)!.click());
  await click("查看趋势"); expect(requests().find(q => q.view === "trend")).toEqual({ ...selected.scope, view: "trend" });
  expect(host.querySelector('svg')).not.toBeNull();
  await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="所选异常趋势"] .pt-chart-buckets button')!.click());
  expect(p.go.mock.calls.at(-1)![0].scope).toEqual({ ...selected.scope, start: "2026-11-10T00:02:00.000Z", end: "2026-11-10T00:05:00.000Z" });
  await click("查看失败记录"); expect(p.go.mock.calls.at(-1)![0]).toMatchObject({ view: "records", scope: selected.scope });
  await click("查看全部测试"); expect(p.go.mock.calls.at(-1)![0]).toMatchObject({ view: "records", scope: { ...scope, stage_id: "7", software_id: "8" }, selectedError: false });
  await click("查看上位机 源未提供"); expect(p.go.mock.calls.at(-1)![0].scope).toEqual({ ...selected.scope, missing_fields: ["device"] });
});

it("puts a compact machine table before activity and keeps device investigation actions scoped", async () => {
  const p = props(apiFor(analysis([{ ...aggregate, device: "PC01", timestamp: "2026-11-10T00:00:00Z" }])), { ...location, view: "activity" });
  await render(<ActivityBoard {...p} />);
  expect(host.querySelector("h3")?.textContent).toBe("现场上位机");
  const table = host.querySelector('[aria-label="上位机名单"]')!;
  expect(table).not.toBeNull();
  expect([...table.querySelectorAll("thead th")].map(h => h.textContent)).toEqual(["上位机", "测试 SN", "失败 SN", "测试次数", "最近测试", "操作"]);
  expect(table.querySelectorAll('[role="group"]')).toHaveLength(0);
  expect(table.compareDocumentPosition(host.querySelector(".pt-activity-map")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  await act(async () => table.querySelector<HTMLButtonElement>("button")!.click());
  expect(p.go.mock.calls[0][0]).toMatchObject({ view: "device", scope: { ...scope, device: "PC01" } });
  await render(<ActivityBoard {...p} location={{ ...location, view: "device", scope: { ...scope, device: "PC01" } }} />);
  expect(host.querySelector('[aria-label="上位机症状"] table')).not.toBeNull();
  expect(host.querySelector('[aria-label="上位机版本"] table')).not.toBeNull();
  expect([...host.querySelectorAll("button")].some(b => b.textContent === "查看该时段测试")).toBe(true);
});

it("highlights a missing-dimension symptom only for explicit missing predicates", async () => {
  const rows = [
    { ...aggregate, key: "missing", error_code: "E1", stage_id: null, software_id: null },
    { ...aggregate, key: "known", error_code: "E1", stage_id: "7", software_id: "8" },
  ];
  const api = { productionAnalysis: vi.fn(async () => analysis(rows)), productionStatus: vi.fn(async () => ({ configured: true, capabilities: { production: { available: true } } })), productionObservations: vi.fn(async () => ({ items: [], redacted_fields: [], complete: true, captured_at: scope.end })) } as unknown as Api;
  const broad: Location = { ...location, view: "anomalies", selectedError: true, scope: { ...scope, error_code: "E1", status: "2" } };
  await render(<AnomaliesBoard {...props(api, broad)} />);
  const highlighted = () => [...host.querySelectorAll('[aria-label="症状排行"] tbody tr[aria-selected="true"]')];
  expect(highlighted()).toHaveLength(0);
  const explicit: Location = { ...broad, scope: { ...broad.scope, missing_fields: ["stage_id", "software_id"] } };
  await render(<AnomaliesBoard {...props(api, explicit)} />);
  expect(highlighted()).toHaveLength(1);
  expect(highlighted()[0].querySelector("button")?.textContent).toBe("选择异常 E1");
  expect(highlighted()[0]).toBe(host.querySelector('[aria-label="症状排行"] tbody tr'));
  await render(<AnomaliesBoard {...props(api, { ...broad, scope: { ...broad.scope, stage_id: "7", software_id: "8" } })} />);
  expect(highlighted()).toHaveLength(1);
  expect(highlighted()[0]).toBe(host.querySelector('[aria-label="症状排行"] tbody tr:nth-child(2)'));
});
