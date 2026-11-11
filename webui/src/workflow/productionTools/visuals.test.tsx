import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { Badge, boundedPercent, EmptyState, Metric, Panel, ResultBadge } from "./visuals";

const host = document.createElement("div");
document.body.append(host);
const root = createRoot(host);
async function render(children: ReactNode) {
  await act(async () => root.render(children));
}
afterEach(async () => { await act(async () => root.render(null)); });

it("keeps zero, unknown and huge counts distinct and names each metric", async () => {
  await render(<><Metric label="失败涉及 SN" value="0" tone="danger" /><Metric label="未取得" value={null} tone="danger" /><Metric label="测试记录" value="99999999999999999999" detail="本页完整统计" /></>);
  const metrics = [...host.querySelectorAll('[role="group"]')];
  expect(metrics.map((node) => node.getAttribute("aria-label"))).toEqual(["失败涉及 SN", "未取得", "测试记录"]);
  expect(metrics[0].textContent).toBe("失败涉及 SN 0");
  expect(metrics[0].getAttribute("data-tone")).toBe("neutral");
  expect(metrics[1].textContent).toContain("未取得 —");
  expect(metrics[2].textContent).toContain("99999999999999999999");
  expect(metrics[2].textContent).toContain("本页完整统计");
});

it("exposes metric drill actions as a named native button", async () => {
  const action = vi.fn();
  await render(<Metric label="测试记录" value="12" tone="info" onClick={action} />);
  const button = host.querySelector("button")!;
  expect(button.textContent).toBe("测试记录 12");
  expect(button.type).toBe("button");
  await act(async () => button.click());
  expect(action).toHaveBeenCalledTimes(1);
});

it("only marks source result codes 1 and 2 as known results", async () => {
  await render(<>{["1", "PASS", "2", "FAIL", null, "9", "", "0"].map((value, i) => <ResultBadge key={i} value={value} />)}</>);
  const badges = [...host.querySelectorAll("[data-tone]")];
  expect(badges.map((b) => b.getAttribute("data-tone"))).toEqual(["success", "neutral", "danger", "neutral", "neutral", "neutral", "neutral", "neutral"]);
  expect(badges[0].textContent).toContain("通过 PASS");
  expect(badges[2].textContent).toContain("失败 FAIL");
  expect(badges[1].textContent).toBe("结果未知（PASS）");
  expect(badges[3].textContent).toBe("结果未知（FAIL）");
  expect(badges[4].textContent).toContain("结果未知");
  expect(badges[5].textContent).toContain("结果未知（9）");
});

it("provides named panels and explicit empty states with semantic badges", async () => {
  await render(<Panel title="测试项目" eyebrow="本页统计" description="读取完整" actions={<button>查看项目</button>} className="example"><Badge tone="warning">部分读取</Badge><EmptyState title="当前范围无测试" description="没有事件不能推断设备离线。" /></Panel>);
  const panel = host.querySelector("section")!;
  expect(panel.getAttribute("aria-labelledby")).toBe(host.querySelector("h3")!.id);
  expect(host.querySelector("h3")!.textContent).toBe("测试项目");
  expect(host.querySelector('[data-tone="warning"]')!.textContent).toBe("部分读取");
  expect(host.textContent).toContain("没有事件不能推断设备离线。");
  expect(host.querySelector("button")!.textContent).toBe("查看项目");
});

it("bounds percentages using decimal integer arithmetic before numeric conversion", () => {
  expect(boundedPercent("0", "0")).toBe(0);
  expect(boundedPercent("0", "99999999999999999999")).toBe(0);
  expect(boundedPercent("99999999999999999999", "99999999999999999999")).toBe(100);
  expect(boundedPercent("99999999999999999998", "99999999999999999999")).toBeLessThan(100);
  expect(boundedPercent("99999999999999999999", "1")).toBe(100);
  expect(boundedPercent("1", "3")).toBeCloseTo(33.33, 2);
  for (const count of ["-1", "1.5", "1e3", "", " 1", "NaN"]) {
    expect(() => boundedPercent(count, "10")).toThrow(RangeError);
    expect(() => boundedPercent("1", count)).toThrow(RangeError);
  }
});
