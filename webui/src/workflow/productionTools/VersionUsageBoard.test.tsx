import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { VersionUsageBoard } from "./VersionUsageBoard";
import type { Api } from "./boards";
import type { Aggregate, Analysis, ProductionPage, ProductionRow } from "./types";
import type { Location } from "./context";
const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
const scope = { start: "2026-11-10T00:02:59.123Z", end: "2026-11-10T00:08:31.456Z", sn: "SYNTHETIC-SN", error_code: "OLD", status: "1" as const };
const location: Location = { view: "catalog", projectId: "1", labels: {}, inherited: true, scope };
const item: Aggregate = { key: "a", stage_id: "7", stage_name: "合成阶段", software_id: "9007199254740993", software_name: "合成工具", software_version: "v2", config_log_id: "9007199254740994", config_version: "7", records: "9007199254740995", distinct_sn: "80", pass_records: "90", fail_records: "10", unknown_records: "0", failed_sn: "8", first_time: scope.start, last_time: scope.end };
const analysis = (items = [item], complete = true): Analysis => ({ source_namespace: "synthetic", source_project_id: "1", view: "versions", captured_at: scope.end, filters: scope, items, complete, truncation_reason: complete ? null : "PRIVATE-REASON" });
const page = (items: ProductionRow[] = []): ProductionPage => ({ snapshot_id: "synthetic", source_namespace: "synthetic", source_project_id: "1", source_kind: "config_versions", captured_at: scope.end, expires_at: scope.end, filters: {}, items, complete: false, truncation_reason: "limit", next_before_id: "88", redacted_fields: [], offset: 0, limit: 100, captured_count: items.length, has_more: true });
async function render(node: ReactNode) { await act(async () => root.render(node)); }
afterEach(async () => render(null));
async function setup(result = analysis(), overrides: Partial<Api> = {}) {
  const go = vi.fn();
  const api = { productionAnalysis: vi.fn(async (_p, q) => q.view === "devices" ? analysis([{ ...item, key: "device", device: "合成上位机" }]) : result), productionCatalog: vi.fn(async (_p, kind) => page(kind === "config_versions" ? [{ id: item.config_log_id, name: "合成配置", versions: "7", configid: "99" }] : [])), ...overrides } as unknown as Api;
  const show = async (loc = location, refresh = 0) => render(<VersionUsageBoard api={api} location={loc} go={go} inspect={vi.fn()} refresh={refresh} />);
  await show(); return { go, api, show };
}
async function click(label: string, index = 0) { const button = [...host.querySelectorAll("button")].filter(b => b.textContent === label)[index]; expect(button, label).toBeTruthy(); await act(async () => button.click()); }
it("shows exact counts and bounded optional names without technical prose or IDs", async () => {
  const { api } = await setup();
  expect([...host.querySelectorAll("thead th")].map(th => th.textContent)).toEqual(["生产阶段", "工具 / 版本", "配置 / 版本", "测试次数", "测试 SN", "失败 SN", "最近测试", "操作"]);
  expect(host.textContent).toContain("9007199254740995"); expect(host.textContent).toContain("合成配置");
  expect(host.textContent).not.toContain(item.software_id!); expect(host.textContent).not.toContain(item.config_log_id!);
  expect(host.textContent).not.toMatch(/统计说明|captured_at|PRIVATE-REASON|来源|读取完整|更新/);
  expect(api.productionCatalog).toHaveBeenCalledTimes(2);
  for (const call of vi.mocked(api.productionCatalog).mock.calls) expect(call[2]).toEqual({});
});
it("carries the entire combination and exact window through all tests, failures and machines", async () => {
  const { go, api } = await setup();
  const { error_code: _error, status: _status, ...allTests } = scope;
  const combo = { ...allTests, stage_id: "7", software_id: item.software_id, software_version: "v2", config_log_id: item.config_log_id, config_version: "7" };
  await click("查看测试"); expect(go.mock.calls[0][0]).toMatchObject({ view: "records", projectId: "1", scope: combo, selectedError: false });
  expect(go.mock.calls[0][0].scope.error_code).toBeUndefined(); expect(go.mock.calls[0][0].scope.status).toBeUndefined();
  await click("查看失败"); expect(go.mock.calls[1][0]).toMatchObject({ view: "records", projectId: "1", scope: { ...combo, status: "2" } });
  await click("查看上位机");
  expect(api.productionAnalysis).toHaveBeenLastCalledWith("1", { ...combo, error_code: scope.error_code, status: scope.status, view: "devices" }, expect.any(AbortSignal));
  expect(host.textContent).toContain("合成上位机");
  await click("进入上位机"); expect(go.mock.calls[2][0]).toMatchObject({ view: "device", projectId: "1", scope: { ...combo, error_code: scope.error_code, status: scope.status, device: "合成上位机" } });
});
it("keeps missing identities and versions distinct and removes stale error missing predicates", async () => {
  const missing = { ...item, key: "missing", stage_id: null, software_id: null, software_version: null, config_log_id: null, config_version: null };
  const { go, show } = await setup(analysis([missing, { ...missing, key: "other", config_log_id: "91" }]));
  await show({ ...location, scope: { ...scope, stage_id: "old", software_id: "old", software_version: "old", config_log_id: "old", config_version: "old", missing_fields: ["error_code", "device"] } });
  expect(host.querySelectorAll(".pt-version-table tbody tr")).toHaveLength(2);
  await click("查看测试"); const outgoing = go.mock.calls[0][0].scope;
  expect(outgoing).toMatchObject({ start: scope.start, end: scope.end, sn: scope.sn, missing_fields: ["stage_id", "software_id", "config_log_id", "software_version", "config_version", "device"] });
  for (const key of ["stage_id", "software_id", "software_version", "config_log_id", "config_version", "error_code", "status"]) expect(outgoing[key]).toBeUndefined();
  await click("查看失败", 1); expect(go.mock.calls[1][0].scope).toMatchObject({ config_log_id: "91", status: "2" });
});
it("distinguishes complete empty, incomplete unknown, failures and unavailable names", async () => {
  await setup(analysis([])); expect(host.textContent).toContain("本时段无版本使用记录");
  await setup(analysis([], false)); expect(host.textContent).toContain("部分结果未显示，请缩小范围"); expect(host.textContent).not.toContain("本时段无版本使用记录");
  await setup(analysis(), { productionCatalog: vi.fn(async () => { throw Error("private"); }) });
  expect(host.textContent).toContain("配置名称未取得"); expect(host.textContent).not.toContain("private");
  const bad = await setup(analysis(), { productionAnalysis: vi.fn(async () => { throw Error("private"); }) });
  expect(host.textContent).toContain("数据源暂不可用"); expect(host.textContent).not.toContain("本时段无版本使用记录");
  await click("重试版本使用"); expect(bad.api.productionAnalysis).toHaveBeenCalledTimes(2);
});
it("isolates late version and device responses after project or scope changes", async () => {
  let finishVersions!: (value: Analysis) => void, finishDevices!: (value: Analysis) => void;
  const apiRead = vi.fn((_p: string, q: any) => q.view === "devices" ? new Promise<Analysis>(r => { finishDevices = r; }) : _p === "late" ? new Promise<Analysis>(r => { finishVersions = r; }) : Promise.resolve(analysis()));
  const { show } = await setup(analysis(), { productionAnalysis: apiRead });
  await click("查看上位机");
  await show({ ...location, projectId: "late" }); expect(host.textContent).not.toContain("9007199254740995");
  await show({ ...location, projectId: "new", scope: { ...scope, end: "2026-11-10T00:10:00.001Z" } });
  await act(async () => { finishVersions(analysis([{ ...item, software_name: "旧项目版本" }])); finishDevices(analysis([{ ...item, device: "旧项目上位机" }])); });
  expect(host.textContent).not.toContain("旧项目版本"); expect(host.textContent).not.toContain("旧项目上位机");
  expect(apiRead).toHaveBeenLastCalledWith("new", expect.objectContaining({ end: "2026-11-10T00:10:00.001Z" }), expect.any(AbortSignal));
});
it("keeps selected device failures independent and unknown device results honest", async () => {
  const { api, show } = await setup(analysis(), { productionAnalysis: vi.fn(async (_p, q) => q.view === "devices" ? analysis([], false) : analysis()) });
  await click("查看上位机"); expect(host.textContent).toContain("部分上位机未显示，请缩小范围"); expect(host.textContent).not.toContain("该组合暂无上位机记录");
  vi.mocked(api.productionAnalysis).mockImplementation(async (_p, q) => { if (q.view === "devices") throw Error("private"); return analysis(); });
  await show(location, 1); expect(host.textContent).toContain("重试组合上位机"); expect(host.querySelectorAll(".pt-version-table tbody tr")).toHaveLength(1);
});
it("retains a failed refresh only for the same scope and labels the retained results", async () => {
  let failRefresh = false;
  const read = vi.fn(async () => { if (failRefresh) throw Error("private"); return analysis(); });
  const { show } = await setup(analysis(), { productionAnalysis: read });
  failRefresh = true; await show(location, 1);
  expect(host.textContent).toContain("9007199254740995"); expect(host.textContent).toContain("显示上次数据"); expect(host.textContent).toContain("重试版本使用");
  await show({ ...location, scope: { ...scope, software_version: "different" } }, 1);
  expect(host.textContent).not.toContain("9007199254740995"); expect(host.textContent).not.toContain("显示上次数据");
});
it("keeps optional late directory names isolated to their source project", async () => {
  const pending: ((value: ProductionPage) => void)[] = [];
  const directory = vi.fn((project: string, kind: string) => project === "1"
    ? new Promise<ProductionPage>(resolve => pending.push(resolve))
    : Promise.resolve(page(kind === "config_versions" ? [{ id: item.config_log_id, name: "新项目配置" }] : [])));
  const { show } = await setup(analysis(), { productionCatalog: directory as Api["productionCatalog"] });
  await show({ ...location, projectId: "2" });
  await act(async () => { for (const finish of pending) finish(page([{ id: item.config_log_id, name: "旧项目配置" }])); });
  expect(host.textContent).toContain("新项目配置"); expect(host.textContent).not.toContain("旧项目配置");
  expect(directory).toHaveBeenCalledTimes(4);
});

