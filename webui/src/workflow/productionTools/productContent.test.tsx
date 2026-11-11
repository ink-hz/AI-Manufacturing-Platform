import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { WorkflowError } from "../api";
import { Coverage, ReadBlock, type Api } from "./boards";
import { CatalogPage, Compare, EventSidebar, HistoryPage, Parameters, RecordTable } from "./details";
import { InvestigationPanel, type InvestigationController } from "./investigations";
import { errorText, localTime, type Location } from "./context";
import type { CatalogKind, Investigation, ProductionPage, ViewedEvent } from "./types";
const host = document.createElement("div"); document.body.append(host); const root = createRoot(host);
const scope = { start: "2026-11-10T00:00:00Z", end: "2026-11-10T08:00:00Z" };
const location: Location = { view: "catalog", catalog: "software", projectId: "7", labels: { project: "合成项目" }, inherited: true, scope };
const event: ViewedEvent = { snapshot_id: "PRIVATE-SNAPSHOT", offset: 50, captured_at: "2026-11-11T08:00:00Z", projectId: "7", kind: "production", row: { timestamp: scope.start, sn: "SYNTHETIC-SN", status: "2", measurement: "99999999999999999999", projuectid: "PRIVATE-PROJECT", del: 0 } };
const page: ProductionPage = { ...event, source_namespace: "PRIVATE-NAMESPACE", source_project_id: "7", source_kind: "production", expires_at: scope.end, filters: scope, items: [event.row], captured_count: 51, limit: 50, has_more: true, next_before_id: null, truncation_reason: null, complete: true, redacted_fields: [] };
const selection = { snapshot_id: event.snapshot_id, offset: 50, fingerprint: "PRIVATE-FINGERPRINT", descriptor: event.row, source_kind: "production" as const };
const capture = { state: "partial", captured_at: event.captured_at, complete: false, counts: null, filters: scope };
const draft: Investigation = { id: "meaningful-draft-reference", source_namespace: "PRIVATE-NAMESPACE", source_project_id: "7", owner_id: "synthetic-owner", version: 5, created_at: scope.start, updated_at: event.captured_at, expires_at: scope.end, context: { ...scope, view: "catalog" }, primary: selection, comparison: null, logs: [], note: "检查合成参数", impact: { state: "partial", captured_at: event.captured_at, baseline: capture, selected: capture, failure: capture, failure_records: { numerator: "1", denominator: null }, failed_involved_sn: { numerator: "1", denominator: null } } };
const controller = (extra = {}) => ({ draft, handoff: null, state: "已保存 2026-11-11 · 修订 5", note: draft.note, dirty: false, error: "", canStart: true, list: [], resolved: null, conflict: null, browsingOtherScope: false, logBusy: false, start: vi.fn(), generate: vi.fn(), restore: vi.fn(), setNote: vi.fn(), resolve: vi.fn(), ...extra }) as unknown as InvestigationController;
const props = { location, go: vi.fn(), inspect: vi.fn(), refresh: 0 };
async function render(node: ReactNode) { await act(async () => root.render(node)); }
afterEach(async () => render(null));
const clean = () => expect(host.textContent).not.toMatch(/统计说明|PRIVATE-|捕获|读取时间|本次复查读取|行号|原子快照|namespace|fingerprint|snapshot_id|projuectid|schema|协议|del：|修订 5/);
it("renders no successful coverage metadata and keeps incomplete data actionable without reason codes", async () => {
  await render(<Coverage data={page} />); expect(host.childElementCount).toBe(0);
  await render(<Coverage data={{ ...page, complete: false, truncation_reason: "PRIVATE-REASON" }} />);
  expect(host.textContent).toContain("请缩小范围"); clean();
});
it("keeps loading, stale data, and retry actions short and visible", async () => {
  const retry = vi.fn();
  await render(<ReadBlock label="测试记录" state={{ data: page, loading: false, error: "数据源暂不可用", retry }}>{p => <strong>{p.items.length} 条记录</strong>}</ReadBlock>);
  expect(host.textContent).toContain("显示上次数据"); expect(host.textContent).toContain("数据源暂不可用");
  await act(async () => host.querySelector("button")!.click()); expect(retry).toHaveBeenCalledOnce(); clean();
});
it("records and expanded raw business parameters omit provenance while exact event actions remain", async () => {
  const inspect = vi.fn(), go = vi.fn();
  await render(<RecordTable page={page} location={location} go={go} inspect={inspect} />); clean();
  expect(host.textContent).toContain(localTime(event.row.timestamp)); expect(host.textContent).not.toContain("查看测试 51");
  await act(async () => host.querySelector<HTMLButtonElement>("tbody button")!.click()); expect(inspect).toHaveBeenCalledWith(event);
  await act(async () => [...host.querySelectorAll("button")].find(b => b.textContent === "下一页")!.click());
  expect(go.mock.calls[0][0].cursor).toEqual({ id: event.snapshot_id, offset: 100, limit: 50, kind: "production" });
  await render(<Parameters row={event.row} />); clean(); expect(host.textContent).toContain("99999999999999999999");
  expect(host.querySelector("summary")?.textContent).toBe("原始记录");
});
it("drawer and comparison focus on business facts and measurements", async () => {
  await render(<EventSidebar api={{} as Api} event={event} location={location} go={vi.fn()} close={vi.fn()} investigation={draft} readOnly={false} onPrimary={vi.fn()} onComparison={vi.fn()} onLog={vi.fn()} logBusy={false} onEvidenceScope={vi.fn()} />); clean();
  expect(host.textContent).toContain("设为调查对象"); expect(host.textContent).toContain(localTime(scope.start));
  await render(<Compare primary={event} comparison={{ ...event, row: { ...event.row, measurement: "10" } }} />); clean();
  expect(host.textContent).toContain("99999999999999999999"); expect(host.textContent).toContain("10");
});
it("history keeps its actual search bounds without query lectures", async () => {
  const api = { productionObservations: vi.fn(async () => page) } as unknown as Api;
  await render(<HistoryPage {...props} location={{ ...location, view: "history", historySN: "SYNTHETIC-SN" }} api={api} />); clean();
  expect(host.textContent).toContain(localTime(scope.start)); expect(host.textContent).not.toMatch(/只继承|原症状保留在返回路径|原问题时段仍保留/);
  expect(api.productionObservations).toHaveBeenCalledWith("7", { ...scope, sn: "SYNTHETIC-SN", kind: "stopover" }, expect.any(AbortSignal));
});
it.each(["software", "software_versions", "configs", "config_versions", "review_orders"] as CatalogKind[])("%s directory allows only useful business fields", async kind => {
  const api = { productionCatalog: vi.fn(async () => ({ ...page, items: [{ id: "PRIVATE-ID", name: "合成工具", versions: "v1", details: "合成版本说明", username: "合成作者", audituser: "合成审核人", state: 4, projuectid: "PRIVATE-PROJECT", softwareid: "PRIVATE-TOOL", url1: "PRIVATE-URL", unknown_column: "PRIVATE-COLUMN" }] })) } as unknown as Api;
  await render(<CatalogPage {...props} location={{ ...location, catalog: kind }} api={api} />); clean();
  expect(host.textContent).toContain("合成版本说明"); expect(host.textContent).toContain("合成作者");
  if (kind === "configs" || kind === "software") expect(host.textContent).not.toContain("审核状态");
  else { expect(host.textContent).toContain("当前审核状态"); expect(host.textContent).toContain("已准出"); }
});
it.each([["software_versions", -1, "测试中"], ["config_versions", 2, "待准出"], ["review_orders", 5, "强制准出"], ["software_versions", 5, "未知"], ["review_orders", -1, "未知"], ["config_versions", "PRIVATE-ENUM", "未知"], ["software_versions", "__proto__", "未知"], ["review_orders", "toString", "未知"]] as const)("%s review state %s stays object specific", async (kind, state, expected) => {
  const api = { productionCatalog: vi.fn(async () => ({ ...page, items: [{ name: "合成版本", state }] })) } as unknown as Api;
  await render(<CatalogPage {...props} location={{ ...location, catalog: kind }} api={api} />); clean(); expect(host.textContent).toContain(expected);
});
it("investigation retains references, uncertainty, scope actions and errors without internal traces", async () => {
  const c = controller({ browsingOtherScope: true, error: "保存失败，请重试", dirty: true, applyBrowsingScope: vi.fn(), returnToSaved: vi.fn(), newRange: vi.fn(), flush: vi.fn() });
  await render(<InvestigationPanel controller={c} readOnly={false} onCompare={vi.fn()} onCandidate={vi.fn()} />); clean();
  expect(host.textContent).toContain(draft.id); expect(host.textContent).toContain(localTime(scope.start));
  for (const text of ["部分统计未取得", "保存失败，请重试", "返回原调查范围", "重试保存", "读取交接"]) expect(host.textContent).toContain(text);
  expect(host.querySelector('[aria-label="日志引用"]')).toBeNull(); expect(host.textContent).not.toContain("当前项目暂无其他个人草稿");
  await act(async () => [...host.querySelectorAll("button")].find(b => b.textContent === "返回原调查范围")!.click()); expect(c.returnToSaved).toHaveBeenCalledOnce();
});
it("formats business event times without a repeated zone suffix and retains milliseconds", () => {
  const shown = localTime("2026-11-10T00:00:00.123Z");
  expect(shown).toContain(".123");
  expect(shown).not.toMatch(/GMT|UTC/);
});
it("omits empty comparison sections and uses available investigation business names", async () => {
  await render(<InvestigationPanel controller={controller({ draft: { ...draft, context: { ...draft.context, software_id: "8" } } })} projectName="合成项目" names={{ projectId: "7", labels: { "software_id:8": "合成工具" } }} readOnly={false} onCompare={vi.fn()} onCandidate={vi.fn()} />);
  expect(host.querySelector('[aria-label="对照事件"]')).toBeNull();
  expect(host.textContent).toContain("合成项目"); expect(host.textContent).toContain("工具：合成工具");
});

