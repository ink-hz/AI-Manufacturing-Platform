import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { OverviewBoard, type Api } from "./boards";
import type { Aggregate, Overview, OverviewItem } from "./types";
import type { Location } from "./context";
const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
const scope = { start: "2026-11-10T00:02:59.123Z", end: "2026-11-10T00:08:31.456Z" };
const location: Location = { view: "overview", projectId: "", labels: {}, inherited: true, scope };
const stats: Aggregate = { key: "a", records: "100", distinct_sn: "80", pass_records: "90", fail_records: "10", unknown_records: "0", failed_sn: "8", first_time: scope.start, last_time: scope.end };
const block = { state: "ready" as const, captured_at: scope.end, complete: true, error: null, truncation_reason: null };
const project = (id: string, name: string, statistics: Aggregate | null): OverviewItem => ({ id, name, state: statistics ? "ready" : "unavailable", statistics, trend: [{ ...stats, timestamp: scope.start }], latest_at: scope.end, blocks: { statistics: statistics ? block : { ...block, complete: false, state: "unavailable" }, trend: block, latest: block } });
const items = [project("1", "合成项目甲", stats), project("2", "合成项目乙", { ...stats, records: "0", distinct_sn: "0", fail_records: "0", failed_sn: "0" }), project("3", "合成项目丙", null)];
async function render(node: ReactNode) { await act(async () => root.render(node)); }
afterEach(async () => render(null));
async function overview(view: Location["view"] = "overview", rows = items, complete = false) {
  const data: Overview = { source_namespace: "synthetic", captured_at: scope.end, complete, has_more: false, next_before_id: null, items: rows };
  const go = vi.fn(); const api = { productionOverview: vi.fn(async () => data) } as unknown as Api;
  await render(<OverviewBoard api={api} location={{ ...location, view }} go={go} inspect={vi.fn()} refresh={0} />);
  return go;
}
async function toggle(summary: string) {
  const details = [...host.querySelectorAll("details")].find((d) => d.querySelector("summary")?.textContent === summary)!;
  expect(details).toBeTruthy();
  await act(async () => { details.open = !details.open; details.dispatchEvent(new Event("toggle")); });
}
it("keeps active and unavailable projects in a compact table and mounts known zeros on demand", async () => {
  const go = await overview();
  expect([...host.querySelectorAll("thead th")].map((h) => h.textContent)).toEqual(["项目", "测试次数", "测试 SN", "失败 SN", "失败次数", "最近测试", "操作"]);
  expect(host.textContent).toContain("合成项目甲"); expect(host.textContent).toContain("合成项目丙"); expect(host.textContent).not.toContain("合成项目乙");
  const unknown = [...host.querySelectorAll("tbody tr")].find((r) => r.textContent?.includes("合成项目丙"))!;
  expect([...unknown.querySelectorAll("td")].slice(0, 4).map((td) => td.textContent)).toEqual(["—", "—", "—", "—"]);
  expect(unknown.textContent).toContain("统计未取得"); expect(unknown.textContent).not.toContain("无观测失败");
  expect(host.querySelector("svg")).toBeNull(); expect(host.textContent).not.toContain("本次概览实际范围"); expect(host.textContent).not.toContain("测试记录不是成品数量");
  expect([...host.querySelectorAll('.pt-metrics [role="group"]')].map((m) => m.getAttribute("aria-label"))).toEqual(["有测试项目", "测试次数", "测试 SN", "失败 SN"]);
  const primary = host.querySelector<HTMLButtonElement>("tbody .pt-button-primary")!; expect(primary.textContent).toBe("查看失败");
  await act(async () => primary.click()); expect(go.mock.calls[0][0]).toMatchObject({ view: "anomalies", projectId: "1", scope, selectedError: false, selectedStage: false });
  await act(async () => host.querySelector<HTMLButtonElement>('tbody th button')!.click()); expect(go.mock.calls[1][0]).toMatchObject({ view: "project", projectId: "1", scope });
  await toggle("本时段无测试的项目（1）"); expect(host.textContent).toContain("合成项目乙");
  await toggle("本时段无测试的项目（1）"); expect(host.textContent).not.toContain("合成项目乙");
  expect(host.textContent).not.toContain("统计说明");
  expect(host.textContent).toContain("自动刷新");
});
it.each([["anomalies", "失败分析", "查看失败"], ["activity", "现场上位机", "查看上位机"], ["catalog", "版本使用", "查看版本"]] as const)("keeps the %s project chooser on its task", async (view, title, action) => {
  const go = await overview(view);
  expect(host.querySelector("h3")?.textContent).toBe(`${title} · 选择项目`); expect(host.textContent).not.toContain("运行总览");
  const button = host.querySelector<HTMLButtonElement>("tbody .pt-button-primary")!; expect(button.textContent).toBe(action);
  await act(async () => button.click()); expect(go.mock.calls[0][0]).toMatchObject({ view, projectId: "1", scope });
});
it("keeps incomplete zero statistics visible and marks them partial", async () => {
  const partial = { ...items[1], blocks: { ...items[1].blocks, statistics: { ...block, state: "partial" as const, complete: false } } };
  await overview("overview", [partial], false);
  expect(host.querySelector("tbody")?.textContent).toContain("合成项目乙"); expect(host.textContent).toContain("统计未完整");
  expect(host.textContent).not.toContain("本时段无测试的项目"); expect(host.textContent).not.toContain("当前无观测失败");
});
it("removes successful coverage metadata and statistics help", async () => {
  await overview("overview", [items[0]], true);
  expect(host.querySelector(".pt-updated")).toBeNull();
  expect(host.textContent).not.toContain("统计说明");
  expect(host.textContent).not.toContain("本次范围读取完整"); expect(host.textContent).not.toContain("本页已读取");
});
it("keeps an empty incomplete overview unknown rather than claiming zero tests", async () => {
  await overview("overview", [], false);
  expect([...host.querySelectorAll('.pt-metrics [role="group"]')].every((metric) => metric.textContent?.includes("—"))).toBe(true);
  expect(host.textContent).not.toContain("源项目目录暂无项目");
});
it("remounts a returning zero-project section closed without hidden row content", async () => {
  await overview(); await toggle("本时段无测试的项目（1）");
  await overview("overview", [items[0]], true); await overview();
  expect(host.querySelector<HTMLDetailsElement>(".pt-zero-projects")?.open).toBe(false);
  expect(host.textContent).not.toContain("合成项目乙");
});
