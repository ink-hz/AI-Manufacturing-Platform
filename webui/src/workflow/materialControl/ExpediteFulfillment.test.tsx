import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { ExpeditePanel } from "./ExpeditePanel";
import { WorkflowError } from "../api";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined, host: HTMLDivElement;
afterEach(async () => { if (root) await act(async () => root!.unmount()); host?.remove(); root = undefined; });
const req: any = { id: "r1", material_id: "steel", unit: "kg", expedite_ids: ["e1"] };
const entry: any = { id: "e1", requirement_id: "old-r1", expedite_number: "急料甲", state: "open", reason: "急需装配", impact: "影响装配", progress: [] };
const check = (ready = false) => ({ can_fulfill: ready, project_version: 7, evaluated_at: "2026-11-12T08:00:00Z",
  required: "20", qualified: "20", usable_reserved: "20", line_received: ready ? "20" : "18",
  remaining_to_receive: ready ? "0" : "2", unit: "kg", blocking_reasons: ready ? [] : ["线边实收仍差2件"] });
const api = (ready = false) => ({
  object: vi.fn(async () => ({ value: { kind: "material_expedite", fulfillment_check: check(ready) } })),
  command: vi.fn(async (_id: string, body: any) => ({ project_id: "p1", project_version: 8,
    operation_id: body.operation_id, object_type: "material_expedite", object_id: "e1" })),
});
async function mount(a: any, extra: any = {}) {
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  const changed = vi.fn();
  await act(async () => root!.render(<ExpeditePanel p={{ api: a, project: { id: "p1", version: 7, allowed_actions: ["expedite.close", "expedite.progress"] },
    readOnly: false, onDirty: () => {}, onChanged: changed, onMaterialChanged: changed } as any}
    page={{ expedites: [entry] } as any} requirement={req} active begin={f => f()}
    resetRef={{ current: () => {} }} {...extra} />));
  return changed;
}
async function click(text: string) {
  const button = [...host.querySelectorAll("button")].find(x => x.textContent === text);
  expect(button).toBeDefined(); await act(async () => button!.click());
}
async function reason(value: string) {
  const input = host.querySelector<HTMLInputElement>('[aria-label="结束说明"]')!;
  expect(input).not.toBeNull();
  await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
}
const submit = () => [...host.querySelectorAll("button")].find(x => x.textContent === "确认结束")!;

it("shows separate current quantities and blocks a short receipt", async () => {
  const a = api(); await mount(a); await click("结束催料"); await reason("已经找到2件");
  expect(host.textContent).toContain("线边实收仍差2件");
  expect(host.textContent).toContain("相关批次合格量");
  expect(submit().disabled).toBe(true);
  expect(a.command).not.toHaveBeenCalled();
});

it("submits a verified preview while leaving the actual proof to the server", async () => {
  const a = api(true), changed = await mount(a);
  await click("结束催料"); await reason("当前实收已满足"); await click("确认结束");
  expect(a.command).toHaveBeenCalledWith("p1", expect.objectContaining({ action: "expedite.close", expedite_id: "e1", outcome: "fulfilled", reason: "当前实收已满足" }));
  expect(a.command.mock.calls[0][1]).not.toHaveProperty("fulfillment_proof");
  expect(changed).toHaveBeenCalledTimes(1);
});

it("keeps the reason and displays current server blockers after a changed condition", async () => {
  const a = api(true); a.command.mockRejectedValue(new WorkflowError(409, "EXPEDITE_NOT_FULFILLED", ["当前批次已被冻结"]));
  await mount(a); await click("结束催料"); await reason("核对记录"); await click("确认结束");
  expect(host.textContent).toContain("当前批次已被冻结");
  expect(host.querySelector<HTMLInputElement>('[aria-label="结束说明"]')!.value).toBe("核对记录");
  await click("重新核对");
  expect(host.querySelector<HTMLInputElement>('[aria-label="结束说明"]')!.value).toBe("核对记录");
  expect(a.object).toHaveBeenCalledTimes(2);
  expect(submit().disabled).toBe(false);
});

it("opens a compatible existing case from intent without creating another case", async () => {
  const a = api(); await mount(a, { intent: { requirementId: "r1", token: 1, expediteId: "e1" } });
  expect(host.querySelector('[aria-label="进展说明"]')).not.toBeNull();
  expect(host.textContent).toContain("急料甲");
  expect(a.command).not.toHaveBeenCalled();
});