it("capability errors offer the next action without configuration lectures", () => {
  const message = errorText(new WorkflowError(503, "PRODUCTION_CAPABILITY_UNAVAILABLE"));
  expect(message).toContain("请联系管理员"); expect(message).not.toMatch(/可用性|连通状态/);
});
it("keeps an unknown log verification state actionable", async () => {
  const c = controller({ draft: { ...draft, logs: [{ source_log_id: "88", descriptor: { csn: "SYNTHETIC-CSN" }, state: "unverified" }] }, resolved: { logs: [{ source_log_id: "88", state: "constructor" }] } });
  await render(<InvestigationPanel controller={c} readOnly={false} onCompare={vi.fn()} onCandidate={vi.fn()} />);
  expect(host.querySelector(".pt-log-reference")?.textContent).toMatch(/项目与时间\s*·\s*待核对/);
});

const ownedNames = { projectId: "7", labels: { "stage_id:71717171": "合成阶段", "software_id:81818181": "合成工具", "config_log_id:91919191": "合成配置", "software_id:82828282": "合成工具" } };
const factRow = { timestamp: "2026-11-10T00:00:00.123Z", sn: "SYNTHETIC-SN", status: "2", workstagesid: "71717171", softwareid: "81818181", configlogsid: "91919191", measurement: "99999999999999999999" };
const factEvent = { ...event, row: factRow };
const comparisonRow = (label: string) => [...host.querySelectorAll('tbody tr')].find(row => row.querySelector("th")?.textContent === label)!;
it("comparison resolves owned business names while comparing exact identities and formatting facts", async () => {
  await render(<Compare primary={factEvent} comparison={{ ...factEvent, row: { ...factRow, softwareid: "82828282", status: "1", measurement: "10" } }} names={ownedNames} />);
  for (const label of ["阶段", "工具", "配置"]) expect(comparisonRow(label).textContent).not.toMatch(/71717171|81818181|82828282|91919191/);
  const tool = comparisonRow("工具"); expect(tool.textContent).toContain("不同");
  expect([...tool.querySelectorAll("td")].slice(1).map(td => td.textContent)).toEqual(["合成工具", "合成工具"]);
  expect(comparisonRow("事件时间").textContent).toContain(localTime(factRow.timestamp));
  expect(comparisonRow("结果").textContent).toContain("失败 FAIL");
  expect(comparisonRow("measurement").textContent).toContain("99999999999999999999");
});
it("comparison translates own name aliases and never borrows another project's names", async () => {
  const named = { ...factEvent, projectId: "other-project", row: { ...factRow, softwarename: "记录自带工具", workstagesname: "记录自带阶段", configlogsname: "记录自带配置" } };
  await render(<Compare primary={named} comparison={{ ...factEvent, projectId: "other-project" }} names={ownedNames} />);
  expect(host.textContent).not.toMatch(/softwarename|workstagesname|configlogsname|71717171|81818181|91919191/);
  for (const [label, own] of [["工具", "记录自带工具"], ["阶段", "记录自带阶段"], ["配置", "记录自带配置"]]) {
    const cells = comparisonRow(label).querySelectorAll("td");
    expect(cells[1].textContent).toBe(own); expect(cells[2].textContent).toContain("名称暂不可用");
  }
  expect(comparisonRow("工具名称").textContent).toContain("记录自带工具");
});
it.each([true, false])("saved evidence and copied summary use own names or unavailable fallback with owned metadata %s", async available => {
  const descriptor = { ...factRow, ...(available ? { softwarename: "记录自带工具", workstagesname: "记录自带阶段", configlogsname: "记录自带配置" } : {}) };
  const handoff = { ...draft, context: { ...draft.context, stage_id: factRow.workstagesid, software_id: factRow.softwareid, config_log_id: factRow.configlogsid, status: "2" }, primary: { ...selection, descriptor } };
  const writeText = vi.fn(async (_text: string) => {});
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
  await render(<InvestigationPanel controller={controller({ handoff, browsingOtherScope: true })} names={available ? ownedNames : { projectId: "other-project", labels: ownedNames.labels }} readOnly={false} onCompare={vi.fn()} onCandidate={vi.fn()} />);
  const details = host.querySelector<HTMLDetailsElement>('[aria-label="主要事件"] details')!;
  await act(async () => { details.open = true; details.dispatchEvent(new Event("toggle")); });
  expect(details.textContent).not.toMatch(/71717171|81818181|91919191|softwarename|workstagesname|configlogsname/);
  expect(details.textContent).toContain(available ? "记录自带工具" : "名称暂不可用");
  expect(details.textContent).toContain(localTime(factRow.timestamp));
  const savedScope = host.querySelector('[aria-label="调查范围"]')!;
  expect(savedScope.textContent).toContain("结果：失败 FAIL"); expect(savedScope.textContent).not.toMatch(/71717171|81818181|91919191/);
  await act(async () => [...host.querySelectorAll("button")].find(b => b.textContent === "复制交接摘要与恢复链接")!.click());
  const copied = writeText.mock.calls[0][0];
  expect(copied).not.toMatch(/71717171|81818181|91919191|softwarename|workstagesname|configlogsname/);
  expect(copied).toContain("结果：失败 FAIL"); expect(copied).toContain("结果=失败 FAIL"); expect(copied).toContain(localTime(factRow.timestamp));
  expect(copied).toContain(available ? "记录自带工具" : "名称暂不可用");
});