it("keeps a filtered version row and inline machine counts in the same captured scope", async () => {
  const filtered = { ...item, records: "2", distinct_sn: "2", failed_sn: "2" };
  const machineRead = vi.fn(async (_project: string, q: any) => analysis(q.view === "devices"
    ? [{ ...filtered, key: "device", device: "合成上位机", records: q.status === "2" && q.missing_fields?.includes("error_code") ? "2" : "10" }]
    : [filtered]));
  const { go, show } = await setup(analysis([filtered]), { productionAnalysis: machineRead });
  await show({ ...location, scope: { ...scope, error_code: undefined, status: "2", missing_fields: ["error_code"] } });
  await click("查看上位机");
  const query = machineRead.mock.calls.at(-1)![1];
  expect(query).toMatchObject({ start: scope.start, end: scope.end, status: "2", missing_fields: ["error_code"], stage_id: "7", software_id: item.software_id, software_version: "v2", config_log_id: item.config_log_id, config_version: "7", view: "devices" });
  expect(host.querySelector('[aria-label="组合上位机分布"] tbody td')?.textContent).toBe("2");
  expect([...host.querySelectorAll('[aria-label="组合上位机分布"] tbody td')].slice(0, 3).map(td => td.textContent)).toEqual(["2", "2", "2"]);
  await click("进入上位机");
  const { view: _view, ...capturedCombo } = query;
  expect(go.mock.calls[0][0].scope).toEqual({ ...capturedCombo, device: "合成上位机" });
  await click("查看测试"); expect(go.mock.calls[1][0].scope.status).toBeUndefined(); expect(go.mock.calls[1][0].scope.missing_fields).not.toContain("error_code");
  await click("查看失败"); expect(go.mock.calls[2][0].scope.status).toBe("2"); expect(go.mock.calls[2][0].scope.missing_fields).not.toContain("error_code");
});
