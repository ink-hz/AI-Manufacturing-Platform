import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { TrendChart } from "./charts";
import type { Aggregate, Analysis } from "./types";
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
