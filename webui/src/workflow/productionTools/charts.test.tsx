import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { MiniTrend, TrendChart } from "./charts";
import type { Aggregate, Analysis } from "./types";
import { localTime } from "./context";
const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
const scope = { start: "2026-11-10T00:00:00Z", end: "2026-11-10T00:05:00Z" };
const item: Aggregate = { key: "a", timestamp: scope.start, records: "99999999999999999999", fail_records: "0", failed_sn: "0", distinct_sn: "1", pass_records: "0", unknown_records: "99999999999999999999", first_time: null, last_time: null };
const data: Analysis = { source_namespace: "n", source_project_id: "1", view: "trend", captured_at: scope.end, filters: scope, items: [item, { ...item, key: "b", timestamp: "2026-11-10T00:05:00Z", records: "99999999999999999998" }], complete: true, truncation_reason: null, bucket_minutes: 5 };
afterEach(async () => { await act(async () => root.render(null)); });
it("retains the last exact decimal distinction in bounded bar geometry and keeps zero failure empty", async () => {
  await act(async () => root.render(<TrendChart data={data} scope={{ ...scope, end: "2026-11-10T00:10:00Z" }} onRange={vi.fn()} />));
  expect([...host.querySelectorAll(".pt-chart-tests")].map((r) => r.getAttribute("height"))).toEqual(["100", "99.99"]);
  expect([...host.querySelectorAll(".pt-chart-failures")].map((r) => r.getAttribute("height"))).toEqual(["0", "0"]);
  expect(host.textContent).toContain("99999999999999999998");
  expect(host.textContent).not.toContain("PASS");
  expect([...host.querySelectorAll("button")].every((b) => b.type === "button")).toBe(true);
});
it("keeps activity rows from different devices in named separate charts", async () => {
  await act(async () => root.render(<TrendChart data={{ ...data, view: "activity", items: [{ ...item, device: "PC01" }, { ...item, key: "b", device: "PC02", records: "1" }] }} scope={scope} onRange={vi.fn()} />));
  expect(host.querySelector('[aria-label="上位机 PC01 的活动趋势"]')).not.toBeNull();
  expect(host.querySelector('[aria-label="上位机 PC02 的活动趋势"]')).not.toBeNull();
  expect(host.querySelectorAll('svg[aria-label="测试与失败时间趋势"]').length).toBe(2);
});

it("keeps sparse mini-trend buckets distinct at their actual timestamps in both series", async () => {
  const timestamps = ["2026-11-10T00:00:00Z", "2026-11-10T00:05:00Z", "2026-11-10T01:00:00Z"];
  const items = timestamps.map((timestamp, i) => ({ ...item, key: String(i), timestamp, fail_records: String(i + 1) }));
  await act(async () => root.render(<MiniTrend items={items} complete={false} />));
  const svg = host.querySelector('svg[aria-label="项目近期测试与失败趋势"]')!;
  const chartWidth = Number(svg.getAttribute("viewBox")!.split(" ")[2]);
  for (const series of [".pt-chart-tests", ".pt-chart-failures"]) {
    const bars = [...svg.querySelectorAll(series)].map((bar) => ({ x: Number(bar.getAttribute("x")), width: Number(bar.getAttribute("width")) }));
    expect(bars).toHaveLength(3);
    for (const [i, bar] of bars.entries()) {
      expect(bar.width).toBeGreaterThan(0);
      expect(bar.x).toBeGreaterThanOrEqual(0);
      expect(bar.x + bar.width).toBeLessThanOrEqual(chartWidth);
      if (i) expect(bars[i - 1].x + bars[i - 1].width).toBeLessThan(bar.x);
    }
    expect((bars[2].x - bars[0].x) / (bars[1].x - bars[0].x)).toBeCloseTo(12);
  }
  expect([...svg.querySelectorAll("title")].map((title) => title.textContent)).toEqual(items.map((entry) => `${localTime(entry.timestamp)} · 测试 ${entry.records} · 失败 ${entry.fail_records} · 未知 ${entry.unknown_records}`));
  expect(host.textContent).toContain("部分读取；空白时段未知");
  expect(host.textContent).not.toContain("PASS");
});

it("uses one count scale so ten failures are one tenth of one hundred tests", async () => {
  await act(async () => root.render(<TrendChart data={{ ...data, items: [{ ...item, records: "100", fail_records: "10", unknown_records: "0" }] }} scope={scope} onRange={vi.fn()} />));
  const height = (selector: string) => Number(host.querySelector(selector)?.getAttribute("height"));
  expect(height(".pt-chart-failures") / height(".pt-chart-tests")).toBeCloseTo(0.1);
  expect(host.textContent).toContain("测试次数"); expect(host.textContent).toContain("其中失败");
  expect(host.textContent).not.toContain("含所有结果"); expect(host.textContent).not.toContain("各自最大值");
});
